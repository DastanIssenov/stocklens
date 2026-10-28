from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DB
from app.core.config import get_settings
from app.core.redis import cached
from app.schemas.api import NewsOut
from app.services import market, news

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=list[NewsOut])
async def list_news(
    db: DB,
    symbol: str | None = Query(default=None, max_length=20),
    lang: str | None = Query(default=None, pattern="^(en|ru|kk)$"),
    market_: str | None = Query(default=None, alias="market", pattern="^(US|KZ)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[NewsOut]:
    ticker = None
    if symbol:
        try:
            ticker = await market.get_ticker(db, symbol)
        except market.NotFoundError as e:
            raise HTTPException(404, str(e)) from None

    async def produce() -> list[dict]:
        rows = await news.list_news(db, ticker, lang, market_, limit, offset)
        return [r.model_dump(mode="json") for r in rows]

    key = f"news:{ticker.symbol if ticker else '-'}:{lang}:{market_}:{limit}:{offset}"
    data = await cached(key, get_settings().cache_ttl_news, produce)
    return [NewsOut.model_validate(d) for d in data]
