"""Drift detection tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from churn.config import settings
from churn.data import generate
from churn.monitoring import categorical_psi, drift_report, psi


def test_psi_is_zero_for_identical_distributions():
    rng = np.random.default_rng(0)
    sample = rng.normal(50, 10, 2000)
    assert psi(sample, sample) == pytest.approx(0.0, abs=1e-9)


def test_psi_grows_with_shift():
    rng = np.random.default_rng(1)
    reference = rng.normal(50, 10, 5000)
    mild = rng.normal(53, 10, 5000)
    severe = rng.normal(80, 10, 5000)
    assert psi(reference, reference) < psi(reference, mild) < psi(reference, severe)
    assert psi(reference, severe) > settings.drift_alert


def test_psi_handles_nan_and_constant_columns():
    reference = np.array([np.nan, 1.0, 1.0, 1.0])
    assert psi(reference, np.array([1.0, np.nan])) == 0.0


def test_categorical_psi_detects_new_distribution():
    reference = pd.Series(["a"] * 900 + ["b"] * 100)
    same = pd.Series(["a"] * 900 + ["b"] * 100)
    shifted = pd.Series(["a"] * 200 + ["b"] * 800)
    assert categorical_psi(reference, same) == pytest.approx(0.0, abs=1e-9)
    assert categorical_psi(reference, shifted) > 0.2


def test_drift_report_stable_batch():
    reference = generate(n_samples=1500, seed=21)
    current = generate(n_samples=300, seed=22)
    report = drift_report(reference, current)
    assert report["verdict"] == "stable"
    assert report["max_psi"] < settings.drift_warn
    assert len(report["features"]) == len(settings.numeric_features) + len(settings.categorical_features)


def test_drift_report_flags_shifted_batch():
    reference = generate(n_samples=1500, seed=31)
    current = generate(n_samples=300, seed=32).copy()
    current["monthly_charges"] = current["monthly_charges"] * 2.4  # billing change
    report = drift_report(reference, current)
    assert report["verdict"] in {"warning", "alert"}
    assert "monthly_charges" in (report["alerts"] + report["warnings"])
    assert report["worst_feature"] == "monthly_charges"
    numeric = next(f for f in report["features"] if f["feature"] == "monthly_charges")
    assert numeric["current_mean"] > numeric["reference_mean"]


def test_drift_report_validates_input():
    reference = generate(n_samples=200, seed=41)
    with pytest.raises(ValueError, match="at least 10"):
        drift_report(reference, reference.head(3))
    with pytest.raises(ValueError, match="empty"):
        drift_report(reference, reference.iloc[0:0])
