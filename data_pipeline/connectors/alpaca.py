"""Alpaca: asset list, multi-symbol daily bars (SIP, raw + all-adjusted), corporate actions."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from data_pipeline.config import SECRETS
from data_pipeline.http import Polite, SourceError

DATA = "https://data.alpaca.markets"
TRADING = "https://paper-api.alpaca.markets"
NY = ZoneInfo("America/New_York")


def client() -> Polite:
    if not (SECRETS.alpaca_key and SECRETS.alpaca_secret):
        raise SourceError("ALPACA_KEY / ALPACA_SECRET missing in .env")
    return Polite(
        "alpaca", {"APCA-API-KEY-ID": SECRETS.alpaca_key, "APCA-API-SECRET-KEY": SECRETS.alpaca_secret}
    )


def _json(c: Polite, url: str, params: dict[str, Any]) -> Any:
    r = c.get(url, params)
    if r.status_code != 200:
        raise SourceError(f"alpaca {url.rsplit('/', 1)[-1]} HTTP {r.status_code}: {r.text[:150]}")
    return r.json()


def assets(c: Polite) -> pd.DataFrame:
    rows = _json(c, f"{TRADING}/v2/assets", {"status": "active", "asset_class": "us_equity"})
    df = pd.DataFrame(rows)
    return df[["symbol", "name", "exchange", "tradable", "status"]]


def _chunks(xs: list[str], n: int) -> Iterator[list[str]]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def bars(
    c: Polite,
    symbols: list[str],
    start: dt.date,
    end: dt.date | None = None,
    adjustment: str = "raw",
    feed: str = "sip",
    chunk: int = 100,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for group in _chunks(symbols, chunk):
        params: dict[str, Any] = {
            "symbols": ",".join(group),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "limit": 10000,
            "adjustment": adjustment,
            "feed": feed,
        }
        if end:
            params["end"] = end.isoformat()
        while True:
            j = _json(c, f"{DATA}/v2/stocks/bars", params)
            for sym, rows in (j.get("bars") or {}).items():
                if rows:
                    f = pd.DataFrame(rows)
                    f["symbol"] = sym
                    frames.append(f)
            if not j.get("next_page_token"):
                break
            params["page_token"] = j["next_page_token"]
        params.pop("page_token", None)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(NY).dt.date
    return df.rename(
        columns={
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "n": "trades",
            "vw": "vwap",
        }
    )[["symbol", "date", "open", "high", "low", "close", "volume", "trades", "vwap"]]


def corporate_actions(c: Polite, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for group in _chunks(symbols, 50):
        # the endpoint limits the date span; walk it year by year
        y0 = start
        while y0 <= end:
            y1 = min(end, dt.date(y0.year, 12, 31))
            params: dict[str, Any] = {
                "symbols": ",".join(group),
                "types": "forward_split,reverse_split,cash_dividend",
                "start": y0.isoformat(),
                "end": y1.isoformat(),
                "limit": 1000,
            }
            while True:
                j = _json(c, f"{DATA}/v1/corporate-actions", params)
                for kind, rows in (j.get("corporate_actions") or {}).items():
                    for r in rows:
                        out.append({"type": kind, **r})
                if not j.get("next_page_token"):
                    break
                params["page_token"] = j["next_page_token"]
            y0 = dt.date(y0.year + 1, 1, 1)
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df.get("ex_date", df.get("process_date"))).dt.date
    keep = [
        k
        for k in ("type", "symbol", "date", "rate", "new_rate", "old_rate", "special", "payable_date")
        if k in df
    ]
    return df[keep]
