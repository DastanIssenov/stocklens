# Task for Claude Code: Stock Prediction Platform (US + Kazakhstan)

## Scope of THIS run

This machine has **no GPU**. In this run you:

1. **Research and design** the whole system (Phase 0).
2. **Build the website** end to end with seed data and mock predictions (Phase 1).
3. **Write a precise plan** for everything that will happen once we get the GPU (Phase 2).

Do **not** train ML models, download large LLMs or build the full data pipeline in this run, unless you reach "If there is time left".

The GPU we will get later: **one NVIDIA RTX 5090 (32 GB VRAM, Blackwell architecture)**.

---

## 0. How you work (read first)

You work **autonomously for a long time** while I am away. Rules:

1. **Do not ask questions or wait for answers.** If something is unclear, make a reasonable decision, write it to `docs/DECISIONS.md` (what you decided, why, what the alternatives were), and keep going.
2. **Keep `docs/PROGRESS.md` up to date.** After each task, write what was done, what was verified, what is left, and any problems. This is the first file I will read when I come back.
3. **Work through the phases in order.** A phase is finished only when all its Definition of Done criteria are met.
4. **Git:** initialise a repo, make small commits after each finished task with clear messages. Do not push anywhere without me.
5. **Tests are mandatory.** Run linters and tests before every commit. Never commit broken code.
6. **If something blocks you** (missing API key, site unavailable, library will not install): do not stop. Build a stub/mock, write the problem to `docs/BLOCKERS.md`, and move on. Come back to blockers at the end.
7. **Secrets only via `.env`.** API keys are already in `.env` with these names: `ALPACA_KEY`, `ALPACA_SECRET`, `ALPACA_ENDPOINT`, `FINNHUB_KEY`, `FRED_KEY`, `SEC_USER_AGENT`. Add `.env` to `.gitignore` first. Create `.env.example` with all variables. Never commit, print or log key values.
8. **Data:** use legal sources only. Respect `robots.txt`, terms of service and rate limits (SEC EDGAR: max ~10 requests/second). Prefer official APIs and RSS over HTML scraping.
9. **Verify facts yourself.** Check tickers, APIs, library versions and data formats against documentation and real requests, not memory.

---

## 1. Project goal (the full system, not just this run)

Bachelor capstone (team project). A web platform that:

- shows quotes and charts for **US** and **Kazakhstan** stocks;
- gives **short-term** (1–5 trading days) and **long-term** (1–12 months) predictions;
- uses an ensemble of **LightGBM + XGBoost + an LLM** that reads news (EN / RU / KZ);
- has a **paper-trading sandbox**: users "buy" and "sell" with virtual money, and an **AI reviewer** comments on every trade (is it reasonable, and why);
- shows a disclaimer everywhere: *educational project, not investment advice*.

---

## 2. Stack

| Layer | Technologies |
|---|---|
| Backend | Python 3.12, **FastAPI**, Pydantic v2, SQLAlchemy 2.0 (async), Alembic |
| Database | **PostgreSQL 16 + TimescaleDB** (price time series), pgvector (news embeddings) |
| Cache / queues | **Redis**: caching, rate limiting, pub/sub for live prices, task broker |
| Background jobs | **Celery + Celery Beat** (or ARQ if you decide it is simpler; record the decision) |
| Frontend | **Next.js (App Router) + TypeScript + Tailwind**, TradingView **lightweight-charts**, TanStack Query |
| Auth | JWT (access + refresh), argon2 password hashing |
| Infrastructure | **Docker Compose**, Nginx (reverse proxy), GitHub Actions (CI) |
| Quality | ruff, mypy, pytest, pytest-asyncio; eslint, prettier on the frontend |
| Later (GPU phase) | LightGBM, XGBoost, PyTorch, transformers, peft, bitsandbytes, vLLM, MLflow |

---

## 3. Repository structure

```
stock-platform/
├── backend/
│   ├── app/
│   │   ├── api/            # routers: auth, tickers, prices, news, predictions, portfolio, trades
│   │   ├── core/           # config, security, logging
│   │   ├── db/             # models, sessions, migrations
│   │   ├── services/       # business logic
│   │   ├── workers/        # celery tasks
│   │   ├── ml_interface/   # PredictionProvider + TradeReviewer interfaces, mock implementations
│   │   └── main.py
│   └── tests/
├── frontend/               # Next.js
├── data_pipeline/          # empty skeleton with README (built in the GPU phase)
├── ml/                     # empty skeleton with README (built in the GPU phase)
├── infra/                  # docker-compose, nginx
├── docs/                   # ARCHITECTURE, DECISIONS, PROGRESS, BLOCKERS, DATA_SOURCES, GPU_PLAN
├── .env.example
├── Makefile
└── README.md
```

