"""DocMind configuration (env driven, safe offline defaults)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    corpus_dir: Path = Path(os.getenv("DOCMIND_CORPUS", BASE_DIR / "corpus"))
    index_dir: Path = Path(os.getenv("DOCMIND_INDEX", BASE_DIR / "data" / "index"))

    # chunking
    chunk_chars: int = int(os.getenv("DOCMIND_CHUNK_CHARS", "900"))
    chunk_overlap: int = int(os.getenv("DOCMIND_CHUNK_OVERLAP", "150"))
    min_chunk_chars: int = int(os.getenv("DOCMIND_MIN_CHUNK_CHARS", "80"))

    # retrieval
    top_k: int = int(os.getenv("DOCMIND_TOP_K", "5"))
    dense_weight: float = float(os.getenv("DOCMIND_DENSE_WEIGHT", "0.55"))
    keyword_weight: float = float(os.getenv("DOCMIND_KEYWORD_WEIGHT", "0.45"))
    mmr_lambda: float = float(os.getenv("DOCMIND_MMR_LAMBDA", "0.65"))
    min_score: float = float(os.getenv("DOCMIND_MIN_SCORE", "0.02"))

    # embeddings: "hashing" (offline, deterministic) or "openai"
    embedding_provider: str = os.getenv("DOCMIND_EMBEDDING_PROVIDER", "hashing")
    embedding_dim: int = int(os.getenv("DOCMIND_EMBEDDING_DIM", "384"))
    embedding_model: str = os.getenv("DOCMIND_EMBEDDING_MODEL", "text-embedding-3-small")

    # generation: "extractive" (offline) or "openai"
    generator_provider: str = os.getenv("DOCMIND_GENERATOR", "extractive")
    generator_model: str = os.getenv("DOCMIND_GENERATOR_MODEL", "gpt-4o-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    request_timeout: float = float(os.getenv("DOCMIND_TIMEOUT", "45"))

    max_question_chars: int = int(os.getenv("DOCMIND_MAX_QUESTION_CHARS", "1000"))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("DOCMIND_CORS", "*").split(",") if o.strip()]
    )
    log_level: str = os.getenv("DOCMIND_LOG_LEVEL", "info")

    def validate(self) -> None:
        if self.embedding_provider not in {"hashing", "openai"}:
            raise ValueError("DOCMIND_EMBEDDING_PROVIDER must be 'hashing' or 'openai'")
        if self.generator_provider not in {"extractive", "openai"}:
            raise ValueError("DOCMIND_GENERATOR must be 'extractive' or 'openai'")
        if self.embedding_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the openai embedding provider")
        if self.generator_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the openai generator")
        if self.chunk_overlap >= self.chunk_chars:
            raise ValueError("DOCMIND_CHUNK_OVERLAP must be smaller than DOCMIND_CHUNK_CHARS")
        if not 0.0 <= self.mmr_lambda <= 1.0:
            raise ValueError("DOCMIND_MMR_LAMBDA must be in [0, 1]")
        total = self.dense_weight + self.keyword_weight
        if total <= 0:
            raise ValueError("Retrieval weights must sum to a positive number")


settings = Settings()
