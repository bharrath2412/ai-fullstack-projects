"""Razorpay integration — test mode only, by construction.

Two modes, one code path:

* **simulated** (default, no keys): order ids are generated locally in Razorpay's
  shape (`order_sim_…`) and callbacks are signed with the same HMAC-SHA256 scheme
  Razorpay uses, `HMAC_SHA256(order_id + "|" + payment_id, key_secret)`. So the
  verification code tested here is the code that would run against real Razorpay.
* **razorpay-test** (`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` set): orders are
  created with a real signed HTTPS call to the Razorpay **test** endpoint. No live
  key is accepted: keys starting `rzp_live_` are refused at startup.

What is verified, in order: the order belongs to this tenant, the amount matches
the invoice, the signature is valid (constant-time compare), and the payment id
has not been used before (DB unique constraint → replay is a 409, not a second
"paid" invoice).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone

import httpx

from .config import Settings
from .db import audit, now_iso, transaction
from .gst import paise_to_rupees

RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class PaymentError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _row(conn: sqlite3.Connection, tenant_id: int, invoice_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM invoices WHERE id = ? AND tenant_id = ?", (invoice_id, tenant_id)
    ).fetchone()
    if row is None:
        raise PaymentError("invoice not found", status_code=404)
    return row


def sign(order_id: str, payment_id: str, secret: str) -> str:
    """The Razorpay callback signature: hex HMAC-SHA256 of `order_id|payment_id`."""
    return hmac.new(
        secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    if not signature or not order_id or not payment_id:
        return False
    expected = sign(order_id, payment_id, secret)
    return hmac.compare_digest(expected, signature.strip().lower())


def _assert_payable(row: sqlite3.Row) -> None:
    if row["status"] == "paid":
        raise PaymentError("invoice is already paid", status_code=409)
    if row["status"] == "cancelled":
        raise PaymentError("cannot pay a cancelled invoice", status_code=409)


def _create_razorpay_order(settings: Settings, *, amount_paise: int, receipt: str) -> str:
    if settings.razorpay_key_id.startswith("rzp_live_"):
        raise PaymentError("live Razorpay keys are refused; this project is test-mode only", status_code=500)
    payload = {
        "amount": amount_paise,
        "currency": settings.currency,
        "receipt": receipt[:40],
        "payment_capture": 1,
        "notes": {"source": "billbook", "mode": "test"},
    }
    try:
        response = httpx.post(
            RAZORPAY_ORDERS_URL,
            json=payload,
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise PaymentError(f"could not reach Razorpay: {exc}", status_code=502) from exc
    if response.status_code >= 400:
        raise PaymentError(f"Razorpay rejected the order ({response.status_code})", status_code=502)
    body = response.json()
    if not body.get("id"):
        raise PaymentError("Razorpay returned no order id", status_code=502)
    return str(body["id"])


def create_order(conn: sqlite3.Connection, settings: Settings, *, tenant_id: int, user_id: int,
                 invoice_id: int) -> dict:
    invoice = _row(conn, tenant_id, invoice_id)
    _assert_payable(invoice)
    amount = int(invoice["total_paise"])

    if settings.live_payments:
        order_id = _create_razorpay_order(settings, amount_paise=amount, receipt=invoice["number"])
        mode = "razorpay-test"
        note = "Razorpay test-mode order created. Complete it with a test card / UPI id."
    else:
        order_id = f"order_sim_{secrets.token_hex(8)}"
        mode = "simulated"
        note = ("Simulated order: no money moves. Use the simulate endpoint (or the UI's "
                "'Simulate payment' button) to produce a signed callback.")

    created = now_iso()
    with transaction(conn):
        conn.execute(
            "INSERT INTO payments (tenant_id, invoice_id, provider, provider_order_id, amount_paise,"
            " status, signature_verified, mode, created_at)"
            " VALUES (?, ?, 'razorpay', ?, ?, 'created', 0, ?, ?)",
            (tenant_id, invoice_id, order_id, amount, mode, created),
        )
        audit(conn, tenant_id=tenant_id, user_id=user_id, action="payment.order_created",
              entity="invoice", entity_id=invoice_id,
              meta=json.dumps({"order_id": order_id, "mode": mode, "amount_paise": amount}))

    return {
        "provider": "razorpay",
        "mode": mode,
        "key_id": settings.razorpay_key_id or "rzp_test_simulated",
        "order_id": order_id,
        "amount": amount,
        "currency": settings.currency,
        "invoice_id": invoice_id,
        "invoice_number": invoice["number"],
        "checkout_url": None if not settings.live_payments else "https://api.razorpay.com/v1/checkout",
        "note": note,
    }


def simulate_signed_callback(conn: sqlite3.Connection, settings: Settings, *, tenant_id: int,
                             order_id: str) -> dict:
    """Test-mode helper: produce the (payment_id, signature) pair Razorpay would send."""
    if settings.live_payments:
        raise PaymentError("simulation is disabled while real test keys are configured", status_code=403)
    payment = conn.execute(
        "SELECT * FROM payments WHERE provider_order_id = ? AND tenant_id = ?", (order_id, tenant_id)
    ).fetchone()
    if payment is None:
        raise PaymentError("order not found", status_code=404)
    payment_id = f"pay_sim_{secrets.token_hex(8)}"
    return {
        "order_id": order_id,
        "payment_id": payment_id,
        "signature": sign(order_id, payment_id, settings.payment_secret),
        "amount": payment["amount_paise"],
        "note": "Generated locally with the configured test secret; Razorpay would send the same shape.",
    }


def verify_and_capture(conn: sqlite3.Connection, settings: Settings, *, tenant_id: int, user_id: int,
                       invoice_id: int, order_id: str, payment_id: str, signature: str) -> dict:
    invoice = _row(conn, tenant_id, invoice_id)
    payment = conn.execute(
        "SELECT * FROM payments WHERE provider_order_id = ? AND tenant_id = ?", (order_id, tenant_id)
    ).fetchone()
    if payment is None:
        raise PaymentError("unknown order for this tenant", status_code=404)
    if int(payment["invoice_id"]) != int(invoice_id):
        raise PaymentError("order does not belong to this invoice", status_code=400)

    if payment["status"] == "captured" and payment["provider_payment_id"] == payment_id:
        # Idempotent: a retried webhook must not double-book anything.
        return _payment_state(conn, payment, invoice)

    if not verify_signature(order_id, payment_id, signature, settings.payment_secret):
        with transaction(conn):
            conn.execute("UPDATE payments SET status = 'failed', signature_verified = 0 WHERE id = ?",
                         (payment["id"],))
            audit(conn, tenant_id=tenant_id, user_id=user_id, action="payment.signature_rejected",
                  entity="invoice", entity_id=invoice_id,
                  meta=json.dumps({"order_id": order_id, "payment_id": payment_id}))
        raise PaymentError("signature verification failed", status_code=400)

    if int(payment["amount_paise"]) != int(invoice["total_paise"]):
        raise PaymentError("order amount does not match the invoice total", status_code=400)

    try:
        with transaction(conn):
            conn.execute(
                "UPDATE payments SET status = 'captured', provider_payment_id = ?,"
                " signature_verified = 1 WHERE id = ?",
                (payment_id, payment["id"]),
            )
            if invoice["status"] != "paid":
                conn.execute(
                    "UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ? AND tenant_id = ?",
                    (now_iso(), invoice_id, tenant_id),
                )
            audit(conn, tenant_id=tenant_id, user_id=user_id, action="payment.captured",
                  entity="invoice", entity_id=invoice_id,
                  meta=json.dumps({"order_id": order_id, "payment_id": payment_id,
                                   "amount_paise": int(payment["amount_paise"])}))
    except sqlite3.IntegrityError as exc:
        raise PaymentError("this payment id has already been used", status_code=409) from exc

    refreshed = _row(conn, tenant_id, invoice_id)
    return {
        "provider": "razorpay",
        "order_id": order_id,
        "payment_id": payment_id,
        "amount": paise_to_rupees(int(payment["amount_paise"])),
        "status": "captured",
        "signature_verified": True,
        "invoice_id": invoice_id,
        "invoice_status": refreshed["status"],
    }


def _payment_state(conn: sqlite3.Connection, payment: sqlite3.Row, invoice: sqlite3.Row) -> dict:
    return {
        "provider": payment["provider"],
        "order_id": payment["provider_order_id"],
        "payment_id": payment["provider_payment_id"],
        "amount": paise_to_rupees(int(payment["amount_paise"])),
        "status": payment["status"],
        "signature_verified": bool(payment["signature_verified"]),
        "invoice_id": int(invoice["id"]),
        "invoice_status": invoice["status"],
    }


def list_payments(conn: sqlite3.Connection, tenant_id: int, invoice_id: int) -> list[dict]:
    _row(conn, tenant_id, invoice_id)
    rows = conn.execute(
        "SELECT * FROM payments WHERE invoice_id = ? AND tenant_id = ? ORDER BY id DESC",
        (invoice_id, tenant_id),
    ).fetchall()
    return [
        {
            "order_id": row["provider_order_id"],
            "payment_id": row["provider_payment_id"],
            "amount": paise_to_rupees(int(row["amount_paise"])),
            "status": row["status"],
            "mode": row["mode"],
            "signature_verified": bool(row["signature_verified"]),
            "created_at": datetime.fromisoformat(row["created_at"]).astimezone(timezone.utc).isoformat(),
        }
        for row in rows
    ]
