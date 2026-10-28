"""Small real data updates for the website (Phase 1). The full historical pipeline is in `data_pipeline/`
(GPU phase). Every function is idempotent (upserts) and never raises for a single failing source —
errors are logged and returned in the summary.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.redis import PRICES_CHANNEL, cache_delete_pattern, get_redis
from app.db.models import FxRate, MacroObservation, PriceDaily, Ticker, TickerAlias
from app.ml_interface.base import PredictionProvider
from app.services import news as news_svc
from app.services.market import quote_key
from app.services.predictions import compute_predictions, store_predictions
from app.services.sources import alpaca, feeds, tradernet, yf
from app.services.sources.base import USER_AGENT, PriceBar
from app.services.universe import ALL_LISTINGS, ListingSpec

log = get_logger(__name__)
D6 = Decimal("0.000001")


def http_client(settings: Settings | None = None) -> httpx.AsyncClient:
    s = settings or get_settings()
    return httpx.AsyncClient(timeout=s.http_timeout_s, headers={"User-Agent": USER_AGENT})


def alpaca_client(client: httpx.AsyncClient, s: Settings) -> alpaca.AlpacaClient | None:
    if not s.alpaca_configured:
        return None
    assert s.alpaca_key and s.alpaca_secret
    return alpaca.AlpacaClient(
        s.alpaca_key.get_secret_value(), s.alpaca_secret.get_secret_value(), client, s.alpaca_data_url
    )


# ------------------------------------------------------------------ universe
async def upsert_universe(session: AsyncSession, listings: list[ListingSpec] = ALL_LISTINGS) -> int:
    for spec in listings:
        values = {
            "symbol": spec.symbol,
            "local_symbol": spec.local_symbol,
            "name": spec.name,
            "exchange": spec.exchange,
            "market": spec.market,
            "currency": spec.currency,
            "sector": spec.sector,
            "country": spec.country,
            "issuer": spec.issuer,
            "data_source": spec.data_source,
            "source_symbol": spec.source_symbol,
            "is_liquid": spec.is_liquid,
            "is_active": True,
        }
        ins = insert(Ticker).values(**values)
        upsert = ins.on_conflict_do_update(
            index_elements=["symbol"], set_={k: ins.excluded[k] for k in values if k != "symbol"}
        ).returning(Ticker.id)
        tid = (await session.execute(upsert)).scalar_one()
        await session.execute(delete(TickerAlias).where(TickerAlias.ticker_id == tid))
        if spec.aliases:
            await session.execute(
                insert(TickerAlias)
                .values([{"ticker_id": tid, "alias": a, "lang": lang} for a, lang in spec.aliases])
                .on_conflict_do_nothing()
            )
    await session.commit()
    return len(listings)


# ------------------------------------------------------------------ prices
async def upsert_bars(session: AsyncSession, ticker_id: int, bars: list[PriceBar], source: str) -> int:
    rows = [
        {
            "ticker_id": ticker_id,
            "date": b.date,
            "open": Decimal(str(b.open)).quantize(D6),
            "high": Decimal(str(b.high)).quantize(D6),
            "low": Decimal(str(b.low)).quantize(D6),
            "close": Decimal(str(b.close)).quantize(D6),
            "adj_close": None if b.adj_close is None else Decimal(str(b.adj_close)).quantize(D6),
            "volume": b.volume,
            "source": source,
        }
        for b in bars
        if b.is_valid()
    ]
    skipped = len(bars) - len(rows)
    if skipped:
        log.warning("bars_skipped_invalid", ticker_id=ticker_id, skipped=skipped)
    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = insert(PriceDaily).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker_id", "date"],
            set_={
                c: stmt.excluded[c] for c in ("open", "high", "low", "close", "adj_close", "volume", "source")
            },
        )
        await session.execute(stmt)
    await session.commit()
    return len(rows)


async def update_prices(
    session: AsyncSession,
    start: dt.date,
    end: dt.date | None = None,
    symbols: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    s = get_settings()
    stmt = select(Ticker).where(Ticker.is_active.is_(True))
    if symbols:
        stmt = stmt.where(Ticker.symbol.in_(symbols))
    tickers = list((await session.execute(stmt)).scalars().all())
    groups: dict[str, list[Ticker]] = defaultdict(list)
    for t in tickers:
        groups[t.data_source].append(t)

    summary: dict[str, Any] = {"rows": {}, "errors": []}
    own_client = client is None
    client = client or http_client(s)
    try:
        for source, group in groups.items():
            by_src_symbol = {t.source_symbol: t for t in group}
            fetched: dict[str, list[PriceBar]] = {}
            used = source
            try:
                if source == "alpaca":
                    ac = alpaca_client(client, s)
                    if ac is None:  # no keys → yfinance fallback keeps the site usable
                        used = "yfinance"
                        fetched = await yf.daily_bars(list(by_src_symbol), start, end)
                    else:
                        fetched = await ac.daily_bars(list(by_src_symbol), start, end)
                elif source == "tradernet":
                    fetched = await tradernet.daily_bars(
                        client,
                        list(by_src_symbol),
                        start,
                        end,
                        url=s.tradernet_url,
                        min_interval_s=s.tradernet_min_interval_s,
                    )
                elif source == "yfinance":
                    fetched = await yf.daily_bars(list(by_src_symbol), start, end)
                else:
                    summary["errors"].append(f"unknown source {source}")
                    continue
            except Exception as e:
                log.warning("price_source_failed", source=source, error=str(e)[:200])
                summary["errors"].append(f"{source}: {type(e).__name__} {str(e)[:200]}")
                continue
            for src_sym, bars in fetched.items():
                listing = by_src_symbol.get(src_sym)
                if listing is None:
                    continue
                summary["rows"][listing.symbol] = await upsert_bars(session, listing.id, bars, used)
                await cache_delete_pattern(f"prices:{listing.symbol}:*")
        await cache_delete_pattern("overview:*")
    finally:
        if own_client:
            await client.aclose()
    log.info("prices_updated", tickers=len(summary["rows"]), errors=len(summary["errors"]))
    return summary


# ------------------------------------------------------------------ FX & macro
async def upsert_fx(session: AsyncSession, rows: list[tuple[dt.date, Decimal]], source: str) -> int:
    if not rows:
        return 0
    stmt = insert(FxRate).values(
        [{"pair": "USDKZT", "date": d, "source": source, "rate": r.quantize(D6)} for d, r in rows]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["pair", "date", "source"], set_={"rate": stmt.excluded.rate}
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def upsert_macro(
    session: AsyncSession, series_id: str, rows: list[tuple[dt.date, float]], source: str
) -> int:
    if not rows:
        return 0
    stmt = insert(MacroObservation).values(
        [
            {"series_id": series_id, "date": d, "source": source, "value": Decimal(str(v)).quantize(D6)}
            for d, v in rows
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["series_id", "date", "source"], set_={"value": stmt.excluded.value}
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def update_fx_and_macro(
    session: AsyncSession, history_days: int = 14, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    summary: dict[str, Any] = {"errors": []}
    own_client = client is None
    client = client or http_client()
    start = dt.date.today() - dt.timedelta(days=history_days)
    try:
        # official NBK rate: today + a few recent days (one small request each)
        nbk_rows: list[tuple[dt.date, Decimal]] = []
        for i in range(min(history_days, 7)):
            day = dt.date.today() - dt.timedelta(days=i)
            try:
                rate = await feeds.nbk_usdkzt(client, day)
                if rate:
                    nbk_rows.append((day, rate))
            except Exception as e:
                summary["errors"].append(f"nbk {day}: {str(e)[:100]}")
                break
        summary["nbk"] = await upsert_fx(session, nbk_rows, "nbk")
        try:
            kzt = await yf.closes("KZT=X", start)
            summary["usdkzt_market"] = await upsert_fx(
                session, [(d, Decimal(str(v))) for d, v in kzt], "yfinance"
            )
        except Exception as e:
            summary["errors"].append(f"yfinance KZT=X: {str(e)[:100]}")
        try:
            brent = await yf.closes("BZ=F", start)
            summary["brent"] = await upsert_macro(session, "BRENT", brent, "yfinance")
        except Exception as e:
            summary["errors"].append(f"yfinance BZ=F: {str(e)[:100]}")
        await cache_delete_pattern("overview:*")
    finally:
        if own_client:
            await client.aclose()
    log.info(
        "fx_macro_updated",
        **{k: v for k, v in summary.items() if k != "errors"},
        errors=len(summary["errors"]),
    )
    return summary


# ------------------------------------------------------------------ news
async def update_news(
    session: AsyncSession, client: httpx.AsyncClient | None = None, finnhub_symbols: int = 5
) -> dict[str, Any]:
    s = get_settings()
    summary: dict[str, Any] = {"inserted": {}, "errors": []}
    own_client = client is None
    client = client or http_client(s)
    alias_index = await news_svc.build_alias_index(session)
    try:
        alpaca_syms = list(
            (
                await session.execute(
                    select(Ticker.source_symbol).where(
                        Ticker.data_source == "alpaca", Ticker.is_active.is_(True)
                    )
                )
            ).scalars()
        )
        ac = alpaca_client(client, s)
        if ac and alpaca_syms:
            try:
                items = await ac.news(alpaca_syms, limit=50)
                summary["inserted"]["alpaca"] = await news_svc.ingest_news(session, items, alias_index)
            except Exception as e:
                summary["errors"].append(f"alpaca news: {str(e)[:150]}")
        if s.finnhub_key and alpaca_syms:
            token = s.finnhub_key.get_secret_value()
            today = dt.date.today()
            n = 0
            for sym in alpaca_syms[:finnhub_symbols]:  # free plan: 60 req/min — keep it small
                try:
                    items = await feeds.finnhub_company_news(
                        client, token, sym, today - dt.timedelta(days=3), today
                    )
                    n += await news_svc.ingest_news(session, items[:20], alias_index)
                except Exception as e:
                    summary["errors"].append(f"finnhub {sym}: {str(e)[:100]}")
            summary["inserted"]["finnhub"] = n
        for feed in feeds.RSS_FEEDS:
            try:
                items = await feeds.fetch_feed(client, feed)
                summary["inserted"][feed.name] = await news_svc.ingest_news(session, items, alias_index)
            except Exception as e:
                summary["errors"].append(f"rss {feed.name}: {type(e).__name__} {str(e)[:100]}")
        await cache_delete_pattern("news:*")
    finally:
        if own_client:
            await client.aclose()
    log.info("news_updated", inserted=sum(summary["inserted"].values()), errors=len(summary["errors"]))
    return summary


# ------------------------------------------------------------------ live quotes
async def refresh_live_quotes(session: AsyncSession, client: httpx.AsyncClient | None = None) -> int:
    """US quotes from Alpaca IEX snapshots → Redis (`quote:SYMBOL`, TTL) + pub/sub for the WebSocket."""
    s = get_settings()
    own_client = client is None
    client = client or http_client(s)
    try:
        ac = alpaca_client(client, s)
        if ac is None:
            return 0
        rows = (
            await session.execute(
                select(Ticker.symbol, Ticker.source_symbol).where(
                    Ticker.data_source == "alpaca", Ticker.is_active.is_(True)
                )
            )
        ).all()
        if not rows:
            return 0
        src_to_sym = {src: sym for sym, src in rows}
        snaps = await ac.snapshots(list(src_to_sym))
        r = get_redis()
        n = 0
        for src, q in snaps.items():
            sym = src_to_sym.get(src)
            if not sym:
                continue
            q = {**q, "symbol": sym}
            if q["prev_close"]:
                q["change_pct"] = q["price"] / q["prev_close"] - 1
            payload = json.dumps(q)
            await r.set(quote_key(sym), payload, ex=s.cache_ttl_quote * 3)
            await r.publish(PRICES_CHANNEL, payload)
            n += 1
        return n
    finally:
        if own_client:
            await client.aclose()


# ------------------------------------------------------------------ predictions
async def generate_predictions(session: AsyncSession, provider: PredictionProvider) -> int:
    tickers = list((await session.execute(select(Ticker).where(Ticker.is_active.is_(True)))).scalars().all())
    n = 0
    for t in tickers:
        results = await compute_predictions(session, t, provider)
        if results:
            await store_predictions(session, t.id, results)
            n += 1
    await session.commit()
    await cache_delete_pattern("pred:*")
    return n
