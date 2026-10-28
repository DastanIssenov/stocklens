import datetime as dt
from decimal import Decimal

from app.db.models import MacroObservation
from app.services.news import NewsItem, ingest_news
from tests.conftest import make_fx, make_prices, make_ticker


async def test_tickers_list_search_detail(client, session) -> None:  # type: ignore[no-untyped-def]
    aapl = await make_ticker(session, "AAPL", aliases=(("Apple", "en"),))
    await make_ticker(session, "KSPI", issuer="KASPI", market="KZ", aliases=(("Каспи", "ru"),))
    await make_ticker(
        session,
        "KSPI.KZ",
        exchange="KASE",
        market="KZ",
        currency="KZT",
        issuer="KASPI",
        data_source="tradernet",
    )
    await make_prices(session, aapl, days=30)

    r = await client.get("/api/v1/tickers", params={"market": "KZ"})
    assert {t["symbol"] for t in r.json()} == {"KSPI", "KSPI.KZ"}
    r = await client.get("/api/v1/tickers/search", params={"q": "Каспи"})
    assert [t["symbol"] for t in r.json()] == ["KSPI"]
    r = await client.get("/api/v1/tickers/search", params={"q": "kspi"})
    assert r.json()[0]["symbol"] == "KSPI"  # exact symbol match first

    r = await client.get("/api/v1/tickers/kspi.kz")
    body = r.json()
    assert r.status_code == 200 and body["currency"] == "KZT"
    assert [o["symbol"] for o in body["other_listings"]] == ["KSPI"]
    r = await client.get("/api/v1/tickers/AAPL")
    assert r.json()["quote"]["price"] > 0 and r.json()["quote"]["is_live"] is False
    assert (await client.get("/api/v1/tickers/NOPE")).status_code == 404


async def test_price_history_latest_and_cache(client, session) -> None:  # type: ignore[no-untyped-def]
    t = await make_ticker(session, "MSFT")
    rows = await make_prices(session, t, days=60)
    r = await client.get("/api/v1/prices/MSFT")
    bars = r.json()["bars"]
    assert len(bars) == 60 and bars[0]["date"] < bars[-1]["date"]
    start = rows[-10].date.isoformat()
    r = await client.get("/api/v1/prices/MSFT", params={"start": start})
    assert len(r.json()["bars"]) == 10
    r = await client.get("/api/v1/prices/MSFT", params={"start": "2026-01-10", "end": "2026-01-01"})
    assert r.status_code == 422

    latest = (await client.get("/api/v1/prices/MSFT/latest")).json()
    assert latest["price"] == float(rows[-1].close)
    assert latest["prev_close"] == float(rows[-2].close)
    assert (await client.get("/api/v1/prices/NOPE/latest")).status_code == 404
    empty = await make_ticker(session, "EMPTY")
    assert (await client.get(f"/api/v1/prices/{empty.symbol}/latest")).status_code == 404


async def test_live_quote_overrides_daily_close(client, session) -> None:  # type: ignore[no-untyped-def]
    from app.core.redis import cache_set_json

    t = await make_ticker(session, "NVDA")
    await make_prices(session, t, days=10)
    await cache_set_json(
        "quote:NVDA",
        {
            "symbol": "NVDA",
            "price": 123.0,
            "prev_close": 120.0,
            "ts": "2026-10-28T15:00:00+00:00",
            "source": "alpaca",
        },
        60,
    )
    q = (await client.get("/api/v1/prices/NVDA/latest")).json()
    assert q["is_live"] is True and q["price"] == 123.0
    assert abs(q["change_pct"] - 0.025) < 1e-9


async def test_market_overview_and_fx(client, session) -> None:  # type: ignore[no-untyped-def]
    a = await make_ticker(session, "AAPL")
    b = await make_ticker(session, "MSFT")
    await make_prices(session, a, days=40, daily_drift=0.01)
    await make_prices(session, b, days=40, daily_drift=-0.01)
    await make_fx(session, "451.05", "nbk")
    await make_fx(session, "455.7", "yfinance")
    session.add(
        MacroObservation(series_id="BRENT", date=dt.date.today(), source="yfinance", value=Decimal("110.5"))
    )
    await session.commit()

    r = await client.get("/api/v1/market/overview", params={"market": "US"})
    body = r.json()
    assert r.status_code == 200
    assert all(g["change_pct"] > 0 for g in body["gainers"])
    assert all(x["change_pct"] < 0 for x in body["losers"])
    assert {row["symbol"] for row in body["rows"]} == {"AAPL", "MSFT"}
    assert len(body["rows"][0]["sparkline"]) == 30
    assert body["fx"]["official"] == 451.05 and body["fx"]["rate_used"] == 451.05
    assert body["brent"] == 110.5
    assert (await client.get("/api/v1/market/overview", params={"market": "XX"})).status_code == 422

    fx = (await client.get("/api/v1/fx/latest")).json()
    assert fx["market"] == 455.7