---

## 4. Phases

### Phase 0. Research and architecture (documents only)

**Tasks:**
1. **`docs/DATA_SOURCES.md`.** Find and verify data sources with **small real test requests** (a few calls each, not bulk downloads):
   - **US prices:** Alpaca (main), yfinance (backup and cross-check). Compare limits, history depth, reliability.
   - **US fundamentals:** SEC EDGAR (XBRL companyfacts API, free, uses `SEC_USER_AGENT`).
   - **Macro:** FRED API (rates, inflation, VIX).
   - **US news:** Alpaca news API, Finnhub, RSS from major outlets, GDELT. Check limits.
   - **Kazakhstan prices:** research how to get data for **KASE** stocks (official KASE data, broker APIs such as Freedom/Tradernet) and **AIX**. Also find Kazakh companies listed abroad (e.g. Kaspi.kz on NASDAQ, Kazatomprom and Halyk on LSE); verify tickers yourself.
   - **Kazakhstan news (RU/KZ):** RSS from business outlets (Kursiv, Kapital.kz, Forbes Kazakhstan, Inbusiness, etc.), company press releases, KASE disclosures. Check RSS availability and terms of use.
   - **Tenge and oil:** USD/KZT and Brent.
   For each source: what it provides, history depth, limits, licence, how to connect, an example request that worked.
2. **Ticker universe:** US (start with NASDAQ-100 or the 100 most liquid stocks, design for the S&P 500); KZ (liquid KASE blue chips + Kazakh stocks listed abroad). Note the survivorship-bias problem and how we will handle it.
3. **`docs/ARCHITECTURE.md`:** service diagram (Mermaid), data flows, DB schema (ER diagram), API contract (list of endpoints), and how the ML part will plug into the website later.

**Done when:** both documents are written, sources are verified with real test requests, decisions are recorded in `DECISIONS.md`.

---

### Phase 1. The website (main work of this run)

**Backend:**
1. FastAPI app with pydantic-settings config, structured logs (structlog), `/health` endpoint.
2. DB models and Alembic migrations:
   - `users`, `tickers` (exchange: NASDAQ/NYSE/KASE/AIX/LSE, currency, sector, country),
   - `prices_daily` (TimescaleDB hypertable),
   - `news` (source, lang, published_at, title, body, url, sentiment nullable, embedding vector nullable) + `news_tickers` (many-to-many),
   - `fundamentals` (point-in-time: report publication date),
   - `predictions` (model_version, horizon, ticker, as_of_date, predicted_return, prob_up, confidence, top_features JSON),
   - `portfolios`, `positions`, `trades`, `trade_reviews`.
