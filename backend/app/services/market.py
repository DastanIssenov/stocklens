"""Tickers, prices, quotes, FX and the market overview."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import cache_get_json, cached, get_redis
from app.db.models import MacroObservation, PriceDaily, Ticker, TickerAlias
from app.schemas.api import Bar, FxOut, MarketOverview, OverviewRow, Quote


class NotFoundError(Exception):
    pass


# ------------------------------------------------------------------ tickers
async def get_ticker(session: AsyncSession, symbol: str) -> Ticker:
    t = (
        await session.execute(select(Ticker).where(func.upper(Ticker.symbol) == symbol.strip().upper()))
    ).scalar_one_or_none()
    if t is None:
        raise NotFoundError(f"ticker {symbol!r} not found")
    return t


async def list_tickers(
    session: AsyncSession,
    market: str | None = None,
    exchange: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Ticker]:
    stmt = select(Ticker).where(Ticker.is_active.is_(True))
    if market:
        stmt = stmt.where(Ticker.market == market.upper())
    if exchange:
        stmt = stmt.where(Ticker.exchange == exchange.upper())
    if q:
        stmt = stmt.where(_search_clause(q))
    stmt = stmt.order_by(Ticker.market, Ticker.exchange, Ticker.symbol).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


def _search_clause(q: str) -> Any:
    like = f"%{q.strip()}%"
    alias_match = select(TickerAlias.ticker_id).where(TickerAlias.alias.ilike(like))
    return or_(Ticker.symbol.ilike(like), Ticker.name.ilike(like), Ticker.id.in_(alias_match))


async def search_tickers(session: AsyncSession, q: str, limit: int = 10) -> list[Ticker]:
    qn = q.strip()
    if not qn:
        return []
    exact_first = func.upper(Ticker.symbol) != qn.upper()
    stmt = (
        select(Ticker)
        .where(Ticker.is_active.is_(True), _search_clause(qn))
        .order_by(exact_first, Ticker.symbol)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def other_listings(session: AsyncSession, ticker: Ticker) -> list[Ticker]:
    if not ticker.issuer:
        return []
    stmt = (
        select(Ticker).where(Ticker.issuer == ticker.issuer, Ticker.id != ticker.id).order_by(Ticker.symbol)
    )
    return list((await session.execute(stmt)).scalars().all())


# ------------------------------------------------------------------ prices
async def get_bars(
    session: AsyncSession, ticker: Ticker, start: dt.date | None = None, end: dt.date | None = None
) -> list[Bar]:
    stmt = select(PriceDaily).where(PriceDaily.ticker_id == ticker.id)
    if start:
        stmt = stmt.where(PriceDaily.date >= start)
    if end:
        stmt = stmt.where(PriceDaily.date <= end)
    rows = (await session.execute(stmt.order_by(PriceDaily.date))).scalars().all()
    return [
        Bar(
            date=r.date,
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            volume=int(r.volume),
        )
        for r in rows
    ]


async def get_bars_cached(
    session: AsyncSession, ticker: Ticker, start: dt.date | None, end: dt.date | None
) -> list[dict[str, Any]]:
    key = f"prices:{ticker.symbol}:{start}:{end}"

    async def produce() -> list[dict[str, Any]]:
        return [b.model_dump(mode="json") for b in await get_bars(session, ticker, start, end)]

    result: list[dict[str, Any]] = await cached(key, get_settings().cache_ttl_prices, produce)
    return result


@dataclass
class Series:
    dates: list[dt.date]
    closes: list[float]
    volumes: list[float]


async def recent_series(
    session: AsyncSession, ticker_id: int, n: int = 300, as_of: dt.date | None = None
) -> Series:
    stmt = select(PriceDaily.date, PriceDaily.close, PriceDaily.volume).where(
        PriceDaily.ticker_id == ticker_id
    )
    if as_of:
        stmt = stmt.where(PriceDaily.date <= as_of)
    rows = (await session.execute(stmt.order_by(PriceDaily.date.desc()).limit(n))).all()
    rows = list(reversed(rows))
    return Series([r[0] for r in rows], [float(r[1]) for r in rows], [float(r[2]) for r in rows])


def quote_key(symbol: str) -> str:
    return f"quote:{symbol}"


async def latest_quote(session: AsyncSession, ticker: Ticker) -> Quote | None:
    """Live quote from Redis (set by the quote task) if fresh, else the last daily close."""
    live = await cache_get_json(quote_key(ticker.symbol))
    if live and live.get("price"):
        prev = live.get("prev_close")
        price = float(live["price"])
        return Quote(
            symbol=ticker.symbol,
            price=price,
            prev_close=prev,
            change=None if prev is None else price - prev,
            change_pct=None if not prev else price / prev - 1,
            currency=ticker.currency,
            as_of=dt.datetime.fromisoformat(live["ts"]),
            source=live.get("source", "live"),
            is_live=True,
        )
    rows = (
        await session.execute(
            select(PriceDaily.date, PriceDaily.close, PriceDaily.source)
            .where(PriceDaily.ticker_id == ticker.id)
            .order_by(PriceDaily.date.desc())
            .limit(2)
        )
    ).all()
    if not rows:
        return None
    last_date, last_close, source = rows[0]
    prev_close = float(rows[1][1]) if len(rows) > 1 else None
    price = float(last_close)
    return Quote(
        symbol=ticker.symbol,
        price=price,
        prev_close=prev_close,
        change=None if prev_close is None else price - prev_close,
        change_pct=None if not prev_close else price / prev_close - 1,
        currency=ticker.currency,
        as_of=last_date,
        source=f"{source}:daily_close",
    )


# ------------------------------------------------------------------ fx & macro
async def usdkzt(session: AsyncSession) -> FxOut:
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT ON (source) source, date, rate FROM fx_rates "
                "WHERE pair = 'USDKZT' ORDER BY source, date DESC"
            )
        )
    ).all()
    by_src = {r[0]: (r[1], float(r[2])) for r in rows}
    official = by_src.get("nbk")
    market = by_src.get("yfinance")
    used = (official or market or (None, float(get_settings().fallback_usdkzt)))[1]
    return FxOut(
        official=official[1] if official else None,
        official_date=official[0] if official else None,
        market=market[1] if market else None,
        market_date=market[0] if market else None,
        rate_used=used,
    )


async def usdkzt_rate(session: AsyncSession) -> Decimal:
    return Decimal(str((await usdkzt(session)).rate_used))


async def latest_macro(session: AsyncSession, series_id: str) -> tuple[dt.date, float] | None:
    row = (
        await session.execute(
            select(MacroObservation.date, MacroObservation.value)
            .where(MacroObservation.series_id == series_id)
            .order_by(MacroObservation.date.desc())
            .limit(1)
        )
    ).first()
    return (row[0], float(row[1])) if row else None


# ------------------------------------------------------------------ overview
async def market_overview(session: AsyncSession, market: str, spark_days: int = 30) -> MarketOverview:
    tickers = await list_tickers(session, market=market, limit=500)
    ids = [t.id for t in tickers]
    since = dt.date.today() - dt.timedelta(days=spark_days * 3)
    rows = (
        await session.execute(
            text(
                "SELECT ticker_id, date, close FROM ("
                "  SELECT ticker_id, date, close,"
                "         row_number() OVER (PARTITION BY ticker_id ORDER BY date DESC) rn"
                "  FROM prices_daily WHERE ticker_id = ANY(:ids) AND date >= :since"
                ") t WHERE rn <= :n ORDER BY ticker_id, date"
            ),
            {"ids": ids, "since": since, "n": spark_days},
        )
    ).all()
    series: dict[int, list[tuple[dt.date, float]]] = {}
    for tid, d, c in rows:
        series.setdefault(tid, []).append((d, float(c)))

    live: dict[str, Any] = {}
    if tickers:
        try:
            vals = await get_redis().mget([quote_key(t.symbol) for t in tickers])
            live = {t.symbol: json.loads(v) for t, v in zip(tickers, vals, strict=True) if v}
        except Exception:
            live = {}

    out: list[OverviewRow] = []
    for t in tickers:
        s = series.get(t.id, [])
        closes = [c for _, c in s]
        price = closes[-1] if closes else None
        prev = closes[-2] if len(closes) > 1 else None
        as_of = s[-1][0] if s else None
        if t.symbol in live:
            price = float(live[t.symbol]["price"])
            prev = live[t.symbol].get("prev_close") or prev
        out.append(
            OverviewRow(
                symbol=t.symbol,
                name=t.name,
                exchange=t.exchange,
                currency=t.currency,
                sector=t.sector,
                is_liquid=t.is_liquid,
                price=price,
                change_pct=(price / prev - 1) if price and prev else None,
                as_of=as_of,
                sparkline=closes,
            )
        )
    with_change = [r for r in out if r.change_pct is not None]
    gainers = sorted(
        (r for r in with_change if (r.change_pct or 0) > 0), key=lambda r: r.change_pct or 0, reverse=True
    )
    losers = sorted((r for r in with_change if (r.change_pct or 0) < 0), key=lambda r: r.change_pct or 0)
    brent = await latest_macro(session, "BRENT")
    return MarketOverview(
        market=market,
        rows=out,
        gainers=gainers[:5],
        losers=losers[:5],
        fx=await usdkzt(session),
        brent=brent[1] if brent else None,
        brent_date=brent[0] if brent else None,
    )
