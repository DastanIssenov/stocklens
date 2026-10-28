from app.core.config import get_settings
from tests.conftest import auth_header, make_fx, make_prices, make_ticker, register


async def _setup(client, session):  # type: ignore[no-untyped-def]
    us = await make_ticker(session, "AAPL")
    kz = await make_ticker(
        session, "HSBK.KZ", exchange="KASE", market="KZ", currency="KZT", data_source="tradernet"
    )
    us_rows = await make_prices(session, us, days=60, start_price=100)
    kz_rows = await make_prices(session, kz, days=60, start_price=300)
    await make_fx(session, "450")
    user = await register(client)
    return auth_header(user), float(us_rows[-1].close), float(kz_rows[-1].close)


async def test_buy_sell_flow_with_review_and_pnl(client, session) -> None:  # type: ignore[no-untyped-def]
    h, us_price, _ = await _setup(client, session)
    p0 = (await client.get("/api/v1/portfolio", headers=h)).json()
    assert p0["cash_usd"] == 100000 and p0["cash_kzt"] == 50000000 and p0["positions"] == []

    r = await client.post("/api/v1/trades", json={"symbol": "AAPL", "side": "buy", "quantity": 10}, headers=h)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["price"] == us_price and t["fee"] == 1.0 and t["currency"] == "USD"
    review = t["review"]
    assert review["reviewer"] == "mock" and review["verdict"] in {"reasonable", "risky", "poor"}
    assert 3 <= len(review["reasons"]) <= 5 and 1 <= review["score"] <= 10

    p1 = (await client.get("/api/v1/portfolio", headers=h)).json()
    assert round(p1["cash_usd"], 6) == round(100000 - 10 * us_price - 1.0, 6)
    pos = p1["positions"][0]
    assert pos["symbol"] == "AAPL" and pos["quantity"] == 10
    assert abs(pos["avg_cost"] - (10 * us_price + 1) / 10) < 1e-6  # fee in cost basis
    assert 0 < pos["weight"] < 0.02

    r = await client.post("/api/v1/trades", json={"symbol": "AAPL", "side": "sell", "quantity": 4}, headers=h)
    assert r.status_code == 201
    sold = r.json()
    assert abs(sold["realized_pnl"] - (-(4 * 0.1) - 1.0)) < 1e-6  # (price - avg_cost) * 4 - fee
    p2 = (await client.get("/api/v1/portfolio", headers=h)).json()
    assert p2["positions"][0]["quantity"] == 6

    history = (await client.get("/api/v1/trades", headers=h)).json()
    assert [x["side"] for x in history] == ["sell", "buy"]
    assert all(x["review"] for x in history)
    one = (await client.get(f"/api/v1/trades/{history[0]['id']}", headers=h)).json()
    assert one["id"] == history[0]["id"]
    rr = await client.post(f"/api/v1/trades/{history[1]['id']}/review", headers=h)
    assert rr.status_code == 200 and rr.json()["reviewer"] == "mock"


async def test_kzt_trade_uses_kzt_cash_and_minimum_fee(client, session) -> None:  # type: ignore[no-untyped-def]
    h, _, kz_price = await _setup(client, session)
    r = await client.post(
        "/api/v1/trades", json={"symbol": "HSBK.KZ", "side": "buy", "quantity": 5}, headers=h
    )
    assert r.status_code == 201
    assert r.json()["fee"] == float(get_settings().fee_min_kase)
    p = (await client.get("/api/v1/portfolio", headers=h)).json()
    assert p["cash_usd"] == 100000
    assert round(p["cash_kzt"], 4) == round(50000000 - 5 * kz_price - 300, 4)
    assert abs(p["total_value_usd"] - p["total_value_kzt"] / 450) < 1e-6


async def test_trade_errors(client, session) -> None:  # type: ignore[no-untyped-def]
    h, _, _ = await _setup(client, session)
    post = client.post
    r = await post("/api/v1/trades", json={"symbol": "AAPL", "side": "sell", "quantity": 1}, headers=h)
    assert r.status_code == 400 and "not enough" in r.json()["detail"]
    r = await post("/api/v1/trades", json={"symbol": "AAPL", "side": "buy", "quantity": 100000}, headers=h)
    assert r.status_code == 400 and "insufficient USD cash" in r.json()["detail"]
    r = await post("/api/v1/trades", json={"symbol": "NOPE", "side": "buy", "quantity": 1}, headers=h)
    assert r.status_code == 404
    r = await post("/api/v1/trades", json={"symbol": "AAPL", "side": "buy", "quantity": 1.5}, headers=h)
    assert r.status_code == 422
    r = await post("/api/v1/trades", json={"symbol": "AAPL", "side": "hold", "quantity": 1}, headers=h)
    assert r.status_code == 422
    await make_ticker(session, "NOPRICE")
    r = await post("/api/v1/trades", json={"symbol": "NOPRICE", "side": "buy", "quantity": 1}, headers=h)
    assert r.status_code == 400 and "no price" in r.json()["detail"]
    assert (await client.get("/api/v1/trades/999", headers=h)).status_code == 404
    assert (await client.post("/api/v1/trades/999/review", headers=h)).status_code == 404


async def test_users_cannot_see_each_others_trades_and_reset(client, session) -> None:  # type: ignore[no-untyped-def]
    h1, _, _ = await _setup(client, session)
    other = await register(client, "other@example.com")
    h2 = auth_header(other)
    t = (
        await client.post("/api/v1/trades", json={"symbol": "AAPL", "side": "buy", "quantity": 1}, headers=h1)
    ).json()
    assert (await client.get(f"/api/v1/trades/{t['id']}", headers=h2)).status_code == 404
    assert (await client.get("/api/v1/trades", headers=h2)).json() == []
    reset = (await client.post("/api/v1/portfolio/reset", headers=h1)).json()
    assert reset["positions"] == [] and reset["cash_usd"] == 100000
    assert (await client.get("/api/v1/trades", headers=h1)).json() == []


async def test_failing_llm_reviewer_falls_back_to_mock(client, session) -> None:  # type: ignore[no-untyped-def]
    from app.api.deps import trade_reviewer
    from app.main import app
    from app.ml_interface.base import TradeReviewer

    class Broken(TradeReviewer):
        name, model = "llm", "broken"

        async def review(self, ctx, lang="en"):  # type: ignore[no-untyped-def]
            raise RuntimeError("LLM down")

    h, _, _ = await _setup(client, session)
    app.dependency_overrides[trade_reviewer] = lambda: Broken()
    try:
        r = await client.post(
            "/api/v1/trades", json={"symbol": "AAPL", "side": "buy", "quantity": 1}, headers=h
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 201 and r.json()["review"]["reviewer"] == "mock"


async def test_rate_limit_returns_429(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_enabled", True)
    monkeypatch.setattr(s, "rate_limit_auth", 2)
    codes = []
    for _ in range(3):
        r = await client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "nope12345"})
        codes.append(r.status_code)
    assert codes == [401, 401, 429]
    assert "Retry-After" in r.headers
