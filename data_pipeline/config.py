"""Paths, secrets and etiquette settings for the historical pipeline (docs/GPU_PLAN.md §2)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
LAKE = Path(os.environ.get("DATA_LAKE", REPO / "data" / "lake"))
REPORT_PATH = REPO / "docs" / "DATA_REPORT.md"

# reuse the website's verified ticker definitions (pure dataclasses, no backend settings import)
sys.path.insert(0, str(REPO / "backend"))
from app.services.universe import KZ_LISTINGS, US_LISTINGS  # noqa: E402

load_dotenv(REPO / ".env")
_ENV = {k.upper(): v for k, v in os.environ.items()}

USER_AGENT = "stock-platform-capstone/0.1"


@dataclass(frozen=True)
class Secrets:
    alpaca_key: str | None = _ENV.get("ALPACA_KEY")
    alpaca_secret: str | None = _ENV.get("ALPACA_SECRET")
    fred_key: str | None = _ENV.get("FRED_KEY")
    sec_user_agent: str | None = _ENV.get("SEC_USER_AGENT")


SECRETS = Secrets()

# requests per second we allow ourselves (below every documented limit, see DATA_SOURCES.md)
RATE = {"alpaca": 3.0, "sec": 5.0, "fred": 2.0, "yahoo": 1.0, "nbk": 1.0, "tradernet": 0.2}

MACRO_SERIES = {
    "DFF": "fed_funds",
    "DGS2": "ust_2y",
    "DGS10": "ust_10y",
    "T10Y2Y": "ust_10y_2y",
    "VIXCLS": "vix",
    "BAMLH0A0HYM2": "hy_spread",
    "DTWEXBGS": "usd_broad",
    "DCOILBRENTEU": "brent_spot",
    "CPIAUCSL": "cpi",
    "UNRATE": "unemployment",
}
YAHOO_MARKET = ["^GSPC", "^NDX", "^VIX", "KZT=X", "BZ=F", "SPY", "QQQ"]

US_FUNDAMENTAL_TAGS = {
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "NetIncomeLoss": "net_income",
    "EarningsPerShareDiluted": "eps_diluted",
    "StockholdersEquity": "equity",
    "Assets": "assets",
    "Liabilities": "liabilities",
    "NetCashProvidedByUsedInOperatingActivities": "cfo",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "GrossProfit": "gross_profit",
    "LongTermDebt": "long_term_debt",
    "CommonStockSharesOutstanding": "shares_out",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "shares_diluted",
}

__all__ = ["KZ_LISTINGS", "LAKE", "REPO", "SECRETS", "US_LISTINGS"]
