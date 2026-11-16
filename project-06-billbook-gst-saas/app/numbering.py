"""Financial-year logic and gapless invoice numbering.

`INV/2026-27/0001`, scoped per tenant per financial year (1 April – 31 March).
The number is allocated *inside* the same IMMEDIATE transaction as the invoice
insert, and a `UNIQUE(tenant_id, fy, seq)` constraint is the backstop: if two
requests ever raced, one of them would get an IntegrityError and retry rather
than silently reuse a number.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime


class NumberingError(RuntimeError):
    pass


def financial_year(when: date | datetime | None = None) -> str:
    """Indian financial year label, e.g. 2026-04-01 → '2026-27'."""
    day = when or date.today()
    if isinstance(day, datetime):
        day = day.date()
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def format_invoice_number(fy: str, seq: int) -> str:
    if seq <= 0:
        raise NumberingError("seq must be positive")
    return f"INV/{fy}/{seq:04d}"


def next_sequence(conn: sqlite3.Connection, tenant_id: int, fy: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS last FROM invoices WHERE tenant_id = ? AND fy = ?",
        (tenant_id, fy),
    ).fetchone()
    return int(row["last"]) + 1


def peek_next_number(conn: sqlite3.Connection, tenant_id: int, fy: str) -> str:
    """What the next invoice number *would* be — used by the admin UI preview."""
    return format_invoice_number(fy, next_sequence(conn, tenant_id, fy))
