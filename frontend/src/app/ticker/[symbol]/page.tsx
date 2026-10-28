import { Suspense } from "react";

import { TickerView } from "./ticker-view";

export default function TickerPage() {
  return (
    <Suspense fallback={<div className="py-10 text-center text-sm text-neutral-500">…</div>}>
      <TickerView />
    </Suspense>
  );
}
