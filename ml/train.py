"""Training entry point: python -m ml.train --config ml/configs/short_gbm.yaml [--dry-run]

--dry-run builds a tiny synthetic panel (no network, no lake), runs 2 folds with small models and logs to
a temporary MLflow store — it must finish in well under a minute on a laptop CPU.
"""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import roc_auc_score

from ml.backtest.metrics import long_top_quantile, prediction_metrics
from ml.datasets.walkforward import Fold, split, yearly_folds
from ml.features import (
    CALENDAR,
    FEATURE_GROUPS,
    FEATURES_V1,
    MACRO_LEVELS,
    add_targets,
    compute_features,
    filings_from_fundamentals,
)
from ml.features.fundamentals import fundamental_events, industry_groups
from ml.models.zoo import build

log = logging.getLogger("ml.train")
REPO = Path(__file__).resolve().parents[1]


def synthetic_panel(
    n_symbols: int = 30, n_days: int = 900, seed: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Random walks with a weak momentum effect, so models have something (small) to learn."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=n_days)
    rows = []
    for s in range(n_symbols):
        r = np.zeros(n_days)
        for t in range(1, n_days):
            r[t] = 0.05 * r[t - 1] + rng.normal(0.0003, 0.02)
        close = 50 * np.exp(np.cumsum(r))
        openp = close * np.exp(rng.normal(0, 0.003, n_days))
        rows.append(
            pd.DataFrame(
                {
                    "symbol": f"S{s:02d}",
                    "date": dates,
                    "open": openp,
                    "close": close,
                    "adj_close": close,
                    "high": np.maximum(openp, close) * 1.005,
                    "low": np.minimum(openp, close) * 0.995,
                    "volume": rng.integers(1e5, 1e6, n_days),
                }
            )
        )
    prices = pd.concat(rows, ignore_index=True)
    spy = prices.groupby("date")["close"].mean().rename("adj_close").reset_index().assign(symbol="SPY")
    spy["close"] = spy["adj_close"]
    vix = spy.assign(symbol="^VIX", close=20.0, adj_close=20.0)
    return prices, pd.concat([spy, vix], ignore_index=True)


@dataclass
class Lake:
    prices: pd.DataFrame
    market: pd.DataFrame | None = None
    macro: pd.DataFrame | None = None
    filings: pd.DataFrame | None = None
    fund_events: pd.DataFrame | None = None
    industries: pd.Series | None = None


def load_lake(cfg: dict[str, Any], lake_dir: Path | None = None) -> Lake:
    lake = lake_dir or REPO / cfg["data"]["lake"]
    prices = pd.read_parquet(lake / f"{cfg['data']['prices']}.parquet")
    prices = prices[pd.to_datetime(prices["date"]) >= pd.Timestamp(cfg["data"]["start"])]

    def opt(name: str) -> pd.DataFrame | None:
        return pd.read_parquet(lake / name) if (lake / name).exists() else None

    fund, sectors = opt("fundamentals_us.parquet"), opt("sectors_us.parquet")
    return Lake(
        prices=prices,
        market=opt("market_yahoo.parquet"),
        macro=opt("macro_fred.parquet"),
        filings=filings_from_fundamentals(fund) if fund is not None else None,
        fund_events=fundamental_events(fund) if fund is not None else None,
        industries=industry_groups(sectors) if sectors is not None else None,
    )


def resolve_features(spec: Any) -> list[str]:
    """`features:` in the config — "v1" (default), or {base: v1|none, add: [group…], drop: [group|name…]}.
    Groups: FEATURE_GROUPS keys plus "macro_levels" and "calendar"."""
    if spec is None or spec == "v1":
        return list(FEATURES_V1)
    groups = {**FEATURE_GROUPS, "macro_levels": MACRO_LEVELS, "calendar": CALENDAR}
    out = list(FEATURES_V1) if spec.get("base", "v1") == "v1" else []
    for g in spec.get("add", []):  # a group name or a single feature name
        out += [f for f in groups.get(g, [g]) if f not in out]
    drop = {f for g in spec.get("drop", []) for f in groups.get(g, [g])}
    return [f for f in out if f not in drop]


def build_dataset(lake: Lake, h: int, min_hist: int) -> pd.DataFrame:
    feats = compute_features(
        lake.prices, lake.market, lake.macro, lake.filings, lake.fund_events, lake.industries
    )
    tgt = add_targets(lake.prices, tuple(sorted({1, h})))
    df = feats.merge(tgt, on=["symbol", "date"])
    df["n_hist"] = df.groupby("symbol").cumcount()
    df = df[df["n_hist"] >= min_hist].drop(columns="n_hist")
    return df.dropna(subset=[f"up_{h}"])


def walk_forward(
    df: pd.DataFrame,
    features: list[str],
    label: str,
    h: int,
    model_cfg: dict[str, Any],
    folds: list[Fold],
    ensemble: list[str] | None = None,
    on_fold: Any = None,
) -> tuple[dict[str, pd.DataFrame], list[pd.Series]]:
    """Fit every model on each fold's training window, score the test window. Returns pooled out-of-sample
    predictions per model (plus "ensemble" = mean probability of the listed members) and LightGBM importances."""
    keep = ["symbol", "date", f"up_{h}", f"xup_{h}", f"fwd_ret_{h}", "fwd_ret_1"]
    oos: dict[str, list[pd.DataFrame]] = {m: [] for m in model_cfg}
    importances: list[pd.Series] = []
    for fold in folds:
        train, test = split(df, fold)
        train = train.dropna(subset=[label])
        Xtr, ytr = train[features], train[label]
        fold_scores: dict[str, np.ndarray] = {}
        for name, params in model_cfg.items():
            model = build(name, params).fit(Xtr, ytr)
            pred = test[keep].copy()
            pred["score"] = model.score(test[features])
            fold_scores[name] = pred["score"].to_numpy()
            oos[name].append(pred)
            if name == "lightgbm":
                importances.append(model.importance(features))  # type: ignore[attr-defined]
        if ensemble:
            pred = test[keep].copy()
            pred["score"] = np.mean([fold_scores[m] for m in ensemble], axis=0)
            oos.setdefault("ensemble", []).append(pred)
        if on_fold:
            on_fold(fold, {n: parts[-1] for n, parts in oos.items()})
        log.info(
            "fold %s done (train ≤ %s, test %s–%s)",
            fold.name,
            fold.train_end.date(),
            fold.test_start.date(),
            fold.test_end.date(),
        )
    return {n: pd.concat(p, ignore_index=True) for n, p in oos.items()}, importances


def evaluate(pred: pd.DataFrame, label: str, h: int, bt: dict[str, Any] | None = None) -> dict[str, float]:
    """Prediction metrics + (optionally) the long-only top-quantile backtest.
    auc     = AUC vs the ABSOLUTE label up_h (stock went up) — the number the promotion rule uses;
    auc_rel = AUC vs xup_h (stock beat the day's median); logloss / hit_rate are vs the training label;
    IC is the same for absolute and excess returns (ranks within a day do not change)."""
    m = prediction_metrics(pred, "score", label, f"fwd_ret_{h}")
    d = pred.dropna(subset=["score"])
    for key, col in (("auc", f"up_{h}"), ("auc_rel", f"xup_{h}")):
        dd = d.dropna(subset=[col])
        if dd[col].nunique() == 2:
            m[key] = float(roc_auc_score(dd[col], dd["score"]))
    if bt:
        m.update(
            long_top_quantile(
                pred,
                "score",
                "fwd_ret_1",
                bt["top_quantile"],
                bt["rebalance_days"],
                bt["cost_bps"],
                hold=bt.get("hold_quantile"),
                smooth=int(bt.get("smooth_span", 1)),
            )
        )
    return m


def run(cfg: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    import mlflow

    t0 = time.time()
    h = int(cfg["horizon"])
    label = f"{cfg.get('target', 'up')}_{h}"
    features = resolve_features(cfg.get("features"))
    if dry_run:
        prices, market = synthetic_panel()
        lake = Lake(prices, market)
        test_years = [2023, 2024]
        min_hist = 120
        model_cfg = {
            k: ({**v, "n_estimators": 30} if k in ("lightgbm", "xgboost") else v)
            for k, v in cfg["models"].items()
        }
        tmp = tempfile.mkdtemp(prefix="mlruns-dry-")
        tracking = f"sqlite:///{tmp}/mlflow.db"
    else:
        lake = load_lake(cfg)
        test_years = cfg["validation"]["test_years"]
        min_hist = cfg["data"]["min_history_days"]
        model_cfg = cfg["models"]
        (REPO / "mlruns").mkdir(exist_ok=True)
        tracking = cfg["mlflow"]["tracking_uri"].replace("sqlite:///mlruns", f"sqlite:///{REPO}/mlruns")
    df = build_dataset(lake, h, min_hist)
    log.info(
        "dataset: %d rows, %d symbols, %s → %s, %d features, label %s",
        len(df),
        df["symbol"].nunique(),
        df["date"].min().date(),
        df["date"].max().date(),
        len(features),
        label,
    )

    mlflow.set_tracking_uri(tracking)
    mlflow.set_experiment(cfg["mlflow"]["experiment"] + ("_dryrun" if dry_run else ""))
    folds = list(yearly_folds(df["date"], test_years, h, int(cfg["validation"]["embargo_days"])))
    results: dict[str, Any] = {}
    with mlflow.start_run(run_name=cfg["name"] + ("-dry" if dry_run else "")) as run:
        mlflow.log_params(
            {
                "horizon": h,
                "label": label,
                "n_rows": len(df),
                "n_symbols": df["symbol"].nunique(),
                "n_features": len(features),
                "folds": ",".join(f.name for f in folds),
                "dry_run": dry_run,
            }
        )
        mlflow.log_dict(cfg, "config.yaml")
        mlflow.log_dict({"features": features}, "features.json")

        def log_fold(fold: Fold, preds: dict[str, pd.DataFrame]) -> None:
            for name, pred in preds.items():
                for k, v in evaluate(pred, label, h).items():
                    if np.isfinite(v):
                        mlflow.log_metric(f"{name}.{k}.{fold.name}", v)

        oos, importances = walk_forward(
            df, features, label, h, model_cfg, folds, cfg.get("ensemble"), on_fold=log_fold
        )
        for name, allp in oos.items():
            m = evaluate(allp, label, h, cfg["backtest"])
            results[name] = m
            mlflow.log_metrics({f"{name}.{k}": v for k, v in m.items() if np.isfinite(v)})
        if importances:
            imp = pd.concat(importances, axis=1).mean(axis=1).sort_values(ascending=False)
            mlflow.log_dict(imp.round(2).to_dict(), "lightgbm_importance.json")
            results["_top_features"] = list(imp.head(10).index)
        results["_run_id"] = run.info.run_id
        results["_seconds"] = round(time.time() - t0, 1)
        if not dry_run and cfg.get("export"):
            export(cfg, df, features, label, model_cfg, run.info.run_id, results, oos)
    return results


def _isotonic_table(x: np.ndarray, y: np.ndarray, bins: int = 20) -> dict[str, list[float]]:
    """Monotone map score → E[y | score] as an interpolation table. Scores are first grouped into equal-count
    quantile bins (thousands of rows each) and isotonic regression runs on the bin means — fitting it on raw
    rows lets a handful of extreme scores pin the tails at 0 / 1. Outside the table np.interp clamps."""
    from sklearn.isotonic import IsotonicRegression

    ok = np.isfinite(x) & np.isfinite(y)
    xs, ys = x[ok], y[ok]
    order = np.argsort(xs, kind="stable")
    parts = np.array_split(order, bins)
    bx = np.array([np.median(xs[p]) for p in parts])
    by = np.array([ys[p].mean() for p in parts])
    w = np.array([len(p) for p in parts], dtype=float)
    fit = IsotonicRegression(out_of_bounds="clip").fit(bx, by, sample_weight=w).predict(bx)
    return {"x": [float(v) for v in bx], "y": [float(v) for v in fit]}


def export(
    cfg: dict[str, Any],
    df: pd.DataFrame,
    features: list[str],
    label: str,
    model_cfg: dict[str, Any],
    run_id: str,
    results: dict[str, Any],
    oos: dict[str, pd.DataFrame],
) -> None:
    """Refit the chosen model (lightgbm, xgboost or the ensemble) on all data and save a bundle for batch
    inference. Two calibration tables are fitted on the pooled OUT-OF-SAMPLE predictions: score → P(up over the
    horizon) and score → expected return, so the website shows calibrated numbers whatever the training label."""
    name = cfg["export"]["model"]
    h = int(cfg["horizon"])
    members = list(cfg.get("ensemble") or []) if name == "ensemble" else [name]
    out = REPO / cfg["export"]["dir"]
    out.mkdir(parents=True, exist_ok=True)
    data = df.dropna(subset=[label])
    files = {}
    for mname in members:
        model = build(mname, model_cfg[mname]).fit(data[features], data[label])
        if mname == "lightgbm":
            model.m.booster_.save_model(str(out / "model.txt"))  # type: ignore[attr-defined]
            files["lightgbm"] = "model.txt"
        elif mname == "xgboost":
            model.m.get_booster().save_model(str(out / "xgb.json"))  # type: ignore[attr-defined]
            files["xgboost"] = "xgb.json"
    pred = oos[name].dropna(subset=["score"])
    meta = {
        "model": name,
        "members": files,
        "horizon": h,
        "label": label,
        "features": features,
        "run_id": run_id,
        "trained_through": str(df["date"].max().date()),
        "calibration": {
            "prob_up": _isotonic_table(pred["score"].to_numpy(), pred[f"up_{h}"].to_numpy()),
            "expected_return": _isotonic_table(pred["score"].to_numpy(), pred[f"fwd_ret_{h}"].to_numpy()),
        },
        "oos_metrics": results.get(name, {}),
        "baseline_metrics": {k: results[k] for k in results if k.startswith("baseline")},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=float))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("mlflow", "alembic", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="python -m ml.train")
    p.add_argument("--config", required=True)
    p.add_argument("--dry-run", action="store_true", help="tiny synthetic data, CPU, < 1 min")
    a = p.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text())
    res = run(cfg, dry_run=a.dry_run)
    table = pd.DataFrame({k: v for k, v in res.items() if not k.startswith("_")}).T
    cols = [
        c
        for c in (
            "auc",
            "auc_rel",
            "ic_mean",
            "ic_tstat",
            "hit_rate",
            "strat_sharpe",
            "bench_sharpe",
            "strat_max_dd",
            "turnover_2sided",
        )
        if c in table
    ]
    print(table[cols].round(4).to_string())
    print(f"top features: {res.get('_top_features')}  run_id={res['_run_id']}  {res['_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
