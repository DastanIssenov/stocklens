"""SQLAlchemy 2.0 ORM models. See docs/ARCHITECTURE.md §3 for the ER diagram."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

EXCHANGES = ("NASDAQ", "NYSE", "KASE", "AIX", "LSE")
MARKETS = ("US", "KZ")
CURRENCIES = ("USD", "KZT")
HORIZONS = ("1d", "5d", "1m", "3m", "6m", "12m")
EMBEDDING_DIM = 1024

Money = Numeric(20, 6)


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    locale: Mapped[str] = mapped_column(String(5), default="en", server_default="en", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[dt.datetime] = _now()

    portfolio: Mapped[Portfolio | None] = relationship(back_populates="user", uselist=False)


class Ticker(Base):
    __tablename__ = "tickers"
    __table_args__ = (
        CheckConstraint(_in("exchange", EXCHANGES), name="exchange"),
        CheckConstraint(_in("market", MARKETS), name="market"),
        CheckConstraint(_in("currency", CURRENCIES), name="currency"),
        Index("ix_tickers_market_exchange", "market", "exchange"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    local_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    market: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(100), index=True)
    data_source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    is_liquid: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    created_at: Mapped[dt.datetime] = _now()

    aliases: Mapped[list[TickerAlias]] = relationship(
        back_populates="ticker", cascade="all, delete-orphan", lazy="selectin"
    )


class TickerAlias(Base):
    """Names used to link news to tickers (EN / RU / KK spellings)."""

    __tablename__ = "ticker_aliases"
    __table_args__ = (UniqueConstraint("ticker_id", "alias", name="uq_ticker_aliases_ticker_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker_id: Mapped[int] = mapped_column(ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    lang: Mapped[str] = mapped_column(String(2), nullable=False)

    ticker: Mapped[Ticker] = relationship(back_populates="aliases")


class PriceDaily(Base):
    """TimescaleDB hypertable on `date` (created in the migration)."""

    __tablename__ = "prices_daily"

    ticker_id: Mapped[int] = mapped_column(
        ForeignKey("tickers.id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(20), nullable=False)


class FxRate(Base):
    __tablename__ = "fx_rates"

    pair: Mapped[str] = mapped_column(String(6), primary_key=True)  # e.g. USDKZT
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)  # nbk | yfinance
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)


class MacroObservation(Base):
    """Macro / commodity series (Brent, VIX, rates...). `source` e.g. fred | yfinance."""

    __tablename__ = "macro_observations"

    series_id: Mapped[str] = mapped_column(String(40), primary_key=True)  # e.g. BRENT, VIXCLS
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)


class News(Base):
    __tablename__ = "news"
    __table_args__ = (Index("ix_news_published_at", "published_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    lang: Mapped[str] = mapped_column(String(2), nullable=False)
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    sentiment: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[dt.datetime] = _now()

    tickers: Mapped[list[NewsTicker]] = relationship(back_populates="news", cascade="all, delete-orphan")


class NewsTicker(Base):
    __tablename__ = "news_tickers"
    __table_args__ = (Index("ix_news_tickers_ticker_id", "ticker_id"),)

    news_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), primary_key=True)
    ticker_id: Mapped[int] = mapped_column(ForeignKey("tickers.id", ondelete="CASCADE"), primary_key=True)
    match_method: Mapped[str] = mapped_column(String(10), nullable=False, default="vendor")
    relevance: Mapped[float | None] = mapped_column(Float)

    news: Mapped[News] = relationship(back_populates="tickers")


class Fundamental(Base):
    """Point-in-time fundamentals: `published_at` is when the value became public."""

    __tablename__ = "fundamentals"
    __table_args__ = (
        UniqueConstraint("ticker_id", "metric", "period_end", "accession", name="uq_fundamentals_fact"),
        Index("ix_fundamentals_ticker_published", "ticker_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker_id: Mapped[int] = mapped_column(ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    metric: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(30, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    period_start: Mapped[dt.date | None] = mapped_column(Date)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(4))
    form: Mapped[str | None] = mapped_column(String(10))
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accession: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="sec")


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("ticker_id", "model_version", "horizon", "as_of_date", name="uq_predictions_key"),
        CheckConstraint(_in("horizon", HORIZONS), name="horizon"),
        CheckConstraint("prob_up >= 0 AND prob_up <= 1", name="prob_up_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_predictions_ticker_horizon_asof", "ticker_id", "horizon", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker_id: Mapped[int] = mapped_column(ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    horizon: Mapped[str] = mapped_column(String(4), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    predicted_return: Mapped[float] = mapped_column(Float, nullable=False)
    prob_up: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    top_features: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = _now()


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (
        CheckConstraint("cash_usd >= 0", name="cash_usd_nonneg"),
        CheckConstraint("cash_kzt >= 0", name="cash_kzt_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    cash_usd: Mapped[Decimal] = mapped_column(Money, nullable=False)
    cash_kzt: Mapped[Decimal] = mapped_column(Money, nullable=False)
    initial_usd: Mapped[Decimal] = mapped_column(Money, nullable=False)
    initial_kzt: Mapped[Decimal] = mapped_column(Money, nullable=False)
    created_at: Mapped[dt.datetime] = _now()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="portfolio")
    positions: Mapped[list[Position]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "ticker_id", name="uq_positions_portfolio_ticker"),
        CheckConstraint("quantity >= 0", name="quantity_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker_id: Mapped[int] = mapped_column(ForeignKey("tickers.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(0))
    avg_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal(0))
    realized_pnl: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal(0))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")
    ticker: Mapped[Ticker] = relationship(lazy="joined")


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="side"),
        CheckConstraint("quantity > 0", name="quantity_pos"),
        CheckConstraint("price > 0", name="price_pos"),
        Index("ix_trades_portfolio_executed", "portfolio_id", "executed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker_id: Mapped[int] = mapped_column(ForeignKey("tickers.id", ondelete="RESTRICT"), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    fee: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Money)
    price_source: Mapped[str] = mapped_column(String(30), nullable=False)
    price_as_of: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[dt.datetime] = _now()

    ticker: Mapped[Ticker] = relationship(lazy="joined")
    review: Mapped[TradeReview | None] = relationship(
        back_populates="trade", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )


class TradeReview(Base):
    __tablename__ = "trade_reviews"
    __table_args__ = (
        CheckConstraint("verdict IN ('reasonable', 'risky', 'poor')", name="verdict"),
        CheckConstraint("score BETWEEN 1 AND 10", name="score_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    reviewer: Mapped[str] = mapped_column(String(20), nullable=False)  # mock | llm
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    what_to_watch: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = _now()

    trade: Mapped[Trade] = relationship(back_populates="review")
