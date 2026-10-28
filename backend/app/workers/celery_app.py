"""Celery app + Beat schedule (decision D-015)."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

celery_app = Celery(
    "stock_platform", broker=settings.broker_url, backend=settings.broker_url, include=["app.workers.tasks"]
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=30 * 60,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # US live quotes during market hours (task itself checks the NYSE session)
        "live-quotes": {"task": "app.workers.tasks.refresh_live_quotes", "schedule": 60.0},
        # daily bars: idempotent re-fetch of the last 10 days every 2 h on weekdays (US + KASE closes)
        "daily-prices": {
            "task": "app.workers.tasks.update_daily_prices",
            "schedule": crontab(minute=15, hour="*/2", day_of_week="mon-fri"),
        },
        "fx-macro": {"task": "app.workers.tasks.update_fx_macro", "schedule": crontab(minute=5, hour="*/3")},
        "news": {"task": "app.workers.tasks.update_news", "schedule": 30 * 60.0},
        # predictions after the US close (mock now; real models in the GPU phase)
        "predictions": {
            "task": "app.workers.tasks.generate_predictions",
            "schedule": crontab(minute=30, hour=23),
        },
    },
)
