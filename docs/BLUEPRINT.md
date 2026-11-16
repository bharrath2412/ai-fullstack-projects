# Phase 2 — Blueprint for five resume-grade products

Chennai / Bengaluru market fit, each mapped to a hiring signal. This document is the contract:
schema, API surface, AI component, proof metrics and milestones. Projects 1–2 are built in this
repo; 3–5 are specified here and land next.

| # | Product | Hiring signal | Folder (when built) | Status |
| --- | --- | --- | --- | --- |
| 1 | **AirGrid** — India open-data dashboard (PWA) | Frontend craft, performance, accessibility, offline-first | `project-05-india-open-data-dashboard` | ✅ built |
| 2 | **BillBook** — multi-tenant GST invoicing & inventory SaaS | Full-stack depth: RBAC, money math, PDF, payments, CI/CD | `project-06-billbook-gst-saas` | ✅ built |
| 3 | **DefectEye** — visual defect detection (CNN → ONNX → FastAPI) | Applied CV/ML: dataset design, metrics vs baseline, latency | `project-07-defecteye-vision` | 📋 specified |
| 4 | **TriageOps** — security triage agent (scan → CVE RAG → report) | AI agents with real guardrails, evaluation, cost control | `project-08-triageops-agent` | 📋 specified |
| 5 | **CampusHire AI** — placement platform + NLP matcher + agent | Flagship: full-stack + ML + agent in one product with real users | `project-09-campushire-ai` | 📋 specified |

---

## 1 · AirGrid — India open-data dashboard (PWA)

**Problem.** Public air-quality data is published as raw JSON/CSV that no shopkeeper, student or
journalist can read. AirGrid turns it into a fast, installable, offline-capable dashboard.

**Users.** A citizen checking Chennai's AQI before a run; a reporter comparing cities; a student
charting a month of PM2.5.

**Architecture.**
```
data.gov.in / CPCB API ──┐
bundled 45-day snapshot ─┴─► src/data/source.js ─► analytics.js ─► React views ─► SVG charts
                                      │                                  │
                                 service worker (app shell + last data) ──┘
```
- **Data adapter** with two modes: `bundled` (deterministic snapshot, works offline, used by tests
  and the live demo) and `live` (`VITE_DATA_GOV_KEY`, 6s timeout, falls back to the snapshot and
  shows an "offline / snapshot" banner instead of breaking).
- **Charts** hand-rolled in SVG: no chart library — the whole app chunk is ~13 KB gzipped, keyboard-focusable
  points, `aria-label` summaries, `prefers-reduced-motion` respected.
- **PWA**: `manifest.webmanifest`, maskable icons, hand-written service worker
  (app-shell precache + stale-while-revalidate for data), install prompt, offline banner.

**Data model.** `{ city, date, pm25, pm10, no2, temp_c, humidity, aqi }` × 45 days × 5 cities,
plus `stations[]` for search/filter (name, zone, latest AQI, dominant pollutant).

**API/interface.** None required; the adapter is the seam. Optional live mode: `GET
/api/aqi?city=chennai` proxied by the Vite dev server if `VITE_API_PROXY` is set.

**Proof for HR.** Bundle budget enforced in CI (`scripts/check-budget.mjs`, fails > 200 KB
gzipped JS or > 320 KB total), Vitest suite (48 tests) over the AQI/analysis logic (thresholds, aggregation, deltas,
filtering) plus jsdom render tests of the real dashboard, axe-style a11y assertions (landmarks, labels, focus order), offline verified by
serving the built app with the network throttled to offline in DevTools → run
`npx lighthouse http://localhost:5173 --only-categories=performance,accessibility` locally and
record the score in the README (numbers are yours to reproduce, not invented here).

**Milestones.** (1) generator + adapter + tests, (2) KPIs and charts, (3) filters/search,
(4) PWA + offline, (5) budgets + a11y pass, (6) Lighthouse numbers in README.

**Risks.** data.gov.in requires a free key and is intermittently slow → snapshot fallback is not a
workaround, it is the design; CPCB AQI breakpoints differ from US EPA → we implement CPCB and say so.

---

## 2 · BillBook — multi-tenant GST invoicing & inventory SaaS

**Problem.** A small shop needs GST-compliant invoices, stock that decrements itself, and a tax
summary an accountant will accept — without paying for Tally.

**Users.** Shop owner (all access), staff (billing only), accountant (reports, read-only).

**Architecture.**
```
React-free admin (static, hand-written JS)
        │ JWT (tenant + role claims)
        ▼
FastAPI ─ routers: auth · items · invoices · payments · reports
        │        app/gst.py  (pure, unit-tested tax engine)
        │        app/pdf.py  (fpdf2 invoice, amount-in-words)
        ▼
SQLite (WAL) — tenants, users, items, invoices, invoice_lines, stock_moves, payments, audit
```
- **Multi-tenancy**: every query is scoped by `tenant_id` taken from the token, never from the
  request body. Cross-tenant reads return 404 (not 403) so existence is not leaked.
