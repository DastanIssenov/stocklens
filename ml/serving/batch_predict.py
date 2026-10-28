"""Batch inference for the website (docs/GPU_PLAN.md §8.2).

Loads the exported bundle (`ml/artifacts/short_gbm/{model.txt,meta.json}`), computes features with the SAME
module used in training (`ml.features`) from the Parquet lake, and upserts one row per ticker into the
website's `predictions` table for the latest date. The website serves these rows instead of mock values.

Promotion rule (§7): rows are written with `is_demo = false` only if the out-of-sample metrics pass
(IC t-stat ≥ 2, AUC ≥ 0.52, strategy Sharpe > benchmark Sharpe). Otherwise they are stored as
`is_demo = true` — the UI keeps its "Demo predictions" badge, but shows the model version.

Usage:  python -m ml.serving.batch_predict --database-url postgresql://stock:stock@localhost:5433/stock
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
from ml.train import REPO

BUNDLE = REPO / "ml" / "artifacts" / "short_gbm"


def promoted(meta: dict[str, Any]) -> bool:
    m = meta.get("oos_metrics", {})
    return bool(
        m.get("ic_tstat", 0) >= 2.0
        and m.get("auc", 0) >= 0.52
        and m.get("strat_sharpe", -9) > m.get("bench_sharpe", 9)
    )


def predict_latest(
    bundle: Path = BUNDLE, lake: Path = REPO / "data" / "lake"
) -> tuple[pd.DataFrame, dict[str, Any]]:
    import lightgbm as lgb

    meta = json.loads((bundle / "meta.json").read_text())
    booster = lgb.Booster(model_file=str(bundle / "model.txt"))
    prices = pd.read_parquet(lake / "prices_us.parquet")
    prices = prices[
        pd.to_datetime(prices["date"]) >= pd.to_datetime(prices["date"]).max() - pd.Timedelta(days=500)
    ]
    market = pd.read_parquet(lake / "market_yahoo.parquet")
    macro = pd.read_parquet(lake / "macro_fred.parquet") if (lake / "macro_fred.parquet").exists() else None
    feats = compute_features(prices, market, macro)
    latest = feats[feats["date"] == feats.groupby("symbol")["date"].transform("max")].reset_index(drop=True)
    X = latest[meta["features"]]
    p = booster.predict(X)
    contrib = booster.predict(X, pred_contrib=True)[:, :-1]  # TreeSHAP, last column = bias
    vol5 = latest["vol_21"].fillna(latest["vol_21"].median()) * math.sqrt(meta["horizon"])
    auc_edge = max(0.0, meta.get("oos_metrics", {}).get("auc", 0.5) - 0.5)
    rows = []
    for i, r in latest.iterrows():
        top = np.argsort(-np.abs(contrib[i]))[:5]
        rows.append(
            {
                "symbol": r["symbol"],
                "as_of_date": r["date"].date(),
                "prob_up": float(p[i]),
                # expected return proxy: direction edge × typical move over the horizon (documented, not a regression)
                "predicted_return": float((2 * p[i] - 1) * vol5[i] * 0.8),
                "confidence": float(min(1.0, abs(2 * p[i] - 1) * (0.5 + 10 * auc_edge))),
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

    version = f"lgbm-cpu-{meta['run_id'][:8]}"
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
    a = ap.parse_args(argv)
    df, meta = predict_latest(a.bundle)
    n = write(df, meta, a.database_url)
    print(f"wrote {n} predictions (model lgbm-cpu-{meta['run_id'][:8]}, promoted={promoted(meta)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
