"use client";

import { useEffect, useState } from "react";

import { wsUrl } from "@/lib/api";

export interface LiveQuote {
  symbol: string;
  price: number;
  prev_close: number | null;
  change_pct?: number;
  ts: string;
}

/** Subscribes to `/ws/prices` for the given symbols; reconnects with back-off. */
export function useLivePrices(symbols: string[]): Record<string, LiveQuote> {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const key = symbols.join(",");

  useEffect(() => {
    if (!key) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 1000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      try {
        ws = new WebSocket(wsUrl(key.split(",")));
      } catch {
        return;
      }
      ws.onopen = () => (retry = 1000);
      ws.onmessage = (e) => {
        try {
          const q = JSON.parse(e.data) as LiveQuote & { type: string };
          if (q.type === "quote") setQuotes((prev) => ({ ...prev, [q.symbol]: q }));
        } catch {}
      };
      ws.onclose = () => {
        if (closed) return;
        timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30_000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [key]);

  return quotes;
}
