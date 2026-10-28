"""Paper trading: portfolios with USD and KZT cash, market orders at the latest price, fees, P&L.

Rules (D-020):
* market orders only, filled at the latest known price (live quote if fresh, else the last close);
* whole shares; trades settle in the listing currency (USD or KZT cash), no automatic FX conversion;
* commission = max(min_fee, rate × notional), per exchange; buy commission is added to the cost basis;
* average-cost accounting; realised P&L = (price − avg_cost) × qty − sell commission.
"""

from __future__ import annotations

import asyncio
import time
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Portfolio, Position, Trade, TradeReview, User
from app.ml_interface.base import PredictionProvider, TradeContext, TradeReviewer
from app.schemas.api import PortfolioOut, PositionOut, ReviewOut, TradeOut
from app.services import analytics
from app.services.market import get_ticker, latest_quote, recent_series, usdkzt_rate
from app.services.predictions import get_predictions

log = get_logger(__name__)

CENT = Decimal("0.01")
MICRO = Decimal("0.000001")


class TradingError(Exception):
    """Business-rule violation (insufficient cash, not enough shares, no price)."""


def compute_fee(exchange: str, notional: Decimal) -> Decimal:
    s = get_settings()
    if exchange in ("NASDAQ", "NYSE"):
        rate, minimum = s.fee_rate_us, s.fee_min_us
    elif exchange == "LSE":
        rate, minimum = s.fee_rate_lse, s.fee_min_lse
    else:  # KASE, AIX
        rate, minimum = s.fee_rate_kase, s.fee_min_kase
    return max(minimum, notional * rate).quantize(CENT, rounding=ROUND_HALF_UP)


async def create_portfolio(session: AsyncSession, user: User) -> Portfolio:
    s = get_settings()
    p = Portfolio(
        user_id=user.id,
        cash_usd=s.starting_cash_usd,
        cash_kzt=s.starting_cash_kzt,
        initial_usd=s.starting_cash_usd,
        initial_kzt=s.starting_cash_kzt,
    )
    session.add(p)
    await session.flush()
    return p


async def get_portfolio(session: AsyncSession, user: User, *, lock: bool = False) -> Portfolio:
    stmt = select(Portfolio).where(Portfolio.user_id == user.id)
    if lock:
        stmt = stmt.with_for_update()
    p = (await session.execute(stmt)).scalar_one_or_none()
    if p is None:  # users created before portfolios existed / manual DB edits
        p = await create_portfolio(session, user)
    return p


async def execute_trade(session: AsyncSession, user: User, symbol: str, side: str, quantity: float) -> Trade:
    ticker = await get_ticker(session, symbol)
    if not ticker.is_active:
        raise TradingError(f"{ticker.symbol} is not tradable")
    quote = await latest_quote(session, ticker)
    if quote is None or quote.price <= 0:
        raise TradingError(f"no price available for {ticker.symbol}")
    price = Decimal(str(quote.price)).quantize(MICRO)
    qty = Decimal(int(quantity))
    if qty <= 0:
        raise TradingError("quantity must be a positive whole number")

    portfolio = await get_portfolio(session, user, lock=True)
    position = (
        await session.execute(
            select(Position)
            .where(Position.portfolio_id == portfolio.id, Position.ticker_id == ticker.id)
            .with_for_update(of=Position)
        )
    ).scalar_one_or_none()

    notional = (price * qty).quantize(MICRO)
    fee = compute_fee(ticker.exchange, notional)
    cash_attr = "cash_usd" if ticker.currency == "USD" else "cash_kzt"
    cash: Decimal = getattr(portfolio, cash_attr)
    realized: Decimal | None = None

    if side == "buy":
        total = notional + fee
        if total > cash:
            raise TradingError(
                f"insufficient {ticker.currency} cash: need {total:,.2f}, available {cash:,.2f}"
            )
        setattr(portfolio, cash_attr, cash - total)
        if position is None:
            position = Position(
                portfolio_id=portfolio.id,
                ticker_id=ticker.id,
                quantity=Decimal(0),
                avg_cost=Decimal(0),
                realized_pnl=Decimal(0),
            )
            session.add(position)
        new_qty = position.quantity + qty
        position.avg_cost = ((position.quantity * position.avg_cost + notional + fee) / new_qty).quantize(
            MICRO
        )
        position.quantity = new_qty
    elif side == "sell":
        held = position.quantity if position else Decimal(0)
        if position is None or held < qty:
            raise TradingError(f"not enough {ticker.symbol} shares: have {held:g}, want to sell {qty:g}")
        realized = ((price - position.avg_cost) * qty - fee).quantize(MICRO)
        setattr(portfolio, cash_attr, cash + notional - fee)
        position.quantity = held - qty
        position.realized_pnl = position.realized_pnl + realized
        if position.quantity == 0:
            position.avg_cost = Decimal(0)
    else:
        raise TradingError("side must be 'buy' or 'sell'")

    trade = Trade(
        portfolio_id=portfolio.id,
        ticker_id=ticker.id,
        side=side,
        quantity=qty,
        price=price,
        fee=fee,
        currency=ticker.currency,
        realized_pnl=realized,
        price_source=quote.source[:30],
        price_as_of=None if not quote.is_live else quote.as_of,
    )
    session.add(trade)
    await session.commit()
    await session.refresh(trade, attribute_names=["ticker", "review", "executed_at"])
    log.info(
        "trade_executed", user_id=user.id, symbol=ticker.symbol, side=side, qty=str(qty), price=str(price)
    )
    return trade


