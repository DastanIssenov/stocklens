"""Alpaca Market Data v2: daily bars (SIP), live snapshots (IEX) and news (Benzinga).

Verified 2026-10-28 (docs/DATA_SOURCES.md §1.1, §4.1): 200 requests/min, SIP daily history from 2016.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.logging import get_logger
from app.services.news import NewsItem
from app.services.sources.base import PriceBar, SourceError

log = get_logger(__name__)
NY = ZoneInfo("America/New_York")


def _bar_date(ts: str) -> dt.date:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(NY).date()


class AlpacaClient:
    def __init__(self, key: str, secret: str, client: httpx.AsyncClient, data_url: str) -> None:
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self._client = client
        self._url = data_url.rstrip("/")

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.get(f"{self._url}{path}", params=params, headers=self._headers)
        if r.status_code != 200:
            raise SourceError(f"alpaca {path} HTTP {r.status_code}: {r.text[:200]}")
        data: dict[str, Any] = r.json()
        return data

    async def _bars(
        self, symbols: list[str], start: dt.date, end: dt.date | None, adjustment: str, feed: str
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        params: dict[str, Any] = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "limit": 10000,
            "adjustment": adjustment,
            "feed": feed,
        }
        if end:
            params["end"] = end.isoformat()
        for _ in range(100):  # pagination guard
            data = await self._get("/v2/stocks/bars", params)
            for sym, bars in (data.get("bars") or {}).items():
                out.setdefault(sym, []).extend(bars)
            token = data.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        return out

    async def daily_bars(
        self, symbols: list[str], start: dt.date, end: dt.date | None = None
    ) -> dict[str, list[PriceBar]]:
        """`close` = split-adjusted, `adj_close` = split + dividend adjusted. SIP feed, IEX fallback."""
        feed = "sip"
        try:
            split = await self._bars(symbols, start, end, "split", feed)
        except SourceError as e:
            log.warning("alpaca_sip_failed_fallback_iex", error=str(e)[:120])
            feed = "iex"
            split = await self._bars(symbols, start, end, "split", feed)
        full = await self._bars(symbols, start, end, "all", feed)
        result: dict[str, list[PriceBar]] = {}
        for sym, bars in split.items():
            adj = {b["t"]: b["c"] for b in full.get(sym, [])}
            result[sym] = [
                PriceBar(
                    date=_bar_date(b["t"]),
                    open=float(b["o"]),
                    high=float(b["h"]),
                    low=float(b["l"]),
                    close=float(b["c"]),
                    volume=int(b["v"]),
                    adj_close=float(adj[b["t"]]) if b["t"] in adj else None,
                )
                for b in bars
            ]
        return result

    async def snapshots(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Latest trade + previous daily close per symbol (IEX feed — real-time on the free plan)."""
        data = await self._get("/v2/stocks/snapshots", {"symbols": ",".join(symbols), "feed": "iex"})
        out: dict[str, dict[str, Any]] = {}
        for sym, snap in data.items():
            if not snap:
                continue
            trade = snap.get("latestTrade") or {}
            daily = snap.get("dailyBar") or {}
            prev = snap.get("prevDailyBar") or {}
            price = trade.get("p") or daily.get("c")
            if not price:
                continue
            out[sym] = {
                "symbol": sym,
                "price": float(price),
                "prev_close": float(prev["c"]) if prev.get("c") else None,
                "ts": trade.get("t") or daily.get("t"),
                "source": "alpaca_iex",
            }
        return out

    async def news(
        self, symbols: list[str] | None = None, start: dt.datetime | None = None, limit: int = 50
    ) -> list[NewsItem]:
        params: dict[str, Any] = {"limit": min(limit, 50), "sort": "desc"}
        if symbols:
            params["symbols"] = ",".join(symbols)
        if start:
            params["start"] = start.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = await self._get("/v1beta1/news", params)
        items: list[NewsItem] = []
        for n in data.get("news", []):
            if not n.get("url") or not n.get("headline"):
                continue
            items.append(
                NewsItem(
                    source=(n.get("source") or "alpaca").lower(),
                    lang="en",
                    published_at=dt.datetime.fromisoformat(n["created_at"].replace("Z", "+00:00")),
                    title=n["headline"],
                    url=n["url"],
                    summary=n.get("summary") or None,
                    symbols=list(n.get("symbols") or []),
                )
            )
        return items
