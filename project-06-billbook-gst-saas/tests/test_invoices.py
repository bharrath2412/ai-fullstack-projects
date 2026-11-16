"""Invoices: numbering, GST split, stock ledger, cancellation, concurrency."""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest

from app.db import connect
from app.numbering import financial_year, format_invoice_number
from app.services import create_invoice


def simple_line(**overrides):
    line = {"description": "Steel bottle", "qty": 2, "unit_price": 749.5, "gst_rate": 18}
    line.update(overrides)
    return line


class TestNumbering:
    def test_financial_year_rolls_on_april_first(self):
        from datetime import date

        assert financial_year(date(2026, 3, 31)) == "2025-26"
        assert financial_year(date(2026, 4, 1)) == "2026-27"
        assert financial_year(date(2026, 11, 16)) == "2026-27"
        assert financial_year(date(2027, 1, 1)) == "2026-27"

    def test_format_pads_to_four_digits(self):
        assert format_invoice_number("2026-27", 1) == "INV/2026-27/0001"
        assert format_invoice_number("2026-27", 12345) == "INV/2026-27/12345"

    def test_numbers_are_sequential_and_gapless(self, api):
        numbers = []
        for _ in range(5):
            response = api.invoice(lines=[simple_line()])
            assert response.status_code == 201, response.text
            numbers.append(response.json()["number"])
        fy = financial_year()
        assert numbers == [f"INV/{fy}/000{i}" for i in range(1, 6)]

    def test_next_number_preview_matches_what_gets_issued(self, api):
        preview = api.get("/api/invoices/next-number").json()
        issued = api.invoice(lines=[simple_line()]).json()
        assert preview["next_number"] == issued["number"]
        assert preview["fy"] == issued["fy"]


class TestInvoiceContent:
    def test_intra_state_invoice_has_cgst_and_sgst(self, api):
        body = api.invoice(lines=[simple_line(qty=1, unit_price=1000)], place_of_supply="33").json()
        assert body["supply_type"] == "intra"
        assert body["cgst"] == 90.0
        assert body["sgst"] == 90.0
        assert body["igst"] == 0.0
        assert body["total"] == 1180.0
        assert body["amount_in_words"] == "Rupees One Thousand One Hundred Eighty Only"
        assert len(body["lines"]) == 1
        assert body["lines"][0]["taxable_value"] == 1000.0
        assert body["hsn_summary"] == [] or isinstance(body["hsn_summary"], list)

    def test_inter_state_invoice_has_igst(self, api):
        body = api.invoice(lines=[simple_line(qty=1, unit_price=1000)],
                           place_of_supply="29", customer_name="Bengaluru Retail").json()
        assert body["supply_type"] == "inter"
        assert body["igst"] == 180.0
        assert body["cgst"] == body["sgst"] == 0.0

    def test_place_of_supply_defaults_from_customer_gstin(self, api):
        body = api.invoice(
            lines=[simple_line()],
            customer_gstin="29ABCDE1234F1Z5",
            customer_state_code=None,
        ).json()
        assert body["place_of_supply"] == "29"
        assert body["supply_type"] == "inter"

    def test_place_of_supply_defaults_to_seller_state(self, api):
        body = api.invoice(lines=[simple_line()]).json()
        assert body["place_of_supply"] == "33"
        assert body["supply_type"] == "intra"

    def test_item_master_fills_price_rate_and_hsn(self, api):
        item = api.item(name="Mechanical keyboard", unit_price=2499, gst_rate=18, hsn="8471")
        body = api.invoice(lines=[{"item_id": item["id"], "qty": 2}]).json()
        assert body["lines"][0]["description"] == "Mechanical keyboard"
        assert body["lines"][0]["unit_price"] == 2499.0
        assert body["lines"][0]["gst_rate"] == 18.0
        assert body["lines"][0]["hsn"] == "8471"
        assert body["subtotal"] == 4998.0

    def test_payload_carries_the_tax_breakup_the_pdf_prints(self, api):
        item = api.item(name="Mouse pad", unit_price=299, gst_rate=12, hsn="3926", stock_qty=10)
        body = api.invoice(lines=[{"item_id": item["id"], "qty": 2}]).json()
        assert [row["gst_rate"] for row in body["tax_breakup"]] == [12.0]
        assert body["tax_breakup"][0]["taxable_value"] == body["subtotal"]
        assert body["tax_breakup"][0]["cgst"] == body["cgst"]
        assert body["hsn_summary"][0]["hsn"] == "3926"

    def test_manual_line_without_price_is_rejected(self, api):
        response = api.invoice(lines=[{"description": "Mystery", "qty": 1, "gst_rate": 18}])
        assert response.status_code == 422

    def test_unknown_item_is_a_404_for_this_tenant(self, api):
        response = api.invoice(lines=[{"item_id": 9999, "qty": 1}])
        assert response.status_code == 404

    def test_invalid_gst_rate_is_rejected(self, api):
        response = api.invoice(lines=[simple_line(gst_rate=19)])
        assert response.status_code in {409, 422}

    def test_listing_and_status_filter(self, api):
        api.invoice(lines=[simple_line()])
        second = api.invoice(lines=[simple_line()]).json()
        api.post(f"/api/invoices/{second['id']}/cancel")

        all_invoices = api.get("/api/invoices").json()
        assert len(all_invoices) == 2
        cancelled = api.get("/api/invoices", params={"status": "cancelled"}).json()
        assert [invoice["id"] for invoice in cancelled] == [second["id"]]
        issued = api.get("/api/invoices", params={"status": "issued"}).json()
        assert len(issued) == 1

    def test_pagination_limits_are_enforced_by_validation(self, api):
        assert api.get("/api/invoices", params={"limit": 0}).status_code == 422
        assert api.get("/api/invoices", params={"limit": 500}).status_code == 422


