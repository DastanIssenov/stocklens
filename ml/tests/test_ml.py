import numpy as np
import pandas as pd
import pytest

from ml.backtest.metrics import long_top_quantile, prediction_metrics
from ml.datasets.walkforward import split, yearly_folds
from ml.features import FEATURES, add_targets, compute_features
from ml.train import build_dataset, synthetic_panel


@pytest.fixture(scope="module")
def panel():  # type: ignore[no-untyped-def]
    return synthetic_panel(n_symbols=8, n_days=400, seed=1)


def test_features_have_no_lookahead(panel) -> None:  # type: ignore[no-untyped-def]
    """Appending future rows (and changing them wildly) must not change features of earlier dates."""
    prices, market = panel
    cut = prices["date"].sort_values().unique()[300]
    past = prices[prices["date"] <= cut]
    future = prices[prices["date"] > cut].copy()
    future[["open", "high", "low", "close", "adj_close"]] *= 3.0  # a crash/bubble that must not leak back
    a = compute_features(past, market[market["date"] <= cut])
    b = compute_features(pd.concat([past, future]), market)
    b = b[b["date"] <= cut]
    cols = [c for c in FEATURES if c not in ("vix",)]
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
    df = build_dataset(prices, market, None, h=5, min_hist=60)
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
