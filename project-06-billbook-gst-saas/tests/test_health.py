"""Health, meta and the observability headers the README quotes."""

from __future__ import annotations

import pytest


class TestHealth:
    def test_health_is_public_and_reports_counts(self, api):
        # api registers a tenant, so the counters must be non-zero
        response = api.client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["db"]["ok"] is True
        assert body["db"]["tenants"] >= 1
        assert body["payments"]["live_keys"] is False
        assert body["payments"]["mode"] == "razorpay-simulated"

    def test_latency_block_is_measured_not_invented(self, api):
        for _ in range(5):
            api.get("/api/items")
        body = api.client.get("/health").json()
        latency = body["latency_ms"]
        assert latency["samples"] >= 5
        assert latency["p50"] > 0
        assert latency["p95"] >= latency["p50"]
        assert isinstance(latency["slowest_routes"], list)

    def test_every_response_carries_request_headers(self, api):
        response = api.get("/api/items")
        assert response.headers["X-Request-ID"]
        assert float(response.headers["X-Response-Time-ms"]) >= 0
        assert response.headers["Server-Timing"].startswith("app;dur=")
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_request_id_is_echoed_when_supplied(self, api):
        response = api.get("/api/items", headers={"X-Request-ID": "trace-123"})
        assert response.headers["X-Request-ID"] == "trace-123"


class TestMeta:
    def test_meta_lists_rates_and_financial_year(self, api):
        body = api.client.get("/api/meta").json()
        assert 18.0 in body["gst_rates"]
        assert 0.0 in body["gst_rates"]
        assert body["currency"] == "INR"
        assert body["roles"] == ["owner", "staff", "accountant"]
        assert "-" in body["financial_year"]

    def test_openapi_schema_is_served(self, api):
        schema = api.client.get("/openapi.json").json()
        assert schema["info"]["title"] == "BillBook"
        assert "/api/invoices" in schema["paths"]


class TestAdminUi:
    def test_admin_page_is_served(self, api):
        response = api.client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "BillBook" in response.text
