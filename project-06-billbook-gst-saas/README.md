# BillBook — multi-tenant GST invoicing & inventory SaaS

A small Chennai electronics shop needs three things that Tally charges for and spreadsheets get
wrong: a **GST-compliant invoice**, **stock that decrements itself**, and a **tax summary an
accountant will accept**. BillBook is that, as a multi-tenant SaaS: FastAPI + SQLite + a
hand-written admin client (no build step), JWT auth with three roles, gapless per-financial-year
numbering, integer-paise money math, PDF invoices, and Razorpay **test-mode** payments.

```
static/ (hand-written admin, no framework)
        │  JWT: {sub, tid, role, exp}  ← tenant id comes from here, never from the body
        ▼
FastAPI ── routers: auth · items · invoices · payments · reports · health
   │        app/gst.py       pure tax engine (47 tests)
   │        app/pdf.py       fpdf2 invoice + amount in words (Indian numbering)
   │        app/payments.py  Razorpay test mode + HMAC verification
   ▼
SQLite (WAL) — tenants, users, items, invoices, invoice_lines, stock_moves, payments, audit
```

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m scripts.seed                 # demo shop + 8 invoices (3 paid, 1 cancelled)
uvicorn app.main:app --reload --port 8100
# open http://localhost:8100  →  demo@billbook.dev / demo12345
# interactive API docs        →  http://localhost:8100/docs
pytest                                 # 143 tests, ~6 s
pytest --cov=app                       # 92% of app/ covered
```

Docker (non-root, healthcheck, `/data` volume for the SQLite file):

```bash
docker build -t billbook .
docker run --rm -p 8100:8100 -v billbook-data:/data billbook
```

## Demo credentials

| Role | Email | Password | Can do |
| --- | --- | --- | --- |
| owner | `demo@billbook.dev` | `demo12345` | everything |
| staff (invite one) | via Settings → Team | — | bill, take payments, adjust stock |
| accountant (invite one) | via Settings → Team | — | read-only, including reports |

## What is actually implemented

**Multi-tenancy by construction.** `tenant_id` is read from the verified JWT on every request and
threaded into every query — never from a header, query string or body. A row belonging to another
tenant returns **404, not 403**, so the API does not confirm that someone else's invoice exists.
Tests: three separate cross-tenant probes (invoice, PDF, item) plus a staff-of-another-tenant probe.

**The GST engine is pure and boring on purpose.** `app/gst.py` has no imports from the app and no
I/O: `price_line()` and `compute_invoice()` take dataclasses and return dataclasses. Everything is
integer **paise** internally; rupees appear only in the JSON/PDF layer. Rules:

| Rule | Behaviour |
| --- | --- |
| Intra-state (POS = seller state) | `CGST = round(taxable × rate/200)`, `SGST = total_tax − CGST` |
| Inter-state | `IGST = round(taxable × rate/100)`, CGST = SGST = 0 |
| Line discount | percentage of the line's gross value, applied before tax |
| Tax-inclusive prices | taxable value back-computed: `net × 100 / (100 + rate + cess)` |
| Compensation cess | extra percentage on taxable value |
| Round-off | invoice total rounded to the nearest rupee (half-up), as its own signed line |
| HSN summary | HSN × rate rollup printed on the PDF and in the report |

The SGST value is derived as `total_tax − CGST` rather than rounded independently. That single
line is why `CGST + SGST == tax` exactly, on every line, for every rate — a property asserted over
200 randomly generated invoices.

**Numbering is gapless under concurrency.** `INV/<FY>/0001`, scoped per tenant per financial year
(April–March), allocated inside the same `BEGIN IMMEDIATE` transaction as the insert, with
`UNIQUE(tenant_id, fy, seq)` as the backstop. The test that matters: 10 threads × 2 invoices each,
separate connections, one tenant → 20 unique numbers `0001…0020`, no gaps, no duplicates.

**Inventory is a ledger, not a counter.** Issuing an invoice decrements stock and writes a
`stock_moves` row; cancelling restores it and writes another. `GET /api/items?low_stock=true` feeds
the reorder alerts. Insufficient stock fails the whole invoice with `409` *inside* the transaction,
so a failed bill never leaves a half-written stock change behind.

**Payments are test-mode only, and that is enforced.** With no keys, orders are simulated locally
(`order_sim_…`) using the identical HMAC scheme Razorpay uses:
`HMAC_SHA256(order_id|payment_id, key_secret)`, compared with `hmac.compare_digest`. With
`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` set to `rzp_test_…` values, real test-mode orders are
created over HTTPS. A key starting with `rzp_live_` is refused at request time. Verified by tests:
forged signature → 400 and the attempt is recorded as `failed`; a payment id replayed on a second
invoice → 409; retried callback on the same payment → idempotent 200.

**The PDF is a real tax invoice.** Seller GSTIN, place of supply, supply type, HSN column, rate-wise
tax summary, round-off line, amount in words in Indian numbering (`Rupees One Lakh …`), and a
declaration block. Deterministic bytes for the same invoice. The currency reads **"Rs."**, not ₹,
because the ₹ glyph needs a Unicode TTF file and this project refuses a runtime font dependency —
a documented trade-off, not an oversight.

**Every response is measurable.** `X-Request-ID`, `X-Response-Time-ms`, `Server-Timing` headers;
`GET /health` returns p50/p95/max latency computed from the last 500 instrumented requests in the
current process, plus DB counters and the payment mode. The admin dashboard prints those numbers.

## RBAC matrix (enforced, then tested)

| Endpoint group | owner | staff | accountant |
| --- | --- | --- | --- |
| items: read | ✅ | ✅ | ✅ |
| items: create / edit | ✅ | ❌ 403 | ❌ 403 |
| stock adjust | ✅ | ✅ | ❌ 403 |
| invoices: create / read / PDF | ✅ | ✅ | read only |
| invoices: cancel | ✅ | ❌ 403 | ❌ 403 |
| payments: order / verify | ✅ | ✅ | ❌ 403 |
| reports: summary / GST | ✅ | ❌ 403 | ✅ |
| team: invite, list | ✅ | ❌ 403 | ❌ 403 |

Roles are re-read from the database on every request, so demoting a user takes effect immediately
instead of when their token expires (there is a test for that).

## API

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/auth/register` | creates tenant + owner, returns a token |
| `POST` | `/api/auth/login` | `{email, password}` → token |
| `GET` | `/api/auth/me`, `/api/auth/tenant` | identity after a page reload |
| `GET`/`POST` | `/api/auth/users` | owner-only team management |
| `GET` | `/api/items?q=&low_stock=&include_inactive=` | search / reorder feed |
| `POST` | `/api/items` | owner only |
| `PATCH` | `/api/items/{id}` | owner only |
| `POST` | `/api/items/{id}/stock` | `{delta, reason}` signed adjustment |
| `GET` | `/api/items/{id}/ledger` | full `stock_moves` history |
| `GET` | `/api/invoices?status=&limit=&offset=` | newest first |
| `GET` | `/api/invoices/next-number` | preview of the number that will be issued |
| `POST` | `/api/invoices` | lines may reference items or be free-form |
| `GET` | `/api/invoices/{id}` | lines, tax breakup, HSN summary, payments |
| `POST` | `/api/invoices/{id}/cancel` | owner only; restores stock |
| `GET` | `/api/invoices/{id}/pdf` | `application/pdf`, deterministic filename |
| `POST` | `/api/payments/order` | Razorpay test-mode order (or local simulation) |
| `POST` | `/api/payments/verify` | HMAC check → invoice flips to `paid` |
| `POST` | `/api/payments/{order_id}/simulate` | test-mode only: returns a signed callback |
| `GET` | `/api/payments/{invoice_id}/history` | attempts incl. failures |
| `GET` | `/api/reports/summary?days=` | sales, tax, paid vs outstanding, top items, low stock |
| `GET` | `/api/reports/gst?fy=&month=` | rate-wise, B2B/B2C, intra/inter |
| `GET` | `/health`, `/api/meta` | metrics and configuration |

