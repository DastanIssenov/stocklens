# Progress

**Read this first.** Updated after every finished task. Newest log entries at the bottom of the log.

## Phase checklist

### Phase 0 — Research and architecture
- [x] 0.1 Repo initialised, `.env` git-ignored (the old `.gitignore` was a directory holding `.env` — fixed, see D-002)
- [x] 0.2 Data sources verified with real requests → `docs/DATA_SOURCES.md`
- [x] 0.3 Ticker universe + survivorship-bias handling → `docs/DATA_SOURCES.md` §8
- [x] 0.4 Architecture (services, flows, ER diagram, API contract, ML plug-in) → `docs/ARCHITECTURE.md`
- [x] 0.5 Decisions recorded → `docs/DECISIONS.md` (D-001…D-018)

### Phase 1 — Website
- [ ] 1.1 Backend skeleton: config, structlog, `/health`, tooling (ruff, mypy, pytest)
- [ ] 1.2 DB models + Alembic migrations (Timescale hypertable, pgvector)
- [ ] 1.3 Auth (register / login / refresh, argon2, JWT)
- [ ] 1.4 Tickers, prices, news, FX, market overview endpoints + Redis cache + rate limiting
- [ ] 1.5 ML interface: mock prediction provider, mock + OpenAI-compatible trade reviewer
- [ ] 1.6 Paper trading (USD/KZT cash, fees, P&L, history) + trade reviews
- [ ] 1.7 Data connectors (Alpaca, Tradernet, yfinance, Finnhub, RSS, NBK) + Celery/Beat tasks + seed command
- [ ] 1.8 WebSocket `/ws/prices` via Redis pub/sub
- [ ] 1.9 Backend tests ≥ 70 % coverage
- [ ] 1.10 Frontend: Next.js pages, charts, i18n (EN/RU/KK), disclaimer, demo badge, responsive
- [ ] 1.11 Infra: docker-compose (db, redis, backend, worker, beat, frontend, nginx), Makefile, GitHub Actions CI
- [ ] 1.12 End-to-end check: `make up` + `make seed` from scratch, register, browse, trade, review

### Phase 2 — GPU plan
- [ ] 2.1 `docs/GPU_PLAN.md` complete (environment, pipeline, features, models, VRAM budget, backtest, MLflow, integration, checklist, cloud fallback)

### Extra (if time left)
- [ ] E.1 Data pipeline for real
- [ ] E.2 Shared feature module + CPU LightGBM/XGBoost baselines
- [ ] E.3 `python -m ml.train --config ... --dry-run`

## Log

### 2026-10-28 — Phase 0 done
- **Done:** fixed `.gitignore`/`.env` layout, created repo and folder skeleton; probed every data source with a few real requests (scripts in `scripts/research/`); wrote `DATA_SOURCES.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `BLOCKERS.md`.
- **Verified:** Alpaca bars (SIP from 2016-01-04, IEX from 2020-07-27, 200 req/min), Alpaca news (since 2015), Finnhub (60 req/min, news ~1 year, candles are premium), SEC companyfacts/submissions/frames, FRED series (no KZT series exists), yfinance (US + LSE GDRs + KZT=X + BZ=F), Tradernet getHloc for all 10 KASE Index shares (no auth), NBK official USD/KZT XML, 7 US + 7 KZ RSS feeds, GDELT.
- **Key findings:** KASE data is free only through the broker API (licence question → BLOCKERS #2); AIX has no free data (BLOCKERS #3); Tradernet bars are `[high, low, open, close]` with Almaty-midnight timestamps.
- **Left:** Phase 1 and 2.
