// Thin fetch wrapper for the FastAPI backend. All calls go to same-origin `/api/v1`
// (nginx in Docker, Next.js rewrites in `npm run dev`).
import type {
  AuthOut,
  MarketOverview,
  Meta,
  NewsItem,
  Portfolio,
  Predictions,
  PriceHistory,
  Review,
  Ticker,
  TickerDetail,
  TokenPair,
  Trade,
  User,
  Fx,
} from "./types";

const BASE = "/api/v1";
const TOKENS_KEY = "sp.tokens";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function loadTokens(): TokenPair | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(TOKENS_KEY);
    return raw ? (JSON.parse(raw) as TokenPair) : null;
  } catch {
    return null;
  }
}

export function saveTokens(tokens: TokenPair | null): void {
  if (typeof window === "undefined") return;
  if (tokens) window.localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  else window.localStorage.removeItem(TOKENS_KEY);
  window.dispatchEvent(new Event("sp-auth-changed"));
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return res.statusText || `HTTP ${res.status}`;
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  const tokens = loadTokens();
  if (!tokens) return false;
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });
      if (!res.ok) {
        saveTokens(null);
        return false;
      }
      saveTokens((await res.json()) as TokenPair);
      return true;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

export async function request<T>(path: string, init: RequestInit = {}, auth = false, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (auth) {
    const tokens = loadTokens();
    if (tokens) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 401 && auth && retry && (await tryRefresh())) {
    return request<T>(path, init, auth, false);
  }
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  register: (email: string, password: string, display_name: string | null, locale: string) =>
    request<AuthOut>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name, locale }),
    }),
  login: (email: string, password: string) =>
    request<AuthOut>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request<User>("/auth/me", {}, true),

  overview: (market: string) => request<MarketOverview>(`/market/overview${qs({ market })}`),
  tickers: (market?: string, q?: string) => request<Ticker[]>(`/tickers${qs({ market, q })}`),
  search: (q: string) => request<Ticker[]>(`/tickers/search${qs({ q })}`),
  ticker: (symbol: string) => request<TickerDetail>(`/tickers/${encodeURIComponent(symbol)}`),
  prices: (symbol: string, start?: string) =>
    request<PriceHistory>(`/prices/${encodeURIComponent(symbol)}${qs({ start })}`),
  news: (params: { symbol?: string; lang?: string; market?: string; limit?: number }) =>
    request<NewsItem[]>(`/news${qs(params)}`),
  predictions: (symbol: string) => request<Predictions>(`/predictions/${encodeURIComponent(symbol)}`),
  fx: () => request<Fx>("/fx/latest"),
  meta: () => request<Meta>("/meta"),

  portfolio: () => request<Portfolio>("/portfolio", {}, true),
  resetPortfolio: () => request<Portfolio>("/portfolio/reset", { method: "POST" }, true),
  trades: () => request<Trade[]>("/trades", {}, true),
  trade: (symbol: string, side: "buy" | "sell", quantity: number) =>
    request<Trade>("/trades", { method: "POST", body: JSON.stringify({ symbol, side, quantity }) }, true),
  rerunReview: (id: number) => request<Review>(`/trades/${id}/review`, { method: "POST" }, true),
};

export function wsUrl(symbols: string[]): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  const q = `?symbols=${encodeURIComponent(symbols.join(","))}`;
  if (env) return `${env}${q}`;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/prices${q}`;
}
