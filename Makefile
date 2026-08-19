.DEFAULT_GOAL := help
COMPOSE := docker compose
PY := api/.venv/bin

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

.PHONY: test
test: ## Run the API test suite (offline — no Postgres or Ollama needed)
	cd api && .venv/bin/pytest -q

.PHONY: lint
lint: ## Lint and format-check
	cd api && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
	cd web && npm run typecheck

.PHONY: fmt
fmt: ## Auto-format
	cd api && .venv/bin/ruff format src tests && .venv/bin/ruff check --fix src tests

.PHONY: check
check: lint test ## Everything CI runs
