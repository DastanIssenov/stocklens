# Architecture

Educational project — **not investment advice**. This document describes the whole system; parts marked *(GPU phase)* are planned, not built yet.

## 1. Services

```mermaid
flowchart LR
    subgraph Client
        B[Browser<br/>Next.js app]
    end
    subgraph Edge
        N[Nginx<br/>reverse proxy :80]
    end
    subgraph App
        FE[frontend<br/>Next.js 16 SSR :3000]
        API[backend<br/>FastAPI + Uvicorn :8000<br/>REST /api/v1 + WS /ws/prices]
        W[worker<br/>Celery]
        BT[beat<br/>Celery Beat scheduler]
    end
    subgraph Data
        PG[(PostgreSQL 16<br/>+ TimescaleDB + pgvector)]
        R[(Redis 7<br/>cache · rate limit · pub/sub · broker)]
    end
    subgraph External
        ALP[Alpaca<br/>bars · snapshots · news]
        YF[yfinance<br/>LSE GDRs · FX · Brent · backup]
        TN[Tradernet getHloc<br/>KASE bars]
        FH[Finnhub<br/>company news]
        RSS[RSS feeds<br/>US + KZ outlets]
        NBK[National Bank KZ<br/>USD/KZT]
        SEC[SEC EDGAR]
        FRED[FRED]
        LLM[OpenAI-compatible LLM<br/>optional · later vLLM on RTX 5090]
    end

    B --> N
    N -->|/| FE
    N -->|/api, /ws, /health| API
    FE -->|server-side fetch| API
    API --> PG
    API --> R
    API -. trade review .-> LLM
    BT -->|schedules| R
    R -->|tasks| W
    W --> PG
    W -->|publish prices| R
    R -->|pub/sub| API
    W --> ALP & YF & TN & FH & RSS & NBK
    W -. GPU phase .-> SEC & FRED
```

| Service | Image / runtime | Role |
|---|---|---|
| `db` | `timescale/timescaledb-ha:pg16` (TimescaleDB + pgvector) | relational data, price hypertable, news embeddings |
| `redis` | `redis:7-alpine` | cache (TTL), rate-limit counters, pub/sub for live prices, Celery broker/result backend |
| `backend` | Python 3.12, FastAPI, Uvicorn | REST API, WebSocket, auth, paper trading, ML interfaces |
| `worker` | same image, `celery worker` | data updates, trade reviews with slow LLMs, *(GPU phase)* nightly inference |
| `beat` | same image, `celery beat` | periodic schedule |
| `frontend` | Node 22, Next.js 16 (App Router), standalone output | UI |
| `nginx` | `nginx:alpine` | single origin: `/` → frontend, `/api` + `/ws` → backend |

## 2. Data flows

### 2.1 Prices
```mermaid
sequenceDiagram
    participant Beat
    participant Worker
    participant Src as Alpaca / Tradernet / yfinance
    participant DB as Postgres (prices_daily)
    participant Redis
    participant API
    participant UI as Browser
    Beat->>Worker: update_daily_prices (weekdays, after US close & after KASE close)
    Worker->>Src: last ~10 days of bars (batched symbols)
    Worker->>DB: UPSERT (ticker_id, date)
    Worker->>Redis: DEL cache prices:* for updated tickers
    Beat->>Worker: refresh_live_quotes (every minute, US market hours)
    Worker->>Src: Alpaca IEX snapshots (one call for all US symbols)
    Worker->>Redis: SET quote:{symbol} (TTL) + PUBLISH prices {...}
    Redis-->>API: pub/sub message
    API-->>UI: WebSocket /ws/prices push
    UI->>API: GET /api/v1/prices/AAPL
    API->>Redis: cache hit? else query DB, SET with TTL
```
- Source routing per ticker is stored in `tickers.data_source` (`alpaca`, `tradernet`, `yfinance`) + `tickers.source_symbol`, so adding a listing needs no code change.
- KASE bars come from Tradernet in one batched request per run; LSE GDRs, FX (`KZT=X`) and Brent (`BZ=F`) from yfinance; the official USD/KZT rate from the National Bank RSS.

### 2.2 News
Beat → `update_news` (every 30 min): Alpaca news (tickers tagged by vendor) + Finnhub company news for the US seed list + RSS feeds (US and KZ). Each item is de-duplicated by URL, language detected from the feed (`en`/`ru`/`kk`), and linked to tickers by **(a)** vendor tags and **(b)** alias matching (`ticker_aliases`: "Kaspi", "Каспи", "Halyk", "Халык", "Народный банк", "Қазатомөнеркәсіп"...). `sentiment` and `embedding` stay `NULL` until the GPU phase fills them.

