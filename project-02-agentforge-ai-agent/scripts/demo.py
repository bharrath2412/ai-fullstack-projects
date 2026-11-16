#!/usr/bin/env python3
"""CLI demo: run a handful of questions through the agent and print the trace.

    python scripts/demo.py
    python scripts/demo.py "what is 4096 / 8" "show revenue by month"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.runtime import AgentRuntime  # noqa: E402
from app.data.seed import create_database  # noqa: E402

DEFAULT_QUESTIONS = [
    "what is 1280 * 1.18 / 3",
    "who are my top 5 customers by lifetime value?",
    "show revenue by month",
    "how does the agent loop work?",
    "what are the guardrails?",
]

ICONS = {
    "thought": "🧠",
    "tool_call": "🛠 ",
    "tool_result": "📦",
    "error": "⚠️ ",
    "answer": "✅",
}


async def main(questions: list[str]) -> None:
    create_database()
    runtime = AgentRuntime()
    print(f"provider={runtime.llm.name} model={runtime.llm.model} "
          f"steps≤{runtime.max_steps} tools≤{runtime.max_tool_calls}\n")

    for index, question in enumerate(questions, start=1):
        print(f"\033[1m[{index}/{len(questions)}] {question}\033[0m")
        async for event in runtime.stream(question, session_id="cli-demo"):
            if event.kind == "answer" and "run_id" in event.payload:
                continue  # printed as part of the trace below
            icon = ICONS.get(event.kind.value, "•")
            detail = event.detail.replace("\n", " ")[:110]
            print(f"  {icon} {detail}")
            if event.kind == "tool_result":
                content = event.payload.get("content", "")
                preview = content.splitlines()[:4]
                for line in preview:
                    print(f"       \033[2m{line[:110]}\033[0m")
        result = await runtime.run(question, session_id=f"cli-demo-{index}")
        print(f"  → \033[32m{result.answer[:600]}\033[0m")
        print(f"  \033[2m{result.tool_calls} tool call(s) · {result.duration_ms:.0f} ms · "
              f"run {result.run_id}\033[0m")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or DEFAULT_QUESTIONS))
