# data_pipeline/ — historical data pipeline (GPU phase, CPU-only work)

Historical load into a Parquet lake (`data/lake/`, not in git) for model training. The website does its own
small daily updates through `backend/app/services/ingest.py`. Plan: [`docs/GPU_PLAN.md` §2](../docs/GPU_PLAN.md);
coverage and gaps: [`docs/DATA_REPORT.md`](../docs/DATA_REPORT.md).

```bash
uv run python -m data_pipeline universe                       # top-100 liquid US companies → universe_us
uv run python -m data_pipeline backfill --start 2016-01-01 --yahoo-before 2010-01-01
uv run python -m data_pipeline backfill --what sectors        # SEC SIC code + Fama–French 12 sector → sectors_us
uv run python -m data_pipeline daily                          # last 14 days of prices, market, macro, NBK
uv run python -m data_pipeline report                         # → docs/DATA_REPORT.md
```

| Dataset | Source | Content |
|---|---|---|
| `universe_us` | Alpaca + SEC | symbols, CIK, median dollar volume |
| `prices_us`, `prices_kz` | Alpaca SIP / Yahoo, Tradernet (KASE), Yahoo (LSE GDRs) | daily OHLCV, adjusted close, quality flags |
| `corporate_actions_us` | Alpaca (from 2016) | dividends, splits |
| `market_yahoo` | Yahoo | SPY, QQQ, ^GSPC, ^NDX, ^VIX, KZT=X, BZ=F |
| `macro_fred` | FRED / ALFRED | rates, CPI, unemployment, USD index, Brent … with `available_at` |
| `fx_nbk` | National Bank of Kazakhstan | official USD/KZT |
| `fundamentals_us` | SEC companyfacts | 12 metrics per filing with acceptance time (`available_at`) |
| `sectors_us` | SEC submissions | SIC code, description, FF12 sector |

Rules (look-ahead bias): every row carries the timestamp when it became **public**
(`published_at`, SEC `acceptanceDateTime`, news `created_at`); features may only use rows public before the
prediction cut-off (US: 16:00 New York on day *t* for a prediction made after the close of *t*).
