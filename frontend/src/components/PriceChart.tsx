"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Bar } from "@/lib/types";

const toTime = (d: string) => (Date.parse(`${d}T00:00:00Z`) / 1000) as UTCTimestamp;

export function PriceChart({ bars, height = 380 }: { bars: Bar[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
    const text = dark ? "#d4d4d4" : "#404040";
    const grid = dark ? "#262626" : "#f0f0f0";
    const chart = createChart(ref.current, {
      autoSize: true,
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text, attributionLogo: true },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: false },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f43f5e",
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
      borderVisible: false,
    });
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "" });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.25 } });
    candles.setData(
      bars.map((b) => ({ time: toTime(b.date), open: b.open, high: b.high, low: b.low, close: b.close })),
    );
    volume.setData(
      bars.map((b) => ({
        time: toTime(b.date),
        value: b.volume,
        color: b.close >= b.open ? "rgba(16,185,129,0.35)" : "rgba(244,63,94,0.35)",
      })),
    );
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, height]);

  return <div ref={ref} style={{ height }} className="w-full" data-testid="price-chart" />;
}
