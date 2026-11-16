"""HTTP-level tests for the inference service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from churn.data import generate
from churn.service import app

CUSTOMER = {
    "customer_id": "C-TEST-1",
    "tenure_months": 3,
    "monthly_charges": 95.5,
    "total_charges": 290.0,
    "support_tickets_90d": 4,
    "late_payments_12m": 3,
    "usage_change_pct": -35.0,
    "num_products": 1,
    "avg_monthly_usage_gb": 38.0,
    "contract_type": "month-to-month",
    "payment_method": "e_wallet",
    "internet_service": "fiber",
    "signup_channel": "outbound",
    "region": "apac",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_version"]
    assert 0 < body["threshold"] < 1


def test_model_info(client):
    body = client.get("/model/info").json()
    assert body["model_type"] == "HistGradientBoostingClassifier"
    assert body["metrics"]["roc_auc"] > 0.7
    assert len(body["feature_names"]) == 13
    assert body["importances"]


def test_predict_high_risk_customer(client):
    response = client.post("/predict", json=CUSTOMER)
    assert response.status_code == 200
    body = response.json()
    assert 0.0 <= body["churn_probability"] <= 1.0
    assert body["risk_band"] in {"low", "medium", "high", "critical"}
    assert isinstance(body["will_churn"], bool)


def test_risky_customer_scores_higher_than_loyal_one(client):
    loyal = {
        **CUSTOMER,
        "tenure_months": 60,
        "monthly_charges": 45.0,
        "total_charges": 2800.0,
        "support_tickets_90d": 0,
        "late_payments_12m": 0,
        "usage_change_pct": 12.0,
        "num_products": 3,
        "contract_type": "two_year",
        "payment_method": "credit_card",
        "signup_channel": "referral",
    }
    risky_probability = client.post("/predict", json=CUSTOMER).json()["churn_probability"]
    loyal_probability = client.post("/predict", json=loyal).json()["churn_probability"]
    assert risky_probability > loyal_probability


@pytest.mark.parametrize(
    "field,value",
    [
        ("monthly_charges", -5),
        ("tenure_months", -1),
        ("contract_type", "lifetime"),
        ("support_tickets_90d", 10_000),
        ("num_products", 0),
    ],
)
def test_predict_rejects_invalid_payloads(client, field, value):
    payload = {**CUSTOMER, field: value}
    response = client.post("/predict", json=payload)
    assert response.status_code == 422


def test_predict_rejects_unknown_fields(client):
    response = client.post("/predict", json={**CUSTOMER, "sneaky_extra": 1})
    assert response.status_code == 422


def test_batch_prediction_summary(client):
    payload = {"customers": [CUSTOMER, {**CUSTOMER, "customer_id": "C-TEST-2", "tenure_months": 48}]}
    response = client.post("/predict/batch", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert len(body["predictions"]) == 2
    assert body["summary"]["count"] == 2
    assert 0 <= body["summary"]["flagged_share"] <= 1
    assert body["duration_ms"] >= 0


def test_batch_limits_size(client):
    payload = {"customers": [CUSTOMER] * 501}
    assert client.post("/predict/batch", json=payload).status_code == 422


def test_explain_returns_ranked_contributions(client):
    response = client.post("/explain", json=CUSTOMER)
    assert response.status_code == 200
    body = response.json()
    assert body["prediction"]["customer_id"] == "C-TEST-1"
    assert body["contributions"]
    impacts = [abs(c["impact"]) for c in body["contributions"]]
    assert impacts == sorted(impacts, reverse=True)
    assert "not a Shapley value" in body["note"]


def test_drift_endpoint(client):
    frame = generate(n_samples=120, seed=99)
    customers = []
    for _, row in frame.iterrows():
        customers.append(
            {
                **{k: (None if row[k] != row[k] else row[k]) for k in [
                    "avg_monthly_usage_gb",
                ]},
                "tenure_months": int(row["tenure_months"]),
                "monthly_charges": float(row["monthly_charges"]),
                "total_charges": float(row["total_charges"]),
                "support_tickets_90d": int(row["support_tickets_90d"]),
                "late_payments_12m": int(row["late_payments_12m"]),
                "usage_change_pct": float(row["usage_change_pct"]),
                "num_products": int(row["num_products"]),
                "contract_type": row["contract_type"],
                "payment_method": row["payment_method"],
                "internet_service": row["internet_service"],
                "signup_channel": row["signup_channel"],
                "region": row["region"],
            }
        )
    response = client.post("/monitor/drift", json={"customers": customers})
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] in {"stable", "warning", "alert"}
    assert body["rows_compared"]["current"] == 120
    assert {"feature", "psi", "severity"} <= set(body["features"][0])


def test_report_is_served(client):
    response = client.get("/report")
    assert response.status_code in {200, 404}
    if response.status_code == 200:
        assert "churn" in response.text.lower()