async def reset_portfolio(session: AsyncSession, user: User) -> None:
    p = await get_portfolio(session, user, lock=True)
    await session.execute(delete(Trade).where(Trade.portfolio_id == p.id))
    await session.execute(delete(Position).where(Position.portfolio_id == p.id))
    p.cash_usd, p.cash_kzt = p.initial_usd, p.initial_kzt
    await session.commit()


async def portfolio_summary(session: AsyncSession, user: User) -> PortfolioOut:
    p = await get_portfolio(session, user)
    rate = await usdkzt_rate(session)
    positions = (
        (
            await session.execute(
                select(Position)
                .where(Position.portfolio_id == p.id, Position.quantity > 0)
                .order_by(Position.id)
            )
        )
        .scalars()
        .all()
    )
    rows: list[PositionOut] = []
    pos_usd = Decimal(0)
    for pos in positions:
        q = await latest_quote(session, pos.ticker)
        price = Decimal(str(q.price)) if q else None
        mv = pos.quantity * price if price is not None else None
        if mv is not None:
            pos_usd += mv if pos.ticker.currency == "USD" else mv / rate
        rows.append(
            PositionOut(
                symbol=pos.ticker.symbol,
                name=pos.ticker.name,
                exchange=pos.ticker.exchange,
                currency=pos.ticker.currency,
                quantity=float(pos.quantity),
                avg_cost=float(pos.avg_cost),
                price=float(price) if price is not None else None,
                market_value=float(mv) if mv is not None else None,
                unrealized_pnl=float((price - pos.avg_cost) * pos.quantity) if price is not None else None,
                unrealized_pnl_pct=float(price / pos.avg_cost - 1)
                if price is not None and pos.avg_cost
                else None,
                realized_pnl=float(pos.realized_pnl),
                weight=None,
            )
        )
    cash_usd_equiv = p.cash_usd + p.cash_kzt / rate
    total_usd = cash_usd_equiv + pos_usd
    for r in rows:
        if r.market_value is not None and total_usd > 0:
            mv_usd = Decimal(str(r.market_value)) / (rate if r.currency == "KZT" else 1)
            r.weight = float(mv_usd / total_usd)
    initial_usd = p.initial_usd + p.initial_kzt / rate
    return PortfolioOut(
        cash_usd=float(p.cash_usd),
        cash_kzt=float(p.cash_kzt),
        positions=rows,
        positions_value_usd=float(pos_usd),
        positions_value_kzt=float(pos_usd * rate),
        total_value_usd=float(total_usd),
        total_value_kzt=float(total_usd * rate),
        initial_value_usd=float(initial_usd),
        total_pnl_usd=float(total_usd - initial_usd),
        total_pnl_pct=float(total_usd / initial_usd - 1) if initial_usd else 0.0,
        usdkzt=float(rate),
    )


