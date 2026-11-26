# StockLens — stock prediction platform (US + Kazakhstan)

Bachelor capstone. A web platform with quotes and charts for **US** and **Kazakhstan** stocks, short- and long-term
predictions, and a **paper-trading sandbox** where an **AI reviewer** comments on every trade.

> ⚠️ **Educational project — not investment advice.** All trading uses virtual money. Predictions are **demo
> placeholders** until the models are trained (see [`docs/GPU_PLAN.md`](docs/GPU_PLAN.md)).

## Quick start

Requirements: Docker Desktop (≈4 GB RAM for Docker), GNU make. Optional for local dev: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 22+.

```bash
cp .env.example .env      # add ALPACA_KEY/SECRET, FINNHUB_KEY, FRED_KEY, SEC_USER_AGENT (all optional)
make up                   # builds and starts db, redis, backend, worker, beat, frontend, nginx
make seed                 # tickers + ~2 years of daily prices + FX + Brent + news + demo predictions (~30 s)
open http://localhost:8080
```

API docs (OpenAPI): <http://localhost:8080/docs>. Other targets: `make help`.

## What is inside

| Part | Tech | Where |
|---|---|---|
| API | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, structlog | `backend/app` |
| DB | PostgreSQL 16 + TimescaleDB (`prices_daily` hypertable) + pgvector (`news.embedding`) | `backend/app/db` |
| Jobs | Celery + Beat on Redis: daily bars, live US quotes, FX/Brent, news, predictions | `backend/app/workers` |
| Data | Alpaca, Tradernet (KASE), yfinance, Finnhub, RSS (EN/RU/KK), National Bank of KZ | `backend/app/services/sources` |
| ML interface | `PredictionProvider`, `TradeReviewer` + mocks + OpenAI-compatible LLM reviewer | `backend/app/ml_interface` |
| Web | Next.js 16 (App Router), TypeScript, Tailwind 4, lightweight-charts, TanStack Query; EN/RU/KK | `frontend` |
| Infra | Docker Compose, nginx, GitHub Actions | `infra`, `.github` |
| GPU phase | data pipeline + models (planned) | `data_pipeline`, `ml`, `docs/GPU_PLAN.md` |

Switching from mock models to real ones is a configuration change: `PREDICTION_PROVIDER=mlflow`,
`TRADE_REVIEWER=llm` + `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL` (any OpenAI-compatible endpoint, e.g. vLLM).

## Development

```bash
make test          # backend: ruff, mypy, pytest (Postgres+Redis test containers, coverage ≥ 70 %); frontend: eslint, tsc, prettier, build
make test-env      # only start the test containers (ports 55432 / 56379)
make dev-backend   # uvicorn --reload on :8000 (set DATABASE_URL / REDIS_URL)
make dev-frontend  # next dev on :3000, proxies /api to :8000
```

## Research workspace (data pipeline + models, CPU)

```bash
uv sync                                                   # root pyproject: data_pipeline/ + ml/ (macOS: brew install libomp)
uv run python -m data_pipeline universe                   # top-100 liquid US companies (Alpaca + SEC)
uv run python -m data_pipeline backfill --start 2016-01-01 --yahoo-before 2010-01-01   # Parquet lake in data/lake
uv run python -m data_pipeline report                     # → docs/DATA_REPORT.md
uv run python -m ml.train --config ml/configs/short_gbm.yaml --dry-run   # synthetic data, < 30 s
uv run python -m ml.train --config ml/configs/short_gbm.yaml             # walk-forward, MLflow in mlruns/
uv run python -m ml.serving.batch_predict --database-url postgresql://stock:stock@localhost:55433/stock
uv run pytest                                             # pipeline + ML tests (incl. no-look-ahead test)
```

## Documentation

- [`docs/PROGRESS.md`](docs/PROGRESS.md) — what is done, verified, left
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — services, data flows, DB schema, API contract
- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) — every data source, verified with real requests
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisions and alternatives
- [`docs/BLOCKERS.md`](docs/BLOCKERS.md) — open problems
- [`docs/GPU_PLAN.md`](docs/GPU_PLAN.md) — step-by-step plan for the RTX 5090

## Data and licences

Headlines are shown with a link to the publisher; full articles are not republished. KASE prices come from the public
Tradernet API for this non-commercial prototype — see BLOCKERS #2 before any public launch.
