"""News feeds (RSS, Finnhub) and the National Bank of Kazakhstan official FX rates.

All feeds were verified on 2026-10-28 (docs/DATA_SOURCES.md §4.3 and §6). Only headline, short
summary and link are stored (decision D-012).
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import feedparser
import httpx

from app.core.logging import get_logger
from app.services.news import NewsItem
from app.services.sources.base import SourceError

log = get_logger(__name__)


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    lang: str
    market: str  # US | KZ


RSS_FEEDS: tuple[Feed, ...] = (
    # US (en)
    Feed("cnbc", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "en", "US"),
    Feed("marketwatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "en", "US"),
    Feed("nasdaq", "https://www.nasdaq.com/feed/rssoutbound?category=Stocks", "en", "US"),
    # Kazakhstan (ru / kk)
    Feed("kursiv", "https://kz.kursiv.media/feed/", "ru", "KZ"),
    Feed("kapital", "https://kapital.kz/feed", "ru", "KZ"),
    Feed("inbusiness", "https://inbusiness.kz/ru/rss", "ru", "KZ"),
    Feed("inbusiness_kk", "https://inbusiness.kz/kz/rss", "kk", "KZ"),
    Feed("tengrinews", "https://tengrinews.kz/news.rss", "ru", "KZ"),
    Feed("tengrinews_kk", "https://kaz.tengrinews.kz/news.rss", "kk", "KZ"),
    Feed("lsm", "https://lsm.kz/rss", "ru", "KZ"),
)


def _entry_time(e: Any) -> dt.datetime:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return dt.datetime.fromtimestamp(calendar.timegm(t), dt.UTC)
    return dt.datetime.now(dt.UTC)


def parse_feed(content: bytes, feed: Feed) -> list[NewsItem]:
    parsed = feedparser.parse(content)
    items: list[NewsItem] = []
    for e in parsed.entries:
        link, title = e.get("link"), e.get("title")
        if not link or not title:
            continue
        items.append(
            NewsItem(
                source=feed.name,
                lang=feed.lang,
                published_at=_entry_time(e),
                title=title,
                url=link,
                summary=e.get("summary") or e.get("description"),
            )
        )
    return items


async def fetch_feed(client: httpx.AsyncClient, feed: Feed) -> list[NewsItem]:
    r = await client.get(feed.url, follow_redirects=True)
    if r.status_code != 200:
        raise SourceError(f"rss {feed.name} HTTP {r.status_code}")
    return parse_feed(r.content, feed)


async def finnhub_company_news(
    client: httpx.AsyncClient, token: str, symbol: str, start: dt.date, end: dt.date
) -> list[NewsItem]:
    r = await client.get(
        "https://finnhub.io/api/v1/company-news",
        params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "token": token},
    )
    if r.status_code != 200:
        raise SourceError(f"finnhub company-news HTTP {r.status_code}")  # never echo the URL (has token)
    items: list[NewsItem] = []
    for n in r.json() or []:
        if not n.get("url") or not n.get("headline"):
            continue
        items.append(
            NewsItem(
                source=(n.get("source") or "finnhub").lower()[:50],
                lang="en",
                published_at=dt.datetime.fromtimestamp(int(n.get("datetime") or 0), dt.UTC),
                title=n["headline"],
                url=n["url"],
                summary=n.get("summary") or None,
                symbols=[symbol],
            )
        )
    return items


# ------------------------------------------------------------------ National Bank of Kazakhstan
NBK_RATES_URL = "https://nationalbank.kz/rss/get_rates.cfm"


def parse_nbk_rates(content: bytes) -> dict[str, Decimal]:
    """`<item><title>USD</title><description>451.05</description><quant>1</quant>` → {"USD": 451.05}."""
    parsed = feedparser.parse(content)
    out: dict[str, Decimal] = {}
    for e in parsed.entries:
        code = (e.get("title") or "").strip().upper()
        try:
            value = Decimal((e.get("description") or e.get("summary") or "").strip())
            quant = Decimal(str(e.get("quant") or "1").strip() or "1")
        except InvalidOperation:
            continue
        if code and value > 0 and quant > 0:
            out[code] = value / quant
    return out


async def nbk_usdkzt(client: httpx.AsyncClient, day: dt.date) -> Decimal | None:
    r = await client.get(NBK_RATES_URL, params={"fdate": day.strftime("%d.%m.%Y")})
    if r.status_code != 200:
        raise SourceError(f"nbk HTTP {r.status_code}")
    return parse_nbk_rates(r.content).get("USD")
