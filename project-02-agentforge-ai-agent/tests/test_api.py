"""API tests via FastAPI's TestClient (real HTTP layer, mock provider)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "calculator" in body["tools"]
    assert body["limits"]["max_steps"] >= 1


def test_tools_manifest(client):
    response = client.get("/api/tools")
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()}
    assert {"calculator", "sqlite_query", "doc_search", "http_fetch"} <= names


def test_chat_returns_answer_and_trace(client):
    response = client.post("/api/chat", json={"message": "what is 1280 * 1.18 / 3"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["tool_calls"] == 1
    assert body["session_id"].startswith("s_")
    kinds = [step["kind"] for step in body["steps"]]
    assert "tool_call" in kinds and "tool_result" in kinds
    assert kinds[-1] == "answer"


def test_chat_validates_empty_message(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={}).status_code == 422


def test_chat_reuses_session_history(client):
    first = client.post("/api/chat", json={"message": "what is 2 + 2", "session_id": "sess-api"}).json()
    assert first["session_id"] == "sess-api"

    history = client.get("/api/sessions/sess-api").json()
    assert len(history["messages"]) == 2
    assert history["messages"][0]["role"] == "user"

    client.delete("/api/sessions/sess-api")
    assert client.get("/api/sessions/sess-api").json()["messages"] == []


def test_run_trace_endpoint(client):
    chat = client.post("/api/chat", json={"message": "show revenue by month"}).json()
    trace = client.get(f"/api/runs/{chat['run_id']}")
    assert trace.status_code == 200
    assert trace.json()["question"] == "show revenue by month"
    assert trace.json()["events"]

    recent = client.get("/api/runs/recent?limit=5").json()
    assert recent["items"]
    assert client.get("/api/runs/run_missing").status_code == 404


def test_stream_sends_sse_events(client):
    with client.stream(
        "POST", "/api/chat/stream", json={"message": "what is 7 * 6"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = "".join(chunk for chunk in response.iter_text())

    assert "event: session" in payload
    assert "event: thought" in payload
    assert "event: tool_call" in payload
    assert "event: tool_result" in payload
    assert "event: answer" in payload
    assert "event: end" in payload
    assert "42" in payload


def test_index_serves_chat_ui(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AgentForge" in response.text
