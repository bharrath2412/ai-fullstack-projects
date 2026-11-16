"""Payment endpoints. Test mode only — see app/payments.py for the reasoning."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings
from ..deps import Principal, get_db, get_settings, require_roles
from ..payments import (
    PaymentError,
    create_order,
    list_payments,
    simulate_signed_callback,
    verify_and_capture,
)
from ..schemas import PaymentOrderIn, PaymentOrderOut, PaymentVerifyIn

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.post("/order", response_model=PaymentOrderOut)
def order(
    payload: PaymentOrderIn,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Principal = Depends(require_roles("owner", "staff")),
):
    try:
        return create_order(conn, settings, tenant_id=user.tenant_id, user_id=user.user_id,
                            invoice_id=payload.invoice_id)
    except PaymentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/verify")
def verify(
    payload: PaymentVerifyIn,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Principal = Depends(require_roles("owner", "staff")),
):
    try:
        return verify_and_capture(
            conn,
            settings,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            invoice_id=payload.invoice_id,
            order_id=payload.razorpay_order_id,
            payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
        )
    except PaymentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{order_id}/simulate")
def simulate(
    order_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: Principal = Depends(require_roles("owner", "staff")),
):
    """Test-mode stand-in for the Razorpay checkout: returns a signed callback."""
    try:
        return simulate_signed_callback(conn, settings, tenant_id=user.tenant_id, order_id=order_id)
    except PaymentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{invoice_id}/history")
def history(
    invoice_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff", "accountant")),
):
    try:
        return list_payments(conn, user.tenant_id, invoice_id)
    except PaymentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
