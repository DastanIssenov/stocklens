"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, meta, news, portfolio, predictions, prices, tickers, trades, ws
from app.api.deps import rate_limit
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.db.session import dispose_engine

log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ws.hub.start()
    log.info("startup", environment=get_settings().environment)
    yield
    await ws.hub.stop()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    app = FastAPI(
        title=s.app_name,
        version="0.1.0",
        description="Educational stock prediction platform (US + Kazakhstan). Not investment advice.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = rid
        if request.url.path != "/health":
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=round((time.perf_counter() - t0) * 1000, 1),
                request_id=rid,
            )
        return response

    app.include_router(health.router)
    api_deps = [Depends(rate_limit("api"))]
    for r in (auth, tickers, prices, news, predictions, portfolio, trades, meta):
        app.include_router(r.router, prefix="/api/v1", dependencies=api_deps)
    app.include_router(ws.router)
    return app


app = create_app()
