"""Feature engineering as reusable sklearn transformers.

Everything is wrapped in a Pipeline/ColumnTransformer so the exact same
transformations run at train time and at inference time — the classic source of
training/serving skew.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .config import settings


class RatioFeatures(BaseEstimator, TransformerMixin):
    """Derived business features that linear models cannot discover alone."""

    def fit(self, X: pd.DataFrame, y=None):  # noqa: D102
        # Store medians so inference never sees NaN in derived ratios.
        self.charge_median_ = float(pd.to_numeric(X["monthly_charges"], errors="coerce").median())
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:  # noqa: D102
        frame = pd.DataFrame(index=X.index)
        tenure = pd.to_numeric(X["tenure_months"], errors="coerce").clip(lower=1)
        charges = pd.to_numeric(X["monthly_charges"], errors="coerce").fillna(self.charge_median_)
        total = pd.to_numeric(X["total_charges"], errors="coerce").fillna(charges * tenure)
        usage = pd.to_numeric(X["avg_monthly_usage_gb"], errors="coerce").fillna(0.0)

        frame["revenue_per_month_of_tenure"] = total / tenure
        frame["charge_vs_median"] = charges / max(self.charge_median_, 1e-6)
        frame["price_per_gb"] = charges / usage.clip(lower=0.5)
        frame["tickets_per_year"] = (
            pd.to_numeric(X["support_tickets_90d"], errors="coerce").fillna(0) * 4.0
        )
        frame["is_new_customer"] = (tenure <= 6).astype(int)
        frame["is_high_value"] = (total >= 1500).astype(int)
        frame["usage_declining"] = (pd.to_numeric(X["usage_change_pct"], errors="coerce") < -10).astype(int)
        return frame.to_numpy(dtype=float)

    def get_feature_names_out(self, input_features=None) -> np.ndarray:  # noqa: D102
        return np.asarray(
            [
                "revenue_per_month_of_tenure",
                "charge_vs_median",
                "price_per_gb",
                "tickets_per_year",
                "is_new_customer",
                "is_high_value",
                "usage_declining",
            ],
            dtype=object,
        )


class CategoryFrequencyEncoder(BaseEstimator, TransformerMixin):
    """Encode how common each category is — a cheap proxy for segment size."""

    def __init__(self, columns: list[str] | None = None):
        self.columns = columns or list(settings.categorical_features)

    def fit(self, X: pd.DataFrame, y=None):  # noqa: D102
        self.frequencies_: dict[str, dict[str, float]] = {}
        n = len(X)
        for column in self.columns:
            counts = X[column].astype(str).value_counts(normalize=True)
            self.frequencies_[column] = counts.to_dict()
        self.default_ = 1.0 / max(n, 1)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:  # noqa: D102
        out = np.empty((len(X), len(self.columns)), dtype=float)
        for j, column in enumerate(self.columns):
            mapping = self.frequencies_[column]
            out[:, j] = X[column].astype(str).map(mapping).fillna(self.default_).to_numpy()
        return out

    def get_feature_names_out(self, input_features=None) -> np.ndarray:  # noqa: D102
        return np.asarray([f"{c}_frequency" for c in self.columns], dtype=object)


def build_preprocessor() -> ColumnTransformer:
    """Numeric + derived + categorical preprocessing."""
    numeric_pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, list(settings.numeric_features)),
            ("ratios", Pipeline([("ratios", RatioFeatures()), ("scale", StandardScaler())]), list(settings.numeric_features)),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False, min_frequency=5),
                list(settings.categorical_features),
            ),
            ("frequency", CategoryFrequencyEncoder(), list(settings.categorical_features)),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def feature_names(preprocessor: ColumnTransformer) -> list[str]:
    try:
        return [str(name) for name in preprocessor.get_feature_names_out()]
    except Exception:  # noqa: BLE001 - older sklearn or unfitted transformer
        return []
