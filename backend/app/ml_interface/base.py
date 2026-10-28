"""Interfaces between the website and the ML part.

The API layer only ever talks to `PredictionProvider` and `TradeReviewer`. Mock implementations live
in `mock.py`; real ones (MLflow models, vLLM-served LLM) are selected in `factory.py` by settings,
so switching from mock to real is a configuration change only.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Horizon = Literal["1d", "5d", "1m", "3m", "6m", "12m"]
HORIZON_DAYS: dict[str, int] = {"1d": 1, "5d": 5, "1m": 21, "3m": 63, "6m": 126, "12m": 252}
SHORT_HORIZONS: tuple[Horizon, ...] = ("1d", "5d")
LONG_HORIZONS: tuple[Horizon, ...] = ("1m", "3m", "6m", "12m")
ALL_HORIZONS: tuple[Horizon, ...] = SHORT_HORIZONS + LONG_HORIZONS


# ------------------------------------------------------------------ predictions
class FeatureContribution(BaseModel):
    name: str
    value: float | None
    contribution: float


class PredictionContext(BaseModel):
    """Everything a provider may use. `closes` ends at `as_of_date` — never later."""

    symbol: str
    market: Literal["US", "KZ"]
    is_liquid: bool = True
    as_of_date: dt.date
    closes: list[float] = Field(default_factory=list)
    volumes: list[float] = Field(default_factory=list)
    horizons: tuple[Horizon, ...] = ALL_HORIZONS


class PredictionResult(BaseModel):
    symbol: str
    horizon: Horizon
    horizon_days: int
    as_of_date: dt.date
    predicted_return: float
    prob_up: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    top_features: list[FeatureContribution] = Field(default_factory=list)
    model_version: str
    is_demo: bool


class PredictionProvider(ABC):
    name: str
    is_demo: bool

    @abstractmethod
    async def predict(self, ctx: PredictionContext) -> list[PredictionResult]:
        """Return one result per horizon in `ctx.horizons`."""


# ------------------------------------------------------------------ trade reviews
Verdict = Literal["reasonable", "risky", "poor"]


class TradeContext(BaseModel):
    """Facts about a just-executed paper trade. Values in the trade currency unless `_usd`."""

    symbol: str
    name: str
    market: Literal["US", "KZ"]
    exchange: str
    currency: Literal["USD", "KZT"]
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    fee: float
    notional: float
    notional_usd: float
    portfolio_value_usd: float
    position_weight_after: float = Field(description="share of total portfolio value, 0..1")
    cash_left_ratio: float = Field(description="cash in trade currency after/before the trade, 0..1")
    avg_cost: float | None = None
    realized_pnl: float | None = None
    is_liquid: bool = True
    return_5d: float | None = None
    return_20d: float | None = None
    volatility_20d: float | None = Field(default=None, description="annualised")
    rsi_14: float | None = None
    avg_volume_20d: float | None = None
    prediction_5d_return: float | None = None
    prediction_5d_prob_up: float | None = None
    prediction_is_demo: bool = True


class TradeReviewOutput(BaseModel):
    """Strict JSON contract for every reviewer (mock or LLM)."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    score: int = Field(ge=1, le=10)
    summary: str = Field(min_length=1, max_length=400)
    reasons: list[str] = Field(min_length=3, max_length=5)
    risks: list[str] = Field(min_length=1, max_length=5)
    what_to_watch: list[str] = Field(min_length=1, max_length=5)


class TradeReviewer(ABC):
    name: str  # "mock" | "llm"
    model: str

    @abstractmethod
    async def review(self, ctx: TradeContext, lang: str = "en") -> TradeReviewOutput:
        """Review a trade. Must return a validated `TradeReviewOutput` or raise."""
