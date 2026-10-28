# ml/ — model training (GPU phase)

Empty skeleton for now. Plan: [`docs/GPU_PLAN.md`](../docs/GPU_PLAN.md) §3–§8.

Planned layout:

```
ml/
├── features/       # ONE shared feature module for training and inference (technical, market, macro, news, fundamentals)
├── datasets/       # point-in-time panel builder, walk-forward splits with purging + embargo
├── models/         # gbm_short (LightGBM/XGBoost), rank_long (LambdaRank/XGB rank), stacking
├── llm/            # FinBERT/multilingual baselines, QLoRA fine-tuning, vLLM batch sentiment, reviewer prompts
├── backtest/       # strategy simulation with fees + slippage, metrics (IC, Sharpe, Sortino, MDD, turnover)
├── configs/        # YAML configs (python -m ml.train --config configs/short_gbm.yaml [--dry-run])
└── serving/        # MLflowPredictionProvider used by backend/app/ml_interface (PREDICTION_PROVIDER=mlflow)
```

Experiments are tracked in MLflow; the website loads the model registered with alias `production`.
