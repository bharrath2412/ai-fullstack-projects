# Full-stack & AI engineering monorepo

Four self-contained, production-shaped projects — a full-stack web app, an AI agent service, a
machine-learning service and a RAG application. Every project has real source code, tests that
pass, offline defaults (no API keys required), Dockerfiles and its own README.

| # | Project | Stack | What it proves | Tests |
| --- | --- | --- | --- | --- |
| 1 | [**TaskFlow**](project-01-taskflow-fullstack) — project & task manager | React 18 + Vite · Express · SQLite · JWT · Zod | Full-stack CRUD, auth, migrations, optimistic UI, Kanban drag & drop, dashboard aggregates | **10 passing** |
| 2 | [**AgentForge**](project-02-agentforge-ai-agent) — tool-using AI agent | FastAPI · ReAct loop · SSE · sandboxed tools | Agent runtime design: budgets, tracing, guardrails, provider abstraction, offline determinism | **57 passing** |
| 3 | [**Churn ML service**](project-03-churn-ml-service) — train → serve → monitor | scikit-learn · pandas · FastAPI · PSI drift | Leakage-safe pipelines, threshold tuning on a business constraint, registry, explanations, drift | **40 passing** |
| 4 | [**DocMind**](project-04-docmind-rag) — RAG over your docs | FastAPI · BM25 + dense + MMR · SSE | Retrieval quality, citations, honest refusals, evaluation gates | **44 passing** |

**Totals: 151 tests, 0 network dependencies for the offline path.**

Measured results on the bundled data:

| Metric | Value |
| --- | --- |
| Churn model ROC AUC (holdout) | **0.822** (5-fold CV 0.809 ± 0.013) |
| Churn recall at tuned threshold | **0.740** (policy floor 0.70) |
| RAG Hit@5 / MRR | **100% / 0.933** |
| RAG keyword coverage of answers | **78.3%** (precision-first quoting) |
| Agent tools covered by safety tests | 4 / 4 (calculator, SQL, docs, HTTP) |

## Quick start

Each project is independent — `cd` into one and follow its README. The 30-second version:

```bash
# 1 — full-stack web app  (API :4000, UI :5173)
cd project-01-taskflow-fullstack/server && npm install && npm run seed && npm run dev
cd ../client && npm install && npm run dev

# 2 — AI agent  (UI + API :8000, mock LLM by default)
cd project-02-agentforge-ai-agent
pip install -r requirements-dev.txt && python -m app.data.seed
uvicorn app.main:app --reload --port 8000

# 3 — ML service  (:8100, trains on boot if no model exists)
cd project-03-churn-ml-service
pip install -r requirements-dev.txt && python -m churn.train
uvicorn churn.service:app --port 8100

# 4 — RAG app  (:8200)
cd project-04-docmind-rag
pip install -r requirements-dev.txt && python -m docmind.ingest
uvicorn docmind.service:app --port 8200
```

Run everything at once:

```bash
docker compose up --build     # web :8080 · agent :8000 · churn :8100 · rag :8200
```

Run every test suite:

```bash
make test        # see Makefile at the repo root
```

## What each project contains

### 1 · TaskFlow — full-stack web
`React + Vite` SPA, `Express` REST API, SQLite with WAL and foreign keys, JWT auth with bcrypt,
Zod validation on every body/query, float-position Kanban ordering, SQL-side dashboard
aggregates, in-memory rate limiting, Helmet, graceful shutdown, and 10 integration tests that hit
real HTTP with a real database. The frontend does optimistic updates with rollback, native
drag & drop, and a dependency-free SVG chart.

### 2 · AgentForge — AI agent
A bounded ReAct loop with hard caps on steps and tool calls, per-call timeouts, AST-safe
calculator (no `eval`), read-only SQL tool (`mode=ro`, single `SELECT`), domain-allowlisted HTTP
tool, BM25 doc search, session memory with rolling summaries, full trace per `run_id`, SSE
streaming, and a deterministic offline planner so tests are hermetic. One env var switches to
real OpenAI-style function calling.

### 3 · Churn ML service — ML engineering
Deterministic data generator with a known logistic ground truth, schema validation, a
`ColumnTransformer` pipeline with derived ratios and unseen-category handling, stratified
holdout + k-fold CV, threshold tuned to a recall floor, permutation importance, versioned model
registry, counterfactual explanations, PSI drift monitoring, and a self-contained HTML model
report (`artifacts/model_report.html`).

