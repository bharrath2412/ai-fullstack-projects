"""Business logic between the HTTP layer and SQLite.

Every function takes `tenant_id` explicitly and every query filters on it. There
is no "current tenant" global: the value comes from the verified JWT and is
threaded down, so a forgotten filter is a visible bug in one function rather
than a global foot-gun.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Iterable

from .db import audit, now_iso, transaction
from .gst import (
    GstError,
    LineInput,
    compute_invoice,
    hsn_summary,
    tax_breakup,
    paise_to_rupees,
    rupees_in_words,
    to_paise,
    validate_rate,
)
from .numbering import financial_year, format_invoice_number, next_sequence
from .security import AuthError, hash_password, verify_password


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Forbidden(Exception):
    pass


# --------------------------------------------------------------------------- #
# serialisation helpers
# --------------------------------------------------------------------------- #
def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def serialize_tenant(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "gstin": row["gstin"],
        "state_code": row["state_code"],
        "address": row["address"],
    }


def serialize_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
    }


def serialize_item(row: sqlite3.Row) -> dict:
    stock = _dec(row["stock_qty"])
    reorder = _dec(row["reorder_level"])
    price_paise = int(row["unit_price_paise"])
    return {
        "id": row["id"],
        "sku": row["sku"],
        "name": row["name"],
        "hsn": row["hsn"],
        "unit": row["unit"],
        "unit_price": paise_to_rupees(price_paise),
        "unit_price_paise": price_paise,
        "gst_rate": float(_dec(row["gst_rate"])),
        "stock_qty": float(stock),
        "reorder_level": float(reorder),
        "low_stock": stock <= reorder,
        "stock_value": paise_to_rupees(int((stock * price_paise).to_integral_value())),
        "active": bool(row["active"]),
    }


def _invoice_row(conn: sqlite3.Connection, tenant_id: int, invoice_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM invoices WHERE id = ? AND tenant_id = ?", (invoice_id, tenant_id)
    ).fetchone()
    if row is None:
        # 404, never 403: a different tenant's invoice must not even be known to exist.
        raise NotFound("invoice not found")
    return row


def serialize_invoice(conn: sqlite3.Connection, row: sqlite3.Row, *, with_lines: bool = True) -> dict:
    payload = {
        "id": row["id"],
        "number": row["number"],
        "fy": row["fy"],
        "seq": row["seq"],
        "customer_name": row["customer_name"],
        "customer_gstin": row["customer_gstin"],
        "customer_state_code": row["customer_state_code"],
        "place_of_supply": row["place_of_supply"],
        "supply_type": row["supply_type"],
        "status": row["status"],
        "subtotal": paise_to_rupees(row["taxable_paise"]),
        "discount_total": paise_to_rupees(row["discount_paise"]),
        "cgst": paise_to_rupees(row["cgst_paise"]),
        "sgst": paise_to_rupees(row["sgst_paise"]),
        "igst": paise_to_rupees(row["igst_paise"]),
        "cess": paise_to_rupees(row["cess_paise"]),
        "round_off": paise_to_rupees(row["round_off_paise"]),
        "total": paise_to_rupees(row["total_paise"]),
        "total_paise": row["total_paise"],
        "notes": row["notes"],
        "issued_at": row["issued_at"],
        "paid_at": row["paid_at"],
        "cancelled_at": row["cancelled_at"],
        "amount_in_words": rupees_in_words(row["total_paise"]),
    }
    if with_lines:
        lines = conn.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY id", (row["id"],)
        ).fetchall()
        payload["lines"] = [
            {
                "id": line["id"],
                "item_id": line["item_id"],
                "description": line["description"],
                "hsn": line["hsn"],
                "qty": float(_dec(line["qty"])),
                "unit_price": paise_to_rupees(line["unit_price_paise"]),
                "discount_pct": float(_dec(line["discount_pct"])),
                "gst_rate": float(_dec(line["gst_rate"])),
                "cess_rate": float(_dec(line["cess_rate"])),
                "taxable_value": paise_to_rupees(line["taxable_paise"]),
                "cgst": paise_to_rupees(line["cgst_paise"]),
                "sgst": paise_to_rupees(line["sgst_paise"]),
                "igst": paise_to_rupees(line["igst_paise"]),
                "cess": paise_to_rupees(line["cess_paise"]),
                "line_total": paise_to_rupees(line["line_total_paise"]),
            }
            for line in lines
        ]
        as_lines = [
            SimpleNamespace(
                hsn=line["hsn"] or "",
                gst_rate=_dec(line["gst_rate"]),
                qty=_dec(line["qty"]),
                taxable_paise=line["taxable_paise"],
                cgst_paise=line["cgst_paise"],
                sgst_paise=line["sgst_paise"],
                igst_paise=line["igst_paise"],
                cess_paise=line["cess_paise"],
                tax_paise=line["cgst_paise"] + line["sgst_paise"] + line["igst_paise"],
            )
            for line in lines
        ]
        payload["tax_breakup"] = tax_breakup(as_lines)
        payload["hsn_summary"] = hsn_summary(as_lines)
    return payload


# --------------------------------------------------------------------------- #
# tenants, users, auth
# --------------------------------------------------------------------------- #
def get_tenant(conn: sqlite3.Connection, tenant_id: int) -> dict:
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if row is None:
        raise NotFound("tenant not found")
    return serialize_tenant(row)


def register_tenant(conn: sqlite3.Connection, *, tenant_name: str, state_code: str, gstin: str | None,
                    address: str | None, name: str, email: str, password: str) -> tuple[dict, dict]:
    if gstin and not gstin.startswith(state_code):
        raise ValueError("gstin must start with the tenant's state_code")
    email = email.strip().lower()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise Conflict("email already registered")
    created = now_iso()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO tenants (name, gstin, state_code, address, created_at) VALUES (?, ?, ?, ?, ?)",
            (tenant_name.strip(), gstin, state_code, address, created),
        )
        tenant_id = int(cursor.lastrowid)
        cursor = conn.execute(
            "INSERT INTO users (tenant_id, email, name, password_hash, role, created_at)"
            " VALUES (?, ?, ?, ?, 'owner', ?)",
            (tenant_id, email, name.strip(), hash_password(password), created),
        )
        user_id = int(cursor.lastrowid)
        audit(conn, tenant_id=tenant_id, user_id=user_id, action="tenant.created", entity="tenant",
              entity_id=tenant_id, meta=json.dumps({"tenant": tenant_name}))
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return serialize_user(user), get_tenant(conn, tenant_id)


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> tuple[dict, dict]:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        # Same message either way: don't reveal which emails exist.
        raise AuthError("invalid email or password")
    return serialize_user(row), get_tenant(conn, row["tenant_id"])


def create_staff_user(conn: sqlite3.Connection, *, tenant_id: int, actor_id: int, name: str, email: str,
                      password: str, role: str) -> dict:
    email = email.strip().lower()
    if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        raise Conflict("email already registered")
    created = now_iso()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO users (tenant_id, email, name, password_hash, role, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, email, name.strip(), hash_password(password), role, created),
        )
        user_id = int(cursor.lastrowid)
        audit(conn, tenant_id=tenant_id, user_id=actor_id, action="user.created", entity="user",
              entity_id=user_id, meta=json.dumps({"role": role}))
    return serialize_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def list_users(conn: sqlite3.Connection, tenant_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM users WHERE tenant_id = ? ORDER BY id", (tenant_id,)
    ).fetchall()
    return [serialize_user(row) for row in rows]


# --------------------------------------------------------------------------- #
# items & stock
# --------------------------------------------------------------------------- #
def list_items(conn: sqlite3.Connection, tenant_id: int, *, query: str | None = None,
               low_stock: bool = False, include_inactive: bool = False) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM items WHERE tenant_id = ? ORDER BY name COLLATE NOCASE", (tenant_id,)
    ).fetchall()
    items = [serialize_item(row) for row in rows]
    if not include_inactive:
        items = [item for item in items if item["active"]]
    if query:
        needle = query.strip().lower()
        items = [
            item for item in items
            if needle in item["name"].lower() or needle in item["sku"].lower()
            or needle in (item["hsn"] or "")
        ]
    if low_stock:
        items = [item for item in items if item["low_stock"]]
    return items


def get_item(conn: sqlite3.Connection, tenant_id: int, item_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM items WHERE id = ? AND tenant_id = ?", (item_id, tenant_id)
    ).fetchone()
    if row is None:
        raise NotFound("item not found")
    return row


def create_item(conn: sqlite3.Connection, *, tenant_id: int, user_id: int, sku: str, name: str,
                hsn: str | None, unit: str, unit_price: float, gst_rate: float, stock_qty: float,
                reorder_level: float) -> dict:
    validate_rate(gst_rate)
    sku = sku.strip()
    if conn.execute("SELECT id FROM items WHERE tenant_id = ? AND sku = ?", (tenant_id, sku)).fetchone():
        raise Conflict(f"sku {sku} already exists for this tenant")
    created = now_iso()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO items (tenant_id, sku, name, hsn, unit, unit_price_paise, gst_rate,"
            " stock_qty, reorder_level, active, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (tenant_id, sku, name.strip(), hsn, unit, to_paise(unit_price), str(Decimal(str(gst_rate))),
             str(Decimal(str(stock_qty))), str(Decimal(str(reorder_level))), created),
        )
        item_id = int(cursor.lastrowid)
        if Decimal(str(stock_qty)) != 0:
            conn.execute(
                "INSERT INTO stock_moves (tenant_id, item_id, delta, reason, ref_type, ref_id, created_at)"
                " VALUES (?, ?, ?, 'opening stock', 'item', ?, ?)",
                (tenant_id, item_id, str(Decimal(str(stock_qty))), item_id, created),
            )
        audit(conn, tenant_id=tenant_id, user_id=user_id, action="item.created", entity="item",
              entity_id=item_id, meta=json.dumps({"sku": sku}))
    return serialize_item(get_item(conn, tenant_id, item_id))


def update_item(conn: sqlite3.Connection, *, tenant_id: int, user_id: int, item_id: int,
                changes: dict[str, Any]) -> dict:
    row = get_item(conn, tenant_id, item_id)
    fields, values = [], []
    mapping = {
        "name": "name",
        "hsn": "hsn",
        "unit": "unit",
        "gst_rate": "gst_rate",
        "reorder_level": "reorder_level",
    }
    if changes.get("gst_rate") is not None:
        validate_rate(changes["gst_rate"])
    for key, column in mapping.items():
        if changes.get(key) is not None:
            value = changes[key]
            fields.append(f"{column} = ?")
            values.append(str(value) if column in {"gst_rate", "reorder_level"} else value)
    if changes.get("unit_price") is not None:
        fields.append("unit_price_paise = ?")
        values.append(to_paise(changes["unit_price"]))
    if changes.get("active") is not None:
        fields.append("active = ?")
        values.append(1 if changes["active"] else 0)
    if not fields:
        return serialize_item(row)
    values.extend([item_id, tenant_id])
    with transaction(conn):
        conn.execute(f"UPDATE items SET {', '.join(fields)} WHERE id = ? AND tenant_id = ?", values)
        audit(conn, tenant_id=tenant_id, user_id=user_id, action="item.updated", entity="item",
              entity_id=item_id, meta=json.dumps(changes, default=str))
    return serialize_item(get_item(conn, tenant_id, item_id))


def adjust_stock(conn: sqlite3.Connection, *, tenant_id: int, user_id: int, item_id: int,
                 delta: float, reason: str) -> dict:
    row = get_item(conn, tenant_id, item_id)
    change = Decimal(str(delta))
    new_qty = _dec(row["stock_qty"]) + change
    if new_qty < 0:
        raise Conflict("stock cannot go negative")
    created = now_iso()
    with transaction(conn):
        conn.execute("UPDATE items SET stock_qty = ? WHERE id = ? AND tenant_id = ?",
                     (str(new_qty), item_id, tenant_id))
        conn.execute(
            "INSERT INTO stock_moves (tenant_id, item_id, delta, reason, ref_type, ref_id, created_at)"
            " VALUES (?, ?, ?, ?, 'manual', NULL, ?)",
            (tenant_id, item_id, str(change), reason.strip()[:120] or "manual adjustment", created),
        )
        audit(conn, tenant_id=tenant_id, user_id=user_id, action="stock.adjusted", entity="item",
              entity_id=item_id, meta=json.dumps({"delta": str(change), "reason": reason}))
    return serialize_item(get_item(conn, tenant_id, item_id))


def stock_ledger(conn: sqlite3.Connection, tenant_id: int, item_id: int, limit: int = 50) -> list[dict]:
    get_item(conn, tenant_id, item_id)  # 404s for another tenant's item
    rows = conn.execute(
        "SELECT * FROM stock_moves WHERE item_id = ? AND tenant_id = ? ORDER BY id DESC LIMIT ?",
        (item_id, tenant_id, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "delta": float(_dec(row["delta"])),
            "reason": row["reason"],
            "ref_type": row["ref_type"],
            "ref_id": row["ref_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- #
# invoices
# --------------------------------------------------------------------------- #
def _resolve_lines(conn: sqlite3.Connection, tenant_id: int, payload_lines: Iterable[Any]) -> list[LineInput]:
    """Turn API lines into engine lines, filling price/rate from the item master."""
    resolved: list[LineInput] = []
    for line in payload_lines:
        data = line.model_dump() if hasattr(line, "model_dump") else dict(line)
        item_row = None
        if data.get("item_id") is not None:
            item_row = get_item(conn, tenant_id, int(data["item_id"]))  # tenant-scoped 404
        unit_price = data.get("unit_price")
        gst_rate = data.get("gst_rate")
        description = data.get("description")
        hsn = data.get("hsn")
        if item_row is not None:
            unit_price = unit_price if unit_price is not None else paise_to_rupees(item_row["unit_price_paise"])
            gst_rate = gst_rate if gst_rate is not None else float(_dec(item_row["gst_rate"]))
            description = description or item_row["name"]
            hsn = hsn or item_row["hsn"]
        if data.get("item_id") is None and (unit_price is None or not description):
            raise GstError("a manual line needs a description and a unit_price")
        resolved.append(
            LineInput(
                description=str(description or ""),
                qty=Decimal(str(data["qty"])),
                unit_price_rupees=Decimal(str(unit_price)),
                gst_rate=Decimal(str(gst_rate)),
                discount_pct=Decimal(str(data.get("discount_pct") or 0)),
                cess_rate=Decimal(str(data.get("cess_rate") or 0)),
                hsn=hsn or "",
                price_inclusive=bool(data.get("price_inclusive")),
                item_id=data.get("item_id"),
            )
        )
    return resolved


def next_invoice_preview(conn: sqlite3.Connection, tenant_id: int) -> dict:
    fy = financial_year()
    return {"fy": fy, "next_number": format_invoice_number(fy, next_sequence(conn, tenant_id, fy))}


def create_invoice(conn: sqlite3.Connection, *, tenant_id: int, user_id: int, customer_name: str,
                   customer_gstin: str | None, customer_state_code: str | None,
                   place_of_supply: str | None, notes: str | None, lines: list[Any]) -> dict:
    tenant = get_tenant(conn, tenant_id)
    pos = (place_of_supply or customer_state_code
           or (customer_gstin[:2] if customer_gstin else tenant["state_code"]))
    engine_lines = _resolve_lines(conn, tenant_id, lines)
    try:
        totals = compute_invoice(engine_lines, seller_state_code=tenant["state_code"], place_of_supply=pos)
    except GstError as exc:
        raise Conflict(str(exc)) from exc

    today = date.today()
    fy = financial_year(today)
    issued_at = now_iso()

    for attempt in range(1, 4):
        try:
            with transaction(conn):
                seq = next_sequence(conn, tenant_id, fy)
                number = format_invoice_number(fy, seq)
                cursor = conn.execute(
                    "INSERT INTO invoices (tenant_id, number, fy, seq, customer_name, customer_gstin,"
                    " customer_state_code, place_of_supply, supply_type, status, taxable_paise,"
                    " discount_paise, cgst_paise, sgst_paise, igst_paise, cess_paise, round_off_paise,"
                    " total_paise, notes, created_by, issued_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tenant_id, number, fy, seq, customer_name.strip(), customer_gstin,
                     customer_state_code or pos, pos, totals.supply_type, totals.taxable_paise,
                     totals.discount_paise, totals.cgst_paise, totals.sgst_paise, totals.igst_paise,
                     totals.cess_paise, totals.round_off_paise, totals.total_paise, notes, user_id,
                     issued_at),
                )
                invoice_id = int(cursor.lastrowid)

                for line in totals.lines:
                    conn.execute(
                        "INSERT INTO invoice_lines (invoice_id, tenant_id, item_id, description, hsn, qty,"
                        " unit_price_paise, discount_pct, gst_rate, cess_rate, taxable_paise, cgst_paise,"
                        " sgst_paise, igst_paise, cess_paise, line_total_paise)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (invoice_id, tenant_id, line.item_id, line.description, line.hsn or None,
                         str(line.qty), line.unit_price_paise, str(line.discount_pct),
                         str(line.gst_rate), str(line.cess_rate), line.taxable_paise, line.cgst_paise,
                         line.sgst_paise, line.igst_paise, line.cess_paise, line.line_total_paise),
                    )
                    if line.item_id is not None:
                        _decrement_stock(conn, tenant_id=tenant_id, item_id=line.item_id,
                                         qty=line.qty, invoice_id=invoice_id, when=issued_at)

                audit(conn, tenant_id=tenant_id, user_id=user_id, action="invoice.issued",
                      entity="invoice", entity_id=invoice_id,
                      meta=json.dumps({"number": number, "total_paise": totals.total_paise}))
            return serialize_invoice(conn, _invoice_row(conn, tenant_id, invoice_id))
        except sqlite3.IntegrityError as exc:
            # Unique (tenant_id, fy, seq) tripped → another writer took the number. Retry.
            if "invoices.tenant_id, invoices.fy, invoices.seq" in str(exc) or "UNIQUE" in str(exc).upper():
                if attempt == 3:
                    raise Conflict("could not allocate an invoice number, please retry") from exc
                continue
            raise Conflict(str(exc)) from exc
    raise Conflict("could not allocate an invoice number, please retry")  # pragma: no cover


def _decrement_stock(conn: sqlite3.Connection, *, tenant_id: int, item_id: int, qty: Decimal,
                     invoice_id: int, when: str) -> None:
    row = conn.execute(
        "SELECT stock_qty FROM items WHERE id = ? AND tenant_id = ?", (item_id, tenant_id)
    ).fetchone()
    if row is None:
        raise NotFound("item not found")
    available = _dec(row["stock_qty"])
    if available < qty:
        raise Conflict(f"insufficient stock: have {available}, need {qty}")
    conn.execute("UPDATE items SET stock_qty = ? WHERE id = ? AND tenant_id = ?",
                 (str(available - qty), item_id, tenant_id))
    conn.execute(
        "INSERT INTO stock_moves (tenant_id, item_id, delta, reason, ref_type, ref_id, created_at)"
        " VALUES (?, ?, ?, 'sold', 'invoice', ?, ?)",
        (tenant_id, item_id, str(-qty), invoice_id, when),
    )


def list_invoices(conn: sqlite3.Connection, tenant_id: int, *, status: str | None = None,
                  limit: int = 50, offset: int = 0) -> list[dict]:
    sql = "SELECT * FROM invoices WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY issued_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(limit, 200)), max(0, offset)])
    rows = conn.execute(sql, params).fetchall()
    return [serialize_invoice(conn, row, with_lines=False) for row in rows]


def get_invoice(conn: sqlite3.Connection, tenant_id: int, invoice_id: int) -> dict:
    return serialize_invoice(conn, _invoice_row(conn, tenant_id, invoice_id))


def cancel_invoice(conn: sqlite3.Connection, *, tenant_id: int, user_id: int, invoice_id: int,
                   reason: str = "cancelled by owner") -> dict:
    row = _invoice_row(conn, tenant_id, invoice_id)
    if row["status"] == "cancelled":
        raise Conflict("invoice is already cancelled")
    if row["status"] == "paid":
        raise Conflict("a paid invoice cannot be cancelled; issue a credit note instead")
    when = now_iso()
    with transaction(conn):
        conn.execute("UPDATE invoices SET status = 'cancelled', cancelled_at = ? WHERE id = ? AND tenant_id = ?",
                     (when, invoice_id, tenant_id))
        lines = conn.execute(
            "SELECT item_id, qty FROM invoice_lines WHERE invoice_id = ? AND item_id IS NOT NULL",
            (invoice_id,),
        ).fetchall()
        for line in lines:
            item = conn.execute("SELECT stock_qty FROM items WHERE id = ? AND tenant_id = ?",
                                (line["item_id"], tenant_id)).fetchone()
            if item is None:
                continue
            restored = _dec(item["stock_qty"]) + _dec(line["qty"])
            conn.execute("UPDATE items SET stock_qty = ? WHERE id = ? AND tenant_id = ?",
                         (str(restored), line["item_id"], tenant_id))
            conn.execute(
                "INSERT INTO stock_moves (tenant_id, item_id, delta, reason, ref_type, ref_id, created_at)"
                " VALUES (?, ?, ?, 'invoice cancelled', 'invoice', ?, ?)",
                (tenant_id, line["item_id"], str(_dec(line["qty"])), invoice_id, when),
            )
        audit(conn, tenant_id=tenant_id, user_id=user_id, action="invoice.cancelled", entity="invoice",
              entity_id=invoice_id, meta=json.dumps({"reason": reason}))
    return get_invoice(conn, tenant_id, invoice_id)


def mark_invoice_paid(conn: sqlite3.Connection, *, tenant_id: int, invoice_id: int, user_id: int | None,
                      payment_id: int | None = None) -> dict:
    row = _invoice_row(conn, tenant_id, invoice_id)
    if row["status"] == "cancelled":
        raise Conflict("cannot pay a cancelled invoice")
    when = now_iso()
    with transaction(conn):
        conn.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ? AND tenant_id = ?",
                     (when, invoice_id, tenant_id))
        audit(conn, tenant_id=tenant_id, user_id=user_id, action="invoice.paid", entity="invoice",
              entity_id=invoice_id, meta=json.dumps({"payment_id": payment_id}))
    return get_invoice(conn, tenant_id, invoice_id)


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
def sales_summary(conn: sqlite3.Connection, tenant_id: int, *, days: int = 30) -> dict:
    since = (datetime.now() - timedelta(days=days)).date().isoformat()
    rows = conn.execute(
        "SELECT * FROM invoices WHERE tenant_id = ? AND issued_at >= ?", (tenant_id, since)
    ).fetchall()
    issued = [row for row in rows if row["status"] != "cancelled"]

    def total(field: str) -> int:
        return sum(int(row[field]) for row in issued)

    daily: dict[str, dict] = {}
    for row in issued:
        day = row["issued_at"][:10]
        bucket = daily.setdefault(day, {"date": day, "invoices": 0, "total_paise": 0})
        bucket["invoices"] += 1
        bucket["total_paise"] += int(row["total_paise"])

    top_items = conn.execute(
        "SELECT l.description, COALESCE(i.sku, '') AS sku, SUM(l.line_total_paise) AS revenue_paise,"
        " SUM(CAST(l.qty AS REAL)) AS qty FROM invoice_lines l"
        " JOIN invoices inv ON inv.id = l.invoice_id"
        " LEFT JOIN items i ON i.id = l.item_id"
        " WHERE l.tenant_id = ? AND inv.status != 'cancelled' AND inv.issued_at >= ?"
        " GROUP BY l.description ORDER BY revenue_paise DESC LIMIT 5",
        (tenant_id, since),
    ).fetchall()

    low_stock = list_items(conn, tenant_id, low_stock=True)

    return {
        "window_days": days,
        "invoice_count": len(issued),
        "cancelled_count": len(rows) - len(issued),
        "gross_sales": paise_to_rupees(total("total_paise")),
        "taxable_value": paise_to_rupees(total("taxable_paise")),
        "tax_collected": paise_to_rupees(total("cgst_paise") + total("sgst_paise") + total("igst_paise")),
        "cess_collected": paise_to_rupees(total("cess_paise")),
        "paid_amount": paise_to_rupees(sum(int(row["total_paise"]) for row in issued if row["status"] == "paid")),
        "outstanding_amount": paise_to_rupees(
            sum(int(row["total_paise"]) for row in issued if row["status"] == "issued")
        ),
        "round_off_total": paise_to_rupees(total("round_off_paise")),
        "daily": [
            {"date": bucket["date"], "invoices": bucket["invoices"],
             "total": paise_to_rupees(bucket["total_paise"])}
            for bucket in sorted(daily.values(), key=lambda bucket: bucket["date"])
        ],
        "top_items": [
            {"description": row["description"], "sku": row["sku"],
             "revenue": paise_to_rupees(int(row["revenue_paise"] or 0)), "qty": round(row["qty"] or 0, 2)}
            for row in top_items
        ],
        "low_stock": low_stock,
    }


def gst_report(conn: sqlite3.Connection, tenant_id: int, *, fy: str | None = None,
               month: str | None = None) -> dict:
    """GSTR-1 shaped summary: rate-wise, HSN-wise, B2B/B2C, intra/inter."""
    target_fy = fy or financial_year()
    start_year = int(target_fy.split("-")[0])
    start = date(start_year, 4, 1)
    end = date(start_year + 1, 4, 1)
    if month:
        try:
            month_start = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise Conflict("month must be YYYY-MM") from exc
        start = month_start
        end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    rows = conn.execute(
        "SELECT * FROM invoices WHERE tenant_id = ? AND status != 'cancelled'"
        " AND issued_at >= ? AND issued_at < ? ORDER BY issued_at",
        (tenant_id, start.isoformat(), end.isoformat()),
    ).fetchall()

    def empty() -> dict:
        return {"invoices": 0, "invoice_ids": set(), "taxable_value_paise": 0, "cgst_paise": 0,
                "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0, "total_paise": 0}

    by_rate: dict[str, dict] = {}
    b2b = empty()
    b2c = empty()
    intra = empty()
    inter = empty()

    for row in rows:
        lines = conn.execute(
            "SELECT gst_rate, taxable_paise, cgst_paise, sgst_paise, igst_paise, cess_paise,"
            " line_total_paise FROM invoice_lines WHERE invoice_id = ?",
            (row["id"],),
        ).fetchall()
        for line in lines:
            key = str(_dec(line["gst_rate"]))
            bucket = by_rate.setdefault(key, empty())
            bucket["taxable_value_paise"] += int(line["taxable_paise"])
            bucket["cgst_paise"] += int(line["cgst_paise"])
            bucket["sgst_paise"] += int(line["sgst_paise"])
            bucket["igst_paise"] += int(line["igst_paise"])
            bucket["cess_paise"] += int(line["cess_paise"])
            bucket["total_paise"] += int(line["line_total_paise"])
            bucket["invoice_ids"].add(row["id"])
        target = b2b if row["customer_gstin"] else b2c
        for bucket in (target, intra if row["supply_type"] == "intra" else inter):
            bucket["invoices"] += 1
            bucket["invoice_ids"].add(row["id"])
            bucket["taxable_value_paise"] += int(row["taxable_paise"])
            bucket["cgst_paise"] += int(row["cgst_paise"])
            bucket["sgst_paise"] += int(row["sgst_paise"])
            bucket["igst_paise"] += int(row["igst_paise"])
            bucket["cess_paise"] += int(row["cess_paise"])
            bucket["total_paise"] += int(row["total_paise"])

    def render(bucket: dict) -> dict:
        return {
            "invoices": len(bucket["invoice_ids"]) or bucket["invoices"],
            "taxable_value": paise_to_rupees(bucket["taxable_value_paise"]),
            "cgst": paise_to_rupees(bucket["cgst_paise"]),
            "sgst": paise_to_rupees(bucket["sgst_paise"]),
            "igst": paise_to_rupees(bucket["igst_paise"]),
            "cess": paise_to_rupees(bucket["cess_paise"]),
            "total": paise_to_rupees(bucket["total_paise"]),
            "tax_total": paise_to_rupees(
                bucket["cgst_paise"] + bucket["sgst_paise"] + bucket["igst_paise"] + bucket["cess_paise"]
            ),
        }

    return {
        "fy": target_fy,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "by_rate": [
            {"gst_rate": float(key), **render(value)}
            for key, value in sorted(by_rate.items(), key=lambda pair: float(pair[0]))
        ],
        "b2b": render(b2b),
        "b2c": render(b2c),
        "intra_state": render(intra),
        "inter_state": render(inter),
        "invoice_count": len(rows),
    }
