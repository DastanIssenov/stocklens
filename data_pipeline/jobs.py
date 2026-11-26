"""Backfill and daily-update jobs. Every job is idempotent (Parquet upsert on a key) and resumable."""

from __future__ import annotations

import datetime as dt
import logging
import re

import pandas as pd

from data_pipeline import cleaning, storage
from data_pipeline.config import KZ_LISTINGS, MACRO_SERIES, US_LISTINGS, YAHOO_MARKET
from data_pipeline.connectors import alpaca, others
from data_pipeline.http import Polite, SourceError

log = logging.getLogger("pipeline")

_FUND_WORDS = re.compile(
    r"\b(ETF|ETN|Fund|Trust|iShares|SPDR|ProShares|Direxion|Invesco|Vanguard|Leveraged|Inverse|"
    r"Bitcoin|Ether|Notes|Warrant|Units?|Rights?|Preferred|Depositary Shares? Series)\b",
    re.I,
)


# ------------------------------------------------------------------ universe
def build_universe(top_n: int = 100, lookback_days: int = 60) -> pd.DataFrame:
    """Top-N US operating companies by median dollar volume (TASK §4 Phase 0: "100 most liquid").

    Candidates = active Alpaca NASDAQ/NYSE equities ∩ SEC company_tickers (operating companies), minus funds.
    Survivorship bias: this is today's list — see docs/DATA_REPORT.md.
    """
    ac = alpaca.client()
    sc = others.sec_client()
    try:
        a = alpaca.assets(ac)
        a = a[a["exchange"].isin(["NASDAQ", "NYSE"]) & a["tradable"]]
        a = a[~a["name"].str.contains(_FUND_WORDS, na=False)]
        sec = others.sec_tickers(sc)
        cand = a.merge(sec, left_on="symbol", right_on="ticker", how="inner")
        cand = cand[~cand["symbol"].str.contains(r"[.\-/ ]")]  # skip share classes with suffixes like BRK.B
        start = dt.date.today() - dt.timedelta(days=lookback_days)
        b = alpaca.bars(ac, sorted(cand["symbol"].unique()), start, chunk=200)
        b["dollar_volume"] = b["close"] * b["volume"]
        liq = b.groupby("symbol")["dollar_volume"].median().rename("median_dollar_volume")
        out = cand.merge(liq, left_on="symbol", right_index=True).sort_values(
            "median_dollar_volume", ascending=False
        )
        out = out.drop_duplicates("cik").head(top_n)  # one listing per company (GOOGL vs GOOG)
        seed = {x.symbol for x in US_LISTINGS} | {"KSPI", "FRHC"}
        extra = cand[cand["symbol"].isin(seed - set(out["symbol"]))].assign(median_dollar_volume=None)
        out = pd.concat([out, extra], ignore_index=True)
        out["as_of"] = dt.date.today()
        out["market"] = "US"
        return out[["symbol", "name", "exchange", "cik", "median_dollar_volume", "market", "as_of"]]
    finally:
        ac.close()
        sc.close()


def universe_symbols() -> list[str]:
    u = storage.read("universe_us")
    if u.empty:
        raise SourceError("run `python -m data_pipeline universe` first")
    return sorted(u["symbol"])


# ------------------------------------------------------------------ prices
def backfill_us_prices(
    start: dt.date, symbols: list[str] | None = None, yahoo_before: dt.date | None = None
) -> int:
    symbols = symbols or universe_symbols()
    ac = alpaca.client()
    try:
        raw = alpaca.bars(ac, symbols, start, adjustment="raw")
        adj = alpaca.bars(ac, symbols, start, adjustment="all")[["symbol", "date", "close"]]
        df = raw.merge(adj.rename(columns={"close": "adj_close"}), on=["symbol", "date"], how="left")
        df["source"] = "alpaca_sip"
        n = storage.upsert("prices_us", cleaning.validate_bars(df), ["symbol", "date"])
        acts = alpaca.corporate_actions(ac, symbols, start, dt.date.today())
        if not acts.empty:
            storage.upsert("corporate_actions_us", acts, ["type", "symbol", "date"])
    finally:
        ac.close()
    if yahoo_before:  # deeper history (Alpaca SIP starts 2016-01-04)
        y = others.yahoo_bars(symbols, yahoo_before)
        if not y.empty:
            y = y[y["date"] < dt.date(2016, 1, 4)].drop(columns=["dividend", "split"])
            y["source"] = "yahoo"
            n = storage.upsert("prices_us", cleaning.validate_bars(y), ["symbol", "date"])
    return n


