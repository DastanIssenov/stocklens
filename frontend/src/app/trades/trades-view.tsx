"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Disclaimer } from "@/components/Disclaimer";
import { ReviewCard } from "@/components/ReviewCard";
import { Card, ErrorBox, Loading, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { changeColor, dateTime, money } from "@/lib/format";
import type { Trade } from "@/lib/types";

const VERDICT_DOT = { reasonable: "bg-emerald-500", risky: "bg-amber-500", poor: "bg-rose-500" } as const;

function TradeRow({ tr }: { tr: Trade }) {
  const { t, locale } = useApp();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const rerun = useMutation({
    mutationFn: () => api.rerunReview(tr.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trades"] }),
  });
  return (
    <li className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left"
        aria-expanded={open}
      >
        <span
          className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${tr.side === "buy" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300" : "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300"}`}
        >
          {t(tr.side)}
        </span>
        <span className="font-semibold">{tr.symbol}</span>
        <span className="text-sm tabular-nums text-neutral-600 dark:text-neutral-300">
          {tr.quantity} × {money(tr.price, tr.currency, locale, 2)} = {money(tr.notional, tr.currency, locale)}
        </span>
        <span className="text-xs text-neutral-500">
          {t("fee")}: {money(tr.fee, tr.currency, locale, 2)}
        </span>
        {tr.realized_pnl !== null && (
          <span className={`text-xs font-semibold ${changeColor(tr.realized_pnl)}`}>
            {t("realized")}: {money(tr.realized_pnl, tr.currency, locale)}
          </span>
        )}
        <span className="ml-auto flex items-center gap-2 text-xs text-neutral-500">
          {tr.review && (
            <span className="inline-flex items-center gap-1">
              <span className={`h-2 w-2 rounded-full ${VERDICT_DOT[tr.review.verdict]}`} />
              {tr.review.score}/10
            </span>
          )}
          {dateTime(tr.executed_at, locale)}
          <span aria-hidden>{open ? "▴" : "▾"}</span>
        </span>
      </button>
      {open && (
        <div className="border-t border-neutral-100 px-4 py-3 dark:border-neutral-800">
          {tr.review ? (
            <ReviewCard review={tr.review} showDisclaimer={false} />
          ) : (
            <p className="text-sm text-neutral-500">—</p>
          )}
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={() => rerun.mutate()}
              disabled={rerun.isPending}
              className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              {rerun.isPending ? t("loading") : t("rerun_review")}
            </button>
            <Link href={`/ticker/${encodeURIComponent(tr.symbol)}`} className="text-xs text-sky-600 hover:underline">
              {t("open_chart")}
            </Link>
          </div>
        </div>
      )}
    </li>
  );
}

export function TradesView() {
  const { t, user, authReady } = useApp();
  const q = useQuery({ queryKey: ["trades"], queryFn: api.trades, enabled: !!user });
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
  return (
    <div className="space-y-4">
      <PageTitle>{t("history_title")}</PageTitle>
      <Disclaimer compact />
      {q.isPending && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && q.data.length === 0 && (
        <Card>
          <p className="text-sm text-neutral-500">{t("no_trades")}</p>
        </Card>
      )}
      <ul className="space-y-2">
        {q.data?.map((tr) => (
          <TradeRow key={tr.id} tr={tr} />
        ))}
      </ul>
    </div>
  );
}
