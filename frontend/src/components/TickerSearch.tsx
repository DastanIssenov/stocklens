"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import type { Ticker } from "@/lib/types";

export function TickerSearch({ onSelect, navigate = true }: { onSelect?: (t: Ticker) => void; navigate?: boolean }) {
  const { t } = useApp();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const { data = [], isFetching } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: debounced.length > 0,
    staleTime: 60_000,
  });

  const choose = (ticker: Ticker) => {
    setOpen(false);
    setQ("");
    onSelect?.(ticker);
    if (navigate) router.push(`/ticker/${encodeURIComponent(ticker.symbol)}`);
  };

  return (
    <div ref={box} className="relative">
      <input
        type="search"
        value={q}
        placeholder={t("search_placeholder")}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, data.length - 1));
          if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          if (e.key === "Enter" && data[active]) choose(data[active]);
          if (e.key === "Escape") setOpen(false);
        }}
        className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-sm outline-none ring-sky-500 focus:ring-2 dark:border-neutral-700 dark:bg-neutral-900"
        aria-label={t("search_placeholder")}
      />
      {open && debounced && (
        <ul className="absolute z-40 mt-1 max-h-80 w-full min-w-[16rem] overflow-auto rounded-lg border border-neutral-200 bg-white py-1 shadow-lg dark:border-neutral-700 dark:bg-neutral-900">
          {isFetching && data.length === 0 && <li className="px-3 py-2 text-sm text-neutral-500">{t("loading")}</li>}
          {!isFetching && data.length === 0 && <li className="px-3 py-2 text-sm text-neutral-500">—</li>}
          {data.map((tk, i) => (
            <li key={tk.symbol}>
              <button
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(tk)}
                className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm ${
                  i === active ? "bg-neutral-100 dark:bg-neutral-800" : ""
                }`}
              >
                <span className="font-semibold">{tk.symbol}</span>
                <span className="truncate text-xs text-neutral-500">{tk.name}</span>
                <span className="shrink-0 rounded bg-neutral-100 px-1.5 text-[10px] text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                  {tk.exchange}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
