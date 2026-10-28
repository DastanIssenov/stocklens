"use client";

import { useApp } from "@/lib/app-context";
import type { Review } from "@/lib/types";

import { Disclaimer } from "./Disclaimer";

const VERDICT_STYLE: Record<Review["verdict"], string> = {
  reasonable: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  risky: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  poor: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

function List({ title, items, icon }: { title: string; items: string[]; icon: string }) {
  if (!items.length) return null;
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h4>
      <ul className="space-y-1">
        {items.map((s, i) => (
          <li key={i} className="flex gap-2 text-sm leading-snug">
            <span aria-hidden className="shrink-0">
              {icon}
            </span>
            <span>{s}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReviewCard({ review, showDisclaimer = true }: { review: Review; showDisclaimer?: boolean }) {
  const { t } = useApp();
  const verdictLabel = t(`verdict_${review.verdict}` as "verdict_risky");
  return (
    <div className="@container space-y-3" data-testid="review-card">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2.5 py-1 text-xs font-bold uppercase ${VERDICT_STYLE[review.verdict]}`}>
          {verdictLabel}
        </span>
        <span className="text-sm font-semibold tabular-nums">
          {t("score")}: {review.score}/10
        </span>
        <span className="ml-auto text-[11px] text-neutral-500">
          {t("reviewer")}: {review.reviewer === "mock" ? "rules (demo)" : "LLM"} ·{" "}
          <span className="font-mono">{review.model}</span>
        </span>
      </div>
      {review.summary && <p className="text-sm text-neutral-700 dark:text-neutral-300">{review.summary}</p>}
      <div className="grid gap-3 @xl:grid-cols-3">
        <List title={t("reasons")} items={review.reasons} icon="•" />
        <List title={t("risks")} items={review.risks} icon="⚠" />
        <List title={t("what_to_watch")} items={review.what_to_watch} icon="👁" />
      </div>
      {showDisclaimer && <Disclaimer compact />}
    </div>
  );
}
