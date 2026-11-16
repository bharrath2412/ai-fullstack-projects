"""LLM providers.

Two implementations behind one tiny interface:

* ``MockLLM``  — a deterministic, rule-based planner. It runs with **no API key
  and no network**, which keeps tests, demos and CI reproducible. It still goes
  through the exact same tool-calling loop as a real model.
* ``OpenAICompatLLM`` — real function calling against any OpenAI-compatible
  ``/chat/completions`` endpoint (OpenAI, Azure, Ollama, vLLM, Groq, ...).

Swapping providers is a one-line change in ``get_llm()``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from ..config import settings
from ..schemas import Message, ToolCall

URL_RE = re.compile(r"https?://[^\s<>\)\]\"']+")
EXPR_RE = re.compile(r"[-+*/().\d\s^e]{3,}")


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


class LLM(Protocol):
    name: str
    model: str

    async def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        ...


# --------------------------------------------------------------------------- #
# Offline deterministic planner
# --------------------------------------------------------------------------- #
_ARITH_HINTS = ("calculate", "compute", "what is", "how much", "evaluate", "*", "+", "/", "^", "sqrt", "percent")
_SQL_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (
        ("top", "customer"),
        "SELECT c.name, ROUND(SUM(o.total), 2) AS lifetime_value, COUNT(o.id) AS orders "
        "FROM customers c JOIN orders o ON o.customer_id = c.id "
        "WHERE o.status != 'cancelled' GROUP BY c.id ORDER BY lifetime_value DESC LIMIT 5",
    ),
    (
        ("revenue", "sales", "turnover"),
        "SELECT ROUND(SUM(total), 2) AS revenue, COUNT(*) AS orders "
        "FROM orders WHERE status != 'cancelled'",
    ),
    (
        ("country",),
        "SELECT c.country, COUNT(DISTINCT c.id) AS customers, ROUND(SUM(o.total), 2) AS revenue "
        "FROM customers c LEFT JOIN orders o ON o.customer_id = c.id AND o.status != 'cancelled' "
        "GROUP BY c.country ORDER BY revenue DESC",
    ),
    (
        ("category", "product"),
        "SELECT p.category, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue, "
        "SUM(oi.quantity) AS units FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id GROUP BY p.category ORDER BY revenue DESC",
    ),
    (
        ("month", "trend", "over time"),
        "SELECT strftime('%Y-%m', order_date) AS month, ROUND(SUM(total), 2) AS revenue "
        "FROM orders WHERE status != 'cancelled' GROUP BY month ORDER BY month",
    ),
    (
        ("average", "avg", "aov"),
        "SELECT ROUND(AVG(total), 2) AS average_order_value, COUNT(*) AS orders FROM orders",
    ),
    (
        ("status", "cancelled", "pending"),
        "SELECT status, COUNT(*) AS orders, ROUND(SUM(total), 2) AS value FROM orders GROUP BY status",
    ),
    (
        ("order", "how many", "count"),
        "SELECT COUNT(*) AS orders, ROUND(SUM(total), 2) AS total_value FROM orders",
    ),
]

_DOC_HINTS = (
    "agent", "architecture", "how does", "tool", "retry", "memory", "guardrail",
    "runbook", "docs", "design", "policy", "stream", "trace", "agentforge",
)


class MockLLM:
    """Deterministic planner: keyword routing + template synthesis."""

    name = "mock"
    model = "mock-planner-v1"

    def __init__(self) -> None:
        self.name = "mock"

    async def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        available = {t["function"]["name"] for t in tools}

        # 1. If we already have observations, answer from them.
        observations = [m for m in messages if m.role == "tool"]
        if observations:
            return LLMResponse(content=self._synthesize(messages, observations))

        user_text = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        ).strip()
        if not user_text:
            return LLMResponse(content="I need a question to work on — try asking about revenue or a calculation.")

        lower = user_text.lower()

        # 2. URL -> fetch
        url_match = URL_RE.search(user_text)
        if url_match and "http_fetch" in available:
            return self._call(
                "http_fetch",
                {"url": url_match.group(0).rstrip(".,)")},
                f"The user wants the contents of {url_match.group(0)}. Fetching it.",
            )

        # 3. Arithmetic -> calculator
        expression = self._extract_expression(user_text)
        if expression and "calculator" in available:
            return self._call(
                "calculator",
                {"expression": expression},
                f"This is an arithmetic question. Evaluating {expression!r}.",
            )

        # 4. Database questions -> sqlite_query
        if "sqlite_query" in available:
            sql = self._sql_for(lower)
            if sql:
                return self._call(
                    "sqlite_query",
                    {"sql": sql},
                    "This needs numbers from the company database, so I'll aggregate in SQL.",
                )

        # 5. Documentation questions -> doc_search
        if "doc_search" in available and any(hint in lower for hint in _DOC_HINTS):
            return self._call(
                "doc_search",
                {"query": user_text, "top_k": 3},
                "Sounds like a question about this project, so I'll search the knowledge base.",
            )

        # 6. Nothing to call: answer directly.
        return LLMResponse(content=self._direct_answer(user_text))

    # ---------------------------------------------------------------- helpers
    def _call(self, name: str, arguments: dict[str, Any], thought: str) -> LLMResponse:
        return LLMResponse(
            content=thought,
            tool_calls=[ToolCall(name=name, arguments=arguments)],
            finish_reason="tool_calls",
        )

    @staticmethod
    def _extract_expression(text: str) -> str | None:
        lowered = text.lower()
        # "20% of 450" style questions
        percent = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:of)\s*(\d+(?:\.\d+)?)", lowered)
        if percent:
            pct, base = percent.groups()
            return f"({pct} / 100) * {base}"
        candidate = EXPR_RE.search(text)
        if not candidate:
            return None
        expr = candidate.group(0).strip()
        if not re.search(r"\d", expr):
            return None
        if not re.search(r"[+\-*/^%]|sqrt|log", expr):
            return None
        if not any(hint in lowered for hint in _ARITH_HINTS):
            return None
        return expr.replace("^", "**").replace("x", "*")

    @staticmethod
    def _sql_for(lower: str) -> str | None:
        for keywords, sql in _SQL_PATTERNS:
            if any(keyword in lower for keyword in keywords):
                return sql
        return None

    def _synthesize(self, messages: list[Message], observations: list[Message]) -> str:
        blocks: list[str] = []
        for obs in observations[-3:]:
            name = obs.name or "tool"
            body = obs.content.strip()
            if body.startswith("ERROR"):
                blocks.append(f"`{name}` could not complete the request: {body[6:].strip()}")
                continue
            if name == "calculator":
                # "expr = value"
                value = body.rsplit("=", 1)[-1].strip()
                blocks.append(f"The result is **{value}**.")
            elif name == "sqlite_query":
                rows = body.splitlines()
                table_start = next((i for i, line in enumerate(rows) if "|" in line), None)
                if table_start is not None:
                    table = "\n".join(rows[table_start:])
                    blocks.append(f"From the database:\n\n```\n{table}\n```")
                else:
                    blocks.append(f"From the database:\n\n{body}")
            elif name == "doc_search":
                first = body.split("\n\n")[0]
                blocks.append(f"According to the knowledge base:\n\n{first}")
            elif name == "http_fetch":
                snippet = body[:900]
                blocks.append(f"Here is what that page says:\n\n{snippet}")
            else:
                blocks.append(body)
        summary = "\n\n".join(blocks) if blocks else "I could not find anything useful."
        return f"{summary}\n\n_Answered offline by the deterministic mock planner._"

    @staticmethod
    def _direct_answer(text: str) -> str:
        return (
            "I can help with three kinds of work right now:\n\n"
            "1. **Calculations** — e.g. `what is 1280 * 1.18 / 3` or `sqrt(144) + 2**10`\n"
            "2. **Database questions** — e.g. `which are my top customers by revenue?`, "
            "`show revenue by month`, `how many orders are cancelled?`\n"
            "3. **Project docs** — e.g. `how does the agent loop work?`, `what are the guardrails?`\n"
            f"\nI didn't spot a tool for: “{text[:140]}”. Could you rephrase it a bit more concretely?"
        )


# --------------------------------------------------------------------------- #
# Real provider
# --------------------------------------------------------------------------- #
class OpenAICompatLLM:
    """Function-calling client for OpenAI-compatible chat APIs."""

    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key or settings.llm_api_key
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.timeout = timeout or settings.llm_timeout_seconds
        if not self.api_key:
            raise ValueError("An API key is required for the openai provider")

    def _payload(self, messages: list[Message], tools: list[dict[str, Any]]) -> dict[str, Any]:
        # OpenAI expects the assistant tool call + tool result pairing in its own
        # format; our Message model carries enough information to rebuild it.
        wire: list[dict[str, Any]] = []
        for message in messages:
            entry: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.role == "tool":
                entry = {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id or "",
                    "content": message.content,
                }
            elif message.tool_calls:
                entry["tool_calls"] = message.tool_calls
                if not message.content:
                    entry["content"] = None
            if message.name and message.role != "tool":
                entry["name"] = message.name
            wire.append(entry)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire,
            "temperature": settings.llm_temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    async def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, headers=headers, json=self._payload(messages, tools))
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"upstream {response.status_code}", request=response.request, response=response
                    )
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                calls = [
                    ToolCall(
                        id=call.get("id") or f"call_{i}",
                        name=call["function"]["name"],
                        arguments=json.loads(call["function"].get("arguments") or "{}"),
                    )
                    for i, call in enumerate(message.get("tool_calls") or [])
                ]
                return LLMResponse(
                    content=message.get("content") or "",
                    tool_calls=calls,
                    finish_reason=data["choices"][0].get("finish_reason", "stop"),
                )
            except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                import asyncio

                await asyncio.sleep(0.6 * (2**attempt))
        raise RuntimeError(f"LLM request failed after 3 attempts: {last_error}")


# --------------------------------------------------------------------------- #
def get_llm(provider: str | None = None) -> LLM:
    """Factory used by the runtime and by tests."""
    provider = (provider or settings.llm_provider).lower()
    if provider == "mock":
        return MockLLM()
    if provider == "openai":
        return OpenAICompatLLM()
    raise ValueError(f"Unknown provider {provider!r}")
