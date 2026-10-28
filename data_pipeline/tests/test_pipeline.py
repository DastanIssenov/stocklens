import datetime as dt

import pandas as pd

from data_pipeline import cleaning, storage


def _bars(**over):  # type: ignore[no-untyped-def]
    base = {
        "symbol": "A",
        "date": dt.date(2026, 1, 2),
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 100,
    }
    return {**base, **over}


def test_validate_bars_drops_impossible_rows_and_flags_jumps() -> None:
    df = pd.DataFrame(
        [
            _bars(),
            _bars(date=dt.date(2026, 1, 5), close=20.0, high=21.0),  # +90 % jump → flagged, kept
            _bars(date=dt.date(2026, 1, 6), high=8.0),  # high < low → dropped
            _bars(date=dt.date(2026, 1, 7), close=-1.0),  # negative → dropped
            _bars(date=dt.date(2026, 1, 8), volume=0),  # zero volume → flagged, kept
        ]
    )
    out = cleaning.validate_bars(df)
    assert len(out) == 3
    assert out["flag_jump"].tolist() == [False, True, True]
    assert out["flag_zero_volume"].tolist() == [False, False, True]


def test_illiquidity_and_cross_check() -> None:
    df = pd.DataFrame(
        [
            _bars(date=dt.date(2026, 1, d), volume=0 if d % 2 else 100, close=10 + d * 0.1, high=12, low=9)
            for d in range(1, 21)
        ]
    )
    liq = cleaning.illiquidity(df)
    assert abs(liq.loc[0, "zero_volume_share"] - 0.5) < 1e-9
    a = pd.DataFrame({"symbol": ["A", "A"], "date": [1, 2], "adj_close": [10.0, 10.0]})
    y = pd.DataFrame({"symbol": ["A", "A"], "date": [1, 2], "adj_close": [10.0, 11.0]})
    cc = cleaning.cross_check(a, y)
    assert cc.loc[0, "mismatch_share"] == 0.5


def test_storage_upsert_is_idempotent(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(storage, "LAKE", tmp_path)
    df = pd.DataFrame({"symbol": ["A", "B"], "date": [1, 1], "close": [1.0, 2.0]})
    assert storage.upsert("t", df, ["symbol", "date"]) == 2
    assert storage.upsert("t", df.assign(close=[5.0, 6.0]), ["symbol", "date"]) == 2
    assert storage.read("t")["close"].tolist() == [5.0, 6.0]
    assert (tmp_path / "_manifest.json").exists()


def test_universe_filters_funds() -> None:
    from data_pipeline.jobs import _FUND_WORDS

    assert _FUND_WORDS.search("SPDR S&P 500 ETF Trust")
    assert _FUND_WORDS.search("ProShares UltraPro QQQ")
    assert not _FUND_WORDS.search("Apple Inc. Common Stock")
    assert not _FUND_WORDS.search("NVIDIA Corporation Common Stock")
