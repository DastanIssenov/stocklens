# Data sources

All sources below were **checked with small real requests on 2026-10-28** (a few calls each, no bulk downloads).
The probe scripts are in [`scripts/research/`](../scripts/research/) and can be re-run with
`.venv-research/bin/python scripts/research/probe_us.py` (and `probe_yf.py`, `probe_rss.py`). They never print secrets.

Legend: ✅ verified with a real request · ⚠️ works with caveats · ❌ not usable · 📄 taken from documentation only (not measured).

## Summary table

| Area | Primary | Backup / cross-check | Status |
|---|---|---|---|
| US daily prices | Alpaca Market Data v2 (SIP feed, history since 2016) | yfinance (history since IPO) | ✅ |
| US live-ish quotes | Alpaca snapshots (IEX feed, free) | Finnhub `/quote` | ✅ |
| US fundamentals | SEC EDGAR XBRL `companyfacts` + `submissions` | — | ✅ |
| Macro | FRED API | yfinance (`^VIX`, `BZ=F`) | ✅ |
| US news | Alpaca News (Benzinga, since 2015) | Finnhub company news (1 year back), RSS, GDELT | ✅ |
| KASE prices | Tradernet (Freedom Broker) public `getHloc` API | KASE official API (paid subscription) | ⚠️ licence to confirm |
| AIX prices | — | LSEG/Refinitiv (paid) | ❌ no free programmatic access |
| KZ issuers listed abroad | yfinance (`KSPI`, `FRHC`, `KAP.IL`, `HSBK.IL`, `AIRA.IL`) + Alpaca for NASDAQ names | Tradernet (`KAP.EU`, `HSBK.EU`, `KSPI.US`) | ✅ |
| KZ news (RU/KZ) | RSS: Kursiv, Kapital.kz, Inbusiness (ru+kk), Tengrinews (ru+kk), LSM.kz | GDELT; Forbes.kz news sitemap | ✅ (Forbes.kz ⚠️) |
| USD/KZT | National Bank of Kazakhstan official rate (RSS/XML) | yfinance `KZT=X` (market rate, since 2003) | ✅ |
| Brent | FRED `DCOILBRENTEU` (EIA spot, ~1 week lag) | yfinance `BZ=F` (front-month future, same day) | ✅ |

---

## 1. US prices

### 1.1 Alpaca Market Data API v2 — **primary** ✅
- **Provides:** OHLCV daily/minute bars, VWAP, trade count, latest trade/quote, snapshots; split/dividend adjustment via `adjustment=raw|split|dividend|all`.
- **Feeds (verified):**
  - `feed=sip` (all US exchanges): **history starts 2016-01-04** (request with `start=2015-12-01` returned first bar 2016-01-04). On the free plan SIP data is allowed when the request does not touch the last 15 minutes — a daily-bar request without `end` worked (HTTP 200).
  - `feed=iex` (IEX exchange only, real-time on free plan): daily bars only **since 2020-07-27**, and volumes are IEX-only (≈2 % of consolidated volume — e.g. AAPL 1.08 M on IEX vs ~40 M consolidated). Use IEX only for intraday/live display, never for volume features.
- **Limits (observed headers):** `x-ratelimit-limit: 200` requests/minute per key. Multi-symbol requests are allowed (`symbols=AAPL,MSFT,...`), `limit` up to 10 000 bars per page with `next_page_token` pagination.
- **Auth:** headers `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` from `.env` (`ALPACA_KEY`, `ALPACA_SECRET`). The `.env` endpoint is the **paper trading** host (`paper-api.alpaca.markets`, account status `ACTIVE`); market data always comes from `https://data.alpaca.markets`.
- **Licence:** market data is provided to Alpaca account holders under Alpaca's market-data terms; public redistribution has exchange rules. OK for an educational, non-commercial, low-traffic project; re-check before any public deployment.
- **Example (worked):**
  ```bash
  curl -H "APCA-API-KEY-ID: $ALPACA_KEY" -H "APCA-API-SECRET-KEY: $ALPACA_SECRET" \
    "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL,MSFT&timeframe=1Day&start=2016-01-01&limit=10000&feed=sip&adjustment=all"
  # → {"bars":{"AAPL":[{"t":"2016-01-04T05:00:00Z","o":..,"h":..,"l":..,"c":..,"v":..,"n":..,"vw":..},...]},"next_page_token":...}
  ```
  Snapshot: `GET /v2/stocks/snapshots?symbols=AAPL&feed=iex` → keys `dailyBar, latestQuote, latestTrade, minuteBar, prevDailyBar`.

