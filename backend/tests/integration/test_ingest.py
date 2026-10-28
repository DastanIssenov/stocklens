import datetime as dt
import json

import httpx
import respx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.models import FxRate, MacroObservation, News, PriceDaily, Ticker, TickerAlias
from app.ml_interface.mock import MockPredictionProvider
from app.services import ingest
from app.services.sources import feeds, yf
from app.services.sources.base import PriceBar
from app.services.universe import ALL_LISTINGS, KZ_LISTINGS, US_LISTINGS
from tests.conftest import make_prices, make_ticker

DATA = "https://data.alpaca.markets"


def test_universe_definition_is_consistent() -> None:
    symbols = [x.symbol for x in ALL_LISTINGS]
    assert len(symbols) == len(set(symbols))
    assert len(US_LISTINGS) == 20
    kase = [x for x in KZ_LISTINGS if x.exchange == "KASE"]
    assert {x.local_symbol for x in kase if x.is_liquid} == {
        "AIRA",
        "CCBN",
        "HSBK",
        "KCEL",
        "KEGC",
        "KMGZ",
        "KSPI",
        "KZAP",
        "KZTK",
        "KZTO",
    }
    for x in ALL_LISTINGS:
        assert x.currency == ("KZT" if x.exchange in ("KASE", "AIX") else "USD")
        assert x.data_source in {"alpaca", "tradernet", "yfinance"}


async def test_upsert_universe_is_idempotent(session) -> None:  # type: ignore[no-untyped-def]
    await ingest.upsert_universe(session)
    await ingest.upsert_universe(session)
    assert await session.scalar(select(func.count()).select_from(Ticker)) == len(ALL_LISTINGS)
    n_alias = sum(len(x.aliases) for x in ALL_LISTINGS)
    assert await session.scalar(select(func.count()).select_from(TickerAlias)) == n_alias


