"""Embedding backends.

`HashingEmbedder` is a deterministic, dependency-free embedder: it hashes word
unigrams/bigrams and character trigrams into a fixed-size vector with sublinear
term-frequency weighting and L2 normalisation. It is *not* a neural embedding —
but it is fast, offline, reproducible, and good enough for lexical + partial
morphological matching when combined with BM25 in the hybrid retriever.

Swap `DOCMIND_EMBEDDING_PROVIDER=openai` for real semantic embeddings.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import numpy as np

from .config import settings

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for", "on", "with", "as",
    "at", "by", "from", "that", "this", "be", "are", "was", "were", "we", "you", "i", "our",
    # question words carry no retrieval signal on their own
    "what", "when", "where", "who", "whom", "whose", "which", "why", "how", "do", "does",
    "did", "can", "should", "would", "could", "will", "my", "me", "they", "their", "there",
    "if", "then", "than", "so", "not", "no", "but", "also", "any", "all", "about", "much",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _stable_hash(value: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    number = int.from_bytes(digest, "big")
    return number % dim, 1.0 if (number >> 63) & 1 == 0 else -1.0


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> np.ndarray:
        ...

    def embed_one(self, text: str) -> np.ndarray:
        ...


class HashingEmbedder:
    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.embedding_dim
        self.name = f"hashing-{self.dim}"

    def _features(self, text: str) -> list[tuple[str, float]]:
        words = tokenize(text)
        features: list[tuple[str, float]] = []
        for word in words:
            features.append((f"w:{word}", 1.0))
        for left, right in zip(words, words[1:]):
            features.append((f"b:{left}_{right}", 0.6))
        joined = " ".join(words)
        for i in range(0, max(0, len(joined) - 3)):
            features.append((f"c:{joined[i:i + 3]}", 0.25))
        return features

    def embed_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        counts: dict[str, float] = {}
        for key, weight in self._features(text):
            counts[key] = counts.get(key, 0.0) + weight
        for key, value in counts.items():
            index, sign = _stable_hash(key, self.dim)
            # sublinear tf keeps repeated boilerplate from dominating
            vector[index] += sign * (1.0 + math.log(value))
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.embed_one(text) for text in texts])


class OpenAIEmbedder:
    """Real semantic embeddings through any OpenAI-compatible embeddings endpoint."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        import httpx  # local import keeps the offline path dependency-light

        self._httpx = httpx
        self.model = model or settings.embedding_model
        self.api_key = api_key or settings.openai_api_key
        self.dim = 1536 if "3-small" in self.model else 3072
        self.name = f"openai-{self.model}"

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        response = self._httpx.post(
            f"{settings.openai_base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
        vectors = np.array([item["embedding"] for item in response.json()["data"]], dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def get_embedder(provider: str | None = None) -> Embedder:
    provider = (provider or settings.embedding_provider).lower()
    if provider == "hashing":
        return HashingEmbedder()
    if provider == "openai":
        return OpenAIEmbedder()
    raise ValueError(f"Unknown embedding provider {provider!r}")
