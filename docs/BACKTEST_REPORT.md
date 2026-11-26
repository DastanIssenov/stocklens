# Backtest report — short-term model (5 days), CPU

Educational project — **not investment advice**. These numbers are research results, not a trading record.
Current model: **v2** (`gbm-ens-cpu-32704ac5`). The previous baseline **v1** (`lgbm-cpu-93314193`) is kept below for comparison.

## How v2 was chosen (no tuning on the test years)
1. `python -m ml.experiments.ablation` tried every change on **dev folds 2016–2018 only** and kept a step only if it
   raised the dev mean daily rank IC → [`ABLATION_DEV.md`](ABLATION_DEV.md).
2. The chosen setup was written to `ml/configs/short_gbm.yaml` and evaluated **once** on the 2019–2026 test folds.
   A second identical run (after a display-only calibration fix) reproduced every metric exactly.

| Change (dev folds 2016–2018) | Dev IC | Kept? |
|---|---|---|
| v1: label "price up in 5 days", 44 features | 0.013 (t 1.8) | reference |
| label "beats the day's median 5-day return" (`xup_5`) | 0.023 (t 3.1) | ✅ |
| drop `hy_spread` (FRED serves ICE BofA data only from 2023-10 → empty for 2010–2023) | 0.023 | ✅ (data defect) |
| + residual (market-adjusted) returns | 0.022 | ❌ |
| + 12 cross-sectional rank features | **0.030 (t 3.9)** | ✅ |
| + filing / earnings-reaction features (SEC 10-Q/10-K timestamps) | 0.020 | ❌ |
| + macro changes (next to the levels) | 0.020 | ❌ |
| − macro levels (10y−2y, Fed funds) | 0.024 | ❌ |
| − calendar (dow, month) | 0.023 | ❌ |
| stronger LightGBM regularisation | 0.024 | ❌ |
| mean of LightGBM + XGBoost | **0.031 (t 4.1)** | ✅ |
| portfolio: top 10 %, keep while in top 30 %, 3-day score EMA | dev Sharpe 1.12 vs 1.04 | ✅ (best of 18) |