def backfill_kz_prices(start: dt.date) -> int:
    ids = [x.source_symbol for x in KZ_LISTINGS if x.data_source == "tradernet"]
    tc = Polite("tradernet")
    try:
        df = others.tradernet_bars(tc, ids, start, dt.date.today())
    finally:
        tc.close()
    df["adj_close"] = None
    df["source"] = "tradernet"
    n = storage.upsert("prices_kz", cleaning.validate_bars(df), ["symbol", "date"])
    abroad = [x.source_symbol for x in KZ_LISTINGS if x.data_source == "yfinance"]
    y = others.yahoo_bars(abroad, start)
    if not y.empty:
        y["source"] = "yahoo"
        n = storage.upsert(
            "prices_kz", cleaning.validate_bars(y.drop(columns=["dividend", "split"])), ["symbol", "date"]
        )
    return n


def backfill_market(start: dt.date) -> int:
    y = others.yahoo_bars(YAHOO_MARKET, start)
    return storage.upsert("market_yahoo", y, ["symbol", "date"])


def backfill_macro(start: dt.date) -> int:
    fc = Polite("fred")
    frames = []
    try:
        for sid in MACRO_SERIES:
            try:
                frames.append(others.fred_series(fc, sid, start))
            except SourceError as e:
                log.warning("fred %s failed: %s", sid, e)
    finally:
        fc.close()
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    return storage.upsert("macro_fred", df, ["series_id", "date"])


def backfill_nbk(start: dt.date, end: dt.date | None = None) -> int:
    """Official USD/KZT, one request per calendar day (resumes where it stopped)."""
    have = storage.read("fx_nbk")
    done = set(have["date"]) if not have.empty else set()
    end = end or dt.date.today()
    nc = Polite("nbk")
    rows, n = [], len(have)
    try:
        d = start
        while d <= end:
            if d not in done:
                try:
                    v = others.nbk_usd(nc, d)
                except SourceError as e:  # transient network errors: skip the day, a re-run fills it
                    log.warning("nbk %s skipped: %s", d, e)
                    v = None
                if v:
                    rows.append({"date": d, "usdkzt": v})
                if len(rows) >= 50:
                    n = storage.upsert("fx_nbk", pd.DataFrame(rows), ["date"])
                    rows = []
            d += dt.timedelta(days=1)
    finally:
        nc.close()
        if rows:
            n = storage.upsert("fx_nbk", pd.DataFrame(rows), ["date"])
    return n


def backfill_fundamentals(symbols: list[str] | None = None, batch: int = 10) -> int:
    """SEC companyfacts → selected metrics with publication timestamps. Resumable: skips companies already in
    the lake; writes every `batch` companies (a full rewrite per company was O(n²))."""
    u = storage.read("universe_us")
    ciks = dict(zip(u["symbol"], u["cik"], strict=True))
    have = storage.read("fundamentals_us")
    done = set(have["symbol"]) if not have.empty else set()
    todo = [s for s in (symbols or sorted(ciks)) if s in ciks and s not in done]
    key = ["symbol", "metric", "tag", "unit", "period_end", "accession", "period_start"]
    sc = others.sec_client()
    n, buf = len(have), []
    try:
        for i, s in enumerate(todo, 1):
            try:
                buf.append(others.sec_facts(sc, int(ciks[s]), s))
            except SourceError as e:
                log.warning("sec %s: %s", s, e)
            if buf and (i % batch == 0 or i == len(todo)):
                n = storage.upsert("fundamentals_us", pd.concat(buf, ignore_index=True), key)
                buf = []
                log.info("fundamentals: %d/%d companies", i, len(todo))
    finally:
        sc.close()
        if buf:
            n = storage.upsert("fundamentals_us", pd.concat(buf, ignore_index=True), key)
    return n


def backfill_sectors() -> int:
    """SEC SIC code per universe company → `sectors_us` (symbol, cik, sic, sic_description, sector = FF12)."""
    u = storage.read("universe_us")
    sc = others.sec_client()
    rows = []
    try:
        for s, cik in zip(u["symbol"], u["cik"], strict=True):
            try:
                info = others.sec_company(sc, int(cik))
            except SourceError as e:
                log.warning("sec %s: %s", s, e)
                info = {"sic": None, "sic_description": None}
            rows.append({"symbol": s, "cik": int(cik), **info, "sector": others.ff12(info["sic"])})
    finally:
        sc.close()
    return storage.upsert("sectors_us", pd.DataFrame(rows), ["symbol"])
