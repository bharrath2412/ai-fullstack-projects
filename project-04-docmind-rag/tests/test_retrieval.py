"""Hybrid retrieval tests: BM25, fusion, MMR, and real questions from the corpus."""

from __future__ import annotations

import numpy as np
import pytest

from docmind.embeddings import HashingEmbedder
from docmind.rag import RAGPipeline
from docmind.retriever import BM25, HybridRetriever


@pytest.fixture(scope="module")
def pipeline():
    rag = RAGPipeline()
    rag.ingest(persist=False)  # returns stats; the pipeline is mutated in place
    return rag


def test_bm25_ranks_matching_document_first():
    bm25 = BM25([["api", "key", "rotate"], ["pricing", "seat", "cost"], ["sso", "enterprise"]])
    scores = bm25.scores("rotate the api key")
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]


def test_bm25_ignores_unknown_terms():
    bm25 = BM25([["alpha", "beta"], ["gamma"]])
    assert bm25.scores("zzz-unknown-token").sum() == 0.0


def test_retriever_returns_scored_chunks(pipeline):
    result = pipeline.retriever.search("how long does an access token last", top_k=3)
    assert len(result.chunks) == 3
    assert result.strategy.startswith("hybrid")
    top = result.chunks[0]
    assert 0.0 <= top.score <= 1.5
    assert top.dense_score >= 0 and top.keyword_score >= 0
    assert result.timings["total_ms"] >= 0


def test_keyword_and_dense_are_fused(pipeline):
    result = pipeline.retriever.search("429 retry backoff", top_k=5)
    sources = [c.chunk.source for c in result.chunks]
    assert "api-guide.md" in sources
    # at least one chunk should be driven primarily by keyword matching
    assert any(c.keyword_score > 0 for c in result.chunks)


@pytest.mark.parametrize(
    "question,expected_source",
    [
        ("How long does an API access token stay valid?", "api-guide.md"),
        ("Which plans include single sign-on?", "pricing.md"),
        ("What is the on-call escalation path for a Sev-1 incident?", "runbook.md"),
        ("What chunk size does the ingestion pipeline use?", "handbook.md"),
        ("How do I rotate a leaked API key?", "runbook.md"),
    ],
)
def test_golden_questions_hit_expected_document(pipeline, question, expected_source):
    result = pipeline.retriever.search(question, top_k=3)
    sources = [c.chunk.source for c in result.chunks]
    assert expected_source in sources, f"{question} -> {sources}"


def test_mmr_reduces_redundancy(pipeline):
    question = "how do I rotate a leaked api key"
    with_mmr = pipeline.retriever.search(question, top_k=5, use_mmr=True)
    without_mmr = pipeline.retriever.search(question, top_k=5, use_mmr=False)

    def max_pairwise_similarity(chunks):
        matrix = pipeline.store.matrix[[
            pipeline.store.chunks.index(chunk.chunk) for chunk in chunks
        ]]
        similarity = matrix @ matrix.T
        np.fill_diagonal(similarity, 0)
        return float(similarity.max()) if similarity.size else 0.0

    assert max_pairwise_similarity(with_mmr.chunks) <= max_pairwise_similarity(without_mmr.chunks) + 1e-6
    assert with_mmr.strategy.startswith("hybrid+mmr")


def test_empty_store_returns_nothing():
    empty = HybridRetriever.__new__(HybridRetriever)
    from docmind.store import VectorStore

    empty.store = VectorStore(dim=16)
    empty.embedder = HashingEmbedder(dim=16)
    empty._bm25 = None
    empty._bm25_size = -1
    result = empty.search("anything", top_k=3)
    assert result.chunks == []
    assert result.strategy == "empty"


def test_top_k_is_respected(pipeline):
    for k in (1, 3, 7):
        assert len(pipeline.retriever.search("pricing plans", top_k=k).chunks) == min(k, len(pipeline.store.chunks))
