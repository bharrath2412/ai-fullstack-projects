"""SQLite access layer: schema, connections, transactions.

Deliberate choices:

* Raw `sqlite3` instead of an ORM. The queries are the interesting part of a
  multi-tenant app (every one of them is tenant-scoped), so they are visible.
* `isolation_level=None` → we drive transactions explicitly with
  `BEGIN IMMEDIATE`, which takes the write lock up front. That is what makes
  concurrent invoice numbering safe instead of "safe most of the time".
* Money and quantities are stored as **integer paise** and **decimal strings**.
  SQLite has no decimal type; storing floats is how ₹0.01 disappears.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    gstin       TEXT,
    state_code  TEXT    NOT NULL,
    address     TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email         TEXT    NOT NULL UNIQUE,          -- login is global: email is the key
    name          TEXT,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('owner', 'staff', 'accountant')),
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

CREATE TABLE IF NOT EXISTS items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id        INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sku              TEXT    NOT NULL,
    name             TEXT    NOT NULL,
    hsn              TEXT,
    unit             TEXT    NOT NULL DEFAULT 'pcs',
    unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise >= 0),
    gst_rate         TEXT    NOT NULL,
    stock_qty        TEXT    NOT NULL DEFAULT '0',
    reorder_level    TEXT    NOT NULL DEFAULT '0',
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT    NOT NULL,
    UNIQUE (tenant_id, sku)
);

CREATE TABLE IF NOT EXISTS invoices (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id          INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    number             TEXT    NOT NULL,
    fy                 TEXT    NOT NULL,
    seq                INTEGER NOT NULL,
    customer_name      TEXT    NOT NULL,
    customer_gstin     TEXT,
    customer_state_code TEXT,
    place_of_supply    TEXT    NOT NULL,
    supply_type        TEXT    NOT NULL CHECK (supply_type IN ('intra', 'inter')),
    status             TEXT    NOT NULL CHECK (status IN ('issued', 'paid', 'cancelled')),
    taxable_paise      INTEGER NOT NULL,
    discount_paise     INTEGER NOT NULL DEFAULT 0,
    cgst_paise         INTEGER NOT NULL DEFAULT 0,
    sgst_paise         INTEGER NOT NULL DEFAULT 0,
    igst_paise         INTEGER NOT NULL DEFAULT 0,
    cess_paise         INTEGER NOT NULL DEFAULT 0,
    round_off_paise    INTEGER NOT NULL DEFAULT 0,
    total_paise        INTEGER NOT NULL,
    notes              TEXT,
    created_by         INTEGER REFERENCES users(id),
    issued_at          TEXT    NOT NULL,
    paid_at            TEXT,
    cancelled_at       TEXT,
    UNIQUE (tenant_id, fy, seq),
    UNIQUE (tenant_id, number)
);
CREATE INDEX IF NOT EXISTS idx_invoices_tenant_status ON invoices(tenant_id, status, issued_at);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id       INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    tenant_id        INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    item_id          INTEGER REFERENCES items(id),
    description      TEXT    NOT NULL,
    hsn              TEXT,
    qty              TEXT    NOT NULL,
    unit_price_paise INTEGER NOT NULL,
    discount_pct     TEXT    NOT NULL DEFAULT '0',
    gst_rate         TEXT    NOT NULL,
    cess_rate        TEXT    NOT NULL DEFAULT '0',
    taxable_paise    INTEGER NOT NULL,
    cgst_paise       INTEGER NOT NULL DEFAULT 0,
    sgst_paise       INTEGER NOT NULL DEFAULT 0,
    igst_paise       INTEGER NOT NULL DEFAULT 0,
    cess_paise       INTEGER NOT NULL DEFAULT 0,
    line_total_paise INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lines_invoice ON invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS idx_lines_tenant_item ON invoice_lines(tenant_id, item_id);

CREATE TABLE IF NOT EXISTS stock_moves (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    delta      TEXT    NOT NULL,
    reason     TEXT    NOT NULL,
    ref_type   TEXT,
    ref_id     INTEGER,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moves_item ON stock_moves(item_id, created_at);

CREATE TABLE IF NOT EXISTS payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_id          INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    provider            TEXT    NOT NULL DEFAULT 'razorpay',
    provider_order_id   TEXT    NOT NULL,
    provider_payment_id TEXT,
    amount_paise        INTEGER NOT NULL,
    status              TEXT    NOT NULL CHECK (status IN ('created', 'captured', 'failed')),
    signature_verified  INTEGER NOT NULL DEFAULT 0,
    mode                TEXT    NOT NULL DEFAULT 'test',
    created_at          TEXT    NOT NULL,
    UNIQUE (provider, provider_order_id),
    UNIQUE (provider, provider_payment_id)
);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    user_id    INTEGER,
    action     TEXT    NOT NULL,
    entity     TEXT    NOT NULL,
    entity_id  INTEGER,
    meta       TEXT,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit(tenant_id, created_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path, *, wal: bool = True) -> sqlite3.Connection:
    """Open a connection tuned for a small multi-tenant web app."""
    target = str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if wal and target != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE … COMMIT, rolling back on any exception.

    IMMEDIATE acquires the write lock at the start, so two concurrent invoice
    inserts serialise instead of both reading the same `MAX(seq)`.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def audit(conn: sqlite3.Connection, *, tenant_id: int, user_id: int | None, action: str,
          entity: str, entity_id: int | None = None, meta: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit (tenant_id, user_id, action, entity, entity_id, meta, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tenant_id, user_id, action, entity, entity_id, meta, now_iso()),
    )
