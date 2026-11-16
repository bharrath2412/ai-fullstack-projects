"""The money-math matrix. If one of these breaks, invoices are wrong."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.gst import (
    GstError,
    LineInput,
    compute_invoice,
    hsn_summary,
    price_line,
    round_to_rupee,
    rupees_in_words,
    to_paise,
)


def line(description="Widget", qty="1", price="100", rate="18", **kwargs) -> LineInput:
    return LineInput(
        description=description,
        qty=Decimal(qty),
        unit_price_rupees=Decimal(price),
        gst_rate=Decimal(rate),
        **kwargs,
    )


class TestPaiseConversion:
    @pytest.mark.parametrize(
        "rupees,paise",
        [("0", 0), ("1", 100), ("199.99", 19999), ("0.005", 1), ("-12.5", -1250), (2.675, 268)],
    )
    def test_rupees_to_paise_rounds_half_up(self, rupees, paise):
        assert to_paise(rupees) == paise

    def test_rejects_nonsense(self):
        with pytest.raises(GstError):
            to_paise("not money")
        with pytest.raises(GstError):
            to_paise(True)


class TestLinePricing:
    def test_exclusive_intra_state_split_is_exact(self):
        priced = price_line(line(qty="3", price="199.99"), intra_state=True)
        assert priced.taxable_paise == 59997
        assert priced.cgst_paise == 5400  # round(59997 × 18 / 200) = 5399.73 → 5400
        assert priced.sgst_paise == 5399  # complement, not a second rounding
        assert priced.tax_paise == 10799
        assert priced.line_total_paise == 70796

    def test_inter_state_uses_igst_only(self):
        priced = price_line(line(qty="2", price="250", rate="12"), intra_state=False)
        assert priced.igst_paise == 6000
        assert priced.cgst_paise == priced.sgst_paise == 0
        assert priced.line_total_paise == 56000

    def test_discount_applies_to_gross_before_tax(self):
        priced = price_line(line(qty="2", price="500", rate="18", discount_pct=Decimal("10")),
                            intra_state=True)
        assert priced.gross_paise == 100000
        assert priced.discount_paise == 10000
        assert priced.taxable_paise == 90000
        assert priced.tax_paise == 16200

    def test_inclusive_price_back_computes_taxable_value(self):
        priced = price_line(line(qty="1", price="1180", rate="18", price_inclusive=True),
                            intra_state=True)
        assert priced.taxable_paise == 100000
        assert priced.taxable_paise + priced.tax_paise == 118000

    def test_inclusive_with_discount_and_cess(self):
        priced = price_line(
            line(qty="1", price="1180", rate="18", price_inclusive=True,
                 discount_pct=Decimal("50"), cess_rate=Decimal("12")),
            intra_state=True,
        )
        # taxable = 590 / 1.30 = 453.85; cess 12% of that
        assert priced.taxable_paise == 45385
        assert priced.cess_paise == round(45385 * 0.12)
        assert priced.cess_paise == 5446

    def test_zero_rate_has_no_tax(self):
        priced = price_line(line(qty="5", price="40", rate="0"), intra_state=True)
        assert priced.tax_paise == 0
        assert priced.cgst_paise == priced.sgst_paise == 0
        assert priced.line_total_paise == 20000

    def test_fractional_quantity(self):
        priced = price_line(line(qty="2.5", price="99.50", rate="5"), intra_state=True)
        assert priced.taxable_paise == 24875
        assert priced.tax_paise == 1244

    @pytest.mark.parametrize("rate", ["7", "19", "-5", "18.5"])
    def test_invalid_rate_is_refused(self, rate):
        with pytest.raises(GstError, match="gst_rate"):
            price_line(line(rate=rate), intra_state=True)

    @pytest.mark.parametrize("qty", ["0", "-1", "200000"])
    def test_invalid_quantity_is_refused(self, qty):
        with pytest.raises(GstError, match="qty"):
            price_line(line(qty=qty), intra_state=True)

    def test_description_is_required(self):
        with pytest.raises(GstError, match="description"):
            price_line(line(description="   "), intra_state=True)

    def test_discount_over_100_is_refused(self):
        with pytest.raises(GstError, match="discount"):
            price_line(line(discount_pct=Decimal("101")), intra_state=True)


class TestInvoiceTotals:
    def test_round_off_line_makes_the_total_a_whole_rupee(self):
        totals = compute_invoice([line(qty="3", price="199.99")], seller_state_code="33",
                                 place_of_supply="33")
        assert totals.total_paise % 100 == 0
        assert totals.total_paise == totals.before_round_off_paise + totals.round_off_paise
        assert totals.total_paise == 70800
        assert totals.round_off_paise == 4

    def test_round_off_can_be_negative(self):
        totals = compute_invoice([line(qty="1", price="100.49", rate="0")],
                                 seller_state_code="33", place_of_supply="33")
        assert totals.before_round_off_paise == 10049
        assert totals.total_paise == 10000
        assert totals.round_off_paise == -49

    @pytest.mark.parametrize(
        "place_of_supply,expected",
        [("33", "intra"), ("29", "inter"), ("07", "inter")],
    )
    def test_supply_type_from_place_of_supply(self, place_of_supply, expected):
        totals = compute_invoice([line()], seller_state_code="33", place_of_supply=place_of_supply)
        assert totals.supply_type == expected
        if expected == "intra":
            assert totals.igst_paise == 0 and totals.cgst_paise == totals.sgst_paise
        else:
            assert totals.cgst_paise == totals.sgst_paise == 0

    def test_totals_are_the_sum_of_their_lines(self):
        lines = [line(qty="2", price="199.99"), line(qty="1", price="49.50", rate="5"),
                 line(qty="3.5", price="12.30", rate="12", discount_pct=Decimal("5"))]
        totals = compute_invoice(lines, seller_state_code="33", place_of_supply="33")
        assert totals.taxable_paise == sum(item.taxable_paise for item in totals.lines)
        assert totals.cgst_paise == sum(item.cgst_paise for item in totals.lines)
        assert totals.sgst_paise == sum(item.sgst_paise for item in totals.lines)
        assert totals.cess_paise == sum(item.cess_paise for item in totals.lines)

    def test_tax_breakup_groups_by_rate(self):
        totals = compute_invoice(
            [line(qty="1", price="100", rate="18"), line(qty="1", price="100", rate="5"),
             line(qty="1", price="100", rate="18")],
            seller_state_code="33", place_of_supply="33",
        )
        breakup = {row["gst_rate"]: row for row in totals.tax_breakup()}
        assert breakup[18.0]["taxable_value"] == 200.0
        assert breakup[5.0]["taxable_value"] == 100.0
        assert breakup[18.0]["cgst"] == 18.0
        assert breakup[18.0]["sgst"] + breakup[18.0]["cgst"] == 36.0

    def test_empty_invoice_is_refused(self):
        with pytest.raises(GstError, match="at least one line"):
            compute_invoice([], seller_state_code="33", place_of_supply="33")

    def test_missing_place_of_supply_is_refused(self):
        with pytest.raises(GstError, match="place_of_supply"):
            compute_invoice([line()], seller_state_code="33", place_of_supply="")

    def test_random_invoices_never_lose_a_paisa(self):
        rng = random.Random(20261116)
        for _ in range(200):
            lines = []
            for _ in range(rng.randint(1, 6)):
                lines.append(
                    LineInput(
                        description="Item",
                        qty=Decimal(str(round(rng.uniform(0.5, 20), 3))),
                        unit_price_rupees=Decimal(str(round(rng.uniform(1, 5000), 2))),
                        gst_rate=Decimal(str(rng.choice([0, 5, 12, 18, 28]))),
                        discount_pct=Decimal(str(round(rng.uniform(0, 30), 2))),
                        cess_rate=Decimal(str(rng.choice([0, 0, 12]))),
                        price_inclusive=rng.random() < 0.3,
                    )
                )
            totals = compute_invoice(lines, seller_state_code="33",
                                     place_of_supply=rng.choice(["33", "29"]))
            assert totals.total_paise == totals.before_round_off_paise + totals.round_off_paise
            assert totals.total_paise % 100 == 0
            tax = totals.cgst_paise + totals.sgst_paise + totals.igst_paise
            assert tax == sum(item.tax_paise for item in totals.lines)
            if totals.supply_type == "intra":
                assert totals.igst_paise == 0
                assert abs(totals.cgst_paise - totals.sgst_paise) <= len(totals.lines)
            else:
                assert totals.cgst_paise == 0 and totals.sgst_paise == 0


class TestRoundingHelpers:
    @pytest.mark.parametrize("paise,expected", [(149, 100), (150, 200), (49, 0), (250, 300), (0, 0)])
    def test_round_to_rupee(self, paise, expected):
        assert round_to_rupee(paise) == expected


class TestAmountInWords:
    @pytest.mark.parametrize(
        "paise,words",
        [
            (0, "Rupees Zero Only"),
            (100, "Rupees One Only"),
            (1050, "Rupees Ten And Fifty Paise Only"),
            (12345600, "Rupees One Lakh Twenty Three Thousand Four Hundred Fifty Six Only"),
            (10000000, "Rupees One Lakh Only"),
            (1000000000, "Rupees One Crore Only"),
            (9999999900, "Rupees Nine Crore Ninety Nine Lakh Ninety Nine Thousand Nine Hundred Ninety Nine Only"),
        ],
    )
    def test_indian_numbering(self, paise, words):
        assert rupees_in_words(paise) == words

    def test_negative_amount_is_refused(self):
        with pytest.raises(GstError):
            rupees_in_words(-1)


class TestHsnSummary:
    def test_groups_by_hsn_and_rate(self):
        totals = compute_invoice(
            [
                LineInput(description="Mouse", qty=Decimal("2"), unit_price_rupees=Decimal("500"),
                          gst_rate=Decimal("18"), hsn="8471"),
                LineInput(description="Mouse (white)", qty=Decimal("1"), unit_price_rupees=Decimal("500"),
                          gst_rate=Decimal("18"), hsn="8471"),
                LineInput(description="Cable", qty=Decimal("3"), unit_price_rupees=Decimal("100"),
                          gst_rate=Decimal("12"), hsn="8544"),
            ],
            seller_state_code="33", place_of_supply="33",
        )
        summary = {row["hsn"]: row for row in hsn_summary(totals.lines)}
        assert summary["8471"]["qty"] == 3.0
        assert summary["8471"]["taxable_value"] == 1500.0
        assert summary["8471"]["tax"] == 270.0
        assert summary["8544"]["tax"] == 36.0
