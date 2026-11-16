# DocMind — RAG over your own documentation

A complete retrieval-augmented generation stack in ~1,500 lines of readable Python: markdown-aware
chunking → deterministic embeddings → hybrid retrieval (BM25 + dense, fused) → MMR diversification
→ citation-first answers → streaming UI, plus an evaluation harness that gates CI.

Runs **offline with no API key**. Flip two env vars for real embeddings and real generation.

![tests](https://img.shields.io/badge/tests-44%20passing-10b981) ![hit@5](https://img.shields.io/badge/Hit%405-100%25-34d399) ![mrr](https://img.shields.io/badge/MRR-0.933-38bdf8) ![python](https://img.shields.io/badge/python-3.11%2B-3776ab)

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m docmind.ingest       # chunk + embed ./corpus into ./data/index
python -m docmind.evaluate     # Hit@5 / MRR / keyword-coverage report
uvicorn docmind.service:app --port 8200
open http://localhost:8200     # chat UI with citations + retrieved context panel
```

Ask: *"How long does an API access token stay valid?"* → answer with `[1]` citations you can
click to inspect the exact chunk that was retrieved.

## Why not just "chunks + cosine + GPT"?

Because each stage below is where RAG systems actually break, and this project shows the fix:

| Failure mode | What this project does |
| --- | --- |
| Chunks lose their section context | Markdown-aware chunking, heading path stored **and** prepended to the embedded text |
| Exact identifiers get missed by embeddings | Hybrid retrieval: BM25 + dense, weights configurable (default 45/55) |
| Top-k is five copies of the same paragraph | Maximal Marginal Relevance (λ = 0.65) |
| Answers invent facts | Extractive generator only quotes retrieved sentences; returns an explicit "I couldn't find a confident answer" when nothing overlaps |
| Citations are decorative | Citations carry chunk id, source, heading, score, snippet — and `/query` returns the retrieved contexts and per-stage timings |
| "It feels better" as an evaluation method | 10-question golden set → Hit@5, MRR, keyword coverage, CI exit code |

## Pipeline

```
corpus/*.md
   │  chunking.py  (heading path + sentence packing, 900 chars / 150 overlap)
   ▼
chunks ──► embeddings.py (hashing-384 offline | OpenAI) ──► store.py (numpy matrix + JSON manifest)
                                                                  │
question ──► embed ──► retriever.py: BM25 ⨯ dense → normalise → fuse → MMR → top-k
                                                                  │
                          generator.py (extractive | OpenAI) ──► answer + citations + timings
```

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | chunk count, embedder, generator |
| GET | `/stats` | store stats, retrieval config, chunking config |
| GET | `/documents` | per-document chunk counts and headings |
| POST | `/ingest` | re-chunk and re-embed the corpus (persists by default) |
| POST | `/query` | `{question, top_k?}` → answer, citations, contexts, timings |
| POST | `/query/stream` | SSE: `retrieved` → `token`… → `done` |
| POST | `/evaluate` | run the golden-set evaluation in-process |
| GET | `/` | chat UI |

```bash
curl -s localhost:8200/query -H 'content-type: application/json' \
  -d '{"question":"What should I do when I receive a 429?"}' | python -m json.tool
```

## Evaluation (the interesting part)

```bash
$ python -m docmind.evaluate
[PASS] rank=1 cov=1.00  How long does an API access token stay valid?
[PASS] rank=1 cov=1.00  What should I do when I receive a 429 response?
...
Hit@5: 100.0% | MRR: 0.933 | Keyword coverage: 78.3%
```

`evaluate.py` exits non-zero below Hit@5 0.70 / MRR 0.50, so a chunker or fusion-weight change
that hurts retrieval fails the build instead of shipping. During development this harness caught
a genuine bug: dense scores were assigned in rank order rather than chunk-id order, which silently
made the first documents always win.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `DOCMIND_CORPUS` | `./corpus` | markdown/text directory |
| `DOCMIND_INDEX` | `./data/index` | persisted index |
| `DOCMIND_CHUNK_CHARS` / `_OVERLAP` | `900` / `150` | chunking budget |
| `DOCMIND_TOP_K` | `5` | retrieved passages |
| `DOCMIND_DENSE_WEIGHT` / `_KEYWORD_WEIGHT` | `0.55` / `0.45` | fusion weights |
| `DOCMIND_MMR_LAMBDA` | `0.65` | relevance vs diversity |
| `DOCMIND_EMBEDDING_PROVIDER` | `hashing` | `hashing` \| `openai` |
| `DOCMIND_GENERATOR` | `extractive` | `extractive` \| `openai` |
| `OPENAI_API_KEY` | — | needed for the `openai` paths |
| `DOCMIND_MAX_QUESTION_CHARS` | `1000` | request guard |

### Switching to real models

```bash
export DOCMIND_EMBEDDING_PROVIDER=openai
export DOCMIND_GENERATOR=openai
export OPENAI_API_KEY=sk-...
python -m docmind.ingest        # re-embed: dims change, the store rejects stale indexes
```

## Tests

```bash
python -m pytest      # 44 tests, all offline
```

| File | Covers |
| --- | --- |
| `test_chunking.py` | heading metadata, size bounds, overlap, short-fragment dropping, hard cuts |
| `test_embeddings_store.py` | determinism, normalisation, **score/chunk alignment regression**, save/load round-trip |
| `test_retrieval.py` | BM25 ranking, fusion, MMR redundancy reduction, golden questions, empty store |
| `test_rag_and_api.py` | grounded answers, citations, "don't know" behaviour, guards, SSE frames, 422s, evaluation gate |

## Add your own documents

```bash
mkdir my-docs && cp ~/notes/*.md my-docs/
DOCMIND_CORPUS=./my-docs python -m docmind.ingest
DOCMIND_CORPUS=./my-docs uvicorn docmind.service:app --port 8200
```

## Docker

```bash
docker build -t docmind .
docker run -p 8200:8200 docmind
```

## Layout

```
docmind/
  config.py       # settings + validation
  chunking.py     # markdown-aware chunker, corpus loader
  embeddings.py   # HashingEmbedder (offline) + OpenAIEmbedder
  store.py        # numpy vector store, persistence, RetrievedChunk
  retriever.py    # BM25, hybrid fusion, MMR
  generator.py    # extractive (grounded) + OpenAI generators
  rag.py          # pipeline: ingest / query / stream / info
  evaluate.py     # golden set, Hit@k, MRR, keyword coverage, CI gate
  service.py      # FastAPI + SSE + UI
corpus/           # 4 realistic docs (API guide, pricing, runbook, handbook)
static/index.html # chat UI with citation → chunk highlighting
tests/            # 44 tests
```

## Honest limitations

- The offline embedder is lexical, not semantic: it handles identifiers and paraphrase-lite
  queries, not "what does this *mean*". Use the OpenAI provider for real semantic search.
- The extractive generator is a sentence selector — great for demos and evaluations, not for
  synthesis across five documents.
- Single-node numpy index: fine to ~100k chunks. Beyond that, move `store.py` to pgvector or Qdrant.
- No re-ranking model, no query rewriting/hyde, no multi-turn question reformulation — all are
  natural next steps and the pipeline exposes the seams for them.
