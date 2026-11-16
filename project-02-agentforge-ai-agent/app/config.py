"""Application settings, read from environment variables with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "AgentForge"
    environment: str = os.getenv("ENVIRONMENT", "development")

    # LLM provider: "mock" runs fully offline, "openai" uses any
    # OpenAI-compatible /chat/completions endpoint.
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))

    # Agent guardrails
    max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "6"))
    max_tool_calls: int = int(os.getenv("AGENT_MAX_TOOL_CALLS", "8"))
    max_tool_output_chars: int = int(os.getenv("AGENT_MAX_TOOL_OUTPUT_CHARS", "4000"))
    step_timeout_seconds: float = float(os.getenv("AGENT_STEP_TIMEOUT_SECONDS", "20"))
    max_history_messages: int = int(os.getenv("AGENT_MAX_HISTORY_MESSAGES", "20"))

    # Tool sandboxing
    sqlite_path: str = os.getenv("SQLITE_PATH", str(BASE_DIR / "app" / "data" / "demo.db"))
    sql_max_rows: int = int(os.getenv("SQL_MAX_ROWS", "50"))
    http_allowed_domains: list[str] = field(
        default_factory=lambda: _list(
            "HTTP_ALLOWED_DOMAINS",
            ["example.com", "api.github.com", "wikipedia.org", "en.wikipedia.org", "httpbin.org"],
        )
    )
    http_timeout_seconds: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "8"))
    http_max_bytes: int = int(os.getenv("HTTP_MAX_BYTES", "200000"))

    # Server
    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS", ["*"])
    )
    log_level: str = os.getenv("LOG_LEVEL", "info")
    enable_streaming: bool = _bool("ENABLE_STREAMING", True)

    def validate(self) -> None:
        if self.llm_provider not in {"mock", "openai"}:
            raise ValueError(f"Unknown LLM_PROVIDER {self.llm_provider!r} (use 'mock' or 'openai')")
        if self.llm_provider == "openai" and not self.llm_api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=openai")
        if self.max_steps < 1:
            raise ValueError("AGENT_MAX_STEPS must be >= 1")


settings = Settings()
