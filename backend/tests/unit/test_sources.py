import datetime as dt
import json
from decimal import Decimal

import httpx
import pandas as pd
import pytest
import respx

from app.services.sources import alpaca, feeds, tradernet, yf
from app.services.sources.base import PriceBar, SourceError

DATA = "https://data.alpaca.markets"


def _bar(t: str, c: float) -> dict:
    return {"t": t, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1000, "n": 10, "vw": c}


@respx.mock
async def test_alpaca_daily_bars_paginates_and_merges_adjustments() -> None:
    route = respx.get(f"{DATA}/v2/stocks/bars")
    route.side_effect = [
        httpx.Response(
            200, json={"bars": {"AAPL": [_bar("2026-10-26T04:00:00Z", 100)]}, "next_page_token": "p2"}
        ),
        httpx.Response(
            200, json={"bars": {"AAPL": [_bar("2026-10-27T04:00:00Z", 101)]}, "next_page_token": None}
        ),
        httpx.Response(
            200,
            json={"bars": {"AAPL": [_bar("2026-10-26T04:00:00Z", 99), _bar("2026-10-27T04:00:00Z", 100)]}},
        ),
    ]
    async with httpx.AsyncClient() as c:
        out = await alpaca.AlpacaClient("k", "s", c, DATA).daily_bars(["AAPL"], dt.date(2026, 10, 1))
    bars = out["AAPL"]
    assert [b.date for b in bars] == [dt.date(2026, 10, 26), dt.date(2026, 10, 27)]
    assert bars[0].close == 100 and bars[0].adj_close == 99
    sent = [dict(call.request.url.params) for call in route.calls]
    assert sent[0]["adjustment"] == "split" and sent[0]["feed"] == "sip"
    assert sent[1]["page_token"] == "p2"
    assert sent[2]["adjustment"] == "all"
    assert route.calls[0].request.headers["APCA-API-KEY-ID"] == "k"


@respx.mock
async def test_alpaca_falls_back_to_iex_when_sip_forbidden() -> None:
    route = respx.get(f"{DATA}/v2/stocks/bars")
    route.side_effect = [
        httpx.Response(403, json={"message": "subscription does not permit querying recent SIP data"}),
        httpx.Response(200, json={"bars": {"AAPL": [_bar("2026-10-27T04:00:00Z", 1)]}}),
        httpx.Response(200, json={"bars": {"AAPL": [_bar("2026-10-27T04:00:00Z", 1)]}}),
    ]
    async with httpx.AsyncClient() as c:
        out = await alpaca.AlpacaClient("k", "s", c, DATA).daily_bars(["AAPL"], dt.date(2026, 10, 1))
    assert len(out["AAPL"]) == 1
    assert dict(route.calls[1].request.url.params)["feed"] == "iex"


@respx.mock
async def test_alpaca_snapshots_and_news() -> None:
    respx.get(f"{DATA}/v2/stocks/snapshots").respond(
        200,
        json={
            "AAPL": {"latestTrade": {"p": 150.5, "t": "2026-10-28T15:00:00Z"}, "prevDailyBar": {"c": 150.0}},
            "MSFT": None,
            "XOM": {"dailyBar": {"c": 0}},
        },
    )
    respx.get(f"{DATA}/v1beta1/news").respond(
        200,
        json={
            "news": [
                {
                    "created_at": "2026-10-28T08:00:00Z",
                    "headline": "H",
                    "url": "https://x/1",
                    "source": "benzinga",
                    "summary": "",
                    "symbols": ["AAPL"],
                },
                {"created_at": "2026-10-28T08:00:00Z", "headline": "", "url": "https://x/2"},
            ]
        },
    )
    async with httpx.AsyncClient() as c:
        client = alpaca.AlpacaClient("k", "s", c, DATA)
        snaps = await client.snapshots(["AAPL", "MSFT", "XOM"])
        news = await client.news(["AAPL"], start=dt.datetime(2026, 10, 27, tzinfo=dt.UTC))
    assert snaps == {
        "AAPL": {
            "symbol": "AAPL",
            "price": 150.5,
            "prev_close": 150.0,
            "ts": "2026-10-28T15:00:00Z",
            "source": "alpaca_iex",
        }
    }
    assert len(news) == 1 and news[0].symbols == ["AAPL"] and news[0].summary is None


@respx.mock
async def test_alpaca_error_does_not_leak_keys() -> None:
    respx.get(f"{DATA}/v1beta1/news").respond(401, text="unauthorized")
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError) as e:
            await alpaca.AlpacaClient("SECRETKEY", "SECRETSECRET", c, DATA).news()
    assert "SECRET" not in str(e.value)


TN = "https://tradernet.com/api/"
# 2026-10-26 and 2026-10-27 Moscow midnight = 21:00 UTC of the previous day
TS1, TS2 = 1792962000, 1793048400


def test_tradernet_parse_order_and_dates() -> None:
    data = {
        "hloc": {"HSBK.KZ": [[380, 370, 372, 375], [381, 371, 375, 380]]},
        "vl": {"HSBK.KZ": [100, 200]},
        "xSeries": {"HSBK.KZ": [TS1, TS2]},
    }
    bars = tradernet.parse_hloc(data)["HSBK.KZ"]
    assert bars[0] == PriceBar(dt.date(2026, 10, 26), open=372, high=380, low=370, close=375, volume=100)
    assert bars[1].date == dt.date(2026, 10, 27)


