from functools import partial

import numpy as np
import pandas as pd
import pytest

from ml.backtest.metrics import long_top_quantile, prediction_metrics
from ml.datasets.walkforward import split, yearly_folds
from ml.features import ALL_FEATURES, FEATURES_V1, add_targets, compute_features
from ml.features.fundamentals import fundamental_events
from ml.train import Lake, build_dataset, resolve_features, synthetic_panel


@pytest.fixture(scope="module")
def panel():  # type: ignore[no-untyped-def]
    return synthetic_panel(n_symbols=8, n_days=400, seed=1)


def _filings_and_macro(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Quarterly reports at mixed times of day (date-only, before the close, after the close) and daily macro."""
    rng = np.random.default_rng(3)
    days = pd.to_datetime(np.sort(prices["date"].unique()))
    fil = []
    for sym in prices["symbol"].unique():
        for d in days[rng.integers(5, 60) :: 63]:
            hour = rng.choice([0, 14, 21])  # 00:00 = date only, 14:00 UTC = intraday, 21:00 UTC = after close
            fil.append(
                {"symbol": sym, "available_at": pd.Timestamp(d).tz_localize("UTC") + pd.Timedelta(hours=hour)}
            )
    mac = [
        {"name": n, "available_at": d + pd.Timedelta(days=1), "value": v}
        for n in ("ust_10y_2y", "fed_funds", "ust_10y", "usd_broad")
        for d, v in zip(days, np.cumsum(rng.normal(0, 0.05, len(days))), strict=True)
    ]
    return pd.DataFrame(fil), pd.DataFrame(mac)


def _fact(
    rows: list[dict[str, object]],
    meta: dict[str, object],
    metric: str,
    start: pd.Timestamp | None,
    end: pd.Timestamp,
    value: float,
    unit: str = "USD",
) -> None:
    rows.append(
        {
            **meta,
            "metric": metric,
            "unit": unit,
            "value": value,
            "period_start": None if start is None else str(start.date()),
            "period_end": str(end.date()),
        }
    )


def _synthetic_fundamentals(prices: pd.DataFrame) -> pd.DataFrame:
    """10-Q / 10-K facts like SEC companyfacts: 3-month and year-to-date values with prior-year comparatives,
    fiscal-year values in 10-Ks, balance-sheet instants, published 25–40 days after the quarter at mixed times."""
    rng = np.random.default_rng(7)
    rows = []
    q_ends = pd.date_range("2020-03-31", "2023-12-31", freq="QE")
    for sym in prices["symbol"].unique():
        base = {m: rng.uniform(50, 150) for m in ("revenue", "net_income", "cfo", "gross_profit")}

        def q_val(m: str, end: pd.Timestamp, base: dict[str, float] = base) -> float:
            return base[m] * (1 + 0.02 * (end.year - 2019)) * (1 + 0.1 * end.quarter)

        for end in q_ends:
            fy_start = pd.Timestamp(end.year, 1, 1)
            avail = end + pd.Timedelta(days=int(rng.integers(25, 40)), hours=int(rng.choice([0, 14, 21])))
            form = "10-K" if end.quarter == 4 else "10-Q"
            acc = f"{sym}-{end.date()}"

            meta = {"symbol": sym, "form": form, "accession": acc, "available_at": avail.tz_localize("UTC")}
            add = partial(_fact, rows, meta)
            for m in base:
                for yr in (0, 1):  # current period and the prior-year comparative
                    e = end - pd.DateOffset(years=yr)
                    q_start = (e - pd.offsets.QuarterBegin(startingMonth=1)).normalize()
                    ytd = sum(
                        q_val(m, qe) for qe in pd.date_range(fy_start - pd.DateOffset(years=yr), e, freq="QE")
                    )
                    if form == "10-Q":
                        add(m, q_start, e, q_val(m, e))
                        add(m, fy_start - pd.DateOffset(years=yr), e, ytd)
                    else:
                        add(m, fy_start - pd.DateOffset(years=yr), e, ytd)
            for m, v in (("equity", 400.0), ("assets", 1000.0), ("liabilities", 600.0)):
                add(m, None, end, v * (1 + 0.01 * end.month))
            add("shares_diluted", end - pd.Timedelta(days=90), end, 10.0, "shares")
    return pd.DataFrame(rows)


def test_ttm_from_ytd_and_comparatives() -> None:
    """TTM at a Q2 end = last fiscal year + current half-year − prior-year half-year."""
    from ml.features.fundamentals import _ttm_at

    t = pd.Timestamp
    d = {
        (t("2022-01-01"), t("2022-12-31")): 400.0,  # FY 2022
        (t("2023-01-01"), t("2023-06-30")): 220.0,  # H1 2023
        (t("2022-01-01"), t("2022-06-30")): 190.0,  # H1 2022 (comparative)
        (t("2023-04-01"), t("2023-06-30")): 115.0,  # Q2 2023
    }
    assert _ttm_at(d, t("2023-06-30")) == 400.0 + 220.0 - 190.0
    assert _ttm_at(d, t("2022-12-31")) == 400.0
    assert np.isnan(_ttm_at(d, t("2021-06-30")))


def test_features_have_no_lookahead(panel) -> None:  # type: ignore[no-untyped-def]
    """Appending future rows (and changing them wildly) must not change features of earlier dates —
    including filing features (future reports are passed in on purpose) and macro changes."""
    prices, market = panel
    filings, macro = _filings_and_macro(prices)
    cut = prices["date"].sort_values().unique()[300]
    past = prices[prices["date"] <= cut]
    future = prices[prices["date"] > cut].copy()
    future[["open", "high", "low", "close", "adj_close"]] *= 3.0  # a crash/bubble that must not leak back
    known = macro[macro["available_at"] <= cut]
    events = fundamental_events(_synthetic_fundamentals(prices))  # includes reports published after the cut
    syms = sorted(prices["symbol"].unique())
    industries = pd.Series(["A" if i % 2 else "B" for i in range(len(syms))], index=syms)
    a = compute_features(past, market[market["date"] <= cut], known, filings, events, industries)
    b = compute_features(pd.concat([past, future]), market, macro, filings, events, industries)
    b = b[b["date"] <= cut]
    for c in ("filing_reaction", "ust_10y_2y_chg_63", "rank_ep", "rank_rev_growth", "ind_rel_ret_21"):
        assert a[c].notna().sum() > 100, c
    cols = [c for c in ALL_FEATURES if c not in ("vix",)]
    pd.testing.assert_frame_equal(
        a[["symbol", "date", *cols]].reset_index(drop=True),
        b[["symbol", "date", *cols]].reset_index(drop=True),
        check_exact=False,
        atol=1e-9,
    )


def test_targets_are_forward_looking(panel) -> None:  # type: ignore[no-untyped-def]
    prices, _ = panel
    t = add_targets(prices, (1, 5))
    s = prices[prices["symbol"] == "S00"].sort_values("date")
    expected = np.log(s["adj_close"].shift(-5) / s["adj_close"]).to_numpy()
    got = t[t["symbol"] == "S00"].sort_values("date")["fwd_ret_5"].to_numpy()
    np.testing.assert_allclose(got[:-5], expected[:-5])
    assert np.isnan(got[-5:]).all()


def test_walk_forward_purges_and_embargoes(panel) -> None:  # type: ignore[no-untyped-def]
    prices, market = panel
    df = build_dataset(Lake(prices, market), h=5, min_hist=60)
    folds = list(yearly_folds(df["date"], [2022], horizon=5, embargo=5))
    assert len(folds) == 1
    train, test = split(df, folds[0])
    cal = sorted(df["date"].unique())
    gap = cal.index(test["date"].min()) - cal.index(train["date"].max())
    assert gap >= 10  # horizon (5) + embargo (5) trading days between last train label start and test
    assert train["date"].max() < test["date"].min()


def test_metrics_and_backtest() -> None:
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2024-01-01", periods=60)
    rows = []
    for d in dates:
        for s in range(20):
            ret = rng.normal(0, 0.01)
            rows.append(
                {
                    "date": d,
                    "symbol": f"S{s}",
                    "fwd_ret_5": ret,
                    "fwd_ret_1": ret / 5,
                    "up_5": float(ret > 0),
                    "score": 0.5 + ret * 10,
                }
            )  # perfect ranking signal
    df = pd.DataFrame(rows)
    m = prediction_metrics(df, "score", "up_5", "fwd_ret_5")
    assert m["auc"] > 0.99 and m["ic_mean"] > 0.99
    bt = long_top_quantile(df, "score", "fwd_ret_1", top=0.2, rebalance=5, cost_bps=10)
    assert bt["strat_cagr"] > bt["bench_cagr"]
    assert 0 <= bt["turnover_2sided"] <= 2


def test_dry_run_end_to_end(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import yaml

    from ml.train import REPO, run

    cfg = yaml.safe_load((REPO / "ml/configs/short_gbm.yaml").read_text())
    res = run(cfg, dry_run=True)
    assert {"baseline_persistence", "logreg", "lightgbm", "xgboost"} <= set(res)
    assert 0.3 < res["lightgbm"]["auc"] < 0.7


def test_filing_counts_from_first_session_after_acceptance() -> None:
    """A report accepted after the close (or with a date-only timestamp) is news for the NEXT session."""
    dates = pd.bdate_range("2024-01-01", periods=30)
    px = 100 * np.exp(np.linspace(0, 0.1, 30))
    prices = pd.DataFrame(
        {
            "symbol": "A",
            "date": dates,
            "open": px,
            "high": px,
            "low": px,
            "close": px,
            "adj_close": px,
            "volume": 1000,
        }
    )
    d10 = dates[10]
    cases = {
        d10.tz_localize("UTC") + pd.Timedelta(hours=14): 10,  # intraday → same session
        d10.tz_localize("UTC") + pd.Timedelta(hours=21): 11,  # after the close → next session
        d10.tz_localize("UTC"): 11,  # date only → next session (time unknown)
    }
    for ts, first in cases.items():
        f = compute_features(prices, None, None, pd.DataFrame({"symbol": ["A"], "available_at": [ts]}))
        days = f["days_since_filing"].to_numpy()
        assert np.isnan(days[:first]).all() and days[first] == 0 and days[first + 5] == 5, ts
        react = f["filing_reaction"].to_numpy()
        assert np.isnan(react[: first + 1]).all() and np.isfinite(react[first + 1])


def test_excess_targets_are_cross_sectional(panel) -> None:  # type: ignore[no-untyped-def]
    prices, _ = panel
    t = add_targets(prices, (5,)).dropna()
    by_day = t.groupby("date")
    assert by_day["fwd_xret_5"].mean().abs().max() < 1e-12
    assert abs(t["xup_5"].mean() - 0.5) < 0.07


def test_resolve_features() -> None:
    assert resolve_features("v1") == FEATURES_V1
    f = resolve_features({"base": "v1", "add": ["residual", "filings"], "drop": ["calendar", "hy_spread"]})
    assert "resid_ret_5" in f and "days_since_filing" in f
    assert not {"dow", "month", "hy_spread"} & set(f)
    assert len(f) == len(set(f))


def test_hold_band_and_smoothing_cut_turnover() -> None:
    """Noisy scores around a persistent signal: a hysteresis band and score smoothing must trade less."""
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2024-01-01", periods=120)
    base = rng.normal(0, 1, 50)
    rows = [
        {"date": d, "symbol": f"S{s}", "score": base[s] + rng.normal(0, 1), "fwd_ret_1": rng.normal(0, 0.01)}
        for d in dates
        for s in range(50)
    ]
    df = pd.DataFrame(rows)
    plain = long_top_quantile(df, "score", "fwd_ret_1", top=0.2, rebalance=5)
    band = long_top_quantile(df, "score", "fwd_ret_1", top=0.2, rebalance=5, hold=0.4)
    smooth = long_top_quantile(df, "score", "fwd_ret_1", top=0.2, rebalance=5, smooth=5)
    assert band["turnover_2sided"] < plain["turnover_2sided"]
    assert smooth["turnover_2sided"] < plain["turnover_2sided"]


def test_calibration_table_is_monotone_and_not_degenerate() -> None:
    """Rare extreme scores must not pin the displayed P(up) to 0 or 1."""
    from ml.train import _isotonic_table

    rng = np.random.default_rng(2)
    score = rng.normal(0.5, 0.03, 50_000)
    score[:3] = [0.01, 0.02, 0.99]  # a few outliers with lucky / unlucky labels
    up = (rng.random(50_000) < 0.5 + 2 * (score - 0.5)).astype(float)
    up[:3] = [1.0, 1.0, 0.0]
    t = _isotonic_table(score, up)
    assert np.all(np.diff(t["y"]) >= -1e-12) and np.all(np.diff(t["x"]) >= 0)
    assert min(t["y"]) > 0.3 and max(t["y"]) < 0.7
