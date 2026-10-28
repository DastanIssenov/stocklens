#!/usr/bin/env python3
"""GPU environment smoke test for the RTX 5090 box (docs/GPU_PLAN.md §1.4).

Usage:  python scripts/gpu/verify_env.py [--skip-bnb] [--skip-gbm] [--skip-vllm]
Exit code 0 only if every enabled check passes. Safe to re-run; downloads nothing.
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
import time

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):  # type: ignore[no-untyped-def]
    def deco(fn):  # type: ignore[no-untyped-def]
        def run() -> None:
            t0 = time.perf_counter()
            try:
                detail = fn() or ""
                RESULTS.append((name, True, f"{detail} ({time.perf_counter() - t0:.1f}s)"))
            except Exception as e:  # noqa: BLE001 - report every failure
                RESULTS.append((name, False, f"{type(e).__name__}: {e}"))

        return run

    return deco


@check("nvidia-smi")
def nvidia_smi() -> str:
    if not shutil.which("nvidia-smi"):
        raise RuntimeError("nvidia-smi not found — install the NVIDIA driver (>= 580 for CUDA 13)")
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if "5090" not in out and "12.0" not in out:
        print(f"  note: expected an RTX 5090 / compute capability 12.0, got: {out}")
    return out


@check("torch + CUDA")
def torch_cuda() -> str:
    import torch

    assert torch.cuda.is_available(), "torch.cuda.is_available() is False"
    cap = torch.cuda.get_device_capability(0)
    archs = torch.cuda.get_arch_list()
    assert f"sm_{cap[0]}{cap[1]}" in archs or any(a.startswith("sm_12") for a in archs), (
        f"this torch build has no kernels for sm_{cap[0]}{cap[1]} (arch list {archs}) — install a CUDA ≥ 12.8 wheel"
    )
    return f"torch {torch.__version__}, CUDA {torch.version.cuda}, {torch.cuda.get_device_name(0)}, cap {cap}"


@check("bf16 matmul")
def bf16_matmul() -> str:
    import torch

    a = torch.randn(8192, 8192, device="cuda", dtype=torch.bfloat16)
    b = torch.randn(8192, 8192, device="cuda", dtype=torch.bfloat16)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    n = 20
    for _ in range(n):
        c = a @ b
    torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    tflops = 2 * 8192**3 * n / dt / 1e12
    ref = (a[:256].float() @ b[:, :256].float())
    err = (c[:256, :256].float() - ref).abs().max().item()
    assert err < 2.0, f"bf16 result looks wrong (max abs err {err})"
    return f"{tflops:.0f} TFLOP/s bf16 (expect roughly 150-220 on a 5090)"


@check("SDPA attention")
def sdpa() -> str:
    import torch
    import torch.nn.functional as F

    q = torch.randn(4, 32, 2048, 128, device="cuda", dtype=torch.bfloat16)
    out = F.scaled_dot_product_attention(q, q, q, is_causal=True)
    assert torch.isfinite(out).all()
    return "ok"


@check("bitsandbytes 4-bit")
def bnb() -> str:
    import bitsandbytes as bnb_mod
    import torch

    lin = bnb_mod.nn.Linear4bit(4096, 4096, bias=False, compute_dtype=torch.bfloat16, quant_type="nf4").cuda()
    x = torch.randn(16, 4096, device="cuda", dtype=torch.bfloat16)
    y = lin(x)
    assert torch.isfinite(y).all()
    return f"bitsandbytes {bnb_mod.__version__} NF4 forward ok"


@check("transformers / peft / trl import")
def hf_stack() -> str:
    vers = []
    for m in ("transformers", "peft", "trl", "accelerate", "datasets"):
        vers.append(f"{m} {importlib.import_module(m).__version__}")
    return ", ".join(vers)


@check("XGBoost on GPU")
def xgb_gpu() -> str:
    import numpy as np
    import xgboost as xgb

    rng = np.random.default_rng(0)
    X = rng.normal(size=(200_000, 50)).astype("float32")
    y = (X[:, 0] + 0.1 * rng.normal(size=200_000) > 0).astype("float32")
    m = xgb.XGBClassifier(n_estimators=50, tree_method="hist", device="cuda", max_depth=6)
    m.fit(X, y)
    acc = float((m.predict(X) == y).mean())
    assert acc > 0.9
    return f"xgboost {xgb.__version__} acc={acc:.3f}"


@check("LightGBM (CUDA if built, else CPU)")
def lgb_check() -> str:
    import lightgbm as lgb
    import numpy as np

    rng = np.random.default_rng(0)
    X = rng.normal(size=(100_000, 30))
    y = (X[:, 0] > 0).astype(int)
    for device in ("cuda", "cpu"):
        try:
            m = lgb.LGBMClassifier(n_estimators=50, device_type=device, verbose=-1).fit(X, y)
            return f"lightgbm {lgb.__version__} device={device} acc={(m.predict(X) == y).mean():.3f}"
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"LightGBM failed on cuda and cpu: {last}")


@check("vLLM import")
def vllm_import() -> str:
    import vllm

    return f"vllm {vllm.__version__} (run the server smoke test in GPU_PLAN §1.5 separately)"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-bnb", action="store_true")
    p.add_argument("--skip-gbm", action="store_true")
    p.add_argument("--skip-vllm", action="store_true", help="vLLM lives in its own env/container")
    a = p.parse_args()
    checks = [nvidia_smi, torch_cuda, bf16_matmul, sdpa, hf_stack]
    if not a.skip_bnb:
        checks.append(bnb)
    if not a.skip_gbm:
        checks += [xgb_gpu, lgb_check]
    if not a.skip_vllm:
        checks.append(vllm_import)
    for c in checks:
        c()
    ok = all(r[1] for r in RESULTS)
    for name, passed, detail in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — see GPU_PLAN.md §1.6 (known problems)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
