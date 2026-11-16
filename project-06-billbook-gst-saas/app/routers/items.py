"""Items and stock: the inventory half of the app."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import Principal, get_db, require_roles
from ..schemas import ItemIn, ItemPatch, StockAdjustIn
from ..services import (
    Conflict,
    adjust_stock,
    create_item,
    list_items,
    serialize_item,
    get_item,
    stock_ledger,
    update_item,
)

router = APIRouter(prefix="/api/items", tags=["items"])


@router.get("")
def index(
    q: str | None = Query(default=None, description="Search name, SKU or HSN"),
    low_stock: bool = Query(default=False, description="Only items at or below reorder level"),
    include_inactive: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff", "accountant")),
):
    return list_items(conn, user.tenant_id, query=q, low_stock=low_stock,
                      include_inactive=include_inactive)


@router.post("", status_code=status.HTTP_201_CREATED)
def create(
    payload: ItemIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner")),
):
    try:
        return create_item(
            conn,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            sku=payload.sku,
            name=payload.name,
            hsn=payload.hsn,
            unit=payload.unit,
            unit_price=payload.unit_price,
            gst_rate=payload.gst_rate,
            stock_qty=payload.stock_qty,
            reorder_level=payload.reorder_level,
        )
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{item_id}")
def show(
    item_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff", "accountant")),
):
    try:
        return serialize_item(get_item(conn, user.tenant_id, item_id))
    except Exception as exc:  # NotFound
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{item_id}")
def patch(
    item_id: int,
    payload: ItemPatch,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner")),
):
    try:
        return update_item(conn, tenant_id=user.tenant_id, user_id=user.user_id, item_id=item_id,
                            changes=payload.model_dump(exclude_none=True))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{item_id}/stock")
def stock(
    item_id: int,
    payload: StockAdjustIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff")),
):
    try:
        return adjust_stock(conn, tenant_id=user.tenant_id, user_id=user.user_id, item_id=item_id,
                            delta=payload.delta, reason=payload.reason)
    except Exception as exc:
        status_code = 409 if isinstance(exc, Conflict) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/{item_id}/ledger")
def ledger(
    item_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "staff", "accountant")),
):
    try:
        return stock_ledger(conn, user.tenant_id, item_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
