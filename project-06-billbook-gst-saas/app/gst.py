"""GST tax engine — pure functions, no database, no framework.

Everything internal is integer **paise**. Floating point rupees are a display
concern, so they are converted at the boundary and never used for arithmetic.
That single rule is what makes the totals on an invoice, the total in the PDF and
the total in the GST report agree to the paisa.

Rules implemented (and the ones deliberately not):

* Intra-state supply  → CGST = SGST = round(taxable × rate / 200)
* Inter-state supply  → IGST = round(taxable × rate / 100)
  The two halves are derived from the *whole* tax so CGST + SGST == tax exactly;
  splitting a rounded half twice is how invoices end up a paisa short.
* Line discount as a percentage of the line's gross value.
* Tax-inclusive prices (`price_inclusive=True`) → taxable value is back-computed.
* Invoice-level round-off to the nearest rupee, exposed as its own signed line.
* HSN summary for GSTR-1 style reporting.
* Compensation cess, as an extra percentage on the taxable value.

Out of scope, on purpose: SEZ/export supplies, reverse charge, e-invoicing/IRN,
advance receipts, TDS/TCS. See the README for the reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Sequence

#: Rates the app accepts. 0.25% is the real notified rate for rough diamonds etc.;
#: 40% covers the post-2020 cess-heavy slabs.
VALID_GST_RATES = (Decimal("0"), Decimal("0.25"), Decimal("3"), Decimal("5"),
                   Decimal("12"), Decimal("18"), Decimal("28"), Decimal("40"))

MAX_LINE_QTY = Decimal("100000")
MAX_UNIT_PRICE_RUPEES = Decimal("10000000")  # ₹1 crore per unit


class GstError(ValueError):
    """Raised for input the engine refuses to price."""


# --------------------------------------------------------------------------- #
# money helpers
# --------------------------------------------------------------------------- #
def to_paise(value) -> int:
    """Convert rupees (int/float/str/Decimal) to integer paise, half-up."""
    if isinstance(value, bool):
        raise GstError("boolean is not an amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise GstError(f"not a valid amount: {value!r}") from exc
    if not amount.is_finite():
        raise GstError(f"not a valid amount: {value!r}")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paise_to_rupees(paise: int) -> float:
    """Display helper: paise → rupees rounded to 2 dp as a JSON-friendly float."""
    return float((Decimal(paise) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_paise(value: Decimal) -> int:
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(value, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise GstError(f"{field_name} is not a number: {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise GstError(f"{field_name} must be a positive number, got {value!r}")
    return parsed


def validate_rate(rate) -> Decimal:
    parsed = _dec(rate, "gst_rate")
    if parsed not in VALID_GST_RATES:
        allowed = ", ".join(str(rate) for rate in VALID_GST_RATES)
        raise GstError(f"gst_rate must be one of {allowed}; got {parsed}")
    return parsed


# --------------------------------------------------------------------------- #
# line pricing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LineInput:
    """One invoice line as the user typed it."""

    description: str
    qty: Decimal
    unit_price_rupees: Decimal
    gst_rate: Decimal
    discount_pct: Decimal = Decimal("0")
    cess_rate: Decimal = Decimal("0")
    hsn: str = ""
    price_inclusive: bool = False
    item_id: int | None = None


@dataclass
class PricedLine:
    """One invoice line after the engine has priced it (all money in paise)."""

    description: str
    hsn: str
    qty: Decimal
    unit_price_paise: int
    discount_pct: Decimal
    gst_rate: Decimal
    cess_rate: Decimal
    price_inclusive: bool
    gross_paise: int
    discount_paise: int
    taxable_paise: int
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    item_id: int | None = None

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    @property
    def line_total_paise(self) -> int:
        return self.taxable_paise + self.tax_paise + self.cess_paise

    def as_dict(self) -> dict:
        """JSON shape used by the API and by the PDF builder."""
        return {
            "item_id": self.item_id,
            "description": self.description,
            "hsn": self.hsn or None,
            "qty": float(self.qty),
            "unit_price": paise_to_rupees(self.unit_price_paise),
            "discount_pct": float(self.discount_pct),
            "gst_rate": float(self.gst_rate),
            "cess_rate": float(self.cess_rate),
            "price_inclusive": self.price_inclusive,
            "gross": paise_to_rupees(self.gross_paise),
            "discount": paise_to_rupees(self.discount_paise),
            "taxable_value": paise_to_rupees(self.taxable_paise),
            "cgst": paise_to_rupees(self.cgst_paise),
            "sgst": paise_to_rupees(self.sgst_paise),
            "igst": paise_to_rupees(self.igst_paise),
            "cess": paise_to_rupees(self.cess_paise),
            "line_total": paise_to_rupees(self.line_total_paise),
            "line_total_paise": self.line_total_paise,
        }


def price_line(line: LineInput, *, intra_state: bool) -> PricedLine:
    """Price a single line and split its tax according to the supply type."""
    qty = _dec(line.qty, "qty")
    if qty <= 0 or qty > MAX_LINE_QTY:
        raise GstError(f"qty must be > 0 and <= {MAX_LINE_QTY}")
    if not str(line.description).strip():
        raise GstError("every line needs a description")
    unit_price = _dec(line.unit_price_rupees, "unit_price")
    if unit_price > MAX_UNIT_PRICE_RUPEES:
        raise GstError("unit_price looks wrong (over ₹1 crore per unit)")
    rate = validate_rate(line.gst_rate)
    cess_rate = _dec(line.cess_rate, "cess_rate")
    discount_pct = _dec(line.discount_pct, "discount_pct")
    if discount_pct > 100:
        raise GstError("discount_pct cannot exceed 100")

    unit_price_paise = to_paise(unit_price)
    gross_paise = _round_paise(qty * Decimal(unit_price_paise))
    discount_paise = _round_paise(Decimal(gross_paise) * discount_pct / Decimal(100))
    net_paise = gross_paise - discount_paise

    if line.price_inclusive:
        divisor = Decimal(100) + rate + cess_rate
        taxable_paise = _round_paise(Decimal(net_paise) * Decimal(100) / divisor)
    else:
        taxable_paise = net_paise

    total_tax_paise = _round_paise(Decimal(taxable_paise) * rate / Decimal(100))
    cess_paise = _round_paise(Decimal(taxable_paise) * cess_rate / Decimal(100))

    if intra_state:
        cgst_paise = _round_paise(Decimal(taxable_paise) * rate / Decimal(200))
        sgst_paise = total_tax_paise - cgst_paise  # exact complement, never off by one
        igst_paise = 0
    else:
        cgst_paise = sgst_paise = 0
        igst_paise = total_tax_paise

    return PricedLine(
        description=str(line.description).strip()[:200],
        hsn=str(line.hsn or "").strip()[:8],
        qty=qty,
        unit_price_paise=unit_price_paise,
        discount_pct=discount_pct,
        gst_rate=rate,
        cess_rate=cess_rate,
        price_inclusive=line.price_inclusive,
        gross_paise=gross_paise,
        discount_paise=discount_paise,
        taxable_paise=taxable_paise,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        igst_paise=igst_paise,
        cess_paise=cess_paise,
        item_id=line.item_id,
    )


# --------------------------------------------------------------------------- #
# invoice totals
# --------------------------------------------------------------------------- #
@dataclass
class InvoiceTotals:
    supply_type: str  # "intra" | "inter"
    lines: list[PricedLine] = field(default_factory=list)
    taxable_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    discount_paise: int = 0
    round_off_paise: int = 0
    total_paise: int = 0

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    @property
    def before_round_off_paise(self) -> int:
        return self.taxable_paise + self.tax_paise + self.cess_paise

    def tax_breakup(self) -> list[dict]:
        """Rows for the tax summary block: rate → taxable + each tax head."""
        return tax_breakup(self.lines)

    def as_dict(self) -> dict:
        return {
            "supply_type": self.supply_type,
            "lines": [line.as_dict() for line in self.lines],
            "taxable_value": paise_to_rupees(self.taxable_paise),
            "discount_total": paise_to_rupees(self.discount_paise),
            "cgst": paise_to_rupees(self.cgst_paise),
            "sgst": paise_to_rupees(self.sgst_paise),
            "igst": paise_to_rupees(self.igst_paise),
            "cess": paise_to_rupees(self.cess_paise),
            "tax_total": paise_to_rupees(self.tax_paise + self.cess_paise),
            "round_off": paise_to_rupees(self.round_off_paise),
            "total": paise_to_rupees(self.total_paise),
            "total_paise": self.total_paise,
            "tax_breakup": self.tax_breakup(),
        }


def tax_breakup(lines: Iterable) -> list[dict]:
    """Group priced lines by GST rate into the rows an invoice prints.

    Takes anything with the priced-line attributes, so it works on PricedLine
    objects, DB rows wrapped in a namespace, or the API's own dicts.
    """
    buckets: dict[float, dict] = {}
    for line in lines:
        key = float(line.gst_rate)
        bucket = buckets.setdefault(
            key,
            {"gst_rate": key, "taxable_value_paise": 0, "cgst_paise": 0, "sgst_paise": 0,
             "igst_paise": 0, "cess_paise": 0, "total_paise": 0},
        )
        bucket["taxable_value_paise"] += line.taxable_paise
        bucket["cgst_paise"] += line.cgst_paise
        bucket["sgst_paise"] += line.sgst_paise
        bucket["igst_paise"] += line.igst_paise
        bucket["cess_paise"] += line.cess_paise
        bucket["total_paise"] += line.taxable_paise + line.cgst_paise + line.sgst_paise + \
            line.igst_paise + line.cess_paise
    rows = []
    for key in sorted(buckets):
        bucket = buckets[key]
        rows.append({
            "gst_rate": bucket["gst_rate"],
            "taxable_value": paise_to_rupees(bucket["taxable_value_paise"]),
            "cgst": paise_to_rupees(bucket["cgst_paise"]),
            "sgst": paise_to_rupees(bucket["sgst_paise"]),
            "igst": paise_to_rupees(bucket["igst_paise"]),
            "cess": paise_to_rupees(bucket["cess_paise"]),
            "total": paise_to_rupees(bucket["total_paise"]),
        })
    return rows


def round_to_rupee(paise: int) -> int:
    """Nearest rupee, half-up, as paise (multiples of 100)."""
    return int((Decimal(paise) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


def compute_invoice(
    lines: Sequence[LineInput],
    *,
    seller_state_code: str,
    place_of_supply: str,
) -> InvoiceTotals:
    """Price every line and roll the invoice up, including the round-off line."""
    if not lines:
        raise GstError("an invoice needs at least one line")
    if len(lines) > 100:
        raise GstError("an invoice supports at most 100 lines")
    if not place_of_supply:
        raise GstError("place_of_supply is required (2-digit GST state code)")

    supply_type = "intra" if str(place_of_supply) == str(seller_state_code) else "inter"
    intra_state = supply_type == "intra"

    totals = InvoiceTotals(supply_type=supply_type)
    for line in lines:
        priced = price_line(line, intra_state=intra_state)
        totals.lines.append(priced)
        totals.taxable_paise += priced.taxable_paise
        totals.cgst_paise += priced.cgst_paise
        totals.sgst_paise += priced.sgst_paise
        totals.igst_paise += priced.igst_paise
        totals.cess_paise += priced.cess_paise
        totals.discount_paise += priced.discount_paise

    before = totals.before_round_off_paise
    totals.total_paise = round_to_rupee(before)
    totals.round_off_paise = totals.total_paise - before
    assert totals.total_paise == before + totals.round_off_paise  # invariant
    return totals


def hsn_summary(lines: Iterable[PricedLine]) -> list[dict]:
    """HSN-wise rollup used by the GST report and the invoice footer."""
    buckets: dict[tuple[str, float], dict] = {}
    for line in lines:
        key = (line.hsn or "-", float(line.gst_rate))
        bucket = buckets.setdefault(
            key,
            {"hsn": line.hsn or "-", "gst_rate": float(line.gst_rate),
             "qty": Decimal("0"), "taxable_value_paise": 0, "tax_paise": 0},
        )
        bucket["qty"] += line.qty
        bucket["taxable_value_paise"] += line.taxable_paise
        bucket["tax_paise"] += line.tax_paise + line.cess_paise
    return [
        {
            "hsn": bucket["hsn"],
            "gst_rate": bucket["gst_rate"],
            "qty": float(bucket["qty"]),
            "taxable_value": paise_to_rupees(bucket["taxable_value_paise"]),
            "tax": paise_to_rupees(bucket["tax_paise"]),
        }
        for _, bucket in sorted(buckets.items())
    ]


# --------------------------------------------------------------------------- #
# amount in words (Indian numbering: crore / lakh / thousand / hundred)
# --------------------------------------------------------------------------- #
_ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen")
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _two_digits(number: int) -> str:
    if number < 20:
        return _ONES[number]
    tens, ones = divmod(number, 10)
    return f"{_TENS[tens]}{' ' + _ONES[ones] if ones else ''}"


def _three_digits(number: int) -> str:
    hundreds, rest = divmod(number, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_two_digits(rest))
    return " ".join(parts)


def _indian_words(number: int) -> str:
    """Indian numbering groups: thousand, lakh, crore (recursive, any magnitude)."""
    if number < 1000:
        return _three_digits(number)
    if number < 100_000:
        chunk, rest = divmod(number, 1_000)
        return _join(f"{_three_digits(chunk)} Thousand", _indian_words(rest))
    if number < 10_000_000:
        chunk, rest = divmod(number, 100_000)
        return _join(f"{_three_digits(chunk)} Lakh", _indian_words(rest))
    chunk, rest = divmod(number, 10_000_000)
    return _join(f"{_indian_words(chunk)} Crore", _indian_words(rest))


def _join(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def rupees_in_words(paise: int) -> str:
    """Indian numbering, because 'One Lakh' is what an Indian invoice says.

    >>> rupees_in_words(12345600)
    'Rupees One Lakh Twenty Three Thousand Four Hundred Fifty Six Only'
    >>> rupees_in_words(10050)
    'Rupees One Hundred And Fifty Paise Only'
    >>> rupees_in_words(0)
    'Rupees Zero Only'
    >>> rupees_in_words(123456789012)
    'Rupees One Hundred Twenty Three Crore Forty Five Lakh Sixty Seven Thousand Eight Hundred Ninety And Twelve Paise Only'
    """
    if paise < 0:
        raise GstError("cannot write a negative amount in words")
    rupees, paise_remainder = divmod(int(paise), 100)
    amount = _indian_words(rupees) or "Zero"
    text = f"Rupees {amount}"
    if paise_remainder:
        text += f" And {_two_digits(paise_remainder)} Paise"
    return f"{text} Only"
