"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useApp } from "@/lib/app-context";
import { LOCALES } from "@/lib/i18n";
import type { Market } from "@/lib/types";

import { TickerSearch } from "./TickerSearch";

const LINKS = [
  { href: "/", key: "nav_home" },
  { href: "/trade", key: "nav_trade" },
  { href: "/portfolio", key: "nav_portfolio" },
  { href: "/trades", key: "nav_history" },
  { href: "/models", key: "nav_models" },
] as const;

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { t } = useApp();
  return (
    <>
      {LINKS.map((l) => {
        const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            onClick={onNavigate}
            className={`whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              active
                ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"
                : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
            }`}
          >
            {t(l.key)}
          </Link>
        );
      })}
    </>
  );
}

export function StaticNavLinks() {
  const { t } = useApp();
  return (
    <>
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className="whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium text-neutral-600 dark:text-neutral-300"
        >
          {t(l.key)}
        </Link>
      ))}
    </>
  );
}

export function MarketSwitch() {
  const { market, setMarket, t } = useApp();
  const opts: { m: Market; label: string; flag: string }[] = [
    { m: "US", label: t("market_us"), flag: "🇺🇸" },
    { m: "KZ", label: t("market_kz"), flag: "🇰🇿" },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Market"
      className="inline-flex rounded-lg border border-neutral-200 p-0.5 dark:border-neutral-700"
    >
      {opts.map((o) => (
        <button
          key={o.m}
          role="radio"
          aria-checked={market === o.m}
          onClick={() => setMarket(o.m)}
          className={`whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
            market === o.m
              ? "bg-sky-600 text-white"
              : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
          }`}
        >
          <span aria-hidden>{o.flag}</span> {o.label}
        </button>
      ))}
    </div>
  );
}

function LanguageSwitch() {
  const { locale, setLocale, t } = useApp();
  return (
    <label className="inline-flex items-center gap-1 text-xs text-neutral-500">
      <span className="sr-only">{t("language")}</span>
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as typeof locale)}
        className="rounded-md border border-neutral-200 bg-transparent px-1.5 py-1 text-xs font-semibold text-neutral-700 dark:border-neutral-700 dark:text-neutral-200"
      >
        {LOCALES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function AuthButtons() {
  const { user, logout, t, authReady } = useApp();
  if (!authReady) return <span className="h-8 w-16" />;
  if (user)
    return (
      <div className="flex items-center gap-2">
        <span className="hidden max-w-[10rem] truncate text-xs text-neutral-500 lg:inline" title={user.email}>
          {user.display_name || user.email}
        </span>
        <button
          onClick={logout}
          className="whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          {t("nav_logout")}
        </button>
      </div>
    );
  return (
    <div className="flex items-center gap-1">
      <Link
        href="/login"
        className="whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-100 dark:text-neutral-200 dark:hover:bg-neutral-800"
      >
        {t("nav_login")}
      </Link>
      <Link
        href="/register"
        className="whitespace-nowrap rounded-md bg-sky-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-sky-700"
      >
        {t("nav_register")}
      </Link>
    </div>
  );
}

export function Header({ nav }: { nav: React.ReactNode }) {
  const { t } = useApp();
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-30 border-b border-neutral-200 bg-white/90 backdrop-blur dark:border-neutral-800 dark:bg-neutral-950/90">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-sky-500 to-emerald-500 text-sm font-black text-white">
            SL
          </span>
          <span className="hidden flex-col leading-tight sm:flex">
            <span className="text-sm font-bold">{t("brand")}</span>
            <span className="text-[10px] text-neutral-500">{t("tagline")}</span>
          </span>
        </Link>
        <nav className="ml-2 hidden items-center gap-1 lg:flex">{nav}</nav>
        <div className="ml-auto hidden w-48 md:block xl:w-64">
          <TickerSearch />
        </div>
        <div className="ml-auto flex items-center gap-2 md:ml-0">
          <MarketSwitch />
          <LanguageSwitch />
          <div className="hidden sm:block">
            <AuthButtons />
          </div>
          <button
            className="rounded-md p-2 text-neutral-600 hover:bg-neutral-100 lg:hidden dark:text-neutral-300 dark:hover:bg-neutral-800"
            aria-label="Menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h14M3 10h14M3 14h14" />
            </svg>
          </button>
        </div>
      </div>
      {open && (
        <div className="border-t border-neutral-200 px-4 pb-3 lg:hidden dark:border-neutral-800">
          <div className="py-2 md:hidden">
            <TickerSearch onSelect={() => setOpen(false)} />
          </div>
          <nav className="flex flex-col gap-1">
            <NavLinks onNavigate={() => setOpen(false)} />
          </nav>
          <div className="mt-2 sm:hidden">
            <AuthButtons />
          </div>
        </div>
      )}
    </header>
  );
}

export { NavLinks };
