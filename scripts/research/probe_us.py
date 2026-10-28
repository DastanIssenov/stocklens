"""Phase 0 probe: a few small real requests per US data source. Never prints secrets."""
import os, time
import httpx
from dotenv import load_dotenv

load_dotenv(".env")
env = {k.upper(): v for k, v in os.environ.items()}
H_ALP = {"APCA-API-KEY-ID": env["ALPACA_KEY"], "APCA-API-SECRET-KEY": env["ALPACA_SECRET"]}

def show(name, r, extract):
    print(f"\n=== {name}: HTTP {r.status_code}")
    rl = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()}
    if rl: print("rate-limit headers:", rl)
    try:
        print(extract(r))
    except Exception as e:  # noqa
        print("extract failed:", e, r.text[:300])

c = httpx.Client(timeout=30)
# Alpaca trading endpoint (account only — check which env: paper or live)
ep = env.get("ALPACA_ENDPOINT", "")
print("alpaca endpoint host:", httpx.URL(ep).host)
r = c.get(ep.rstrip("/") + "/account" if ep.endswith("/v2") else ep.rstrip("/") + "/v2/account", headers=H_ALP)
show("alpaca account", r, lambda r: {k: r.json().get(k) for k in ("status", "currency")})

# Alpaca market data: daily bars, IEX feed (free plan)
r = c.get("https://data.alpaca.markets/v2/stocks/bars", headers=H_ALP,
          params={"symbols": "AAPL,MSFT", "timeframe": "1Day", "start": "2016-01-01", "limit": 10000, "feed": "iex", "adjustment": "all"})
def bars(r):
    j = r.json(); out = {}
    for s, b in j["bars"].items():
        out[s] = (len(b), b[0]["t"], b[-1]["t"], b[-1])
    return out, "next_page_token=" + str(bool(j.get("next_page_token")))
show("alpaca bars iex since 2016", r, bars)

r = c.get("https://data.alpaca.markets/v2/stocks/bars", headers=H_ALP,
          params={"symbols": "AAPL", "timeframe": "1Day", "start": "2025-10-01", "limit": 50, "feed": "sip"})
show("alpaca bars sip (recent, expected 403 on free plan if within 15 min)", r, lambda r: (len(r.json().get("bars", {}).get("AAPL", [])), r.text[:200]))
r = c.get("https://data.alpaca.markets/v2/stocks/bars", headers=H_ALP,
          params={"symbols": "AAPL", "timeframe": "1Day", "start": "2015-12-01", "end": "2016-01-10", "feed": "sip", "adjustment": "all"})
show("alpaca bars sip historical 2015-12", r, lambda r: (len(r.json().get("bars", {}).get("AAPL", []) or []), r.text[:200]))

r = c.get("https://data.alpaca.markets/v2/stocks/snapshots", headers=H_ALP, params={"symbols": "AAPL", "feed": "iex"})
show("alpaca snapshot iex", r, lambda r: list(r.json()["AAPL"].keys()))

r = c.get("https://data.alpaca.markets/v1beta1/news", headers=H_ALP, params={"symbols": "AAPL", "limit": 3})
show("alpaca news", r, lambda r: [(n["created_at"], n["source"], n["headline"][:70], n["symbols"][:5]) for n in r.json()["news"]])
r = c.get("https://data.alpaca.markets/v1beta1/news", headers=H_ALP, params={"symbols": "AAPL", "limit": 1, "start": "2015-01-01T00:00:00Z", "sort": "asc"})
show("alpaca news oldest", r, lambda r: [(n["created_at"], n["source"]) for n in r.json()["news"]])

