"""KASE daily bars from the Tradernet (Freedom Broker) public `getHloc` method (decision D-011).

Format (verified 2026-10-28): `hloc[ticker]` rows are **[high, low, open, close]**, `vl[ticker]` volumes,
`xSeries[ticker]` unix timestamps of **Moscow midnight**. Several tickers per request (comma-separated).
Etiquette: one batched request per update and ≥ `tradernet_min_interval_s` seconds between calls.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.logging import get_logger
from app.services.sources.base import PriceBar, SourceError

log = get_logger(__name__)
MSK = ZoneInfo("Europe/Moscow")

_lock = asyncio.Lock()
_last_call = 0.0


def bar_date(ts: int) -> dt.date:
    return dt.datetime.fromtimestamp(ts, dt.UTC).astimezone(MSK).date()


def parse_hloc(data: dict[str, Any]) -> dict[str, list[PriceBar]]:
    out: dict[str, list[PriceBar]] = {}
    for sym, rows in (data.get("hloc") or {}).items():
        xs = (data.get("xSeries") or {}).get(sym) or []
        vols = (data.get("vl") or {}).get(sym) or []
        bars: list[PriceBar] = []
        for i, row in enumerate(rows):
            if i >= len(xs) or len(row) < 4:
                continue
            high, low, open_, close = (float(v) for v in row[:4])
            bars.append(
                PriceBar(
                    date=bar_date(int(xs[i])),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=int(vols[i]) if i < len(vols) and vols[i] is not None else 0,
                    adj_close=None,  # Tradernet does not publish dividend-adjusted prices
                )
            )
        out[sym] = bars
    return out


async def _throttle(min_interval: float) -> None:
    global _last_call
    wait = _last_call + min_interval - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = time.monotonic()


async def daily_bars(
    client: httpx.AsyncClient,
    ids: list[str],
    start: dt.date,
    end: dt.date | None = None,
    *,
    url: str = "https://tradernet.com/api/",
    min_interval_s: float = 5.0,
) -> dict[str, list[PriceBar]]:
    end = end or dt.date.today() + dt.timedelta(days=1)
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
    async with _lock:
        await _throttle(min_interval_s)
        r = await client.get(url, params={"q": json.dumps(q)})
    if r.status_code != 200:
        raise SourceError(f"tradernet HTTP {r.status_code}")
    data = r.json()
    if "error" in data or "hloc" not in data:
        if len(ids) > 1 and "Failed to find" in str(data.get("error", "")):
            # one unknown ticker fails the whole batch → retry individually and skip bad ones
            out: dict[str, list[PriceBar]] = {}
            for one in ids:
                try:
                    out.update(
                        await daily_bars(client, [one], start, end, url=url, min_interval_s=min_interval_s)
                    )
                except SourceError as e:
                    log.warning("tradernet_ticker_failed", ticker=one, error=str(e)[:100])
            return out
        raise SourceError(f"tradernet error: {str(data.get('error') or data)[:150]}")
    return parse_hloc(data)
