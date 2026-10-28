from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.models import User
from app.services.trading import create_portfolio

# Pre-computed hash so that login with an unknown e-mail costs the same time as a wrong password.
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


class EmailTakenError(Exception):
    pass


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    ).scalar_one_or_none()


async def register(
    session: AsyncSession, email: str, password: str, display_name: str | None, locale: str
) -> User:
    if await get_by_email(session, email):
        raise EmailTakenError(email)
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
        display_name=display_name,
        locale=locale,
    )
    session.add(user)
    await session.flush()
    await create_portfolio(session, user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await get_by_email(session, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user
