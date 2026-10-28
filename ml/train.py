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
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ml.backtest.metrics import long_top_quantile, prediction_metrics
from ml.datasets.walkforward import split, yearly_folds
from ml.features import FEATURES, add_targets, compute_features
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


def load_lake(cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    lake = REPO / cfg["data"]["lake"]
    prices = pd.read_parquet(lake / f"{cfg['data']['prices']}.parquet")
    prices = prices[pd.to_datetime(prices["date"]) >= pd.Timestamp(cfg["data"]["start"])]
    market = (
        pd.read_parquet(lake / "market_yahoo.parquet") if (lake / "market_yahoo.parquet").exists() else None
    )
    macro = pd.read_parquet(lake / "macro_fred.parquet") if (lake / "macro_fred.parquet").exists() else None
    return prices, market, macro


def build_dataset(
    prices: pd.DataFrame, market: pd.DataFrame | None, macro: pd.DataFrame | None, h: int, min_hist: int
) -> pd.DataFrame:
    feats = compute_features(prices, market, macro)
    tgt = add_targets(prices, (1, h))
    df = feats.merge(tgt, on=["symbol", "date"])
    df["n_hist"] = df.groupby("symbol").cumcount()
    df = df[df["n_hist"] >= min_hist].drop(columns="n_hist")
    return df.dropna(subset=[f"up_{h}"])


def run(cfg: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    import mlflow

    t0 = time.time()
    h = int(cfg["horizon"])
    target_up, target_ret = f"up_{h}", f"fwd_ret_{h}"
    if dry_run:
        prices, market = synthetic_panel()
        macro = None
        test_years = [2023, 2024]
        min_hist = 120
        model_cfg = {
            k: ({**v, "n_estimators": 30} if k in ("lightgbm", "xgboost") else v)
            for k, v in cfg["models"].items()
        }
        tmp = tempfile.mkdtemp(prefix="mlruns-dry-")
        tracking = f"sqlite:///{tmp}/mlflow.db"
    else:
        prices, market, macro = load_lake(cfg)
        test_years = cfg["validation"]["test_years"]
        min_hist = cfg["data"]["min_history_days"]
        model_cfg = cfg["models"]
        (REPO / "mlruns").mkdir(exist_ok=True)
        tracking = cfg["mlflow"]["tracking_uri"].replace("sqlite:///mlruns", f"sqlite:///{REPO}/mlruns")
    df = build_dataset(prices, market, macro, h, min_hist)
    log.info(
        "dataset: %d rows, %d symbols, %s → %s",
        len(df),
        df["symbol"].nunique(),
        df["date"].min().date(),
        df["date"].max().date(),
    )

    mlflow.set_tracking_uri(tracking)
    mlflow.set_experiment(cfg["mlflow"]["experiment"] + ("_dryrun" if dry_run else ""))
    folds = list(yearly_folds(df["date"], test_years, h, int(cfg["validation"]["embargo_days"])))
    results: dict[str, Any] = {}
    oos: dict[str, list[pd.DataFrame]] = {m: [] for m in model_cfg}
    importances: list[pd.Series] = []
    with mlflow.start_run(run_name=cfg["name"] + ("-dry" if dry_run else "")) as run:
        mlflow.log_params(
            {
                "horizon": h,
                "n_rows": len(df),
                "n_symbols": df["symbol"].nunique(),
                "n_features": len(FEATURES),
                "folds": ",".join(f.name for f in folds),
                "dry_run": dry_run,
            }
        )
        mlflow.log_dict(cfg, "config.yaml")
        for fold in folds:
            train, test = split(df, fold)
            Xtr, ytr = train[FEATURES], train[target_up]
            for name, params in model_cfg.items():
                model = build(name, params).fit(Xtr, ytr)
                pred = test[["symbol", "date", target_up, target_ret, "fwd_ret_1"]].copy()
                pred["score"] = model.score(test[FEATURES])
                oos[name].append(pred)
                m = prediction_metrics(pred, "score", target_up, target_ret)
                for k, v in m.items():
                    mlflow.log_metric(f"{name}.{k}.{fold.name}", v)
                if name == "lightgbm":
                    importances.append(model.importance(FEATURES))
            log.info(
                "fold %s done (train ≤ %s, test %s–%s)",
                fold.name,
                fold.train_end.date(),
                fold.test_start.date(),
                fold.test_end.date(),
            )
        bt = cfg["backtest"]
        for name, parts in oos.items():
            allp = pd.concat(parts, ignore_index=True)
            m = prediction_metrics(allp, "score", target_up, target_ret)
            m.update(
                long_top_quantile(
                    allp, "score", "fwd_ret_1", bt["top_quantile"], bt["rebalance_days"], bt["cost_bps"]
                )
            )
            results[name] = m
            mlflow.log_metrics({f"{name}.{k}": v for k, v in m.items() if np.isfinite(v)})
        if importances:
            imp = pd.concat(importances, axis=1).mean(axis=1).sort_values(ascending=False)
            mlflow.log_dict(imp.round(2).to_dict(), "lightgbm_importance.json")
            results["_top_features"] = list(imp.head(10).index)
        results["_run_id"] = run.info.run_id
        results["_seconds"] = round(time.time() - t0, 1)
        if not dry_run and cfg.get("export"):
            export(cfg, df, model_cfg, run.info.run_id, results)
    return results


def export(
    cfg: dict[str, Any], df: pd.DataFrame, model_cfg: dict[str, Any], run_id: str, results: dict[str, Any]
) -> None:
    """Refit the chosen model on all data and save a bundle the batch-inference job can load."""
    name = cfg["export"]["model"]
    out = REPO / cfg["export"]["dir"]
    out.mkdir(parents=True, exist_ok=True)
    model = build(name, model_cfg[name]).fit(df[FEATURES], df[f"up_{cfg['horizon']}"])
    model.m.booster_.save_model(str(out / "model.txt"))
    meta = {
        "model": name,
        "horizon": cfg["horizon"],
        "features": FEATURES,
        "run_id": run_id,
        "trained_through": str(df["date"].max().date()),
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
