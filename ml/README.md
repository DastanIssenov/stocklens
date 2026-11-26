# ml/ — model training (CPU now, GPU phase later)

Plan: [`docs/GPU_PLAN.md`](../docs/GPU_PLAN.md) §3–§8. Results: [`docs/BACKTEST_REPORT.md`](../docs/BACKTEST_REPORT.md),
dev-fold choices: [`docs/ABLATION_DEV.md`](../docs/ABLATION_DEV.md).

```
ml/
├── features/       # ONE feature module for training and inference: compute_features(), add_targets(), FEATURE_GROUPS;
│                   #   fundamentals.py = point-in-time SEC TTM values and industry groups
├── datasets/       # walk-forward splits with purging + embargo (never random)
├── models/         # baselines, logistic regression, LightGBM, XGBoost behind fit(X, y) / score(X)
├── backtest/       # IC, AUC, accuracy / precision / recall, long top-quantile strategy with costs, hold band, score EMA
├── experiments/    # ablation.py (v1 → v2), ablation_v3.py (new data) — choices are made on dev folds 2016–2018
├── configs/        # short_gbm.yaml (v2, current), short_gbm_v1.yaml (baseline, ablation base)
├── serving/        # batch_predict.py — scores the latest day and writes rows to the website's predictions table
└── artifacts/      # exported bundles (not in git): short_gbm/ (v2), short_gbm_v1/
```

```bash
uv run python -m ml.experiments.ablation                       # dev folds only → docs/ABLATION_DEV.md (~4 min)
uv run python -m ml.experiments.ablation_v3                    # fundamentals / industry on dev folds (~2 min)
uv run python -m ml.train --config ml/configs/short_gbm.yaml   # test folds 2019–2026, MLflow, export (~2.5 min)
uv run python -m ml.train --config ml/configs/short_gbm.yaml --dry-run   # synthetic data, < 30 s
uv run python -m ml.serving.batch_predict --database-url postgresql://stock:stock@localhost:55433/stock
uv run pytest ml                                               # incl. the no-look-ahead test
```

Rule: the 2019–2026 test folds are for the final number only. Any new idea is tried on the dev folds first.
