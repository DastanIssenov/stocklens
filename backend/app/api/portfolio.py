from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser
from app.schemas.api import PortfolioOut
from app.services import trading

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioOut)
async def get_portfolio(db: DB, user: CurrentUser) -> PortfolioOut:
    return await trading.portfolio_summary(db, user)


@router.post("/reset", response_model=PortfolioOut, status_code=status.HTTP_200_OK)
async def reset(db: DB, user: CurrentUser) -> PortfolioOut:
    await trading.reset_portfolio(db, user)
    return await trading.portfolio_summary(db, user)
