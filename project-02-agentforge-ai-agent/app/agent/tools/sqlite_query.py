"""Read-only SQL tool over a sandboxed SQLite demo database.

Defence in depth:
  1. the file is opened with `mode=ro` (SQLite itself refuses writes)
  2. the statement must parse as a single SELECT/WITH query
  3. write/DDL keywords are rejected before execution
  4. results are truncated to `sql_max_rows`
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from ...config import settings
from .base import Tool, ToolError

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|trigger)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"(--[^\n]*\n)|(/\*.*?\*/)", re.DOTALL)


def _validate(sql: str) -> str:
    cleaned = _COMMENT.sub(" ", sql).strip().rstrip(";").strip()
    if not cleaned:
        raise ToolError("SQL statement is empty")
    if ";" in cleaned:
        raise ToolError("Only one statement per call is allowed")
    if _FORBIDDEN.search(cleaned):
        raise ToolError("Only read-only SELECT/WITH queries are allowed")
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise ToolError("Query must start with SELECT or WITH")
    return cleaned


def describe_schema() -> str:
    """Compact schema string used in tool descriptions / prompts."""
    path = Path(settings.sqlite_path)
    if not path.exists():
        return "(database not initialised)"
    lines: list[str] = []
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ):
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info('{name}')")]
            lines.append(f"{name}({', '.join(cols)})")
    return "\n".join(lines)


def run_query(sql: str, max_rows: int | None = None) -> tuple[list[str], list[tuple[Any, ...]]]:
    statement = _validate(sql)
    limit = max_rows or settings.sql_max_rows
    path = Path(settings.sqlite_path)
    if not path.exists():
        raise ToolError("Demo database not found. Run `python -m app.data.seed` first.")

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(statement)
        rows = cursor.fetchmany(limit)
        columns = [d[0] for d in cursor.description or []]
        return columns, [tuple(row) for row in rows]
    except sqlite3.Error as exc:
        raise ToolError(f"SQL error: {exc}") from exc
    finally:
        conn.close()


def format_table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not columns:
        return "(no columns returned)"
    formatted = [columns] + [[("NULL" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(str(line[i])) for line in formatted) for i in range(len(columns))]
    lines = [
        " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(formatted[0])),
        "-+-".join("-" * w for w in widths),
    ]
    for row in formatted[1:]:
        lines.append(" | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
    if not rows:
        lines.append("(0 rows)")
    return "\n".join(lines)


async def sqlite_query(sql: str, max_rows: int = 50) -> str:
    columns, rows = run_query(sql, max_rows=max_rows)
    table = format_table(columns, rows)
    suffix = f"\n({len(rows)} row(s) returned)" if len(rows) >= max_rows else ""
    return f"SQL: {sql.strip()}\n\n{table}{suffix}"


sqlite_tool = Tool(
    name="sqlite_query",
    description=(
        "Run a single read-only SELECT query against the demo company database. "
        "Tables: customers(id, name, country, signup_date, segment), "
        "products(id, name, category, unit_price), "
        "orders(id, customer_id, order_date, status, total), "
        "order_items(id, order_id, product_id, quantity, unit_price). "
        "Always aggregate in SQL and keep result sets small."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A single SELECT statement"},
            "max_rows": {"type": "integer", "description": "Rows to return (default 50, max 200)"},
        },
        "required": ["sql"],
    },
    func=sqlite_query,
    dangerous=True,
    max_output_chars=6000,
)
