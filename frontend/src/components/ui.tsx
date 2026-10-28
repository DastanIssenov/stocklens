"use client";

import type { ReactNode } from "react";

import { useApp } from "@/lib/app-context";

export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900 ${className}`}
    >
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-100">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  sub,
  className = "",
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900 ${className}`}
    >
      <div className="text-xs font-medium text-neutral-500">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-neutral-500">{sub}</div>}
    </div>
  );
}

export function Loading() {
  const { t } = useApp();
  return <div className="animate-pulse py-6 text-center text-sm text-neutral-500">{t("loading")}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const { t } = useApp();
  return (
    <div className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
      {t("error_loading")} {error instanceof Error ? <span className="opacity-80">({error.message})</span> : null}
    </div>
  );
}

export function Sparkline({ values, width = 96, height = 28 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <span className="inline-block" style={{ width, height }} />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map(
      (v, i) =>
        `${((i / (values.length - 1)) * width).toFixed(1)},${(height - ((v - min) / span) * (height - 2) - 1).toFixed(1)}`,
    )
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="overflow-visible">
      <polyline points={pts} fill="none" strokeWidth="1.5" className={up ? "stroke-emerald-500" : "stroke-rose-500"} />
    </svg>
  );
}

export function PageTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-bold tracking-tight sm:text-2xl">{children}</h1>
      {right}
    </div>
  );
}
