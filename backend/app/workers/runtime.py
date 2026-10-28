"""Run async service code from sync contexts (Celery tasks, CLI) with a fresh engine per run."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import close_redis, set_redis
from app.db.session import configure_engine, get_sessionmaker, make_engine


def run_with_session[T](fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def runner() -> T:
        engine = make_engine(null_pool=True)  # no pooled connections shared across event loops
        configure_engine(engine)
        set_redis(None)
        try:
            async with get_sessionmaker()() as session:
                return await fn(session)
        finally:
            await close_redis()
            await engine.dispose()
            configure_engine(None)

    return asyncio.run(runner())
