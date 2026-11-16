.PHONY: help install train serve test clean

help:
	@echo "make install   - create venv + install dev deps"
	@echo "make train     - train, register and report (full dataset)"
	@echo "make serve     - run the API on :8100"
	@echo "make test      - run the test suite"
	@echo "make clean     - remove artifacts (models, report, reference)"

install:
	python -m pip install -r requirements-dev.txt

train:
	python -m churn.train

quicktrain:
	python -m churn.train --samples 1500 --cv 0 --fast

serve:
	uvicorn churn.service:app --host 0.0.0.0 --port 8100 --reload

test:
	python -m pytest

clean:
	rm -rf artifacts/models artifacts/model_report.html artifacts/reference.csv data/churn.csv
