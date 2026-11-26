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
REVISED_SERIES = {"CPIAUCSL", "UNRATE"}  # revised after publication → use first-release vintages (ALFRED)


def fred_series(c: Polite, series_id: str, start: dt.date) -> pd.DataFrame:
    """Daily market series are never revised: plain observations, available the next day (FRED publishes
    with ≥ 1 business day delay). Revised macro series: first-release values with their real publication date."""
    if not SECRETS.fred_key:
        raise SourceError("FRED_KEY missing")
    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": SECRETS.fred_key,
        "file_type": "json",
        "observation_start": start.isoformat(),
    }
    vintage = series_id in REVISED_SERIES
    if vintage:
        params.update({"realtime_start": start.isoformat(), "realtime_end": "9999-12-31", "output_type": 4})
    r = c.get("https://api.stlouisfed.org/fred/series/observations", params)
    if r.status_code != 200:
        raise SourceError(f"fred {series_id} HTTP {r.status_code}")  # never echo the URL: it holds the key
    df = pd.DataFrame(r.json().get("observations", []))
    if df.empty:
        return df
    df = df[df["value"] != "."]
    date = pd.to_datetime(df["date"])
    available = pd.to_datetime(df["realtime_start"]) if vintage else date + pd.Timedelta(days=1)
    return pd.DataFrame(
        {
            "series_id": series_id,
            "name": MACRO_SERIES.get(series_id, series_id),
            "date": date.dt.date,
            "available_at": available.dt.date,
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


def sec_company(c: Polite, cik: int) -> dict[str, Any]:
    """SIC industry code and name from the submissions endpoint (current value; SIC codes rarely change)."""
    r = c.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if r.status_code != 200:
        raise SourceError(f"sec submissions CIK {cik} HTTP {r.status_code}")
    j = r.json()
    sic = j.get("sic")
    return {"sic": int(sic) if sic else None, "sic_description": j.get("sicDescription") or None}


# Fama–French 12-industry grouping of SIC codes (French's Data Library definition); everything else → "Other"
_FF12: list[tuple[str, list[tuple[int, int]]]] = [
    ("NoDur", [(100, 999), (2000, 2399), (2700, 2749), (2770, 2799), (3100, 3199), (3940, 3989)]),
    (
        "Durbl",
        [
            (2500, 2519),
            (2590, 2599),
            (3630, 3659),
            (3710, 3711),
            (3714, 3714),
            (3716, 3716),
            (3750, 3751),
            (3792, 3792),
            (3900, 3939),
            (3990, 3999),
        ],
    ),
    (
        "Manuf",
        [
            (2520, 2589),
            (2600, 2699),
            (2750, 2769),
            (3000, 3099),
            (3200, 3569),
            (3580, 3629),
            (3700, 3709),
            (3712, 3713),
            (3715, 3715),
            (3717, 3749),
            (3752, 3791),
            (3793, 3799),
            (3830, 3839),
            (3860, 3899),
        ],
    ),
    ("Enrgy", [(1200, 1399), (2900, 2999)]),
    ("Chems", [(2800, 2829), (2840, 2899)]),
    ("BusEq", [(3570, 3579), (3660, 3692), (3694, 3699), (3810, 3829), (7370, 7379)]),
    ("Telcm", [(4800, 4899)]),
    ("Utils", [(4900, 4949)]),
    ("Shops", [(5000, 5999), (7200, 7299), (7600, 7699)]),
    ("Hlth", [(2830, 2839), (3693, 3693), (3840, 3859), (8000, 8099)]),
    ("Money", [(6000, 6999)]),
]


def ff12(sic: int | None) -> str:
    if sic is None:
        return "Other"
    for name, ranges in _FF12:
        if any(lo <= sic <= hi for lo, hi in ranges):
            return name
    return "Other"


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
