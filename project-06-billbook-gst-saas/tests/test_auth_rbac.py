"""Auth, RBAC and tenant isolation — the three ways a SaaS leaks data."""

from __future__ import annotations

import time

import pytest

from app.security import AuthError, create_token, decode_token, hash_password, verify_password


class TestPasswordHashing:
    def test_hash_and_verify(self):
        stored = hash_password("correct horse battery")
        assert stored.startswith("pbkdf2_sha256$")
        assert verify_password("correct horse battery", stored)
        assert not verify_password("wrong password", stored)

    def test_salted_hashes_differ(self):
        assert hash_password("samepassword") != hash_password("samepassword")

    def test_short_password_refused(self):
        with pytest.raises(AuthError):
            hash_password("short")

    def test_garbage_hash_is_false_not_an_exception(self):
        assert not verify_password("anything", "not-a-hash")
        assert not verify_password("anything", "")


class TestTokens:
    def test_round_trip(self):
        token = create_token(subject=7, tenant_id=3, role="owner", secret="s3cret")
        claims = decode_token(token, secret="s3cret")
        assert claims["sub"] == "7"
        assert claims["tid"] == 3
        assert claims["role"] == "owner"
        assert claims["exp"] > time.time()

    def test_wrong_secret_is_rejected(self):
        token = create_token(subject=1, tenant_id=1, role="owner", secret="a")
        with pytest.raises(AuthError, match="signature"):
            decode_token(token, secret="b")

    def test_expired_token_is_rejected(self):
        token = create_token(subject=1, tenant_id=1, role="owner", secret="s", ttl_seconds=-1)
        with pytest.raises(AuthError, match="expired"):
            decode_token(token, secret="s")

    def test_tampered_payload_is_rejected(self):
        token = create_token(subject=1, tenant_id=1, role="cashier", secret="s")
        header, _, signature = token.split(".")
        forged = create_token(subject=1, tenant_id=1, role="owner", secret="s").split(".")[1]
        with pytest.raises(AuthError):
            decode_token(f"{header}.{forged}.{signature}", secret="s")

    def test_alg_none_is_rejected(self):
        import base64
        import json

        def b64(data: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

        header = b64({"alg": "none", "typ": "JWT"})
        payload = b64({"sub": "1", "tid": 1, "role": "owner", "exp": int(time.time()) + 60})
        token = f"{header}.{payload}."
        with pytest.raises(AuthError):
            decode_token(token, secret="s")

    def test_malformed_tokens_are_rejected(self):
        for bad in ("", "abc", "a.b", "a.b.c.d"):
            with pytest.raises(AuthError):
                decode_token(bad, secret="s")


class TestRegistrationAndLogin:
    def test_register_returns_a_usable_token(self, anon):
        body = anon.register(tenant_name="Anna Nagar Traders", state_code="33")
        assert body["user"]["role"] == "owner"
        assert body["tenant"]["state_code"] == "33"
        assert body["token_type"] == "bearer"
        response = anon.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json()["email"] == body["user"]["email"]

    def test_duplicate_email_conflicts(self, anon):
        body = anon.register(email="dup@example.com")
        assert body["user"]["email"] == "dup@example.com"
        again = anon.post(
            "/api/auth/register",
            json={"tenant_name": "Other", "state_code": "29", "name": "X",
                  "email": "dup@example.com", "password": "secret123"},
        )
        assert again.status_code == 409

    def test_gstin_must_match_state_code(self, anon):
        response = anon.post(
            "/api/auth/register",
            json={"tenant_name": "Mismatch", "state_code": "33", "gstin": "29AABCU9603R1ZM",
                  "name": "X", "email": "g@example.com", "password": "secret123"},
        )
        assert response.status_code == 422

    def test_invalid_state_code_is_rejected(self, anon):
        response = anon.post(
            "/api/auth/register",
            json={"tenant_name": "Bad state", "state_code": "Tamil Nadu", "name": "X",
                  "email": "s@example.com", "password": "secret123"},
        )
        assert response.status_code == 422

    def test_login_and_wrong_password(self, anon):
        body = anon.register(email="login@example.com")
        anon.login("login@example.com", "secret123")
        bad = anon.post("/api/auth/login", json={"email": "login@example.com", "password": "nope"})
        assert bad.status_code == 401
        assert "invalid email or password" in bad.json()["detail"]
        missing = anon.post("/api/auth/login", json={"email": "ghost@example.com", "password": "secret123"})
        assert missing.status_code == 401
        assert missing.json()["detail"] == bad.json()["detail"]

    def test_short_password_is_rejected_at_registration(self, anon):
        response = anon.post(
            "/api/auth/register",
            json={"tenant_name": "Short", "state_code": "33", "name": "X",
                  "email": "short@example.com", "password": "123"},
        )
        assert response.status_code == 422

    def test_missing_and_bad_tokens_get_401(self, anon):
        assert anon.get("/api/items").status_code == 401
        anon.token = "not.a.token"
        assert anon.get("/api/items").status_code == 401


class TestRBAC:
    def test_owner_can_do_everything(self, api):
        assert api.get("/api/items").status_code == 200
        assert (api.item()["id"] is not None)
        assert api.get("/api/reports/summary").status_code == 200

    def test_staff_can_bill_but_not_manage_catalogue_or_reports(self, api, client):
        email = "staff@example.com"
        api.invite(email=email, role="staff")
        staff = type(api)(client)
        staff.login(email, "secret123")

        assert staff.get("/api/items").status_code == 200
        response = staff.invoice(lines=[{"description": "Counter sale", "qty": 1,
                                         "unit_price": 100, "gst_rate": 18}])
        assert response.status_code == 201
        assert staff.post("/api/items", json={"sku": "NOPE", "name": "x", "unit_price": 10,
                                              "gst_rate": 18}).status_code == 403
        assert staff.get("/api/reports/summary").status_code == 403
        assert staff.get("/api/auth/users").status_code == 403
        # cancelling is an owner decision
        assert staff.post(f"/api/invoices/{response.json()['id']}/cancel").status_code == 403

    def test_accountant_is_read_only(self, api, client):
        email = "ca@example.com"
        api.invite(email=email, role="accountant")
        accountant = type(api)(client)
        accountant.login(email, "secret123")

        assert accountant.get("/api/items").status_code == 200
        assert accountant.get("/api/reports/summary").status_code == 200
        assert accountant.get("/api/reports/gst").status_code == 200
        assert accountant.invoice(lines=[{"description": "x", "qty": 1, "unit_price": 10,
                                           "gst_rate": 18}]).status_code == 403
        assert accountant.post("/api/items", json={"sku": "X", "name": "x", "unit_price": 10,
                                                    "gst_rate": 18}).status_code == 403

    def test_demoting_a_user_does_not_wait_for_the_token_to_expire(self, api, client):
        email = "mover@example.com"
        invited = api.invite(email=email, role="staff")
        worker = type(api)(client)
        worker.login(email, "secret123")
        assert worker.get("/api/items").status_code == 200

        # The role is read from the DB on every request, so this takes effect now.
        import sqlite3

        conn = sqlite3.connect(api.client.app.state.settings.db_path)
        conn.execute("UPDATE users SET role = 'accountant' WHERE id = ?", (invited["id"],))
        conn.commit()
        conn.close()
        assert worker.get("/api/reports/summary").status_code == 200  # accountants may read reports
        assert worker.post("/api/items", json={"sku": "X", "name": "x", "unit_price": 10,
                                                "gst_rate": 18}).status_code == 403

    def test_owner_lists_users(self, api):
        api.invite(email="listed@example.com", role="staff")
        users = api.get("/api/auth/users").json()
        assert {user["role"] for user in users} == {"owner", "staff"}


class TestTenantIsolation:
    def test_second_tenant_cannot_read_first_tenants_invoice(self, api, client):
        invoice = api.invoice(lines=[{"description": "Widget", "qty": 1, "unit_price": 100,
                                      "gst_rate": 18}]).json()
        other = type(api)(client)
        other.register(tenant_name="Delhi Depot", state_code="07")

        response = other.get(f"/api/invoices/{invoice['id']}")
        assert response.status_code == 404  # 404, never 403: do not confirm existence
        assert other.get(f"/api/invoices/{invoice['id']}/pdf").status_code == 404
        assert other.post(f"/api/invoices/{invoice['id']}/cancel").status_code == 404
        assert other.get("/api/invoices").json() == []

    def test_second_tenant_gets_its_own_numbering(self, api, client):
        api.invoice(lines=[{"description": "A", "qty": 1, "unit_price": 100, "gst_rate": 18}])
        other = type(api)(client)
        other.register(tenant_name="Delhi Depot", state_code="07")
        other_invoice = other.invoice(
            lines=[{"description": "B", "qty": 1, "unit_price": 100, "gst_rate": 18}]
        ).json()
        assert other_invoice["number"].endswith("/0001")

    def test_items_are_tenant_scoped(self, api, client):
        item = api.item()
        other = type(api)(client)
        other.register(tenant_name="Delhi Depot", state_code="07")
        assert other.get(f"/api/items/{item['id']}").status_code == 404
        assert other.get("/api/items").json() == []
        # the same SKU is allowed for another tenant
        assert other.post("/api/items", json={"sku": item["sku"], "name": "Same SKU",
                                               "unit_price": 10, "gst_rate": 18}).status_code == 201

    def test_staff_of_tenant_a_cannot_read_tenant_b(self, api, client):
        api.invoice(lines=[{"description": "A", "qty": 1, "unit_price": 100, "gst_rate": 18}])
        other = type(api)(client)
        other.register(tenant_name="Delhi Depot", state_code="07")
        item = other.item()
        assert api.get(f"/api/items/{item['id']}").status_code == 404


class TestAuditTrail:
    def test_writes_are_audited(self, api):
        import sqlite3

        api.invoice(lines=[{"description": "Widget", "qty": 1, "unit_price": 100, "gst_rate": 18}])
        conn = sqlite3.connect(api.client.app.state.settings.db_path)
        actions = [row[0] for row in conn.execute("SELECT action FROM audit ORDER BY id").fetchall()]
        conn.close()
        assert "tenant.created" in actions
        assert "invoice.issued" in actions
