"""Training tests: metric sanity, threshold policy, registry round-trip."""

from __future__ import annotations

import json

import numpy as np
import pytest

from churn.config import settings
from churn.data import generate
from churn.registry import ModelRegistry
from churn.train import build_pipeline, compute_metrics, train, tune_threshold


def test_model_learns_the_signal(trained):
    assert trained.metrics["roc_auc"] > 0.75, "AUC should clearly beat random on synthetic data"
    assert trained.metrics["roc_auc"] < 0.99, "perfect AUC would suggest label leakage"
    assert trained.metrics["pr_auc"] > 0.45
    assert 0.05 <= trained.threshold <= 0.95


def test_threshold_honours_recall_floor(trained):
    assert trained.metrics["recall"] >= settings.min_recall - 0.02


def test_confusion_matrix_is_consistent(trained):
    (tn, fp), (fn, tp) = trained.confusion
    predicted_positive = fp + tp
    actual_positive = fn + tp
    assert predicted_positive > 0 and actual_positive > 0
    expected_precision = tp / predicted_positive
    assert abs(expected_precision - trained.metrics["precision"]) < 0.01


def test_metrics_keys_and_ranges():
    y = np.array([0, 0, 1, 0, 1, 1, 0, 1])
    proba = np.array([0.1, 0.2, 0.85, 0.35, 0.65, 0.9, 0.05, 0.4])
    metrics = compute_metrics(y, proba, 0.5)
    for key in ("roc_auc", "pr_auc", "precision", "recall", "f1", "brier"):
        assert 0.0 <= metrics[key] <= 1.0
    assert metrics["roc_auc"] == 1.0  # perfectly separable in this toy example


def test_tune_threshold_respects_min_recall():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    proba = np.clip(0.5 + 0.25 * (2 * y - 1) + rng.normal(0, 0.2, 500), 0.01, 0.99)
    threshold = tune_threshold(y, proba, min_recall=0.9)
    recall = ((proba >= threshold) & (y == 1)).sum() / (y == 1).sum()
    assert recall >= 0.85  # small tolerance for the discrete threshold grid


def test_pipeline_is_serialisable(trained):
    pipe = build_pipeline(fast=True)
    data = generate(n_samples=120, seed=3)
    pipe.fit(data[settings.feature_names], data[settings.target])
    proba = pipe.predict_proba(data[settings.feature_names].head(5))[:, 1]
    assert proba.shape == (5,)
    assert ((proba >= 0) & (proba <= 1)).all()


def test_registry_roundtrip(trained, tmp_path):
    registry = ModelRegistry(tmp_path)
    model = registry.save(
        pipeline=build_pipeline(fast=True).fit(
            generate(n_samples=80, seed=1)[settings.feature_names],
            generate(n_samples=80, seed=1)[settings.target],
        ),
        metadata={"threshold": 0.42, "metrics": {"roc_auc": 0.8}, "model_type": "test"},
        version="v-test-1",
    )
    assert model.version == "v-test-1"
    assert (tmp_path / "v-test-1" / "model.joblib").exists()

    loaded = registry.load_latest()
    assert loaded.metadata["threshold"] == 0.42
    assert loaded.pipeline is not None

    entries = json.loads((tmp_path / "index.json").read_text())
    assert entries[-1]["version"] == "v-test-1"
    assert entries[-1]["is_latest"] is True
    assert [e["version"] for e in registry.list_versions()] == ["v-test-1"]


def test_registry_reports_missing_version(tmp_path):
    registry = ModelRegistry(tmp_path)
    with pytest.raises(FileNotFoundError):
        registry.get("nope")
    with pytest.raises(FileNotFoundError):
        registry.load_latest()


def test_train_rejects_invalid_dataset():
    frame = generate(n_samples=150, seed=5).drop(columns=["monthly_charges"])
    with pytest.raises(ValueError, match="failed validation"):
        train(df=frame, cv_folds=0, write_report_file=False)
