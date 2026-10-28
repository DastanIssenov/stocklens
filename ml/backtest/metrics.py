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
    out["hit_rate"] = float(((d[score] > 0.5) == (d[target_up] > 0.5)).mean())
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


def long_top_quantile(
    df: pd.DataFrame, score: str, ret_1d: str, top: float = 0.1, rebalance: int = 5, cost_bps: float = 10.0
) -> dict[str, float]:
    """Every `rebalance` days buy the top `top` share by score (equal weight), hold, pay costs on turnover.
    Daily P&L uses next-day returns (`ret_1d` = forward 1-day log return), compared with equal-weight universe."""
    d = df.dropna(subset=[score, ret_1d]).sort_values("date")
    dates = sorted(d["date"].unique())
    holdings: set[str] = set()
    rows = []
    for i, day in enumerate(dates):
        g = d[d["date"] == day]
        turnover = 0.0
        if i % rebalance == 0:
            k = max(1, int(len(g) * top))
            new = set(g.nlargest(k, score)["symbol"])
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