## Setup (v2)
| Item | Value |
|---|---|
| Universe | 102 US stocks (today's 100 most liquid + KSPI, FRHC; D-028); 99 have ≥ 252 days of history in the panel |
| Data | daily bars 2010-01-04 → 2026-10-27, SPY / ^VIX, FRED macro joined on publication date |
| Features | 55: the 44 of v1 minus `hy_spread`, plus 12 within-day percentile ranks (`FEATURE_GROUPS["ranks"]`) |
| Label | `xup_5` = 1 if the stock's 5-day forward return beats that day's median across the universe (50/50 by construction) |
| Validation | expanding walk-forward, 8 yearly test folds 2019 → 2026, purge 5 + embargo 5 sessions |
| Model | mean probability of LightGBM (400 trees) and XGBoost (400 trees) |
| Strategy | every 5 days rank by the 3-day EMA of the score, buy the top 10 % equal-weight, keep a holding while it ranks in the top 30 %; **10 bps per side**; benchmark = equal-weight universe |
| Out-of-sample rows | 172 516 (identical to v1) |
| MLflow | run `32704ac5072f44d3af06ff48f54a3d82`, experiment `short_term_gbm`; ≈ 2.5 min on an 8-core laptop CPU |

## Results, test folds 2019–2026 (pooled, out of sample)
| Model | IC | IC t | AUC (up) | AUC (beats median) | Accuracy | Strategy Sharpe | Bench Sharpe | CAGR | Vol | Max DD | Turnover |
|---|---|---|---|---|---|---|---|---|---|---|---|
| persistence | −0.007 | −1.3 | 0.497 | 0.499 | 50.1 % | 1.12 | 1.36 | 37.1 % | 33 % | −44.6 % | 1.35 |
| 21-day momentum | −0.002 | −0.3 | 0.499 | 0.501 | 50.1 % | **1.55** | 1.36 | **64.3 %** | 36 % | −37.9 % | 0.51 |
| logistic regression | 0.009 | 1.6 | 0.499 | 0.504 | 50.2 % | 1.07 | 1.36 | 47.7 % | 47 % | −66.1 % | 0.69 |
| LightGBM | **0.024** | **4.5** | 0.505 | 0.515 | 51.0 % | 1.32 | 1.36 | 57.0 % | 40 % | −67.6 % | 0.49 |
| XGBoost | 0.020 | 3.7 | 0.504 | 0.514 | 50.9 % | 1.37 | 1.36 | 59.2 % | 40 % | −57.3 % | 0.49 |
| **ensemble (v2)** | 0.023 | 4.2 | 0.505 | 0.515 | 51.0 % | 1.38 | 1.36 | 59.6 % | 40 % | −63.6 % | 0.49 |

Benchmark (equal-weight universe): CAGR 35.3 %, vol 24 %, max DD −33.4 %, Sortino 1.79 (ensemble 1.85).
Baselines use the same portfolio rule, so the strategy columns compare signals, not rules.

### v1 vs v2
| Metric (2019–2026) | v1 LightGBM | v2 ensemble |
|---|---|---|
| Label | price up in 5 days (54.6 % of rows) | beats the day's median (49.8 % of rows) |
| Accuracy at 0.5 | 52.5 % — **below** "always up" (54.6 %) | 51.0 % — above the best constant guess (50.2 %) |
| Precision / recall, positive class | 55.1 % / 70.2 % | 50.7 % / 50.3 % |
| Precision / recall, negative class | 46.5 % / 31.2 % | 51.2 % / 51.6 % |
| Share of rows predicted positive | 69.6 % (15 %–99.9 % by year) | 49.4 % (42 %–62 % by year) |
| Log-loss (ln 2 = 0.693) | 0.752 (over-confident) | 0.696 |
| Rank IC (t-stat) | 0.013 (2.8) | **0.023 (4.2)** |
| Strategy Sharpe — old rule (top 10 %, no band) | 0.92 | — |
| Strategy Sharpe — v2 rule | 1.17 | **1.38** |
| Turnover per rebalance — v2 rule | 0.61 | 0.49 |

So of the Sharpe gain from 0.92 to 1.38, about 0.25 comes from the low-turnover portfolio rule and about 0.21 from the model.

### IC by test year
| | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 (to Oct) |
|---|---|---|---|---|---|---|---|---|
| v1 LightGBM | −0.022 | 0.022 | 0.008 | −0.005 | −0.016 | 0.034 | 0.057 | 0.033 |
| v2 ensemble | −0.006 | 0.059 | 0.019 | −0.026 | −0.012 | 0.029 | 0.053 | 0.076 |

## Reading the numbers
1. **The ranking signal roughly doubled** (IC 0.013 → 0.023, t 2.8 → 4.2) and the model stopped guessing the market
   direction: v1 said "up" for 99.9 % of 2024 and 15 % of 2019; v2's share of positive calls stays between 42 % and 62 %.
2. **It is still not a strategy.** The ensemble's Sharpe (1.38) only ties the benchmark (1.36); it earns a higher CAGR
   by taking more risk (vol 40 % vs 24 %, max drawdown −64 % vs −33 %). Large gain importance of `beta_63`, `vol_63`
   and the rate features shows a tilt towards high-beta stocks, which beat the median when the market rises.
3. **The plain 21-day momentum rule beats every model on strategy metrics** (Sharpe 1.55, max DD −38 %) although its IC is
   zero. Most likely survivorship bias: the universe is *today's* most liquid names, i.e. the winners of the last
   years, which flatters any rule that buys recent winners. Absolute CAGRs here are inflated for the same reason.
4. **The signal is unstable:** negative IC in 2019, 2022 and 2023. Three good years (2020, 2025, 2026) carry the average.
5. **Calibrated outputs are modest:** on the website P(up over 5 days) ranges 51.8 %–55.2 % and the expected 5-day
   return 0.1 %–0.8 % (isotonic maps fitted on these out-of-sample predictions, `meta.json → calibration`).

## Decision
Promotion rule (D-030), unchanged: IC t-stat ≥ 2 ✅ (4.2), AUC ≥ 0.52 ❌ (0.505 vs "up"; 0.515 even vs "beats median"),
strategy Sharpe > benchmark ✅ but only by 0.01 — within noise, and below the momentum baseline.
→ **Not promoted.** The "Demo predictions" badge stays. `python -m ml.serving.batch_predict` writes v2 rows as
`gbm-ens-cpu-32704ac5` with `is_demo = true` (bundle `ml/artifacts/short_gbm/`; v1 kept in `ml/artifacts/short_gbm_v1/`).

## Tried after v2: more data (not adopted)
Point-in-time SEC fundamentals (E/P, B/P, S/P, CF/P, ROE, gross margin, leverage, revenue growth, earnings change,
accruals) and industry-relative returns (SEC SIC codes → 9 groups) all **lowered** the dev IC (0.030 → 0.007–0.027),
so the model stays v2 and the test years were not touched. Details and why: [`ABLATION_DEV_V3.md`](ABLATION_DEV_V3.md).

## Next steps (to be chosen on dev folds again — the test years are now spent)
- **Point-in-time universe** (index membership by date) — removes the survivorship bias behind point 3 and makes
  benchmark and momentum numbers meaningful.
- **Beta-neutral label** (stock return − β × market) and volatility-scaled position sizes, to stop the high-beta tilt.
- Long-horizon (1–12 month) ranking models — the place for the fundamentals features, already built and tested.
- Quarterly instead of yearly refits; news-sentiment features once the LLM part exists (postponed).

---

## v1 (2026-10-28, kept for reference)
Run `933141939e194420bf031c0c38fb14e3`, `ml/configs/short_gbm_v1.yaml`: 44 features, label `up_5`, LightGBM,
portfolio = top 10 % every 5 days without a band. Out of sample 2019–2026: AUC 0.516, IC 0.013 (t 2.84), hit rate
52.5 %, strategy Sharpe 0.92 vs 1.36, CAGR 26.8 % vs 35.3 %, max DD −51.6 %, turnover 1.31, log-loss 0.752. Top
features by gain were market-level (10y−2y, Fed funds, VIX, month), which let the model time the whole market instead of
ranking stocks. Not promoted (AUC < 0.52, Sharpe below benchmark).
