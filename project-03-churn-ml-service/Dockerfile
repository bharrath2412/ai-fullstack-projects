FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libgomp is needed by scikit-learn's OpenMP-backed estimators
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY churn ./churn
COPY tests ./tests

# Train and register a model at build time so the image starts serving immediately.
RUN python -m churn.train --cv 3

RUN useradd --create-home --shell /bin/bash churn && chown -R churn:churn /app
USER churn

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health').status==200 else 1)"

CMD ["uvicorn", "churn.service:app", "--host", "0.0.0.0", "--port", "8100"]
