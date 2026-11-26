"""Prediction and strategy metrics (docs/GPU_PLAN.md §6)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, roc_auc_score


def prediction_metrics(df: pd.DataFrame, score: str, target_up: str, target_ret: str) -> dict[str, float]:
    d = df.dropna(subset=[score, target_up, target_ret])
    out: dict[str, float] = {"n": float(len(d))}
    if d[target_up].nunique() == 2:
        out["auc"] = float(roc_auc_score(d[target_up], d[score]))
        out["logloss"] = float(log_loss(d[target_up], d[score].clip(1e-4, 1 - 1e-4)))
    pred_up, true_up = d[score] > 0.5, d[target_up] > 0.5
    out["hit_rate"] = float((pred_up == true_up).mean())  # = accuracy at the 0.5 threshold
    out["base_rate"] = float(
        true_up.mean()
    )  # accuracy of "always predict up" = max(base_rate, 1 − base_rate)
    tp = float((pred_up & true_up).sum())
    out["pred_up_share"] = float(pred_up.mean())
    out["precision_up"] = tp / pred_up.sum() if pred_up.sum() else float("nan")
    out["recall_up"] = tp / true_up.sum() if true_up.sum() else float("nan")
    tn = float((~pred_up & ~true_up).sum())
    out["precision_down"] = tn / (~pred_up).sum() if (~pred_up).sum() else float("nan")
    out["recall_down"] = tn / (~true_up).sum() if (~true_up).sum() else float("nan")
    ic = (
        d.groupby("date")
        .apply(
            lambda g: g[score].rank().corr(g[target_ret].rank()) if len(g) >= 5 else np.nan,
            include_groups=False,
        )
        .dropna()
    )
    out["ic_mean"] = float(ic.mean()) if len(ic) else float("nan")
    out["ic_tstat"] = (
        float(ic.mean() / ic.std() * np.sqrt(len(ic))) if len(ic) > 2 and ic.std() > 0 else float("nan")
    )
    return out


def smooth_scores(df: pd.DataFrame, score: str, span: int) -> pd.Series:
    """EMA of each symbol's score over its own past dates (span 1 = unchanged). Uses only today and earlier."""
    if span <= 1:
        return df[score]
    d = df.sort_values("date")
    sm = d.groupby("symbol")[score].transform(lambda s: s.ewm(span=span, adjust=False).mean())
    return sm.reindex(df.index)


def long_top_quantile(
    df: pd.DataFrame,
    score: str,
    ret_1d: str,
    top: float = 0.1,
    rebalance: int = 5,
    cost_bps: float = 10.0,
    hold: float | None = None,
    smooth: int = 1,
) -> dict[str, float]:
    """Every `rebalance` days buy the top `top` share by score (equal weight), hold, pay costs on turnover.
    Daily P&L uses next-day returns (`ret_1d` = forward 1-day log return), compared with equal-weight universe.

    hold:   hysteresis band — a name already held is kept while it ranks inside the top `hold` share
            (hold > top), so names hovering around the cut-off do not churn. None = no band.
    smooth: EMA span over each symbol's past scores before ranking (1 = off)."""
    d = df.dropna(subset=[score, ret_1d]).copy()
    d["_s"] = smooth_scores(d, score, smooth)
    d = d.sort_values("date")
    holdings: set[str] = set()
    rows = []
    for i, (day, g) in enumerate(d.groupby("date", sort=True)):
        turnover = 0.0
        if i % rebalance == 0:
            k = max(1, int(len(g) * top))
            ranked = g.sort_values("_s", ascending=False)["symbol"].tolist()
            if hold is not None and holdings:
                keep_k = max(k, int(len(g) * hold))
                kept = [s for s in ranked[:keep_k] if s in holdings][:k]
                new = set(kept)
                for s in ranked:
                    if len(new) >= k:
                        break
                    new.add(s)
            else:
                new = set(ranked[:k])
            if holdings or new:
                turnover = len(new.symmetric_difference(holdings)) / max(len(new), 1)
            holdings = new
        held = g[g["symbol"].isin(holdings)]
        r = float(np.expm1(held[ret_1d]).mean()) if len(held) else 0.0
        bench = float(np.expm1(g[ret_1d]).mean())
        rows.append(
            {"date": day, "strat": r - turnover * cost_bps / 1e4, "bench": bench, "turnover": turnover}
        )
    s = pd.DataFrame(rows).set_index("date")
    return {
        **_perf(s["strat"], "strat"),
        **_perf(s["bench"], "bench"),
        "turnover_2sided": float(
            s["turnover"][s["turnover"] > 0].mean() if (s["turnover"] > 0).any() else 0.0
        ),
    }


def _perf(r: pd.Series, p: str) -> dict[str, float]:
    if r.empty:
        return {}
    eq = (1 + r).cumprod()
    years = len(r) / 252
    downside = r[r < 0].std() * np.sqrt(252)
    return {
        f"{p}_cagr": float(eq.iloc[-1] ** (1 / years) - 1) if years > 0 else float("nan"),
        f"{p}_vol": float(r.std() * np.sqrt(252)),
        f"{p}_sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else float("nan"),
        f"{p}_sortino": float(r.mean() * 252 / downside) if downside > 0 else float("nan"),
        f"{p}_max_dd": float((eq / eq.cummax() - 1).min()),
        f"{p}_hit_rate": float((r > 0).mean()),
    }
