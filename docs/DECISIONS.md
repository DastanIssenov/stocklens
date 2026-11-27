# Decisions log

Every non-obvious decision made while working autonomously. Format: **what** was decided, **why**, and the **alternatives** considered.
Newest decisions are appended at the bottom.

---

### D-001 — Repository root is the `capstone/` folder
- **Decision:** the git repo root is `~/Desktop/capstone` itself; it plays the role of `stock-platform/` from TASK.md §3 (same sub-folders: `backend/`, `frontend/`, `data_pipeline/`, `ml/`, `infra/`, `docs/`).
- **Why:** `TASK.md` and the `.env` file already live there; nesting another `stock-platform/` folder adds a level with no benefit.
- **Alternatives:** create `capstone/stock-platform/` and move `.env` into it.

### D-002 — Fixed the `.gitignore` that was a directory
- **Decision:** on arrival `.gitignore` was a *directory* that contained `.env`. I moved `.env` to the repo root (permissions `600`), removed the empty directory and created a real `.gitignore` file whose first rule is `.env`. Done before `git init`, so the secrets were never staged.
- **Why:** TASK.md §0.7 — `.env` must be ignored before anything else.
- **Alternatives:** none sensible.

### D-003 — `.env` variable name casing
- **Decision:** the `.env` has `alpaca_endpoint` in lower case (the other keys are upper case). Config uses pydantic-settings with `case_sensitive=False`, so both spellings work; `.env.example` uses the canonical `ALPACA_ENDPOINT`. I did not edit the user's `.env` values.
- **Why:** do not touch the user's secrets file more than needed.

### D-004 — Task tracking
- **Decision:** this Claude Code session has no dedicated task-list tool, so the phase/task checklist lives at the top of `docs/PROGRESS.md` and is updated after each finished task.

## Phase 0 — data and architecture

### D-010 — US prices: Alpaca SIP primary, yfinance backup
- **Decision:** daily bars from Alpaca `feed=sip` (history 2016-01-04 →, verified); yfinance for pre-2016 history, LSE GDRs, FX, Brent and daily cross-checks. Alpaca IEX feed only for live snapshots (its volume is IEX-only).
- **Why:** official API with a known limit (200 req/min, verified), consolidated volume, ≥ 10 years of history. yfinance is unofficial and personal-use only.
- **Alternatives:** yfinance only (fragile, ToS); Finnhub candles (HTTP 403 on free plan — verified); Polygon/Massive (paid).

