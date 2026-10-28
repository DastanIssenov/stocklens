"""Structured logging with structlog (JSON in prod, pretty console in dev)."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_SENSITIVE = ("password", "token", "secret", "api_key", "authorization", "key")


def _redact(_: object, __: str, event_dict: dict) -> dict:
    """Last line of defence: never let secret-looking fields reach the log output."""
    for k in list(event_dict):
        if any(s in k.lower() for s in _SENSITIVE) and k != "event":
            event_dict[k] = "***"
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
    ]
    renderer = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # quiet noisy libraries; httpx logs full URLs (which may contain API keys as query params)
    for noisy in ("httpx", "httpcore", "yfinance", "peewee", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
