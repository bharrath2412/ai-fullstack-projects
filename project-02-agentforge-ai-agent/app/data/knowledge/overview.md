# Product overview

AgentForge is a reference implementation of a tool-using AI agent. It ships with
four tools and works with zero configuration because the default provider is a
deterministic offline planner.

## What it can do

- **Arithmetic** — any expression using `+ - * / // % **` plus `sqrt`, `log`,
  `sin`, `cos`, `factorial`, and the constants `pi` and `e`.
- **Company analytics** — read-only SQL over the bundled commerce database
  (customers, products, orders, order_items).
- **Documentation search** — BM25 retrieval over the markdown files in
  `app/data/knowledge`.
- **Web lookups** — allowlisted HTTP fetches with HTML-to-text conversion.

## Demo questions

```
what is 1280 * 1.18 / 3
which are my top 5 customers by lifetime value?
show revenue by month
what is the average order value?
how many orders were cancelled?
how does the agent loop work?
what are the guardrails?
```

## Providers

`LLM_PROVIDER=mock` (default) needs no key. Set `LLM_PROVIDER=openai` plus
`LLM_API_KEY` and optionally `LLM_BASE_URL` / `LLM_MODEL` to use real function
calling with OpenAI, Azure OpenAI, Groq, Together, Ollama or vLLM.

## Pricing of a run

Every response reports `tool_calls` and `duration_ms`. The trace endpoint
returns the full event list, which is what you would append to an observability
pipeline (Langfuse, Phoenix, OpenTelemetry) in production.
