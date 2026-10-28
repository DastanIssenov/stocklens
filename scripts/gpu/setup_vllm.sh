#!/usr/bin/env bash
# vLLM serving (OpenAI-compatible API) for the trade reviewer and batch sentiment (docs/GPU_PLAN.md §1.5).
# Option A (recommended): official container. Option B: pip in a separate venv (vllm pins torch==2.13.0).
set -euo pipefail
MODEL="${MODEL:-Qwen/Qwen3-8B}"
PORT="${PORT:-8001}"
: "${VLLM_API_KEY:?set VLLM_API_KEY (it becomes LLM_API_KEY in the website .env)}"

if [[ "${1:-docker}" == "docker" ]]; then
  docker run --gpus all --ipc=host -p "${PORT}:8000" \
    -v "${HOME}/.cache/huggingface:/root/.cache/huggingface" \
    -e HF_TOKEN="${HF_TOKEN:-}" \
    vllm/vllm-openai:v0.32.0 \
    --model "${MODEL}" --api-key "${VLLM_API_KEY}" \
    --dtype bfloat16 --max-model-len 8192 --gpu-memory-utilization "${GPU_UTIL:-0.55}" \
    --enable-prefix-caching
else
  uv venv --python 3.12 .venv-vllm && source .venv-vllm/bin/activate
  uv pip install "vllm==0.32.0"
  vllm serve "${MODEL}" --port "${PORT}" --api-key "${VLLM_API_KEY}" \
    --dtype bfloat16 --max-model-len 8192 --gpu-memory-utilization "${GPU_UTIL:-0.55}" --enable-prefix-caching
fi
