"""Pydantic models shared by the agent runtime and the HTTP API."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A request from the LLM to execute a tool."""

    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    call_id: str
    name: str
    ok: bool
    content: str
    error: str | None = None
    duration_ms: float = 0.0


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    # Only used by real providers: the assistant turn that requested tools.
    tool_calls: list[dict[str, Any]] | None = None


class StepKind(str, Enum):
    thought = "thought"
    tool_call = "tool_call"
    tool_result = "tool_result"
    answer = "answer"
    error = "error"


class TraceEvent(BaseModel):
    index: int
    kind: StepKind
    detail: str
    payload: dict[str, Any] = Field(default_factory=dict)
    at: float = Field(default_factory=time.time)

    def to_sse(self) -> str:
        return f"event: {self.kind.value}\ndata: {self.model_dump_json()}\n\n"


class AgentAnswer(BaseModel):
    run_id: str
    answer: str
    steps: list[TraceEvent]
    tool_calls: int
    duration_ms: float
    provider: str
    model: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    max_steps: int | None = Field(default=None, ge=1, le=12)


class ChatResponse(BaseModel):
    session_id: str
    run_id: str
    answer: str
    steps: list[TraceEvent]
    tool_calls: int
    duration_ms: float


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    requires_network: bool = False
    dangerous: bool = False
