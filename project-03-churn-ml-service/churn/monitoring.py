"""Data drift detection with Population Stability Index (PSI).

PSI compares the distribution of a feature in a reference (training) window with
a current window. Rules of thumb used here: < 0.10 stable, 0.10–0.25 warning,
> 0.25 significant shift (alert). Chi-square p-values are also reported for
categorical features as a second opinion.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .config import settings

EPSILON = 1e-6


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index between two numeric samples."""
    reference = np.asarray(reference, dtype=float)
    current = np.asarray(current, dtype=float)
    reference = reference[np.isfinite(reference)]
    current = current[np.isfinite(current)]
    if reference.size == 0 or current.size == 0:
        return 0.0

    # Quantile edges from the reference distribution, de-duplicated.
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if edges.size < 2:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf

    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)
    ref_pct = np.clip(ref_counts / max(ref_counts.sum(), 1), EPSILON, None)
    cur_pct = np.clip(cur_counts / max(cur_counts.sum(), 1), EPSILON, None)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def categorical_psi(reference: pd.Series, current: pd.Series) -> float:
    ref = reference.astype(str).value_counts(normalize=True)
    cur = current.astype(str).value_counts(normalize=True)
    index = ref.index.union(cur.index)
    ref_pct = np.clip(ref.reindex(index, fill_value=0).to_numpy(), EPSILON, None)
    cur_pct = np.clip(cur.reindex(index, fill_value=0).to_numpy(), EPSILON, None)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def _severity(value: float) -> str:
    if value >= settings.drift_alert:
        return "alert"
    if value >= settings.drift_warn:
        return "warning"
    return "stable"


def drift_report(reference: pd.DataFrame, current: pd.DataFrame) -> dict[str, Any]:
    """Per-feature PSI + chi-square, and an overall verdict."""
    if current.empty:
        raise ValueError("current batch is empty")
    if len(current) < 10:
        raise ValueError("need at least 10 rows to measure drift reliably")

    features: list[dict[str, Any]] = []
    for column in settings.numeric_features:
        value = psi(reference[column], current[column])
        features.append(
            {
                "feature": column,
                "kind": "numeric",
                "psi": round(value, 4),
                "severity": _severity(value),
                "reference_mean": round(float(reference[column].mean()), 3),
                "current_mean": round(float(current[column].mean()), 3),
            }
        )

    for column in settings.categorical_features:
        value = categorical_psi(reference[column], current[column])
        table = pd.crosstab(
            reference[column].astype(str).reindex(range(len(reference))).fillna("missing"),
            current[column].astype(str).reindex(range(len(current))).fillna("missing"),
        )
        p_value = 1.0
        try:
            p_value = float(stats.chi2_contingency(table.to_numpy())[1])
        except ValueError:
            p_value = float("nan")
        features.append(
            {
                "feature": column,
                "kind": "categorical",
                "psi": round(value, 4),
                "severity": _severity(value),
                "chi2_p_value": None if np.isnan(p_value) else round(p_value, 6),
            }
        )

    worst = max(features, key=lambda f: f["psi"])
    alerts = [f["feature"] for f in features if f["severity"] == "alert"]
    warnings = [f["feature"] for f in features if f["severity"] == "warning"]
    verdict = "alert" if alerts else "warning" if warnings else "stable"

    return {
        "verdict": verdict,
        "rows_compared": {"reference": int(len(reference)), "current": int(len(current))},
        "worst_feature": worst["feature"],
        "max_psi": worst["psi"],
        "alerts": alerts,
        "warnings": warnings,
        "thresholds": {"warn": settings.drift_warn, "alert": settings.drift_alert},
        "features": sorted(features, key=lambda f: f["psi"], reverse=True),
    }
