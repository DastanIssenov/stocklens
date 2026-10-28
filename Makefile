# Stock platform — common tasks. Run from the repo root.
COMPOSE      := docker compose -f infra/docker-compose.yml
TEST_COMPOSE := docker compose -f infra/docker-compose.test.yml
BACKEND      := cd backend &&
FRONTEND     := cd frontend &&

.PHONY: help up down restart logs ps migrate seed update test test-backend test-frontend lint lint-backend lint-frontend \
        fmt test-env test-env-down dev-backend dev-frontend clean

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

up:  ## build and start the whole stack (db, redis, backend, worker, beat, frontend, nginx)
	$(COMPOSE) up -d --build --wait
	@echo "Site: http://localhost:$${HTTP_PORT:-8080}   API docs: http://localhost:$${HTTP_PORT:-8080}/docs"

down:  ## stop the stack (keeps data volumes)
	$(COMPOSE) down

restart: down up  ## restart the stack

logs:  ## follow logs of all services
	$(COMPOSE) logs -f --tail=100

ps:  ## list running services
	$(COMPOSE) ps

migrate:  ## apply database migrations
	$(COMPOSE) exec backend alembic upgrade head

seed:  ## load tickers, ~2 years of prices, FX, Brent, news and demo predictions (real sources)
	$(COMPOSE) exec backend python -m app.cli seed --years 2

update:  ## one-off refresh of prices, FX and news (Celery Beat does this automatically)
	$(COMPOSE) exec backend python -m app.cli update-prices --days 10
	$(COMPOSE) exec backend python -m app.cli update-fx
	$(COMPOSE) exec backend python -m app.cli update-news

test: test-backend test-frontend  ## run all tests and checks

test-env:  ## start throw-away Postgres + Redis for backend tests
	$(TEST_COMPOSE) up -d --wait

test-env-down:
	$(TEST_COMPOSE) down -v

test-backend: test-env lint-backend  ## backend lint + type check + tests (coverage ≥ 70 %)
	$(BACKEND) uv run pytest --cov --cov-report=term --cov-fail-under=70

test-frontend: lint-frontend  ## frontend lint + type check + production build
	$(FRONTEND) npm run build

lint: lint-backend lint-frontend  ## all linters

lint-backend:
	$(BACKEND) uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy app

lint-frontend:
	$(FRONTEND) npm run lint && npm run typecheck && npm run format:check

fmt:  ## auto-format backend and frontend
	$(BACKEND) uv run ruff check --fix app tests && uv run ruff format app tests
	$(FRONTEND) npm run format

dev-backend:  ## run the API locally with reload (needs `make test-env` or your own Postgres/Redis)
	$(BACKEND) uv run uvicorn app.main:app --reload --port 8000

dev-frontend:  ## run Next.js dev server (proxies /api to localhost:8000)
	$(FRONTEND) npm run dev

clean:  ## stop the stack and DELETE its volumes (database!)
	$(COMPOSE) down -v
