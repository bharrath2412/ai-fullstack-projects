"""FastAPI inference service for the churn model.

    uvicorn churn.service:app --reload --port 8100
    open http://localhost:8100/docs
    open http://localhost:8100/report        # HTML model report

Endpoints
---------
GET  /health            liveness + loaded model version
GET  /model/info        full metadata (metrics, importances, dataset summary)
GET  /model/versions    registry index
POST /predict           one customer -> probability, decision, risk band
POST /predict/batch     up to 500 customers -> predictions + segment summary
POST /explain           prediction + one-at-a-time counterfactual contributions
POST /monitor/drift     PSI drift report for an incoming batch
GET  /report            rendered HTML model report
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import ARTIFACT_DIR, REPORT_PATH, settings
from .monitoring import drift_report
from .registry import ModelRegistry
from .schemas import (
    BatchRequest,
    BatchResponse,
    Contribution,
    CustomerFeatures,
    DriftRequest,
    ExplanationResponse,
    ModelInfoResponse,
    PredictionResponse,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("churn.service")

STATE: dict[str, Any] = {}


def risk_band(probability: float) -> str:
    if probability < 0.2:
        return "low"
    if probability < 0.4:
        return "medium"
    if probability < 0.6:
        return "high"
    return "critical"


def load_state() -> None:
    """Load the latest registered model, training a small one if none exists."""
    registry = ModelRegistry()
    try:
        model = registry.load_latest()
        logger.info("loaded model %s", model.version)
    except FileNotFoundError:
        logger.warning("no registered model found — training a small bootstrap model")
        from .train import train

        train(samples=1500, cv_folds=0, fast=True)
        model = registry.load_latest()

    pipeline = model.pipeline
    threshold = float(model.metadata.get("threshold", 0.5))

    reference_path = ARTIFACT_DIR / "reference.csv"
    reference = (
        pd.read_csv(reference_path)
        if reference_path.exists()
        else pd.DataFrame(columns=settings.feature_names)
    )
    baselines: dict[str, Any] = {}
    if not reference.empty:
        for column in settings.numeric_features:
            baselines[column] = float(reference[column].median())
        for column in settings.categorical_features:
            baselines[column] = str(reference[column].mode().iloc[0])

    STATE.update(
        {
            "model": model,
            "pipeline": pipeline,
            "threshold": threshold,
            "reference": reference,
            "baselines": baselines,
            "registry": registry,
        }
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    load_state()
    yield
    STATE.clear()


app = FastAPI(
    title="Churn Prediction Service",
    version="1.0.0",
    description="Gradient-boosted churn scoring with threshold tuning, explanations and drift monitoring.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request, exc):  # noqa: ANN001
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": str(exc)}})


def _predict_frame(pipeline, frame: pd.DataFrame) -> np.ndarray:
    return pipeline.predict_proba(frame[settings.feature_names])[:, 1]


def _to_response(customer_id: str | None, probability: float, threshold: float, version: str) -> PredictionResponse:
    return PredictionResponse(
        customer_id=customer_id,
        churn_probability=round(float(probability), 4),
        will_churn=bool(probability >= threshold),
        risk_band=risk_band(float(probability)),
        threshold=round(threshold, 4),
        model_version=version,
    )


# --------------------------------------------------------------------------- #
@app.get("/health")
async def health() -> dict[str, Any]:
    model = STATE.get("model")
    return {
        "status": "ok" if model else "degraded",
        "model_version": model.version if model else None,
        "threshold": STATE.get("threshold"),
        "reference_rows": int(len(STATE.get("reference", []))),
    }


@app.get("/model/info", response_model=ModelInfoResponse)
async def model_info() -> ModelInfoResponse:
    model = STATE["model"]
    meta = model.metadata
    return ModelInfoResponse(
        version=model.version,
        model_type=meta.get("model_type", "unknown"),
        threshold=float(meta.get("threshold", 0.5)),
        metrics=meta.get("metrics", {}),
        cv=meta.get("cv", {}),
        dataset=meta.get("dataset", {}),
        feature_names=meta.get("feature_names", []),
        importances=meta.get("importances", []),
        training_rows=int(meta.get("training_rows", 0)),
        created_at=meta.get("created_at", ""),
        levels=meta.get("levels", {}),
    )


@app.get("/model/versions")
async def model_versions() -> dict[str, Any]:
    return {"items": STATE["registry"].list_versions()}


@app.post("/predict", response_model=PredictionResponse)
async def predict(customer: CustomerFeatures) -> PredictionResponse:
    frame = pd.DataFrame([customer.to_record()])
    probability = _predict_frame(STATE["pipeline"], frame)[0]
    return _to_response(customer.customer_id, probability, STATE["threshold"], STATE["model"].version)


@app.post("/predict/batch", response_model=BatchResponse)
async def predict_batch(payload: BatchRequest) -> BatchResponse:
    started = time.perf_counter()
    frame = pd.DataFrame([c.to_record() for c in payload.customers])
    probabilities = _predict_frame(STATE["pipeline"], frame)
    threshold, version = STATE["threshold"], STATE["model"].version

    predictions = [
        _to_response(customer.customer_id, probability, threshold, version)
        for customer, probability in zip(payload.customers, probabilities)
    ]

    bands = pd.Series([p.risk_band for p in predictions]).value_counts().to_dict()
    flagged = [p for p in predictions if p.will_churn]
    frame["probability"] = probabilities
    high_value = frame.loc[frame["probability"] >= 0.6, "total_charges"].sum()

    summary = {
        "count": len(predictions),
        "flagged": len(flagged),
        "flagged_share": round(len(flagged) / len(predictions), 4),
        "mean_probability": round(float(np.mean(probabilities)), 4),
        "risk_bands": bands,
        "revenue_at_risk": round(float(high_value), 2),
    }
    return BatchResponse(
        predictions=predictions,
        summary=summary,
        model_version=version,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )


@app.post("/explain", response_model=ExplanationResponse)
async def explain(customer: CustomerFeatures) -> ExplanationResponse:
    """One-at-a-time counterfactual sensitivity (not SHAP).

    For each feature we reset it to the training baseline, re-score the customer
    and report how the probability moves. Cheap, model-agnostic and honest about
    what it measures.
    """
    pipeline = STATE["pipeline"]
    baselines: dict[str, Any] = STATE["baselines"]
    record = customer.to_record()
    frame = pd.DataFrame([record])

    base_probability = float(_predict_frame(pipeline, frame)[0])
    contributions: list[Contribution] = []

    for feature in settings.feature_names:
        if feature not in baselines:
            continue
        # Rebuild the row instead of mutating the column (avoids pandas dtype churn).
        perturbed_record = {**record, feature: baselines[feature]}
        counterfactual = float(_predict_frame(pipeline, pd.DataFrame([perturbed_record]))[0])
        impact = base_probability - counterfactual  # >0 means this value raises risk
        contributions.append(
            Contribution(
                feature=feature,
                value=record[feature],
                baseline=baselines[feature],
                impact=round(impact, 4),
                direction="increases" if impact > 0.01 else "decreases" if impact < -0.01 else "neutral",
            )
        )

    contributions.sort(key=lambda c: abs(c.impact), reverse=True)
    return ExplanationResponse(
        prediction=_to_response(
            customer.customer_id, base_probability, STATE["threshold"], STATE["model"].version
        ),
        baseline_probability=round(base_probability, 4),
        contributions=contributions[:8],
        note=(
            "Contribution = probability drop when the feature is reset to the training median/mode. "
            "It is a one-at-a-time sensitivity, not a Shapley value; correlated features share credit."
        ),
    )


@app.post("/monitor/drift")
async def monitor_drift(payload: DriftRequest) -> dict[str, Any]:
    reference = STATE.get("reference")
    if reference is None or reference.empty:
        raise HTTPException(status_code=503, detail="reference distribution unavailable")
    current = pd.DataFrame([c.to_record() for c in payload.customers])
    try:
        return drift_report(reference, current)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/report", include_in_schema=False)
async def report() -> FileResponse:
    if not Path(REPORT_PATH).exists():
        raise HTTPException(status_code=404, detail="Train the model first: python -m churn.train")
    return FileResponse(REPORT_PATH)
