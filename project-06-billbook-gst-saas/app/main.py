"""Application factory.

Keeping the app behind `create_app()` is what makes the test suite able to spin up a
throwaway SQLite file per test module, and what lets `scripts/seed.py` reuse the
exact same settings the server uses.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings, get_settings
from .db import connect, init_db
from .gst import VALID_GST_RATES, GstError
from .numbering import financial_year
from .routers import auth, health, invoices, items, payments, reports
from .services import NotFound

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved
        app.state.latencies = deque(maxlen=500)
        app.state.started_at = time.time()
        conn = connect(resolved.db_path)
        try:
            init_db(conn)
        finally:
            conn.close()
        yield

    app = FastAPI(
        title="BillBook",
        version=__version__,
        description="Multi-tenant GST invoicing & inventory SaaS. Test-mode payments only.",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ #
    # middleware: one request id and one measured duration per request
    # ------------------------------------------------------------------ #
    @app.middleware("http")
    async def measure(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        route = request.scope.get("path", "?")
        if request.url.path.startswith("/api") or request.url.path == "/health":
            app.state.latencies.append((route, elapsed_ms))
        return response

    # ------------------------------------------------------------------ #
    # error shape: {"detail": str, "code": str} for everything
    # ------------------------------------------------------------------ #
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "body"
        message = first.get("msg", "invalid request")
        return JSONResponse(
            status_code=422,
            content={"detail": f"{field}: {message}", "code": "validation_error",
                     "errors": exc.errors()[:5]},
        )

    @app.exception_handler(GstError)
    async def gst_handler(request: Request, exc: GstError):
        return JSONResponse(status_code=422, content={"detail": str(exc), "code": "gst_error"})

    @app.exception_handler(NotFound)
    async def not_found_handler(request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc), "code": "not_found"})

    # ------------------------------------------------------------------ #
    # routes
    # ------------------------------------------------------------------ #
    for module in (auth, items, invoices, payments, reports, health):
        app.include_router(module.router)

    @app.get("/api/meta", tags=["system"])
    def meta(request: Request):
        settings: Settings = request.app.state.settings
        return {
            "version": __version__,
            "financial_year": financial_year(),
            "gst_rates": [float(rate) for rate in VALID_GST_RATES],
            "currency": settings.currency,
            "payments": {"mode": settings.payment_label, "live_keys": settings.live_payments},
            "roles": ["owner", "staff", "accountant"],
        }

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def admin():
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
