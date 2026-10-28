"""Seed ticker universe (docs/DATA_SOURCES.md §8, decision D-018).

Every listing was verified on 2026-10-28: US exchange via Alpaca `/v2/assets`, KASE tickers via
Tradernet `getHloc`, LSE GDRs via yfinance. Aliases are used to link RU / KK / EN news to tickers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ListingSpec:
    symbol: str
    local_symbol: str
    name: str
    exchange: str
    market: str
    currency: str
    country: str
    sector: str
    data_source: str
    source_symbol: str
    issuer: str
    is_liquid: bool = True
    aliases: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (alias, lang)


def _us(symbol: str, name: str, exchange: str, sector: str, *aliases: str) -> ListingSpec:
    return ListingSpec(
        symbol=symbol,
        local_symbol=symbol,
        name=name,
        exchange=exchange,
        market="US",
        currency="USD",
        country="US",
        sector=sector,
        data_source="alpaca",
        source_symbol=symbol,
        issuer=symbol,
        aliases=tuple((a, "en") for a in aliases),
    )


US_LISTINGS: list[ListingSpec] = [
    _us("AAPL", "Apple Inc.", "NASDAQ", "Technology", "Apple"),
    _us("MSFT", "Microsoft Corporation", "NASDAQ", "Technology", "Microsoft"),
    _us("NVDA", "NVIDIA Corporation", "NASDAQ", "Semiconductors", "Nvidia"),
    _us("AMZN", "Amazon.com, Inc.", "NASDAQ", "Retail", "Amazon"),
    _us("GOOGL", "Alphabet Inc. (Class A)", "NASDAQ", "Media", "Alphabet", "Google"),
    _us("META", "Meta Platforms, Inc.", "NASDAQ", "Media", "Meta Platforms"),
    _us("TSLA", "Tesla, Inc.", "NASDAQ", "Automobiles", "Tesla"),
    _us("AVGO", "Broadcom Inc.", "NASDAQ", "Semiconductors", "Broadcom"),
    _us("JPM", "JPMorgan Chase & Co.", "NYSE", "Banking", "JPMorgan"),
    _us("V", "Visa Inc.", "NYSE", "Financial Services", "Visa Inc"),
    _us("MA", "Mastercard Incorporated", "NYSE", "Financial Services", "Mastercard"),
    _us("LLY", "Eli Lilly and Company", "NYSE", "Pharmaceuticals", "Eli Lilly"),
    _us("UNH", "UnitedHealth Group Incorporated", "NYSE", "Health Care", "UnitedHealth"),
    _us("XOM", "ExxonMobil Holdings Corporation", "NYSE", "Energy", "ExxonMobil", "Exxon"),
    _us("WMT", "Walmart Inc.", "NASDAQ", "Retail", "Walmart"),
    _us("JNJ", "Johnson & Johnson", "NYSE", "Pharmaceuticals", "Johnson & Johnson"),
    _us("PG", "The Procter & Gamble Company", "NYSE", "Consumer Products", "Procter & Gamble"),
    _us("HD", "The Home Depot, Inc.", "NYSE", "Retail", "Home Depot"),
    _us("COST", "Costco Wholesale Corporation", "NASDAQ", "Retail", "Costco"),
    _us("NFLX", "Netflix, Inc.", "NASDAQ", "Media", "Netflix"),
]

_KASPI = (("Kaspi", "en"), ("Каспи", "ru"), ("Kaspi.kz", "en"))
_HALYK = (("Halyk", "en"), ("Халык", "ru"), ("Народный банк", "ru"), ("Халық банк", "kk"))
_KAZATOMPROM = (("Kazatomprom", "en"), ("Казатомпром", "ru"), ("Қазатомөнеркәсіп", "kk"))
_AIR_ASTANA = (("Air Astana", "en"), ("Эйр Астана", "ru"))


def _kase(
    local: str, name: str, sector: str, issuer: str, aliases: tuple[tuple[str, str], ...], liquid: bool = True
) -> ListingSpec:
    return ListingSpec(
        symbol=f"{local}.KZ",
        local_symbol=local,
        name=name,
        exchange="KASE",
        market="KZ",
        currency="KZT",
        country="KZ",
        sector=sector,
        data_source="tradernet",
        source_symbol=f"{local}.KZ",
        issuer=issuer,
        is_liquid=liquid,
        aliases=aliases,
    )


KZ_LISTINGS: list[ListingSpec] = [
    # --- KASE Index representative list (28.10.2026) ---
    _kase("AIRA", "Air Astana JSC", "Airlines", "AIR_ASTANA", _AIR_ASTANA),
    _kase(
        "CCBN",
        "Bank CenterCredit JSC",
        "Banking",
        "BCC",
        (("Bank CenterCredit", "en"), ("Банк ЦентрКредит", "ru"), ("БЦК", "ru")),
    ),
    _kase("HSBK", "Halyk Bank of Kazakhstan JSC", "Banking", "HALYK", _HALYK),
    _kase("KCEL", "Kcell JSC", "Telecommunications", "KCELL", (("Kcell", "en"), ("Кселл", "ru"))),
    _kase("KEGC", "KEGOC JSC", "Utilities", "KEGOC", (("KEGOC", "en"), ("КЕГОК", "ru"))),
    _kase(
        "KMGZ",
        "National Company KazMunayGas JSC",
        "Energy",
        "KMG",
        (("KazMunayGas", "en"), ("КазМунайГаз", "ru"), ("ҚазМұнайГаз", "kk")),
    ),
    _kase("KSPI", "Kaspi.kz JSC", "Financial Services", "KASPI", _KASPI),
    _kase("KZAP", "NAC Kazatomprom JSC", "Uranium", "KAZATOMPROM", _KAZATOMPROM),
    _kase(
        "KZTK",
        "Kazakhtelecom JSC",
        "Telecommunications",
        "KAZAKHTELECOM",
        (("Kazakhtelecom", "en"), ("Казахтелеком", "ru"), ("Қазақтелеком", "kk")),
    ),
    _kase(
        "KZTO",
        "KazTransOil JSC",
        "Energy",
        "KAZTRANSOIL",
        (("KazTransOil", "en"), ("КазТрансОйл", "ru"), ("ҚазТрансОйл", "kk")),
    ),
    # --- other KASE shares with data (thin trading → is_liquid = False) ---
    _kase("ASBN", "ForteBank JSC", "Banking", "FORTEBANK", (("ForteBank", "en"), ("ФортеБанк", "ru")), False),
    _kase("KMGD", "KM GOLD JSC", "Mining", "KMGOLD", (("KM Gold", "en"),), False),
    _kase("BAST", "BAST JSC", "Mining", "BAST", (("БАСТ", "ru"),), False),
    _kase(
        "RAHT", "Lotte Rakhat JSC", "Consumer Products", "RAKHAT", (("Рахат", "ru"), ("Rakhat", "en")), False
    ),
    # --- Kazakh companies listed abroad (market "KZ" = shown in the Kazakhstan section) ---
    # Freedom Holding is incorporated in Nevada (country US) but headquartered in Almaty.
    ListingSpec(
        "KSPI",
        "KSPI",
        "Kaspi.kz JSC (ADS)",
        "NASDAQ",
        "KZ",
        "USD",
        "KZ",
        "Financial Services",
        "alpaca",
        "KSPI",
        "KASPI",
        True,
        _KASPI,
    ),
    ListingSpec(
        "FRHC",
        "FRHC",
        "Freedom Holding Corp.",
        "NASDAQ",
        "KZ",
        "USD",
        "US",
        "Financial Services",
        "alpaca",
        "FRHC",
        "FREEDOM",
        True,
        (("Freedom Holding", "en"), ("Фридом Финанс", "ru"), ("Freedom Finance", "en")),
    ),
    ListingSpec(
        "KAP.IL",
        "KAP",
        "NAC Kazatomprom JSC (GDR)",
        "LSE",
        "KZ",
        "USD",
        "KZ",
        "Uranium",
        "yfinance",
        "KAP.IL",
        "KAZATOMPROM",
        True,
        _KAZATOMPROM,
    ),
    ListingSpec(
        "HSBK.IL",
        "HSBK",
        "Halyk Bank of Kazakhstan JSC (GDR)",
        "LSE",
        "KZ",
        "USD",
        "KZ",
        "Banking",
        "yfinance",
        "HSBK.IL",
        "HALYK",
        True,
        _HALYK,
    ),
    ListingSpec(
        "AIRA.IL",
        "AIRA",
        "Air Astana JSC (GDR)",
        "LSE",
        "KZ",
        "USD",
        "KZ",
        "Airlines",
        "yfinance",
        "AIRA.IL",
        "AIR_ASTANA",
        False,
        _AIR_ASTANA,
    ),
]

ALL_LISTINGS: list[ListingSpec] = US_LISTINGS + KZ_LISTINGS