@respx.mock
async def test_tradernet_batch_retry_skips_unknown_ticker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        ids = json.loads(request.url.params["q"])["params"]["id"]
        if "BAD.KZ" in ids:
            return httpx.Response(200, json={"error": f"Failed to find instruments by tickers: {ids}"})
        return httpx.Response(
            200, json={"hloc": {ids: [[2, 1, 1, 2]]}, "vl": {ids: [5]}, "xSeries": {ids: [TS2]}}
        )

    respx.get(TN).mock(side_effect=handler)
    async with httpx.AsyncClient() as c:
        out = await tradernet.daily_bars(c, ["HSBK.KZ", "BAD.KZ"], dt.date(2026, 10, 1), min_interval_s=0)
    assert list(out) == ["HSBK.KZ"]


@respx.mock
async def test_tradernet_http_error() -> None:
    respx.get(TN).respond(403, text="forbidden")
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError):
            await tradernet.daily_bars(c, ["HSBK.KZ"], dt.date(2026, 10, 1), min_interval_s=0)


def test_yfinance_frame_to_bars_skips_nan() -> None:
    idx = pd.to_datetime(["2026-10-26", "2026-10-27"]).tz_localize("Europe/London")
    df = pd.DataFrame(
        {
            "Open": [1.0, 2.0],
            "High": [1.5, 2.5],
            "Low": [0.5, 1.5],
            "Close": [1.2, float("nan")],
            "Adj Close": [1.1, float("nan")],
            "Volume": [10, 0],
        },
        index=idx,
    )
    bars = yf.frame_to_bars(df)
    assert len(bars) == 1 and bars[0].date == dt.date(2026, 10, 26) and bars[0].adj_close == 1.1
    assert yf.frame_to_bars(None) == []


async def test_yfinance_daily_bars_handles_failures(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("blocked")

    monkeypatch.setattr(yf, "_history", boom)
    monkeypatch.setattr(yf.asyncio, "sleep", lambda s: _noop())
    with pytest.raises(SourceError):
        await yf.daily_bars(["KAP.IL"], dt.date(2026, 1, 1))


async def _noop() -> None:
    return None


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Kaspi profit up</title><link>https://k/1</link><description>&lt;p&gt;text&lt;/p&gt;</description>
<pubDate>Wed, 28 Oct 2026 09:01:30 +0000</pubDate></item>
<item><title>No link</title></item>
</channel></rss>"""


def test_parse_feed() -> None:
    items = feeds.parse_feed(RSS, feeds.Feed("kursiv", "u", "ru", "KZ"))
    assert len(items) == 1
    assert items[0].published_at == dt.datetime(2026, 10, 28, 9, 1, 30, tzinfo=dt.UTC)
    assert items[0].lang == "ru" and items[0].source == "kursiv"


NBK = """<?xml version="1.0" encoding="utf-8"?><rates><title>Official exchange rates</title>
<item><fullname>ДОЛЛАР США</fullname><title>USD</title><description>451.05</description><quant>1</quant></item>
<item><fullname>РУБЛЬ</fullname><title>RUB</title><description>5.6</description><quant>1</quant></item>
<item><fullname>ВОН</fullname><title>KRW</title><description>31.2</description><quant>100</quant></item>
<item><title>BAD</title><description>n/a</description></item>
</rates>""".encode()


def test_parse_nbk_rates() -> None:
    rates = feeds.parse_nbk_rates(NBK)
    assert rates["USD"] == Decimal("451.05")
    assert rates["KRW"] == Decimal("0.312")
    assert "BAD" not in rates


@respx.mock
async def test_nbk_and_finnhub_requests() -> None:
    respx.get(feeds.NBK_RATES_URL).respond(200, content=NBK)
    respx.get("https://finnhub.io/api/v1/company-news").respond(
        200,
        json=[
            {"datetime": 1793131200, "headline": "AAPL up", "url": "https://f/1", "source": "Yahoo"},
            {"datetime": 1, "headline": "", "url": ""},
        ],
    )
    async with httpx.AsyncClient() as c:
        assert await feeds.nbk_usdkzt(c, dt.date(2026, 10, 27)) == Decimal("451.05")
        items = await feeds.finnhub_company_news(
            c, "tok", "AAPL", dt.date(2026, 10, 25), dt.date(2026, 10, 28)
        )
    assert len(items) == 1 and items[0].symbols == ["AAPL"] and items[0].source == "yahoo"
    sent = respx.calls.last.request.url.params
    assert sent["symbol"] == "AAPL"


def test_detect_lang_for_kz_feeds() -> None:
    assert feeds.detect_lang("Акции Казатомпрома выросли", "ru") == "ru"
    assert feeds.detect_lang("Қазақтелеком жаңа шешімдерін ұсынды", "ru") == "kk"
    assert feeds.detect_lang("Apple shares rise", "en") == "en"
