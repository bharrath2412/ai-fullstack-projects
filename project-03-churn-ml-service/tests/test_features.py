"""Feature pipeline tests: shapes, NaN handling, derived features, leakage guards."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from churn.config import settings
from churn.data import generate, validate_frame
from churn.features import CategoryFrequencyEncoder, RatioFeatures, build_preprocessor


@pytest.fixture(scope="module")
def frame():
    return generate(n_samples=300, seed=7)


def test_generate_is_deterministic():
    a = generate(n_samples=100, seed=11)
    b = generate(n_samples=100, seed=11)
    pd.testing.assert_frame_equal(a, b)


def test_generate_has_all_columns(frame):
    for column in settings.feature_names:
        assert column in frame.columns, f"missing {column}"
    assert settings.target in frame.columns
    assert frame[settings.target].isin([0, 1]).all()


def test_validate_frame_accepts_generated(frame):
    assert validate_frame(frame) == []


def test_validate_frame_reports_problems(frame):
    broken = frame.drop(columns=["tenure_months"])
    problems = validate_frame(broken)
    assert any("missing columns" in p for p in problems)

    bad_target = frame.copy()
    bad_target[settings.target] = 2
    assert any("binary" in p for p in validate_frame(bad_target))

    bad_category = frame.copy()
    bad_category.loc[0, "contract_type"] = "lifetime"
    assert any("unknown categories" in p for p in validate_frame(bad_category))


def test_ratio_features_are_sane(frame):
    transformer = RatioFeatures().fit(frame)
    out = transformer.transform(frame.head(20))
    names = transformer.get_feature_names_out()

    assert out.shape == (20, len(names))
    assert np.isfinite(out).all(), "derived features must never contain NaN/inf"
    revenue_per_month = out[:, list(names).index("revenue_per_month_of_tenure")]
    assert (revenue_per_month > 0).all()


def test_ratio_features_survive_missing_usage(frame):
    broken = frame.head(5).copy()
    broken["avg_monthly_usage_gb"] = np.nan
    transformer = RatioFeatures().fit(frame)
    out = transformer.transform(broken)
    assert np.isfinite(out).all()


def test_category_frequency_encoder_handles_unseen_levels(frame):
    encoder = CategoryFrequencyEncoder().fit(frame)
    unseen = frame.head(3).copy()
    unseen["region"] = "antarctica"
    out = encoder.transform(unseen)
    assert out.shape == (3, len(settings.categorical_features))
    assert np.isfinite(out).all()


def test_preprocessor_output_is_stable(frame):
    preprocessor = build_preprocessor()
    preprocessor.fit(frame[settings.feature_names], frame[settings.target])
    transformed = preprocessor.transform(frame[settings.feature_names].head(10))
    assert transformed.shape[0] == 10
    assert np.isfinite(transformed).all()

    names = list(preprocessor.get_feature_names_out())
    assert len(names) == transformed.shape[1]
    # Derived + encoded features should be present
    assert any("charge_vs_median" in n for n in names)
    assert any("contract_type" in n for n in names)


def test_preprocessor_ignores_unknown_categories_at_inference(frame):
    preprocessor = build_preprocessor()
    preprocessor.fit(frame[settings.feature_names], frame[settings.target])
    unseen = frame.head(2).copy()
    unseen["payment_method"] = "crypto"
    out = preprocessor.transform(unseen[settings.feature_names])
    assert np.isfinite(out).all()
