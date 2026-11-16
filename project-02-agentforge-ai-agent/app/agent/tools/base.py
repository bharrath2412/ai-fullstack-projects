"""Tool base class, registry and argument validation.

Every tool declares a JSON-schema-ish manifest. The registry enforces:
  * name allowlisting (an LLM can only call registered tools)
  * required/typed argument checking
  * output truncation so a runaway tool cannot blow up the context window
  * per-tool timeout
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ...schemas import ToolCall, ToolResult, ToolSpec


class ToolError(Exception):
    """Raised for expected, user-facing tool failures."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Awaitable[str] | str]
    requires_network: bool = False
    dangerous: bool = False
    timeout_seconds: float = 15.0
    max_output_chars: int = 4000

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            requires_network=self.requires_network,
            dangerous=self.dangerous,
        )

    # ---------------------------------------------------------------- args
    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Coerce and validate arguments against `self.parameters`."""
        props: dict[str, Any] = self.parameters.get("properties", {})
        required: list[str] = self.parameters.get("required", [])

        unknown = set(arguments) - set(props)
        if unknown:
            raise ToolError(
                f"Unknown argument(s) {sorted(unknown)} for tool '{self.name}'. "
                f"Allowed: {sorted(props)}"
            )

        missing = [key for key in required if key not in arguments]
        if missing:
            raise ToolError(f"Missing required argument(s) {missing} for tool '{self.name}'")

        coerced: dict[str, Any] = {}
        for key, value in arguments.items():
            expected = props[key].get("type")
            try:
                if expected == "string":
                    coerced[key] = value if isinstance(value, str) else str(value)
                elif expected == "integer":
                    coerced[key] = int(value)
                elif expected == "number":
                    coerced[key] = float(value)
                elif expected == "boolean":
                    if isinstance(value, str):
                        coerced[key] = value.lower() in {"1", "true", "yes"}
                    else:
                        coerced[key] = bool(value)
                else:
                    coerced[key] = value
            except (TypeError, ValueError) as exc:
                raise ToolError(f"Argument '{key}' should be of type {expected}: {exc}") from exc
        return coerced

    async def run(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        try:
            args = self.validate_arguments(call.arguments)
            result = self.func(**args)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=self.timeout_seconds)
            text = result if isinstance(result, str) else str(result)
            if len(text) > self.max_output_chars:
                text = text[: self.max_output_chars] + (
                    f"\n…[truncated {len(text) - self.max_output_chars} chars]"
                )
            return ToolResult(
                call_id=call.id,
                name=self.name,
                ok=True,
                content=text,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=call.id,
                name=self.name,
                ok=False,
                content="",
                error=f"Tool timed out after {self.timeout_seconds}s",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except (ToolError, TypeError, ValueError) as exc:
            return ToolResult(
                call_id=call.id,
                name=self.name,
                ok=False,
                content="",
                error=str(exc),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except Exception as exc:  # noqa: BLE001 - tools must never crash a run
            return ToolResult(
                call_id=call.id,
                name=self.name,
                ok=False,
                content="",
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name in self.disabled:
            raise ToolError(f"Tool '{name}' is disabled by policy")
        tool = self.tools.get(name)
        if tool is None:
            raise ToolError(f"No tool named '{name}'. Available: {sorted(self.tools)}")
        return tool

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for name, t in sorted(self.tools.items()) if name not in self.disabled]

    def openai_tool_schema(self) -> list[dict[str, Any]]:
        """Shape expected by OpenAI-compatible function-calling APIs."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self.specs()
        ]

    async def run(self, call: ToolCall) -> ToolResult:
        try:
            tool = self.get(call.name)
        except ToolError as exc:
            return ToolResult(call_id=call.id, name=call.name, ok=False, content="", error=str(exc))
        return await tool.run(call)