### 2.3 Paper trading and AI review
```mermaid
sequenceDiagram
    participant UI
    participant API
    participant Price as PriceService
    participant Port as TradingService
    participant Rev as TradeReviewer (mock or LLM)
    UI->>API: POST /api/v1/trades {symbol, side, quantity}
    API->>Price: latest price (Redis quote → last daily close)
    API->>Port: validate cash/position, apply fee, update cash + position (one DB transaction, row lock)
    Port-->>API: trade
    API->>Rev: review(TradeContext: trade, portfolio weights, volatility, recent move, prediction)
    Rev-->>API: TradeReview (strict JSON, Pydantic-validated)
    API-->>UI: trade + review
```
If the reviewer fails or times out, the trade is still stored and the review falls back to the rule-based mock (marked as such).

### 2.4 Predictions
`PredictionProvider.predict(ticker, as_of, horizons)` returns `PredictionResult`s. Today `MockPredictionProvider` produces deterministic demo values (hash of ticker + date + horizon, nudged by real recent momentum) and every prediction is stored with `is_demo = true` → the UI shows a **"Demo predictions"** badge. In the GPU phase a nightly Celery task runs the real provider for the whole universe and writes to `predictions`; the API serves the latest row per (ticker, horizon).

## 3. Database schema

```mermaid
erDiagram
    users ||--o| portfolios : owns
    portfolios ||--o{ positions : holds
    portfolios ||--o{ trades : records
    trades ||--o| trade_reviews : "reviewed by"
    tickers ||--o{ positions : ""
    tickers ||--o{ trades : ""
    tickers ||--o{ prices_daily : "has (hypertable)"
    tickers ||--o{ predictions : ""
    tickers ||--o{ fundamentals : ""
    tickers ||--o{ news_tickers : ""
    tickers ||--o{ ticker_aliases : ""
    news ||--o{ news_tickers : ""

    users { int id PK
        string email UK
        string password_hash "argon2id"
        string display_name
        string locale "en|ru|kk"
        bool is_active
        timestamptz created_at }
    tickers { int id PK
        string symbol UK "AAPL, KSPI.KZ, KAP.IL"
        string local_symbol "KSPI"
        string name
        string exchange "NASDAQ|NYSE|KASE|AIX|LSE"
        string market "US|KZ"
        string currency "USD|KZT"
        string sector
        string industry
        string country
        string issuer "groups listings of one company"
        string data_source "alpaca|tradernet|yfinance"
        string source_symbol
        bool is_liquid
        bool is_active }
    ticker_aliases { int id PK
        int ticker_id FK
        string alias
        string lang }
    prices_daily { int ticker_id PK
        date date PK "hypertable time column"
        numeric open
        numeric high
        numeric low
        numeric close
        numeric adj_close
        bigint volume
        string source }
    fx_rates { string pair PK "USDKZT"
        date date PK
        numeric rate
        string source PK "nbk|yfinance" }
    news { bigint id PK
        string source
        string lang
        timestamptz published_at
        string title
        text summary
        text body "nullable, internal only"
        string url UK
        float sentiment "nullable (GPU phase)"
        vector embedding "vector(1024), nullable" }
    news_tickers { bigint news_id PK
        int ticker_id PK
        string match_method "vendor|alias"
        float relevance }
    fundamentals { bigint id PK
        int ticker_id FK
        string metric
        numeric value
        string unit
        date period_start
        date period_end
        string fiscal_period
        timestamptz published_at "SEC acceptance time - point in time"
        string accession
        string source }
    predictions { bigint id PK
        int ticker_id FK
        string model_version
        string horizon "1d,5d,1m,3m,6m,12m"
        int horizon_days
        date as_of_date
        float predicted_return
        float prob_up
        float confidence
        jsonb top_features
        bool is_demo }
    portfolios { int id PK
        int user_id FK,UK
        numeric cash_usd
        numeric cash_kzt
        numeric initial_usd
        numeric initial_kzt }
    positions { int id PK
        int portfolio_id FK
        int ticker_id FK
        numeric quantity
        numeric avg_cost
        numeric realized_pnl }
    trades { bigint id PK
        int portfolio_id FK
        int ticker_id FK
        string side "buy|sell"
        numeric quantity
        numeric price
        numeric fee
        string currency
        numeric realized_pnl
        timestamptz executed_at
        string price_source }
    trade_reviews { bigint id PK
        bigint trade_id FK,UK
        string reviewer "mock|llm"
        string model
        string verdict "reasonable|risky|poor"
        int score "1-10"
        jsonb reasons
        jsonb risks
        jsonb what_to_watch }
```

Notes:
- `prices_daily` is a TimescaleDB hypertable partitioned on `date` (1-year chunks; ~10 k rows/ticker for 40 years is tiny). Primary key `(ticker_id, date)` makes daily upserts idempotent.
- `fundamentals.published_at` is the SEC `acceptanceDateTime` (or `filed` date) — features may only use rows with `published_at` < prediction time (look-ahead rule).
- `news.embedding` is `vector(1024)` to match multilingual embedding models with 1024 dimensions (bge-m3, multilingual-e5-large), see D-016.
- Money columns are `NUMERIC(20, 6)`; prices `NUMERIC(20, 6)`; no floats for cash.