# ------------------------------------------------------------------ reviews
async def build_trade_context(
    session: AsyncSession, user: User, trade: Trade, provider: PredictionProvider
) -> TradeContext:
    t = trade.ticker
    summary = await portfolio_summary(session, user)
    weight = next((pos.weight for pos in summary.positions if pos.symbol == t.symbol), 0.0) or 0.0
    rate = Decimal(str(summary.usdkzt))
    notional = trade.price * trade.quantity
    notional_usd = notional if trade.currency == "USD" else notional / rate
    cash_after = Decimal(str(summary.cash_usd if trade.currency == "USD" else summary.cash_kzt))
    cash_before = cash_after + (notional + trade.fee if trade.side == "buy" else -(notional - trade.fee))
    series = await recent_series(session, t.id, n=60)
    closes, vols = series.closes, series.volumes
    preds = await get_predictions(session, t, provider)
    p5 = next((p for p in preds.short_term if p.horizon == "5d"), None)
    avg_cost = next((pos.avg_cost for pos in summary.positions if pos.symbol == t.symbol), None)
    return TradeContext(
        symbol=t.symbol,
        name=t.name,
        market=t.market,
        exchange=t.exchange,
        currency=trade.currency,
        side=trade.side,
        quantity=float(trade.quantity),
        price=float(trade.price),
        fee=float(trade.fee),
        notional=float(notional),
        notional_usd=float(notional_usd),
        portfolio_value_usd=summary.total_value_usd,
        position_weight_after=weight,
        cash_left_ratio=float(cash_after / cash_before) if cash_before > 0 else 0.0,
        avg_cost=avg_cost,
        realized_pnl=float(trade.realized_pnl) if trade.realized_pnl is not None else None,
        is_liquid=t.is_liquid,
        return_5d=analytics.simple_return(closes, 5),
        return_20d=analytics.simple_return(closes, 20),
        volatility_20d=analytics.volatility(closes, 20),
        rsi_14=analytics.rsi(closes, 14),
        avg_volume_20d=analytics.average(vols[-20:]),
        prediction_5d_return=p5.predicted_return if p5 else None,
        prediction_5d_prob_up=p5.prob_up if p5 else None,
        prediction_is_demo=p5.is_demo if p5 else True,
    )


async def review_trade(
    session: AsyncSession,
    user: User,
    trade: Trade,
    reviewer: TradeReviewer,
    fallback: TradeReviewer,
    provider: PredictionProvider,
) -> TradeReview:
    ctx = await build_trade_context(session, user, trade, provider)
    lang = user.locale or "en"
    used = reviewer
    t0 = time.perf_counter()
    try:
        out = await asyncio.wait_for(reviewer.review(ctx, lang), timeout=get_settings().llm_timeout_s + 5)
    except Exception as e:
        log.warning("trade_review_failed_using_fallback", reviewer=reviewer.name, error=str(e)[:200])
        used = fallback
        out = await fallback.review(ctx, lang)
    latency = int((time.perf_counter() - t0) * 1000)
    await session.execute(delete(TradeReview).where(TradeReview.trade_id == trade.id))
    review = TradeReview(
        trade_id=trade.id,
        reviewer=used.name,
        model=used.model,
        verdict=out.verdict,
        score=out.score,
        summary=out.summary,
        reasons=out.reasons,
        risks=out.risks,
        what_to_watch=out.what_to_watch,
        latency_ms=latency,
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return review


def review_out(r: TradeReview | None) -> ReviewOut | None:
    if r is None:
        return None
    return ReviewOut(
        reviewer=r.reviewer,
        model=r.model,
        verdict=r.verdict,
        score=r.score,
        summary=r.summary,
        reasons=list(r.reasons),
        risks=list(r.risks),
        what_to_watch=list(r.what_to_watch),
        created_at=r.created_at,
    )


def trade_out(t: Trade, review: TradeReview | None = None) -> TradeOut:
    return TradeOut(
        id=t.id,
        symbol=t.ticker.symbol,
        name=t.ticker.name,
        exchange=t.ticker.exchange,
        side=t.side,
        quantity=float(t.quantity),
        price=float(t.price),
        fee=float(t.fee),
        currency=t.currency,
        notional=float(t.price * t.quantity),
        realized_pnl=float(t.realized_pnl) if t.realized_pnl is not None else None,
        price_source=t.price_source,
        executed_at=t.executed_at,
        review=review_out(review if review is not None else t.review),
    )


async def list_trades(session: AsyncSession, user: User, limit: int = 100, offset: int = 0) -> list[Trade]:
    p = await get_portfolio(session, user)
    stmt = (
        select(Trade)
        .where(Trade.portfolio_id == p.id)
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_trade(session: AsyncSession, user: User, trade_id: int) -> Trade | None:
    p = await get_portfolio(session, user)
    return (
        await session.execute(select(Trade).where(Trade.id == trade_id, Trade.portfolio_id == p.id))
    ).scalar_one_or_none()
