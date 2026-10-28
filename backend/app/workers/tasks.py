"""Celery tasks: thin sync wrappers around async services."""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.logging import get_logger
from app.ml_interface.factory import get_prediction_provider
from app.services import ingest
from app.workers.celery_app import celery_app
from app.workers.runtime import run_with_session

log = get_logger(__name__)
NY = ZoneInfo("America/New_York")


def us_market_open(now: dt.datetime | None = None) -> bool:
    """Regular NYSE/Nasdaq session, Mon–Fri 09:30–16:00 New York time (holidays ignored)."""
    t = (now or dt.datetime.now(dt.UTC)).astimezone(NY)
    return t.weekday() < 5 and dt.time(9, 30) <= t.time() <= dt.time(16, 0)


def _enabled() -> bool:
    if not get_settings().data_updates_enabled:
        log.info("data_updates_disabled_skip")
        return False
    return True


@celery_app.task(name="app.workers.tasks.refresh_live_quotes")
def refresh_live_quotes(force: bool = False) -> int:
    if not _enabled() or not (force or us_market_open()):
        return 0
    return run_with_session(ingest.refresh_live_quotes)


@celery_app.task(
    name="app.workers.tasks.update_daily_prices", autoretry_for=(Exception,), retry_backoff=60, max_retries=3
)
def update_daily_prices(days: int = 10) -> dict[str, Any]:
    if not _enabled():
        return {}
    start = dt.date.today() - dt.timedelta(days=days)
    return run_with_session(lambda s: ingest.update_prices(s, start))


@celery_app.task(name="app.workers.tasks.update_fx_macro")
def update_fx_macro(days: int = 14) -> dict[str, Any]:
    if not _enabled():
        return {}
    return run_with_session(lambda s: ingest.update_fx_and_macro(s, days))


@celery_app.task(name="app.workers.tasks.update_news")
def update_news() -> dict[str, Any]:
    if not _enabled():
        return {}
    return run_with_session(ingest.update_news)


@celery_app.task(name="app.workers.tasks.generate_predictions")
def generate_predictions() -> int:
    return run_with_session(lambda s: ingest.generate_predictions(s, get_prediction_provider()))
