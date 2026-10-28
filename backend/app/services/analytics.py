"""Small, pure price statistics shared by the mock models, trade reviews and the API.

Everything here only looks at the series it is given (no future data).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

TRADING_DAYS = 252


def simple_return(closes: Sequence[float], lookback: int) -> float | None:
    if len(closes) <= lookback or closes[-1 - lookback] <= 0:
        return None
    return closes[-1] / closes[-1 - lookback] - 1.0


def log_returns(closes: Sequence[float]) -> list[float]:
    return [math.log(b / a) for a, b in pairwise(closes) if a > 0 and b > 0]


def volatility(closes: Sequence[float], window: int = 20, annualize: bool = True) -> float | None:
    """Standard deviation of daily log returns over the last `window` returns."""
    rets = log_returns(closes[-(window + 1) :])
    if len(rets) < max(5, window // 2):
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    return sd * math.sqrt(TRADING_DAYS) if annualize else sd


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(closes) <= period:
        return None
    gains, losses = 0.0, 0.0
    for a, b in zip(closes[-period - 1 : -1], closes[-period:], strict=True):
        d = b - a
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def max_drawdown(closes: Sequence[float]) -> float | None:
    if not closes:
        return None
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            mdd = min(mdd, c / peak - 1.0)
    return mdd


def average(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
