"""Shared FastAPI dependencies: DB session, current user, rate limits, ML providers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import hit_rate_limit
from app.core.security import TokenError, decode_token
from app.db.models import User
from app.db.session import get_sessionmaker
from app.ml_interface.base import PredictionProvider, TradeReviewer
from app.ml_interface.factory import get_fallback_reviewer, get_prediction_provider, get_trade_reviewer


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


DB = Annotated[AsyncSession, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    try:
        payload = decode_token(creds.credentials, "access")
        user_id = int(payload["sub"])
    except (TokenError, ValueError, KeyError):
        raise unauthorized from None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def client_id(request: Request) -> str:
    # Behind nginx the real client IP is in X-Forwarded-For (set by our own proxy config).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit_attr: str = "rate_limit_default") -> Callable[[Request], Awaitable[None]]:
    async def _dep(request: Request) -> None:
        s = get_settings()
        if not s.rate_limit_enabled:
            return
        limit = int(getattr(s, limit_attr))
        allowed, reset = await hit_rate_limit(f"{scope}:{client_id(request)}", limit)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(reset)},
            )

    return _dep


def prediction_provider() -> PredictionProvider:
    return get_prediction_provider()


def trade_reviewer() -> TradeReviewer:
    return get_trade_reviewer()


def fallback_reviewer() -> TradeReviewer:
    return get_fallback_reviewer()


Provider = Annotated[PredictionProvider, Depends(prediction_provider)]
Reviewer = Annotated[TradeReviewer, Depends(trade_reviewer)]
FallbackReviewer = Annotated[TradeReviewer, Depends(fallback_reviewer)]