@respx.mock
async def test_update_prices_routes_sources(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    s = get_settings()
    monkeypatch.setattr(s, "alpaca_key", __import__("pydantic").SecretStr("k"))
    monkeypatch.setattr(s, "alpaca_secret", __import__("pydantic").SecretStr("s"))
    monkeypatch.setattr(s, "tradernet_min_interval_s", 0.0)
    await make_ticker(session, "AAPL")
    await make_ticker(
        session, "HSBK.KZ", exchange="KASE", market="KZ", currency="KZT", data_source="tradernet"
    )
    await make_ticker(session, "KAP.IL", exchange="LSE", market="KZ", data_source="yfinance")

    bar = {"t": "2026-10-27T04:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100}
    respx.get(f"{DATA}/v2/stocks/bars").respond(200, json={"bars": {"AAPL": [bar]}})
    respx.get("https://tradernet.com/api/").respond(
        200,
        json={
            "hloc": {"HSBK.KZ": [[380, 370, 372, 375]]},
            "vl": {"HSBK.KZ": [5]},
            "xSeries": {"HSBK.KZ": [1793048400]},
        },
    )

    async def fake_yf(symbols, start, end=None):  # type: ignore[no-untyped-def]
        return {
            "KAP.IL": [
                PriceBar(dt.date(2026, 10, 27), 60, 61, 59, 60.5, 1000, 60.5),
                PriceBar(dt.date(2026, 10, 28), 0, 0, 0, 0, 0),
            ]
        }  # invalid row is skipped

    monkeypatch.setattr(yf, "daily_bars", fake_yf)
    out = await ingest.update_prices(session, dt.date(2026, 10, 1))
    assert out == {"rows": {"AAPL": 1, "HSBK.KZ": 1, "KAP.IL": 1}, "errors": []}
    rows = (await session.execute(select(PriceDaily.source, PriceDaily.close))).all()
    assert {r[0] for r in rows} == {"alpaca", "tradernet", "yfinance"}
    # idempotent
    out2 = await ingest.update_prices(session, dt.date(2026, 10, 1))
    assert out2["rows"]["AAPL"] == 1
    assert await session.scalar(select(func.count()).select_from(PriceDaily)) == 3


async def test_update_prices_without_alpaca_keys_uses_yfinance(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    s = get_settings()
    monkeypatch.setattr(s, "alpaca_key", None)
    await make_ticker(session, "MSFT")
    seen: list[list[str]] = []

    async def fake_yf(symbols, start, end=None):  # type: ignore[no-untyped-def]
        seen.append(symbols)
        return {"MSFT": [PriceBar(dt.date(2026, 10, 27), 1, 2, 0.5, 1.5, 10)]}

    monkeypatch.setattr(yf, "daily_bars", fake_yf)
    out = await ingest.update_prices(session, dt.date(2026, 10, 1))
    assert out["rows"] == {"MSFT": 1} and seen == [["MSFT"]]
    assert (await session.execute(select(PriceDaily.source))).scalar_one() == "yfinance"


async def test_update_prices_records_source_errors(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "alpaca_key", None)
    await make_ticker(session, "MSFT")

    async def broken(*a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("down")

    monkeypatch.setattr(yf, "daily_bars", broken)
    out = await ingest.update_prices(session, dt.date(2026, 10, 1))
    assert out["rows"] == {} and "RuntimeError down" in out["errors"][0]


@respx.mock
async def test_update_fx_and_macro(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tests.unit.test_sources import NBK

    respx.get(feeds.NBK_RATES_URL).respond(200, content=NBK)

    async def fake_closes(symbol, start):  # type: ignore[no-untyped-def]
        return [(dt.date(2026, 10, 27), 455.7 if symbol == "KZT=X" else 110.9)]

    monkeypatch.setattr(yf, "closes", fake_closes)
    out = await ingest.update_fx_and_macro(session, history_days=3)
    assert out["nbk"] == 3 and out["usdkzt_market"] == 1 and out["brent"] == 1 and out["errors"] == []
    sources = set((await session.execute(select(FxRate.source))).scalars())
    assert sources == {"nbk", "yfinance"}
    assert (await session.execute(select(MacroObservation.series_id))).scalar_one() == "BRENT"


@respx.mock
async def test_update_news_from_all_sources(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from pydantic import SecretStr

    from tests.unit.test_sources import RSS

    s = get_settings()
    monkeypatch.setattr(s, "alpaca_key", SecretStr("k"))
    monkeypatch.setattr(s, "alpaca_secret", SecretStr("s"))
    monkeypatch.setattr(s, "finnhub_key", SecretStr("f"))
    monkeypatch.setattr(
        feeds,
        "RSS_FEEDS",
        (
            feeds.Feed("kursiv", "https://kursiv.test/feed", "ru", "KZ"),
            feeds.Feed("down", "https://down.test/feed", "ru", "KZ"),
        ),
    )
    await make_ticker(session, "AAPL")
    await make_ticker(
        session,
        "KSPI.KZ",
        exchange="KASE",
        market="KZ",
        currency="KZT",
        data_source="tradernet",
        aliases=(("Kaspi", "en"),),
    )
    respx.get(f"{DATA}/v1beta1/news").respond(
        200,
        json={
            "news": [
                {
                    "created_at": "2026-10-28T08:00:00Z",
                    "headline": "Apple",
                    "url": "https://a/1",
                    "symbols": ["AAPL"],
                }
            ]
        },
    )
    respx.get("https://finnhub.io/api/v1/company-news").respond(
        200, json=[{"datetime": 1793131200, "headline": "AAPL f", "url": "https://f/1", "source": "Yahoo"}]
    )
    respx.get("https://kursiv.test/feed").respond(200, content=RSS)
    respx.get("https://down.test/feed").respond(500)

    out = await ingest.update_news(session)
    assert out["inserted"] == {"alpaca": 1, "finnhub": 1, "kursiv": 1}
    assert len(out["errors"]) == 1 and "down" in out["errors"][0]
    assert await session.scalar(select(func.count()).select_from(News)) == 3


@respx.mock
async def test_refresh_live_quotes_publishes(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from pydantic import SecretStr

    s = get_settings()
    assert await ingest.refresh_live_quotes(session) == 0  # no keys → no-op
    monkeypatch.setattr(s, "alpaca_key", SecretStr("k"))
    monkeypatch.setattr(s, "alpaca_secret", SecretStr("s"))
    await make_ticker(session, "AAPL")
    respx.get(f"{DATA}/v2/stocks/snapshots").respond(
        200,
        json={
            "AAPL": {"latestTrade": {"p": 101.0, "t": "2026-10-28T15:00:00Z"}, "prevDailyBar": {"c": 100.0}}
        },
    )
    pubsub = get_redis().pubsub()
    await pubsub.subscribe("prices")
    assert await ingest.refresh_live_quotes(session) == 1
    q = json.loads(await get_redis().get("quote:AAPL"))
    assert q["price"] == 101.0 and abs(q["change_pct"] - 0.01) < 1e-9
    msg = None
    for _ in range(10):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if msg:
            break
    assert msg and json.loads(msg["data"])["symbol"] == "AAPL"
    await pubsub.aclose()


async def test_generate_predictions(session) -> None:  # type: ignore[no-untyped-def]
    t = await make_ticker(session, "AAPL")
    await make_ticker(session, "EMPTY")
    await make_prices(session, t, days=50)
    assert await ingest.generate_predictions(session, MockPredictionProvider()) == 1


async def test_http_client_has_user_agent() -> None:
    async with ingest.http_client() as c:
        assert c.headers["User-Agent"] == "stock-platform-capstone/0.1"
        assert isinstance(c, httpx.AsyncClient)