### 4 · DocMind — RAG
Markdown-aware chunking with heading paths, deterministic hashing embeddings (offline) or OpenAI
embeddings, a numpy vector store, hybrid BM25 + dense retrieval with MMR, an extractive
generator that quotes sources and refuses when it cannot ground an answer, SSE streaming, a
citation UI, and a golden-set evaluation harness that fails CI below Hit@5 0.70 / MRR 0.50.

## Repository conventions

- **No secrets in code.** Every service reads env vars, has a `.env.example`, and refuses to boot
  in production with a placeholder secret.
- **Offline-first.** Tests never need network access or API keys; hosted providers are opt-in.
- **Errors are data.** Stable error codes, field-level validation details, request/trace ids.
- **Every number is reproducible.** Fixed seeds, fingerprints of the dataset, versioned artifacts.
- **Docs live with the code.** Each README doubles as the design rationale and the limitations list.

## Layout

```
.
├── project-01-taskflow-fullstack/   # React + Express + SQLite (JS)
│   ├── server/                      # app factory, repositories, routes, tests
│   ├── client/                      # Vite SPA, components, design tokens
│   └── deploy/, Dockerfile, docker-compose.yml
├── project-02-agentforge-ai-agent/  # Python/FastAPI agent
│   ├── app/agent/                   # runtime, llm, memory, tools/
│   ├── app/data/knowledge/          # searchable docs
│   ├── static/index.html            # chat UI with live trace
│   └── tests/
├── project-03-churn-ml-service/     # Python/ML
│   ├── churn/                       # data, features, train, registry, monitoring, service
│   ├── artifacts/                   # registered models + HTML report
│   └── tests/
├── project-04-docmind-rag/          # Python/RAG
│   ├── docmind/                     # chunking, embeddings, store, retriever, generator, rag, evaluate
│   ├── corpus/                      # 4 realistic markdown docs
│   ├── static/index.html            # chat UI with citations
│   └── tests/
├── docker-compose.yml
└── Makefile
```

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs four parallel jobs on every push and
pull request: the web app (npm ci, API tests, production build), the agent, the ML service
(train + tests) and DocMind (index + tests + the retrieval quality gate). No API keys are needed —
the offline providers are the default.

## Packaging & pushing

```bash
make test                      # 151 tests across the four projects
make export                    # git bundle + per-project zips in exports/
make push REPO=git@github.com:you/your-repo.git
```

Fastest path to `bharrath2412/ai-fullstack-projects`: see
[QUICKSTART-PUSH.md](QUICKSTART-PUSH.md) (two steps, no token shared).
Broader options in [PUSH-TO-YOUR-REPO.md](PUSH-TO-YOUR-REPO.md) — five import recipes (new repo, merge into an
existing repo, copy into a subfolder, git subtree, bundle/zip), the exact conflict-resolution
policy, and the post-push checklist.

## Adding these to an existing repository

This workspace is a fresh git repo (2 commits). Three ways to graft it onto your own project:

```bash
# A. copy the folders you want, keep your history
cp -r project-01-taskflow-fullstack ~/your-repo/projects/taskflow
cd ~/your-repo && git add projects/taskflow && git commit -m "Add TaskFlow full-stack project"

# B. pull this repo in as a remote and merge (keeps full history)
cd ~/your-repo
git remote add portfolio /path/to/this/repo
git fetch portfolio
git merge --allow-unrelated-histories portfolio/main

# C. vendor a single project as a subtree
git subtree add --prefix=projects/docmind /path/to/this/repo main --squash
```

If your repo already has a root README, keep yours and lift the per-project READMEs — each one
is standalone (setup, API, tests, config, limitations). Merge `.gitignore` rules for
`node_modules/`, `data/`, `artifacts/models/` and `__pycache__/`.

## Roadmap ideas

- Unify the three Python services behind one gateway + shared compose network
- Add Playwright e2e for TaskFlow's drag & drop and a Lighthouse budget
- Persist agent traces to Postgres and emit OpenTelemetry spans
- Real temporal validation and a fairness audit for the churn model
- pgvector + a re-ranking model for DocMind, with query rewriting

## License

MIT — see [LICENSE](LICENSE).