### 1.2 yfinance (Yahoo Finance) — **backup and cross-check** ✅
- **Provides:** daily OHLCV + adjusted close, dividends, splits; very deep history (AAPL from **1980-12-12**, `^GSPC` from 1927, `^NDX` from 1985). Also FX, futures and non-US listings (needed for Kazakh GDRs on LSE).
- **Version tested:** `yfinance 1.7.0`.
- **Limits:** unofficial (scrapes Yahoo endpoints); no documented quota, may break or throttle without notice. Yahoo's terms allow personal use only → use it as a backup/cross-check and for the few instruments Alpaca does not cover, keep request volume low, never as the only source of truth for US equities.
- **Example (worked):** `yf.Ticker("AAPL").history(period="max", auto_adjust=False)` → 11 561 rows, last 2026-10-27, close 347.10 (Alpaca SIP close for the same day 347.10 ✔ cross-check).

### Comparison

| | Alpaca SIP | Alpaca IEX | yfinance |
|---|---|---|---|
| History depth | 2016-01 → | 2020-07 → | IPO → (decades) |
| Volume | consolidated | IEX only | consolidated |
| Real-time | 15-min delayed on free plan | real-time | ~15 min delayed |
| Rate limit | 200 req/min | 200 req/min | undocumented |
| Reliability | official API, SLA-less but stable | same | breaks occasionally |
| Licence | Alpaca market-data terms | same | personal use |

**Decision:** Alpaca SIP is primary for US daily bars (≥ 10 years available: 2016 → today); yfinance fills pre-2016 history and is used for daily cross-checks (|close diff| > 0.5 % ⇒ data-quality flag). See D-010.

---

## 2. US fundamentals — SEC EDGAR ✅
- **Endpoints (all verified):**
  - `https://www.sec.gov/files/company_tickers.json` → ticker → CIK map (10 430 entries; contains `KSPI` → CIK 1985487, Joint Stock Co Kaspi.kz, which files 20-F/6-K).
  - `https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json` → every XBRL fact for a company (AAPL: 503 us-gaap concepts, 3.8 MB). Each fact has `start`, `end`, `val`, `accn`, `fy`, `fp`, `form`, **`filed`** (publication date → used for point-in-time features) and `frame`.
    Example fact: Revenue 2026-03-29..2026-06-27 = 109 417 000 000 USD, form 10-Q, **filed 2026-07-31**.
  - `https://data.sec.gov/submissions/CIK0000320193.json` → filing list with `acceptanceDateTime` (exact timestamp; better than `filed` for look-ahead rules).
  - `https://data.sec.gov/api/xbrl/frames/us-gaap/EarningsPerShareBasic/USD-per-shares/CY2024Q4.json` → one concept for all companies in one period (1 086 rows) — handy for cross-sectional features.
- **Limits:** SEC fair-access policy: **max 10 requests/second**, a descriptive `User-Agent` with contact e-mail is mandatory (`SEC_USER_AGENT` in `.env`). No key.
- **Licence:** public-domain US government data.
- **Caveat:** foreign private issuers (Kaspi, Freedom files 10-K/10-Q as a US company) report under IFRS (`ifrs-full` taxonomy), not `us-gaap` — the fundamentals parser must handle both.

---

## 3. Macro — FRED API ✅
- **Endpoint:** `https://api.stlouisfed.org/fred/series/observations?series_id=...&api_key=$FRED_KEY&file_type=json`
- **Series verified (title / frequency / range):**

| Series | Meaning | Freq | Range (verified) |
|---|---|---|---|
| `DFF` | Fed funds effective rate | D | 1954-07-01 → 2026-10-26 |
| `DGS10` | 10-year Treasury yield | D | 1962-01-02 → 2026-10-26 |
| `CPIAUCSL` | CPI (all urban) | M | 1947-01 → 2026-09 |
| `VIXCLS` | CBOE VIX close | D | 1990-01-02 → 2026-10-26 |
| `DCOILBRENTEU` | Brent spot (EIA) | D | 1987-05-20 → 2026-10-20 (≈1 week publication lag) |
| `DTWEXBGS` | Broad USD index | D | 2006-01-02 → 2026-10-23 |

- **No tenge series in FRED** (search "Kazakhstan tenge" returns only BIS bond-issuance series; `EXKZUS`, `CCUSMA02KZM618N` do not exist) → USD/KZT comes from the National Bank of Kazakhstan (§7).
- **Limits:** 📄 120 requests/minute per key (FRED docs). Free key.
- **Licence:** FRED terms of use; some series are third-party copyrighted (e.g. VIX © Cboe) — fine for internal features, show attribution if displayed.
- **Point-in-time caveat:** FRED returns the *latest revised* values. For CPI and other revised series use ALFRED vintages (`realtime_start/realtime_end` params) in the GPU phase.

