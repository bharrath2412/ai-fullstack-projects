# Operations runbook

## Health checks

```
curl localhost:8000/health
curl localhost:8000/api/tools
```

## Common failures

### `LLM_API_KEY is required when LLM_PROVIDER=openai`

The settings object validates at import time. Either export a key or unset
`LLM_PROVIDER` to fall back to the offline planner.

### `Demo database not found`

Run `python -m app.data.seed` to create `app/data/demo.db`. The API also seeds it
automatically on first boot when the file is missing.

### A tool returns `Domain is not on the allowlist`

That is the SSRF guard. Add the host to `HTTP_ALLOWED_DOMAINS` (comma separated)
and restart, or ask a question the agent can answer from the knowledge base.

### Agent stops at `Tool budget exhausted`

The run hit `AGENT_MAX_TOOL_CALLS`. The agent is asked for a final answer using
what it already knows. Raise the limit only if you also raise `AGENT_MAX_STEPS`.

## Tuning

- Latency: lower `AGENT_MAX_STEPS` to 3 and keep `LLM_TIMEOUT_SECONDS` under 15.
- Cost: use a smaller model for routing (`LLM_MODEL`) and a larger one only for
  synthesis; the tool schema is stable, so prompt caching works well.
- Safety: leave `http_fetch` disabled in production unless you control the
  allowlist, and keep SQL on a read replica user.

## Observability

`GET /api/runs/recent` lists the latest runs with tool counts and timings.
`GET /api/runs/{run_id}` returns every step, including arguments and truncated
tool output, which is enough to replay a failure.