### D-011 — KASE prices via the Tradernet public `getHloc` API
- **Decision:** use Tradernet (Freedom Broker) `getHloc` for all KASE shares, one batched request per update, ≥ 5 s between calls. Mark the licence question as a blocker (BLOCKERS #2).
- **Why:** it is the only free, programmatic source found; it worked without authentication and covers all 10 KASE Index names with history from 2007–2024 depending on listing date. KASE's own API is a paid subscription.
- **Alternatives:** KASE IRIS API subscription (best for production — needs a contract), scraping kase.kz HTML (fragile, terms unclear), investing.com (scraping forbidden).

### D-012 — News storage policy
- **Decision:** store title, short summary, URL, source, language, published time; show only headline + link on the site; full text (if ever fetched) stays internal for model training and only where the publisher allows it.
- **Why:** RSS content is copyrighted; linking back is the accepted use of RSS.

### D-013 — Official NBK USD/KZT rate for portfolio conversion
- **Decision:** convert USD↔KZT in the paper-trading portfolio with the National Bank of Kazakhstan official rate (RSS); fall back to yfinance `KZT=X`, then to a configured constant.
- **Why:** official, free, daily; it is the reference rate in Kazakhstan.

### D-014 — Listing-level ticker model with a unique `symbol`
- **Decision:** one `tickers` row per **listing**. `symbol` is unique and follows Yahoo-style suffixes: US listings have no suffix (`AAPL`, `KSPI`), KASE uses `.KZ` (`KSPI.KZ`, `HSBK.KZ`), LSE GDRs use `.IL` (`KAP.IL`). `issuer` groups listings of one company so news links to all of them.
- **Why:** Kaspi trades on NASDAQ (USD) and KASE (KZT) — the same local code in two currencies. URL-friendly unique symbols keep routes simple (`/ticker/KSPI.KZ`).
- **Alternatives:** composite key (exchange, symbol) in every route — more verbose.

### D-015 — Celery + Celery Beat (not ARQ)
- **Decision:** Celery 5 with Redis broker + Celery Beat. Tasks are thin sync wrappers that call async service code with `asyncio.run()` and a per-task engine (`NullPool`) to avoid sharing event loops.
- **Why:** the stack table names Celery; Beat gives a declarative schedule; mature monitoring (flower) and retry semantics. ARQ is simpler but less known to the team and has no built-in scheduler UI.

### D-016 — `news.embedding` is `vector(1024)`
- **Decision:** pgvector column with 1024 dimensions, nullable.
- **Why:** the strongest open multilingual (EN/RU/KK) embedding models — BAAI/bge-m3 and intfloat/multilingual-e5-large — output 1024-dim vectors. Changing the dimension later needs only a migration.

### D-017 — Database image `timescale/timescaledb-ha:pg16`
- **Decision:** use the official Timescale HA image (PostgreSQL 16 + TimescaleDB + pgvector preinstalled, arm64 and amd64).
- **Why:** the plain `timescale/timescaledb` image has no pgvector; building a custom image adds maintenance. Same image in docker-compose, the test compose file and CI.

### D-018 — Seed universe
- **Decision:** 20 liquid US names (`AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA LLY UNH XOM WMT JNJ PG HD COST NFLX`) + all KZ listings verified in DATA_SOURCES §5 (10 KASE Index shares, 4 extra KASE shares flagged illiquid, KSPI and FRHC on NASDAQ, KAP.IL, HSBK.IL, AIRA.IL). AIX is in the schema but has no data source yet.
- **Why:** TASK.md asks for ~20 US tickers and all available KZ tickers.

## Phase 1 — backend

### D-019 — Plain bot User-Agent for all connectors
- **Decision:** `User-Agent: stock-platform-capstone/0.1` (honest bot identifier, no browser impersonation). SEC requests use `SEC_USER_AGENT` from `.env` as SEC requires.
- **Why:** verified that Tradernet answers **HTTP 403** when the UA contains a URL (`... +https://github.com/`), while a plain identifier is accepted. AIX blocks automated clients (Cloudflare) — we do not try to work around that.

### D-020 — Paper-trading rules
- **Decision:** market orders only, filled at the latest known price (live Alpaca IEX quote if fresh, else last daily close); whole shares; each trade settles in the listing currency (USD or KZT cash — no automatic FX); commission `max(min, rate × notional)`: US 0.05 % (min $1), KASE/AIX 0.15 % (min ₸300), LSE 0.1 % (min $3); buy commission goes into the cost basis; average-cost accounting; realised P&L = (price − avg cost) × qty − sell commission. Starting balance $100 000 + ₸50 000 000. Portfolio totals use the NBK official USD/KZT rate.
- **Why:** simple, explainable, close to what Kazakh retail brokers (Freedom, Halyk) charge; separate currency wallets avoid hidden FX conversions.
- **Alternatives:** limit orders / fractional shares (more UI and edge cases, little teaching value for now).

### D-021 — `close` = split-adjusted, `adj_close` = split + dividend adjusted
- **Decision:** charts and trading use `close` (split-adjusted, no dividend adjustment); models will use `adj_close` for returns. Tradernet has no dividend-adjusted series → `adj_close` is NULL for KASE; the GPU-phase pipeline will compute it from KASE dividend announcements (GPU_PLAN §2).
- **Why:** charts must not jump on splits, but past prices should look like what traders actually saw.

### D-022 — Today's KASE bar is provisional
- **Decision:** Tradernet returns a bar for the current day during the session; we store it and overwrite it on every 2-hourly update (upsert on `(ticker_id, date)`).
- **Why:** shows a near-live KZ price on the site. Models (GPU phase) must only use bars dated before the prediction date (look-ahead rule in GPU_PLAN §2).

### D-023 — Mock prediction text: EN and RU; KK falls back to RU
- **Decision:** rule-based review texts exist in English and Russian; Kazakh-locale users get Russian review text until a translation is added (the UI itself has KK strings).
- **Why:** time; Russian is understood by most KZ users. The LLM reviewer already answers in Kazakh when asked.

## Phase 1 — frontend

### D-024 — Client-side data fetching with TanStack Query; keep `cacheComponents`
- **Decision:** pages are thin server components that render client views; data comes from `/api/v1` via TanStack Query. The Next.js 16 template default `cacheComponents: true` is kept; hooks that read the URL (`usePathname`, `useParams`) are wrapped in `Suspense` as the bundled docs require.
- **Why:** almost all data is per-user or changes every minute; client fetching keeps one source of truth (the FastAPI API) and makes the site work behind any reverse proxy.
- **Alternatives:** server components fetching from the backend over the Docker network (needs a second base URL and token forwarding).

### D-025 — JWTs stored in `localStorage`
- **Decision:** access + refresh tokens are kept in `localStorage`; a 401 triggers one refresh attempt.
- **Why:** simplest flow that works both through nginx and with the dev proxy. Risk: XSS could read tokens. Mitigations: React escapes output, no `dangerouslySetInnerHTML`, external links use `rel="noopener noreferrer"`, access tokens live 15 min.
- **Later:** move the refresh token to an `HttpOnly; Secure; SameSite=Strict` cookie set by the backend once the site runs on one domain in production.

### D-026 — Own tiny i18n instead of next-intl
- **Decision:** typed dictionaries in `src/lib/i18n.ts` (EN, RU, KK) + a context; no locale in the URL.
- **Why:** three languages, ~130 strings, no SEO requirement for translated URLs. Kazakh UI is included (TASK asked "KZ if time allows").

### D-027 — Kazakh-language detection for KZ feeds
- **Decision:** items from RU/KK feeds are labelled `kk` when the text contains letters that exist only in Kazakh (ә ғ қ ң ө ұ ү һ і), otherwise `ru`.
- **Why:** verified that Kapital.kz publishes Kazakh articles in its Russian feed. A full language-ID model is planned for the GPU phase.

## Extras (TASK §5) — data pipeline and CPU baselines

### D-028 — US research universe = top-100 liquid operating companies from Alpaca + SEC
- **Decision:** candidates = active, tradable Alpaca NASDAQ/NYSE equities ∩ SEC `company_tickers.json`, minus funds/ETFs/notes by name, one listing per CIK; ranked by 60-day median dollar volume; plus the website's seed tickers.
- **Why:** TASK allows "NASDAQ-100 or the 100 most liquid stocks". Wikipedia (the usual NASDAQ-100 source) rejects bots without contact details in the User-Agent, and I did not want to send the owner's e-mail (`SEC_USER_AGENT`) to a non-SEC service. The liquidity universe uses only official APIs we already have keys for.
- **Known issue:** survivorship bias — this is *today's* list. Documented in DATA_REPORT; point-in-time membership is in GPU_PLAN §2.1.

### D-029 — Research workspace at the repo root
- **Decision:** `data_pipeline/` and `ml/` share a root `pyproject.toml` (uv, `.venv`), separate from the website backend. The pipeline has its own synchronous, bulk-oriented connectors (pagination, resume, Parquet), and imports only the pure ticker definitions from `backend/app/services/universe.py`.
- **Why:** heavy ML dependencies (LightGBM, XGBoost, MLflow) stay out of the web image; the website keeps working without them.
- **Note:** LightGBM on macOS needs `brew install libomp` (installed on this machine).

### D-030 — Promotion rule for trained models; CPU baselines stay "demo"
- **Decision:** the batch job (`ml/serving/batch_predict.py`) writes LightGBM predictions with `model_version = lgbm-cpu-<run>`; `is_demo = false` only if out-of-sample IC t-stat ≥ 2, AUC ≥ 0.52 and strategy Sharpe > benchmark Sharpe (after costs). Otherwise `is_demo = true` and the UI keeps the "Demo predictions" badge while showing the model version.
- **Why:** a weak CPU baseline must not look like a validated model to users (TASK §6: never promise returns).
- **How it reaches the site:** stored rows of a trained model win over mock rows for the same horizon; horizons without a trained model are filled by the mock provider (`services/predictions.py`).

### D-031 — Postgres published on 127.0.0.1:55433 in docker-compose
- **Decision:** `db` maps `127.0.0.1:${DB_PORT:-55433}:5432` so the research env can write batch predictions (5433 was taken on the dev Mac).
- **Why:** offline batch inference is the GPU-phase integration pattern (GPU_PLAN §8.2). Bound to localhost only.

### D-032 — Short-term model v2: rank label, dev-fold selection, ensemble (2026-11-26)
- **Decision:** the 5-day model predicts `xup_5` (stock beats the day's median 5-day return) instead of `up_5`; features = v1 + 12 within-day ranks − `hy_spread`; score = mean of LightGBM and XGBoost; strategy = top 10 % with a top-30 % hold band and a 3-day score EMA. Every choice was made on dev folds 2016–2018 (`ml/experiments/ablation.py`, `docs/ABLATION_DEV.md`); 2019–2026 was evaluated once.
- **Why:** v1's top features were market-level, so it timed the market (it said "up" for 12.6 %–99.2 % of a year's predictions) and its accuracy was below "always up". A 50/50 cross-sectional label makes the model rank stocks, which is what the strategy and the website use. The hold band halves turnover, which ate v1's edge.
- **Rejected on dev folds:** residual returns, SEC-filing / earnings-reaction features, macro changes, dropping macro levels or calendar, stronger regularisation (all lowered dev IC).
- **Result:** IC 0.013 → 0.023 (t 4.2), Sharpe 0.92 → 1.38 vs benchmark 1.36; still not promoted (AUC 0.505 < 0.52; the 21-day momentum baseline does better on strategy metrics). See `docs/BACKTEST_REPORT.md`.

### D-033 — `hy_spread` removed; website numbers come from out-of-sample calibration
- **Decision:** drop `hy_spread` from model features. Bundles carry two monotone tables fitted on pooled out-of-sample predictions (20 equal-count bins + isotonic regression): score → P(up over the horizon) and score → expected return. `batch_predict` uses them for `prob_up` and `predicted_return`.
- **Why:** FRED serves ICE BofA series only for the last 3 years, so `hy_spread` is empty before 2023-10 (79 % of rows). The model is trained on a ranking label, so its raw probability is not P(up); isotonic on raw rows pinned the tails at 0 / 1, binning first keeps the displayed P(up) at 51.8 %–55.2 %.

### D-034 — SEC fundamentals and industry features: built, not used by the 5-day model
- **Decision:** keep `FEATURE_GROUPS["fundamentals"]` (10 point-in-time ranks from `ml/features/fundamentals.py`) and `["industry"]` (SEC SIC → 9 groups, `data_pipeline backfill --what sectors`) in the code and tests, but the 5-day model stays v2 without them.
- **Why:** on dev folds 2016–2018 every variant lowered IC (0.030 → 0.007 all fundamentals, 0.027 fast-changing only, 0.015 / 0.027 industry). Slow per-stock ratios let the trees memorise stock identity in a ~100-name universe. They are long-horizon signals → reuse them for the 1–12-month models. Test folds were not run (nothing selected). See `docs/ABLATION_DEV_V3.md`.
- **Point-in-time rules:** TTM = last fiscal year + YTD − prior-year YTD, known from the filing's acceptance time (first session after it, same rule as D-033 filings); market cap = share count × close on the count date × total return since (adj_close ratio), so it needs no split table and does not change when history is re-adjusted.

