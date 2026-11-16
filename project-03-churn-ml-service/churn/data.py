"""Dataset generation and loading.

There is no public churn dataset bundled here on purpose: a deterministic
synthetic generator makes the project reproducible, keeps the repo small and —
because the label is generated from a known logistic function — lets you sanity
check that the model recovered the real signal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CATEGORY_LEVELS, DATASET_PATH, settings

# Ground-truth coefficients used to synthesise the label (log-odds).
_CONTRACT_EFFECT = {"month-to-month": 1.15, "one_year": 0.05, "two_year": -1.05}
_PAYMENT_EFFECT = {"credit_card": -0.35, "bank_transfer": -0.1, "e_wallet": 0.25, "mailed_check": 0.55}
_SERVICE_EFFECT = {"fiber": 0.45, "dsl": 0.0, "mobile": 0.2}
_CHANNEL_EFFECT = {"organic": -0.3, "paid_search": 0.1, "referral": -0.45, "partner": 0.0, "outbound": 0.6}
_REGION_EFFECT = {"north_america": 0.0, "europe": -0.15, "apac": 0.2, "latam": 0.35}

_DECISION_BOUNDARY = 1.1  # tuned so the synthetic churn rate lands around 26%


@dataclass
class DatasetSummary:
    n_rows: int
    churn_rate: float
    sha256: str

    def as_dict(self) -> dict:
        return {"n_rows": self.n_rows, "churn_rate": round(self.churn_rate, 4), "sha256": self.sha256}


def describe(df: pd.DataFrame) -> DatasetSummary:
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(df, index=False).values.tobytes()
    ).hexdigest()[:16]
    return DatasetSummary(n_rows=len(df), churn_rate=float(df[settings.target].mean()), sha256=digest)


def generate(n_samples: int | None = None, seed: int | None = None) -> pd.DataFrame:
    """Create a realistic-ish telecom customer table with a known churn label."""
    n = n_samples or settings.n_samples
    rng = np.random.default_rng(seed if seed is not None else settings.random_seed)

    contract = rng.choice(list(_CONTRACT_EFFECT), size=n, p=[0.55, 0.25, 0.20])
    payment = rng.choice(list(_PAYMENT_EFFECT), size=n, p=[0.42, 0.26, 0.20, 0.12])
    service = rng.choice(list(_SERVICE_EFFECT), size=n, p=[0.46, 0.34, 0.20])
    channel = rng.choice(list(_CHANNEL_EFFECT), size=n, p=[0.34, 0.24, 0.16, 0.14, 0.12])
    region = rng.choice(list(_REGION_EFFECT), size=n, p=[0.42, 0.28, 0.20, 0.10])

    tenure = np.clip(rng.gamma(shape=2.1, scale=11.0, size=n), 1, 72).round().astype(int)
    base_charge = np.where(service == "fiber", 78.0, np.where(service == "dsl", 52.0, 34.0))
    monthly_charges = np.clip(
        base_charge + rng.normal(0, 12.0, size=n) + rng.integers(0, 4, size=n) * 5.0, 15, 160
    ).round(2)
    total_charges = (monthly_charges * tenure * rng.uniform(0.92, 1.08, size=n)).round(2)

    usage = np.clip(rng.gamma(2.0, 42.0, size=n), 1, 600).round(1)
    usage_change = np.clip(rng.normal(-3.0, 18.0, size=n), -85, 60).round(1)
    support_tickets = rng.poisson(np.where(service == "fiber", 1.5, 0.9), size=n)
    late_payments = rng.poisson(0.7, size=n)
    num_products = np.clip(rng.poisson(1.8, size=n), 1, 6)

    log_odds = (
        -1.15
        + 0.85 * (monthly_charges / 60.0)
        - 0.055 * tenure
        - 0.035 * usage_change
        + 0.30 * support_tickets
        + 0.42 * late_payments
        - 0.18 * num_products
        + np.vectorize(_CONTRACT_EFFECT.get)(contract)
        + np.vectorize(_PAYMENT_EFFECT.get)(payment)
        + np.vectorize(_SERVICE_EFFECT.get)(service)
        + np.vectorize(_CHANNEL_EFFECT.get)(channel)
        + np.vectorize(_REGION_EFFECT.get)(region)
        - _DECISION_BOUNDARY
    )
    probability = 1.0 / (1.0 + np.exp(-log_odds))
    churned = (rng.random(n) < probability).astype(int)

    df = pd.DataFrame(
        {
            "customer_id": [f"C{100000 + i}" for i in range(n)],
            "tenure_months": tenure,
            "monthly_charges": monthly_charges,
            "total_charges": total_charges,
            "support_tickets_90d": support_tickets,
            "late_payments_12m": late_payments,
            "usage_change_pct": usage_change,
            "num_products": num_products,
            "avg_monthly_usage_gb": usage,
            "contract_type": contract,
            "payment_method": payment,
            "internet_service": service,
            "signup_channel": channel,
            "region": region,
            "churned": churned,
        }
    )
    # A little deliberate messiness so the pipeline has to be robust.
    missing_idx = rng.choice(n, size=max(1, n // 200), replace=False)
    df.loc[missing_idx, "avg_monthly_usage_gb"] = np.nan
    return df


def load_or_create(path: Path | None = None) -> pd.DataFrame:
    target = Path(path or DATASET_PATH)
    if target.exists():
        return pd.read_csv(target)
    df = generate()
    prepare_dirs(target.parent)
    df.to_csv(target, index=False)
    return df


def prepare_dirs(*dirs: Path) -> None:
    for directory in dirs:
        Path(directory).mkdir(parents=True, exist_ok=True)


def validate_frame(df: pd.DataFrame) -> list[str]:
    """Schema validation. Returns a list of human-readable problems (empty = ok)."""
    problems: list[str] = []
    missing = [c for c in settings.feature_names if c not in df.columns]
    if missing:
        problems.append(f"missing columns: {missing}")
        return problems
    if settings.target not in df.columns:
        problems.append(f"missing target column {settings.target!r}")
    else:
        values = set(df[settings.target].dropna().unique().tolist())
        if not values <= {0, 1}:
            problems.append(f"target must be binary 0/1, found {sorted(values)[:5]}")
    for column in settings.numeric_features:
        if not pd.api.types.is_numeric_dtype(df[column]):
            problems.append(f"{column} must be numeric")
    for column, allowed in CATEGORY_LEVELS.items():
        unknown = set(df[column].dropna().unique()) - set(allowed)
        if unknown:
            problems.append(f"{column} has unknown categories: {sorted(unknown)}")
    return problems
