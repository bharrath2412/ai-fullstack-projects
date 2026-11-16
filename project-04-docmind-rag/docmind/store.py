"""A small, persisted vector store (numpy + JSON, no external service).

Fine for tens of thousands of chunks on a single node: dense search is one
matrix multiply. For millions of chunks, swap this class for pgvector/Qdrant —
the interface is intentionally tiny (`add`, `search`, `save`, `load`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .chunking import Chunk


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    dense_score: float = 0.0
    keyword_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.chunk.id,
            "source": self.chunk.source,
            "heading": self.chunk.heading,
            "title": self.chunk.title,
            "text": self.chunk.text,
            "position": self.chunk.position,
            "score": round(float(self.score), 4),
            "dense_score": round(float(self.dense_score), 4),
            "keyword_score": round(float(self.keyword_score), 4),
        }


class VectorStore:
    def __init__(self, dim: int, embedding_name: str = "unknown") -> None:
        self.dim = dim
        self.embedding_name = embedding_name
        self.chunks: list[Chunk] = []
        self.matrix: np.ndarray = np.zeros((0, dim), dtype=np.float32)

    # ------------------------------------------------------------------ write
    def add(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if vectors.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {vectors.shape[1]}")
        self.chunks.extend(chunks)
        self.matrix = np.vstack([self.matrix, vectors.astype(np.float32)]) if len(self.matrix) else vectors.astype(np.float32)

    def reset(self) -> None:
        self.chunks = []
        self.matrix = np.zeros((0, self.dim), dtype=np.float32)

    # ------------------------------------------------------------------- read
    def score_all(self, query_vector: np.ndarray) -> np.ndarray:
        """Cosine similarity of the query against *every* chunk, in chunk order."""
        if not self.chunks or self.matrix.size == 0:
            return np.zeros(0, dtype=np.float32)
        vector = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        if vector.shape[0] != self.dim and vector.size == self.dim:
            vector = vector.reshape(self.dim)
        if vector.shape[0] != self.dim:
            raise ValueError(f"query vector has dim {vector.size}, store expects {self.dim}")
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        return self.matrix @ vector

    def search(self, query_vector: np.ndarray, k: int = 5) -> list[tuple[Chunk, float]]:
        scores = self.score_all(query_vector)
        if scores.size == 0:
            return []
        top = np.argsort(-scores)[: max(1, k)]
        return [(self.chunks[i], float(scores[i])) for i in top]

    def by_source(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk.source] = counts.get(chunk.source, 0) + 1
        return dict(sorted(counts.items()))

    def stats(self) -> dict[str, Any]:
        return {
            "chunks": len(self.chunks),
            "documents": len(self.by_source()),
            "dim": self.dim,
            "embedding": self.embedding_name,
            "vectors_bytes": int(self.matrix.nbytes) if self.matrix.size else 0,
            "per_document": self.by_source(),
        }

    # ------------------------------------------------------------ persistence
    def save(self, directory: Path | None = None, directory_override: Path | None = None) -> Path:
        target = Path(directory_override or directory or ".")
        target.mkdir(parents=True, exist_ok=True)
        np.save(target / "vectors.npy", self.matrix)
        (target / "chunks.json").write_text(
            json.dumps(
                {
                    "dim": self.dim,
                    "embedding": self.embedding_name,
                    "chunks": [chunk.to_dict() for chunk in self.chunks],
                },
                ensure_ascii=False,
                indent=0,
            ),
            encoding="utf-8",
        )
        return target

    @classmethod
    def load(cls, directory: Path) -> "VectorStore":
        directory = Path(directory)
        manifest_path = directory / "chunks.json"
        vectors_path = directory / "vectors.npy"
        if not manifest_path.exists() or not vectors_path.exists():
            raise FileNotFoundError(f"No index found in {directory}. Run ingest first.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        store = cls(dim=int(manifest["dim"]), embedding_name=manifest.get("embedding", "unknown"))
        store.matrix = np.load(vectors_path).astype(np.float32)
        store.chunks = [Chunk.from_dict(row) for row in manifest["chunks"]]
        return store
