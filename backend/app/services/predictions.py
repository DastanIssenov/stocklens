"""Serving predictions: read the latest stored ones, or compute on demand with the active provider."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Prediction, Ticker
from app.ml_interface.base import (
    LONG_HORIZONS,
    SHORT_HORIZONS,
    PredictionContext,
    PredictionProvider,
    PredictionResult,
)
from app.schemas.api import FeatureOut, PredictionOut, PredictionsOut
from app.services.market import recent_series


def _to_out(p: Prediction) -> PredictionOut:
    return PredictionOut(
        horizon=p.horizon,
        horizon_days=p.horizon_days,
        as_of_date=p.as_of_date,
        predicted_return=p.predicted_return,
        prob_up=p.prob_up,
        confidence=p.confidence,
        top_features=[FeatureOut(**f) for f in p.top_features],
        model_version=p.model_version,
        is_demo=p.is_demo,
    )


async def store_predictions(session: AsyncSession, ticker_id: int, results: list[PredictionResult]) -> None:
    if not results:
        return
    rows = [
        {
            "ticker_id": ticker_id,
            "model_version": r.model_version,
            "horizon": r.horizon,
            "horizon_days": r.horizon_days,
            "as_of_date": r.as_of_date,
            "predicted_return": r.predicted_return,
            "prob_up": r.prob_up,
            "confidence": r.confidence,
            "top_features": [f.model_dump() for f in r.top_features],
            "is_demo": r.is_demo,
        }
        for r in results
    ]
    stmt = insert(Prediction).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_predictions_key",
        set_={
            c: stmt.excluded[c]
            for c in ("predicted_return", "prob_up", "confidence", "top_features", "is_demo")
        },
    )
    await session.execute(stmt)


async def compute_predictions(
    session: AsyncSession, ticker: Ticker, provider: PredictionProvider, as_of: dt.date | None = None
) -> list[PredictionResult]:
    series = await recent_series(session, ticker.id, n=300, as_of=as_of)
    if not series.dates:
        return []
    ctx = PredictionContext(
        symbol=ticker.symbol,
        market=ticker.market,
        is_liquid=ticker.is_liquid,
        as_of_date=series.dates[-1],
        closes=series.closes,
        volumes=series.volumes,
    )
    return await provider.predict(ctx)


async def get_predictions(
    session: AsyncSession, ticker: Ticker, provider: PredictionProvider
) -> PredictionsOut:
    series = await recent_series(session, ticker.id, n=1)
    rows: list[Prediction] = []
    if series.dates:
        as_of = series.dates[-1]
        rows = list(
            (
                await session.execute(
                    select(Prediction)
                    .where(Prediction.ticker_id == ticker.id, Prediction.as_of_date == as_of)
                    .order_by(Prediction.horizon_days, Prediction.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:  # nothing precomputed for the latest bar yet → compute now and store
            results = await compute_predictions(session, ticker, provider)
            await store_predictions(session, ticker.id, results)
            await session.commit()
            rows = list(
                (
                    await session.execute(
                        select(Prediction)
                        .where(Prediction.ticker_id == ticker.id, Prediction.as_of_date == as_of)
                        .order_by(Prediction.horizon_days)
                    )
                )
                .scalars()
                .all()
            )
    latest: dict[str, Prediction] = {}
    for r in rows:  # one row per horizon (first = newest model run)
        latest.setdefault(r.horizon, r)
    outs = [_to_out(p) for p in latest.values()]
    return PredictionsOut(
        symbol=ticker.symbol,
        short_term=[o for o in outs if o.horizon in SHORT_HORIZONS],
        long_term=[o for o in outs if o.horizon in LONG_HORIZONS],
        is_demo=any(o.is_demo for o in outs) if outs else provider.is_demo,
    )
