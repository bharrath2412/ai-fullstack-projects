"""Central configuration for the churn service (paths, seed, model thresholds)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CHURN_DATA_DIR", BASE_DIR / "data"))
ARTIFACT_DIR = Path(os.getenv("CHURN_ARTIFACT_DIR", BASE_DIR / "artifacts"))
REPORT_PATH = ARTIFACT_DIR / "model_report.html"
DATASET_PATH = DATA_DIR / "churn.csv"


@dataclass(frozen=True)
class Settings:
    random_seed: int = int(os.getenv("CHURN_SEED", "42"))
    n_samples: int = int(os.getenv("CHURN_N_SAMPLES", "6000"))
    test_size: float = float(os.getenv("CHURN_TEST_SIZE", "0.2"))
    cv_folds: int = int(os.getenv("CHURN_CV_FOLDS", "5"))

    # Decision threshold is tuned on the validation split, but can be pinned.
    decision_threshold: float | None = (
        float(os.environ["CHURN_THRESHOLD"]) if os.getenv("CHURN_THRESHOLD") else None
    )
    # Business rule: we must catch at least this share of churners.
    min_recall: float = float(os.getenv("CHURN_MIN_RECALL", "0.70"))

    model_version: str = os.getenv("CHURN_MODEL_VERSION", "")
    drift_warn: float = float(os.getenv("CHURN_DRIFT_WARN", "0.10"))  # PSI
    drift_alert: float = float(os.getenv("CHURN_DRIFT_ALERT", "0.25"))  # PSI

    numeric_features: tuple[str, ...] = (
        "tenure_months",
        "monthly_charges",
        "total_charges",
        "support_tickets_90d",
        "late_payments_12m",
        "usage_change_pct",
        "num_products",
        "avg_monthly_usage_gb",
    )
    categorical_features: tuple[str, ...] = (
        "contract_type",
        "payment_method",
        "internet_service",
        "signup_channel",
        "region",
    )
    target: str = "churned"

    @property
    def feature_names(self) -> list[str]:
        return [*self.numeric_features, *self.categorical_features]

    def validate(self) -> None:
        if self.n_samples < 100:
            raise ValueError("CHURN_N_SAMPLES must be >= 100")
        if not 0.05 <= self.test_size <= 0.5:
            raise ValueError("CHURN_TEST_SIZE must be between 0.05 and 0.5")
        if not 0.0 <= self.min_recall <= 1.0:
            raise ValueError("CHURN_MIN_RECALL must be in [0, 1]")


settings = Settings()

CATEGORY_LEVELS: dict[str, list[str]] = {
    "contract_type": ["month-to-month", "one_year", "two_year"],
    "payment_method": ["credit_card", "bank_transfer", "e_wallet", "mailed_check"],
    "internet_service": ["fiber", "dsl", "mobile"],
    "signup_channel": ["organic", "paid_search", "referral", "partner", "outbound"],
    "region": ["north_america", "europe", "apac", "latam"],
}
