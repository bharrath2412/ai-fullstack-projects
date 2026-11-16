"""Hybrid retrieval: BM25 keyword search + dense vectors, fused, then MMR-diversified.

Why hybrid: dense embeddings capture paraphrase, BM25 nails exact identifiers
(`429`, `X-Idempotency-Key`, product names). Fusing them is consistently better
than either alone, and MMR stops the top-k from being five near-duplicate chunks
of the same paragraph.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .config import settings
from .embeddings import Embedder, tokenize
from .store import RetrievedChunk, VectorStore


class BM25:
    """Okapi BM25 over the chunk corpus."""

    def __init__(self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.documents = documents
        self.doc_freqs = [Counter(doc) for doc in documents]
        self.lengths = np.array([len(doc) for doc in documents], dtype=float)
        self.avg_length = float(self.lengths.mean()) if len(documents) else 0.0
        df: Counter = Counter()
        for freq in self.doc_freqs:
            df.update(freq.keys())
        n = len(documents)
        self.idf = {
            term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()
        }

    def scores(self, query: str) -> np.ndarray:
        terms = tokenize(query)
        scores = np.zeros(len(self.documents), dtype=float)
        for term in terms:
            if term not in self.idf:
                continue
            idf = self.idf[term]
            for i, freq in enumerate(self.doc_freqs):
                tf = freq.get(term, 0)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / max(self.avg_length, 1e-9))
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        return scores


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    strategy: str
    candidates: int
    timings: dict[str, float]


class HybridRetriever:
    def __init__(self, store: VectorStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder
        self._bm25: BM25 | None = None
        self._bm25_size = -1

    @property
    def bm25(self) -> BM25:
        if self._bm25 is None or self._bm25_size != len(self.store.chunks):
            self._bm25 = BM25([tokenize(chunk.text) for chunk in self.store.chunks])
            self._bm25_size = len(self.store.chunks)
        return self._bm25

    def _normalise(self, scores: np.ndarray) -> np.ndarray:
        if scores.size == 0:
            return scores
        peak = float(scores.max())
        if peak <= 0:
            return np.zeros_like(scores)
        return scores / peak

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        use_mmr: bool = True,
        mmr_lambda: float | None = None,
    ) -> RetrievalResult:
        import time

        started = time.perf_counter()
        k = top_k or settings.top_k
        if not self.store.chunks:
            return RetrievalResult([], "empty", 0, {"total_ms": 0.0})

        # score_all keeps the result aligned with chunk order (search() sorts it away).
        dense_aligned = self.store.score_all(self.embedder.embed_one(query)).astype(float)
        dense_ms = (time.perf_counter() - started) * 1000

        keyword_started = time.perf_counter()
        keyword_scores = self.bm25.scores(query)
        keyword_ms = (time.perf_counter() - keyword_started) * 1000

        dense_norm = self._normalise(dense_aligned)
        keyword_norm = self._normalise(keyword_scores)
        combined = settings.dense_weight * dense_norm + settings.keyword_weight * keyword_norm

        candidates = int(min(len(combined), max(k * 4, k)))
        candidate_idx = np.argsort(-combined)[:candidates]
        candidate_idx = [i for i in candidate_idx if combined[i] >= settings.min_score] or list(candidate_idx)

        selected: list[int] = []
        if use_mmr and len(candidate_idx) > 1:
            lam = settings.mmr_lambda if mmr_lambda is None else mmr_lambda
            query_vector = self.embedder.embed_one(query)
            candidate_vectors = self.store.matrix[candidate_idx]
            relevance = np.array([combined[i] for i in candidate_idx], dtype=float)
            relevance = self._normalise(relevance)
            while candidate_idx and len(selected) < k:
                best_pos, best_value = -1, -math.inf
                for pos, index in enumerate(candidate_idx):
                    if index in selected:
                        continue
                    redundancy = 0.0
                    if selected:
                        sims = self.store.matrix[selected] @ self.store.matrix[index]
                        redundancy = float(np.max(sims))
                    value = lam * relevance[pos] - (1 - lam) * redundancy
                    if value > best_value:
                        best_value, best_pos = value, pos
                if best_pos < 0:
                    break
                selected.append(candidate_idx[best_pos])
            strategy = f"hybrid+mmr(λ={lam})"
        else:
            selected = candidate_idx[:k]
            strategy = "hybrid"

        results = [
            RetrievedChunk(
                chunk=self.store.chunks[i],
                score=float(combined[i]),
                dense_score=float(dense_norm[i]),
                keyword_score=float(keyword_norm[i]),
            )
            for i in selected
        ]
        return RetrievalResult(
            chunks=results,
            strategy=strategy,
            candidates=candidates,
            timings={
                "dense_ms": round(dense_ms, 2),
                "keyword_ms": round(keyword_ms, 2),
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
