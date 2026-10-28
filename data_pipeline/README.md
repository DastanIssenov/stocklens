# data_pipeline/ — historical data pipeline (GPU phase, CPU-only work)

Empty skeleton for now. The website already performs **small** daily updates through
`backend/app/services/ingest.py`; this package will do the **full historical load** and the research-grade
cleaning needed for model training. Step-by-step plan: [`docs/GPU_PLAN.md` §2](../docs/GPU_PLAN.md).

Planned layout:

```
data_pipeline/
├── connectors/     # alpaca, yfinance, tradernet, sec_edgar, fred, nbk, gdelt, rss  (reuse backend/app/services/sources)
├── jobs/           # backfill_prices, backfill_fundamentals, backfill_macro, backfill_news, daily_update
├── cleaning/       # splits/dividends, gaps, outliers, KZ illiquidity flags, calendar alignment
├── linking/        # news → ticker (vendor tags + RU/KK/EN aliases + NER)
├── quality/        # checks → docs/DATA_REPORT.md
└── storage/        # Parquet lake (data/raw, data/processed) + Postgres loaders
```

Rules (look-ahead bias): every row carries the timestamp when it became **public**
(`published_at`, SEC `acceptanceDateTime`, news `created_at`); features may only use rows public before the
prediction cut-off (US: 16:00 New York on day *t* for a prediction made after the close of *t*).
