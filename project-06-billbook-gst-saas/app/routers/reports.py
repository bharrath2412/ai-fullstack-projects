"""Reports: the numbers an accountant asks for on the 11th of the month."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import Principal, get_db, require_roles
from ..services import Conflict, gst_report, sales_summary

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/summary")
def summary(
    days: int = Query(default=30, ge=1, le=366),
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "accountant")),
):
    return sales_summary(conn, user.tenant_id, days=days)


@router.get("/gst")
def gst(
    fy: str | None = Query(default=None, pattern=r"^\d{4}$|^\d{4}-\d{2}$",
                           description="Financial year label, e.g. 2026-27"),
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$",
                              description="Optional YYYY-MM slice inside the FY"),
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner", "accountant")),
):
    try:
        return gst_report(conn, user.tenant_id, fy=fy, month=month)
    except Conflict as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
