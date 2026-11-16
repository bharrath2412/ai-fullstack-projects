"""The agent loop.

A deliberately explicit ReAct-style runtime:

    plan -> (maybe call tools) -> observe -> repeat -> final answer

Guarantees enforced here (not in the prompt):
  * hard cap on reasoning steps and on tool invocations
  * per-step timeout for the LLM call
  * every tool result is fed back even when the tool failed
  * full trace of thoughts / calls / results for observability
  * the loop can never raise: failures become an `error` event + graceful answer
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

from ..config import settings
from ..schemas import AgentAnswer, Message, StepKind, ToolCall, TraceEvent
from .llm import LLM, get_llm
from .memory import memory_store
from .tools import ToolRegistry, build_registry

SYSTEM_PROMPT = """You are AgentForge, an AI assistant that answers questions by calling tools.

Rules:
1. Prefer a tool over guessing. Never invent numbers, metrics or quotes.
2. Use `calculator` for arithmetic, `sqlite_query` for company data,
   `doc_search` for questions about this project, and `http_fetch` for allowlisted web pages.
3. Call at most one tool per step and read the observation before deciding what to do next.
4. If a tool fails, explain the failure and try a different approach once.
5. Finish with a direct, concise answer (2-5 sentences) and cite the tool you relied on.
"""


@dataclass
class RunRecord:
    run_id: str
    session_id: str
    question: str
    events: list[TraceEvent] = field(default_factory=list)
    answer: str = ""
    tool_calls: int = 0
    duration_ms: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "question": self.question,
            "answer": self.answer,
            "tool_calls": self.tool_calls,
            "duration_ms": self.duration_ms,
            "events": [e.model_dump() for e in self.events],
        }


class AgentRuntime:
    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        llm: LLM | None = None,
        max_steps: int | None = None,
        max_tool_calls: int | None = None,
        step_timeout_seconds: float | None = None,
        max_runs_kept: int = 200,
    ) -> None:
        self.registry = registry or build_registry()
        self.llm = llm or get_llm()
        self.max_steps = max_steps or settings.max_steps
        self.max_tool_calls = max_tool_calls or settings.max_tool_calls
        self.step_timeout_seconds = step_timeout_seconds or settings.step_timeout_seconds
        self._runs: dict[str, RunRecord] = {}
        self._max_runs_kept = max_runs_kept

    # ------------------------------------------------------------- observability
    def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def recent_runs(self, limit: int = 20) -> list[RunRecord]:
        return sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)[:limit]

    def _remember(self, record: RunRecord) -> None:
        self._runs[record.run_id] = record
        if len(self._runs) > self._max_runs_kept:
            oldest = min(self._runs.values(), key=lambda r: r.created_at)
            self._runs.pop(oldest.run_id, None)

    # ------------------------------------------------------------------- loop
    async def stream(
        self, question: str, session_id: str = "default", max_steps: int | None = None
    ) -> AsyncIterator[TraceEvent]:
        started = time.perf_counter()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        steps_budget = min(max_steps or self.max_steps, self.max_steps)
        session = await memory_store.get(session_id)

        history: list[Message] = [Message(role="system", content=SYSTEM_PROMPT)]
        if session.summary:
            history.append(
                Message(role="system", content=f"Earlier conversation summary:\n{session.summary}")
            )
        history.extend(session.messages[-settings.max_history_messages :])
        history.append(Message(role="user", content=question))

        events: list[TraceEvent] = []
        tool_call_count = 0
        counter = 0
        answer = ""

        def emit(kind: StepKind, detail: str, payload: dict | None = None) -> TraceEvent:
            nonlocal counter
            event = TraceEvent(index=counter, kind=kind, detail=detail, payload=payload or {})
            counter += 1
            events.append(event)
            return event

        try:
            for step in range(steps_budget):
                context = history[-settings.max_history_messages :]
                yield emit(
                    StepKind.thought,
                    f"Step {step + 1}/{steps_budget}: deciding the next action",
                    {"step": step + 1},
                )

                try:
                    response = await asyncio.wait_for(
                        self.llm.complete(context, self.registry.openai_tool_schema()),
                        timeout=self.step_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    answer = (
                        "The language model did not respond in time. Please try again, or ask a "
                        "narrower question."
                    )
                    yield emit(StepKind.error, "LLM call timed out")
                    break
                except Exception as exc:  # noqa: BLE001
                    answer = f"I could not reach the language model ({type(exc).__name__}). Please retry shortly."
                    yield emit(StepKind.error, f"LLM error: {exc}")
                    break

                if response.content:
                    yield emit(StepKind.thought, response.content[:600], {"step": step + 1})

                # ---------------- final answer ----------------
                if not response.tool_calls:
                    answer = response.content.strip() or "I don't have an answer for that yet."
                    yield emit(StepKind.answer, answer)
                    break

                # ---------------- tool calls ----------------
                calls: list[ToolCall] = response.tool_calls[:1]  # one tool per step by design
                for call in calls:
                    if tool_call_count >= self.max_tool_calls:
                        yield emit(
                            StepKind.error,
                            f"Tool budget exhausted ({self.max_tool_calls} calls); asking for a final answer",
                        )
                        history.append(
                            Message(
                                role="system",
                                content="Tool budget exhausted. Answer with what you already know.",
                            )
                        )
                        break

                    tool_call_count += 1
                    yield emit(
                        StepKind.tool_call,
                        f"Calling {call.name}",
                        {"tool": call.name, "arguments": call.arguments, "call_id": call.id},
                    )

                    result = await self.registry.run(call)

                    if result.ok:
                        yield emit(
                            StepKind.tool_result,
                            f"{call.name} returned {len(result.content)} chars in {result.duration_ms:.0f}ms",
                            {
                                "tool": call.name,
                                "call_id": call.id,
                                "ok": True,
                                "content": result.content,
                                "duration_ms": result.duration_ms,
                            },
                        )
                    else:
                        yield emit(
                            StepKind.error,
                            f"{call.name} failed: {result.error}",
                            {"tool": call.name, "call_id": call.id, "ok": False, "error": result.error},
                        )

                    history.append(
                        Message(
                            role="assistant",
                            content=response.content or f"Calling {call.name}",
                            tool_calls=[
                                {
                                    "id": call.id,
                                    "type": "function",
                                    "function": {
                                        "name": call.name,
                                        "arguments": _json_dumps(call.arguments),
                                    },
                                }
                            ],
                        )
                    )
                    history.append(
                        Message(
                            role="tool",
                            name=call.name,
                            tool_call_id=call.id,
                            content=result.content
                            if result.ok
                            else f"ERROR: {result.error}",
                        )
                    )
            else:
                # Loop finished without a final answer (step budget hit).
                answer = (
                    "I hit my step limit before fully answering. Here is what I found so far:\n\n"
                    + _digest(events)
                )
                yield emit(StepKind.answer, answer, {"budget_exhausted": True})
        except Exception as exc:  # noqa: BLE001 - the loop must never crash the server
            answer = f"Something went wrong while running the agent: {type(exc).__name__}: {exc}"
            yield emit(StepKind.error, str(exc))
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            answer = answer or _digest(events) or "I wasn't able to produce an answer."

            # Persist the turn (trimming folds old messages into the summary).
            async with memory_store.lock(session_id):
                session.messages.append(Message(role="user", content=question))
                session.messages.append(Message(role="assistant", content=answer))
                session.runs += 1
                memory_store.trim(session)

            final_event = TraceEvent(
                index=counter,
                kind=StepKind.answer,
                detail="run complete",
                payload={
                    "run_id": run_id,
                    "session_id": session_id,
                    "answer": answer,
                    "tool_calls": tool_call_count,
                    "duration_ms": duration_ms,
                    "provider": self.llm.name,
                    "model": self.llm.model,
                },
            )

            record = RunRecord(
                run_id=run_id,
                session_id=session_id,
                question=question,
                events=[*events, final_event],
                answer=answer,
                tool_calls=tool_call_count,
                duration_ms=duration_ms,
            )
            self._remember(record)

            yield final_event

    async def run(
        self, question: str, session_id: str = "default", max_steps: int | None = None
    ) -> AgentAnswer:
        """Collect the full stream into a single response object."""
        started = time.perf_counter()
        events: list[TraceEvent] = []
        payload: dict = {}
        async for event in self.stream(question, session_id=session_id, max_steps=max_steps):
            events.append(event)
            if event.kind is StepKind.answer and "run_id" in event.payload:
                payload = event.payload

        return AgentAnswer(
            run_id=payload.get("run_id", "unknown"),
            answer=payload.get("answer", ""),
            steps=events,
            tool_calls=payload.get("tool_calls", 0),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            provider=self.llm.name,
            model=self.llm.model,
        )


def _digest(events: list[TraceEvent]) -> str:
    """Build a readable answer from whatever observations we already have."""
    parts: list[str] = []
    for event in events:
        if event.kind is StepKind.tool_result:
            content = event.payload.get("content", "")
            parts.append(content.split("\n\n")[0] if content else "")
        elif event.kind is StepKind.error:
            parts.append(f"⚠️ {event.detail}")
    return "\n\n".join(p for p in parts if p)[:1500]


def _json_dumps(value: dict) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


_runtime: AgentRuntime | None = None


def get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
    return _runtime