---

## 4. US news

### 4.1 Alpaca News API ✅ (primary)
- `GET https://data.alpaca.markets/v1beta1/news?symbols=AAPL&limit=50` → `created_at, updated_at, headline, summary, content (HTML, optional), source, url, symbols[]`. Source is **Benzinga**; ticker tags are provided by the vendor (very useful for linking).
- History: oldest item returned with `start=2015-01-01&sort=asc` is **2015-01-01** → ~11 years of tagged news.
- Same 200 req/min limit as market data; max `limit=50` per page, paginated.

### 4.2 Finnhub ✅ (secondary)
- `GET /api/v1/company-news?symbol=AAPL&from=...&to=...&token=$FINNHUB_KEY` → 247 items for one week of AAPL (sources: Yahoo, etc.).
- **History only ~1 year on the free plan:** the same query for 2024-01-02..05 returned 0 items.
- `GET /api/v1/news?category=general` → 100 latest market headlines (Reuters etc.).
- `GET /api/v1/quote?symbol=AAPL` ✅; `GET /api/v1/stock/profile2?symbol=KSPI` ✅ (country KZ, NASDAQ).
- `GET /api/v1/stock/candle` → **HTTP 403 (premium)** → do not use Finnhub for prices.
- **Limit (observed header):** `x-ratelimit-limit: 60` per minute.
- Licence: free plan, attribution to Finnhub.

### 4.3 RSS (headline + link only) ✅

| Feed | URL | Items | Lang |
|---|---|---|---|
| CNBC Top News | `https://www.cnbc.com/id/100003114/device/rss/rss.html` | 30 | en |
| CNBC Markets | `https://www.cnbc.com/id/20910258/device/rss/rss.html` | 30 | en |
| MarketWatch Top | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | 10 | en |
| Yahoo Finance per ticker | `https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US` | 17 | en |
| Nasdaq Stocks | `https://www.nasdaq.com/feed/rssoutbound?category=Stocks` | 15 | en |
| SEC press releases | `https://www.sec.gov/news/pressreleases.rss` | 25 | en |
| Investing.com news | `https://www.investing.com/rss/news.rss` | 10 | en |

Not working: `finance.yahoo.com/news/rssindex` (404); MarketWatch "marketpulse" feed is stale (last item 2025-07).

### 4.4 GDELT DOC 2.0 ✅
- `https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&format=json&maxrecords=..&timespan=3d` → URL, title, `seendate`, domain, language, country. Free, no key, worldwide incl. Russian/Kazakh-language media; 📄 ~1 request / 5 s; returns only the last 3 months by default.
- Good for **coverage/attention features** (article counts) and for discovering KZ articles; titles only (no body).
- Licence: open, cite GDELT.

---

## 5. Kazakhstan prices

