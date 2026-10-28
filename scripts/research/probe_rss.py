"""Phase 0 probe: RSS/GDELT/NBK availability. One request per feed."""
import time, httpx, feedparser
UA = {"User-Agent": "Mozilla/5.0 (compatible; capstone-stock-research/0.1)"}
feeds = {
  # US
  "cnbc_top": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
  "cnbc_markets": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
  "marketwatch_top": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
  "marketwatch_pulse": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
  "yahoo_fin": "https://finance.yahoo.com/news/rssindex",
  "yahoo_ticker": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US",
  "nasdaq_stocks": "https://www.nasdaq.com/feed/rssoutbound?category=Stocks",
  "sec_press": "https://www.sec.gov/news/pressreleases.rss",
  "investing_news": "https://www.investing.com/rss/news.rss",
  # KZ
  "kursiv_ru": "https://kz.kursiv.media/feed/",
  "kursiv_root": "https://kursiv.media/feed/",
  "kapital_rss": "https://kapital.kz/feed",
  "kapital_rss2": "https://kapital.kz/rss",
  "kapital_yandex": "https://kapital.kz/feed/yandex",
  "forbes_kz": "https://forbes.kz/rss",
  "forbes_kz2": "https://forbes.kz/newrss",
  "inbusiness_ru": "https://inbusiness.kz/ru/rss",
  "inbusiness_kz": "https://inbusiness.kz/kz/rss",
  "tengri_ru": "https://tengrinews.kz/news.rss",
  "tengri_kz": "https://kaz.tengrinews.kz/news.rss",
  "kz_inform_ru": "https://www.inform.kz/ru/rss",
  "kase_news_ru": "https://kase.kz/ru/rss/news",
  "kase_rss": "https://kase.kz/rss",
  "nbk_rates_all": "https://nationalbank.kz/rss/rates_all.xml",
  "nbk_rates_date": "https://nationalbank.kz/rss/get_rates.cfm?fdate=27.10.2026",
  "lsm_kz_ru": "https://lsm.kz/rss",
  "zakon_ru": "https://www.zakon.kz/rss/",
  "interfax_kz": "https://www.interfax.kz/?lang=rus&int_id=21&news_id=all&rss=1",
}
c = httpx.Client(timeout=20, follow_redirects=True, headers=UA)
for name, url in feeds.items():
    try:
        r = c.get(url)
        f = feedparser.parse(r.content)
        n = len(f.entries)
        e = f.entries[0] if n else {}
        print(f"{name:18s} {r.status_code} final={str(r.url)[:60]:60s} entries={n:3d} lang={f.feed.get('language','?')} "
              f"first={(e.get('published') or e.get('updated') or '')[:31]} | {(e.get('title') or '')[:60]!r}")
        if name.startswith("nbk") and r.status_code == 200 and n == 0:
            print("   raw:", r.text[:300].replace("\n", " "))
    except Exception as ex:
        print(f"{name:18s} ERR {type(ex).__name__}: {str(ex)[:80]}")
    time.sleep(0.5)

r = c.get("https://api.gdeltproject.org/api/v2/doc/doc", params={"query": "Kaspi sourcelang:russian", "mode": "artlist", "format": "json", "maxrecords": 5, "timespan": "7d"})
print("\ngdelt", r.status_code, r.text[:400])
time.sleep(6)
r = c.get("https://api.gdeltproject.org/api/v2/doc/doc", params={"query": "\"Apple\" earnings", "mode": "artlist", "format": "json", "maxrecords": 3, "timespan": "3d"})
print("gdelt en", r.status_code, r.text[:400])