class TestInventory:
    def test_stock_decrements_when_issued_and_reverses_on_cancel(self, api):
        item = api.item(stock_qty=10)
        assert item["stock_qty"] == 10
        invoice = api.invoice(lines=[{"item_id": item["id"], "qty": 4}]).json()
        assert api.get(f"/api/items/{item['id']}").json()["stock_qty"] == 6

        api.post(f"/api/invoices/{invoice['id']}/cancel")
        assert api.get(f"/api/items/{item['id']}").json()["stock_qty"] == 10

    def test_insufficient_stock_blocks_the_invoice(self, api):
        item = api.item(stock_qty=2)
        response = api.invoice(lines=[{"item_id": item["id"], "qty": 3}])
        assert response.status_code == 409
        assert "insufficient stock" in response.json()["detail"]
        # and nothing was written
        assert api.get("/api/invoices").json() == []
        assert api.get(f"/api/items/{item['id']}").json()["stock_qty"] == 2

    def test_stock_ledger_records_every_move(self, api):
        item = api.item(stock_qty=5)
        api.post(f"/api/items/{item['id']}/stock", json={"delta": 7, "reason": "goods received"})
        invoice = api.invoice(lines=[{"item_id": item["id"], "qty": 3}]).json()
        api.post(f"/api/invoices/{invoice['id']}/cancel")

        ledger = api.get(f"/api/items/{item['id']}/ledger").json()
        reasons = [entry["reason"] for entry in ledger]
        assert "opening stock" in reasons
        assert "goods received" in reasons
        assert "sold" in reasons
        assert "invoice cancelled" in reasons
        # ledger deltas must reconcile with the item's current quantity
        assert sum(entry["delta"] for entry in ledger) == 12

    def test_manual_adjustment_cannot_go_negative(self, api):
        item = api.item(stock_qty=3)
        response = api.post(f"/api/items/{item['id']}/stock", json={"delta": -5})
        assert response.status_code == 409

    def test_low_stock_feed(self, api):
        api.item(name="Plenty", stock_qty=100, reorder_level=10)
        low = api.item(name="Scarce", stock_qty=2, reorder_level=10)
        feed = api.get("/api/items", params={"low_stock": True}).json()
        assert [item["id"] for item in feed] == [low["id"]]
        assert feed[0]["low_stock"] is True

    def test_search_matches_name_sku_and_hsn(self, api):
        api.item(name="Wireless Mouse", sku="WM-1", hsn="8471")
        api.item(name="USB Cable", sku="UC-2", hsn="8544")
        assert [item["sku"] for item in api.get("/api/items", params={"q": "mouse"}).json()] == ["WM-1"]
        assert [item["sku"] for item in api.get("/api/items", params={"q": "8544"}).json()] == ["UC-2"]

    def test_duplicate_sku_conflicts(self, api):
        item = api.item()
        response = api.post("/api/items", json={"sku": item["sku"], "name": "Dup",
                                                "unit_price": 10, "gst_rate": 18})
        assert response.status_code == 409


class TestCancellationRules:
    def test_cannot_cancel_twice(self, api):
        invoice = api.invoice(lines=[simple_line()]).json()
        assert api.post(f"/api/invoices/{invoice['id']}/cancel").status_code == 200
        assert api.post(f"/api/invoices/{invoice['id']}/cancel").status_code == 409

    def test_cannot_cancel_a_paid_invoice(self, api):
        invoice = api.invoice(lines=[simple_line()]).json()
        order = api.post("/api/payments/order", json={"invoice_id": invoice["id"]}).json()
        callback = api.post(f"/api/payments/{order['order_id']}/simulate").json()
        api.post("/api/payments/verify", json={
            "invoice_id": invoice["id"],
            "razorpay_order_id": callback["order_id"],
            "razorpay_payment_id": callback["payment_id"],
            "razorpay_signature": callback["signature"],
        })
        response = api.post(f"/api/invoices/{invoice['id']}/cancel")
        assert response.status_code == 409
        assert "credit note" in response.json()["detail"]


class TestConcurrentNumbering:
    def test_parallel_creates_get_unique_consecutive_numbers(self, api):
        """20 threads, 20 connections, one tenant: no gaps, no duplicates."""
        tenant_id = api.tenant["id"]
        user_id = api.user["id"]
        db_path = api.client.app.state.settings.db_path
        results: list[str] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(10)

        def worker() -> None:
            conn = connect(db_path)
            try:
                barrier.wait(timeout=10)
                for _ in range(2):
                    invoice = create_invoice(
                        conn,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        customer_name="Thread Co",
                        customer_gstin=None,
                        customer_state_code="33",
                        place_of_supply="33",
                        notes=None,
                        lines=[{"description": "Bulk", "qty": 1, "unit_price": 100,
                                "gst_rate": 18, "discount_pct": 0, "cess_rate": 0}],
                    )
                    results.append(invoice["number"])
            except Exception as exc:  # noqa: BLE001 - collected and asserted below
                errors.append(exc)
            finally:
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not errors, errors[:3]
        fy = financial_year()
        expected = {f"INV/{fy}/{index:04d}" for index in range(1, 21)}
        assert set(results) == expected
        assert len(results) == len(set(results)) == 20