## 4. API contract (`/api/v1`)

All responses are JSON. Errors: `{"detail": "..."}` with proper HTTP status. Auth = `Authorization: Bearer <access JWT>`.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | – | liveness + DB/Redis checks |
| POST | `/auth/register` | – | `{email, password, display_name?}` → user + tokens; creates portfolio with starting balance |
| POST | `/auth/login` | – | `{email, password}` → `{access_token, refresh_token, token_type}` |
| POST | `/auth/refresh` | – | `{refresh_token}` → new token pair |
| GET | `/auth/me` | ✔ | current user |
| GET | `/tickers` | – | list; filters `market=US\|KZ`, `exchange`, `q`, `limit`, `offset` |
| GET | `/tickers/search?q=` | – | fast search by symbol / name / alias (top 10) |
| GET | `/tickers/{symbol}` | – | ticker details + latest quote |
| GET | `/market/overview?market=US\|KZ` | – | tickers with last price/change, top gainers/losers, USD/KZT, Brent |
| GET | `/prices/{symbol}?start=&end=` | – | daily OHLCV bars (cached) |
| GET | `/prices/{symbol}/latest` | – | latest quote (live quote if fresh, else last close) |
| GET | `/news?symbol=&lang=&limit=&offset=` | – | news list, newest first |
| GET | `/predictions/{symbol}` | – | latest prediction per horizon + `is_demo`, `model_version`, disclaimer |
| GET | `/fx/latest` | – | USD/KZT (official + market) |
| GET | `/portfolio` | ✔ | cash (USD, KZT), positions with market value and P&L, totals in USD and KZT |
| POST | `/portfolio/reset` | ✔ | reset to starting balance |
| POST | `/trades` | ✔ | `{symbol, side, quantity}` → executed trade + review |
| GET | `/trades` | ✔ | trade history with reviews |
| GET | `/trades/{id}` | ✔ | one trade + review |
| POST | `/trades/{id}/review` | ✔ | re-run the review (e.g. after switching to the LLM reviewer) |
| GET | `/meta` | – | active prediction provider / reviewer (mock or real), disclaimer text, supported currencies |
| WS | `/ws/prices?symbols=AAPL,MSFT` | – | pushes `{"type":"quote","symbol","price","change_pct","ts"}` |

Rate limits (Redis, fixed window per client IP; per user when authenticated): general 120 req/min, `/auth/*` 10 req/min, `POST /trades` 30 req/min → `429` with `Retry-After`.

Caching (Redis): price history 10 min, latest quote 60 s, market overview 60 s, predictions 1 h, news 5 min. Data-update tasks invalidate the affected keys.

## 5. How the ML part plugs in

```
backend/app/ml_interface/
├── base.py          # PredictionProvider, TradeReviewer (ABCs) + Pydantic I/O schemas
├── mock.py          # MockPredictionProvider, MockTradeReviewer (rule-based)
├── openai_compat.py # OpenAICompatibleTradeReviewer (any OpenAI-compatible /chat/completions, incl. vLLM)
└── factory.py       # builds providers from settings
```

- `PREDICTION_PROVIDER=mock|mlflow` and `TRADE_REVIEWER=mock|llm|auto` in `.env` choose the implementation; `auto` uses the LLM reviewer only when `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` are set. **Switching to real models = changing these variables** (and starting vLLM / having MLflow reachable); no code in the API layer changes.
- *(GPU phase)* `MLflowPredictionProvider` loads the model registered as `production` (`models:/short_term_gbm@production`, `models:/long_term_rank@production`) and uses the shared feature module `ml/features/` — the same code that built the training set — to compute features as of the prediction date.
- *(GPU phase)* the trade reviewer is served by **vLLM** with an OpenAI-compatible endpoint on the RTX 5090 machine, so `OpenAICompatibleTradeReviewer` is reused as-is (`LLM_BASE_URL=http://gpu-box:8001/v1`). Its output is forced to strict JSON (`response_format={"type":"json_object"}` + Pydantic validation + one retry, then fallback to the mock).
- *(GPU phase)* nightly Celery task `run_nightly_inference` writes predictions for all tickers with `is_demo=false`; the "Demo" badge disappears automatically because the API reports `is_demo` per prediction.

## 6. Security and compliance
- Secrets only in `.env` (git-ignored); `.env.example` documents every variable. Settings objects never log secret values (`SecretStr`).
- Passwords: argon2id (`argon2-cffi`). JWT HS256: access 15 min, refresh 7 days, `type` claim checked; refresh tokens carry a `jti`.
- CORS restricted to the frontend origin; behind Nginx the app is same-origin.
- Disclaimer component on every page that shows predictions or reviews; API responses for predictions/reviews carry a `disclaimer` field.
- Data use: headlines + links only on the site; respect robots.txt and rate limits (SEC ≤ 10 req/s, Tradernet ≥ 5 s between calls, GDELT ≤ 1 req/5 s).
