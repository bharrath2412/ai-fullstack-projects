"""PDF: it must be a real PDF, say the right things, and be stable."""

from __future__ import annotations

import re
import zlib

import pytest

from app.pdf import _rupees, invoice_filename, render_invoice_pdf


def pdf_text(data: bytes) -> str:
    """Crude but dependency-free text extraction: inflate every stream, keep ASCII."""
    chunks = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            chunks.append(zlib.decompress(stream))
        except zlib.error:
            chunks.append(stream)
    return b"\n".join(chunks).decode("latin-1", errors="ignore")


@pytest.fixture()
def invoice_body(api):
    item = api.item(name="Mechanical keyboard", unit_price=2499, gst_rate=18, hsn="8471",
                    stock_qty=10)
    return api.invoice(
        lines=[
            {"item_id": item["id"], "qty": 2},
            {"description": "Mouse pad", "qty": 1, "unit_price": 299, "gst_rate": 12, "hsn": "3926"},
        ],
        customer_name="Sri Traders",
        customer_gstin="33ABCDE1234F1Z5",
        notes="Delivered by 20 Nov",
    ).json()


class TestPdfEndpoint:
    def test_returns_a_valid_pdf_with_download_headers(self, api, invoice_body):
        response = api.get(f"/api/invoices/{invoice_body['id']}/pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert invoice_body["number"].replace("/", "-") in response.headers["content-disposition"]
        assert response.content.startswith(b"%PDF-")
        assert response.content.rstrip().endswith(b"%%EOF")
        assert len(response.content) > 1500

    def test_contains_the_tax_invoice_facts(self, api, invoice_body):
        data = api.get(f"/api/invoices/{invoice_body['id']}/pdf").content
        text = pdf_text(data)
        assert "TAX INVOICE" in text
        assert invoice_body["number"] in text
        assert "Sri Traders" in text
        assert "33ABCDE1234F1Z5" in text
        assert "Mechanical keyboard" in text
        assert "GSTIN" in text
        assert "Amount in words" in text
        assert "Rupees" in text
        # intra-state invoice: CGST and SGST present, IGST row correctly omitted
        assert "CGST" in text and "SGST" in text

    def test_prints_each_gst_rate_from_the_breakup(self, api, invoice_body):
        text = pdf_text(api.get(f"/api/invoices/{invoice_body['id']}/pdf").content)
        assert "18%" in text
        assert "12%" in text
        assert "0%" not in text.replace("100%", "")

    def test_rendering_is_deterministic_for_the_same_invoice(self, api, invoice_body):
        first = api.get(f"/api/invoices/{invoice_body['id']}/pdf").content
        second = api.get(f"/api/invoices/{invoice_body['id']}/pdf").content
        assert first == second

    def test_other_tenant_cannot_download_it(self, api, client, invoice_body):
        other = type(api)(client)
        other.register(tenant_name="Delhi Depot", state_code="07")
        assert other.get(f"/api/invoices/{invoice_body['id']}/pdf").status_code == 404

    def test_filename_is_filesystem_safe(self):
        assert invoice_filename("INV/2026-27/0001") == "INV-2026-27-0001.pdf"
        assert invoice_filename("A B/C") == "A-B-C.pdf"

    def test_many_lines_do_not_crash_the_layout(self, api):
        lines = [
            {"description": f"Bulk item {index}", "qty": 1, "unit_price": 100 + index,
             "gst_rate": 18, "hsn": "8471"}
            for index in range(30)
        ]
        invoice = api.invoice(lines=lines).json()
        response = api.get(f"/api/invoices/{invoice['id']}/pdf")
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF-")


class TestRupeeFormatting:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (0, "Rs. 0.00"),
            (1, "Rs. 1.00"),
            (999.5, "Rs. 999.50"),
            (1000, "Rs. 1,000.00"),
            (100000, "Rs. 1,00,000.00"),
            (12345678.9, "Rs. 1,23,45,678.90"),
            (-45.5, "-Rs. 45.50"),
        ],
    )
    def test_indian_digit_grouping(self, value, expected):
        assert _rupees(value) == expected
