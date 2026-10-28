"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { DemoBadge, Disclaimer } from "@/components/Disclaimer";
import { NewsList } from "@/components/NewsList";
import { Card, ErrorBox, Loading, PageTitle, Sparkline, Stat } from "@/components/ui";
import { useLivePrices } from "@/components/useLivePrices";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { changeColor, dateOnly, money, num, pct } from "@/lib/format";
import type { OverviewRow } from "@/lib/types";

function MoversList({ title, rows }: { title: string; rows: OverviewRow[] }) {
  const { locale } = useApp();
  return (
    <Card title={title}>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.symbol} className="flex items-center justify-between gap-2 text-sm">
            <Link href={`/ticker/${encodeURIComponent(r.symbol)}`} className="font-semibold hover:text-sky-600">
              {r.symbol}
            </Link>
            <span className="tabular-nums text-neutral-500">{money(r.price, r.currency, locale, 2)}</span>
            <span className={`w-16 text-right font-semibold tabular-nums ${changeColor(r.change_pct)}`}>
              {pct(r.change_pct)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function MarketHome() {
  const { market, t, locale } = useApp();
  const q = useQuery({ queryKey: ["overview", market], queryFn: () => api.overview(market), refetchInterval: 60_000 });
  const live = useLivePrices(market === "US" && q.data ? q.data.rows.map((r) => r.symbol) : []);
  const rows = (q.data?.rows ?? []).map((r) => {
    const l = live[r.symbol];
    return l ? { ...r, price: l.price, change_pct: l.prev_close ? l.price / l.prev_close - 1 : r.change_pct } : r;
  });

  return (
    <div className="space-y-6">
      <PageTitle right={<DemoBadge />}>
        {t("overview_title")} · {market === "US" ? `🇺🇸 ${t("market_us")}` : `🇰🇿 ${t("market_kz")}`}
      </PageTitle>
      <Disclaimer compact />
      {q.isPending && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              label={`${t("usd_kzt")} · ${t("official_rate")}`}
              value={q.data.fx.official ? num(q.data.fx.official, locale) : "—"}
              sub={q.data.fx.official_date ? dateOnly(q.data.fx.official_date, locale) : undefined}
            />
            <Stat
              label={`${t("usd_kzt")} · ${t("market_rate")}`}
              value={q.data.fx.market ? num(q.data.fx.market, locale) : "—"}
              sub={q.data.fx.market_date ? dateOnly(q.data.fx.market_date, locale) : undefined}
            />
            <Stat
              label={`${t("brent")}, $/bbl`}
              value={q.data.brent ? num(q.data.brent, locale) : "—"}
              sub={q.data.brent_date ? dateOnly(q.data.brent_date, locale) : undefined}
            />
            <Stat
              label={t("symbol")}
              value={rows.length}
              sub={market === "KZ" ? "KASE · NASDAQ · LSE" : "NASDAQ · NYSE"}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <MoversList title={t("gainers")} rows={q.data.gainers} />
            <MoversList title={t("losers")} rows={q.data.losers} />
          </div>
          <Card>
            {rows.length === 0 ? (
              <p className="text-sm text-neutral-500">{t("no_data")}</p>
            ) : (
              <div className="-mx-4 overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500 dark:border-neutral-800">
                      <th className="px-4 py-2 font-medium">{t("symbol")}</th>
                      <th className="px-2 py-2 font-medium">{t("name")}</th>
                      <th className="px-2 py-2 font-medium">{t("exchange")}</th>
                      <th className="px-2 py-2 text-right font-medium">{t("price")}</th>
                      <th className="px-2 py-2 text-right font-medium">{t("change")}</th>
                      <th className="px-4 py-2 text-right font-medium">{t("last_30d")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr
                        key={r.symbol}
                        className="border-b border-neutral-100 last:border-0 hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-800/50"
                      >
                        <td className="px-4 py-2">
                          <Link
                            href={`/ticker/${encodeURIComponent(r.symbol)}`}
                            className="font-semibold text-sky-700 hover:underline dark:text-sky-400"
                          >
                            {r.symbol}
                          </Link>
                          {live[r.symbol] && (
                            <span
                              className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 align-middle"
                              title={t("live")}
                            />
                          )}
                        </td>
                        <td className="max-w-[16rem] truncate px-2 py-2 text-neutral-600 dark:text-neutral-300">
                          {r.name}
                          {!r.is_liquid && (
                            <span className="ml-1.5 rounded bg-amber-100 px-1 text-[10px] text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                              {t("illiquid")}
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-xs text-neutral-500">{r.exchange}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{money(r.price, r.currency, locale, 2)}</td>
                        <td className={`px-2 py-2 text-right font-semibold tabular-nums ${changeColor(r.change_pct)}`}>
                          {pct(r.change_pct)}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <Sparkline values={r.sparkline} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <NewsList market={market} limit={10} />
        </>
      )}
    </div>
  );
}
