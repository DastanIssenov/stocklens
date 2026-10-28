"""Parquet lake helpers. One file per dataset; idempotent merge on a key."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from data_pipeline.config import LAKE


def path(name: str) -> Path:
    return LAKE / f"{name}.parquet"


def read(name: str) -> pd.DataFrame:
    p = path(name)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def upsert(name: str, df: pd.DataFrame, key: list[str]) -> int:
    """Merge `df` into the dataset (new rows win), write atomically, return the total row count."""
    if df.empty:
        return len(read(name))
    LAKE.mkdir(parents=True, exist_ok=True)
    old = read(name)
    merged = pd.concat([old, df], ignore_index=True) if not old.empty else df
    merged = merged.drop_duplicates(subset=key, keep="last").sort_values(key).reset_index(drop=True)
    tmp = path(name).with_suffix(".tmp")
    merged.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path(name))
    _manifest(name, merged)
    return len(merged)


def _manifest(name: str, df: pd.DataFrame) -> None:
    mpath = LAKE / "_manifest.json"
    m = json.loads(mpath.read_text()) if mpath.exists() else {}
    m[name] = {"rows": len(df), "columns": list(df.columns), "updated_at": datetime.now(UTC).isoformat()}
    mpath.write_text(json.dumps(m, indent=2))
