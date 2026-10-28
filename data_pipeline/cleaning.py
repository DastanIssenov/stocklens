"""Bar validation and cleaning rules (docs/GPU_PLAN.md §2.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def validate_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop impossible bars, add `flag_*` columns; never forward-fills or edits prices."""
    if df.empty:
        return df
    df = df.copy()
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    bad = (
        df[["open", "high", "low", "close"]].isna().any(axis=1)
        | (df["close"] <= 0)
        | (df["high"] < df["low"])
        | (df["close"] > df["high"] * 1.001)
        | (df["close"] < df["low"] * 0.999)
    )
    df = df[~bad].sort_values(["symbol", "date"])
    lr = np.log(df["close"]).groupby(df["symbol"]).diff()
    df["flag_jump"] = lr.abs() > np.log(1.5)  # > +50 % / < −33 % in a day: needs a corporate-action check
    df["flag_zero_volume"] = df["volume"] == 0
    return df.reset_index(drop=True)


def cross_check(alpaca: pd.DataFrame, yahoo: pd.DataFrame, tol: float = 0.005) -> pd.DataFrame:
    """Share of days where adjusted closes differ by more than `tol` (per symbol)."""
    m = alpaca.merge(yahoo, on=["symbol", "date"], suffixes=("_a", "_y"))
    if m.empty:
        return pd.DataFrame(columns=["symbol", "days", "mismatch_share"])
    m["diff"] = (m["adj_close_a"] / m["adj_close_y"] - 1).abs()
    g = m.groupby("symbol")["diff"]
    return pd.DataFrame(
        {"days": g.size(), "mismatch_share": g.apply(lambda s: float((s > tol).mean()))}
    ).reset_index()


def illiquidity(df: pd.DataFrame, window: int = 63) -> pd.DataFrame:
    """Per symbol: share of zero-volume days and Amihud illiquidity over the last `window` rows."""
    out = []
    for sym, g in df.sort_values("date").groupby("symbol"):
        g = g.tail(window)
        ret = g["close"].pct_change().abs()
        dv = g["close"] * g["volume"]
        amihud = (ret / dv.replace(0, np.nan)).mean()
        out.append(
            {
                "symbol": sym,
                "rows": len(g),
                "zero_volume_share": float((g["volume"] == 0).mean()),
                "amihud": float(amihud) if pd.notna(amihud) else None,
            }
        )
    return pd.DataFrame(out)
