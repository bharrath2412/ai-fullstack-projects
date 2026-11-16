# Churn ML service — train, explain, serve, monitor

An end-to-end machine-learning project that behaves like something you'd actually deploy:
deterministic data generation → leakage-safe sklearn pipeline → threshold tuning against a
business constraint → versioned registry → FastAPI scoring → counterfactual explanations →
PSI drift monitoring → self-contained HTML model report.

Current model on the bundled 6,000-row synthetic dataset:

| ROC AUC | PR AUC | Precision | Recall | F1 | Brier |
| --- | --- | --- | --- | --- | --- |
| **0.822** | 0.630 | 0.534 | 0.740 | 0.620 | 0.141 |

5-fold CV ROC AUC: **0.809 ± 0.013**. Decision threshold 0.232, tuned to keep recall ≥ 0.70
(missing a churner is ~5× more expensive than a wasted retention email — that policy lives in
`tune_threshold`, not in a slide deck).

![tests](https://img.shields.io/badge/tests-40%20passing-10b981) ![python](https://img.shields.io/badge/python-3.11%2B-3776ab) ![sklearn](https://img.shields.io/badge/scikit--learn-1.6-f7931e)

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m churn.train                 # trains, registers a version, writes the HTML report
uvicorn churn.service:app --port 8100 # http://localhost:8100/docs
open artifacts/model_report.html      # model card + charts (no CDN, renders offline)
```

`GET /report` serves the same HTML report from the API.

## What it does

**Data** (`churn/data.py`) — 6,000 telecom-style customers with a logistic ground truth, mild
class imbalance (26% churn), injected missing values and 13 features across 5 categories.
`validate_frame()` enforces schema, dtypes and category levels before training.

**Features** (`churn/features.py`) — all preprocessing is a fitted `ColumnTransformer`, so
train and inference cannot drift apart:
- median imputation + standardisation for 8 numeric features
- 7 derived ratios (`revenue_per_month_of_tenure`, `price_per_gb`, `usage_declining`, …)
- one-hot encoding with `handle_unknown="ignore"` (never crashes on a new plan name)
- category-frequency encoding as a cheap segment-size signal

**Training** (`churn/train.py`) — `HistGradientBoostingClassifier`, stratified holdout,
optional k-fold CV, permutation importance on the held-out split, ROC/PR curves, confusion
matrix, Brier score. Writes `artifacts/models/<version>/` plus a versioned `index.json`.

**Threshold tuning** — sweeps the PR curve for the F1-maximising threshold **subject to
`CHURN_MIN_RECALL`**. Override with `CHURN_THRESHOLD=0.5` if you want the naive default.

**Registry** (`churn/registry.py`) — `models/v<timestamp>/model.joblib` + `metadata.json`,
a newest-wins `index.json`, and `load_latest()` for serving. Rollback = point at an older version.

**Monitoring** (`churn/monitoring.py`) — PSI per feature (quantile bins, ε-smoothed) with
`stable / warning / alert` bands plus chi-square p-values for categoricals.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | loaded version, threshold, reference rows |
| GET | `/model/info` | metrics, CV, importances, dataset fingerprint |
| GET | `/model/versions` | registry index |
| POST | `/predict` | one customer → probability, decision, risk band |
| POST | `/predict/batch` | ≤500 customers → predictions + revenue-at-risk summary |
| POST | `/explain` | prediction + ranked one-at-a-time counterfactual contributions |
| POST | `/monitor/drift` | PSI report for an incoming batch (≥10 rows) |
| GET | `/report` | HTML model report |

```bash
curl -s localhost:8100/predict -H 'content-type: application/json' -d '{
  "customer_id":"C100123","tenure_months":4,"monthly_charges":89.5,"total_charges":356,
  "support_tickets_90d":3,"late_payments_12m":2,"usage_change_pct":-28.4,"num_products":1,
  "avg_monthly_usage_gb":41.2,"contract_type":"month-to-month","payment_method":"e_wallet",
  "internet_service":"fiber","signup_channel":"outbound","region":"apac"}' | python -m json.tool
```

```json
{
  "customer_id": "C100123",
  "churn_probability": 0.83,
  "will_churn": true,
  "risk_band": "critical",
  "threshold": 0.2324,
  "model_version": "v20261116-121803"
}
```

> `/explain` returns *one-at-a-time counterfactual sensitivity*: reset one feature to its
> training median/mode, re-score, report the delta. It is model-agnostic and cheap, and the
> response says explicitly that it is not a Shapley value.

## Tests

```bash
python -m pytest            # 40 tests
```

| File | Covers |
| --- | --- |
| `test_features.py` | determinism, schema validation, NaN/inf survival, unseen categories |
| `test_train.py` | AUC in a sane band (no leakage), recall floor, confusion/ precision consistency, registry round-trip, invalid dataset rejection |
| `test_monitoring.py` | PSI identity/shift behaviour, NaN handling, stable vs shifted batches |
| `test_service.py` | validation (422s), known risk ordering, batch limits, explanation ranking, drift endpoint, report |

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CHURN_SEED` | `42` | reproducibility |
| `CHURN_N_SAMPLES` | `6000` | synthetic rows |
| `CHURN_TEST_SIZE` | `0.2` | holdout share |
| `CHURN_CV_FOLDS` | `5` | cross-validation |
| `CHURN_THRESHOLD` | auto | pin the decision threshold |
| `CHURN_MIN_RECALL` | `0.70` | recall floor during tuning |
| `CHURN_DRIFT_WARN` / `CHURN_DRIFT_ALERT` | `0.10` / `0.25` | PSI bands |
| `CHURN_ARTIFACT_DIR` | `artifacts/` | registry + report location |

## Retraining

```bash
python -m churn.train --samples 20000 --cv 5 --version v2026-12-retrain
curl -X POST localhost:8100/monitor/drift -d @batch.json -H 'content-type: application/json'
# restart the service to pick up the new version (or call the reload hook you add in prod)
```

## Docker

```bash
docker build -t churn-service .
docker run -p 8100:8100 churn-service
```

## Layout

```
churn/
  config.py        # settings + category levels + feature contract
  data.py          # synthetic generator, schema validation, dataset fingerprint
  features.py      # RatioFeatures, CategoryFrequencyEncoder, ColumnTransformer
  train.py         # training, tuning, CV, report generation
  registry.py      # versioned artifact registry
  monitoring.py    # PSI + chi-square drift report
  schemas.py       # pydantic contracts (extra="forbid")
  service.py       # FastAPI app, load-on-startup, all endpoints
artifacts/         # registered models, reference distribution, HTML report
tests/             # 40 tests
```

## Limitations & honest next steps

- The label is synthetic: the model recovers a known logistic function, which is why AUC
  saturates around 0.82. Swap in a real warehouse extract to make the numbers meaningful.
- No temporal validation — with real data you'd hold out the most recent months, not a random split.
- No fairness audit (e.g. churn-rate parity across regions) or calibration curve; both are
  cheap to add on top of the existing report.
- Explanations are marginal, not causal. For causal uplift modelling you need experiment data.
