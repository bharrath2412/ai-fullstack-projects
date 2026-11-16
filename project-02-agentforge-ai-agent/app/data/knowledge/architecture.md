# AgentForge architecture

AgentForge is a single-process FastAPI service with a small, explicit agent runtime.

## Request lifecycle

1. `POST /api/chat` (or `/api/chat/stream`) receives `{message, session_id}`.
2. `AgentRuntime.stream()` builds the prompt: system prompt + rolled-up session
   summary + the last 20 messages + the new user message.
3. The runtime asks the LLM for the next action. The LLM either returns text
   (final answer) or a tool call.
4. Tool calls go through `ToolRegistry.run()`, which validates arguments,
   enforces a timeout and truncates the output before it reaches the context.
5. Observations are appended as `tool` messages and the loop repeats.
6. The answer, every thought, every tool call and every observation are written
   to a `RunRecord` that `GET /api/runs/{run_id}` exposes.

## Agent loop

The loop is bounded by four independent limits:

| Limit | Setting | Default |
| --- | --- | --- |
| Reasoning steps | `AGENT_MAX_STEPS` | 6 |
| Tool invocations | `AGENT_MAX_TOOL_CALLS` | 8 |
| LLM call timeout | `AGENT_STEP_TIMEOUT_SECONDS` | 20s |
| Tool timeout | per-tool | 15s |

A run always terminates: exhausting the step budget produces a partial answer
built from the observations already collected instead of an exception.

## Memory model

Session memory keeps the recent turns verbatim. When the message count crosses
`AGENT_MAX_HISTORY_MESSAGES`, the oldest turns are folded into a rolling
summary string that is injected back as a system message. Memory is in-process;
replace `MemoryStore` with Redis for multi-replica deployments.

## Guardrails and policies

- **Tool allowlist** — the LLM can only call registered names; unknown names are rejected.
- **Argument validation** — unexpected or missing arguments fail fast with a clear message.
- **SQL is read-only** — the database is opened with `mode=ro`, only a single
  `SELECT`/`WITH` statement is accepted, and DDL/DML keywords are refused.
- **Network allowlist** — `http_fetch` only reaches domains in `HTTP_ALLOWED_DOMAINS`.
- **No `eval`** — the calculator walks a Python AST with an operator/function allowlist.
- **Output truncation** — tool output is capped so a huge page cannot flood the prompt.
- **Full tracing** — every step is a `TraceEvent` streamed to the client.

## Streaming protocol

`POST /api/chat/stream` returns `text/event-stream`. Each event is named after its
kind (`thought`, `tool_call`, `tool_result`, `error`, `answer`) and carries a JSON
payload with an `index`, so clients can render the agent's reasoning live.
