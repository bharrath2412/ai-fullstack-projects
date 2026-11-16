.PHONY: help test test-web test-agent test-churn test-rag test-airgrid test-billbook seed train ingest seed-billbook build-airgrid budget export up down clean

help:
	@echo "make test        - run all six test suites"
	@echo "make test-web    - TaskFlow API tests (node:test)"
	@echo "make test-agent  - AgentForge tests (pytest)"
	@echo "make test-churn  - churn service tests (pytest)"
	@echo "make test-rag    - DocMind tests + retrieval evaluation"
	@echo "make test-airgrid   - AirGrid tests (vitest) + production build + gzip budget gate"
	@echo "make test-billbook  - BillBook tests (pytest, 143) with coverage"
	@echo "make seed        - seed the TaskFlow demo account"
	@echo "make train       - train + register the churn model and build its report"
	@echo "make ingest      - build the RAG index from ./project-04-docmind-rag/corpus"
	@echo "make seed-billbook  - create the demo GST shop (demo@billbook.dev / demo12345)"
	@echo "make budget      - re-measure the AirGrid gzip payload"
	@echo "make export      - build git bundle + per-project zips in exports/"
	@echo "make push REPO=<git-url> - push/merge this repo into your own repository"
	@echo "make up / down   - docker compose for all four services"

test: test-web test-agent test-churn test-rag test-airgrid test-billbook

test-web:
	cd project-01-taskflow-fullstack/server && npm test

test-agent:
	cd project-02-agentforge-ai-agent && python -m pytest -q

test-churn:
	cd project-03-churn-ml-service && python -m pytest -q

test-rag:
	cd project-04-docmind-rag && python -m pytest -q && python -m docmind.evaluate

test-airgrid:
	cd project-05-india-open-data-dashboard && npm ci && npm test && npm run build && npm run check:budget

test-billbook:
	cd project-06-billbook-gst-saas && python -m pytest --cov=app -q

seed:
	cd project-01-taskflow-fullstack/server && npm run seed

seed-billbook:
	cd project-06-billbook-gst-saas && python -m scripts.seed

build-airgrid:
	cd project-05-india-open-data-dashboard && npm run build

budget:
	cd project-05-india-open-data-dashboard && npm run check:budget

train:
	cd project-03-churn-ml-service && python -m churn.train

ingest:
	cd project-04-docmind-rag && python -m docmind.ingest

export:
	mkdir -p exports
	git bundle create exports/portfolio-monorepo.bundle --all
	git archive --format=zip --prefix="portfolio-monorepo/" -o exports/portfolio-monorepo.zip HEAD
	for p in project-01-taskflow-fullstack project-02-agentforge-ai-agent \
	         project-03-churn-ml-service project-04-docmind-rag \
	         project-05-india-open-data-dashboard project-06-billbook-gst-saas; do \
	  git archive --format=zip --prefix="$$p/" -o "exports/$$p.zip" HEAD:"$$p"; \
	done
	@ls -lh exports

push:
	@test -n "$(REPO)" || (echo "usage: make push REPO=git@github.com:you/repo.git" && exit 1)
	./scripts/push-to-repo.sh "$(REPO)"

up:
	docker compose up --build

down:
	docker compose down -v

clean:
	rm -rf project-01-taskflow-fullstack/server/data \
	       project-01-taskflow-fullstack/client/dist \
	       project-02-agentforge-ai-agent/app/data/demo.db \
	       project-03-churn-ml-service/artifacts/models \
	       project-04-docmind-rag/data/index \
	       project-05-india-open-data-dashboard/dist \
	       project-06-billbook-gst-saas/billbook.db \
	       project-06-billbook-gst-saas/.coverage \
	       exports
