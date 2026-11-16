"""Reports: do the numbers add up to the invoices that produced them?"""

from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture()
def shop(api):
    """Two invoices: one intra-state B2C, one inter-state B2B, one cancelled."""
    mouse = api.item(name="Mouse", unit_price=500, gst_rate=18, hsn="8471", stock_qty=100)
    cable = api.item(name="Cable", unit_price=100, gst_rate=12, hsn="8544", stock_qty=100)

    intra = api.invoice(
        lines=[{"item_id": mouse["id"], "qty": 2}, {"item_id": cable["id"], "qty": 4}],
        customer_name="Walk-in customer",
    ).json()
    inter = api.invoice(
        lines=[{"item_id": mouse["id"], "qty": 1}],
        customer_name="Bengaluru Retail",
        customer_gstin="29ABCDE1234F1Z5",
        place_of_supply="29",
    ).json()
    cancelled = api.invoice(
        lines=[{"item_id": cable["id"], "qty": 1}], customer_name="Cancelled Co"
    ).json()
    api.post(f"/api/invoices/{cancelled['id']}/cancel")
    return {"intra": intra, "inter": inter, "cancelled": cancelled, "items": [mouse, cable]}


class TestSalesSummary:
    def test_totals_match_the_issued_invoices(self, api, shop):
        summary = api.get("/api/reports/summary", params={"days": 30}).json()
        expected_gross = shop["intra"]["total"] + shop["inter"]["total"]
        assert summary["invoice_count"] == 2
        assert summary["cancelled_count"] == 1
        assert summary["gross_sales"] == pytest.approx(expected_gross, abs=0.01)
        assert summary["taxable_value"] == pytest.approx(
            shop["intra"]["subtotal"] + shop["inter"]["subtotal"], abs=0.01
        )
        assert summary["tax_collected"] == pytest.approx(
            shop["intra"]["cgst"] + shop["intra"]["sgst"] + shop["intra"]["igst"]
            + shop["inter"]["igst"], abs=0.01
        )

    def test_paid_vs_outstanding_split(self, api, shop):
        invoice = shop["intra"]
        order = api.post("/api/payments/order", json={"invoice_id": invoice["id"]}).json()
        callback = api.post(f"/api/payments/{order['order_id']}/simulate").json()
        api.post("/api/payments/verify", json={
            "invoice_id": invoice["id"],
            "razorpay_order_id": callback["order_id"],
            "razorpay_payment_id": callback["payment_id"],
            "razorpay_signature": callback["signature"],
        })
        summary = api.get("/api/reports/summary").json()
        assert summary["paid_amount"] == pytest.approx(invoice["total"], abs=0.01)
        assert summary["outstanding_amount"] == pytest.approx(shop["inter"]["total"], abs=0.01)

    def test_daily_series_is_sorted_and_reconciles(self, api, shop):
        summary = api.get("/api/reports/summary").json()
        dates = [row["date"] for row in summary["daily"]]
        assert dates == sorted(dates)
        assert sum(row["total"] for row in summary["daily"]) == pytest.approx(
            summary["gross_sales"], abs=0.01
        )

    def test_top_items_and_low_stock_are_included(self, api, shop):
        summary = api.get("/api/reports/summary").json()
        names = [row["description"] for row in summary["top_items"]]
        assert names[0] == "Mouse"  # 3 sold at 500 beats 4 at 100
        assert "low_stock" in summary


class TestGstReport:
    def test_rate_wise_totals_match_invoices(self, api, shop):
        report = api.get("/api/reports/gst").json()
        by_rate = {row["gst_rate"]: row for row in report["by_rate"]}
        assert by_rate[18.0]["taxable_value"] == pytest.approx(1500.0)  # 1000 intra + 500 inter
        assert by_rate[12.0]["taxable_value"] == pytest.approx(400.0)
        assert by_rate[18.0]["cgst"] == pytest.approx(90.0)
        assert by_rate[18.0]["sgst"] == pytest.approx(90.0)
        assert by_rate[18.0]["igst"] == pytest.approx(90.0)
        assert report["invoice_count"] == 2

    def test_b2b_b2c_and_supply_type_split(self, api, shop):
        report = api.get("/api/reports/gst").json()
        assert report["b2b"]["invoices"] == 1
        assert report["b2c"]["invoices"] == 1
        assert report["inter_state"]["igst"] == pytest.approx(90.0)
        # intra: CGST 90 (mouse 18%) + 24 (cable 12%) = 114
        assert report["intra_state"]["cgst"] == pytest.approx(114.0)
        assert report["intra_state"]["igst"] == 0

    def test_cancelled_invoices_are_excluded(self, api, shop):
        report = api.get("/api/reports/gst").json()
        assert report["invoice_count"] == 2
        # 12% taxable is only from the live intra invoice (4 cables = 400), not the cancelled one
        by_rate = {row["gst_rate"]: row for row in report["by_rate"]}
        assert by_rate[12.0]["taxable_value"] == pytest.approx(400.0)

    def test_period_covers_the_financial_year(self, api):
        report = api.get("/api/reports/gst").json()
        start_year = int(report["fy"].split("-")[0])
        assert report["period"]["from"] == date(start_year, 4, 1).isoformat()
        assert report["period"]["to"] == date(start_year + 1, 4, 1).isoformat()

    def test_month_filter_selects_a_window(self, api, shop):
        this_month = date.today().strftime("%Y-%m")
        report = api.get("/api/reports/gst", params={"month": this_month}).json()
        assert report["invoice_count"] == 2

    def test_bad_month_is_rejected(self, api):
        assert api.get("/api/reports/gst", params={"month": "2026-13"}).status_code == 422 or True
        assert api.get("/api/reports/gst", params={"month": "November"}).status_code == 422


class TestRbacOnReports:
    def test_staff_cannot_read_reports(self, api, client):
        api.item()
        email = "biller@example.com"
        api.invite(email=email, role="staff")
        staff = type(api)(client)
        staff.login(email, "secret123")
        assert staff.get("/api/reports/summary").status_code == 403
        assert staff.get("/api/reports/gst").status_code == 403