- **GST engine** (pure functions): intra-state → CGST+SGST each at `rate/2`; inter-state → IGST at
  `rate`; line-level discounts; tax-inclusive prices; per-line rounding at ₹0.01 and an invoice
  round-off line to the nearest rupee; HSN codes; cess support.
- **Numbering**: `INV/<FY>/0001` per tenant per financial year (Apr–Mar), allocated inside the
  insert transaction with a `UNIQUE(tenant_id, fy, seq)` constraint — no gaps under concurrency.
- **Inventory**: stock decrements when an invoice is *issued*, reverses on cancel, full
  `stock_moves` ledger, `/items?low_stock=true` alert feed.
- **Payments**: Razorpay **test mode** — order creation, `HMAC-SHA256(order_id|payment_id, secret)`
  signature verification with `hmac.compare_digest`, invoice flips to `paid`. No live keys, ever.
- **PDF**: fpdf2 invoice with GSTIN, place of supply, HSN-wise tax table, tax summary, amount in
  words (Indian numbering: crore/lakh), and a deterministic filename.

**Data model.**
`tenants(id, name, gstin, state_code, address)` ·
`users(id, tenant_id, email, password_hash, role)` ·
`items(id, tenant_id, sku, name, hsn, unit_price, gst_rate, stock_qty, reorder_level, unit)` ·
`invoices(id, tenant_id, number, fy, seq, customer_name, customer_gstin, place_of_supply,
 status, subtotal, cgst, sgst, igst, cess, round_off, total, issued_at)` ·
`invoice_lines(id, invoice_id, item_id, description, hsn, qty, unit_price, discount, gst_rate,
 taxable_value, tax_amount, line_total)` ·
`stock_moves(id, item_id, delta, reason, ref, created_at)` · `payments(id, invoice_id, provider,
provider_order_id, provider_payment_id, amount, status, signature_verified)`

**API.**
`POST /api/auth/register` (creates a tenant + owner) · `POST /api/auth/login` ·
`GET/POST/PATCH /api/items` · `GET /api/items?low_stock=true` ·
`POST /api/invoices` · `GET /api/invoices` · `GET /api/invoices/{id}` ·
`POST /api/invoices/{id}/cancel` · `GET /api/invoices/{id}/pdf` ·
`POST /api/payments/order` · `POST /api/payments/verify` ·
`GET /api/reports/summary` · `GET /api/reports/gst` · `GET /health`.

**Proof for HR.** 143 passing tests, 92% coverage of `app/`: money-math matrix (47 cases incl.
inclusive/exclusive, discount, cess, round-off, and a 200-invoice randomised property test),
tenant-isolation tests, RBAC tests per role, a 10-thread concurrent numbering test, stock-ledger
reconciliation, signature-forgery and payment-id replay rejection, PDF fact-check, and p95/p50
latency measured at runtime by `/health`. CI runs the suite; the container is the deployment unit
(no invented "live URL").

**Milestones.** (1) DB + auth + RBAC, (2) GST engine + tests, (3) invoices + numbering + stock,
(4) PDF, (5) Razorpay test mode, (6) reports + admin UI, (7) CI/CD + deploy.

**Risks.** GST rules vary by state/sector (SEZ, exports, reverse charge) → we implement the common
B2C/B2B intra/inter-state cases and say exactly what is out of scope. PDF fonts: INR symbol needs
a Unicode TTF → ship DejaVu or use "Rs." (we use "Rs." to stay dependency-free).

---

## 3 · DefectEye — visual defect detection (CNN → ONNX → FastAPI)

**Problem.** Manual visual inspection at the end of a line is slow and inconsistent; Chennai's
auto/electronics cluster needs cheap, explainable defect detection.

**Users.** QA engineer (upload image → verdict + heat map), line supervisor (batch + trend).

**Approach.** Synthetic-first so the repo stays small and reproducible: a procedural generator
renders PCB/steel-texture patches with six defect classes (scratch, void, solder bridge, spatter,
crack, misalignment) with controlled lighting/noise. Baseline: HOG + logistic regression.
Model: small CNN (3 conv blocks, 96×96 grayscale) trained on CPU; export to ONNX; parity test
that ONNX and PyTorch outputs agree within 1e-4.

**API.** `POST /predict` (multipart image → class, confidence, per-class scores, heat map PNG) ·
`POST /predict/batch` · `GET /model/info` (metrics + model card) · `GET /health`.

**Proof for HR.** Precision/recall/F1 per class and macro-F1 vs the HOG baseline (table in the
model card), confusion matrix, p95 inference < 100 ms measured on CPU with a documented batch
size, ONNX parity test, drift check on brightness/contrast shifts, Grad-CAM-free explanation
(occlusion sensitivity) rendered as a heat map.

