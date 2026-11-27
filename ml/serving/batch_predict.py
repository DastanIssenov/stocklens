"""Batch inference for the website (docs/GPU_PLAN.md §8.2).

Loads the exported bundle (`ml/artifacts/short_gbm/{model.txt,meta.json}`), computes features with the SAME
module used in training (`ml.features`) from the Parquet lake, and upserts one row per ticker into the
website's `predictions` table for the latest date. The website serves these rows instead of mock values.

Promotion rule (§7): rows are written with `is_demo = false` only if the out-of-sample metrics pass
(IC t-stat ≥ 2, AUC ≥ 0.52, strategy Sharpe > benchmark Sharpe). Otherwise they are stored as
`is_demo = true` — the UI keeps its "Demo predictions" badge, but shows the model version.

Usage:  python -m ml.serving.batch_predict --database-url postgresql://stock:stock@localhost:55433/stock
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.features import compute_features
from ml.train import REPO, load_lake

BUNDLE = REPO / "ml" / "artifacts" / "short_gbm"


def promoted(meta: dict[str, Any]) -> bool:
    m = meta.get("oos_metrics", {})
    return bool(
        m.get("ic_tstat", 0) >= 2.0
        and m.get("auc", 0) >= 0.52
        and m.get("strat_sharpe", -9) > m.get("bench_sharpe", 9)
    )


def _interp(table: dict[str, list[float]] | None, x: np.ndarray) -> np.ndarray | None:
    if not table:
        return None
    return np.interp(x, np.asarray(table["x"]), np.asarray(table["y"]))


def model_version(meta: dict[str, Any]) -> str:
    prefix = {"lightgbm": "lgbm", "xgboost": "xgb", "ensemble": "gbm-ens"}.get(meta.get("model", ""), "lgbm")
    return f"{prefix}-cpu-{meta['run_id'][:8]}"


def _score_members(bundle: Path, meta: dict[str, Any], X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Mean probability of the bundle's members and mean TreeSHAP contributions (log-odds, bias dropped)."""
    import lightgbm as lgb

    members = meta.get("members") or {"lightgbm": "model.txt"}  # v1 bundles: one LightGBM file
    probs, contribs = [], []
    for name, fname in members.items():
        if name == "lightgbm":
            booster = lgb.Booster(model_file=str(bundle / fname))
            probs.append(booster.predict(X))
            contribs.append(booster.predict(X, pred_contrib=True)[:, :-1])
        elif name == "xgboost":
            import xgboost as xgb

            xb = xgb.Booster()
            xb.load_model(str(bundle / fname))
            dm = xgb.DMatrix(X)
            probs.append(xb.predict(dm))
            contribs.append(xb.predict(dm, pred_contribs=True)[:, :-1])
    return np.mean(probs, axis=0), np.mean(contribs, axis=0)


def predict_latest(
    bundle: Path = BUNDLE, lake: Path = REPO / "data" / "lake", as_of: str | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Score each symbol's latest session, or its latest session on or before `as_of` (YYYY-MM-DD) — used to
    match the website, which shows predictions only for its own latest stored bar."""
    meta = json.loads((bundle / "meta.json").read_text())
    data = load_lake({"data": {"prices": "prices_us", "start": "1900-01-01"}}, lake)
    if as_of:
        cut = pd.Timestamp(as_of)
        data.prices = data.prices[pd.to_datetime(data.prices["date"]) <= cut]
        if data.market is not None:
            data.market = data.market[pd.to_datetime(data.market["date"]) <= cut]
        if data.macro is not None:
            data.macro = data.macro[pd.to_datetime(data.macro["available_at"]) <= cut]
    prices = data.prices
    data.prices = prices[
        pd.to_datetime(prices["date"]) >= pd.to_datetime(prices["date"]).max() - pd.Timedelta(days=500)
    ]
    feats = compute_features(
        data.prices, data.market, data.macro, data.filings, data.fund_events, data.industries
    )
    latest = feats[feats["date"] == feats.groupby("symbol")["date"].transform("max")].reset_index(drop=True)
    X = latest[meta["features"]]
    score, contrib = _score_members(bundle, meta, X)
    cal = meta.get("calibration", {})
    # v2 bundles carry isotonic tables fitted on out-of-sample predictions; v1 used the raw probability
    prob = _interp(cal.get("prob_up"), score)
    prob = score if prob is None else prob
    exp_ret = _interp(cal.get("expected_return"), score)
    vol_h = latest["vol_21"].fillna(latest["vol_21"].median()) * math.sqrt(meta["horizon"])
    auc_edge = max(0.0, meta.get("oos_metrics", {}).get("auc", 0.5) - 0.5)
    rows = []
    for i, r in latest.iterrows():
        top = np.argsort(-np.abs(contrib[i]))[:5]
        rows.append(
            {
                "symbol": r["symbol"],
                "as_of_date": r["date"].date(),
                "prob_up": float(prob[i]),
                # v2: isotonic E[return | score] from out-of-sample folds; v1: direction edge × typical move
                "predicted_return": float(
                    exp_ret[i] if exp_ret is not None else (2 * prob[i] - 1) * vol_h[i] * 0.8
                ),
                "confidence": float(min(1.0, abs(2 * prob[i] - 1) * (0.5 + 10 * auc_edge))),
                "top_features": [
                    {
                        "name": meta["features"][j],
                        "value": None if pd.isna(X.iloc[i, j]) else round(float(X.iloc[i, j]), 5),
                        "contribution": round(float(contrib[i, j]), 5),
                    }
                    for j in top
                ],
            }
        )
    return pd.DataFrame(rows), meta


def write(df: pd.DataFrame, meta: dict[str, Any], database_url: str) -> int:
    import psycopg

    version = model_version(meta)
    is_demo = not promoted(meta)
    n = 0
    with (
        psycopg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://")) as conn,
        conn.cursor() as cur,
    ):
        cur.execute("SELECT symbol, id FROM tickers")
        ids = dict(cur.fetchall())
        for r in df.itertuples():
            tid = ids.get(r.symbol)
            if tid is None:
                continue
            cur.execute(
                """INSERT INTO predictions (ticker_id, model_version, horizon, horizon_days, as_of_date,
                       predicted_return, prob_up, confidence, top_features, is_demo)
                   VALUES (%s, %s, '5d', %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT ON CONSTRAINT uq_predictions_key DO UPDATE SET
                       predicted_return = EXCLUDED.predicted_return, prob_up = EXCLUDED.prob_up,
                       confidence = EXCLUDED.confidence, top_features = EXCLUDED.top_features,
                       is_demo = EXCLUDED.is_demo, created_at = now()""",
                (
                    tid,
                    version,
                    meta["horizon"],
                    r.as_of_date,
                    r.predicted_return,
                    r.prob_up,
                    r.confidence,
                    json.dumps(r.top_features),
                    is_demo,
                ),
            )
            n += 1
        conn.commit()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ml.serving.batch_predict")
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--bundle", type=Path, default=BUNDLE)
    ap.add_argument(
        "--as-of", default=None, help="score the latest session on or before this date (YYYY-MM-DD)"
    )
    a = ap.parse_args(argv)
    df, meta = predict_latest(a.bundle, as_of=a.as_of)
    n = write(df, meta, a.database_url)
    print(f"wrote {n} predictions (model {model_version(meta)}, promoted={promoted(meta)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
