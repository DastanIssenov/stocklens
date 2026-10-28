"""Shared types for data-source connectors."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


class SourceError(Exception):
    """A data source failed or returned something unexpected (never contains secrets)."""


@dataclass(frozen=True)
class PriceBar:
    date: dt.date
    open: float
    high: float
    low: float
    close: float  # split-adjusted close (what charts show)
    volume: int
    adj_close: float | None = None  # split + dividend adjusted (for modelling)

    def is_valid(self) -> bool:
        return (
            self.close > 0
            and self.open > 0
            and self.high >= max(self.open, self.close) * 0.999
            and self.low <= min(self.open, self.close) * 1.001
            and self.volume >= 0
        )


# Honest, plain bot identifier. Note: Tradernet answers 403 to user agents that contain a URL (verified).
USER_AGENT = "stock-platform-capstone/0.1"
