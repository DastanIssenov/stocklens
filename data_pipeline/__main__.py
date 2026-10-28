"""CLI: python -m data_pipeline <command>.

universe                         build the top-100 US universe (Alpaca + SEC)
backfill [--what ...] [--start]  historical load into data/lake (prices_us, prices_kz, market, macro, nbk, fundamentals)
daily                            small daily refresh of everything (last 14 days)
report                           write docs/DATA_REPORT.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import time

from data_pipeline import jobs, quality, storage

ALL = ["prices_us", "prices_kz", "market", "macro", "nbk", "fundamentals"]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx logs full URLs at INFO; FRED and Finnhub carry API keys in the query string → never log them
    for noisy in ("httpx", "httpcore", "yfinance", "urllib3", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="python -m data_pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("universe")
    u.add_argument("--top", type=int, default=100)
    b = sub.add_parser("backfill")
    b.add_argument("--what", nargs="*", default=ALL, choices=ALL)
    b.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2016, 1, 1))
    b.add_argument(
        "--yahoo-before",
        type=dt.date.fromisoformat,
        default=None,
        help="also load pre-2016 US history from Yahoo starting at this date",
    )
    b.add_argument("--nbk-start", type=dt.date.fromisoformat, default=None)
    sub.add_parser("daily")
    sub.add_parser("report")
    a = p.parse_args(argv)

    t0 = time.time()
    if a.cmd == "universe":
        df = jobs.build_universe(a.top)
        storage.upsert("universe_us", df, ["symbol"])
        print(f"universe_us: {len(df)} symbols")
    elif a.cmd == "backfill":
        for what in a.what:
            t = time.time()
            if what == "prices_us":
                n = jobs.backfill_us_prices(a.start, yahoo_before=a.yahoo_before)
            elif what == "prices_kz":
                n = jobs.backfill_kz_prices(dt.date(2005, 1, 1))
            elif what == "market":
                n = jobs.backfill_market(dt.date(2005, 1, 1))
            elif what == "macro":
                n = jobs.backfill_macro(dt.date(2005, 1, 1))
            elif what == "nbk":
                n = jobs.backfill_nbk(a.nbk_start or dt.date.today() - dt.timedelta(days=60))
            else:
                n = jobs.backfill_fundamentals()
            print(f"{what}: {n:,} rows ({time.time() - t:.0f}s)")
    elif a.cmd == "daily":
        start = dt.date.today() - dt.timedelta(days=14)
        jobs.backfill_us_prices(start)
        jobs.backfill_kz_prices(start)
        jobs.backfill_market(start)
        jobs.backfill_macro(start)
        jobs.backfill_nbk(start)
    elif a.cmd == "report":
        quality.build_report()
        print("docs/DATA_REPORT.md written")
    print(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
