"""Baselines and gradient-boosted models behind one tiny interface: fit(X, y) / score(X) → higher = more bullish."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
import pandas as pd


class Model(Protocol):
    name: str

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Model: ...
    def score(self, X: pd.DataFrame) -> np.ndarray: ...


class Persistence:
    """'Tomorrow = today': bullish if the last 1-day return was positive."""

    name = "baseline_persistence"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Persistence:
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return 0.5 + 0.5 * np.tanh(50 * X["ret_1"].fillna(0).to_numpy())


class Momentum:
    name = "baseline_momentum"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> Momentum:
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return 0.5 + 0.5 * np.tanh(5 * X["ret_21"].fillna(0).to_numpy())


class LogReg:
    name = "logreg"
    COLS = (
        "ret_1",
        "ret_5",
        "ret_21",
        "ret_63",
        "vol_21",
        "rsi_14",
        "sma_50",
        "volume_z_21",
        "mkt_ret_5",
        "vix",
    )

    def __init__(self, **kw: Any) -> None:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self.cols = [c for c in self.COLS]
        self.m = make_pipeline(StandardScaler(), LogisticRegression(C=kw.get("C", 0.1), max_iter=500))

    def _x(self, X: pd.DataFrame) -> pd.DataFrame:
        return X.reindex(columns=self.cols).fillna(0)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> LogReg:
        self.m.fit(self._x(X), y)
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(self._x(X))[:, 1]


class LightGBM:
    name = "lightgbm"

    def __init__(self, **params: Any) -> None:
        import lightgbm as lgb

        defaults = dict(
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=31,
            min_child_samples=200,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.7,
            reg_lambda=1.0,
            verbose=-1,
            n_jobs=-1,
        )
        self.m = lgb.LGBMClassifier(**{**defaults, **params})

    def fit(self, X: pd.DataFrame, y: pd.Series) -> LightGBM:
        self.m.fit(X, y)
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(X)[:, 1]

    def importance(self, cols: list[str]) -> pd.Series:
        return pd.Series(self.m.booster_.feature_importance("gain"), index=cols).sort_values(ascending=False)


class XGBoost:
    name = "xgboost"

    def __init__(self, **params: Any) -> None:
        import xgboost as xgb

        defaults = dict(
            n_estimators=400,
            learning_rate=0.03,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.7,
            min_child_weight=50,
            tree_method="hist",
            n_jobs=-1,
            eval_metric="logloss",
        )
        self.m = xgb.XGBClassifier(**{**defaults, **params})

    def fit(self, X: pd.DataFrame, y: pd.Series) -> XGBoost:
        self.m.fit(X, y)
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(X)[:, 1]


REGISTRY: dict[str, type] = {
    "baseline_persistence": Persistence,
    "baseline_momentum": Momentum,
    "logreg": LogReg,
    "lightgbm": LightGBM,
    "xgboost": XGBoost,
}
TRAINABLE = {"logreg", "lightgbm", "xgboost"}


def build(name: str, params: dict[str, Any] | None = None) -> Model:
    cls = REGISTRY[name]
    model: Model = cls(**(params or {})) if name in TRAINABLE else cls()
    return model