3. Endpoints: auth (register / login / refresh), tickers and search, price history, news per ticker, predictions, portfolio, trades, trade review.
4. **Redis:** cache for prices and predictions (TTL), API rate limiting, pub/sub + **WebSocket** `/ws/prices`.
5. Celery + Beat: working periodic tasks for **small real updates** (latest daily prices for the ticker universe via Alpaca/yfinance, latest news via Finnhub/RSS), so the site shows real recent data.
6. Paper trading: starting virtual balance, buy/sell at the latest price, fees, USD and KZT, P&L, history.
7. **ML interface with mocks** (`app/ml_interface/`):
   - `PredictionProvider` interface + `MockPredictionProvider` (deterministic fake predictions, clearly labelled "demo" in the UI).
   - `TradeReviewer` interface + `MockTradeReviewer` (rule-based review: concentration, volatility, recent price move) + `OpenAICompatibleTradeReviewer` that calls any OpenAI-compatible endpoint from `.env` (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`); used only if those variables are set.
   - Review output in strict JSON validated with Pydantic: `verdict` (reasonable / risky / poor), `score` 1–10, `reasons` (3–5), `risks`, `what_to_watch`.
   - Switching from mock to real models later must only need a config change.
8. Tests: unit + integration (testcontainers or a separate docker-compose for tests). Backend coverage ≥ 70%.

**Frontend (Next.js):**
1. Pages: home (US / KZ market overview), ticker page (candlestick chart, volume, news, predictions with confidence), portfolio, trading, trade history with AI reviews, "How the models work" (placeholder text for now), login / register.
2. US / KZ market switch, currency display, RU / EN interface language (KZ if time allows).
3. "Not investment advice" disclaimer on every page with predictions; "demo predictions" badge while mocks are used.
4. Clean, responsive design (works on a phone).

**Infra:** `docker-compose.yml` (postgres+timescale, redis, backend, worker, beat, frontend, nginx), `Makefile` (`make up`, `make test`, `make migrate`, `make seed`), GitHub Actions CI (lint + tests).

**Seed data:** `make seed` loads about 1–2 years of daily prices for ~20 US and all available KZ tickers, plus recent news, so the site is usable right away.

**Done when:** `make up` + `make seed` bring everything up from scratch; you can register, browse US and KZ tickers with real recent data, see charts and news, make a paper trade, and get a mock review. All tests pass, CI is green.

---

### Phase 2. GPU plan (`docs/GPU_PLAN.md`)

Write a **precise, step-by-step plan** for the day we get the RTX 5090, so we can start immediately. It must include:

1. **Environment setup:** exact versions (Python, CUDA 12.8+ for Blackwell, PyTorch, transformers, peft, bitsandbytes, vLLM, flash-attention). Check current compatibility with the RTX 5090 in official docs and issues, and note known problems and workarounds. Include a verification script (`nvidia-smi`, `torch.cuda.is_available()`, a small bf16 matmul test).
2. **Data pipeline plan:** each connector, the order of building them, historical load size (US ≥ 10 years daily, KZ as deep as available), daily updates, cleaning rules (splits, dividends, gaps, KZ illiquidity), news-to-ticker linking (RU/KZ/EN aliases), **look-ahead-bias rules** (after-close news → next trading day; fundamentals from publication date), estimated disk space and download time.
3. **Features:** full list (technical, market, macro incl. USD/KZT and Brent, news sentiment, fundamentals) with how each is computed, all from one shared module for training and inference.
4. **Models:**
   - Short-term (1–5 days): LightGBM + XGBoost, targets (return and direction), baselines ("tomorrow = today", logistic regression), walk-forward validation with purging/embargo.
   - Long-term (1–12 months): ranking (LightGBM LambdaRank / XGBoost rank), monthly rebalancing.
   - LLM: FinBERT + multilingual baseline; main model a 7–8B instruct model with good Russian support (compare current candidates, e.g. Qwen family), QLoRA fine-tuning for ticker-level sentiment and weekly summaries; training data sources with licences; strict JSON output.
   - Ensemble: stacking on out-of-fold predictions.
   - Kazakhstan: separate settings (longer horizons, illiquidity), KZ-only vs transfer from US.
5. **VRAM and time budget for the 5090:** for each job (QLoRA fine-tuning, batch sentiment over all news with vLLM, serving the trade reviewer, GBM training on GPU) give model size, quantisation, batch size, sequence length, estimated VRAM use and estimated run time. Note what can run at the same time.
6. **Backtest and metrics:** strategy rules, fees and slippage, benchmarks (buy-and-hold, index); metrics: AUC, RMSE, Information Coefficient, Sharpe, Sortino, max drawdown, turnover, hit rate.
7. **MLflow:** experiment tracking, model registry, how the website picks the `production` model.
8. **Integration:** how the real `PredictionProvider` and `TradeReviewer` replace the mocks (only config changes), nightly inference task.
9. **Order of work and checklist:** a numbered day-by-day (or step-by-step) list with a "done when" for each step, and the main risks with fallbacks (e.g. if bitsandbytes does not work on Blackwell; if KASE data is unavailable).
10. **Cloud fallback:** if we need to start before we have the GPU, which cloud GPU options fit this plan and their rough hourly price (check current prices).

**Done when:** `GPU_PLAN.md` is complete enough that someone can follow it step by step without asking questions.

---

## 5. If there is time left (CPU only)

In this order:
1. Build the **data pipeline** for real (connectors, historical load, daily updates, cleaning, data quality report `docs/DATA_REPORT.md`). It does not need a GPU.
2. Write the **shared feature module** and train **LightGBM / XGBoost baselines on CPU** for the short-term model, with walk-forward validation and MLflow logging. Plug the best one into the website through `PredictionProvider`.
3. Write the ML training code skeleton (`python -m ml.train --config ...`, YAML configs) with a `--dry-run` mode that runs on CPU with tiny data, so it is ready for the GPU.

## 6. Do NOT

- Download large models or datasets (> 2 GB) in this run.
- Use a random train/test split on time series.
- Peek into the future (features only from data available on the prediction date).
- Scrape sites that forbid it or bypass access restrictions.
- Promise returns in the UI or call predictions advice.
- Stop to ask questions: decide, record, move on.
