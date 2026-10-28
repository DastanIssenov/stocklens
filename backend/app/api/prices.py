from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DB
from app.core.config import get_settings
from app.core.redis import cached
from app.schemas.api import Bar, FxOut, MarketOverview, PriceHistory, Quote
from app.services import market

router = APIRouter(tags=["prices"])


@router.get("/prices/{symbol}", response_model=PriceHistory)
async def price_history(
    symbol: str,
    db: DB,
    start: dt.date | None = Query(default=None, description="inclusive, default = 2 years ago"),
    end: dt.date | None = None,
) -> PriceHistory:
    try:
        t = await market.get_ticker(db, symbol)
    except market.NotFoundError as e:
        raise HTTPException(404, str(e)) from None
    if start is None:
        start = dt.date.today() - dt.timedelta(days=730)
    if end is not None and end < start:
        raise HTTPException(422, "end must be >= start")
    bars = await market.get_bars_cached(db, t, start, end)
    return PriceHistory(symbol=t.symbol, currency=t.currency, bars=[Bar(**b) for b in bars])


@router.get("/prices/{symbol}/latest", response_model=Quote)
async def latest(symbol: str, db: DB) -> Quote:
    try:
        t = await market.get_ticker(db, symbol)
    except market.NotFoundError as e:
        raise HTTPException(404, str(e)) from None
    q = await market.latest_quote(db, t)
    if q is None:
        raise HTTPException(404, f"no prices for {t.symbol} yet")
    return q


@router.get("/market/overview", response_model=MarketOverview)
async def overview(
    db: DB, market_: str = Query(default="US", alias="market", pattern="^(US|KZ)$")
) -> MarketOverview:
    async def produce() -> dict:
        return (await market.market_overview(db, market_)).model_dump(mode="json")

    data = await cached(f"overview:{market_}", get_settings().cache_ttl_overview, produce)
    return MarketOverview.model_validate(data)


@router.get("/fx/latest", response_model=FxOut)
async def fx_latest(db: DB) -> FxOut:
    return await market.usdkzt(db)
