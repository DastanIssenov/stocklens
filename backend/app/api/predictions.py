from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DB, Provider
from app.core.config import get_settings
from app.core.redis import cached
from app.schemas.api import PredictionsOut
from app.services import market
from app.services.predictions import get_predictions

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("/{symbol}", response_model=PredictionsOut)
async def predictions(symbol: str, db: DB, provider: Provider) -> PredictionsOut:
    try:
        t = await market.get_ticker(db, symbol)
    except market.NotFoundError as e:
        raise HTTPException(404, str(e)) from None

    async def produce() -> dict:
        return (await get_predictions(db, t, provider)).model_dump(mode="json")

    data = await cached(f"pred:{t.symbol}", get_settings().cache_ttl_predictions, produce)
    return PredictionsOut.model_validate(data)
