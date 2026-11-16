"""Pydantic request/response models with strict input validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import CATEGORY_LEVELS

_CONTRACT = Literal["month-to-month", "one_year", "two_year"]
_PAYMENT = Literal["credit_card", "bank_transfer", "e_wallet", "mailed_check"]
_SERVICE = Literal["fiber", "dsl", "mobile"]
_CHANNEL = Literal["organic", "paid_search", "referral", "partner", "outbound"]
_REGION = Literal["north_america", "europe", "apac", "latam"]


class CustomerFeatures(BaseModel):
    """One customer record. Field ranges mirror what the model was trained on."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "customer_id": "C100123",
                "tenure_months": 4,
                "monthly_charges": 89.5,
                "total_charges": 356.0,
                "support_tickets_90d": 3,
                "late_payments_12m": 2,
                "usage_change_pct": -28.4,
                "num_products": 1,
                "avg_monthly_usage_gb": 41.2,
                "contract_type": "month-to-month",
                "payment_method": "e_wallet",
                "internet_service": "fiber",
                "signup_channel": "outbound",
                "region": "apac",
            }
        },
    )

    customer_id: str | None = Field(default=None, max_length=64)
    tenure_months: int = Field(ge=0, le=120, description="Months as a customer")
    monthly_charges: float = Field(gt=0, le=1000, description="Current monthly bill")
    total_charges: float = Field(ge=0, le=500_000, description="Lifetime billed amount")
    support_tickets_90d: int = Field(ge=0, le=200)
    late_payments_12m: int = Field(ge=0, le=60)
    usage_change_pct: float = Field(ge=-100, le=500, description="Change in usage vs prior quarter")
    num_products: int = Field(ge=1, le=20)
    avg_monthly_usage_gb: float | None = Field(default=None, ge=0, le=100_000)
    contract_type: _CONTRACT
    payment_method: _PAYMENT
    internet_service: _SERVICE
    signup_channel: _CHANNEL
    region: _REGION

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(exclude={"customer_id"})


class PredictionResponse(BaseModel):
    customer_id: str | None
    churn_probability: float
    will_churn: bool
    risk_band: Literal["low", "medium", "high", "critical"]
    threshold: float
    model_version: str


class BatchRequest(BaseModel):
    customers: list[CustomerFeatures] = Field(min_length=1, max_length=500)


class BatchResponse(BaseModel):
    predictions: list[PredictionResponse]
    summary: dict[str, Any]
    model_version: str
    duration_ms: float


class Contribution(BaseModel):
    feature: str
    value: Any
    baseline: Any
    impact: float = Field(description="Change in churn probability when this feature is reset to baseline")
    direction: Literal["increases", "decreases", "neutral"]


class ExplanationResponse(BaseModel):
    prediction: PredictionResponse
    baseline_probability: float
    contributions: list[Contribution]
    note: str


class DriftRequest(BaseModel):
    customers: list[CustomerFeatures] = Field(min_length=10, max_length=1000)


class ModelInfoResponse(BaseModel):
    version: str
    model_type: str
    threshold: float
    metrics: dict[str, float]
    cv: dict[str, Any]
    dataset: dict[str, Any]
    feature_names: list[str]
    importances: list[dict[str, Any]]
    training_rows: int
    created_at: str
    levels: dict[str, list[str]]


__all__ = [
    "CATEGORY_LEVELS",
    "BatchRequest",
    "BatchResponse",
    "Contribution",
    "CustomerFeatures",
    "DriftRequest",
    "ExplanationResponse",
    "ModelInfoResponse",
    "PredictionResponse",
]