## Numbers measured in this repo

| Claim | Value | How to reproduce |
| --- | --- | --- |
| Tests | **143 passing**, 7 files, ~6 s | `pytest` |
| Coverage of `app/` | **92%** (120 uncovered of 1,430 statements) | `pytest --cov=app` |
| GST money-math tests | 47 cases incl. a 200-invoice randomised property test | `pytest tests/test_gst.py` |
| Auth / RBAC / isolation | 27 cases | `pytest tests/test_auth_rbac.py` |
| Invoice + numbering + inventory | 25 cases | `pytest tests/test_invoices.py` |
| Payments (signature forgery, replay, idempotency) | 12 cases | `pytest tests/test_payments.py` |
| PDF (valid file, facts, determinism) | 14 cases | `pytest tests/test_pdf.py` |
| Reports | 11 cases | `pytest tests/test_reports.py` |
| Health/observability | 7 cases | `pytest tests/test_health.py` |
| Concurrent numbering | 10 threads × 2 → 20/20 unique, gapless | `pytest tests/test_invoices.py -k concurrent` |
| Demo dataset | 1 tenant, 8 items, 8 invoices (3 paid, 1 cancelled) | `python -m scripts.seed --reset` |

There is no deployed public URL: this repo is the source of truth, and the container runs anywhere
(`docker build && docker run` above). A previous README style of pasting "deployed on Azure" before
deploying is exactly the kind of claim this project avoids.

## Out of scope (deliberate, so nobody is surprised)

- SEZ/export supplies, reverse charge, e-invoicing/IRN, advance receipts, TDS/TCS.
- Credit notes (a paid invoice cannot be cancelled — the API says so explicitly).
- Multi-currency, multi-branch, purchase-side GST (ITC) reconciliation.
- Real money: there is no live-key path and no webhook endpoint for live callbacks.
- Horizontal scale: SQLite in WAL mode is plenty for a shop, and the README says so instead of
  pretending Postgres is wired up.

## Layout

```
app/
  gst.py         pure tax engine: paise integers, splits, round-off, words
  security.py    PBKDF2 password hashing + HS256 JWT (stdlib only, alg checked)
  db.py          schema, BEGIN IMMEDIATE transactions, audit helper
  numbering.py   financial year + gapless INV/<FY>/<seq>
  services.py    tenant-scoped business logic (the only place that writes)
  pdf.py         fpdf2 invoice renderer
  payments.py    Razorpay test mode, HMAC verify, replay protection
  deps.py        per-request DB connection, JWT gate, role guards
  routers/       auth · items · invoices · payments · reports · health
static/          admin UI (index.html, app.js, styles.css) — no build step
scripts/seed.py  deterministic demo shop, uses the service layer (not raw SQL)
tests/           pytest suites, one SQLite file per test
```
