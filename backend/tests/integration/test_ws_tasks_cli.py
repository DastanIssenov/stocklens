import datetime as dt
import json

import pytest
from starlette.testclient import TestClient

from app import cli
from app.api.ws import PriceHub
from app.core import redis as redis_mod
from app.workers import tasks


class FakeWS:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, data: dict) -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(data)


async def test_hub_broadcast_filters_and_drops_dead_sockets() -> None:
    hub = PriceHub()
    a, b, everything, dead = FakeWS(), FakeWS(), FakeWS(), FakeWS(fail=True)
    hub.clients = {a: {"AAPL"}, b: {"MSFT"}, everything: set(), dead: {"AAPL"}}  # type: ignore[dict-item]
    await hub.broadcast({"symbol": "AAPL", "price": 1.0})
    assert a.sent == [{"type": "quote", "symbol": "AAPL", "price": 1.0}]
    assert b.sent == [] and len(everything.sent) == 1
    assert dead not in hub.clients


def test_ws_endpoint_snapshot_subscribe_and_live_push() -> None:
    from app.main import app

    redis_mod.set_redis(None)
    quote = {"symbol": "AAPL", "price": 10.0, "prev_close": 9.0, "ts": "2026-10-28T15:00:00Z"}
    with TestClient(app) as tc:
        tc.portal.call(redis_mod.get_redis().set, "quote:AAPL", json.dumps(quote))
        with tc.websocket_connect("/ws/prices?symbols=aapl,msft") as ws:
            assert ws.receive_json() == {"type": "quote", **quote}
            ws.send_text("subscribe:MSFT")
            pushed = {"symbol": "MSFT", "price": 5.0}
            for _ in range(20):  # the hub subscribes asynchronously; publish until it is listening
                n = tc.portal.call(redis_mod.get_redis().publish, "prices", json.dumps(pushed))
                if n:
                    break
                tc.portal.call(__import__("anyio").sleep, 0.1)
            assert ws.receive_json() == {"type": "quote", **pushed}
        too_many = ",".join(f"S{i}" for i in range(60))
        with tc.websocket_connect(f"/ws/prices?symbols={too_many}") as ws, pytest.raises(Exception):  # noqa: B017
            ws.receive_json()
    redis_mod.set_redis(None)


def test_us_market_hours() -> None:
    ny_open = dt.datetime(2026, 10, 28, 14, 0, tzinfo=dt.UTC)  # 10:00 New York, Wednesday
    assert tasks.us_market_open(ny_open)
    assert not tasks.us_market_open(dt.datetime(2026, 10, 28, 21, 30, tzinfo=dt.UTC))  # 17:30 NY
    assert not tasks.us_market_open(dt.datetime(2026, 10, 31, 15, 0, tzinfo=dt.UTC))  # Saturday


def test_tasks_respect_switch_and_call_services(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    monkeypatch.setattr(
        tasks, "run_with_session", lambda fn: calls.append(getattr(fn, "__name__", "lambda")) or 1
    )
    s = tasks.get_settings()
    monkeypatch.setattr(s, "data_updates_enabled", False)
    assert tasks.update_daily_prices() == {} and tasks.update_news() == {} and tasks.update_fx_macro() == {}
    assert tasks.refresh_live_quotes(force=True) == 0
    assert calls == []
    monkeypatch.setattr(s, "data_updates_enabled", True)
    tasks.update_daily_prices()
    tasks.update_fx_macro()
    tasks.update_news()
    tasks.refresh_live_quotes(force=True)
    tasks.generate_predictions()
    assert len(calls) == 5


def test_cli_dispatch(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli, "run_with_session", lambda fn: {"ok": True})
    for argv in (
        ["seed", "--years", "0.1", "--skip-news"],
        ["universe"],
        ["update-prices", "--days", "3"],
        ["update-news"],
        ["update-fx"],
        ["predict"],
        ["quotes"],
    ):
        assert cli.main(argv) == 0
    assert '"ok": true' in capsys.readouterr().out


async def test_cli_seed_flow(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.services import ingest

    async def fake_prices(s, start, *a, **k):  # type: ignore[no-untyped-def]
        return {"rows": {"AAPL": 5}, "errors": []}

    async def fake_fx(s, history_days=14, client=None):  # type: ignore[no-untyped-def]
        return {"errors": []}

    async def fake_news(s, client=None):  # type: ignore[no-untyped-def]
        return {"inserted": {"x": 2}, "errors": []}

    monkeypatch.setattr(ingest, "update_prices", fake_prices)
    monkeypatch.setattr(ingest, "update_fx_and_macro", fake_fx)
    monkeypatch.setattr(ingest, "update_news", fake_news)
    out = await cli._seed(session, years=0.1, skip_news=False)
    assert out["tickers"] > 30 and out["price_rows"] == 5 and out["news_inserted"] == 2
