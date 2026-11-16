"""FastAPI surface for AgentForge.

Endpoints
---------
GET  /                    -> minimal chat UI (static/index.html)
GET  /health              -> liveness + provider info
GET  /api/tools           -> tool manifests (what the agent can do)
POST /api/chat            -> full JSON answer with trace
POST /api/chat/stream     -> Server-Sent Events, live reasoning
GET  /api/sessions/{id}   -> conversation history
DEL  /api/sessions/{id}   -> forget a session
GET  /api/runs/{run_id}   -> full trace of one run
GET  /api/runs/recent     -> latest runs
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent.llm import get_llm
from .agent.memory import memory_store
from .agent.runtime import get_runtime
from .config import settings
from .data.seed import create_database
from .schemas import ChatRequest, ChatResponse, StepKind, ToolSpec

logging.basicConfig(level=settings.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agentforge")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    db_path = create_database()  # idempotent; seeds on first boot
    runtime = get_runtime()  # warm the registry / knowledge base
    logger.info(
        "AgentForge starting | provider=%s model=%s db=%s",
        runtime.llm.name,
        runtime.llm.model,
        db_path.name,
    )
    yield
    logger.info("AgentForge shutting down")


app = FastAPI(
    title="AgentForge",
    version="1.0.0",
    description="A tool-using AI agent service with guardrails, tracing and SSE streaming.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Unexpected server error"}},
    )


# --------------------------------------------------------------------------- #
# Basics
# --------------------------------------------------------------------------- #
@app.get("/health")
async def health() -> dict[str, Any]:
    runtime = get_runtime()
    return {
        "status": "ok",
        "provider": runtime.llm.name,
        "model": runtime.llm.model,
        "tools": [spec.name for spec in runtime.registry.specs()],
        "limits": {
            "max_steps": runtime.max_steps,
            "max_tool_calls": runtime.max_tool_calls,
        },
    }


@app.get("/api/tools", response_model=list[ToolSpec])
async def list_tools() -> list[ToolSpec]:
    return get_runtime().registry.specs()


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    session_id = payload.session_id or f"s_{uuid.uuid4().hex[:10]}"
    result = await get_runtime().run(payload.message, session_id, max_steps=payload.max_steps)
    return ChatResponse(
        session_id=session_id,
        run_id=result.run_id,
        answer=result.answer,
        steps=result.steps,
        tool_calls=result.tool_calls,
        duration_ms=result.duration_ms,
    )


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    session_id = payload.session_id or f"s_{uuid.uuid4().hex[:10]}"

    async def event_source():
        # Tell the client its session id before anything else.
        meta = {"type": "session", "session_id": session_id}
        yield f"event: session\ndata: {json.dumps(meta)}\n\n"
        try:
            async for event in get_runtime().stream(
                payload.message, session_id, max_steps=payload.max_steps
            ):
                if await request.is_disconnected():
                    logger.info("client disconnected from run in session %s", session_id)
                    return
                yield event.to_sse()
                await asyncio.sleep(0)  # cooperative yield keeps streaming smooth
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream failed")
            error = json.dumps({"message": f"{type(exc).__name__}: {exc}"})
            yield f"event: error\ndata: {error}\n\n"
        finally:
            yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Sessions & traces
# --------------------------------------------------------------------------- #
@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = await memory_store.get(session_id)
    return {
        "session_id": session.id,
        "runs": session.runs,
        "summary": session.summary,
        "messages": session.public_history(),
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    await memory_store.reset(session_id)
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/runs/recent")
async def recent_runs(limit: int = Query(default=10, ge=1, le=50)) -> dict[str, Any]:
    return {
        "items": [
            {
                "run_id": run.run_id,
                "session_id": run.session_id,
                "question": run.question,
                "tool_calls": run.tool_calls,
                "duration_ms": run.duration_ms,
                "answer_preview": run.answer[:180],
            }
            for run in get_runtime().recent_runs(limit)
        ]
    }


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = get_runtime().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found (traces are kept in memory)")
    return run.to_dict()


# --------------------------------------------------------------------------- #
# Static chat UI
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
