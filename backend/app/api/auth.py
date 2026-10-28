from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DB, CurrentUser, rate_limit
from app.core.security import TokenError, create_token, decode_token
from app.db.models import User
from app.schemas.api import AuthOut, LoginIn, RefreshIn, RegisterIn, TokenPair, UserOut
from app.services import users

router = APIRouter(
    prefix="/auth", tags=["auth"], dependencies=[Depends(rate_limit("auth", "rate_limit_auth"))]
)


def _tokens(user_id: int) -> TokenPair:
    return TokenPair(
        access_token=create_token(user_id, "access"), refresh_token=create_token(user_id, "refresh")
    )


@router.post("/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, db: DB) -> AuthOut:
    try:
        user = await users.register(db, body.email, body.password, body.display_name, body.locale)
    except users.EmailTakenError:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from None
    return AuthOut(user=UserOut.model_validate(user), tokens=_tokens(user.id))


@router.post("/login", response_model=AuthOut)
async def login(body: LoginIn, db: DB) -> AuthOut:
    user = await users.authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    return AuthOut(user=UserOut.model_validate(user), tokens=_tokens(user.id))


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, db: DB) -> TokenPair:
    try:
        payload = decode_token(body.refresh_token, "refresh")
        user = await db.get(User, int(payload["sub"]))
    except (TokenError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    return _tokens(user.id)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
