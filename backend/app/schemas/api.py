"""Pydantic v2 request / response schemas of the public API."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import DISCLAIMER

Market = Literal["US", "KZ"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)
    locale: Literal["en", "ru", "kk"] = "en"

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        if v.isdigit() or v.isalpha():
            raise ValueError("password must contain letters and digits")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class UserOut(ORM):
    id: int
    email: str
    display_name: str | None
    locale: str
    created_at: dt.datetime


class AuthOut(BaseModel):
    user: UserOut
    tokens: TokenPair


# ---------------------------------------------------------------- tickers & prices
class TickerOut(ORM):
    symbol: str
    local_symbol: str
    name: str
    exchange: str
    market: str
    currency: str
    sector: str | None
    country: str
    issuer: str | None
    is_liquid: bool


class Quote(BaseModel):
    symbol: str
    price: float
    prev_close: float | None
    change: float | None
    change_pct: float | None
    currency: str
    as_of: dt.datetime | dt.date
    source: str
    is_live: bool = False


class TickerDetail(TickerOut):
    quote: Quote | None = None
    other_listings: list[TickerOut] = []


class Bar(BaseModel):
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceHistory(BaseModel):
    symbol: str
    currency: str
    bars: list[Bar]


class OverviewRow(BaseModel):
    symbol: str
    name: str
    exchange: str
    currency: str
    sector: str | None
    is_liquid: bool
    price: float | None
    change_pct: float | None
    as_of: dt.date | None
    sparkline: list[float] = []


class FxOut(BaseModel):
    pair: str = "USDKZT"
    official: float | None
    official_date: dt.date | None
    market: float | None
    market_date: dt.date | None
    rate_used: float


class MarketOverview(BaseModel):
    market: Market
    rows: list[OverviewRow]
    gainers: list[OverviewRow]
    losers: list[OverviewRow]
    fx: FxOut
    brent: float | None = None
    brent_date: dt.date | None = None


# ---------------------------------------------------------------- news
class NewsOut(BaseModel):
    id: int
    source: str
    lang: str
    published_at: dt.datetime
    title: str
    summary: str | None
    url: str
    sentiment: float | None
    symbols: list[str] = []


# ---------------------------------------------------------------- predictions
class FeatureOut(BaseModel):
    name: str
    value: float | None
    contribution: float


class PredictionOut(BaseModel):
    horizon: str
    horizon_days: int
    as_of_date: dt.date
    predicted_return: float
    prob_up: float
    confidence: float
    top_features: list[FeatureOut]
    model_version: str
    is_demo: bool


class PredictionsOut(BaseModel):
    symbol: str
    short_term: list[PredictionOut]
    long_term: list[PredictionOut]
    is_demo: bool
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------- portfolio & trades
class PositionOut(BaseModel):
    symbol: str
    name: str
    exchange: str
    currency: str
    quantity: float
    avg_cost: float
    price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    realized_pnl: float
    weight: float | None


class PortfolioOut(BaseModel):
    cash_usd: float
    cash_kzt: float
    positions: list[PositionOut]
    positions_value_usd: float
    positions_value_kzt: float
    total_value_usd: float
    total_value_kzt: float
    initial_value_usd: float
    total_pnl_usd: float
    total_pnl_pct: float
    usdkzt: float
    disclaimer: str = DISCLAIMER


class TradeIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0, le=1_000_000)

    @field_validator("quantity")
    @classmethod
    def _whole_shares(cls, v: float) -> float:
        if v != int(v):
            raise ValueError("only whole shares can be traded")
        return v


class ReviewOut(BaseModel):
    reviewer: str
    model: str
    verdict: str
    score: int
    summary: str | None
    reasons: list[str]
    risks: list[str]
    what_to_watch: list[str]
    created_at: dt.datetime | None = None
    disclaimer: str = DISCLAIMER


class TradeOut(BaseModel):
    id: int
    symbol: str
    name: str
    exchange: str
    side: str
    quantity: float
    price: float
    fee: float
    currency: str
    notional: float
    realized_pnl: float | None
    price_source: str
    executed_at: dt.datetime
    review: ReviewOut | None


class MetaOut(BaseModel):
    prediction_provider: str
    predictions_are_demo: bool
    trade_reviewer: str
    trade_reviewer_model: str
    currencies: list[str] = ["USD", "KZT"]
    markets: list[str] = ["US", "KZ"]
    disclaimer: str = DISCLAIMER
