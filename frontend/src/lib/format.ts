import type { Locale } from "./types";

const intl = (locale: Locale) => (locale === "kk" ? "kk-KZ" : locale === "ru" ? "ru-RU" : "en-US");

export function money(value: number | null | undefined, currency: string, locale: Locale = "en", digits?: number) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const d = digits ?? (Math.abs(value) >= 1000 ? 0 : 2);
  try {
    return new Intl.NumberFormat(intl(locale), {
      style: "currency",
      currency,
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    }).format(value);
  } catch {
    return `${value.toFixed(d)} ${currency}`;
  }
}

export function num(value: number | null | undefined, locale: Locale = "en", digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(intl(locale), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(
    value,
  );
}

export function compact(value: number | null | undefined, locale: Locale = "en") {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(intl(locale), { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function pct(value: number | null | undefined, digits = 2, signed = true) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const s = (value * 100).toFixed(digits);
  return `${signed && value > 0 ? "+" : ""}${s}%`;
}

export function changeColor(value: number | null | undefined) {
  if (!value) return "text-neutral-500";
  return value > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

export function dateTime(iso: string, locale: Locale = "en") {
  const d = new Date(iso);
  return new Intl.DateTimeFormat(intl(locale), { dateStyle: "medium", timeStyle: "short" }).format(d);
}

export function dateOnly(iso: string, locale: Locale = "en") {
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return new Intl.DateTimeFormat(intl(locale), { dateStyle: "medium" }).format(d);
}
