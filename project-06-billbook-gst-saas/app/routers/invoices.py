"""Invoices: create, list, inspect, cancel, and download as PDF."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..deps import Principal, get_db, require_roles
from ..pdf import invoice_filename, render_invoice_pdf
from ..schemas import InvoiceIn
from ..services import (
    Conflict,
    NotFound,
    cancel_invoice,
    create_invoice,
    get_invoice,
    get_tenant,
    list_invoices,
    next_invoice_preview,
)
from ..payments import list_payments

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("")
def index(
    status_filter: str | None = Query(default=None, alias="status",
                                       description="issued | paid | cancelled"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff", "accountant")),
):
    return list_invoices(conn, user.tenant_id, status=status_filter, limit=limit, offset=offset)


@router.get("/next-number")
def next_number(
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff")),
):
    return next_invoice_preview(conn, user.tenant_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create(
    payload: InvoiceIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff")),
):
    try:
        return create_invoice(
            conn,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            customer_name=payload.customer_name,
            customer_gstin=payload.customer_gstin,
            customer_state_code=payload.customer_state_code,
            place_of_supply=payload.place_of_supply,
            notes=payload.notes,
            lines=payload.lines,
        )
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{invoice_id}")
def show(
    invoice_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff", "accountant")),
):
    try:
        invoice = get_invoice(conn, user.tenant_id, invoice_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invoice["payments"] = list_payments(conn, user.tenant_id, invoice_id)
    return invoice


@router.post("/{invoice_id}/cancel")
def cancel(
    invoice_id: int,
    reason: str = Query(default="cancelled by owner", max_length=200),
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner")),
):
    try:
        return cancel_invoice(conn, tenant_id=user.tenant_id, user_id=user.user_id,
                              invoice_id=invoice_id, reason=reason)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{invoice_id}/pdf")
def pdf(
    invoice_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff", "accountant")),
):
    try:
        invoice = get_invoice(conn, user.tenant_id, invoice_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tenant = get_tenant(conn, user.tenant_id)
    payload = render_invoice_pdf(invoice, tenant)
    filename = invoice_filename(invoice["number"])
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            # Deterministic bytes for the same invoice → cheap caching for the browser.
            "Cache-Control": "private, max-age=60",
        },
    )
