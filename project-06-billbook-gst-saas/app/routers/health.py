"""Health + runtime metrics.

The p95 numbers here are *measured* by the middleware on real requests, not typed
into a README. They reset when the process restarts, which is the honest thing for
an in-memory buffer; the README says so.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request

from .. import __version__
from ..deps import get_db, get_settings
from ..config import Settings
from fastapi import Depends

router = APIRouter(tags=["system"])


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * len(ordered))) - 1))
    return round(ordered[index], 2)


@router.get("/health")
def health(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    db_ok = True
    counts = {"tenants": 0, "invoices": 0, "items": 0}
    try:
        counts["tenants"] = conn.execute("SELECT COUNT(*) AS n FROM tenants").fetchone()["n"]
        counts["invoices"] = conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
        counts["items"] = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
    except sqlite3.Error:
        db_ok = False

    samples: list[tuple[str, float]] = list(getattr(request.app.state, "latencies", []))
    durations = [ms for _, ms in samples]
    worst = sorted(samples, key=lambda pair: pair[1], reverse=True)[:3]

    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "db": {
            "ok": db_ok,
            "path": settings.db_path.split("/")[-1],
            "journal_mode": "wal" if settings.db_path != ":memory:" else "memory",
            **counts,
        },
        "payments": {"mode": settings.payment_label, "live_keys": settings.live_payments},
        "latency_ms": {
            "samples": len(durations),
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
            "max": round(max(durations), 2) if durations else 0.0,
            "slowest_routes": [{"route": route, "ms": round(ms, 2)} for route, ms in worst],
        },
    }
