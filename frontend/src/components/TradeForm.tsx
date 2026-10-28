"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { money } from "@/lib/format";
import type { Ticker, Trade } from "@/lib/types";

import { ReviewCard } from "./ReviewCard";

// Mirrors backend/app/services/trading.py:compute_fee (estimate only; the server is the source of truth)
export function estimateFee(exchange: string, notional: number): number {
  if (exchange === "NASDAQ" || exchange === "NYSE") return Math.max(1, notional * 0.0005);
  if (exchange === "LSE") return Math.max(3, notional * 0.001);
  return Math.max(300, notional * 0.0015);
}

export function TradeForm({
  ticker,
  price,
}: {
  ticker: Pick<Ticker, "symbol" | "exchange" | "currency">;
  price: number | null;
}) {
  const { t, locale, user } = useApp();
  const qc = useQueryClient();
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [qty, setQty] = useState("1");
  const [result, setResult] = useState<Trade | null>(null);
  const quantity = Math.floor(Number(qty));
  const valid = Number.isFinite(quantity) && quantity > 0;
  const notional = price && valid ? price * quantity : 0;
  const fee = notional ? estimateFee(ticker.exchange, notional) : 0;

  const m = useMutation({
    mutationFn: () => api.trade(ticker.symbol, side, quantity),
    onSuccess: (tr) => {
      setResult(tr);
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["trades"] });
    },
  });

  if (!user)
    return (
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        <Link href="/login" className="font-semibold text-sky-600 hover:underline">
          {t("nav_login")}
        </Link>{" "}
        — {t("login_to_trade")}
      </p>
    );

  return (
    <div className="space-y-3">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) m.mutate();
        }}
      >
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-neutral-100 p-1 dark:bg-neutral-800" role="radiogroup">
          {(["buy", "sell"] as const).map((s) => (
            <button
              type="button"
              key={s}
              role="radio"
              aria-checked={side === s}
              onClick={() => setSide(s)}
              className={`rounded-md py-1.5 text-sm font-semibold ${
                side === s
                  ? s === "buy"
                    ? "bg-emerald-600 text-white"
                    : "bg-rose-600 text-white"
                  : "text-neutral-600 dark:text-neutral-300"
              }`}
            >
              {t(s)}
            </button>
          ))}
        </div>
        <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-400">
          {t("quantity")}
          <input
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            className="mt-1 w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm tabular-nums dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>
        <dl className="grid grid-cols-2 gap-y-1 text-xs text-neutral-600 dark:text-neutral-400">
          <dt>{t("price")}</dt>
          <dd className="text-right tabular-nums">{money(price, ticker.currency, locale, 2)}</dd>
          <dt>{t("est_cost")}</dt>
          <dd className="text-right tabular-nums">{money(notional, ticker.currency, locale, 2)}</dd>
          <dt>{t("est_fee")}</dt>
          <dd className="text-right tabular-nums">{money(fee, ticker.currency, locale, 2)}</dd>
        </dl>
        <button
          type="submit"
          disabled={!valid || !price || m.isPending}
          className="w-full rounded-lg bg-sky-600 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.isPending ? t("loading") : `${t("place_order")} · ${t(side)} ${valid ? quantity : ""} ${ticker.symbol}`}
        </button>
        {m.error && (
          <p role="alert" className="text-sm text-rose-600">
            {m.error instanceof ApiError ? m.error.message : String(m.error)}
          </p>
        )}
      </form>
      {result?.review && (
        <div className="rounded-xl border border-sky-200 bg-sky-50/50 p-3 dark:border-sky-900 dark:bg-sky-950/30">
          <h3 className="mb-2 text-sm font-semibold">
            {t("review_title")} — {t(result.side)} {result.quantity} {result.symbol} @{" "}
            {money(result.price, result.currency, locale, 2)}
          </h3>
          <ReviewCard review={result.review} />
        </div>
      )}
    </div>
  );
}
