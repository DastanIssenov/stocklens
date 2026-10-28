"""Walk-forward splits with purging and embargo (docs/GPU_PLAN.md §4.1). Never random splits."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Fold:
    name: str
    train_end: pd.Timestamp  # last date allowed in training (after purge + embargo)
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def yearly_folds(dates: pd.Series, test_years: list[int], horizon: int, embargo: int) -> Iterator[Fold]:
    """Expanding window. Training stops `horizon + embargo` trading days before the test period, so no
    training label window (t, t+horizon] overlaps the test period (purging) plus an extra embargo."""
    cal = pd.Series(sorted(pd.to_datetime(dates).unique()))
    for y in test_years:
        in_year = cal[(cal.dt.year == y)]
        if in_year.empty:
            continue
        start_idx = in_year.index[0]
        cut = start_idx - (horizon + embargo)
        if cut <= 0:
            continue
        yield Fold(str(y), cal[cut], in_year.iloc[0], in_year.iloc[-1])


def split(df: pd.DataFrame, fold: Fold) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = df[df["date"] <= fold.train_end]
    test = df[(df["date"] >= fold.test_start) & (df["date"] <= fold.test_end)]
    return train, test
