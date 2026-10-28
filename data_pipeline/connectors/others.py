"""Tradernet (KASE), Yahoo (yfinance), FRED, National Bank of Kazakhstan, SEC EDGAR."""

from __future__ import annotations

import datetime as dt
import json
import warnings
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from data_pipeline.config import MACRO_SERIES, SECRETS, US_FUNDAMENTAL_TAGS
from data_pipeline.http import Polite, SourceError

MSK = ZoneInfo("Europe/Moscow")


# ------------------------------------------------------------------ KASE via Tradernet
def tradernet_bars(c: Polite, ids: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
    q = {
        "cmd": "getHloc",
        "params": {
            "id": ",".join(ids),
            "count": -1,
            "timeframe": 1440,
            "date_from": start.strftime("%d.%m.%Y 00:00"),
            "date_to": end.strftime("%d.%m.%Y 23:59"),
            "intervalMode": "ClosedRay",
        },
    }
    r = c.get("https://tradernet.com/api/", {"q": json.dumps(q)})
    if r.status_code != 200:
        raise SourceError(f"tradernet HTTP {r.status_code}")
    j = r.json()
    if "hloc" not in j:
        raise SourceError(f"tradernet: {str(j)[:150]}")
    rows = []
    for sym, bars in j["hloc"].items():
        xs, vols = j["xSeries"][sym], j["vl"][sym]
        for i, (h, lo, o, cl) in enumerate(bars):
            d = dt.datetime.fromtimestamp(int(xs[i]), dt.UTC).astimezone(MSK).date()
            rows.append(
                {
                    "symbol": sym,
                    "date": d,
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": cl,
                    "volume": int(vols[i] or 0),
                }
            )
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ Yahoo
def yahoo_bars(symbols: list[str], start: dt.date) -> pd.DataFrame:
    import time

    import yfinance as yf

    warnings.filterwarnings("ignore", module="yfinance")
    frames = []
    for s in symbols:
        h = yf.Ticker(s).history(start=start.isoformat(), interval="1d", auto_adjust=False, actions=True)
        time.sleep(1.0)
        if h.empty:
            continue
        h = h.reset_index()
        h["date"] = pd.to_datetime(h["Date"]).dt.date
        h["symbol"] = s
        frames.append(
            h.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Adj Close": "adj_close",
                    "Volume": "volume",
                    "Dividends": "dividend",
                    "Stock Splits": "split",
                }
            )[["symbol", "date", "open", "high", "low", "close", "adj_close", "volume", "dividend", "split"]]
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ------------------------------------------------------------------ FRED / ALFRED
def fred_series(c: Polite, series_id: str, start: dt.date) -> pd.DataFrame:
    if not SECRETS.fred_key:
        raise SourceError("FRED_KEY missing")
    r = c.get(
        "https://api.stlouisfed.org/fred/series/observations",
        {
            "series_id": series_id,
            "api_key": SECRETS.fred_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            # first-release vintages: realtime_start = when the value was first published (point-in-time)
            "realtime_start": start.isoformat(),
            "realtime_end": "9999-12-31",
            "output_type": 4,
        },
    )
    if r.status_code != 200:
        raise SourceError(f"fred {series_id} HTTP {r.status_code}")
    obs = r.json().get("observations", [])
    df = pd.DataFrame(obs)
    if df.empty:
        return df
    df = df[df["value"] != "."]
    return pd.DataFrame(
        {
            "series_id": series_id,
            "name": MACRO_SERIES.get(series_id, series_id),
            "date": pd.to_datetime(df["date"]).dt.date,
            "available_at": pd.to_datetime(df["realtime_start"]).dt.date,
            "value": df["value"].astype(float),
        }
    )


# ------------------------------------------------------------------ National Bank of Kazakhstan
def nbk_usd(c: Polite, day: dt.date) -> float | None:
    import re

    r = c.get("https://nationalbank.kz/rss/get_rates.cfm", {"fdate": day.strftime("%d.%m.%Y")})
    if r.status_code != 200:
        raise SourceError(f"nbk HTTP {r.status_code}")
    m = re.search(r"<title>USD</title>\s*<description>([\d.]+)</description>", r.text)
    return float(Decimal(m.group(1))) if m else None


# ------------------------------------------------------------------ SEC EDGAR
def sec_client() -> Polite:
    if not SECRETS.sec_user_agent:
        raise SourceError("SEC_USER_AGENT missing (SEC requires a contact in the User-Agent)")
    return Polite("sec", {"User-Agent": SECRETS.sec_user_agent, "Accept-Encoding": "gzip, deflate"})


def sec_tickers(c: Polite) -> pd.DataFrame:
    r = c.get("https://www.sec.gov/files/company_tickers.json")
    if r.status_code != 200:
        raise SourceError(f"sec tickers HTTP {r.status_code}")
    return pd.DataFrame(r.json().values()).rename(columns={"cik_str": "cik", "title": "sec_name"})


def sec_acceptance_times(c: Polite, cik: int) -> dict[str, str]:
    """accession number → acceptanceDateTime (exact publication time, used for point-in-time features)."""
    r = c.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if r.status_code != 200:
        return {}
    recent = r.json()["filings"]["recent"]
    return dict(zip(recent["accessionNumber"], recent["acceptanceDateTime"], strict=False))


def sec_facts(c: Polite, cik: int, symbol: str) -> pd.DataFrame:
    r = c.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
    if r.status_code != 200:
        raise SourceError(f"sec companyfacts {symbol} HTTP {r.status_code}")
    facts: dict[str, Any] = r.json().get("facts", {})
    accepted = sec_acceptance_times(c, cik)
    rows = []
    for taxonomy in ("us-gaap", "dei"):
        for tag, metric in US_FUNDAMENTAL_TAGS.items():
            node = facts.get(taxonomy, {}).get(tag)
            if not node:
                continue
            for unit, items in node.get("units", {}).items():
                for it in items:
                    if it.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F"):
                        continue
                    acc = it.get("accn")
                    rows.append(
                        {
                            "symbol": symbol,
                            "cik": cik,
                            "metric": metric,
                            "tag": tag,
                            "unit": unit,
                            "value": it.get("val"),
                            "period_start": it.get("start"),
                            "period_end": it.get("end"),
                            "fy": it.get("fy"),
                            "fp": it.get("fp"),
                            "form": it.get("form"),
                            "accession": acc,
                            "filed": it.get("filed"),
                            "accepted_at": accepted.get(acc),
                        }
                    )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # available_at = SEC acceptance time when known (submissions only lists the last ~1000 filings), else filed date
    df["available_at"] = pd.to_datetime(df["accepted_at"].fillna(df["filed"]), utc=True, format="mixed")
    return df.drop(columns=["accepted_at"])
