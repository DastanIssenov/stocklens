"""Test fixtures.

Integration tests need the throw-away Postgres (Timescale + pgvector) and Redis from
`infra/docker-compose.test.yml` (`make test` starts them) or the CI service containers.
External HTTP is always mocked (respx) — tests never call real APIs.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from collections.abc import AsyncIterator
from decimal import Decimal

# --- test settings must be in place before the app (and its cached settings) is imported ---
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+asyncpg://stock:stock@localhost:55432/stock_test"
        ),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:56379/15"),
        "RATE_LIMIT_ENABLED": "false",
        "TRADE_REVIEWER": "mock",
        "PREDICTION_PROVIDER": "mock",
        "LLM_BASE_URL": "",
        "LLM_API_KEY": "",
        "LLM_MODEL": "",
        "JWT_SECRET": "test-secret-key-that-is-long-enough-for-hs256",
        "LOG_LEVEL": "WARNING",
        "DATA_UPDATES_ENABLED": "false",
    }
)

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import redis as redis_mod
from app.core.config import get_settings
from app.db.models import FxRate, PriceDaily, Ticker, TickerAlias
from app.db.session import get_engine, get_sessionmaker

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TABLES = (
    "trade_reviews, trades, positions, portfolios, predictions, fundamentals, news_tickers, news, "
    "fx_rates, macro_observations, prices_daily, ticker_aliases, tickers, users"
)


@pytest.fixture(scope="session", autouse=True)
async def _database() -> AsyncIterator[None]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    def _upgrade(sync_conn) -> None:  # type: ignore[no-untyped-def]
        cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
        cfg.attributes["connection"] = sync_conn
        command.upgrade(cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_upgrade)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    await redis_mod.get_redis().flushdb()
    get_settings.cache_clear()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ------------------------------------------------------------------ data helpers
async def make_ticker(
    session: AsyncSession,
    symbol: str = "AAPL",
    *,
    exchange: str = "NASDAQ",
    market: str = "US",
    currency: str = "USD",
    issuer: str | None = None,
    is_liquid: bool = True,
    aliases: tuple[tuple[str, str], ...] = (),
    data_source: str = "alpaca",
) -> Ticker:
    t = Ticker(
        symbol=symbol,
        local_symbol=symbol.split(".")[0],
        name=f"{symbol} Corp",
        exchange=exchange,
        market=market,
        currency=currency,
        sector="Technology",
        country="US" if market == "US" else "KZ",
        issuer=issuer or symbol,
        data_source=data_source,
        source_symbol=symbol,
        is_liquid=is_liquid,
    )
    t.aliases = [TickerAlias(alias=a, lang=lang) for a, lang in aliases]
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


async def make_prices(
    session: AsyncSession,
    ticker: Ticker,
    days: int = 120,
    start_price: float = 100.0,
    daily_drift: float = 0.001,
    end: dt.date | None = None,
) -> list[PriceDaily]:
    end = end or dt.date.today() - dt.timedelta(days=1)
    rows: list[PriceDaily] = []
    d = end - dt.timedelta(days=int(days * 1.5))
    price = start_price
    i = 0
    while len(rows) < days:
        d += dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        price *= 1 + daily_drift + 0.01 * math.sin(i / 3)
        i += 1
        p = Decimal(str(round(price, 4)))
        rows.append(
            PriceDaily(
                ticker_id=ticker.id,
                date=d,
                open=p,
                high=p * Decimal("1.01"),
                low=p * Decimal("0.99"),
                close=p,
                adj_close=p,
                volume=1_000_000,
                source="test",
            )
        )
    session.add_all(rows)
    await session.commit()
    return rows


async def make_fx(session: AsyncSession, rate: str = "450", source: str = "nbk") -> None:
    session.add(FxRate(pair="USDKZT", date=dt.date.today(), source=source, rate=Decimal(rate)))
    await session.commit()


async def register(
    client: httpx.AsyncClient, email: str = "user@example.com", password: str = "secret123"
) -> dict:
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def auth_header(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}
