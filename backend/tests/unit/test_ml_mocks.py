import datetime as dt

import pytest
from pydantic import ValidationError

from app.ml_interface.base import ALL_HORIZONS, PredictionContext, TradeContext, TradeReviewOutput
from app.ml_interface.mock import MockPredictionProvider, MockTradeReviewer

CLOSES = [100 * (1 + 0.002 * i) for i in range(120)]


async def test_mock_predictions_are_deterministic_and_bounded() -> None:
    ctx = PredictionContext(symbol="AAPL", market="US", as_of_date=dt.date(2026, 10, 27), closes=CLOSES)
    p = MockPredictionProvider()
    r1, r2 = await p.predict(ctx), await p.predict(ctx)
    assert [x.model_dump() for x in r1] == [x.model_dump() for x in r2]
    assert [x.horizon for x in r1] == list(ALL_HORIZONS)
    for x in r1:
        assert x.is_demo and x.model_version.startswith("mock")
        assert 0.05 <= x.prob_up <= 0.95
        assert 0 <= x.confidence <= 0.75
        assert x.top_features


async def test_mock_predictions_change_with_date_and_handle_empty_history() -> None:
    p = MockPredictionProvider()
    a = await p.predict(
        PredictionContext(symbol="X", market="KZ", as_of_date=dt.date(2026, 1, 1), closes=CLOSES)
    )
    b = await p.predict(
        PredictionContext(symbol="X", market="KZ", as_of_date=dt.date(2026, 1, 2), closes=CLOSES)
    )
    assert a[0].predicted_return != b[0].predicted_return
    empty = await p.predict(
        PredictionContext(symbol="X", market="KZ", is_liquid=False, as_of_date=dt.date(2026, 1, 1))
    )
    assert len(empty) == len(ALL_HORIZONS)


def _ctx(**kw) -> TradeContext:  # type: ignore[no-untyped-def]
    base = dict(
        symbol="AAPL",
        name="Apple",
        market="US",
        exchange="NASDAQ",
        currency="USD",
        side="buy",
        quantity=10,
        price=100,
        fee=1,
        notional=1000,
        notional_usd=1000,
        portfolio_value_usd=100000,
        position_weight_after=0.01,
        cash_left_ratio=0.99,
        volatility_20d=0.2,
        return_5d=0.01,
    )
    base.update(kw)
    return TradeContext(**base)


async def test_mock_reviewer_small_diversified_buy_is_reasonable() -> None:
    out = await MockTradeReviewer().review(_ctx())
    assert out.verdict == "reasonable"
    assert 3 <= len(out.reasons) <= 5 and out.risks and out.what_to_watch


async def test_mock_reviewer_flags_concentration_volatility_and_chasing() -> None:
    out = await MockTradeReviewer().review(
        _ctx(position_weight_after=0.6, volatility_20d=0.9, return_5d=0.2, cash_left_ratio=0.01)
    )
    assert out.verdict == "poor"
    assert out.score <= 3
    assert len(out.risks) >= 3


async def test_mock_reviewer_sell_and_kz_and_russian() -> None:
    out = await MockTradeReviewer().review(
        _ctx(
            side="sell",
            market="KZ",
            currency="KZT",
            exchange="KASE",
            return_5d=-0.15,
            is_liquid=False,
            realized_pnl=-500.0,
            volatility_20d=None,
        ),
        lang="ru",
    )
    assert out.verdict in {"risky", "poor"}
    assert any("Курс" in w or "курс" in w for w in out.what_to_watch)
    assert any("ликвид" in r for r in out.risks)


async def test_mock_reviewer_minimum_reasons_when_no_stats() -> None:
    out = await MockTradeReviewer().review(_ctx(side="sell", volatility_20d=None, return_5d=None), lang="kk")
    assert len(out.reasons) >= 3


def test_review_schema_is_strict() -> None:
    good = dict(
        verdict="risky", score=5, summary="s", reasons=["a", "b", "c"], risks=["r"], what_to_watch=["w"]
    )
    TradeReviewOutput(**good)
    with pytest.raises(ValidationError):
        TradeReviewOutput(**{**good, "score": 11})
    with pytest.raises(ValidationError):
        TradeReviewOutput(**{**good, "reasons": ["a"]})
    with pytest.raises(ValidationError):
        TradeReviewOutput(**{**good, "verdict": "buy"})
    with pytest.raises(ValidationError):
        TradeReviewOutput(**{**good, "extra": 1})
