"""Command line entry point: `python -m app.cli <command>` (used by `make seed`)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.ml_interface.factory import get_prediction_provider
from app.services import ingest
from app.workers.runtime import run_with_session

log = get_logger("cli")


async def _seed(session: AsyncSession, years: float, skip_news: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"tickers": await ingest.upsert_universe(session)}
    start = dt.date.today() - dt.timedelta(days=int(365 * years))
    prices = await ingest.update_prices(session, start)
    out["price_rows"] = sum(prices["rows"].values())
    out["tickers_with_prices"] = len(prices["rows"])
    out["price_errors"] = prices["errors"]
    fx = await ingest.update_fx_and_macro(session, history_days=int(365 * years))
    out["fx"] = fx
    if not skip_news:
        news = await ingest.update_news(session)
        out["news_inserted"] = sum(news["inserted"].values())
        out["news_errors"] = news["errors"]
    out["predictions_for_tickers"] = await ingest.generate_predictions(session, get_prediction_provider())
    return out


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    seed = sub.add_parser("seed", help="load the ticker universe, ~2y of prices, FX, news, demo predictions")
    seed.add_argument("--years", type=float, default=2.0)
    seed.add_argument("--skip-news", action="store_true")
    sub.add_parser("universe", help="upsert the ticker universe only")
    up = sub.add_parser("update-prices", help="re-fetch the last N days of daily bars")
    up.add_argument("--days", type=int, default=10)
    up.add_argument("--symbols", nargs="*")
    sub.add_parser("update-news")
    sub.add_parser("update-fx")
    sub.add_parser("predict")
    sub.add_parser("quotes", help="refresh live US quotes once (ignores market hours)")
    a = p.parse_args(argv)

    result: Any
    if a.cmd == "seed":
        result = run_with_session(lambda ss: _seed(ss, a.years, a.skip_news))
    elif a.cmd == "universe":
        result = run_with_session(ingest.upsert_universe)
    elif a.cmd == "update-prices":
        start = dt.date.today() - dt.timedelta(days=a.days)
        result = run_with_session(lambda ss: ingest.update_prices(ss, start, symbols=a.symbols))
    elif a.cmd == "update-news":
        result = run_with_session(ingest.update_news)
    elif a.cmd == "update-fx":
        result = run_with_session(ingest.update_fx_and_macro)
    elif a.cmd == "predict":
        result = run_with_session(lambda ss: ingest.generate_predictions(ss, get_prediction_provider()))
    elif a.cmd == "quotes":
        result = run_with_session(ingest.refresh_live_quotes)
    else:  # pragma: no cover - argparse guards this
        return 2
    sys.stdout.write(json.dumps(result, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
