# Blockers

Problems that could not be solved during the autonomous run. Each entry: what is blocked, what was done instead (stub/mock), and what a human needs to do.

| # | Blocker | Workaround in place | What is needed | Status |
|---|---------|---------------------|----------------|--------|
| 1 | No GPU on this machine | ML models are mocked behind `PredictionProvider` / `TradeReviewer`; GPU work planned in `docs/GPU_PLAN.md` | RTX 5090 machine | open (expected) |
| 2 | KASE data licence: the free source (Tradernet `getHloc`) has no published API terms; the official KASE API is a paid subscription | Tradernet used at ≤ 1 batched request per run for an educational, non-commercial prototype | Before any public launch: e-mail `mds@kase.kz` for the KASE "Market Prices of Securities" API (academic pricing?) or get written OK from Freedom Broker | open |
| 3 | AIX market data: no free API; website is behind Cloudflare bot protection | AIX-listed Kazakh companies are covered through their KASE listing; `AIX` exists as an exchange code | Ask AIX (aix.kz) for academic data access or use LSEG via the university | open |
| 4 | Forbes.kz RSS returns no items; Inform.kz RSS returns 403; KASE has no RSS | Other KZ outlets (Kursiv, Kapital, Inbusiness ru/kk, Tengrinews ru/kk, LSM) are used | GPU phase: Forbes.kz news sitemap (robots.txt allows), KASE / dfo.kz disclosures via HTML with low rate | open |
| 5 | GitHub Actions has not run yet: the repo is not pushed (TASK §0.4: do not push without the owner) | Every CI step was run locally with identical commands (`make test`, `alembic check`, `docker compose build`) | Push to GitHub and check the first CI run | open |
