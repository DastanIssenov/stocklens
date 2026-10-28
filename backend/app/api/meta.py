from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Provider, Reviewer
from app.schemas.api import MetaOut

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaOut)
async def meta(provider: Provider, reviewer: Reviewer) -> MetaOut:
    return MetaOut(
        prediction_provider=provider.name,
        predictions_are_demo=provider.is_demo,
        trade_reviewer=reviewer.name,
        trade_reviewer_model=reviewer.model,
    )
