"""Redis client (asyncio), JSON cache helpers and a fixed-window rate limiter."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

PRICES_CHANNEL = "prices"

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def set_redis(client: aioredis.Redis | None) -> None:
    """Used by tests and Celery tasks (fresh event loop per task)."""
    global _client
    _client = client


# ---------------------------------------------------------------- cache
async def cache_get_json(key: str) -> Any | None:
    try:
        raw = await get_redis().get(key)
    except Exception as e:  # cache must never break the request
        log.warning("cache_get_failed", key=key, error=str(e))
        return None
    return None if raw is None else json.loads(raw)


async def cache_set_json(key: str, value: Any, ttl: int) -> None:
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as e:
        log.warning("cache_set_failed", key=key, error=str(e))


async def cached[T](key: str, ttl: int, producer: Callable[[], Awaitable[T]]) -> T | Any:
    hit = await cache_get_json(key)
    if hit is not None:
        return hit
    value = await producer()
    await cache_set_json(key, value, ttl)
    return value


async def cache_delete_pattern(pattern: str) -> int:
    r = get_redis()
    n = 0
    try:
        async for key in r.scan_iter(match=pattern, count=500):
            n += await r.delete(key)
    except Exception as e:
        log.warning("cache_delete_failed", pattern=pattern, error=str(e))
    return n


# ---------------------------------------------------------------- rate limit
async def hit_rate_limit(bucket: str, limit: int, window_s: int = 60) -> tuple[bool, int]:
    """Fixed-window counter. Returns (allowed, seconds_until_reset)."""
    window = int(time.time() // window_s)
    key = f"rl:{bucket}:{window}"
    r = get_redis()
    try:
        async with r.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s + 1)
            count, _ = await pipe.execute()
    except Exception as e:  # fail open: an unavailable Redis must not take the API down
        log.warning("rate_limit_redis_error", error=str(e))
        return True, 0
    reset = window_s - int(time.time() % window_s)
    return int(count) <= limit, reset
