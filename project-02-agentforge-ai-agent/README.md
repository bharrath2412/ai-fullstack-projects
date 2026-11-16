# AgentForge — tool-using AI agent service

A production-shaped AI agent: FastAPI + a bounded ReAct loop + four sandboxed tools +
Server-Sent-Events streaming + full run tracing. Runs **fully offline** by default
(deterministic mock planner), and switches to real function calling with one env var.

![tests](https://img.shields.io/badge/tests-57%20passing-10b981) ![python](https://img.shields.io/badge/python-3.11%2B-3776ab) ![fastapi](https://img.shields.io/badge/FastAPI-0.115-009688)

## Why it is interesting

Most "agent" demos are a prompt glued to an API key. This one is the plumbing you actually need:

| Concern | How it is handled |
| --- | --- |
| Infinite loops | Hard caps on steps **and** tool calls; a partial answer is always produced |
| Runaway cost | Per-LLM-call timeout, per-tool timeout, output truncation |
| Prompt injection → RCE | Calculator evaluates an **AST allowlist**, never `eval` |
| Data exfiltration | SQL tool opens the DB `mode=ro` and only permits one `SELECT`/`WITH` |
| SSRF | `http_fetch` has a domain allowlist (no `169.254.169.254` tricks) |
| Debuggability | Every thought/call/observation is a `TraceEvent`, retrievable per `run_id` |
| Context overflow | Session memory trims old turns into a rolling summary |
| Testing without a key | Deterministic `MockLLM` exercises the same loop, so CI is hermetic |

## Quick start (no API key needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.data.seed                 # builds app/data/demo.db (idempotent)
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000> for the chat UI (live reasoning trace on the right),
or <http://localhost:8000/docs> for Swagger.

### Talk to it

```bash
curl -s localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"message":"who are my top 5 customers by lifetime value?"}' | python -m json.tool

# live SSE stream
curl -N -X POST localhost:8000/api/chat/stream \
  -H 'content-type: application/json' -d '{"message":"what is sqrt(144) + 2**10"}'
```

### Use a real model

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-...
export LLM_MODEL=gpt-4o-mini
# optional for Ollama / vLLM / Groq / Azure:
export LLM_BASE_URL=http://localhost:11434/v1
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | provider, model, tools, limits |
| GET | `/api/tools` | tool manifests (JSON-schema parameters) |
| POST | `/api/chat` | `{message, session_id?}` → answer + full trace |
| POST | `/api/chat/stream` | same, as `text/event-stream` (`thought`, `tool_call`, `tool_result`, `error`, `answer`) |
| GET | `/api/sessions/{id}` | conversation history + rolling summary |
| DELETE | `/api/sessions/{id}` | forget a session |
| GET | `/api/runs/{run_id}` | every step of one run |
| GET | `/api/runs/recent` | latest runs with timings |

## Tools

| Tool | What it does | Safety |
| --- | --- | --- |
| `calculator` | arithmetic, `sqrt/log/sin/cos/factorial`, `pi`/`e` | AST allowlist, length + exponent caps |
| `sqlite_query` | read-only SQL over the demo commerce DB | `mode=ro`, single `SELECT`/`WITH`, row cap |
| `doc_search` | BM25 over `app/data/knowledge/*.md` | no network, pure Python |
| `http_fetch` | allowlisted web pages → readable text | domain allowlist, byte cap, timeout |

Demo database: 40 customers, 12 products, 348 orders, 851 order_items across 12 months.

## Agent loop

```
user question
   │
   ├─ thought ─────────────► LLM (tools schema)
   │                           ├─ text  ──► final answer
   │                           └─ tool_call
   ├─ tool_call ───────────► registry: validate → run (timeout) → truncate
   ├─ tool_result ─────────► append observation
   └─ loop (≤ max_steps, ≤ max_tool_calls)
                              └─ trace stored, answer returned
```

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | `mock` \| `openai` |
| `LLM_MODEL` | `gpt-4o-mini` | any chat model with function calling |
| `LLM_API_KEY` | — | required for `openai` |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `AGENT_MAX_STEPS` | `6` | reasoning steps per run |
| `AGENT_MAX_TOOL_CALLS` | `8` | tool invocations per run |
| `AGENT_STEP_TIMEOUT_SECONDS` | `20` | per LLM call |
| `SQLITE_PATH` | `app/data/demo.db` | sandbox DB |
| `HTTP_ALLOWED_DOMAINS` | example.com, api.github.com, wikipedia.org, httpbin.org | comma separated |
| `CORS_ORIGINS` | `*` | tighten in production |

## Tests

```bash
python -m pytest              # 57 tests
python -m pytest tests/test_tools.py -v
```

Highlights: injection attempts (`__import__`, `open()`, `exec()`), SQL write attempts
(`DROP`, `PRAGMA`, stacked statements, comments), SSRF to the metadata IP, step/tool budget
enforcement, provider crash and timeout handling, memory trimming, SSE frame sequence.

## Docker

```bash
docker build -t agentforge .
docker run -p 8000:8000 -e LLM_PROVIDER=mock agentforge
```

## Layout

```
app/
  main.py                 # FastAPI routes, SSE, lifespan
  config.py               # env-driven settings + validation
  schemas.py              # pydantic models (Message, ToolCall, TraceEvent…)
  agent/
    runtime.py            # the bounded ReAct loop + tracing
    llm.py                # MockLLM (offline) + OpenAICompatLLM (function calling)
    memory.py             # session store, trimming, rolling summary
    tools/
      base.py             # Tool, ToolRegistry, arg validation, timeouts
      calculator.py       # AST-based safe evaluator
      sqlite_query.py     # read-only SQL sandbox
      doc_search.py       # BM25 knowledge-base retrieval
      http_fetch.py       # allowlisted fetch + HTML→text
  data/
    seed.py               # deterministic demo DB
    knowledge/*.md        # architecture, overview, runbook (searchable)
static/index.html         # zero-dependency chat UI with live trace
tests/                    # 57 tests
```

## Next steps

- Persist sessions/traces in Postgres and export spans to OpenTelemetry
- Add a `python_sandbox` tool backed by a WASM runtime (e.g. Pyodide in a Worker)
- Human-in-the-loop approval for `dangerous` tools before execution
- Golden-set evaluation harness (answer correctness + tool-choice accuracy)
