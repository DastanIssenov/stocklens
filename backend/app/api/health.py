from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.redis import get_redis
from app.db.session import get_sessionmaker

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response) -> dict[str, str]:
    result = {"status": "ok", "db": "ok", "redis": "ok"}
    try:
        async with get_sessionmaker()() as s:
            await s.execute(text("SELECT 1"))
    except Exception:
        result["db"] = "error"
    try:
        await get_redis().ping()
    except Exception:
        result["redis"] = "error"
    if result["db"] != "ok":
        result["status"] = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif result["redis"] != "ok":
        result["status"] = "degraded"
    return result
