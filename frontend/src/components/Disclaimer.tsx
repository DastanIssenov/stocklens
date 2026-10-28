"use client";

import { useApp } from "@/lib/app-context";

export function Disclaimer({ compact = false }: { compact?: boolean }) {
  const { t } = useApp();
  return (
    <div
      role="note"
      className={`flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200 ${
        compact ? "px-3 py-2 text-xs" : "px-4 py-3 text-sm"
      }`}
    >
      <span aria-hidden className="mt-0.5">
        ⚠️
      </span>
      <span>{t("disclaimer")}</span>
    </div>
  );
}

export function DemoBadge({ show = true }: { show?: boolean }) {
  const { t } = useApp();
  if (!show) return null;
  return (
    <span
      title={t("demo_hint")}
      className="inline-flex items-center gap-1 rounded-full border border-violet-300 bg-violet-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-violet-700 dark:border-violet-700 dark:bg-violet-950/50 dark:text-violet-300"
    >
      <span aria-hidden>●</span> {t("demo_badge")}
    </span>
  );
}

export function Footer() {
  const { t } = useApp();
  return (
    <footer className="mt-12 border-t border-neutral-200 dark:border-neutral-800">
      <div className="mx-auto max-w-7xl space-y-2 px-4 py-6 text-xs text-neutral-500">
        <p>{t("disclaimer")}</p>
        <p>
          Data: Alpaca (US), Tradernet / Freedom Broker (KASE), Yahoo Finance (LSE GDRs, FX, Brent), National Bank of
          Kazakhstan (official USD/KZT), Finnhub, RSS feeds of the cited publishers. Headlines link to the original
          source.
        </p>
      </div>
    </footer>
  );
}
