# Backtest report — CPU baseline (short-term, 5 days)

Run `933141939e194420bf031c0c38fb14e3` in MLflow (`mlruns/mlflow.db`, experiment `short_term_gbm`), produced by
`python -m ml.train --config ml/configs/short_gbm.yaml` on 2026-10-28, CPU only (≈ 12 min).
Educational project — **not investment advice**; these numbers are a research baseline, not a trading result.

## Setup
| Item | Value |
|---|---|
| Universe | 102 US stocks: today's 100 most liquid operating companies (Alpaca + SEC, D-028) + KSPI, FRHC |
| Data | daily bars 2010-01-04 → 2026-10-27 (Alpaca SIP from 2016, Yahoo before), SPY / ^VIX, FRED macro with publication dates |
| Features | 44 from `ml/features` (returns, trend, oscillators, volatility, liquidity, beta/idio-vol, market, macro as-of, cross-sectional ranks, calendar) |
| Target | `up_5` = 5-day forward log return > 0 (close to close) |
| Validation | expanding walk-forward, **8 yearly test folds 2019 → 2026**; purge = 5 trading days (horizon) + embargo 5 days before each test year |
| Models | persistence ("tomorrow = today"), 21-day momentum, logistic regression (10 features), LightGBM (400 trees), XGBoost (400 trees) |
| Strategy | every 5 days buy the top 10 % by score, equal weight, hold 5 days; **10 bps per side** on two-sided turnover; benchmark = equal-weight universe |
| Out-of-sample rows | 172 516 |

## Results (all folds pooled, out of sample)
| Model | AUC | IC (mean daily rank) | IC t-stat | Hit rate | Strategy Sharpe | Benchmark Sharpe | Strategy max DD | 2-sided turnover / rebalance |
|---|---|---|---|---|---|---|---|---|
| baseline_persistence | 0.497 | −0.007 | −1.34 | 50.4 % | 0.85 | 1.36 | −63.5 % | 1.70 |
| baseline_momentum | 0.499 | −0.002 | −0.35 | 51.0 % | 1.41 | 1.36 | −40.8 % | 0.86 |
| logreg | 0.509 | −0.018 | −3.71 | 54.5 % | 0.64 | 1.36 | −38.5 % | 1.28 |
| **lightgbm** | **0.516** | **0.013** | **2.84** | 52.5 % | 0.92 | 1.36 | −51.6 % | 1.31 |
| xgboost | 0.514 | 0.013 | 2.63 | 52.4 % | 1.13 | 1.36 | −34.7 % | 1.30 |

LightGBM details: CAGR 26.8 % vs benchmark 35.3 %, volatility 31 % vs 24 %, Sortino 1.27 vs 1.79, log-loss 0.752 (> ln 2 = 0.693 → probabilities are over-confident and need calibration).

## Reading the numbers
1. **The tree models find a small, statistically significant ranking signal** (IC ≈ 0.013, t ≈ 2.7–2.8) that the naive baselines do not have. That is a typical size for daily US large caps.
2. **It does not survive as a strategy:** after costs the top-decile portfolio has a *lower* Sharpe and a deeper drawdown than simply holding the whole universe. Turnover (≈ 130 % two-sided every 5 days) eats the edge.
3. **The most important features are market-level** (10y−2y slope, Fed funds, VIX, market returns, month). They are the same for every stock on a day, so they help the model time the overall up/down rate (AUC) rather than rank stocks (IC). Next step: train on **cross-sectionally demeaned targets** (excess return vs the universe) and keep macro only as interactions.
4. **The benchmark is inflated by survivorship bias:** the universe is today's most liquid names, i.e. yesterday's winners (benchmark CAGR 35 %). Absolute returns here are not meaningful; only model-vs-benchmark comparisons are.
5. Logistic regression has the best hit rate (54.5 %) but a *negative* IC: it mostly learned "stocks go up" — hit rate alone is a misleading metric.

## Decision
Promotion rule (D-030): IC t-stat ≥ 2 ✅, AUC ≥ 0.52 ❌ (0.516), strategy Sharpe > benchmark ❌. → **Not promoted.**
The model is still exported (`ml/artifacts/short_gbm/`) and its 5-day predictions are written to the website by
`python -m ml.serving.batch_predict`, labelled `lgbm-cpu-93314193` with `is_demo = true`, so the "Demo predictions"
badge stays on.

## Next steps (GPU phase, see GPU_PLAN §4)
- Excess-return targets, isotonic calibration, monthly instead of yearly refits.
- Point-in-time universe (removes survivorship bias), fundamentals and news-sentiment features.
- Lower-turnover portfolio rules (hysteresis bands, longer holding) and next-open execution.
