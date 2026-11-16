"""Runtime tests: budget enforcement, tracing, memory trimming, error handling."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.llm import LLMResponse, MockLLM
from app.agent.memory import MemoryStore
from app.agent.runtime import AgentRuntime
from app.agent.tools import build_registry
from app.schemas import StepKind, ToolCall


class ScriptedLLM:
    """Deterministic scripted model so we can test loop mechanics precisely."""

    name = "scripted"
    model = "scripted-v1"

    def __init__(self, script):
        self.script = script
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        return LLMResponse(content="done")


class ExplodingLLM:
    name = "boom"
    model = "boom-v1"

    async def complete(self, messages, tools):
        raise RuntimeError("provider exploded")


class SlowLLM:
    name = "slow"
    model = "slow-v1"

    async def complete(self, messages, tools):
        await asyncio.sleep(5)
        return LLMResponse(content="too late")


def make_runtime(llm=None, **kwargs):
    return AgentRuntime(registry=build_registry(allow_network=False), llm=llm or MockLLM(), **kwargs)


def test_arithmetic_end_to_end():
    runtime = make_runtime()
    result = asyncio.run(runtime.run("what is 12 * 12 + 1", session_id="t1"))
    assert result.tool_calls == 1
    assert "145" in result.answer
    kinds = [event.kind for event in result.steps]
    assert StepKind.tool_call in kinds
    assert StepKind.tool_result in kinds
    assert kinds[-1] is StepKind.answer


def test_database_question_uses_sql_tool():
    runtime = make_runtime()
    result = asyncio.run(runtime.run("show revenue by month", session_id="t2"))
    assert result.tool_calls == 1
    assert any(event.payload.get("tool") == "sqlite_query" for event in result.steps)


def test_no_tool_question_answers_directly():
    runtime = make_runtime()
    result = asyncio.run(runtime.run("hello, who are you?", session_id="t3"))
    assert result.tool_calls == 0
    assert result.answer


def test_step_budget_is_enforced():
    # Model that always asks for another tool call, never answers.
    script = [
        LLMResponse(
            content="looping",
            tool_calls=[ToolCall(name="calculator", arguments={"expression": "1+1"})],
        )
        for _ in range(10)
    ]
    runtime = make_runtime(llm=ScriptedLLM(script), max_steps=3, max_tool_calls=2)
    result = asyncio.run(runtime.run("loop forever", session_id="t4"))
    assert result.tool_calls <= 2
    assert result.answer  # always produces something


def test_tool_errors_are_reported_as_events():
    script = [
        LLMResponse(
            content="trying bad tool",
            tool_calls=[ToolCall(name="calculator", arguments={"expression": "__import__('os')"})],
        ),
        LLMResponse(content="I could not run that safely."),
    ]
    runtime = make_runtime(llm=ScriptedLLM(script))
    result = asyncio.run(runtime.run("break the sandbox", session_id="t5"))
    errors = [e for e in result.steps if e.kind is StepKind.error]
    assert errors, "expected an error event for the rejected tool call"
    assert "I could not run that safely." in result.answer


def test_provider_exception_is_handled_gracefully():
    runtime = make_runtime(llm=ExplodingLLM())
    result = asyncio.run(runtime.run("anything", session_id="t6"))
    assert result.answer
    assert any(e.kind is StepKind.error for e in result.steps)
    assert "could not reach the language model" in result.answer


def test_llm_timeout_is_handled():
    runtime = make_runtime(llm=SlowLLM(), step_timeout_seconds=0.2)
    result = asyncio.run(runtime.run("slow question", session_id="t7"))
    assert "did not respond in time" in result.answer


def test_trace_is_retrievable_by_run_id():
    runtime = make_runtime()
    result = asyncio.run(runtime.run("what is 2 ** 8", session_id="t8"))
    stored = runtime.get_run(result.run_id)
    assert stored is not None
    assert stored.question.startswith("what is")
    assert len(stored.events) == len(result.steps)
    assert runtime.recent_runs(1)[0].run_id == result.run_id


def test_session_history_is_persisted():
    runtime = make_runtime()
    asyncio.run(runtime.run("what is 2 + 2", session_id="t9"))
    asyncio.run(runtime.run("what is 3 + 3", session_id="t9"))
    from app.agent.memory import memory_store

    session = asyncio.run(memory_store.get("t9"))
    history = session.public_history()
    assert len(history) == 4  # two questions + two answers
    assert session.runs == 2


def test_memory_trims_and_summarises():
    store = MemoryStore(max_messages=4)
    from app.agent.memory import Session
    from app.schemas import Message

    session = Session(id="trim")
    for i in range(10):
        session.messages.append(Message(role="user", content=f"question {i}"))
        session.messages.append(Message(role="assistant", content=f"answer {i}"))
    store.trim(session)
    assert len(session.messages) == 4
    assert "question 0" in session.summary
    assert len(session.summary) <= 1200


def test_mock_llm_is_deterministic():
    llm = MockLLM()
    messages = [__import__("app.schemas", fromlist=["Message"]).Message(role="user", content="what is 9*9")]
    first = asyncio.run(llm.complete(messages, []))
    second = asyncio.run(llm.complete(messages, []))
    assert first.content == second.content
