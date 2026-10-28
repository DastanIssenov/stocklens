from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DB
from app.schemas.api import TickerDetail, TickerOut
from app.services import market

router = APIRouter(prefix="/tickers", tags=["tickers"])


@router.get("", response_model=list[TickerOut])
async def list_tickers(
    db: DB,
    market_: Literal["US", "KZ"] | None = Query(default=None, alias="market"),
    exchange: str | None = None,
    q: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[TickerOut]:
    rows = await market.list_tickers(db, market_, exchange, q, limit, offset)
    return [TickerOut.model_validate(t) for t in rows]


@router.get("/search", response_model=list[TickerOut])
async def search(
    db: DB, q: str = Query(min_length=1, max_length=50), limit: int = Query(10, ge=1, le=25)
) -> list[TickerOut]:
    return [TickerOut.model_validate(t) for t in await market.search_tickers(db, q, limit)]


@router.get("/{symbol}", response_model=TickerDetail)
async def get_ticker(symbol: str, db: DB) -> TickerDetail:
    try:
        t = await market.get_ticker(db, symbol)
    except market.NotFoundError as e:
        raise HTTPException(404, str(e)) from None
    detail = TickerDetail.model_validate(t)
    detail.quote = await market.latest_quote(db, t)
    detail.other_listings = [TickerOut.model_validate(o) for o in await market.other_listings(db, t)]
    return detail
