"""RAG pipeline: ingest -> retrieve -> generate, with citations and timings."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from .chunking import load_corpus
from .config import settings
from .embeddings import Embedder, get_embedder
from .generator import Generator, get_generator
from .retriever import HybridRetriever
from .store import RetrievedChunk, VectorStore


@dataclass
class Citation:
    index: int
    chunk_id: str
    title: str
    source: str
    heading: str
    score: float
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass
class RAGAnswer:
    question: str
    answer: str
    citations: list[Citation]
    contexts: list[dict[str, Any]]
    strategy: str
    timings: dict[str, float]
    generator: str
    embedding: str
    grounded: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "contexts": self.contexts,
            "strategy": self.strategy,
            "timings": self.timings,
            "generator": self.generator,
            "embedding": self.embedding,
            "grounded": self.grounded,
        }


class RAGPipeline:
    def __init__(
        self,
        store: VectorStore | None = None,
        *,
        embedder: Embedder | None = None,
        generator: Generator | None = None,
    ) -> None:
        self.embedder = embedder or get_embedder()
        self.generator = generator or get_generator()
        self.store = store or VectorStore(dim=self.embedder.dim, embedding_name=self.embedder.name)
        self.retriever = HybridRetriever(self.store, self.embedder)

    # ------------------------------------------------------------------ ingest
    def ingest(self, corpus_dir: Path | None = None, *, persist: bool = True) -> dict[str, Any]:
        started = time.perf_counter()
        documents, chunks = load_corpus(corpus_dir)
        vectors = self.embedder.embed([chunk.text for chunk in chunks])

        self.store = VectorStore(dim=self.embedder.dim, embedding_name=self.embedder.name)
        self.store.add(chunks, vectors)
        self.retriever = HybridRetriever(self.store, self.embedder)  # reset BM25 cache

        if persist:
            self.store.save(directory_override=settings.index_dir)

        return {
            "documents": len(documents),
            "chunks": len(chunks),
            "dim": self.store.dim,
            "embedding": self.embedder.name,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "per_document": self.store.by_source(),
        }

    @classmethod
    def from_disk(cls, *, auto_ingest: bool = True) -> "RAGPipeline":
        """Load a persisted index, ingesting the corpus if it is missing."""
        pipeline = cls()
        try:
            pipeline.store = VectorStore.load(settings.index_dir)
            if pipeline.store.dim != pipeline.embedder.dim:
                raise ValueError(
                    f"Index was built with dim {pipeline.store.dim} but the embedder "
                    f"produces {pipeline.embedder.dim}. Re-ingest the corpus."
                )
            pipeline.retriever = HybridRetriever(pipeline.store, pipeline.embedder)
        except (FileNotFoundError, ValueError):
            if not auto_ingest:
                raise
            pipeline.ingest()
        return pipeline

    # ------------------------------------------------------------------- query
    def query(self, question: str, top_k: int | None = None) -> RAGAnswer:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        if len(question) > settings.max_question_chars:
            raise ValueError(f"question is longer than {settings.max_question_chars} characters")

        started = time.perf_counter()
        retrieval = self.retriever.search(question, top_k=top_k)
        retrieval_ms = (time.perf_counter() - started) * 1000

        generation_started = time.perf_counter()
        generation = self.generator.generate(question, retrieval.chunks)
        answer, grounded = generation.text, generation.grounded
        generation_ms = (time.perf_counter() - generation_started) * 1000

        citations: list[Citation] = []
        seen: set[str] = set()
        for position, retrieved in enumerate(retrieval.chunks, start=1):
            if retrieved.chunk.id in seen:
                continue
            seen.add(retrieved.chunk.id)
            citations.append(
                Citation(
                    index=position,
                    chunk_id=retrieved.chunk.id,
                    title=retrieved.chunk.title,
                    source=retrieved.chunk.source,
                    heading=retrieved.chunk.heading,
                    score=round(retrieved.score, 4),
                    snippet=retrieved.chunk.text[:280].replace("\n", " "),
                )
            )

        return RAGAnswer(
            question=question,
            answer=answer,
            citations=citations,
            contexts=[retrieved.to_dict() for retrieved in retrieval.chunks],
            strategy=retrieval.strategy,
            timings={
                "retrieval_ms": round(retrieval_ms, 2),
                "generation_ms": round(generation_ms, 2),
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
            },
            generator=self.generator.name,
            embedding=self.embedder.name,
            grounded=bool(retrieval.chunks) and grounded,
        )

    # ------------------------------------------------------------------ stream
    async def stream(self, question: str, top_k: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """Yield retrieval metadata first, then the answer sentence by sentence."""
        result = self.query(question, top_k=top_k)
        yield {
            "event": "retrieved",
            "data": {
                "citations": [c.to_dict() for c in result.citations],
                "strategy": result.strategy,
                "timings": result.timings,
            },
        }

        # Sentence-ish chunks keep the UI responsive without a token stream API.
        buffer = ""
        for token in result.answer.split(" "):
            buffer += token + " "
            if len(buffer) >= 24 or token.endswith((".", "!", "?")):
                yield {"event": "token", "data": {"text": buffer}}
                buffer = ""
        if buffer:
            yield {"event": "token", "data": {"text": buffer}}

        yield {
            "event": "done",
            "data": {
                "answer": result.answer,
                "grounded": result.grounded,
                "timings": result.timings,
            },
        }

    # -------------------------------------------------------------------- info
    def info(self) -> dict[str, Any]:
        return {
            "store": self.store.stats(),
            "embedding": self.embedder.name,
            "generator": self.generator.name,
            "retrieval": {
                "dense_weight": settings.dense_weight,
                "keyword_weight": settings.keyword_weight,
                "mmr_lambda": settings.mmr_lambda,
                "top_k": settings.top_k,
            },
            "chunking": {
                "chunk_chars": settings.chunk_chars,
                "overlap": settings.chunk_overlap,
            },
        }
