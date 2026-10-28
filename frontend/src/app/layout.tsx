import type { Metadata, Viewport } from "next";
import { Suspense } from "react";

import { Footer } from "@/components/Disclaimer";
import { Header, NavLinks, StaticNavLinks } from "@/components/Header";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "StockLens — US & Kazakhstan markets", template: "%s · StockLens" },
  description:
    "Educational stock platform: quotes, charts, demo predictions and a paper-trading sandbox with AI reviews. Not investment advice.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-neutral-50 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
        <Providers>
          <Header
            nav={
              <Suspense fallback={<StaticNavLinks />}>
                <NavLinks />
              </Suspense>
            }
          />
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
          <Footer />
        </Providers>
      </body>
    </html>
  );
}
