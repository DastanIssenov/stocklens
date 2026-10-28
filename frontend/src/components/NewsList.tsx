"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { dateTime } from "@/lib/format";

import { Card, ErrorBox, Loading } from "./ui";

export function NewsList({
  symbol,
  market,
  limit = 12,
  title,
}: {
  symbol?: string;
  market?: string;
  limit?: number;
  title?: string;
}) {
  const { t, locale } = useApp();
  const q = useQuery({ queryKey: ["news", symbol, market, limit], queryFn: () => api.news({ symbol, market, limit }) });
  return (
    <Card title={title ?? t("news")}>
      {q.isPending && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && q.data.length === 0 && <p className="text-sm text-neutral-500">{t("no_news")}</p>}
      <ul className="divide-y divide-neutral-100 dark:divide-neutral-800">
        {q.data?.map((n) => (
          <li key={n.id} className="py-2.5">
            <a href={n.url} target="_blank" rel="noopener noreferrer nofollow" className="group block">
              <p className="text-sm font-medium leading-snug group-hover:text-sky-600 dark:group-hover:text-sky-400">
                {n.title}
              </p>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-neutral-500">
                <span className="font-medium uppercase">{n.source}</span>
                <span>{dateTime(n.published_at, locale)}</span>
                <span className="rounded bg-neutral-100 px-1 uppercase dark:bg-neutral-800">
                  {n.lang === "kk" ? "kz" : n.lang}
                </span>
                {n.symbols.slice(0, 4).map((s) => (
                  <span key={s} className="font-mono text-sky-700 dark:text-sky-400">
                    {s}
                  </span>
                ))}
              </p>
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
