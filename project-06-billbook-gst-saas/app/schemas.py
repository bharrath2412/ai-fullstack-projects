"""Request/response models. Validation lives here, business rules live in services."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
#: 15-character GSTIN: 2-digit state + PAN + entity + Z + checksum.
GSTIN_PATTERN = r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
STATE_PATTERN = r"^\d{2}$"
HSN_PATTERN = r"^[0-9]{2,8}$"

Role = Literal["owner", "staff", "accountant"]


class RegisterIn(BaseModel):
    """Cross-field rules (GSTIN ↔ state code) live in services: see register_tenant()."""

    tenant_name: str = Field(min_length=2, max_length=120)
    state_code: str = Field(pattern=STATE_PATTERN, description="GST state code of the seller, e.g. 33 for Tamil Nadu")
    gstin: str | None = Field(default=None, pattern=GSTIN_PATTERN)
    address: str | None = Field(default=None, max_length=300)
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=200)

class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: int
    tenant_id: int
    name: str | None
    email: str
    role: Role


class TenantOut(BaseModel):
    id: int
    name: str
    gstin: str | None
    state_code: str
    address: str | None


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut
    tenant: TenantOut


class StaffInviteIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["staff", "accountant"]


class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    hsn: str | None = Field(default=None, pattern=HSN_PATTERN)
    unit: str = Field(default="pcs", max_length=10)
    unit_price: float = Field(gt=0, le=10_000_000)
    gst_rate: float = Field(ge=0, le=40)
    stock_qty: float = Field(default=0, ge=0, le=1_000_000)
    reorder_level: float = Field(default=0, ge=0, le=1_000_000)


class ItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    hsn: str | None = Field(default=None, pattern=HSN_PATTERN)
    unit: str | None = Field(default=None, max_length=10)
    unit_price: float | None = Field(default=None, gt=0, le=10_000_000)
    gst_rate: float | None = Field(default=None, ge=0, le=40)
    reorder_level: float | None = Field(default=None, ge=0, le=1_000_000)
    active: bool | None = None


class StockAdjustIn(BaseModel):
    delta: float = Field(description="Signed quantity change, e.g. 12 or -3")
    reason: str = Field(default="manual adjustment", max_length=120)


class InvoiceLineIn(BaseModel):
    item_id: int | None = None
    description: str | None = Field(default=None, max_length=200)
    hsn: str | None = Field(default=None, pattern=HSN_PATTERN)
    qty: float = Field(gt=0, le=100_000)
    unit_price: float | None = Field(default=None, gt=0, le=10_000_000)
    discount_pct: float = Field(default=0, ge=0, le=100)
    gst_rate: float | None = Field(default=None, ge=0, le=40)
    cess_rate: float = Field(default=0, ge=0, le=50)
    price_inclusive: bool = False



class InvoiceIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=160)
    customer_gstin: str | None = Field(default=None, pattern=GSTIN_PATTERN)
    customer_state_code: str | None = Field(default=None, pattern=STATE_PATTERN)
    place_of_supply: str | None = Field(default=None, pattern=STATE_PATTERN)
    notes: str | None = Field(default=None, max_length=500)
    lines: list[InvoiceLineIn] = Field(min_length=1, max_length=100)



class LineOut(BaseModel):
    model_config = ConfigDict(extra="allow")


class InvoiceOut(BaseModel):
    model_config = ConfigDict(extra="allow")


class PaymentOrderIn(BaseModel):
    invoice_id: int


class PaymentVerifyIn(BaseModel):
    invoice_id: int
    razorpay_order_id: str = Field(min_length=4, max_length=120)
    razorpay_payment_id: str = Field(min_length=4, max_length=120)
    razorpay_signature: str = Field(min_length=8, max_length=256)


class PaymentOrderOut(BaseModel):
    provider: str
    mode: str
    key_id: str
    order_id: str
    amount: int = Field(description="Amount in paise, as Razorpay expects")
    currency: str
    invoice_id: int
    invoice_number: str
    checkout_url: str | None = None
    note: str


class PaymentOut(BaseModel):
    provider: str
    order_id: str
    payment_id: str | None
    amount: float
    status: str
    signature_verified: bool
    invoice_id: int
    invoice_status: str
