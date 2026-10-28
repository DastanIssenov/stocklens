"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Disclaimer } from "@/components/Disclaimer";
import { NewsList } from "@/components/NewsList";
import { PredictionPanel } from "@/components/Predictions";
import { PriceChart } from "@/components/PriceChart";
import { TradeForm } from "@/components/TradeForm";
import { Card, ErrorBox, Loading } from "@/components/ui";
import { useLivePrices } from "@/components/useLivePrices";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { changeColor, compact, dateOnly, money, pct } from "@/lib/format";

const RANGES = [
  { key: "1M", days: 31 },
  { key: "3M", days: 92 },
  { key: "6M", days: 183 },
  { key: "1Y", days: 366 },
  { key: "2Y", days: 731 },
] as const;

export function TickerView() {
  const params = useParams<{ symbol: string }>();
  const symbol = decodeURIComponent(params.symbol).toUpperCase();
  const { t, locale } = useApp();
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("1Y");

  const detail = useQuery({ queryKey: ["ticker", symbol], queryFn: () => api.ticker(symbol) });
  const history = useQuery({ queryKey: ["prices", symbol], queryFn: () => api.prices(symbol) });
  const live = useLivePrices([symbol]);

  const bars = useMemo(() => {
    const all = history.data?.bars ?? [];
    const days = RANGES.find((r) => r.key === range)!.days;
    if (!all.length) return all;
    // range is measured back from the latest bar (pure: no clock access during render)
    const lastMs = Date.parse(`${all[all.length - 1].date}T00:00:00Z`);
    const cutoff = new Date(lastMs - days * 86_400_000).toISOString().slice(0, 10);
    return all.filter((b) => b.date >= cutoff);
  }, [history.data, range]);

  if (detail.isPending) return <Loading />;
  if (detail.error) return <ErrorBox error={detail.error} />;
  const d = detail.data;
  const lq = live[symbol];
  const price = lq?.price ?? d.quote?.price ?? null;
  const prev = lq?.prev_close ?? d.quote?.prev_close ?? null;
  const changePct = price && prev ? price / prev - 1 : null;
  const last = bars[bars.length - 1];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold">{d.symbol}</h1>
            <span className="rounded bg-neutral-200 px-1.5 py-0.5 text-xs font-semibold text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
              {d.exchange} · {d.currency}
            </span>
            {!d.is_liquid && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                {t("illiquid")}
              </span>
            )}
          </div>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            {d.name} {d.sector ? `· ${d.sector}` : ""}
          </p>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold tabular-nums">{money(price, d.currency, locale, 2)}</div>
          <div className={`text-sm font-semibold tabular-nums ${changeColor(changePct)}`}>
            {pct(changePct)}{" "}
            <span className="font-normal text-neutral-500">
              · {lq ? t("live") : t("delayed")}
              {!lq && d.quote ? ` ${dateOnly(String(d.quote.as_of), locale)}` : ""}
            </span>
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card
            actions={
              <div className="flex gap-1" role="tablist" aria-label={t("range")}>
                {RANGES.map((r) => (
                  <button
                    key={r.key}
                    role="tab"
                    aria-selected={range === r.key}
                    onClick={() => setRange(r.key)}
                    className={`rounded px-2 py-0.5 text-xs font-semibold ${
                      range === r.key
                        ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"
                        : "text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
                    }`}
                  >
                    {r.key}
                  </button>
                ))}
              </div>
            }
            title={`${d.symbol} · ${t("price")}`}
          >
            {history.isPending && <Loading />}
            {history.error && <ErrorBox error={history.error} />}
            {history.data &&
              (bars.length ? <PriceChart bars={bars} /> : <p className="text-sm text-neutral-500">{t("no_data")}</p>)}
            {last && (
              <p className="mt-2 text-xs text-neutral-500">
                {t("volume")}: {compact(last.volume, locale)} · O {last.open} · H {last.high} · L {last.low} · C{" "}
                {last.close}
              </p>
            )}
          </Card>
          <PredictionPanel symbol={d.symbol} />
          <NewsList symbol={d.symbol} />
        </div>
        <div className="space-y-4">
          <Card title={`${t("trade")} ${d.symbol}`}>
            <TradeForm ticker={d} price={price} />
          </Card>
          {d.other_listings.length > 0 && (
            <Card title={t("other_listings")}>
              <ul className="space-y-1 text-sm">
                {d.other_listings.map((o) => (
                  <li key={o.symbol} className="flex justify-between">
                    <Link
                      href={`/ticker/${encodeURIComponent(o.symbol)}`}
                      className="font-semibold text-sky-700 hover:underline dark:text-sky-400"
                    >
                      {o.symbol}
                    </Link>
                    <span className="text-xs text-neutral-500">
                      {o.exchange} · {o.currency}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Disclaimer compact />
        </div>
      </div>
    </div>
  );
}
