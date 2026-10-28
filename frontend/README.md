# Frontend (Next.js 16 App Router)

TypeScript, Tailwind CSS 4, TradingView lightweight-charts 5, TanStack Query 5.

```bash
npm ci
BACKEND_URL=http://localhost:8000 npm run dev   # proxies /api to the backend (next.config.ts rewrites)
npm run lint && npm run typecheck && npm run format:check
npm run build                                   # standalone output for Docker
```

- All data is fetched client-side from `/api/v1` (same origin: nginx in Docker, rewrites in dev).
- Live prices: WebSocket `/ws/prices` (set `NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/prices` when running without nginx).
- UI languages: EN / RU / KK (`src/lib/i18n.ts`); market switch US / KZ; preferences in `localStorage`.
- Every page with predictions or reviews shows the "not investment advice" disclaimer and a "Demo predictions" badge while mock models are used.