# Finnhub
fk = env["FINNHUB_KEY"]
r = c.get("https://finnhub.io/api/v1/quote", params={"symbol": "AAPL", "token": fk})
show("finnhub quote", r, lambda r: r.json())
r = c.get("https://finnhub.io/api/v1/company-news", params={"symbol": "AAPL", "from": "2026-10-20", "to": "2026-10-27", "token": fk})
show("finnhub company-news", r, lambda r: (len(r.json()), [(n["datetime"], n["source"], n["headline"][:60]) for n in r.json()[:3]]))
r = c.get("https://finnhub.io/api/v1/company-news", params={"symbol": "AAPL", "from": "2024-01-02", "to": "2024-01-05", "token": fk})
show("finnhub company-news 2024 (history depth)", r, lambda r: len(r.json()))
r = c.get("https://finnhub.io/api/v1/stock/candle", params={"symbol": "AAPL", "resolution": "D", "from": 1700000000, "to": 1700900000, "token": fk})
show("finnhub candles (premium?)", r, lambda r: r.text[:150])
r = c.get("https://finnhub.io/api/v1/stock/profile2", params={"symbol": "KSPI", "token": fk})
show("finnhub profile KSPI", r, lambda r: r.json())
r = c.get("https://finnhub.io/api/v1/news", params={"category": "general", "token": fk})
show("finnhub general news", r, lambda r: (len(r.json()), r.json()[0]["source"] if r.json() else None))

# SEC EDGAR
sh = {"User-Agent": env["SEC_USER_AGENT"], "Accept-Encoding": "gzip, deflate"}
r = c.get("https://www.sec.gov/files/company_tickers.json", headers=sh)
show("sec company_tickers", r, lambda r: (len(r.json()), [v for v in r.json().values() if v["ticker"] in ("AAPL", "KSPI")]))
time.sleep(0.2)
r = c.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", headers=sh)
def facts(r):
    j = r.json(); g = j["facts"]["us-gaap"]
    rev = g.get("RevenueFromContractWithCustomerExcludingAssessedTax", {}).get("units", {}).get("USD", [])
    return (j["entityName"], len(g), len(r.content), rev[-1] if rev else None)
show("sec companyfacts AAPL", r, facts)
time.sleep(0.2)
r = c.get("https://data.sec.gov/submissions/CIK0000320193.json", headers=sh)
show("sec submissions AAPL", r, lambda r: (r.json()["name"], r.json()["filings"]["recent"]["form"][:5], r.json()["filings"]["recent"]["acceptanceDateTime"][:2]))
time.sleep(0.2)
r = c.get("https://data.sec.gov/api/xbrl/frames/us-gaap/EarningsPerShareBasic/USD-per-shares/CY2024Q4I.json", headers=sh)
show("sec frames (expected 404 for duration concept with I)", r, lambda r: r.text[:120])
r = c.get("https://data.sec.gov/api/xbrl/frames/us-gaap/EarningsPerShareBasic/USD-per-shares/CY2024Q4.json", headers=sh)
show("sec frames EPS CY2024Q4", r, lambda r: len(r.json()["data"]))

# FRED
fr = env["FRED_KEY"]
for sid in ["DFF", "DGS10", "CPIAUCSL", "VIXCLS", "DCOILBRENTEU", "DTWEXBGS", "CCUSMA02KZM618N", "EXKZUS"]:
    r = c.get("https://api.stlouisfed.org/fred/series", params={"series_id": sid, "api_key": fr, "file_type": "json"})
    def s(r):
        j = r.json()
        if "seriess" not in j: return j.get("error_message")
        x = j["seriess"][0]; return (x["title"][:60], x["frequency_short"], x["observation_start"], x["observation_end"])
    show(f"fred series {sid}", r, s)
r = c.get("https://api.stlouisfed.org/fred/series/observations", params={"series_id": "DCOILBRENTEU", "api_key": fr, "file_type": "json", "sort_order": "desc", "limit": 3})
show("fred obs brent", r, lambda r: [(o["date"], o["value"]) for o in r.json()["observations"]])
r = c.get("https://api.stlouisfed.org/fred/series/search", params={"search_text": "Kazakhstan tenge", "api_key": fr, "file_type": "json", "limit": 8})
show("fred search kzt", r, lambda r: [(x["id"], x["title"][:60], x["frequency_short"], x["observation_end"]) for x in r.json()["seriess"]])
