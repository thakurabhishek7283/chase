# Convenience wrappers. Every target is a plain command you can also run by
# hand (the README lists them), so nothing here is required — on Windows
# without `make`, copy the command from the recipe.

COMPOSE      := docker compose
COMPOSE_DEV  := docker compose -f docker-compose.yml -f docker-compose.dev.yml

.DEFAULT_GOAL := help
.PHONY: help up pull down logs ps admin dev-infra backend-dev frontend-dev \
        install lint format test test-backend test-frontend build check clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\n"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# --- Run the whole stack in Docker ------------------------------------------

up: ## Build and start everything at http://localhost:8080
	$(COMPOSE) up -d --build
	@printf "\n  App:      http://localhost:%s\n  API docs: http://localhost:%s/docs\n\n" "$${APP_PORT:-8080}" "$${APP_PORT:-8080}"

pull: ## Start from the published images instead of building
	$(COMPOSE) pull
	$(COMPOSE) up -d

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow logs from every service
	$(COMPOSE) logs -f

ps: ## Show service status and health
	$(COMPOSE) ps

admin: ## Promote an account to admin: make admin EMAIL=you@example.com
	@test -n "$(EMAIL)" || (echo "usage: make admin EMAIL=you@example.com" && exit 1)
	$(COMPOSE) exec backend python -m app.cli promote-admin $(EMAIL)

# --- Native development (reload on save) ------------------------------------

dev-infra: ## Start Postgres + LaTeX worker on localhost for native dev
	$(COMPOSE_DEV) up -d postgres latex-worker
	$(COMPOSE_DEV) exec postgres sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB -tc "SELECT 1 FROM pg_database WHERE datname = '"'"'jarvis_test'"'"'" | grep -q 1 || psql -U $$POSTGRES_USER -d $$POSTGRES_DB -c "CREATE DATABASE jarvis_test"'

backend-dev: ## Run the API natively with reload (needs dev-infra)
	cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --reload

frontend-dev: ## Run the Angular dev server (proxies /api to :8000)
	cd frontend && npm start

# --- Quality gates (the same checks CI runs) ---------------------------------

install: ## Install backend and frontend dependencies
	cd backend && uv sync --extra local-embeddings
	cd frontend && npm ci

lint: ## Lint and check formatting
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run format:check

format: ## Auto-format backend and frontend
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format

test-backend: ## Backend tests (needs dev-infra)
	cd backend && uv run pytest

test-frontend: ## Frontend unit tests
	cd frontend && npm run test:ci

test: test-backend test-frontend ## All tests

build: ## Production frontend bundle
	cd frontend && npm run build

check: lint test build ## Everything CI checks

clean: ## Remove local build output and caches
	rm -rf frontend/dist frontend/.angular backend/.pytest_cache backend/.ruff_cache backend/.coverage backend/htmlcov
