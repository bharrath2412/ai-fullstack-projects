"""Training entrypoint: prepare data -> fit pipeline -> tune threshold -> register.

    python -m churn.train                 # full dataset
    python -m churn.train --samples 1500  # quick run
    python -m churn.train --cv 0          # skip cross-validation
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline

from .config import ARTIFACT_DIR, REPORT_PATH, settings
from .data import describe, generate, load_or_create, prepare_dirs, validate_frame
from .features import build_preprocessor, feature_names
from .registry import ModelRegistry


@dataclass
class TrainingResult:
    version: str
    threshold: float
    metrics: dict[str, float]
    cv: dict[str, Any]
    dataset: dict[str, Any]
    confusion: list[list[int]]
    curves: dict[str, list[float]] = field(default_factory=dict)
    importances: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "threshold": self.threshold,
            "metrics": self.metrics,
            "cv": self.cv,
            "dataset": self.dataset,
            "confusion_matrix": self.confusion,
            "duration_seconds": round(self.duration_seconds, 2),
            "report_path": self.report_path,
        }


def build_pipeline(*, fast: bool = False, seed: int | None = None) -> Pipeline:
    classifier = HistGradientBoostingClassifier(
        max_iter=120 if fast else 350,
        learning_rate=0.07,
        max_leaf_nodes=31,
        min_samples_leaf=20,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.12,
        n_iter_no_change=20,
        random_state=seed if seed is not None else settings.random_seed,
    )
    return Pipeline(
        steps=[
            ("preprocess", build_preprocessor()),
            ("classifier", classifier),
        ]
    )


def compute_metrics(y_true: np.ndarray, proba: np.ndarray, threshold: float) -> dict[str, float]:
    predictions = (proba >= threshold).astype(int)
    return {
        "roc_auc": round(float(roc_auc_score(y_true, proba)), 4),
        "pr_auc": round(float(average_precision_score(y_true, proba)), 4),
        "accuracy": round(float(accuracy_score(y_true, predictions)), 4),
        "precision": round(float(precision_score(y_true, predictions, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, predictions, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, predictions, zero_division=0)), 4),
        "brier": round(float(brier_score_loss(y_true, proba)), 4),
        "churn_rate_actual": round(float(np.mean(y_true)), 4),
        "churn_rate_predicted": round(float(np.mean(predictions)), 4),
        "threshold": round(float(threshold), 4),
    }


def tune_threshold(y_true: np.ndarray, proba: np.ndarray, min_recall: float | None = None) -> float:
    """Pick the threshold that maximises F1 while honouring a recall floor."""
    floor = settings.min_recall if min_recall is None else min_recall
    precisions, recalls, thresholds = precision_recall_curve(y_true, proba)
    f1 = np.divide(
        2 * precisions * recalls,
        precisions + recalls,
        out=np.zeros_like(precisions),
        where=(precisions + recalls) > 0,
    )
    candidates = np.where(recalls[:-1] >= floor)[0]
    if candidates.size == 0:
        candidates = np.arange(len(thresholds))
    best = candidates[int(np.argmax(f1[candidates]))]
    return float(np.clip(thresholds[best], 0.05, 0.95))


def cross_validate(df: pd.DataFrame, folds: int) -> dict[str, Any]:
    if folds < 2:
        return {"folds": 0, "roc_auc_mean": None, "roc_auc_std": None}
    X, y = df[settings.feature_names], df[settings.target].to_numpy()
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=settings.random_seed)
    scores: list[float] = []
    for train_idx, valid_idx in skf.split(X, y):
        pipeline = build_pipeline(fast=True)
        pipeline.fit(X.iloc[train_idx], y[train_idx])
        proba = pipeline.predict_proba(X.iloc[valid_idx])[:, 1]
        scores.append(roc_auc_score(y[valid_idx], proba))
    return {
        "folds": folds,
        "roc_auc_mean": round(float(np.mean(scores)), 4),
        "roc_auc_std": round(float(np.std(scores)), 4),
        "roc_auc_scores": [round(float(s), 4) for s in scores],
    }


def train(
    df: pd.DataFrame | None = None,
    *,
    samples: int | None = None,
    cv_folds: int | None = None,
    fast: bool = False,
    version: str | None = None,
    write_report_file: bool = True,
) -> TrainingResult:
    started = time.perf_counter()
    settings.validate()

    if df is None:
        if samples is not None:
            df = generate(n_samples=samples)
        else:
            df = load_or_create()

    problems = validate_frame(df)
    if problems:
        raise ValueError(f"Dataset failed validation: {problems}")

    X = df[settings.feature_names]
    y = df[settings.target].to_numpy()

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=settings.test_size,
        random_state=settings.random_seed,
        stratify=y,
    )

    pipeline = build_pipeline(fast=fast)
    pipeline.fit(X_train, y_train)
    proba = pipeline.predict_proba(X_test)[:, 1]

    threshold = settings.decision_threshold or tune_threshold(y_test, proba)
    metrics = compute_metrics(y_test, proba, threshold)
    confusion = confusion_matrix(y_test, (proba >= threshold).astype(int)).tolist()

    cv = cross_validate(df, cv_folds if cv_folds is not None else settings.cv_folds)

    # Permutation importance on the held-out split (model-agnostic).
    importance = permutation_importance(
        pipeline,
        X_test,
        y_test,
        scoring="roc_auc",
        n_repeats=4,
        random_state=settings.random_seed,
    )
    importances = sorted(
        (
            {"feature": name, "importance": round(float(mean), 4)}
            for name, mean in zip(settings.feature_names, importance.importances_mean)
        ),
        key=lambda row: row["importance"],
        reverse=True,
    )

    fpr, tpr, _ = roc_curve(y_test, proba)
    precision, recall, _ = precision_recall_curve(y_test, proba)
    curves = {
        "fpr": [round(float(v), 4) for v in fpr[:: max(1, len(fpr) // 120)]],
        "tpr": [round(float(v), 4) for v in tpr[:: max(1, len(tpr) // 120)]],
        "precision": [round(float(v), 4) for v in precision[:: max(1, len(precision) // 120)]],
        "recall": [round(float(v), 4) for v in recall[:: max(1, len(recall) // 120)]],
    }

    dataset_summary = describe(df).as_dict()
    version = version or f"v{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    duration = time.perf_counter() - started

    metadata = {
        "version": version,
        "model_type": "HistGradientBoostingClassifier",
        "threshold": round(float(threshold), 4),
        "metrics": metrics,
        "cv": cv,
        "dataset": dataset_summary,
        "feature_names": settings.feature_names,
        "numeric_features": list(settings.numeric_features),
        "categorical_features": list(settings.categorical_features),
        "levels": {k: list(v) for k, v in __import__("churn.config", fromlist=["CATEGORY_LEVELS"]).CATEGORY_LEVELS.items()},
        "importances": importances,
        "training_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "duration_seconds": round(duration, 2),
        "sklearn_pipeline_steps": list(pipeline.named_steps),
    }

    registry = ModelRegistry()
    registry.save(pipeline, metadata, version=version)

    # Reference distribution for drift monitoring is the training feature set.
    prepare_dirs(ARTIFACT_DIR)
    X_train.assign(**{settings.target: y_train}).to_csv(
        ARTIFACT_DIR / "reference.csv", index=False
    )

    result = TrainingResult(
        version=version,
        threshold=float(threshold),
        metrics=metrics,
        cv=cv,
        dataset=dataset_summary,
        confusion=confusion,
        curves=curves,
        importances=importances,
        duration_seconds=duration,
    )
    if write_report_file:
        result.report_path = str(write_html_report(result, pipeline))
    return result


# --------------------------------------------------------------------------- #
# HTML report (self-contained, inline SVG — no JS, no CDN)
# --------------------------------------------------------------------------- #
def _bar_chart(importances: list[dict[str, Any]], width: int = 520) -> str:
    if not importances:
        return ""
    peak = max(row["importance"] for row in importances) or 1.0
    row_height = 26
    height = row_height * len(importances) + 10
    bars = []
    for i, row in enumerate(importances):
        bar_width = max(2.0, (row["importance"] / peak) * (width - 200))
        y = 6 + i * row_height
        bars.append(
            f'<text x="0" y="{y + 12}" font-size="11" fill="#94a3b8">{row["feature"]}</text>'
            f'<rect x="185" y="{y}" width="{bar_width:.1f}" height="15" rx="4" fill="url(#g1)"/>'
            f'<text x="{190 + bar_width:.1f}" y="{y + 12}" font-size="10" fill="#cbd5e1">'
            f'{row["importance"]:.3f}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}">'
        f'<defs><linearGradient id="g1" x1="0" x2="1"><stop offset="0" stop-color="#818cf8"/>'
        f'<stop offset="1" stop-color="#38bdf8"/></linearGradient></defs>{"".join(bars)}</svg>'
    )


def _curve_svg(curves: dict[str, list[float]], width: int = 320, height: int = 240) -> str:
    fpr, tpr = curves.get("fpr", []), curves.get("tpr", [])
    if len(fpr) < 2:
        return ""
    pad = 28
    points = " ".join(
        f"{pad + x * (width - pad * 2):.1f},{height - pad - y * (height - pad * 2):.1f}"
        for x, y in zip(fpr, tpr)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img">'
        f'<rect x="{pad}" y="{pad}" width="{width - pad * 2}" height="{height - pad * 2}" '
        f'fill="none" stroke="rgba(148,163,184,.25)"/>'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{pad}" '
        f'stroke="rgba(148,163,184,.3)" stroke-dasharray="4 4"/>'
        f'<polyline points="{points}" fill="none" stroke="#38bdf8" stroke-width="2"/>'
        f'<text x="{pad}" y="{height - 8}" font-size="10" fill="#94a3b8">false positive rate</text>'
        f'<text x="{pad}" y="{pad - 8}" font-size="10" fill="#94a3b8">true positive rate</text>'
        f"</svg>"
    )


def _confusion_html(confusion: list[list[int]]) -> str:
    (tn, fp), (fn, tp) = confusion
    cells = [
        ("True negative", tn, "#10b98122"),
        ("False positive", fp, "#f59e0b22"),
        ("False negative", fn, "#ef444422"),
        ("True positive", tp, "#10b98122"),
    ]
    return (
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">'
        + "".join(
            f'<div style="padding:12px;border-radius:10px;background:{bg};border:1px solid rgba(148,163,184,.18)">'
            f'<div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em">{label}</div>'
            f'<div style="font-size:24px;font-weight:700;margin-top:4px">{value:,}</div></div>'
            for label, value, bg in cells
        )
        + "</div>"
    )


def write_html_report(result: TrainingResult, pipeline: Pipeline) -> Path:
    prepare_dirs(REPORT_PATH.parent)
    metrics = result.metrics
    cards = "".join(
        f'<div class="card"><div class="k">{label}</div><div class="v">{metrics[key]}</div></div>'
        for label, key in [
            ("ROC AUC", "roc_auc"),
            ("PR AUC", "pr_auc"),
            ("Precision", "precision"),
            ("Recall", "recall"),
            ("F1", "f1"),
            ("Brier", "brier"),
        ]
    )
    cv_text = (
        f'{result.cv.get("roc_auc_mean")} ± {result.cv.get("roc_auc_std")} over {result.cv.get("folds")} folds'
        if result.cv.get("roc_auc_mean") is not None
        else "not run"
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Churn model report · {result.version}</title>
<style>
  :root{{--bg:#080d17;--panel:#0f1829;--line:rgba(148,163,184,.18);--text:#e6edf7;--muted:#93a3bd;--accent:#818cf8}}
  *{{box-sizing:border-box}}
  body{{margin:0;padding:2rem;background:radial-gradient(900px 500px at 10% -10%,rgba(129,140,248,.18),transparent 60%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}}
  .wrap{{max-width:1000px;margin:0 auto}}
  h1{{font-size:1.4rem;margin:0 0 .3rem}} h2{{font-size:.95rem;margin:0 0 .8rem;color:#c7d2fe}}
  .sub{{color:var(--muted);font-size:.82rem;margin-bottom:1.5rem}}
  .grid{{display:grid;gap:.8rem}} .g6{{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}}
  .g2{{grid-template-columns:1.1fr .9fr}}
  .panel{{background:rgba(15,24,41,.8);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;margin-bottom:1rem}}
  .card{{background:rgba(8,13,23,.6);border:1px solid var(--line);border-radius:12px;padding:.75rem .85rem}}
  .k{{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}}
  .v{{font-size:1.5rem;font-weight:700;margin-top:.2rem}}
  table{{width:100%;border-collapse:collapse;font-size:.82rem}}
  th,td{{text-align:left;padding:.45rem .5rem;border-bottom:1px solid var(--line)}}
  th{{color:var(--muted);font-weight:600;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em}}
  code{{font-family:ui-monospace,Menlo,monospace;font-size:.78em;color:#a5b4fc}}
  .pill{{display:inline-block;padding:.18rem .5rem;border-radius:999px;border:1px solid var(--line);font-size:.7rem;color:var(--muted)}}
  @media(max-width:820px){{.g2{{grid-template-columns:1fr}}}}
</style></head>
<body><div class="wrap">
  <h1>Customer churn — model report</h1>
  <p class="sub">
    Version <code>{result.version}</code> ·
    <span class="pill">HistGradientBoosting</span>
    <span class="pill">threshold {result.threshold:.3f}</span>
    <span class="pill">{result.dataset["n_rows"]:,} rows · {result.dataset["churn_rate"]:.1%} churn</span>
    <span class="pill">trained in {result.duration_seconds:.1f}s</span>
  </p>

  <section class="panel">
    <h2>Held-out performance</h2>
    <div class="grid g6">{cards}</div>
    <p class="sub" style="margin:.9rem 0 0">Cross-validation ROC AUC: {cv_text}</p>
  </section>

  <div class="grid g2">
    <section class="panel">
      <h2>Permutation importance (ROC AUC drop)</h2>
      {_bar_chart(result.importances)}
    </section>
    <section class="panel">
      <h2>ROC curve</h2>
      {_curve_svg(result.curves)}
      <h2 style="margin-top:1rem">Confusion matrix @ {result.threshold:.2f}</h2>
      {_confusion_html(result.confusion)}
    </section>
  </div>

  <section class="panel">
    <h2>Metrics table</h2>
    <table>
      <thead><tr><th>Metric</th><th>Value</th><th>What it means</th></tr></thead>
      <tbody>
        <tr><td>ROC AUC</td><td>{metrics["roc_auc"]}</td><td>Ranking quality across all thresholds</td></tr>
        <tr><td>PR AUC</td><td>{metrics["pr_auc"]}</td><td>Precision/recall trade-off for the minority class</td></tr>
        <tr><td>Precision</td><td>{metrics["precision"]}</td><td>Share of flagged customers who really churn</td></tr>
        <tr><td>Recall</td><td>{metrics["recall"]}</td><td>Share of churners we catch (floor {settings.min_recall:.0%})</td></tr>
        <tr><td>F1</td><td>{metrics["f1"]}</td><td>Harmonic mean of the two</td></tr>
        <tr><td>Brier</td><td>{metrics["brier"]}</td><td>Calibration error of the probabilities</td></tr>
      </tbody>
    </table>
  </section>

  <section class="panel">
    <h2>Model card</h2>
    <table>
      <tbody>
        <tr><th>Intended use</th><td>Rank active customers by churn risk to prioritise retention outreach</td></tr>
        <tr><th>Data</th><td>Synthetic telecom-style table (deterministic seed {settings.random_seed}); {result.dataset["sha256"]}</td></tr>
        <tr><th>Features</th><td>{", ".join(result.importances[:3] and [r["feature"] for r in result.importances[:5]])} …</td></tr>
        <tr><th>Known limits</th><td>Synthetic label, no temporal validation, no fairness audit across regions</td></tr>
        <tr><th>Monitoring</th><td>PSI drift check per feature (warn 0.10 / alert 0.25) via <code>POST /monitor/drift</code></td></tr>
      </tbody>
    </table>
  </section>

  <p class="sub">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · regenerate with <code>python -m churn.train</code></p>
</div></body></html>"""
    REPORT_PATH.write_text(html)
    return REPORT_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the churn model")
    parser.add_argument("--samples", type=int, default=None, help="generate N synthetic rows")
    parser.add_argument("--cv", type=int, default=None, help="cross-validation folds (0 = skip)")
    parser.add_argument("--fast", action="store_true", help="fewer boosting iterations")
    parser.add_argument("--version", type=str, default=None)
    args = parser.parse_args()

    result = train(samples=args.samples, cv_folds=args.cv, fast=args.fast, version=args.version)
    print(json.dumps(result.to_dict(), indent=2))
    print(f"\nModel report: {result.report_path}")


if __name__ == "__main__":
    main()
