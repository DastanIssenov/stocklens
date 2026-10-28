"""ONE feature module for training and inference (docs/GPU_PLAN.md §3).

`compute_features(prices, market, macro)` only uses information available at each row's date:
all windows look backwards, macro values are joined on `available_at`, cross-sectional ranks are
computed within a date. `tests/test_features.py` checks that appending future rows never changes past values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES: list[str] = [
    "ret_1",
    "ret_5",
    "ret_10",
    "ret_21",
    "ret_63",
    "ret_126",
    "ret_252",
    "mom_12_1",
    "vol_5",
    "vol_21",
    "vol_63",
    "parkinson_21",
    "vol_ratio_5_63",
    "sma_10",
    "sma_20",
    "sma_50",
    "sma_200",
    "rsi_14",
    "bb_pctb_20",
    "macd_hist",
    "dist_52w_high",
    "dist_52w_low",
    "overnight_ret",
    "intraday_ret",
    "volume_z_21",
    "log_dollar_volume",
    "amihud_21",
    "zero_volume_63",
    "beta_63",
    "idio_vol_63",
    "mkt_ret_1",
    "mkt_ret_5",
    "mkt_ret_21",
    "vix",
    "vix_chg_5",
    "rank_ret_5",
    "rank_ret_21",
    "rank_vol_21",
    "rank_dollar_volume",
    "ust_10y_2y",
    "hy_spread",
    "fed_funds",
    "dow",
    "month",
]


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def _per_symbol(g: pd.DataFrame) -> pd.DataFrame:
    px = g["adj_close"].fillna(g["close"])
    lr = np.log(px).diff()
    out = pd.DataFrame(index=g.index)
    for n in (1, 5, 10, 21, 63, 126, 252):
        out[f"ret_{n}"] = np.log(px / px.shift(n))
    out["mom_12_1"] = np.log(px.shift(21) / px.shift(252))
    for n in (5, 21, 63):
        out[f"vol_{n}"] = lr.rolling(n, min_periods=max(3, n // 2)).std()
    hl = np.log(g["high"] / g["low"]) ** 2
    out["parkinson_21"] = np.sqrt(hl.rolling(21, min_periods=10).mean() / (4 * np.log(2)))
    out["vol_ratio_5_63"] = out["vol_5"] / out["vol_63"]
    for n in (10, 20, 50, 200):
        out[f"sma_{n}"] = px / px.rolling(n, min_periods=n // 2).mean() - 1
    out["rsi_14"] = _rsi(px)
    ma20, sd20 = px.rolling(20).mean(), px.rolling(20).std()
    out["bb_pctb_20"] = (px - (ma20 - 2 * sd20)) / (4 * sd20)
    macd = px.ewm(span=12, adjust=False).mean() - px.ewm(span=26, adjust=False).mean()
    out["macd_hist"] = (macd - macd.ewm(span=9, adjust=False).mean()) / px
    raw = g["close"]  # level features use raw prices (future splits must not change past levels)
    out["dist_52w_high"] = raw / raw.rolling(252, min_periods=60).max() - 1
    out["dist_52w_low"] = raw / raw.rolling(252, min_periods=60).min() - 1
    out["overnight_ret"] = np.log(g["open"] / raw.shift(1))
    out["intraday_ret"] = np.log(raw / g["open"])
    lv = np.log1p(g["volume"].astype(float))
    out["volume_z_21"] = (lv - lv.rolling(21).mean()) / lv.rolling(21).std()
    dv = raw * g["volume"]
    out["log_dollar_volume"] = np.log1p(dv.rolling(21, min_periods=5).median())
    out["amihud_21"] = (lr.abs() / dv.replace(0, np.nan)).rolling(21, min_periods=5).mean() * 1e9
    out["zero_volume_63"] = (g["volume"] == 0).rolling(63, min_periods=10).mean()
    return out


def compute_features(
    prices: pd.DataFrame, market: pd.DataFrame | None = None, macro: pd.DataFrame | None = None
) -> pd.DataFrame:
    """prices: symbol, date, open, high, low, close, adj_close, volume → one row per (symbol, date)."""
    p = prices.sort_values(["symbol", "date"]).reset_index(drop=True)
    p["date"] = pd.to_datetime(p["date"])
    feats = p.groupby("symbol", group_keys=False)[
        ["open", "high", "low", "close", "adj_close", "volume"]
    ].apply(_per_symbol)
    df = pd.concat([p[["symbol", "date"]], feats], axis=1)

    # market context (SPY / ^VIX closes), same calendar day
    if market is not None and not market.empty:
        m = market.copy()
        m["date"] = pd.to_datetime(m["date"])
        spy = m[m["symbol"] == "SPY"].set_index("date")["adj_close"].sort_index()
        vix = m[m["symbol"] == "^VIX"].set_index("date")["close"].sort_index()
        mk = pd.DataFrame({"mkt_lr": np.log(spy).diff()})
        for n in (1, 5, 21):
            mk[f"mkt_ret_{n}"] = np.log(spy / spy.shift(n))
        mk["vix"] = vix
        mk["vix_chg_5"] = np.log(vix / vix.shift(5))
        df = df.merge(mk, left_on="date", right_index=True, how="left")
        # beta / idiosyncratic vol vs SPY over 63 days
        sym_lr = np.log(p["adj_close"].fillna(p["close"])).groupby(p["symbol"]).diff()
        df["_lr"] = sym_lr.values
        cov = df.groupby("symbol", group_keys=False).apply(
            lambda g: g["_lr"].rolling(63, min_periods=30).cov(g["mkt_lr"]), include_groups=False
        )
        var = df.groupby("symbol", group_keys=False)["mkt_lr"].apply(
            lambda s: s.rolling(63, min_periods=30).var()
        )
        df["beta_63"] = cov / var
        resid = df["_lr"] - df["beta_63"] * df["mkt_lr"]
        df["idio_vol_63"] = resid.groupby(df["symbol"]).transform(
            lambda s: s.rolling(63, min_periods=30).std()
        )
        df = df.drop(columns=["_lr", "mkt_lr"])

    # macro: as-of join on publication date (available_at), never on observation date
    if macro is not None and not macro.empty:
        mac = macro.copy()
        mac["available_at"] = pd.to_datetime(mac["available_at"])
        wide = (
            mac.sort_values("available_at")
            .pivot_table(index="available_at", columns="name", values="value", aggfunc="last")
            .sort_index()
            .ffill()
        )
        keep = [c for c in ("ust_10y_2y", "hy_spread", "fed_funds") if c in wide]
        df = df.sort_values("date")
        df = pd.merge_asof(df, wide[keep], left_on="date", right_index=True, direction="backward")

    # cross-sectional ranks within each date
    for src, dst in (
        ("ret_5", "rank_ret_5"),
        ("ret_21", "rank_ret_21"),
        ("vol_21", "rank_vol_21"),
        ("log_dollar_volume", "rank_dollar_volume"),
    ):
        df[dst] = df.groupby("date")[src].rank(pct=True)
    df["dow"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month
    for c in FEATURES:
        if c not in df:
            df[c] = np.nan
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)[["symbol", "date", *FEATURES]]


def add_targets(prices: pd.DataFrame, horizons: tuple[int, ...] = (1, 5)) -> pd.DataFrame:
    """Forward log returns from close t to close t+h (labels — never used as features)."""
    p = prices.sort_values(["symbol", "date"]).copy()
    p["date"] = pd.to_datetime(p["date"])
    px = p["adj_close"].fillna(p["close"])
    out = p[["symbol", "date"]].copy()
    for h in horizons:
        out[f"fwd_ret_{h}"] = np.log(px.groupby(p["symbol"]).shift(-h) / px)
        out[f"up_{h}"] = (out[f"fwd_ret_{h}"] > 0).astype(float).where(out[f"fwd_ret_{h}"].notna())
    return out
