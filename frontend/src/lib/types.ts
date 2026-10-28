// Types mirror backend/app/schemas/api.py

export type Market = "US" | "KZ";
export type Locale = "en" | "ru" | "kk";

export interface User {
  id: number;
  email: string;
  display_name: string | null;
  locale: Locale;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AuthOut {
  user: User;
  tokens: TokenPair;
}

export interface Ticker {
  symbol: string;
  local_symbol: string;
  name: string;
  exchange: string;
  market: Market;
  currency: "USD" | "KZT";
  sector: string | null;
  country: string;
  issuer: string | null;
  is_liquid: boolean;
}

export interface Quote {
  symbol: string;
  price: number;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  currency: string;
  as_of: string;
  source: string;
  is_live: boolean;
}

export interface TickerDetail extends Ticker {
  quote: Quote | null;
  other_listings: Ticker[];
}

export interface Bar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceHistory {
  symbol: string;
  currency: string;
  bars: Bar[];
}

export interface OverviewRow {
  symbol: string;
  name: string;
  exchange: string;
  currency: string;
  sector: string | null;
  is_liquid: boolean;
  price: number | null;
  change_pct: number | null;
  as_of: string | null;
  sparkline: number[];
}

export interface Fx {
  pair: string;
  official: number | null;
  official_date: string | null;
  market: number | null;
  market_date: string | null;
  rate_used: number;
}

export interface MarketOverview {
  market: Market;
  rows: OverviewRow[];
  gainers: OverviewRow[];
  losers: OverviewRow[];
  fx: Fx;
  brent: number | null;
  brent_date: string | null;
}

export interface NewsItem {
  id: number;
  source: string;
  lang: string;
  published_at: string;
  title: string;
  summary: string | null;
  url: string;
  sentiment: number | null;
  symbols: string[];
}

export interface Feature {
  name: string;
  value: number | null;
  contribution: number;
}

export interface Prediction {
  horizon: string;
  horizon_days: number;
  as_of_date: string;
  predicted_return: number;
  prob_up: number;
  confidence: number;
  top_features: Feature[];
  model_version: string;
  is_demo: boolean;
}

export interface Predictions {
  symbol: string;
  short_term: Prediction[];
  long_term: Prediction[];
  is_demo: boolean;
  disclaimer: string;
}

export interface Position {
  symbol: string;
  name: string;
  exchange: string;
  currency: string;
  quantity: number;
  avg_cost: number;
  price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  realized_pnl: number;
  weight: number | null;
}

export interface Portfolio {
  cash_usd: number;
  cash_kzt: number;
  positions: Position[];
  positions_value_usd: number;
  positions_value_kzt: number;
  total_value_usd: number;
  total_value_kzt: number;
  initial_value_usd: number;
  total_pnl_usd: number;
  total_pnl_pct: number;
  usdkzt: number;
  disclaimer: string;
}

export interface Review {
  reviewer: string;
  model: string;
  verdict: "reasonable" | "risky" | "poor";
  score: number;
  summary: string | null;
  reasons: string[];
  risks: string[];
  what_to_watch: string[];
  created_at: string | null;
  disclaimer: string;
}

export interface Trade {
  id: number;
  symbol: string;
  name: string;
  exchange: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  fee: number;
  currency: string;
  notional: number;
  realized_pnl: number | null;
  price_source: string;
  executed_at: string;
  review: Review | null;
}

export interface Meta {
  prediction_provider: string;
  predictions_are_demo: boolean;
  trade_reviewer: string;
  trade_reviewer_model: string;
  currencies: string[];
  markets: string[];
  disclaimer: string;
}
