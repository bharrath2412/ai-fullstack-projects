"""Test fixtures: a throwaway database and a tiny authenticated HTTP client.

Every test gets its own SQLite file (under pytest's tmp_path) so tests cannot leak
state into each other, and the app is created through `create_app()` exactly as in
production — no monkeypatched globals.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "billbook-test.db"),
        jwt_secret="test-secret-do-not-use-in-prod",
        payment_mode="simulated",
        env="test",
    )


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


class Api:
    """Thin wrapper: keeps the bearer token and returns parsed JSON."""

    def __init__(self, client: TestClient):
        self.client = client
        self.token: str | None = None
        self.user: dict | None = None
        self.tenant: dict | None = None

    # -- plumbing ---------------------------------------------------------
    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        headers.update(extra or {})
        return headers

    def request(self, method: str, path: str, **kwargs):
        kwargs.setdefault("headers", self._headers(kwargs.pop("headers", None)))
        return getattr(self.client, method)(path, **kwargs)

    def get(self, path, **kwargs):
        return self.request("get", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("post", path, **kwargs)

    def patch(self, path, **kwargs):
        return self.request("patch", path, **kwargs)

    def json(self, method: str, path: str, **kwargs):
        response = self.request(method, path, **kwargs)
        return response, (response.json() if response.content else None)

    # -- domain helpers ---------------------------------------------------
    def register(self, *, tenant_name="Chennai Gadgets", state_code="33", email=None,
                 password="secret123", gstin=None, address="12 Anna Salai, Chennai"):
        email = email or f"owner-{uuid.uuid4().hex[:8]}@example.com"
        response = self.post(
            "/api/auth/register",
            json={
                "tenant_name": tenant_name,
                "state_code": state_code,
                "gstin": gstin,
                "address": address,
                "name": "Owner",
                "email": email,
                "password": password,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        self.token = body["access_token"]
        self.user = body["user"]
        self.tenant = body["tenant"]
        return body

    def login(self, email, password):
        response = self.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        body = response.json()
        self.token = body["access_token"]
        self.user = body["user"]
        self.tenant = body["tenant"]
        return body

    def invite(self, *, email, role, password="secret123"):
        response = self.post(
            "/api/auth/users",
            json={"name": role.title(), "email": email, "password": password, "role": role},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def item(self, **overrides):
        payload = {
            "sku": f"SKU-{uuid.uuid4().hex[:6]}",
            "name": "Wireless mouse",
            "hsn": "8471",
            "unit": "pcs",
            "unit_price": 599.0,
            "gst_rate": 18,
            "stock_qty": 50,
            "reorder_level": 5,
        }
        payload.update(overrides)
        response = self.post("/api/items", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    def invoice(self, *, lines, customer_name="Sri Traders", place_of_supply=None, **overrides):
        payload = {"customer_name": customer_name, "lines": lines, **overrides}
        if place_of_supply:
            payload["place_of_supply"] = place_of_supply
        response = self.post("/api/invoices", json=payload)
        return response


@pytest.fixture()
def api(client) -> Api:
    helper = Api(client)
    helper.register()
    return helper


@pytest.fixture()
def anon(client) -> Api:
    return Api(client)
