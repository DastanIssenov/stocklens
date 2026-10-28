"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Disclaimer } from "@/components/Disclaimer";
import { TickerSearch } from "@/components/TickerSearch";
import { TradeForm } from "@/components/TradeForm";
import { Card, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { changeColor, money, pct } from "@/lib/format";
import type { Ticker } from "@/lib/types";

export function TradeView() {
  const { t, locale, market } = useApp();
  const [selected, setSelected] = useState<Ticker | null>(null);
  const list = useQuery({ queryKey: ["overview", market], queryFn: () => api.overview(market) });
  const detail = useQuery({
    queryKey: ["ticker", selected?.symbol],
    queryFn: () => api.ticker(selected!.symbol),
    enabled: !!selected,
  });
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio, retry: false });

  return (
    <div className="space-y-4">
      <PageTitle>{t("nav_trade")}</PageTitle>
      <Disclaimer compact />
      {portfolio.data && (
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          {t("cash")}: <b className="tabular-nums">{money(portfolio.data.cash_usd, "USD", locale)}</b> ·{" "}
          <b className="tabular-nums">{money(portfolio.data.cash_kzt, "KZT", locale)}</b>
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t("choose_ticker")} className="lg:col-span-2">
          <div className="mb-3">
            <TickerSearch navigate={false} onSelect={setSelected} />
          </div>
          <ul className="grid gap-1 sm:grid-cols-2">
            {list.data?.rows.map((r) => (
              <li key={r.symbol}>
                <button
                  onClick={() =>
                    setSelected({
                      symbol: r.symbol,
                      name: r.name,
                      exchange: r.exchange,
                      currency: r.currency as "USD" | "KZT",
                      local_symbol: r.symbol,
                      market,
                      sector: r.sector,
                      country: "",
                      issuer: null,
                      is_liquid: r.is_liquid,
                    })
                  }
                  className={`flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm ${
                    selected?.symbol === r.symbol
                      ? "border-sky-500 bg-sky-50 dark:bg-sky-950/40"
                      : "border-neutral-200 hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-800/50"
                  }`}
                >
                  <span className="font-semibold">{r.symbol}</span>
                  <span className="tabular-nums text-neutral-500">{money(r.price, r.currency, locale, 2)}</span>
                  <span className={`w-14 text-right text-xs font-semibold tabular-nums ${changeColor(r.change_pct)}`}>
                    {pct(r.change_pct)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={selected ? `${t("selected")}: ${selected.symbol}` : t("trade")}>
          {!selected && <p className="text-sm text-neutral-500">{t("choose_ticker")}</p>}
          {selected && detail.data && (
            <div className="space-y-3">
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                {detail.data.name} · {detail.data.exchange} ·{" "}
                <Link href={`/ticker/${encodeURIComponent(selected.symbol)}`} className="text-sky-600 hover:underline">
                  {t("open_chart")}
                </Link>
              </p>
              <TradeForm key={selected.symbol} ticker={detail.data} price={detail.data.quote?.price ?? null} />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
