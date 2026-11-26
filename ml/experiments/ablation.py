"""Dev-fold ablation for the short-term model: python -m ml.experiments.ablation [--out docs/ABLATION_DEV.md]

Every design choice (label, feature groups, hyper-parameters, ensemble, portfolio rule) is made here on the
2016–2018 DEV folds only. The 2019–2026 test folds are used once, by `python -m ml.train`, with the config this
script points to — so the reported test numbers are not tuned on the test period (docs/GPU_PLAN.md §4.1).

Selection is greedy and uses the mean daily rank IC (the ranking signal the strategy trades on): a step is kept
if it raises dev IC. Results are appended to a JSON-lines log so an interrupted run keeps what it computed.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ml.backtest.metrics import long_top_quantile
from ml.datasets.walkforward import yearly_folds
from ml.train import REPO, build_dataset, evaluate, load_lake, resolve_features, walk_forward

log = logging.getLogger("ml.ablation")
DEV_YEARS = [2016, 2017, 2018]
LGBM_REG = {
    "n_estimators": 300,
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 1000,
    "colsample_bytree": 0.5,
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m ml.experiments.ablation")
    ap.add_argument("--config", default="ml/configs/short_gbm_v1.yaml")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "ABLATION_DEV.md")
    ap.add_argument("--log", type=Path, default=REPO / "mlruns" / "ablation_dev.jsonl")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text())
    h = int(cfg["horizon"])
    t0 = time.time()

    lake = load_lake(cfg)
    lake.prices = lake.prices[pd.to_datetime(lake.prices["date"]) <= pd.Timestamp(f"{DEV_YEARS[-1]}-12-31")]
    df = build_dataset(lake, h, cfg["data"]["min_history_days"])
    folds = list(yearly_folds(df["date"], DEV_YEARS, h, int(cfg["validation"]["embargo_days"])))
    log.info("dev panel: %d rows, %s → %s", len(df), df["date"].min().date(), df["date"].max().date())
    lgbm_v1 = cfg["models"]["lightgbm"]
    rows: list[dict[str, Any]] = []

    def trial(
        step: str, spec: Any, label: str, models: dict[str, Any], ens: list[str] | None = None
    ) -> tuple[dict[str, float], pd.DataFrame]:
        feats = resolve_features(spec)
        oos, _ = walk_forward(df, feats, f"{label}_{h}", h, models, folds, ens)
        name = "ensemble" if ens else "lightgbm"
        m = evaluate(oos[name], f"{label}_{h}", h, cfg["backtest"])
        row = {"step": step, "label": label, "n_features": len(feats), "spec": spec, "model": name, **m}
        rows.append(row)
        with a.log.open("a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        log.info(
            "%-34s IC %.4f (t %.2f) AUC %.4f AUC_rel %.4f",
            step,
            m["ic_mean"],
            m["ic_tstat"],
            m.get("auc", float("nan")),
            m.get("auc_rel", float("nan")),
        )
        return m, oos[name]

    a.log.parent.mkdir(exist_ok=True)
    a.log.write_text("")
    # 1. reference and label choice
    up_m, _ = trial("v1 · label up (old model)", "v1", "up", {"lightgbm": lgbm_v1})
    x_m, _ = trial("v1 · label xup", "v1", "xup", {"lightgbm": lgbm_v1})
    label = "xup" if x_m["ic_mean"] > up_m["ic_mean"] else "up"
    # hy_spread is a data defect (FRED serves only the last 3 years of ICE BofA series) → dropped regardless
    spec: dict[str, Any] = {"base": "v1", "add": [], "drop": ["hy_spread"]}
    best_m, _ = trial(f"− hy_spread (empty before 2023-10) · {label}", spec, label, {"lightgbm": lgbm_v1})
    # 2. greedy feature groups
    for group in ("residual", "ranks", "filings", "macro_changes"):
        cand = {**spec, "add": [*spec["add"], group]}
        m, _ = trial(f"+ {group}", cand, label, {"lightgbm": lgbm_v1})
        if m["ic_mean"] > best_m["ic_mean"]:
            spec, best_m = cand, m
    for group in ("macro_levels", "calendar"):
        cand = {**spec, "drop": [*spec["drop"], group]}
        m, _ = trial(f"− {group}", cand, label, {"lightgbm": lgbm_v1})
        if m["ic_mean"] > best_m["ic_mean"]:
            spec, best_m = cand, m
    # 3. hyper-parameters and ensemble
    lgbm = lgbm_v1
    m, _ = trial("LightGBM regularised", spec, label, {"lightgbm": LGBM_REG})
    if m["ic_mean"] > best_m["ic_mean"]:
        lgbm, best_m = LGBM_REG, m
    models = {"lightgbm": lgbm, "xgboost": cfg["models"]["xgboost"]}
    m, ens_pred = trial("ensemble LightGBM + XGBoost", spec, label, models, ["lightgbm", "xgboost"])
    use_ens = m["ic_mean"] > best_m["ic_mean"]
    if use_ens:
        best_m = m
        pred = ens_pred
    else:
        _, pred = trial("final (LightGBM)", spec, label, {"lightgbm": lgbm})
    # 4. portfolio rule on the chosen predictions (dev folds only)
    bt = cfg["backtest"]
    grid = []
    for top in (0.1, 0.2):
        for hold in (None, 2 * top, 3 * top):
            for smooth in (1, 3, 5):
                r = long_top_quantile(
                    pred, "score", "fwd_ret_1", top, bt["rebalance_days"], bt["cost_bps"], hold, smooth
                )
                grid.append({"top": top, "hold": hold, "smooth": smooth, **r})
    g = pd.DataFrame(grid)
    g["excess_sharpe"] = g["strat_sharpe"] - g["bench_sharpe"]
    best_rule = g.sort_values("excess_sharpe", ascending=False).iloc[0]

    chosen = {
        "target": label,
        "features": spec,
        "lightgbm": lgbm,
        "ensemble": ["lightgbm", "xgboost"] if use_ens else None,
        "backtest": {
            "top_quantile": round(float(best_rule["top"]), 2),
            "hold_quantile": None if pd.isna(best_rule["hold"]) else round(float(best_rule["hold"]), 2),
            "smooth_span": int(best_rule["smooth"]),
        },
    }
    write_report(a.out, rows, g, chosen, round(time.time() - t0))
    print(json.dumps(chosen, indent=2))
    return 0


def _md(df: pd.DataFrame, digits: int) -> str:
    """Markdown table without the optional `tabulate` dependency."""

    def cell(v: Any) -> str:
        if isinstance(v, float):
            return "—" if pd.isna(v) else f"{v:.{digits}f}"
        return "—" if v is None else str(v)

    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def write_report(
    out: Path, rows: list[dict[str, Any]], grid: pd.DataFrame, chosen: dict[str, Any], secs: int
) -> None:
    r = pd.DataFrame(rows)
    cols = [
        "step",
        "label",
        "n_features",
        "ic_mean",
        "ic_tstat",
        "auc",
        "auc_rel",
        "strat_sharpe",
        "bench_sharpe",
        "turnover_2sided",
    ]
    g = grid.sort_values("excess_sharpe", ascending=False)
    gcols = [
        "top",
        "hold",
        "smooth",
        "strat_sharpe",
        "bench_sharpe",
        "excess_sharpe",
        "strat_cagr",
        "bench_cagr",
        "strat_max_dd",
        "turnover_2sided",
    ]
    text = [
        "# Dev-fold ablation — short-term model (5 days)",
        "",
        f"Generated by `python -m ml.experiments.ablation` ({secs} s, CPU). Dev folds: {DEV_YEARS} "
        "(expanding window from 2011, purge 5 + embargo 5 sessions). **The 2019–2026 test folds are not used "
        "here.** Each step is kept only if it raises the dev mean daily rank IC.",
        "",
        "## Model steps",
        "",
        _md(r[cols], 4),
        "",
        "## Portfolio rule (chosen model, dev folds, 10 bps per side)",
        "",
        _md(g[gcols].head(12), 3),
        "",
        "## Chosen configuration",
        "",
        "```json",
        json.dumps(chosen, indent=2),
        "```",
        "",
    ]
    out.write_text("\n".join(text))


if __name__ == "__main__":
    raise SystemExit(main())
