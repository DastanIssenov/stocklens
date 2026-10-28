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
