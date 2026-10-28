from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, CurrentUser, FallbackReviewer, Provider, Reviewer, rate_limit
from app.core.redis import cache_delete_pattern
from app.schemas.api import ReviewOut, TradeIn, TradeOut
from app.services import market, trading

router = APIRouter(prefix="/trades", tags=["trades"])


@router.post(
    "",
    response_model=TradeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("trades", "rate_limit_trades"))],
)
async def create_trade(
    body: TradeIn,
    db: DB,
    user: CurrentUser,
    provider: Provider,
    reviewer: Reviewer,
    fallback: FallbackReviewer,
) -> TradeOut:
    try:
        trade = await trading.execute_trade(db, user, body.symbol, body.side, body.quantity)
    except market.NotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except trading.TradingError as e:
        raise HTTPException(400, str(e)) from None
    review = await trading.review_trade(db, user, trade, reviewer, fallback, provider)
    await cache_delete_pattern(f"pred:{trade.ticker.symbol}")
    return trading.trade_out(trade, review)


@router.get("", response_model=list[TradeOut])
async def list_trades(
    db: DB, user: CurrentUser, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
) -> list[TradeOut]:
    return [trading.trade_out(t) for t in await trading.list_trades(db, user, limit, offset)]


@router.get("/{trade_id}", response_model=TradeOut)
async def get_trade(trade_id: int, db: DB, user: CurrentUser) -> TradeOut:
    t = await trading.get_trade(db, user, trade_id)
    if t is None:
        raise HTTPException(404, "trade not found")
    return trading.trade_out(t)


@router.post(
    "/{trade_id}/review",
    response_model=ReviewOut,
    dependencies=[Depends(rate_limit("trades", "rate_limit_trades"))],
)
async def rerun_review(
    trade_id: int,
    db: DB,
    user: CurrentUser,
    provider: Provider,
    reviewer: Reviewer,
    fallback: FallbackReviewer,
) -> ReviewOut:
    t = await trading.get_trade(db, user, trade_id)
    if t is None:
        raise HTTPException(404, "trade not found")
    review = await trading.review_trade(db, user, t, reviewer, fallback, provider)
    out = trading.review_out(review)
    assert out is not None
    return out
