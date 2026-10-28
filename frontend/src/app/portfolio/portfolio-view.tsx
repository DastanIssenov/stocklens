"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Disclaimer } from "@/components/Disclaimer";
import { Card, ErrorBox, Loading, PageTitle, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { changeColor, money, num, pct } from "@/lib/format";

export function PortfolioView() {
  const { t, locale, user, authReady } = useApp();
  const qc = useQueryClient();
  const [ccy, setCcy] = useState<"USD" | "KZT">("USD");
  const q = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio, enabled: !!user, refetchInterval: 60_000 });
  const reset = useMutation({
    mutationFn: api.resetPortfolio,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["trades"] });
    },
  });

  if (!authReady) return <Loading />;
  if (!user)
    return (
      <p className="text-sm">
        <Link href="/login" className="font-semibold text-sky-600 hover:underline">
          {t("nav_login")}
        </Link>{" "}
        — {t("login_to_trade")}
      </p>
    );
  if (q.isPending) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const p = q.data;
  const conv = (usd: number) => (ccy === "USD" ? usd : usd * p.usdkzt);

  return (
    <div className="space-y-4">
      <PageTitle
        right={
          <div className="flex items-center gap-2 text-xs">
            <span className="text-neutral-500">{t("show_in")}</span>
            {(["USD", "KZT"] as const).map((c) => (
              <button
                key={c}
                onClick={() => setCcy(c)}
                className={`rounded px-2 py-1 font-semibold ${ccy === c ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900" : "text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"}`}
              >
                {c}
              </button>
            ))}
          </div>
        }
      >
        {t("portfolio_title")}
      </PageTitle>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label={t("total_value")}
          value={money(conv(p.total_value_usd), ccy, locale)}
          sub={`${t("rate_used")}: ${num(p.usdkzt, locale)} ₸/$`}
        />
        <Stat
          label={t("total_pnl")}
          value={<span className={changeColor(p.total_pnl_usd)}>{money(conv(p.total_pnl_usd), ccy, locale)}</span>}
          sub={<span className={changeColor(p.total_pnl_pct)}>{pct(p.total_pnl_pct)}</span>}
        />
        <Stat label={`${t("cash")} USD`} value={money(p.cash_usd, "USD", locale)} />
        <Stat label={`${t("cash")} KZT`} value={money(p.cash_kzt, "KZT", locale)} />
      </div>
      <Card title={t("positions")}>
        {p.positions.length === 0 ? (
          <p className="text-sm text-neutral-500">
            {t("no_positions")}{" "}
            <Link href="/trade" className="font-semibold text-sky-600 hover:underline">
              {t("nav_trade")} →
            </Link>
          </p>
        ) : (
          <div className="-mx-4 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500 dark:border-neutral-800">
                  <th className="px-4 py-2 font-medium">{t("symbol")}</th>
                  <th className="px-2 py-2 text-right font-medium">{t("quantity")}</th>
                  <th className="px-2 py-2 text-right font-medium">{t("avg_cost")}</th>
                  <th className="px-2 py-2 text-right font-medium">{t("price")}</th>
                  <th className="px-2 py-2 text-right font-medium">{t("market_value")}</th>
                  <th className="px-2 py-2 text-right font-medium">{t("unrealized")}</th>
                  <th className="px-2 py-2 text-right font-medium">{t("realized")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("weight")}</th>
                </tr>
              </thead>
              <tbody>
                {p.positions.map((x) => (
                  <tr key={x.symbol} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
                    <td className="px-4 py-2">
                      <Link
                        href={`/ticker/${encodeURIComponent(x.symbol)}`}
                        className="font-semibold text-sky-700 hover:underline dark:text-sky-400"
                      >
                        {x.symbol}
                      </Link>
                      <div className="text-[11px] text-neutral-500">{x.exchange}</div>
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{x.quantity}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{money(x.avg_cost, x.currency, locale, 2)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{money(x.price, x.currency, locale, 2)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{money(x.market_value, x.currency, locale)}</td>
                    <td className={`px-2 py-2 text-right tabular-nums ${changeColor(x.unrealized_pnl)}`}>
                      {money(x.unrealized_pnl, x.currency, locale)}{" "}
                      <span className="text-[11px]">{pct(x.unrealized_pnl_pct)}</span>
                    </td>
                    <td className={`px-2 py-2 text-right tabular-nums ${changeColor(x.realized_pnl)}`}>
                      {money(x.realized_pnl, x.currency, locale)}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{pct(x.weight, 1, false)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Disclaimer compact />
        <button
          onClick={() => window.confirm(t("reset_confirm")) && reset.mutate()}
          className="rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-950/40"
        >
          {t("reset")}
        </button>
      </div>
    </div>
  );
}