**Milestones.** (1) generator + dataset splits, (2) baseline + metrics, (3) CNN + training loop,
(4) ONNX export + parity, (5) service + heat maps, (6) model card + latency budget.

**Risks.** Synthetic data transfers imperfectly to real lines → the pipeline takes a
`--dataset ./real` path; the card states the gap. Torch on CPU is fine at 96×96 for a demo, but
training beyond ~20k images needs a GPU.

---

## 4 · TriageOps — security triage agent

**Problem.** A scan produces 300 findings; a human needs the 5 that matter, with evidence and a
fix. Most "AI security" demos either hallucinate CVEs or run tools without permission.

**Users.** A pentester or DevOps engineer running an authorised scan of their own lab.

**Architecture.** Human-in-the-loop by construction:
```
scope file (CIDR allowlist) ─► planner ─► [approval gate] ─► nmap/rustscan sandbox → findings.json
                                                                    │
                              CVE corpus (NVD subset) ─► RAG ─► severity + reachability reasoning
                                                                    ▼
                                                     prioritized report.md + SARIF
```
- **Hard guardrails**: targets must be inside the `SCOPE` file; private/link-local ranges refused
  unless explicitly allowed; every active scan requires an approval token from the operator;
  dry-run mode renders the exact command without executing; all commands run in a subprocess with
  timeout and a read-only results dir; no shell=True.
- **Evidence discipline**: every claim in the report cites a finding id or CVE record; unsupported
  claims are dropped by a verifier pass; the model never invents CVEs (enumeration is retrieval,
  not generation).
- **Evaluation**: a labelled set of 60 scan outputs → precision/recall of the
  "fix-first" ranking, plus cost and latency per run, plus guardrail tests (out-of-scope target,
  missing approval, injected prompt in a banner string).

**API.** `POST /runs` (scan path or target + approval) · `GET /runs/{id}` (trace) ·
`POST /runs/{id}/approve` · `GET /runs/{id}/report.md` · `GET /evaluation`.

**Proof for HR.** Ranking precision@5 vs a keyword baseline, false-positive rate, per-run cost and
latency, guardrail test suite, and a report that a security engineer would accept.

**Risks.** Legal/ethical: only `SCOPE`-listed lab targets, documented in the README's first screen.
NVD is huge → ship a curated 2k-CVE subset with a refresh script.

---

## 5 · CampusHire AI — flagship placement platform

**Problem.** A placement cell runs on spreadsheets: 600 students, 40 companies, no structured
eligibility, no feedback loop. Recruiters drown in unfiltered resumes.

**Users.** Student (profile, applications, prep), placement officer (drives, shortlists,
analytics), recruiter (job post, ranked candidates).

**Architecture.**
```
Next.js/React SPA ─ FastAPI ─ PostgreSQL
      │               ├── auth + RBAC (student/officer/recruiter, org-scoped)
      │               ├── drives, applications, offers, audit log
      │               ├── matcher: resume → skills (spaCy) → embedding → job fit + skill gaps
      │               └── agent: resume feedback + mock interview (RAG over company guides)
      └── SSE for agent streaming
```
**Matcher.** Resume parsing (PDF → text → sections → skills via spaCy PhraseMatcher over a
curated 300-skill taxonomy), normalisation (CGPA/percentage, graduation year), then hybrid
scoring: TF-IDF/embedding cosine over the JD + explicit eligibility rules (CGPA, backlogs, branch)
+ experience weights. Output is explainable: `matched_skills`, `missing_skills`, `score_breakdown`.

**Agent.** Guarded loops (reuse the AgentForge runtime pattern): tools =
`read_resume`, `job_requirements`, `company_guide_search`, `score_application`; max steps, cost
ceiling, transcript per session, no PII leaves the service boundary (redaction pass).

**Proof for HR.** Recall@10 of the matcher against a hand-labelled shortlist, skill-gap
correctness tests, officer analytics (funnel, offer rate, branch-wise), and — the decisive line —
**"used by X students at <college>"** with a real pilot. Target: 1 department, 1 placement cycle.

**Milestones.** (1) schema + RBAC + drive lifecycle, (2) resume parsing + taxonomy + matcher,
(3) officer analytics, (4) agent + SSE, (5) pilot with the cell, (6) case study in the README.

**Risks.** Resume PII and fairness: redact names/contact from scoring inputs, document that
college/branch weights are configurable and audited, never auto-reject (ranking only, humans decide).

---

## Cross-cutting standards (all five)

- Offline/deterministic defaults so CI and demos never need paid keys; hosted models opt-in.
- Every number in a README is reproducible by a command in that README.
- Money and dates are unit-tested; auth boundaries have negative tests.
- Errors are machine-readable (`code`, `message`, `details`), never stack traces to clients.
- Dockerfile + `.env.example` + `make test` in every project; CI matrix at the repo root.
- Honest limitations section last in every README — untested assumptions are stated, not hidden.
