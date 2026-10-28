"use client";

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";

import { api, saveTokens } from "./api";
import { translate, type Dict } from "./i18n";
import type { AuthOut, Locale, Market, User } from "./types";

interface AppState {
  locale: Locale;
  setLocale: (l: Locale) => void;
  market: Market;
  setMarket: (m: Market) => void;
  t: (key: keyof Dict) => string;
  user: User | null;
  authReady: boolean;
  onAuth: (a: AuthOut) => void;
  logout: () => void;
}

const Ctx = createContext<AppState | null>(null);

let browserQueryClient: QueryClient | undefined;
function getQueryClient() {
  const make = () =>
    new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } } });
  if (typeof window === "undefined") return make();
  browserQueryClient ??= make();
  return browserQueryClient;
}

// ---- localStorage-backed external store (preferences + tokens), hydration-safe via useSyncExternalStore
const listeners = new Set<() => void>();
function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  window.addEventListener("sp-auth-changed", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
    window.removeEventListener("sp-auth-changed", cb);
  };
}
function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
  listeners.forEach((l) => l());
}

function usePref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  const raw = useSyncExternalStore(
    subscribe,
    () => readStorage(key),
    () => null,
  );
  return raw && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback;
}

const LOCALES = ["en", "ru", "kk"] as const;
const MARKETS = ["US", "KZ"] as const;

function AppStateProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const locale = usePref<Locale>("sp.locale", LOCALES, "en");
  const market = usePref<Market>("sp.market", MARKETS, "US");
  const tokensRaw = useSyncExternalStore(
    subscribe,
    () => readStorage("sp.tokens"),
    () => null,
  );
  const me = useQuery({ queryKey: ["me", tokensRaw], queryFn: api.me, enabled: !!tokensRaw, retry: false });
  const user = tokensRaw ? (me.data ?? null) : null;
  const authReady = !tokensRaw || !me.isPending;

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<AppState>(
    () => ({
      locale,
      setLocale: (l) => writeStorage("sp.locale", l),
      market,
      setMarket: (m) => writeStorage("sp.market", m),
      t: (key) => translate(locale, key),
      user,
      authReady,
      onAuth: (a) => {
        qc.setQueryData(["me", JSON.stringify(a.tokens)], a.user);
        saveTokens(a.tokens);
        writeStorage("sp.locale", a.user.locale);
      },
      logout: () => {
        saveTokens(null);
        qc.removeQueries({ queryKey: ["portfolio"] });
        qc.removeQueries({ queryKey: ["trades"] });
        qc.removeQueries({ queryKey: ["me"] });
      },
    }),
    [locale, market, user, authReady, qc],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={getQueryClient()}>
      <AppStateProvider>{children}</AppStateProvider>
    </QueryClientProvider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used inside <Providers>");
  return ctx;
}
