"""News storage, ticker linking (vendor tags + RU/KK/EN aliases) and queries."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import News, NewsTicker, Ticker, TickerAlias
from app.schemas.api import NewsOut

MAX_SUMMARY = 600


@dataclass
class NewsItem:
    """Normalised news item produced by every connector."""

    source: str
    lang: str
    published_at: dt.datetime
    title: str
    url: str
    summary: str | None = None
    symbols: list[str] = field(default_factory=list)  # vendor-provided tags (exact listing symbols)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(s: str | None, limit: int | None = None) -> str | None:
    if not s:
        return None
    s = _WS_RE.sub(" ", _TAG_RE.sub(" ", s)).strip()
    if limit and len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s or None


class AliasIndex:
    """Case-sensitive whole-word matching of company names in titles/summaries.

    Case-sensitive on purpose: aliases are proper nouns ("Kaspi", "Халык"), which avoids most false
    positives such as the fruit "apple".
    """

    def __init__(self, pairs: list[tuple[int, str]]) -> None:
        self._patterns = [
            (tid, re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])")) for tid, alias in pairs if alias
        ]

    def match(self, text: str) -> set[int]:
        return {tid for tid, pat in self._patterns if pat.search(text)}


async def build_alias_index(session: AsyncSession) -> AliasIndex:
    rows = (await session.execute(select(TickerAlias.ticker_id, TickerAlias.alias))).all()
    return AliasIndex([(r[0], r[1]) for r in rows])


async def ingest_news(
    session: AsyncSession, items: list[NewsItem], alias_index: AliasIndex | None = None
) -> int:
    """Insert new items (dedup by URL) and link them to tickers. Returns number of new rows."""
    if not items:
        return 0
    sym_rows = (await session.execute(select(Ticker.symbol, Ticker.id))).all()
    sym_to_id = {s.upper(): i for s, i in sym_rows}
    alias_index = alias_index or await build_alias_index(session)
    inserted = 0
    seen: set[str] = set()
    for it in items:
        url = it.url.strip()
        if not url or url in seen or not it.title:
            continue
        seen.add(url)
        stmt = (
            insert(News)
            .values(
                source=it.source[:50],
                lang=it.lang,
                published_at=it.published_at,
                title=clean_text(it.title, 500) or it.title[:500],
                summary=clean_text(it.summary, MAX_SUMMARY),
                url=url[:1000],
            )
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(News.id)
        )
        news_id = (await session.execute(stmt)).scalar_one_or_none()
        if news_id is None:
            continue
        inserted += 1
        links: dict[int, str] = {}
        for s in it.symbols:
            tid = sym_to_id.get(s.upper())
            if tid:
                links[tid] = "vendor"
        for tid in alias_index.match(f"{it.title} {it.summary or ''}"):
            links.setdefault(tid, "alias")
        if links:
            await session.execute(
                insert(NewsTicker)
                .values([{"news_id": news_id, "ticker_id": t, "match_method": m} for t, m in links.items()])
                .on_conflict_do_nothing()
            )
    await session.commit()
    return inserted


async def list_news(
    session: AsyncSession,
    ticker: Ticker | None = None,
    lang: str | None = None,
    market: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[NewsOut]:
    stmt = select(News).order_by(News.published_at.desc()).limit(limit).offset(offset)
    if ticker is not None:
        # all listings of the same issuer share news (e.g. KSPI on NASDAQ and KSPI.KZ on KASE)
        issuer_ids = select(Ticker.id).where(
            (Ticker.issuer == ticker.issuer) if ticker.issuer else (Ticker.id == ticker.id)
        )
        stmt = stmt.where(News.id.in_(select(NewsTicker.news_id).where(NewsTicker.ticker_id.in_(issuer_ids))))
    elif market:
        market_ids = select(Ticker.id).where(Ticker.market == market.upper())
        stmt = stmt.where(News.id.in_(select(NewsTicker.news_id).where(NewsTicker.ticker_id.in_(market_ids))))
    if lang:
        stmt = stmt.where(News.lang == lang)
    news = list((await session.execute(stmt)).scalars().all())
    if not news:
        return []
    links = (
        await session.execute(
            select(NewsTicker.news_id, Ticker.symbol)
            .join(Ticker, Ticker.id == NewsTicker.ticker_id)
            .where(NewsTicker.news_id.in_([n.id for n in news]))
        )
    ).all()
    by_news: dict[int, list[str]] = {}
    for nid, sym in links:
        by_news.setdefault(nid, []).append(sym)
    return [
        NewsOut(
            id=n.id,
            source=n.source,
            lang=n.lang,
            published_at=n.published_at,
            title=n.title,
            summary=n.summary,
            url=n.url,
            sentiment=n.sentiment,
            symbols=sorted(by_news.get(n.id, [])),
        )
        for n in news
    ]
