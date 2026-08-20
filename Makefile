.DEFAULT_GOAL := help
COMPOSE := docker compose
PY := api/.venv/bin
TEST_DATABASE_URL := postgresql+psycopg://meetingiq:meetingiq@localhost:5433/meetingiq_test

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_.-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ---- setup ----

.env: ## Create .env from the example if it does not exist
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

$(PY)/python: ## Create the API virtualenv
	python3 -m venv api/.venv
	$(PY)/pip install -q -e "api[dev]"

.PHONY: install
install: .env $(PY)/python ## Install API and web dependencies
	cd web && npm install

# ---- running ----

.PHONY: up
up: .env ## Start Postgres (the only containerised service)
	$(COMPOSE) up -d db
	@echo "postgres -> localhost:$${POSTGRES_HOST_PORT:-5433}"

.PHONY: down
down: ## Stop containers
	$(COMPOSE) --profile full down

.PHONY: dev
dev: ## Run the API and web app natively (needs `make up` and Ollama running)
	@echo "api -> http://localhost:8000/docs    web -> http://localhost:5173"
	@trap 'kill 0' EXIT; \
		$(PY)/uvicorn meetingiq.main:app --reload --app-dir api/src --port 8000 & \
		(cd web && npm run dev) & \
		wait

.PHONY: api
api: ## Run only the API natively
	$(PY)/uvicorn meetingiq.main:app --reload --app-dir api/src --port 8000

.PHONY: web
web: ## Run only the web app natively
	cd web && npm run dev

.PHONY: docker-up
docker-up: .env ## Run the whole stack in containers (verifies the deployment path)
	$(COMPOSE) --profile full up --build -d
	@echo "api -> http://localhost:$${MEETINGIQ_API_HOST_PORT:-8000}/docs"

.PHONY: clean
clean: ## Stop everything and delete the database volume
	$(COMPOSE) --profile full down -v

.PHONY: logs
logs: ## Tail container logs
	$(COMPOSE) --profile full logs -f

.PHONY: health
health: ## Print the health report
	@curl -s localhost:$${MEETINGIQ_API_HOST_PORT:-8000}/health | python3 -m json.tool

# ---- quality ----

.PHONY: seed
seed: ## Ingest the seed corpus (needs `make up` and Ollama)
	cd api && .venv/bin/alembic upgrade head
	cd api && .venv/bin/python -m meetingiq.ingest.cli ../seed/transcripts

.PHONY: brief
brief: ## Extract briefs for every meeting (~35s each; otherwise lazy on first view)
	cd api && .venv/bin/python -m meetingiq.extraction.cli

.PHONY: migrate
migrate: ## Apply database migrations
	cd api && .venv/bin/alembic upgrade head

.PHONY: test
test: ## Run unit tests (offline — no Postgres or Ollama needed)
	cd api && .venv/bin/pytest -q
	cd web && npm test

.PHONY: test-all
test-all: testdb ## Run unit and integration tests (needs `make up`)
	cd api && MEETINGIQ_TEST_DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/pytest -q
	cd web && npm test

.PHONY: testdb
testdb: ## Create the integration-test database if it does not exist
	@$(COMPOSE) exec -T db psql -U $${POSTGRES_USER:-meetingiq} -d postgres \
		-tc "SELECT 1 FROM pg_database WHERE datname='meetingiq_test'" | grep -q 1 \
		|| $(COMPOSE) exec -T db psql -U $${POSTGRES_USER:-meetingiq} -d postgres \
		-c 'CREATE DATABASE meetingiq_test'

.PHONY: eval
eval: ## Run the evaluation golden set against the real model (a few minutes)
	cd api && PYTHONPATH=src .venv/bin/python evals/run_eval.py

.PHONY: lint
lint: ## Lint and format-check
	cd api && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
	cd web && npm run typecheck

.PHONY: fmt
fmt: ## Auto-format
	cd api && .venv/bin/ruff format src tests && .venv/bin/ruff check --fix src tests

.PHONY: check
check: lint test-all ## Everything CI runs
