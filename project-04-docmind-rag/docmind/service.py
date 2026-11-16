"""FastAPI app for DocMind RAG.

    python -m docmind.ingest              # build the index (or POST /ingest)
    uvicorn docmind.service:app --port 8200
    open http://localhost:8200            # chat UI with citations
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .rag import RAGPipeline

logging.basicConfig(level=settings.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("docmind")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATE: dict[str, Any] = {}


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=12)


class IngestRequest(BaseModel):
    persist: bool = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    pipeline = RAGPipeline.from_disk()
    STATE["pipeline"] = pipeline
    logger.info(
        "DocMind ready | chunks=%s embedding=%s generator=%s",
        len(pipeline.store.chunks),
        pipeline.embedder.name,
        pipeline.generator.name,
    )
    yield
    STATE.clear()


app = FastAPI(
    title="DocMind RAG",
    version="1.0.0",
    description="Hybrid retrieval (BM25 + dense + MMR) over your own markdown, with citations.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500, content={"error": {"code": "internal_error", "message": str(exc)}}
    )


def pipeline() -> RAGPipeline:
    if "pipeline" not in STATE:
        raise HTTPException(status_code=503, detail="pipeline still starting up")
    return STATE["pipeline"]


@app.get("/health")
async def health() -> dict[str, Any]:
    p = STATE.get("pipeline")
    return {
        "status": "ok" if p else "starting",
        "chunks": len(p.store.chunks) if p else 0,
        "embedding": p.embedder.name if p else None,
        "generator": p.generator.name if p else None,
    }


@app.get("/stats")
async def stats() -> dict[str, Any]:
    return pipeline().info()


@app.get("/documents")
async def documents() -> dict[str, Any]:
    p = pipeline()
    grouped: dict[str, dict[str, Any]] = {}
    for chunk in p.store.chunks:
        entry = grouped.setdefault(
            chunk.source, {"source": chunk.source, "chunks": 0, "headings": [], "chars": 0}
        )
        entry["chunks"] += 1
        entry["chars"] += chunk.char_count
        if chunk.heading and chunk.heading not in entry["headings"]:
            entry["headings"].append(chunk.heading)
    return {"items": list(grouped.values()), "total_chunks": len(p.store.chunks)}


@app.post("/ingest")
async def ingest(payload: IngestRequest | None = None) -> dict[str, Any]:
    body = payload or IngestRequest()
    result = pipeline().ingest(persist=body.persist)
    logger.info("re-ingested corpus: %s chunks", result["chunks"])
    return result


@app.post("/query")
async def query(payload: QueryRequest) -> dict[str, Any]:
    try:
        return pipeline().query(payload.question, top_k=payload.top_k).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/query/stream")
async def query_stream(payload: QueryRequest) -> StreamingResponse:
    p = pipeline()

    async def events():
        try:
            async for event in p.stream(payload.question, top_k=payload.top_k):
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
        except ValueError as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
        finally:
            yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/evaluate")
async def evaluate_endpoint() -> dict[str, Any]:
    from .evaluate import evaluate

    return evaluate(pipeline()).to_dict()


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
