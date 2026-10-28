# Progress

**Read this first.** Updated after every finished task. Newest log entries at the bottom of the log.

## Where things stand (end of the autonomous run, 2026-10-28)
- **Phase 0, 1, 2: done.** All extras from TASK §5 done as well (pipeline, CPU baselines, `ml.train --dry-run`).
- **Run it:** `make up && make seed` → <http://localhost:8080> (API docs at `/docs`). `make test` runs every check.
- **Predictions on the site:** 5-day horizon from the CPU LightGBM baseline (`lgbm-cpu-93314193`, run `uv run python -m ml.serving.batch_predict --database-url postgresql://stock:stock@localhost:55433/stock` after `make seed`); other horizons are mock. The "Demo predictions" badge stays on because the model failed the promotion rule (docs/BACKTEST_REPORT.md).
- **Needs you:** push to GitHub to get the first CI run (BLOCKERS #5); decide on KASE data licensing before any public launch (BLOCKERS #2); optional `LLM_*` variables to switch the trade reviewer to a real LLM.
- **Key docs:** DECISIONS (D-001…D-031), DATA_SOURCES, ARCHITECTURE, GPU_PLAN, DATA_REPORT, BACKTEST_REPORT, BLOCKERS.

## Phase checklist

### Phase 0 — Research and architecture
- [x] 0.1 Repo initialised, `.env` git-ignored (the old `.gitignore` was a directory holding `.env` — fixed, see D-002)
- [x] 0.2 Data sources verified with real requests → `docs/DATA_SOURCES.md`
- [x] 0.3 Ticker universe + survivorship-bias handling → `docs/DATA_SOURCES.md` §8
- [x] 0.4 Architecture (services, flows, ER diagram, API contract, ML plug-in) → `docs/ARCHITECTURE.md`
- [x] 0.5 Decisions recorded → `docs/DECISIONS.md` (D-001…D-018)

### Phase 1 — Website
- [x] 1.1 Backend skeleton: config, structlog, `/health`, tooling (ruff, mypy, pytest)
- [x] 1.2 DB models + Alembic migrations (Timescale hypertable, pgvector)
- [x] 1.3 Auth (register / login / refresh, argon2, JWT)
- [x] 1.4 Tickers, prices, news, FX, market overview endpoints + Redis cache + rate limiting
- [x] 1.5 ML interface: mock prediction provider, mock + OpenAI-compatible trade reviewer
- [x] 1.6 Paper trading (USD/KZT cash, fees, P&L, history) + trade reviews
- [x] 1.7 Data connectors (Alpaca, Tradernet, yfinance, Finnhub, RSS, NBK) + Celery/Beat tasks + seed command
- [x] 1.8 WebSocket `/ws/prices` via Redis pub/sub
- [x] 1.9 Backend tests ≥ 70 % coverage
- [x] 1.10 Frontend: Next.js pages, charts, i18n (EN/RU/KK), disclaimer, demo badge, responsive
- [x] 1.11 Infra: docker-compose (db, redis, backend, worker, beat, frontend, nginx), Makefile, GitHub Actions CI
- [x] 1.12 End-to-end check: `make up` + `make seed` from scratch, register, browse, trade, review

### Phase 2 — GPU plan
- [x] 2.1 `docs/GPU_PLAN.md` complete (environment, pipeline, features, models, VRAM budget, backtest, MLflow, integration, checklist, cloud fallback)

### Extra (if time left)
- [x] E.1 Data pipeline for real
- [x] E.2 Shared feature module + CPU LightGBM/XGBoost baselines
- [x] E.3 `python -m ml.train --config ... --dry-run`

## Log

### 2026-10-28 — Phase 0 done
- **Done:** fixed `.gitignore`/`.env` layout, created repo and folder skeleton; probed every data source with a few real requests (scripts in `scripts/research/`); wrote `DATA_SOURCES.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `BLOCKERS.md`.
- **Verified:** Alpaca bars (SIP from 2016-01-04, IEX from 2020-07-27, 200 req/min), Alpaca news (since 2015), Finnhub (60 req/min, news ~1 year, candles are premium), SEC companyfacts/submissions/frames, FRED series (no KZT series exists), yfinance (US + LSE GDRs + KZT=X + BZ=F), Tradernet getHloc for all 10 KASE Index shares (no auth), NBK official USD/KZT XML, 7 US + 7 KZ RSS feeds, GDELT.
- **Key findings:** KASE data is free only through the broker API (licence question → BLOCKERS #2); AIX has no free data (BLOCKERS #3); Tradernet bars are `[high, low, open, close]` with Moscow-midnight timestamps (corrected later the same day).
- **Left:** Phase 1 and 2.

### 2026-10-28 — Backend core (commit `228f021`)
- **Done:** FastAPI app (config, structlog, `/health`), SQLAlchemy models + Alembic migration `0001` (Timescale hypertable `prices_daily`, pgvector `news.embedding vector(1024)`), JWT auth with argon2id, tickers/search, prices + latest quote, market overview, FX, news (vendor tags + RU/KK/EN alias linking, issuer-level sharing), predictions (mock provider, stored per as-of date), paper trading (USD/KZT cash, per-exchange fees, average cost, realised P&L), trade reviews (mock rule-based + OpenAI-compatible LLM with strict JSON + fallback), Redis cache + fixed-window rate limits, WebSocket hub.
- **Verified:** `alembic upgrade/downgrade` round-trip and `alembic check` (models == migration); ruff + mypy clean; 40 tests pass against real Timescale + Redis containers (`infra/docker-compose.test.yml`), coverage 92 %.
- **Left:** data connectors + Celery/Beat + seed; WebSocket tests; frontend; infra; GPU plan.

### 2026-10-28 — Data connectors, Celery, seed (commit `deee196`)
- **Done:** connectors for Alpaca (bars/snapshots/news), Tradernet (KASE), yfinance (LSE GDRs, KZT=X, Brent), Finnhub news, RSS (US + KZ ru/kk), NBK official rate; idempotent ingest service; live quotes → Redis + pub/sub → WebSocket; Celery app + Beat schedule; `python -m app.cli seed|universe|update-prices|update-news|update-fx|predict|quotes`.
- **Verified with real sources** (dev DB): seed loaded 39 listings, 12.5 k US/LSE price rows + 7.5 k KASE rows (2 years), 7 NBK rates, 518 KZT=X and 504 Brent rows, 755 news items, demo predictions for every ticker with prices. Tests: 68 pass, coverage 95 %.
- **Problems found & fixed:** Tradernet 403 for UAs containing a URL (D-019); Tradernet timestamps are Moscow midnight (fixed in DATA_SOURCES); `FOR UPDATE` on an outer join (locked only `positions`).
- **Left:** frontend, Docker/infra/CI, end-to-end check, GPU plan.

### 2026-10-28 — Frontend (commit `45232ab`)
- **Done:** Next.js 16 app: market overview (US/KZ switch, FX, Brent, movers, sparkline table, news), ticker page (candlestick + volume chart with ranges, live price over WebSocket, demo predictions for 1d/5d/1m/3m/6m/12m with P(up)/confidence/top factors, news, trade form, other listings), trade page, portfolio (USD/KZT view), trade history with expandable AI reviews and re-run, "How the models work", login/register. EN/RU/KK UI. Disclaimer on every page with predictions/reviews; "Demo predictions" badge.
- **Verified in the browser:** all pages with real seeded data, register → buy 300 KZAP.KZ → rule-based review (Reasonable 8/10) → portfolio math (fee in cost basis, P&L at NBK rate) → history; RU locale; 375 px phone layout without horizontal scroll. eslint, tsc, prettier, `next build` clean.

### 2026-10-28 — Infra + end-to-end (commit `ba43cda`)
- **Done:** Dockerfiles (backend uv-based, frontend standalone), `infra/docker-compose.yml` (db, redis, backend, worker, beat, frontend, nginx), nginx single origin incl. WebSocket, `Makefile`, GitHub Actions CI, `.env.example`, root README, `data_pipeline/` and `ml/` skeletons.
- **Verified from scratch:** `make up` → all 7 containers healthy in ~3 min; `make seed` → 39 listings, 19 427 daily bars, 7 NBK rates, 518 KZT=X, 504 Brent, 770 news, demo predictions for 39 tickers, **0 errors**, 29 s. Through nginx: `/health`, all pages 200, register → trade (20 000 HSBK.KZ) → Russian-language review, portfolio; WebSocket push via nginx; every Celery task executed inside the worker (prices, FX/Brent, news, predictions, 22 live US quotes). `make test`: 70 backend tests (coverage 95.5 %) + frontend checks pass.
- **Not verified:** GitHub Actions itself (repo is not pushed — TASK §0.4 says do not push). The CI steps were run locally with the same commands. See BLOCKERS #5.

**Phase 1 Definition of Done: met** (except the remote CI run, which needs a push).

### 2026-10-28 — Phase 2: GPU plan
- **Done:** `docs/GPU_PLAN.md` (environment with exact pins, data pipeline with sizes/times and look-ahead rules, feature list, models incl. LLM candidates and training data with licences, VRAM/time budget, backtest and metrics, MLflow registry flow, website integration by config, 10-day checklist with "done when", risks/fallbacks, cloud prices). Added `scripts/gpu/verify_env.py` (nvidia-smi, torch CUDA + sm_120 kernels, bf16 matmul, SDPA, bitsandbytes NF4, XGBoost/LightGBM GPU, vLLM import), `scripts/gpu/setup_train_env.sh`, `scripts/gpu/setup_vllm.sh`.
- **Verified facts (2026-10-28):** torch 2.13.0/2.14.1 default wheels are CUDA 13.0; vLLM 0.32.0 pins torch 2.13.0 and transformers <5.20; `vllm/vllm-openai:v0.32.0` exists (9.2 GB); vLLM sm_120 wheel issue closed 2026-05-15; NVFP4 on sm_120 still problematic → bf16/AWQ; flash-attn only as sdist → SDPA default; model IDs/licences on Hugging Face (Qwen3-8B Apache-2.0 default; Qwen3.5-9B is a new hybrid-attention VL model; Sherkala/KazLLM non-commercial, gated); dataset licences; cloud 5090 ≈ $0.4–1.2/h; Alpaca corporate-actions endpoint works.
- **Not verified (no GPU):** actual throughput/VRAM numbers in §5 are estimates — the plan says to measure them on day 1–2.

**Phase 2 Definition of Done: met.**

### 2026-10-28 — Extras (TASK §5): data pipeline, CPU baselines, training skeleton (commits `d9114fc`, `fdfe3fa` + this one)
- **E.1 Data pipeline** (`data_pipeline/`, `python -m data_pipeline universe|backfill|daily|report`): polite HTTP with per-source rate limits and retries, Parquet lake with idempotent upserts and a manifest. Loaded: top-100 liquid US universe (Alpaca + SEC, D-028), **340 683 US bars 2010→2026** (Alpaca SIP raw + adjusted from 2016, Yahoo before), 2 466 corporate actions, **41 898 KZ bars** (KASE back to 2004 + LSE GDRs), 37 895 market rows (SPY, QQQ, ^GSPC, ^NDX, ^VIX, KZT=X, BZ=F), 41 841 FRED rows (first-release vintages for CPI/unemployment), 666 NBK official rates (2025→), 141 335 SEC facts for 98 companies with acceptance timestamps. Lake size 14 MB. `docs/DATA_REPORT.md` generated (coverage, split-explained jumps, gaps, KZ liquidity, publication lags).
- **E.2 Features + baselines** (`ml/`): one feature module (44 features, macro joined on publication date), walk-forward with purge + embargo, persistence/momentum/logreg/LightGBM/XGBoost, metrics (AUC, IC, hit rate, Sharpe, Sortino, max DD, turnover), MLflow (`mlruns/mlflow.db`). Results in `docs/BACKTEST_REPORT.md`: LightGBM OOS AUC 0.516, IC 0.013 (t 2.8) — beats the baselines on IC but its strategy Sharpe (0.92) is below the equal-weight benchmark (1.36) → not promoted (D-030). Plugged into the website through batch inference (`ml/serving/batch_predict.py`) → 22 tickers show `lgbm-cpu-93314193` 5-day predictions with SHAP factors.
- **E.3** `python -m ml.train --config ml/configs/short_gbm.yaml --dry-run` runs on synthetic data in ≈ 12 s. Research tests: 9 pass (incl. the no-look-ahead test).
- **Problems found & fixed:** httpx logged full URLs (FRED key is a query parameter) → silenced; FRED vintage mode returned no data for daily series → vintages only for revised series; NBK connection error stopped the backfill → per-day error handling; fundamentals O(n²) rewrites hit the time limit → batched + resumable; port 5433 already in use on this Mac → Postgres mapped to 127.0.0.1:55433 (site was briefly down, restored and re-verified); LightGBM needs `brew install libomp` on macOS (installed).
