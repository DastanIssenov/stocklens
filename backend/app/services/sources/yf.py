"""yfinance: LSE GDRs, USD/KZT market rate, Brent futures, and a backup for US prices.

yfinance is unofficial and for personal use (docs/DATA_SOURCES.md §1.2) → small, infrequent requests.
The library is synchronous, so calls run in a worker thread.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import warnings
from typing import Any

from app.core.logging import get_logger
from app.services.sources.base import PriceBar, SourceError

log = get_logger(__name__)


def _history(symbol: str, start: dt.date, end: dt.date | None) -> Any:
    import yfinance as yf  # heavy import (pandas) kept lazy

    warnings.filterwarnings("ignore", module="yfinance")

    kwargs: dict[str, Any] = {
        "start": start.isoformat(),
        "interval": "1d",
        "auto_adjust": False,
        "actions": False,
    }
    if end:
        kwargs["end"] = (end + dt.timedelta(days=1)).isoformat()  # yfinance end is exclusive
    return yf.Ticker(symbol).history(**kwargs)


def frame_to_bars(df: Any) -> list[PriceBar]:
    bars: list[PriceBar] = []
    if df is None or len(df) == 0:
        return bars
    for idx, row in df.iterrows():
        try:
            close = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if close != close or close <= 0:  # NaN / bad rows
            continue
        adj = row.get("Adj Close")
        vol = row.get("Volume")
        bars.append(
            PriceBar(
                date=idx.date() if hasattr(idx, "date") else idx,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=close,
                volume=int(vol) if vol == vol and vol is not None else 0,
                adj_close=float(adj) if adj is not None and adj == adj else None,
            )
        )
    return bars


async def daily_bars(
    symbols: list[str], start: dt.date, end: dt.date | None = None
) -> dict[str, list[PriceBar]]:
    out: dict[str, list[PriceBar]] = {}
    for sym in symbols:
        try:
            df = await asyncio.to_thread(_history, sym, start, end)
            out[sym] = frame_to_bars(df)
        except Exception as e:
            log.warning("yfinance_failed", symbol=sym, error=str(e)[:150])
        await asyncio.sleep(0.5)  # be gentle
    if symbols and not out:
        raise SourceError("yfinance returned no data")
    return out


async def closes(symbol: str, start: dt.date) -> list[tuple[dt.date, float]]:
    bars = (await daily_bars([symbol], start)).get(symbol, [])
    return [(b.date, b.close) for b in bars]
