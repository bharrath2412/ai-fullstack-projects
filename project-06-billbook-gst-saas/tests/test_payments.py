"""Razorpay test mode: signature verification is the security boundary here."""

from __future__ import annotations

import pytest

from app.payments import sign, verify_signature


def make_invoice(api, total=1180.0):
    return api.invoice(
        lines=[{"description": "Steel bottle", "qty": 1, "unit_price": total, "gst_rate": 18}]
    ).json()


class TestSignaturePrimitives:
    def test_signature_is_hmac_sha256_of_order_pipe_payment(self):
        # Known-answer test: compute the expected value independently.
        import hashlib
        import hmac

        expected = hmac.new(b"secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
        assert sign("order_1", "pay_1", "secret") == expected

    def test_verify_accepts_correct_and_rejects_everything_else(self):
        signature = sign("order_1", "pay_1", "secret")
        assert verify_signature("order_1", "pay_1", signature, "secret")
        assert verify_signature("order_1", "pay_1", signature.upper(), "secret")
        assert not verify_signature("order_1", "pay_2", signature, "secret")
        assert not verify_signature("order_2", "pay_1", signature, "secret")
        assert not verify_signature("order_1", "pay_1", signature, "other-secret")
        assert not verify_signature("order_1", "pay_1", "", "secret")


class TestOrderFlow:
    def test_order_matches_invoice_total_in_paise(self, api):
        invoice = make_invoice(api)
        order = api.post("/api/payments/order", json={"invoice_id": invoice["id"]}).json()
        assert order["amount"] == int(round(invoice["total"] * 100))
        assert order["mode"] == "simulated"
        assert order["order_id"].startswith("order_sim_")
        assert order["currency"] == "INR"
        assert order["invoice_number"] == invoice["number"]

    def test_paying_flips_the_invoice_to_paid(self, api):
        invoice = make_invoice(api)
        order = api.post("/api/payments/order", json={"invoice_id": invoice["id"]}).json()
        callback = api.post(f"/api/payments/{order['order_id']}/simulate").json()
        response = api.post("/api/payments/verify", json={
            "invoice_id": invoice["id"],
            "razorpay_order_id": callback["order_id"],
            "razorpay_payment_id": callback["payment_id"],
            "razorpay_signature": callback["signature"],
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "captured"
        assert body["signature_verified"] is True
        assert body["invoice_status"] == "paid"
        assert body["amount"] == invoice["total"]

        refreshed = api.get(f"/api/invoices/{invoice['id']}").json()
        assert refreshed["status"] == "paid"
        assert refreshed["paid_at"] is not None

    def test_already_paid_invoice_cannot_be_paid_again(self, api):
        invoice = make_invoice(api)
        order = api.post("/api/payments/order", json={"invoice_id": invoice["id"]}).json()
        callback = api.post(f"/api/payments/{order['order_id']}/simulate").json()
        payload = {
            "invoice_id": invoice["id"],
            "razorpay_order_id": callback["order_id"],
            "razorpay_payment_id": callback["payment_id"],
            "razorpay_signature": callback["signature"],
        }
        assert api.post("/api/payments/verify", json=payload).status_code == 200
        # A retried callback is idempotent …
        repeat = api.post("/api/payments/verify", json=payload)
        assert repeat.status_code == 200
        assert repeat.json()["status"] == "captured"
        # … but a *new* order on a paid invoice is refused.
        again = api.post("/api/payments/order", json={"invoice_id": invoice["id"]})
        assert again.status_code == 409


class TestSignatureForgery:
    def test_forged_signature_is_rejected_and_recorded(self, api):
        invoice = make_invoice(api)
        order = api.post("/api/payments/order", json={"invoice_id": invoice["id"]}).json()
        callback = api.post(f"/api/payments/{order['order_id']}/simulate").json()

        forged = callback["signature"][:-1] + ("0" if callback["signature"][-1] != "0" else "1")
        response = api.post("/api/payments/verify", json={
            "invoice_id": invoice["id"],
            "razorpay_order_id": callback["order_id"],
            "razorpay_payment_id": callback["payment_id"],
            "razorpay_signature": forged,
        })
        assert response.status_code == 400
        assert "signature" in response.json()["detail"]
        assert api.get(f"/api/invoices/{invoice['id']}").json()["status"] == "issued"

        history = api.get(f"/api/payments/{invoice['id']}/history").json()
        assert history[0]["status"] == "failed"
        assert history[0]["signature_verified"] is False

    def test_signature_for_a_different_order_is_rejected(self, api):
        invoice = make_invoice(api)
        order = api.post("/api/payments/order", json={"invoice_id": invoice["id"]}).json()
        callback = api.post(f"/api/payments/{order['order_id']}/simulate").json()
        wrong_signature = sign("order_sim_deadbeef", callback["payment_id"], "billbook_test_secret")
        response = api.post("/api/payments/verify", json={
            "invoice_id": invoice["id"],
            "razorpay_order_id": callback["order_id"],
            "razorpay_payment_id": callback["payment_id"],
            "razorpay_signature": wrong_signature,
        })
        assert response.status_code == 400

    def test_payment_id_replay_is_refused(self, api):
        first = make_invoice(api)
        second = make_invoice(api)
        order_a = api.post("/api/payments/order", json={"invoice_id": first["id"]}).json()
        order_b = api.post("/api/payments/order", json={"invoice_id": second["id"]}).json()
        callback_a = api.post(f"/api/payments/{order_a['order_id']}/simulate").json()

        # Pay invoice A with A's callback …
        assert api.post("/api/payments/verify", json={
            "invoice_id": first["id"], "razorpay_order_id": callback_a["order_id"],
            "razorpay_payment_id": callback_a["payment_id"],
            "razorpay_signature": callback_a["signature"],
        }).status_code == 200

        # … then try to reuse the same payment id on invoice B with B's order signature.
        replay_signature = sign(order_b["order_id"], callback_a["payment_id"], "billbook_test_secret")
        replay = api.post("/api/payments/verify", json={
            "invoice_id": second["id"], "razorpay_order_id": order_b["order_id"],
            "razorpay_payment_id": callback_a["payment_id"],
            "razorpay_signature": replay_signature,
        })
        assert replay.status_code == 409
        assert "already been used" in replay.json()["detail"]
        assert api.get(f"/api/invoices/{second['id']}").json()["status"] == "issued"


class TestOrderOwnership:
    def test_unknown_order_is_404(self, api):
        invoice = make_invoice(api)
        response = api.post("/api/payments/verify", json={
            "invoice_id": invoice["id"],
            "razorpay_order_id": "order_sim_doesnotexist",
            "razorpay_payment_id": "pay_sim_x",
            "razorpay_signature": "deadbeef",
        })
        assert response.status_code == 404

    def test_order_belongs_to_the_invoice_it_was_created_for(self, api):
        first = make_invoice(api)
        second = make_invoice(api)
        order = api.post("/api/payments/order", json={"invoice_id": first["id"]}).json()
        callback = api.post(f"/api/payments/{order['order_id']}/simulate").json()
        response = api.post("/api/payments/verify", json={
            "invoice_id": second["id"],
            "razorpay_order_id": callback["order_id"],
            "razorpay_payment_id": callback["payment_id"],
            "razorpay_signature": sign(callback["order_id"], callback["payment_id"],
                                       "billbook_test_secret"),
        })
        assert response.status_code == 400
        assert "does not belong" in response.json()["detail"]

    def test_other_tenant_cannot_pay_my_invoice(self, api, client):
        invoice = make_invoice(api)
        other = type(api)(client)
        other.register(tenant_name="Delhi Depot", state_code="07")
        assert other.post("/api/payments/order", json={"invoice_id": invoice["id"]}).status_code == 404
        assert other.post(f"/api/payments/some-order/simulate").status_code == 404

    def test_accountant_cannot_take_payments(self, api, client):
        email = "readonly@example.com"
        api.invite(email=email, role="accountant")
        accountant = type(api)(client)
        accountant.login(email, "secret123")
        invoice = make_invoice(api)
        assert accountant.post("/api/payments/order",
                               json={"invoice_id": invoice["id"]}).status_code == 403
