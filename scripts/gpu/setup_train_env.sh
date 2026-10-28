#!/usr/bin/env bash
# Training environment for the RTX 5090 box (docs/GPU_PLAN.md §1.3). Ubuntu 24.04, driver >= 580.
# Versions checked on PyPI on 2026-10-28. vLLM runs in its own env/container (see setup_vllm.sh).
set -euo pipefail

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
cd "$(dirname "$0")/../.."
uv venv --python 3.12 .venv-gpu
source .venv-gpu/bin/activate

# torch 2.13.0 from PyPI = CUDA 13.0 build (has sm_120 kernels). Same torch as vLLM 0.32.0 pins.
uv pip install "torch==2.13.0" "torchvision==0.28.0"

uv pip install \
  "transformers==5.19.0" "peft==0.21.2" "trl==1.16.0" "accelerate==1.15.0" "datasets==5.1.0" \
  "bitsandbytes==0.50.2" "sentence-transformers==6.2.0" \
  "xgboost==3.4.1" "scikit-learn==1.9.1" "optuna==5.0.0" "mlflow==3.17.2" \
  "polars==2.1.0" "pandas" "pyarrow" "numpy" "pyyaml" "httpx" "feedparser" "yfinance==1.7.0"

# LightGBM with CUDA (optional; CPU LightGBM is the fallback and is already fast for ~2M rows)
if command -v nvcc >/dev/null; then
  CMAKE_CUDA_ARCHITECTURES=120 uv pip install "lightgbm==4.7.0" --no-binary lightgbm \
    --config-settings=cmake.define.USE_CUDA=ON || uv pip install "lightgbm==4.7.0"
else
  uv pip install "lightgbm==4.7.0"
fi

# flash-attn is OPTIONAL: transformers uses PyTorch SDPA by default. Only sdist is published, the build
# takes 30-60 min: MAX_JOBS=8 TORCH_CUDA_ARCH_LIST="12.0" uv pip install flash-attn==2.8.3.post2 --no-build-isolation

python scripts/gpu/verify_env.py --skip-vllm