### 5.1 KASE (Kazakhstan Stock Exchange)
- **Official:** KASE sells market data as information products; API access ("IRIS API") is by **subscription** (contact `mds@kase.kz`, standard agreement and API spec PDFs on <https://kase.kz/en/information/market-prices>). Not free → **not used in this run**, recommended for production (see BLOCKERS #2).
- **Used instead: Tradernet / Freedom Broker public quotes API** ✅ — `getHloc` works **without authentication** for KASE instruments (other methods such as `getStockQuotesJson` require credentials).
  ```bash
  curl -G "https://tradernet.com/api/" --data-urlencode \
   'q={"cmd":"getHloc","params":{"id":"HSBK.KZ,KSPI.KZ,KZTK.KZ","count":-1,"timeframe":1440,"date_from":"01.01.2010 00:00","date_to":"28.10.2026 00:00","intervalMode":"ClosedRay"}}'
  # → {"hloc":{"HSBK.KZ":[[high,low,open,close],...]},"vl":{"HSBK.KZ":[vol,...]},"xSeries":{"HSBK.KZ":[unix_ts,...]},"info":{...,"mkt_name":"KASE","currency":"KZT"},...}
  ```
  Format gotchas (verified): bar order is **[high, low, open, close]**; `xSeries` timestamps are **Moscow midnight (21:00 UTC of the previous day)**, so convert with `Europe/Moscow` before taking the date — verified on 2020 bars: a bar dated Sunday 2020-01-05 appears, which was an official working day in Kazakhstan (moved from Friday 2020-01-03, which has no bar); several tickers per request with a **comma-separated** `id`; unknown tickers return `{"error": "Failed to find instruments..."}`.
- **KASE Index representative list (kase.kz, 28.10.2026) — all verified on Tradernet:**

| KASE ticker | Company | Weight % | Tradernet id | First bar | Rows |
|---|---|---|---|---|---|
| AIRA | Air Astana | 10.68 | AIRA.KZ | 2024-02-08 | 667 |
| CCBN | Bank CenterCredit | 14.46 | CCBN.KZ | 2007-12-27 | 3 989 |
| HSBK | Halyk Bank | 12.57 | HSBK.KZ | 2009-12-30 | 3 962 |
| KCEL | Kcell | 12.58 | KCEL.KZ | 2012-12-11 | 3 305 |
| KEGC | KEGOC | 4.43 | KEGC.KZ | 2014-12-18 | 2 889 |
| KMGZ | KazMunayGas | 13.33 | KMGZ.KZ | 2022-12-06 | 957 |
| KSPI | Kaspi.kz | 12.93 | KSPI.KZ | 2018-07-22 | 1 309 |
| KZAP | Kazatomprom | 11.78 | KZAP.KZ | 2018-12-10 | 1 906 |
| KZTK | Kazakhtelecom | 3.28 | KZTK.KZ | 2009-12-30 | 3 943 |
| KZTO | KazTransOil | 3.96 | KZTO.KZ | 2012-12-24 | 3 394 |

  Other KASE shares found: `ASBN.KZ` ForteBank (2016→), `BAST.KZ` BAST (2015→, very thin: vol 41), `KMGD.KZ` KM Gold, `RAHT.KZ` Lotte Rakhat (vol 4). Row counts well below 252/year show **illiquidity** (e.g. KSPI.KZ 1 309 rows in 8 years) → gaps are real no-trade days, not missing data.
- **Limits / etiquette:** no published quota. `tradernet.com/robots.txt` sets `Crawl-delay: 20` for crawlers; we batch all KZ tickers into one request and keep ≥ 5 s between API calls (one request per day is enough for the daily update).
- **Licence:** ⚠️ Tradernet does not publish explicit API terms for unauthenticated use. Acceptable for a non-commercial educational prototype at one request per day; before any public launch either get written permission from Freedom Broker or buy the KASE data product. Recorded in BLOCKERS #2 and D-011.

### 5.2 AIX (Astana International Exchange) ❌
- No free public API was found. Real-time data is distributed via LSEG/Refinitiv; the website is behind Cloudflare bot protection, so automated access is not appropriate (we did not try to get around it).
- Most AIX-listed Kazakh equities are dual-listed on KASE (KZAP, KMGZ, AIRA, KCEL, KEGC, HSBK...), so the **KASE line covers the same companies**. `AIX` stays a valid exchange code in the schema for later. See BLOCKERS #3.

### 5.3 Kazakh companies listed abroad ✅ (verified tickers)

| Company | Venue | yfinance | Alpaca | Tradernet | First bar (yfinance) | Currency |
|---|---|---|---|---|---|---|
| Kaspi.kz | NASDAQ | `KSPI` | `KSPI` | `KSPI.US` | 2024-01-19 (NASDAQ IPO) | USD |
| Freedom Holding Corp. (HQ Almaty, US-incorporated) | NASDAQ | `FRHC` | `FRHC` | `FRHC.US` | 2018-02-07 | USD |
| Kazatomprom (GDR) | LSE | `KAP.IL` | — | `KAP.EU` | 2018-11-13 | USD |
| Halyk Bank (GDR) | LSE | `HSBK.IL` | — | `HSBK.EU` | 2006-12-14 | USD |
| Air Astana (GDR) | LSE | `AIRA.IL` | — | — | 2024-02-09 (thin volume) | USD |

Notes: `KAP.L` / `HSBK.L` exist on Yahoo only since 2026-07-17 → use the `.IL` lines for history. Kcell GDRs (`KCEL.IL`) return no data (no longer traded in London). Central Asia Metals (`CAML.L`) and Caspian Sunrise (`CASP.L`) are UK-incorporated with Kazakh assets — out of scope for the KZ universe.

---

## 6. Kazakhstan news (RU / KZ)

| Source | Feed URL | Items | Lang | robots.txt |
|---|---|---|---|---|
| Kursiv | `https://kz.kursiv.media/feed/` | 100 | ru | — (redirect) |
| Kapital.kz | `https://kapital.kz/feed` | 101 | ru | allows (only `/preview/`, `/to/` disallowed) |
| Inbusiness.kz | `https://inbusiness.kz/ru/rss`, `https://inbusiness.kz/kz/rss` | 65 + 65 | ru, **kk** | allows (`/api/` disallowed — we do not use it) |
| Tengrinews | `https://tengrinews.kz/news.rss`, `https://kaz.tengrinews.kz/news.rss` | 102 + 102 | ru, **kk** | — |
| LSM.kz | `https://lsm.kz/rss` | 50 | ru | — |
| Forbes Kazakhstan | `https://forbes.kz/rss/` → 200 but **0 items** | 0 | ru | allows; has news sitemaps (`/sitemaps/sitemap_index-news_ru.xml`) ⚠️ |
| Inform.kz | `/ru/rss` → **403** | — | — | ❌ |
| KASE news / disclosures | no RSS (`/ru/rss` → 404) | — | — | HTML pages only ⚠️ |

- **Usage rules (D-012):** store title, short summary, URL, published time and language; **do not republish full article text** on the site — show the headline and link to the publisher. Full text for model training is fetched in the GPU phase only where terms allow, and is kept internal.
- **Company disclosures:** KASE issuer news pages and the Depository of Financial Statements (`dfo.kz`) are the official channels; both are HTML-only → planned for the GPU phase (GPU_PLAN §2), respecting robots.txt and low request rates.

---

## 7. Tenge and oil

### USD/KZT
- **National Bank of Kazakhstan (official rate) ✅**
  - Today: `https://nationalbank.kz/rss/rates_all.xml` (48 currencies).
  - Any date: `https://nationalbank.kz/rss/get_rates.cfm?fdate=27.10.2026` → `<item><fullname>ДОЛЛАР США</fullname><title>USD</title><description>451.05</description><quant>1</quant>...`
  - One request per day, so history back-fill = one request per date (≈2 600 requests for 10 years at 1 req/s ≈ 45 min) — fine for the GPU phase; not needed now.
  - Official public information; robots.txt does not disallow `/rss/`.
- **yfinance `KZT=X` ✅** market rate, daily since **2003-12-01** (455.73 on 2026-10-28) → history back-fill and intraday-ish value.
- The **official NBK rate is used for converting KZT ↔ USD in the paper-trading portfolio** (D-013).

### Brent
- FRED `DCOILBRENTEU` (EIA spot, back to 1987, ~1 week lag; last value 115.22 on 2026-10-20) — for model features use the value **as published** (lagged).
- yfinance `BZ=F` (ICE front-month future, since 2007-07-30, same-day close 110.97) — for the website and as a same-day feature.

---

## 8. Ticker universe

### US
- **Phase 1 (website seed):** 20 large, liquid names across sectors: `AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA LLY UNH XOM WMT JNJ PG HD COST NFLX` + Kazakh-related US listings `KSPI FRHC`.
- **Model universe (GPU phase):** NASDAQ-100 constituents first, schema and pipeline designed for the S&P 500 (~500 names, ≈ 1.3 M daily rows for 10 years).
- **Benchmarks:** `^GSPC`, `^NDX` (yfinance), `SPY`, `QQQ` (Alpaca).

### Kazakhstan
- KASE Index constituents (10 names above) + `ASBN`, `KMGD`, `BAST`, `RAHT` flagged `is_liquid = false`.
- Abroad: `KSPI` (NASDAQ), `FRHC` (NASDAQ), `KAP.IL`, `HSBK.IL`, `AIRA.IL` (LSE).
- The same company can have several listings (e.g. Kaspi: `KSPI` NASDAQ in USD and `KSPI` KASE in KZT). In the DB each **listing** is a row in `tickers` with its own exchange and currency; listings of the same issuer are linked by a shared `issuer` field so news is linked to all of them.

### Survivorship bias
Training only on today's index members inflates backtests (failed / delisted companies disappear). Handling:
1. **Point-in-time membership table** (`universe_membership(ticker, index, start_date, end_date)`) built from historical NASDAQ-100 / S&P 500 change lists (Wikipedia change tables, cross-checked with public datasets such as `fja05680/sp500`); a stock is in the training set on date *t* only if it was a member on *t*.
2. **Keep delisted tickers**: Alpaca returns history for inactive assets (`status=inactive`), yfinance often does not → note the gap in the data-quality report.
3. KZ: the KASE Index list changes rarely; store the representative-list history from KASE announcements, and treat newly listed names (AIRA 2024, KMGZ 2022) with their real start dates.
4. Report backtest results both on the point-in-time universe and on the current universe, so the bias is visible.
