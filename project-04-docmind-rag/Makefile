.PHONY: help install ingest serve eval test clean

help:
	@echo "make install - install dev dependencies"
	@echo "make ingest  - chunk + embed ./corpus into ./data/index"
	@echo "make serve   - run the API/UI on :8200"
	@echo "make eval    - golden-set evaluation (fails below the gate)"
	@echo "make test    - full test suite"
	@echo "make clean   - remove the built index"

install:
	python -m pip install -r requirements-dev.txt

ingest:
	python -m docmind.ingest

serve:
	uvicorn docmind.service:app --host 0.0.0.0 --port 8200 --reload

eval:
	python -m docmind.evaluate

test:
	python -m pytest

clean:
	rm -rf data/index
