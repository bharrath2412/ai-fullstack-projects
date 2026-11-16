"""Session memory with trimming + rolling summary.

Keeps the last N messages verbatim and folds everything older into a compact
summary line, so long conversations do not blow the context window.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from ..config import settings
from ..schemas import Message


@dataclass
class Session:
    id: str
    messages: list[Message] = field(default_factory=list)
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    runs: int = 0

    def public_history(self) -> list[dict]:
        return [
            {"role": m.role, "content": m.content, "name": m.name}
            for m in self.messages
            if m.role in {"user", "assistant"}
        ]


class MemoryStore:
    """In-process store. Swap the two dicts for Redis/Postgres in production."""

    def __init__(self, max_sessions: int = 500, max_messages: int | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.max_sessions = max_sessions
        self.max_messages = max_messages or settings.max_history_messages
        self._guard = asyncio.Lock()

    async def get(self, session_id: str) -> Session:
        async with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(id=session_id)
                self._sessions[session_id] = session
                self._evict()
            session.updated_at = time.time()
            return session

    def lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def reset(self, session_id: str) -> None:
        async with self._guard:
            self._sessions.pop(session_id, None)

    def _evict(self) -> None:
        if len(self._sessions) <= self.max_sessions:
            return
        oldest = sorted(self._sessions.values(), key=lambda s: s.updated_at)[: len(self._sessions) - self.max_sessions]
        for session in oldest:
            self._sessions.pop(session.id, None)
            self._locks.pop(session.id, None)

    # ------------------------------------------------------------------ write
    def trim(self, session: Session) -> None:
        """Fold the oldest turns into `session.summary`."""
        overflow = len(session.messages) - self.max_messages
        if overflow <= 0:
            return
        dropped = session.messages[:overflow]
        session.messages = session.messages[overflow:]
        snippets = []
        for message in dropped:
            if message.role in {"user", "assistant"}:
                label = "User" if message.role == "user" else "Assistant"
                snippets.append(f"{label}: {message.content[:160]}")
        if snippets:
            merged = session.summary + "\n" + "\n".join(snippets) if session.summary else "\n".join(snippets)
            # keep the summary bounded too
            session.summary = merged[-1200:]


memory_store = MemoryStore()
