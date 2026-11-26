"""ONE feature module for training and inference (docs/GPU_PLAN.md §3).

`compute_features(prices, market, macro, filings)` only uses information available at each row's date:
all windows look backwards, macro values are joined on `available_at`, filings count from the first session
whose close is after the filing was accepted, cross-sectional ranks are computed within a date.
`ml/tests/test_ml.py::test_features_have_no_lookahead` checks that appending future rows never changes past values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# v1 feature set (CPU baseline lgbm-cpu-93314193). Kept so old bundles and the ablation stay reproducible.
FEATURES_V1: list[str] = [
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

# v2 additions, grouped so the dev-fold ablation (ml/experiments/ablation.py) can switch them on and off.
FEATURE_GROUPS: dict[str, list[str]] = {
    # stock return minus beta × market return: the stock-specific part of a move (short-term reversal lives here)
    "residual": ["resid_ret_1", "resid_ret_5", "resid_ret_21", "resid_ret_63"],
    # cross-sectional percentile ranks within the day: what matters for picking stocks is relative standing
    "ranks": [
        "rank_ret_1",
        "rank_ret_63",
        "rank_ret_252",
        "rank_mom_12_1",
        "rank_resid_ret_5",
        "rank_resid_ret_21",
        "rank_idio_vol_63",
        "rank_beta_63",
        "rank_dist_52w_high",
        "rank_volume_z_21",
        "rank_rsi_14",
        "rank_sma_50",
    ],
    # quarterly / annual reports (SEC 10-Q, 10-K, 20-F, 40-F): post-earnings drift proxy
    "filings": ["days_since_filing", "filing_reaction", "rank_filing_reaction"],
    # macro as changes instead of levels: levels identify the calendar period and let trees memorise regimes
    "macro_changes": ["ust_10y_2y_chg_63", "fed_funds_chg_63", "ust_10y_chg_21", "usd_broad_chg_21"],
    # point-in-time SEC fundamentals as within-day ranks (value, quality, growth, accruals)
    "fundamentals": [
        "rank_ep",
        "rank_bp",
        "rank_sp",
        "rank_cfp",
        "rank_roe",
        "rank_gross_margin",
        "rank_leverage",
        "rank_rev_growth",
        "rank_earn_chg",
        "rank_accruals",
    ],
    # industry: return relative to the stock's industry group and the group's own momentum
    "industry": ["ind_rel_ret_5", "ind_rel_ret_21", "ind_rel_ret_63", "ind_ret_21", "ind_ret_63"],
}
# macro levels and calendar fields of v1 that the ablation may drop (hy_spread exists on FRED only from 2023-10)
MACRO_LEVELS = ["ust_10y_2y", "hy_spread", "fed_funds"]
CALENDAR = ["dow", "month"]

ALL_FEATURES: list[str] = list(
    dict.fromkeys(FEATURES_V1 + [f for g in FEATURE_GROUPS.values() for f in g] + MACRO_LEVELS)
)
# default training set; chosen on the 2016–2018 dev folds (docs/BACKTEST_REPORT.md, "v2")
FEATURES: list[str] = FEATURES_V1

FILING_FORMS = ("10-Q", "10-K", "20-F", "40-F")
# 20:00 UTC = 16:00 New York in summer (17:00 in winter time). A filing accepted later counts from the next session.
_CLOSE_UTC_HOUR = 20


def filings_from_fundamentals(fund: pd.DataFrame) -> pd.DataFrame:
    """One row per original periodic report: symbol, available_at (UTC). Amendments (…/A) are not new news."""
    f = fund[fund["form"].isin(FILING_FORMS)]
    f = f.drop_duplicates(["symbol", "accession"])
    return f[["symbol", "available_at"]].reset_index(drop=True)


def _first_session_index(dates: np.ndarray, available_at: pd.Series) -> np.ndarray:
    """Index (into the symbol's sorted trading `dates`) of the first session whose close comes after the
    filing was accepted. Date-only timestamps (00:00, older EDGAR rows) may be after the close → next session."""
    ts = pd.to_datetime(available_at, utc=True)
    day = ts.dt.tz_localize(None).dt.normalize().to_numpy(dtype="datetime64[ns]")
    date_only = (ts.dt.hour == 0) & (ts.dt.minute == 0) & (ts.dt.second == 0)
    after_close = date_only | (ts.dt.hour >= _CLOSE_UTC_HOUR)
    left = np.searchsorted(dates, day, side="left")
    right = np.searchsorted(dates, day, side="right")
    return np.where(after_close.to_numpy(), right, left)


def _filing_features(
    p: pd.DataFrame, filings: pd.DataFrame, spy: pd.Series | None, react_before: int = 3
) -> pd.DataFrame:
    """days_since_filing: sessions since the last report became public (0 on that session).
    filing_reaction: stock minus SPY log return from `react_before` sessions before that session to one session
    after it (the earnings release usually comes a few days before the 10-Q), known from that session's close on."""
    out = pd.DataFrame(index=p.index, columns=["days_since_filing", "filing_reaction"], dtype=float)
    fil = filings.copy()
    for sym, g in p.groupby("symbol", sort=False):
        fs = fil[fil["symbol"] == sym]
        if fs.empty:
            continue
        dates = g["date"].to_numpy(dtype="datetime64[ns]")
        px = np.log(g["adj_close"].fillna(g["close"]).to_numpy(dtype=float))
        m = np.log(spy.reindex(g["date"]).to_numpy(dtype=float)) if spy is not None else np.zeros(len(g))
        eff = np.unique(_first_session_index(dates, fs["available_at"]))
        eff = eff[eff < len(g)]
        if eff.size == 0:
            continue
        i = np.arange(len(g))
        k = np.searchsorted(eff, i, side="right") - 1  # last filing with eff <= i
        has = k >= 0
        e = np.where(has, eff[np.clip(k, 0, None)], -1)
        days = np.where(has, i - e, np.nan)
        a, b = e - react_before, e + 1
        ok = has & (a >= 0) & (b <= i)  # reaction window must be complete by the row's date
        a_c, b_c = np.clip(a, 0, len(g) - 1), np.clip(b, 0, len(g) - 1)
        react = (px[b_c] - px[a_c]) - (m[b_c] - m[a_c])
        out.loc[g.index, "days_since_filing"] = np.minimum(days, 130)
        out.loc[g.index, "filing_reaction"] = np.where(ok, react, np.nan)
    return out


FUNDAMENTAL_RATIOS = (
    "ep",
    "bp",
    "sp",
    "cfp",
    "roe",
    "gross_margin",
    "leverage",
    "rev_growth",
    "earn_chg",
    "accruals",
)


def _fundamental_ratios(p: pd.DataFrame, events: pd.DataFrame) -> dict[str, np.ndarray]:
    """Daily ratios from the last filing whose first session is on or before the row's date. Market cap at t =
    shares × close on the share-count date × total return since then (adj_close ratio) — split-proof without
    a split table, and the ratio of two adj_close values does not change when later corporate actions re-adjust
    the history. Dividends paid in between add a small (< 2 %/year) error."""
    n = len(p)
    out = {k: np.full(n, np.nan) for k in FUNDAMENTAL_RATIOS}
    ev_by_sym = dict(tuple(events.groupby("symbol", sort=False)))
    for sym, g in p.groupby("symbol", sort=False):
        ev = ev_by_sym.get(sym)
        if ev is None or ev.empty:
            continue
        dates = g["date"].to_numpy(dtype="datetime64[ns]")
        close = g["close"].to_numpy(dtype=float)
        adj = g["adj_close"].fillna(g["close"]).to_numpy(dtype=float)
        eff = _first_session_index(dates, ev["available_at"])
        i = np.arange(len(g))
        k = np.searchsorted(eff, i, side="right") - 1  # events are sorted by time, so eff is non-decreasing
        has = k >= 0
        e = ev.iloc[np.clip(k, 0, None)]

        def col(c: str, e: pd.DataFrame = e, has: np.ndarray = has) -> np.ndarray:
            v = e[c].to_numpy(dtype=float) if c in e else np.full(len(e), np.nan)
            return np.where(has, v, np.nan)

        sd = pd.to_datetime(e["shares_date"]).to_numpy(dtype="datetime64[ns]") if "shares_date" in e else None
        mcap = np.full(len(g), np.nan)
        if sd is not None:
            a = np.searchsorted(dates, sd, side="right") - 1  # last session on or before the share-count date
            ok = has & (a >= 0) & ~np.isnat(sd)
            ac = np.clip(a, 0, None)
            mcap = np.where(ok, col("shares") * close[ac] * adj / adj[ac], np.nan)
        mcap = np.where(mcap > 0, mcap, np.nan)
        ni, rev, cfo = col("net_income_ttm"), col("revenue_ttm"), col("cfo_ttm")
        eq, assets = col("equity"), col("assets")
        with np.errstate(divide="ignore", invalid="ignore"):
            vals = {
                "ep": ni / mcap,
                "bp": eq / mcap,
                "sp": rev / mcap,
                "cfp": cfo / mcap,
                "roe": np.where(eq > 0, ni / eq, np.nan),
                "gross_margin": col("gross_profit_ttm") / rev,
                "leverage": col("liabilities") / assets,
                "rev_growth": np.where(col("revenue_ttm_1y") > 0, rev / col("revenue_ttm_1y") - 1, np.nan),
                "earn_chg": (ni - col("net_income_ttm_1y")) / mcap,
                "accruals": (ni - cfo) / assets,
            }
        idx = g.index.to_numpy()
        for c, v in vals.items():
            out[c][idx] = v
    return out


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
    prices: pd.DataFrame,
    market: pd.DataFrame | None = None,
    macro: pd.DataFrame | None = None,
    filings: pd.DataFrame | None = None,
    fund_events: pd.DataFrame | None = None,
    industries: pd.Series | None = None,
) -> pd.DataFrame:
    """prices: symbol, date, open, high, low, close, adj_close, volume → one row per (symbol, date) with
    every column of ALL_FEATURES (missing inputs give NaN columns). filings: symbol, available_at.
    fund_events: `fundamentals.fundamental_events(...)`; industries: symbol → group (`industry_groups(...)`)."""
    p = prices.sort_values(["symbol", "date"]).reset_index(drop=True)
    p["date"] = pd.to_datetime(p["date"])
    feats = p.groupby("symbol", group_keys=False)[
        ["open", "high", "low", "close", "adj_close", "volume"]
    ].apply(_per_symbol)
    df = pd.concat([p[["symbol", "date"]], feats], axis=1)
    spy: pd.Series | None = None

    # market context (SPY / ^VIX closes), same calendar day
    if market is not None and not market.empty:
        m = market.copy()
        m["date"] = pd.to_datetime(m["date"])
        spy = m[m["symbol"] == "SPY"].set_index("date")["adj_close"].sort_index()
        vix = m[m["symbol"] == "^VIX"].set_index("date")["close"].sort_index()
        mk = pd.DataFrame({"mkt_lr": np.log(spy).diff()})
        for n in (1, 5, 21, 63):
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
        # residual (market-adjusted) returns with today's beta — beta uses only data up to today
        for n in (1, 5, 21, 63):
            df[f"resid_ret_{n}"] = df[f"ret_{n}"] - df["beta_63"] * df[f"mkt_ret_{n}"]
        df = df.drop(columns=["_lr", "mkt_lr"])

    if filings is not None and not filings.empty:
        fil = _filing_features(p, filings, spy)
        df["days_since_filing"] = fil["days_since_filing"].to_numpy(dtype=float)
        df["filing_reaction"] = fil["filing_reaction"].to_numpy(dtype=float)

    if fund_events is not None and not fund_events.empty:
        for c, v in _fundamental_ratios(p, fund_events).items():
            df[c] = v

    if industries is not None and not industries.empty:
        grp = p["symbol"].map(industries).fillna("Other")
        for n in (5, 21, 63):
            mean = df[f"ret_{n}"].groupby([df["date"], grp.to_numpy()]).transform("mean")
            df[f"ind_rel_ret_{n}"] = df[f"ret_{n}"] - mean
            if n in (21, 63):
                df[f"ind_ret_{n}"] = mean

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
        keep = [c for c in ("ust_10y_2y", "hy_spread", "fed_funds", "ust_10y", "usd_broad") if c in wide]
        days = pd.DataFrame({"date": np.sort(df["date"].unique())})
        lv = pd.merge_asof(days, wide[keep], left_on="date", right_index=True, direction="backward")
        lv = lv.set_index("date")
        # changes over N sessions of the as-of value (sessions = dates present in the panel, all in the past)
        for col, n in (("ust_10y_2y", 63), ("fed_funds", 63), ("ust_10y", 21), ("usd_broad", 21)):
            if col in lv:
                lv[f"{col}_chg_{n}"] = lv[col] - lv[col].shift(n)
        df = df.merge(lv, left_on="date", right_index=True, how="left")

    # cross-sectional ranks within each date
    for src, dst in (
        ("ret_5", "rank_ret_5"),
        ("ret_21", "rank_ret_21"),
        ("vol_21", "rank_vol_21"),
        ("log_dollar_volume", "rank_dollar_volume"),
        ("ret_1", "rank_ret_1"),
        ("ret_63", "rank_ret_63"),
        ("ret_252", "rank_ret_252"),
        ("mom_12_1", "rank_mom_12_1"),
        ("resid_ret_5", "rank_resid_ret_5"),
        ("resid_ret_21", "rank_resid_ret_21"),
        ("idio_vol_63", "rank_idio_vol_63"),
        ("beta_63", "rank_beta_63"),
        ("dist_52w_high", "rank_dist_52w_high"),
        ("volume_z_21", "rank_volume_z_21"),
        ("rsi_14", "rank_rsi_14"),
        ("sma_50", "rank_sma_50"),
        ("filing_reaction", "rank_filing_reaction"),
        *((r, f"rank_{r}") for r in FUNDAMENTAL_RATIOS),
    ):
        if src in df:
            df[dst] = df.groupby("date")[src].rank(pct=True)
    df["dow"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month
    for c in ALL_FEATURES:
        if c not in df:
            df[c] = np.nan
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)[["symbol", "date", *ALL_FEATURES]]


def add_targets(prices: pd.DataFrame, horizons: tuple[int, ...] = (1, 5)) -> pd.DataFrame:
    """Forward log returns from close t to close t+h (labels — never used as features).

    fwd_ret_h  absolute forward return;  up_h  = 1 if it is > 0.
    fwd_xret_h excess forward return vs the same day's cross-sectional mean;  xup_h = 1 if the stock beats the
               day's median (balanced 50/50, so the label is about ranking stocks, not timing the market)."""
    p = prices.sort_values(["symbol", "date"]).copy()
    p["date"] = pd.to_datetime(p["date"])
    px = p["adj_close"].fillna(p["close"])
    out = p[["symbol", "date"]].copy()
    for h in horizons:
        r = np.log(px.groupby(p["symbol"]).shift(-h) / px)
        out[f"fwd_ret_{h}"] = r
        out[f"up_{h}"] = (r > 0).astype(float).where(r.notna())
        by_day = r.groupby(out["date"])
        out[f"fwd_xret_{h}"] = r - by_day.transform("mean")
        out[f"xup_{h}"] = (r > by_day.transform("median")).astype(float).where(r.notna())
    return out
