"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { changeColor, dateOnly, pct } from "@/lib/format";
import { HORIZON_LABEL } from "@/lib/i18n";
import type { Prediction } from "@/lib/types";

import { DemoBadge, Disclaimer } from "./Disclaimer";
import { Card, ErrorBox, Loading } from "./ui";

function ProbBar({ p }: { p: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-rose-200 dark:bg-rose-900/60" aria-hidden>
      <div className="h-full bg-emerald-500" style={{ width: `${Math.round(p * 100)}%` }} />
    </div>
  );
}

function Row({ p }: { p: Prediction }) {
  const { locale, t } = useApp();
  return (
    <li className="rounded-lg border border-neutral-100 p-3 dark:border-neutral-800">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">{HORIZON_LABEL[locale][p.horizon] ?? p.horizon}</span>
        <span className={`text-sm font-semibold tabular-nums ${changeColor(p.predicted_return)}`}>
          {pct(p.predicted_return)}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-2 text-xs text-neutral-500">
        <span className="w-16 shrink-0">{t("prob_up")}</span>
        <ProbBar p={p.prob_up} />
        <span className="w-10 shrink-0 text-right tabular-nums">{Math.round(p.prob_up * 100)}%</span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-xs text-neutral-500">
        <span className="w-16 shrink-0">{t("confidence")}</span>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
          <div className="h-full bg-sky-500" style={{ width: `${Math.round(p.confidence * 100)}%` }} />
        </div>
        <span className="w-10 shrink-0 text-right tabular-nums">{Math.round(p.confidence * 100)}%</span>
      </div>
      {p.top_features.length > 0 && (
        <details className="mt-2 text-xs text-neutral-500">
          <summary className="cursor-pointer select-none">{t("top_features")}</summary>
          <ul className="mt-1 space-y-0.5">
            {p.top_features.slice(0, 5).map((f) => (
              <li key={f.name} className="flex justify-between gap-2 font-mono">
                <span>{f.name}</span>
                <span>{f.value === null ? "—" : f.value}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

export function PredictionPanel({ symbol }: { symbol: string }) {
  const { t, locale } = useApp();
  const q = useQuery({ queryKey: ["predictions", symbol], queryFn: () => api.predictions(symbol) });
  return (
    <Card title={t("predictions")} actions={<DemoBadge show={q.data?.is_demo ?? true} />}>
      {q.isPending && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && (
        <div className="space-y-4">
          {q.data.short_term.length === 0 && q.data.long_term.length === 0 && (
            <p className="text-sm text-neutral-500">{t("no_data")}</p>
          )}
          {[
            ["short_term", q.data.short_term],
            ["long_term", q.data.long_term],
          ].map(([label, rows]) =>
            (rows as Prediction[]).length ? (
              <div key={label as string}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                  {t(label as "short_term")}
                </h3>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {(rows as Prediction[]).map((p) => (
                    <Row key={p.horizon} p={p} />
                  ))}
                </ul>
              </div>
            ) : null,
          )}
          {q.data.short_term[0] && (
            <p className="text-[11px] text-neutral-500">
              {t("model")}: <span className="font-mono">{q.data.short_term[0].model_version}</span> · {t("as_of")}{" "}
              {dateOnly(q.data.short_term[0].as_of_date, locale)}
            </p>
          )}
          <Disclaimer compact />
        </div>
      )}
    </Card>
  );
}
