"""Point-in-time fundamentals and industry groups for `ml.features.compute_features`.

`fundamental_events(fund)` replays SEC filings in publication order and, after each filing, records what was
knowable at that moment: trailing-twelve-month (TTM) revenue, net income, operating cash flow and gross profit,
the same TTM one year earlier, the latest balance-sheet values and a share count. Restated values overwrite older
ones only from the restatement's own publication time. TTM for a quarter = last fiscal year + current year-to-date −
prior-year year-to-date (the comparative column of the same 10-Q), the standard way to build TTM from XBRL facts.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

DURATION = ("revenue", "net_income", "cfo", "gross_profit")
INSTANT = ("equity", "assets", "liabilities")
_DAY = pd.Timedelta(days=1)

# industry groups: Fama–French 12 (from `sectors_us.sector`), with business equipment split by SIC because it
# holds half of a large-cap US universe; groups with fewer than MIN_GROUP members are merged into "Other"
MIN_GROUP = 3


def industry_groups(sectors: pd.DataFrame) -> pd.Series:
    """symbol → industry group name."""

    def group(row: pd.Series) -> str:
        sic = row["sic"]
        if row["sector"] == "BusEq" and pd.notna(sic):
            if 7370 <= sic <= 7379:
                return "Software"
            if sic in (3674, 3827):
                return "Semis"
            return "Hardware"
        return str(row["sector"])

    g = sectors.set_index("symbol").apply(group, axis=1)
    counts = g.value_counts()
    return g.where(g.map(counts) >= MIN_GROUP, "Other")


def _ttm_at(d: dict[tuple[pd.Timestamp, pd.Timestamp], float], end: pd.Timestamp, tol: int = 10) -> float:
    """TTM value for the period ending near `end` from the known duration facts `d[(start, end)] = value`."""
    ends = {e for (_, e) in d if abs((e - end).days) <= tol}
    if not ends:
        return float("nan")
    p = min(ends, key=lambda e: abs((e - end).days))
    items = [(s, v) for (s, e), v in d.items() if e == p]
    annual = [v for s, v in items if 350 <= (p - s).days <= 380]
    if annual:
        return annual[-1]
    part = [(s, v) for s, v in items if (p - s).days < 350]
    if not part:
        return float("nan")
    s, ytd = max(part, key=lambda sv: (p - sv[0]).days)
    span = (p - s).days
    fy = [v for (s2, e2), v in d.items() if 350 <= (e2 - s2).days <= 380 and abs((e2 - (s - _DAY)).days) <= 7]
    prev = [
        v
        for (s2, e2), v in d.items()
        if abs((e2 - s2).days - span) <= 15 and abs((e2 - (p - pd.Timedelta(days=365))).days) <= 10
    ]
    if not fy or not prev:
        return float("nan")
    return fy[-1] + ytd - prev[-1]


def _latest(d: dict[pd.Timestamp, float]) -> float:
    return d[max(d)] if d else float("nan")


def _events_for_symbol(sym: str, g: pd.DataFrame) -> Iterable[dict[str, object]]:
    dur: dict[str, dict[tuple[pd.Timestamp, pd.Timestamp], float]] = {
        m: {} for m in (*DURATION, "shares_diluted")
    }
    inst: dict[str, dict[pd.Timestamp, float]] = {m: {} for m in (*INSTANT, "shares_out")}
    for ts, ev in g.groupby("available_at", sort=True):
        for metric, start, end, value in ev[["metric", "start", "end", "value"]].itertuples(index=False):
            if metric in dur and pd.notna(start):
                dur[metric][(start, end)] = value
            elif metric in inst:
                inst[metric][end] = value
        row: dict[str, object] = {"symbol": sym, "available_at": ts}
        for m in DURATION:
            if dur[m]:
                p = max(e for (_, e) in dur[m])
                row[f"{m}_ttm"] = _ttm_at(dur[m], p)
                row[f"{m}_ttm_1y"] = _ttm_at(dur[m], p - pd.Timedelta(days=365))
        for m in INSTANT:
            row[m] = _latest(inst[m])
        # share count and the date it refers to (market cap is rebuilt from the price on that date)
        if dur["shares_diluted"]:
            (_, end), val = max(
                dur["shares_diluted"].items(), key=lambda kv: (kv[0][1], -(kv[0][1] - kv[0][0]).days)
            )
            row["shares"], row["shares_date"] = val, end
        elif inst["shares_out"]:
            end = max(inst["shares_out"])
            row["shares"], row["shares_date"] = inst["shares_out"][end], end
        yield row


def fundamental_events(fund: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, available_at) with the fundamentals known right after that publication.
    Only USD and share units are used (foreign filers in EUR/RUB would need FX to compare with USD prices)."""
    keep = (*DURATION, *INSTANT, "shares_diluted", "shares_out")
    f = fund[fund["metric"].isin(keep) & fund["unit"].isin(["USD", "shares"])].copy()
    if f.empty:
        return pd.DataFrame(columns=["symbol", "available_at"])
    f["available_at"] = pd.to_datetime(f["available_at"], utc=True)
    f["end"] = pd.to_datetime(f["period_end"])
    f["start"] = pd.to_datetime(f["period_start"])
    rows = [r for sym, g in f.groupby("symbol", sort=True) for r in _events_for_symbol(sym, g)]
    ev = pd.DataFrame(rows).sort_values(["symbol", "available_at"]).reset_index(drop=True)
    cols = [c for c in ev.columns if c not in ("symbol", "available_at")]
    ev[cols] = ev.groupby("symbol")[cols].ffill()  # a filing without a metric keeps the last known value
    return ev