async def test_fx_fallback_when_no_rates(client) -> None:  # type: ignore[no-untyped-def]
    fx = (await client.get("/api/v1/fx/latest")).json()
    assert fx["official"] is None and fx["rate_used"] == 450.0


async def test_news_linking_and_issuer_sharing(client, session) -> None:  # type: ignore[no-untyped-def]
    await make_ticker(
        session, "KSPI", issuer="KASPI", market="KZ", aliases=(("Kaspi", "en"), ("Каспи", "ru"))
    )
    await make_ticker(session, "KSPI.KZ", exchange="KASE", market="KZ", currency="KZT", issuer="KASPI")
    await make_ticker(session, "AAPL")
    now = dt.datetime.now(dt.UTC)
    items = [
        NewsItem(
            source="kursiv",
            lang="ru",
            published_at=now,
            title="Каспи отчитался о прибыли",
            url="https://k.example/1",
            summary="<p>Текст</p>",
        ),
        NewsItem(
            source="benzinga",
            lang="en",
            published_at=now - dt.timedelta(hours=1),
            title="Apple news",
            url="https://b.example/2",
            symbols=["AAPL", "UNKNOWN"],
        ),
        NewsItem(source="benzinga", lang="en", published_at=now, title="dup", url="https://b.example/2"),
    ]
    assert await ingest_news(session, items) == 2
    assert await ingest_news(session, items) == 0  # dedup by URL

    r = await client.get("/api/v1/news", params={"symbol": "KSPI.KZ"})
    news = r.json()
    assert len(news) == 1 and news[0]["symbols"] == ["KSPI"] and news[0]["summary"] == "Текст"
    r = await client.get("/api/v1/news", params={"lang": "en"})
    assert [n["title"] for n in r.json()] == ["Apple news"]
    r = await client.get("/api/v1/news", params={"market": "KZ"})
    assert len(r.json()) == 1
    assert (await client.get("/api/v1/news", params={"symbol": "NOPE"})).status_code == 404


async def test_predictions_are_demo_and_cached(client, session) -> None:  # type: ignore[no-untyped-def]
    t = await make_ticker(session, "TSLA")
    await make_prices(session, t, days=100)
    r = await client.get("/api/v1/predictions/TSLA")
    body = r.json()
    assert r.status_code == 200 and body["is_demo"] is True
    assert [p["horizon"] for p in body["short_term"]] == ["1d", "5d"]
    assert [p["horizon"] for p in body["long_term"]] == ["1m", "3m", "6m", "12m"]
    assert "not investment advice" in body["disclaimer"]
    again = (await client.get("/api/v1/predictions/TSLA")).json()
    assert again == body
    meta = (await client.get("/api/v1/meta")).json()
    assert meta["predictions_are_demo"] is True and meta["trade_reviewer"] == "mock"
    empty = await make_ticker(session, "NEW")
    body = (await client.get(f"/api/v1/predictions/{empty.symbol}")).json()
    assert body["short_term"] == [] and body["is_demo"] is True


async def test_trained_model_rows_win_and_mock_fills_gaps(client, session) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import Prediction

    t = await make_ticker(session, "AMD")
    rows = await make_prices(session, t, days=80)
    session.add(
        Prediction(
            ticker_id=t.id,
            model_version="lgbm-cpu-abc",
            horizon="5d",
            horizon_days=5,
            as_of_date=rows[-1].date,
            predicted_return=0.01,
            prob_up=0.6,
            confidence=0.2,
            top_features=[{"name": "ret_5", "value": 0.01, "contribution": 0.02}],
            is_demo=True,
        )
    )
    await session.commit()
    body = (await client.get("/api/v1/predictions/AMD")).json()
    five = next(p for p in body["short_term"] if p["horizon"] == "5d")
    assert five["model_version"] == "lgbm-cpu-abc" and five["prob_up"] == 0.6
    one = next(p for p in body["short_term"] if p["horizon"] == "1d")
    assert one["model_version"].startswith("mock")
    assert len(body["long_term"]) == 4
