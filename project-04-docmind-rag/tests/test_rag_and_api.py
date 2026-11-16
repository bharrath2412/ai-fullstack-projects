"""Pipeline + HTTP tests: grounded answers, citations, guards, SSE, evaluation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from docmind.evaluate import evaluate
from docmind.rag import RAGPipeline
from docmind.service import app


@pytest.fixture(scope="module")
def pipeline():
    rag = RAGPipeline()
    rag.ingest(persist=False)  # returns stats; the pipeline is mutated in place
    return rag


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------- pipeline
def test_query_returns_grounded_answer_with_citations(pipeline):
    result = pipeline.query("What should I do when I receive a 429?")
    assert result.citations, "expected citations"
    assert result.grounded is True
    assert "[1]" in result.answer
    assert result.citations[0].index == 1
    assert result.citations[0].source
    lowered = result.answer.lower()
    assert "retry" in lowered or "backoff" in lowered


def test_query_reports_timings(pipeline):
    result = pipeline.query("Which plans include SSO?")
    assert {"retrieval_ms", "generation_ms", "total_ms"} <= set(result.timings)
    assert result.timings["total_ms"] >= result.timings["retrieval_ms"]


def test_irrelevant_question_is_not_hallucinated(pipeline):
    result = pipeline.query("What is the airspeed velocity of an unladen swallow?")
    assert not result.grounded or "couldn't find" in result.answer.lower()
    # citations may exist (retrieval always returns something) but the answer must not assert facts
    assert "swallow" in result.answer.lower() or "couldn't find" in result.answer.lower()


def test_question_guards(pipeline):
    with pytest.raises(ValueError):
        pipeline.query("   ")
    with pytest.raises(ValueError):
        pipeline.query("x" * 2000)


def test_ingest_reports_corpus_stats(pipeline):
    stats = pipeline.ingest(persist=False)
    assert stats["documents"] >= 4
    assert stats["chunks"] >= 15
    assert stats["dim"] == pipeline.embedder.dim
    assert "api-guide.md" in stats["per_document"]


def test_streaming_events(pipeline):
    import asyncio

    async def collect():
        return [event async for event in pipeline.stream("How long do tokens last?")]

    events = asyncio.run(collect())
    names = [event["event"] for event in events]
    assert names[0] == "retrieved"
    assert names[-1] == "done"
    assert "token" in names
    assert events[0]["data"]["citations"]
    assert events[-1]["data"]["answer"]


def test_evaluation_meets_the_gate(pipeline):
    report = evaluate(pipeline, k=5)
    assert report.hit_at_k >= 0.7
    assert report.mrr >= 0.5
    assert len(report.rows) >= 10


# ------------------------------------------------------------------- API
def test_health_and_stats(client):
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["chunks"] > 0

    stats = client.get("/stats").json()
    assert stats["store"]["chunks"] > 0
    assert stats["embedding"].startswith("hashing")


def test_documents_listing(client):
    body = client.get("/documents").json()
    sources = {item["source"] for item in body["items"]}
    assert {"api-guide.md", "runbook.md"} <= sources
    assert all(item["chunks"] > 0 for item in body["items"])


def test_query_endpoint(client):
    response = client.post("/query", json={"question": "How do I rotate a leaked API key?"})
    assert response.status_code == 200
    body = response.json()
    assert body["citations"]
    assert body["answer"]
    assert body["strategy"].startswith("hybrid")
    assert body["generator"] == "extractive"


def test_query_validation(client):
    assert client.post("/query", json={"question": "hi"}).status_code == 422
    assert client.post("/query", json={}).status_code == 422
    assert client.post("/query", json={"question": "x" * 2000}).status_code == 422
    assert client.post("/query", json={"question": "valid question here", "top_k": 99}).status_code == 422


def test_query_stream_endpoint(client):
    with client.stream(
        "POST", "/query/stream", json={"question": "What is the Team plan price per seat?"}
    ) as response:
        assert response.status_code == 200
        payload = "".join(response.iter_text())
    assert "event: retrieved" in payload
    assert "event: token" in payload
    assert "event: done" in payload
    assert "24" in payload


def test_evaluate_endpoint(client):
    body = client.post("/evaluate").json()
    assert body["hit_at_k"] >= 0.7
    assert body["rows"]


def test_index_serves_ui(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "DocMind" in response.text
