.PHONY: help test test-web test-agent test-churn test-rag seed train ingest up down clean

help:
	@echo "make test        - run all four test suites"
	@echo "make test-web    - TaskFlow API tests (node:test)"
	@echo "make test-agent  - AgentForge tests (pytest)"
	@echo "make test-churn  - churn service tests (pytest)"
	@echo "make test-rag    - DocMind tests + retrieval evaluation"
	@echo "make seed        - seed the TaskFlow demo account"
	@echo "make train       - train + register the churn model and build its report"
	@echo "make ingest      - build the RAG index from ./project-04-docmind-rag/corpus"
	@echo "make up / down   - docker compose for all four services"

test: test-web test-agent test-churn test-rag

test-web:
	cd project-01-taskflow-fullstack/server && npm test

test-agent:
	cd project-02-agentforge-ai-agent && python -m pytest -q

test-churn:
	cd project-03-churn-ml-service && python -m pytest -q

test-rag:
	cd project-04-docmind-rag && python -m pytest -q && python -m docmind.evaluate

seed:
	cd project-01-taskflow-fullstack/server && npm run seed

train:
	cd project-03-churn-ml-service && python -m churn.train

ingest:
	cd project-04-docmind-rag && python -m docmind.ingest

up:
	docker compose up --build

down:
	docker compose down -v

clean:
	rm -rf project-01-taskflow-fullstack/server/data \
	       project-01-taskflow-fullstack/client/dist \
	       project-02-agentforge-ai-agent/app/data/demo.db \
	       project-03-churn-ml-service/artifacts/models \
	       project-04-docmind-rag/data/index
