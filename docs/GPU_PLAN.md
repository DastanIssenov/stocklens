# GPU plan — RTX 5090 (32 GB, Blackwell)

A step-by-step plan for the day the GPU arrives. Everything here was checked on **2026-10-28** against PyPI,
Hugging Face, Docker Hub, GitHub issues and price trackers (sources at the end). Re-check versions on day 1 —
this stack moves fast. Educational project: models must never be presented as investment advice.

**Contents**
1. [Environment](#1-environment) · 2. [Data pipeline](#2-data-pipeline) · 3. [Features](#3-features) ·
4. [Models](#4-models) · 5. [VRAM and time budget](#5-vram-and-time-budget-rtx-5090-32-gb) ·
6. [Backtest and metrics](#6-backtest-and-metrics) · 7. [MLflow](#7-mlflow) · 8. [Integration with the website](#8-integration-with-the-website) ·
9. [Order of work, checklist, risks](#9-order-of-work-and-checklist) · 10. [Cloud fallback](#10-cloud-fallback)

---

## 1. Environment

### 1.1 Facts that drive the choices
| Fact (verified 2026-10-28) | Consequence |
|---|---|
| RTX 5090 = Blackwell **compute capability 12.0 (`sm_120`)**; kernels need CUDA ≥ 12.8. | Only CUDA 12.8+ builds of every GPU library work. `cu126` wheels do **not**. |
| `torch 2.13.0` / `2.14.1` default PyPI wheels are **CUDA 13.0** builds (`nvidia-*-cu13` deps); `cu129`/`cu130` index variants also exist for 2.13.0. | Use the default PyPI wheel. CUDA 13 needs **NVIDIA driver ≥ 580** (open kernel modules — mandatory on Blackwell). |
| `vllm 0.32.0` (2026-10-18) pins `torch==2.13.0`, `transformers>=5.16.1,<5.20`, `flashinfer-python==0.7.0.post1`. | Pin **torch 2.13.0 and transformers 5.19.0 everywhere**, keep vLLM in its **own** venv/container anyway. |
| vLLM issue #35432 ("prebuilt wheels fail on RTX 50-series") was **closed on 2026-05-15** (PR #35568, CUDA 13 builds). | Prebuilt `vllm==0.32.0` / `vllm/vllm-openai:v0.32.0` (9.2 GB image) should work. Fallback: build from source. |
| Native **NVFP4** kernels on `sm_120` are still incomplete in vLLM (issues #31085, #47749: falls back to Marlin W4A16; crashes for some models). FP8 under WSL2 is slow. | Serve **bf16** (8B fits) or **AWQ int4**. Run **native Linux**, not WSL2. |
| `flash-attn 2.8.3.post2` is published only as an sdist; `sm_120` works when compiled with `TORCH_CUDA_ARCH_LIST=12.0`. FlashAttention-4 does **not** run on `sm_120`. | Use PyTorch **SDPA** (default in transformers) for training; flash-attn is optional. vLLM brings its own attention backends. |
| `bitsandbytes 0.50.2` (2026-08-27) ships CUDA 13 builds; release notes mention GB10 (`sm_121`) 4-bit work. | QLoRA should work; verify with the smoke test. Fallback: **bf16 LoRA** (an 8B model fits in 32 GB). |
| `xgboost 3.4.1` manylinux wheels include CUDA; LightGBM GPU needs a source build (`USE_CUDA=ON`). | XGBoost on GPU; LightGBM CUDA optional (CPU LightGBM is fast enough for ≈2 M rows). |

### 1.2 Machine setup (day 1, ≈2 h)
1. **OS:** Ubuntu 24.04 LTS (kernel ≥ 6.8), BIOS: Resizable BAR on, PSU ≥ 1000 W (5090 TGP 575 W), 2 TB NVMe for data.
2. **Driver:** `sudo ubuntu-drivers install nvidia-driver-580-open` (or newer `-open` branch). Reboot. `nvidia-smi` must show the 5090 and driver ≥ 580.
3. **CUDA toolkit 13.0** only if building from source (LightGBM CUDA, flash-attn, vLLM fallback): install from NVIDIA's apt repo, `export PATH=/usr/local/cuda/bin:$PATH`.
4. **Docker + NVIDIA Container Toolkit:** `nvidia-ctk runtime configure --runtime=docker`; test `docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi`.
5. **Repo + secrets:** clone, copy `.env`, add `HF_TOKEN` (gated models: Sherkala, KazLLM, Llama) and `VLLM_API_KEY`.

### 1.3 Python environments (exact versions)
Two environments so vLLM's strict pins never break training code:

| Env | Created by | Key pins |
|---|---|---|
| `.venv-gpu` (training, features, GBMs, LoRA) | [`scripts/gpu/setup_train_env.sh`](../scripts/gpu/setup_train_env.sh) | Python 3.12 · torch 2.13.0 (CUDA 13.0) · torchvision 0.28.0 · transformers 5.19.0 · peft 0.21.2 · trl 1.16.0 · accelerate 1.15.0 · datasets 5.1.0 · bitsandbytes 0.50.2 · sentence-transformers 6.2.0 · xgboost 3.4.1 · lightgbm 4.7.0 · scikit-learn 1.9.1 · optuna 5.0.0 · mlflow 3.17.2 · polars 2.1.0 |
| vLLM server | [`scripts/gpu/setup_vllm.sh`](../scripts/gpu/setup_vllm.sh) | `vllm/vllm-openai:v0.32.0` container (preferred) or `vllm==0.32.0` in `.venv-vllm` |
| Optional | — | `flash-attn==2.8.3.post2` (source build, 30–60 min), `unsloth==2026.10.9` (faster LoRA, but one extra pins `torch==2.10.0` → separate venv only) |

### 1.4 Verification script
`python scripts/gpu/verify_env.py` ([source](../scripts/gpu/verify_env.py)) checks, and fails loudly:
`nvidia-smi` (name, driver, VRAM, compute cap) → `torch.cuda.is_available()` and that the torch build contains `sm_120` kernels →
**8192² bf16 matmul** (prints TFLOP/s, checks the numbers) → SDPA causal attention → bitsandbytes NF4 `Linear4bit` forward →
transformers/peft/trl/accelerate/datasets imports → XGBoost `device="cuda"` → LightGBM (`cuda`, falls back to `cpu`) → vLLM import.
**Done when:** `ALL CHECKS PASSED`.

### 1.5 vLLM smoke test
```bash
VLLM_API_KEY=... MODEL=Qwen/Qwen3-8B GPU_UTIL=0.55 scripts/gpu/setup_vllm.sh docker
curl -s localhost:8001/v1/chat/completions -H "Authorization: Bearer $VLLM_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3-8B","messages":[{"role":"user","content":"Reply with JSON {\"ok\":true}"}],"response_format":{"type":"json_object"}}'
```
**Done when:** valid JSON comes back and `nvidia-smi` shows ≈ 18–19 GB used.

### 1.6 Known problems and workarounds
| Symptom | Cause | Workaround |
|---|---|---|
| `no kernel image is available for execution on the device` | a wheel built without `sm_120` | use the CUDA 13 wheels above; for anything else rebuild with `TORCH_CUDA_ARCH_LIST="12.0"` / `CMAKE_CUDA_ARCHITECTURES=120` |
| vLLM crashes with an NVFP4 / FP8 checkpoint | incomplete `sm_120` FP4/FP8 kernels | use bf16 or AWQ checkpoints |
| `CUDA driver version is insufficient` | driver < 580 with CUDA 13 wheels | upgrade driver (or use `torch==2.13.0+cu129` from the PyTorch cu129 index with driver ≥ 575) |
| bitsandbytes import/4-bit error | missing `sm_120` build | `pip install bitsandbytes` from the latest release / source build with `-DCOMPUTE_CAPABILITY=120`; fallback bf16 LoRA |
| flash-attn build OOM | too many parallel nvcc jobs | `MAX_JOBS=4`; or just use SDPA |
| LightGBM CUDA build fails | toolkit/compiler mismatch | use CPU LightGBM (`n_jobs=-1`) |

---

## 2. Data pipeline

Code goes to `data_pipeline/` (skeleton exists) and reuses the connectors already in `backend/app/services/sources/`.
Storage: **Parquet lake** (`data/raw/<source>/…`, `data/processed/…`, partitioned by year) as the source of truth for
training, plus **Postgres/Timescale** for what the website serves. All timestamps UTC; every row has `available_at`.

### 2.1 Connectors, in build order
| # | Connector | Why this order | Historical load | Daily update |
|---|---|---|---|---|
| 1 | **Trading calendar** (`exchange_calendars`: XNYS, XLON; KASE calendar from KASE holiday notices + observed bar dates) | everything aligns to it | 2005 → 2027 | yearly |
| 2 | **Universe / membership** (point-in-time NASDAQ-100 & S&P 500 from Wikipedia change tables, cross-checked with `fja05680/sp500`; KASE Index list history from KASE news) | survivorship-bias control | 2014 → now | monthly |
| 3 | **US prices — Alpaca SIP** (`adjustment=raw` **and** `all`, plus `GET data.alpaca.markets/v1/corporate-actions` — verified: splits and cash dividends) | core target data | 2016-01-04 → now, ≈ 800 symbols incl. delisted | 18:00 ET |
| 4 | **US prices pre-2016 — yfinance** | ≥ 10 y history | 2010 → 2015 | — |
| 5 | **KASE — Tradernet `getHloc`** | KZ targets | as deep as available (2007–2024 by ticker) | 13:00 UTC (after KASE close 17:00 Almaty) |
| 6 | **LSE GDRs, FX, Brent, indices — yfinance** (`KAP.IL HSBK.IL AIRA.IL KZT=X BZ=F ^GSPC ^NDX ^VIX`) | KZ features | 2006 → now | daily |
| 7 | **NBK official USD/KZT** (`get_rates.cfm?fdate=…`, 1 req/s) | official FX | 2010 → now (≈ 4 000 requests, ≈ 70 min) | daily |
| 8 | **FRED / ALFRED** (DFF, DGS2, DGS10, T10Y2Y, CPIAUCSL, UNRATE, VIXCLS, DCOILBRENTEU, DTWEXBGS, BAMLH0A0HYM2) with vintages | macro | 1990 → now | daily |
| 9 | **SEC EDGAR** `submissions` + `companyfacts` (or the nightly `companyfacts.zip` bulk file) | fundamentals, point in time | all filings 2009 → now | nightly, ≤ 10 req/s |
| 10 | **News — Alpaca (Benzinga)** | ticker-tagged EN news | 2015 → now | every 30 min |
| 11 | **News — Finnhub** company news (last 12 months only on free plan), RSS, GDELT DOC/TimelineVol | coverage + attention | ≤ 1 y | every 30 min |
| 12 | **KZ news** — RSS (Kursiv, Kapital, Inbusiness ru/kk, Tengrinews ru/kk, LSM) + historical articles via the outlets' sitemaps (robots.txt allows; ≤ 1 req/s); Forbes.kz news sitemap; KASE issuer news / dfo.kz disclosures | RU/KK sentiment | 2018 → now (business sections) | every 30 min |

### 2.2 Size and time estimates
| Dataset | Rows / items | Disk (Parquet, zstd) | Download time |
|---|---|---|---|
| US daily bars, 800 symbols × 2016→ (SIP, raw + adjusted) | ≈ 2.2 M × 2 | ≈ 250 MB | ≈ 450 requests → **< 5 min** (200 req/min) |
| US daily bars pre-2016 (yfinance) | ≈ 1.2 M | ≈ 80 MB | ≈ 800 requests, 1 req/s → **15 min** |
| KASE bars (14 shares) + GDRs + FX + Brent + indices | ≈ 70 k | < 10 MB | **< 2 min** (Tradernet: one batched request) |
| NBK official rates 2010→ | ≈ 4 000 days | < 1 MB | **≈ 70 min** at 1 req/s |
| FRED/ALFRED, 10 series with vintages | ≈ 300 k | ≈ 10 MB | **< 5 min** |
| SEC companyfacts, 800 companies | ≈ 2.4 GB raw JSON → ≈ 3 M selected facts | ≈ 150 MB processed | **≈ 3 min** at 5 req/s (or one 1–2 GB bulk zip) |
| Alpaca news 2015→ (headline + summary; full `content` only for last 2 y) | ≈ 3–5 M | ≈ 2 GB (+ ≈ 4 GB content) | ≈ 80 k requests (50/page) → **≈ 7 h** at 200 req/min — run overnight, resumable by date cursor |
| KZ historical articles (≈ 50 k, business sections, 2018→) | ≈ 50 k | ≈ 1 GB HTML → 200 MB text | **≈ 14 h** at 1 req/s — background over 2 nights |
| Embeddings (bge-m3, `halfvec(1024)`) for last 2 y + all KZ | ≈ 1 M | ≈ 2 GB in pgvector | ≈ 30 min on the 5090 |
| **Total** | | **≈ 10–12 GB** (+ 20 GB headroom for model weights, MLflow artifacts) | **≈ 1.5 days wall clock, < 2 h of attention** |

### 2.3 Cleaning rules
- **Splits/dividends:** keep raw OHLCV + Alpaca corporate actions; compute our own adjustment factors so they can be checked. Returns/targets use **fully adjusted** prices; **price-level** features (e.g. "price < $5", 52-week high) use **raw** prices as of that day (future splits must not change past levels).
- **Cross-check:** Alpaca vs yfinance adjusted close; |diff| > 0.5 % on > 1 % of days → flag the ticker in `DATA_REPORT.md`.
- **Gaps:** reindex to the exchange calendar. Missing US day → refetch once, then mark `is_missing` (never forward-fill targets). KASE no-trade days → keep **NaN price + volume 0**, add `days_since_last_trade`; forward-fill only for *feature* computation with an explicit flag.
- **Bad ticks:** drop bars with high < low, close outside [low, high], or |log return| > 50 % without a corporate action (logged, not silently fixed).
- **KZ illiquidity:** per ticker and month compute share of zero-volume days, Amihud illiquidity, median turnover (₸). Exclude from training any ticker-month with > 50 % no-trade days; `is_liquid` in `tickers` is refreshed monthly from this.
- **Currency:** store native currency; convert to USD with the official NBK rate of the same day only for cross-market features.
- **Delistings:** keep delisted tickers to the last trading day; delisting return = −100 % if bankrupt else last price (documented per case).

### 2.4 News → ticker linking (EN / RU / KK)
1. **Vendor tags** (Alpaca/Finnhub symbols) → confidence 1.0.
2. **Alias dictionary** (`ticker_aliases`, already in the DB): legal names, brands, Russian and Kazakh spellings and inflections — e.g. Kaspi / Каспи / Kaspi.kz; Halyk / Халык / Народный банк / Халық банк; Kazatomprom / Казатомпром / Қазатомөнеркәсіп; KazMunayGas / КазМунайГаз / ҚазМұнайГаз. Add **lemmatised** matching (pymorphy3 for RU; simple suffix stripping for KK) → confidence 0.8.
3. **NER + entity linking** for the rest: multilingual NER (e.g. `Davlan/xlm-roberta-base-ner-hrl` or an LLM extraction prompt in the sentiment pass) → match ORG mentions to aliases with fuzzy matching (rapidfuzz ≥ 90) → confidence 0.6.
4. **Issuer level:** link to the issuer; every listing of that issuer (KSPI.KZ, KSPI) inherits the link.
5. **Language ID:** `lingua` / fastText `lid.176` (replaces the current Kazakh-letter heuristic, D-027).
6. **Quality check:** hand-label 300 random links (100 per language); target precision ≥ 0.9.

### 2.5 Look-ahead-bias rules (enforced in code, tested)
Prediction for trading day *t* is made **after the close of t** for the next horizons; the **cut-off** is the official close
(US 16:00 America/New_York; KASE 17:00 Asia/Almaty; LSE 16:30 Europe/London).
1. **Prices:** features use bars dated ≤ *t*. Today's provisional KASE bar (D-022) is used only after 17:00 Almaty.
2. **News:** `available_at = published_at`. Items published after the cut-off of *t* (or on a non-trading day) belong to the **next trading day**. News is never matched by "date" alone — always by timestamp vs cut-off.
3. **Fundamentals:** `available_at = SEC acceptanceDateTime`; accepted after 16:00 ET → next trading day. Never use `period_end`. Restated values only from their own filing date.
4. **Macro:** revised series (CPI, unemployment) from **ALFRED vintages** (`realtime_start ≤ t`). Daily market series (VIX, yields) available at their close. FRED Brent arrives ≈ 1 week late → use `available_at` = observation date + publication lag, or yfinance `BZ=F` close.
5. **FX:** NBK official rate for date *d* is set on *d−1* evening → available for *d*. Market `KZT=X` at its close.
6. **Universe:** a stock enters the training panel on *t* only if it was an index member on *t*.
7. **Normalisation / scaling / target encoding** are fitted **inside** each training fold only.
8. **Automated test:** `tests/test_no_lookahead.py` — shift every source's `available_at` by +1 day and assert that features dated *t* do not change; plus a "future-shuffle" test: permuting data after *t* must not change features at *t*.

---

## 3. Features

All features come from **one module, `ml/features/`**, used by both training (`build_panel(start, end)`) and inference
(`build_features(as_of=t)`). Inference calls the same function with `end=t`; a test asserts identical values for the
same `(ticker, t)`. Each feature has `name, family, horizon_safe, available_at rule`, registered in `ml/features/registry.py`.

| Family | Features (computed per ticker, day *t*) | Notes |
|---|---|---|
| **Returns** | log returns over 1, 2, 3, 5, 10, 21, 63, 126, 252 days; 12-1 momentum (252d ex last 21d); overnight (open/prev close) and intraday (close/open) return | adjusted prices |
| **Trend** | close / SMA(10, 20, 50, 200) − 1; EMA(12)−EMA(26) (MACD), MACD signal and histogram; distance to 52-week high/low (raw prices); ADX(14) | |
| **Oscillators** | RSI(2, 14); Stochastic %K/%D (14,3); Williams %R(14); CCI(20); Bollinger %B and bandwidth (20, 2σ) | |
| **Volatility** | realised vol 5/21/63 d (close-to-close); Parkinson and Garman–Klass vol (21 d); ATR(14)/close; vol-of-vol; downside semivariance | |
| **Volume / liquidity** | log volume z-score (21 d); dollar volume (USD); turnover; Amihud illiquidity (21 d); OBV slope; **days since last trade, share of no-trade days (63 d)** — key for KASE | |
| **Market / cross-section** | beta and idiosyncratic vol vs `^GSPC` (US) or KASE Index proxy (KZ, cap-weighted from our bars) over 63/252 d; sector-relative return (21 d); cross-sectional ranks of every return/vol feature; market breadth (% above SMA50) | ranks computed per day across the universe |
| **Macro** | VIX level and 5-d change; 2y and 10y yields, 10y−2y slope; Fed funds; CPI YoY (ALFRED); HY spread; broad USD index; **USD/KZT official** level, 5/21-d change, official − market gap; **Brent** 1/5/21-d return and 63-d vol | same value for all tickers on a day; interacts with sector in trees |
| **Kazakhstan-specific** | **lead–lag from foreign listings:** return of `KAP.IL` / `HSBK.IL` / `KSPI` (NASDAQ) after KASE close → next KASE session; premium/discount of KASE line vs foreign line in KZT; oil sensitivity (63-d beta to Brent) | London and NASDAQ trade after KASE closes — strongest known KZ signal; respect cut-offs |
| **News / sentiment** | count of linked articles (1, 5, 21 d) and z-score vs own history; mean and max LLM sentiment (1, 5, 21 d), decayed with half-life 2 d; share negative; novelty (1 − max cosine sim to previous 7 d embeddings); GDELT attention; KZ: separate RU/KK counts | `available_at` rule §2.5.2 |
| **Fundamentals (US, point-in-time)** | E/P, B/P, S/P, FCF yield; ROE, ROA, gross margin; revenue and EPS growth YoY; accruals; leverage (debt/equity); share issuance (12 m); **days since last filing**, earnings surprise proxy (EPS vs same quarter last year) | from `companyfacts` with `available_at`; KZ: from Kaspi/Halyk/Kazatomprom IFRS reports (manual table, few names) |
| **Calendar** | day of week, month, days to month end, days to/from earnings (from filing history), KZ holiday proximity | |
| **Labels (not features)** | short: `fwd_ret_{1,5}d` (log, adjusted), `up_{1,5}d` = sign; long: `fwd_ret_{21,63,126,252}d` and cross-sectional rank; KZ: also excess return vs KZ market | computed only from prices *after* t |

---

## 4. Models

### 4.1 Validation protocol (applies to all models)
- **Walk-forward, expanding window**, monthly refit for short-term (quarterly for long-term). Test folds 2019-01 → 2026-09.
- **Purging:** drop training samples whose label window `(t, t+h]` overlaps the test period. **Embargo:** additionally drop `h` trading days after each test fold (5 d short, 21–63 d long).
- Hyper-parameters tuned with Optuna **only on 2016–2018 inner folds**, then frozen; final numbers reported on 2019–2026 folds only.
- Never a random split (TASK §6).

### 4.2 Short-term (1–5 trading days)
| Item | Plan |
|---|---|
| Targets | regression: `fwd_ret_1d`, `fwd_ret_5d` (winsorised at 1/99 %); classification: `up_1d`, `up_5d` |
| Baselines | (1) "tomorrow = today" (persistence of last return sign) and zero-return; (2) 20-day momentum sign; (3) logistic regression on 10 standardised features; (4) ridge regression |
| Models | **LightGBM** (`objective=regression_l1/binary`, `num_leaves 31–127`, `learning_rate 0.02–0.05`, `feature_fraction 0.7`, `bagging 0.8`, early stopping on the last 10 % of the training window) and **XGBoost** (`tree_method=hist`, `device=cuda`, `max_depth 4–8`, `eta 0.03`) |
| Sample weights | down-weight overlapping 5-d labels (uniqueness weights, López de Prado); KZ illiquid days weight 0.5 |
| Output | `predicted_return`, `prob_up` (classifier, isotonic-calibrated on the last fold), `confidence` = 2·|prob_up − 0.5| shrunk by the fold's AUC, `top_features` = TreeSHAP top-5 |

### 4.3 Long-term (1–12 months)
- **Task:** cross-sectional ranking — every month-end, rank stocks by future 21/63/126/252-day return.
- **Models:** LightGBM `objective=lambdarank` (groups = month-end dates, relevance = return quintile 0–4) and XGBoost `rank:ndcg`; baseline: 12-1 momentum rank and equal-weight.
- **Portfolio rule for evaluation:** monthly rebalancing, long top quintile (and long-short top − bottom as a research metric), 10 bps cost per side, max 10 % per name.
- KZ: universe too small for ranking (14 names) → per-stock 63/126-day regression with heavy shrinkage + ranking inside a pooled US+KZ model with a market flag (§4.6).

### 4.4 LLM part
**Jobs:** (a) ticker-level sentiment of each news item (EN/RU/KK), (b) weekly summary per ticker, (c) the trade reviewer (already wired, §8).

**Baselines (cheap, run first):**
- `ProsusAI/finbert` (EN financial sentiment; CC BY-NC-SA 4.0 — fine for an educational project) for EN headlines.
- `cardiffnlp/twitter-xlm-roberta-base-sentiment` (multilingual, incl. RU) zero-shot; `issai/kazsandra`-fine-tuned XLM-R for Kazakh (KazSAnDRA is CC BY 4.0, gated).
- Embedding + logistic regression on `BAAI/bge-m3` (MIT) vectors trained on the gold set.

**Main model — candidates (7–9 B, verified on Hugging Face 2026-10-28):**
| Model | Params | Licence | RU | KK | Notes |
|---|---|---|---|---|---|
| **`Qwen/Qwen3-8B`** | 8.2 B dense | Apache-2.0 | strong | weak–medium | standard architecture → best tooling (bitsandbytes, PEFT, vLLM); thinking/non-thinking modes. **Default choice.** |
| `Qwen/Qwen3.5-9B` | 9.65 B (incl. vision encoder) | Apache-2.0 | strong | medium (201 languages) | newer hybrid linear-attention architecture (`qwen3_5`); check QLoRA + vLLM support on day 3 before choosing it |
| `inception42/Llama-3.1-Sherkala-8B-Chat` | 8.0 B | CC BY-NC-SA 4.0, gated | good | **best open Kazakh** (trained on KK/EN/RU/TR) | candidate if KK quality decides |
| `issai/LLama-3.1-KazLLM-1.0-8B` | 8.0 B | CC BY-NC 4.0, gated | good | strong | from ISSAI (Nazarbayev University) |
| `yandex/YandexGPT-5-Lite-8B-instruct` | 8.0 B | custom (YandexGPT-5-Lite licence) | **very strong** | weak | RU specialist; check licence terms |
| `meta-llama/Llama-3.1-8B-Instruct` | 8.0 B | Llama 3.1 licence, gated | good | weak | reference |
Selection (day 3): zero-shot **macro-F1 on our gold set** per language (EN/RU/KK, 300 items each) + JSON-validity rate + tokens/s in vLLM. Pick the best overall; if KK lags by > 10 F1 points, use Sherkala/KazLLM for KK news only.

**Fine-tuning (QLoRA):** base in 4-bit NF4 + double quant, LoRA `r=16, alpha=32, dropout=0.05` on all linear layers
(`q,k,v,o,gate,up,down`), lr 2e-4 cosine, 2 epochs, max seq 1024, packing on, gradient checkpointing, bf16 compute.
Fallback without bitsandbytes: bf16 LoRA (same hyper-parameters, micro-batch 2).

**Training data (licences):**
| Source | Use | Licence |
|---|---|---|
| Financial PhraseBank (`takala/financial_phrasebank`) | EN sentence sentiment | CC BY-NC-SA 3.0 |
| Twitter Financial News Sentiment (`zeroshot/twitter-financial-news-sentiment`) | EN headlines | MIT |
| FiQA sentiment (`TheFinAI/fiqa-sentiment-classification`) | EN aspect/entity sentiment | MIT (gated) |
| KazSAnDRA (`issai/kazsandra`) | KK general sentiment (domain adaptation) | CC BY 4.0 (gated) |
| **Own gold set** — 3 × 1 000 news items (EN/RU/KK, ours), labels: ticker, sentiment −2…+2, event type; labelled by the team with a written guideline, 20 % double-labelled (target Cohen's κ ≥ 0.6) | evaluation + fine-tune | ours |
| **Silver set** — 30–50 k items labelled by a larger teacher (`Qwen/Qwen3.6-27B` in AWQ 4-bit, ≈ 16 GB) and filtered by agreement with the **price reaction** (abnormal return next day) | fine-tune | derived from our data; keep internal |
Never train on test-period news (respect walk-forward boundaries for the sentiment feature too: the sentiment model used for fold *k* must be trained on data before fold *k*, or be the zero-shot model).

**Strict JSON output:** vLLM `response_format` / guided decoding with this schema, validated by Pydantic, one retry, then fall back to the baseline classifier:
```json
{"ticker": "KSPI", "relevance": 0.0-1.0, "sentiment": -2..2, "event": "earnings|guidance|m&a|dividend|regulation|macro|legal|other", "horizon": "days|weeks|months", "rationale": "≤ 30 words"}
```

### 4.5 Ensemble
- Level-0: LightGBM and XGBoost (short), LambdaRank models (long), baselines, LLM sentiment aggregates.
- Level-1: **logistic regression / ridge on out-of-fold predictions** (the walk-forward test predictions are the OOF set), plus regime features (VIX bucket, market). Non-negative weights, fitted on 2019–2022 folds, evaluated on 2023–2026.
- Report each component and the stack; keep the stack only if it beats the best single model on IC and Sharpe after costs.

### 4.6 Kazakhstan settings
- Horizons: emphasise **5 d and 1–3 m**; 1-day KASE predictions are reported but flagged low-confidence.
- Liquidity filter (§2.3) and lower sample weights on thin days; minimum 60 trades in the lookback window.
- **Two strategies compared:** (a) KZ-only models (≈ 14 names × 10 y ≈ 30 k rows — high variance), (b) **transfer:** pooled US+KZ model with `market` and `currency` flags plus KZ-specific features, fine-tuned (continued boosting, `init_model`) on KZ rows. Choose by KZ-fold IC.
- Lead–lag features from LSE/NASDAQ listings (§3) and USD/KZT, Brent.
- Costs for KASE in backtests: 15 bps commission + 30–100 bps spread/slippage depending on liquidity bucket.

---

## 5. VRAM and time budget (RTX 5090, 32 GB)

Estimates from model sizes and typical 5090 throughput; **measure on day 2 and update this table.**

| Job | Model / size | Precision | Batch / seq len | Est. VRAM | Est. time | Can run with |
|---|---|---|---|---|---|---|
| Env smoke test | — | bf16 | 8192² matmul | 1 GB | 1 min | anything |
| Embeddings | bge-m3 (568 M) | fp16 | 256 × 128 tok | 4 GB | 1 M texts ≈ 30 min | GBM training |
| Baseline sentiment | FinBERT / XLM-R base | fp16 | 512 × 64 tok | 3 GB | 4 M headlines ≈ 1 h | GBM training |
| Zero-shot eval of 6 candidates | 8–9 B | bf16 in vLLM | 900 gold items each | 20–24 GB | ≈ 10 min per model | nothing heavy |
| **QLoRA fine-tune** | Qwen3-8B | NF4 + bf16 LoRA r16 | micro-batch 8, seq 1024, grad-ckpt, grad-accum 4 | **16–20 GB** | 40 k ex × ≈ 400 tok ≈ 16 M tok/epoch at ≈ 3 k tok/s → **≈ 1.5 h/epoch, ≈ 3 h total** | GBM on CPU |
| bf16 LoRA (fallback) | Qwen3-8B | bf16 | micro-batch 2, seq 1024, grad-ckpt | 26–30 GB | ≈ 2.5 h total | nothing |
| Teacher labelling (silver set) | Qwen3.6-27B AWQ int4 | int4 weights | vLLM, 64 concurrent | 22–26 GB | 50 k items ≈ 3 h | nothing |
| **Batch sentiment (LLM)** | fine-tuned 8B merged | bf16, vLLM, `gpu_memory_utilization 0.9` | 256 concurrent, ≈ 250 tok in / 40 out | 29 GB | 1 M items (last 2 y + KZ) ≈ **3–4 h**; full 4 M history ≈ 14 h (optional — use the baseline for older years) | exclusive |
| **Trade-reviewer serving** | 8B | bf16 (or AWQ int4) | ≤ 16 concurrent, 4 k context | **19 GB** at util 0.55 (≈ 8 GB with AWQ at util 0.25) | p50 ≈ 2–3 s per review (≈ 300 output tokens at ≈ 120 tok/s single stream) | GBM training, embeddings |
| GBM training (XGBoost GPU) | 2.2 M rows × 250 features | float32 | hist, depth 6, 2 000 rounds | 3–5 GB | ≈ 1–2 min per fit; walk-forward 90 monthly folds ≈ **2–3 h** per config | reviewer serving |
| LightGBM (CPU, 8+ cores) | same | — | — | — | ≈ 3–6 min per fit | anything |
| Optuna tuning | 50 trials × 6 inner folds | GPU XGBoost | — | 3–5 GB | ≈ 6–8 h (overnight) | reviewer serving |

**Concurrency rules:** reviewer (≤ 19 GB) + XGBoost (≤ 5 GB) + embeddings (≤ 4 GB) fit together. QLoRA and batch
sentiment are exclusive jobs — schedule them at night and stop the reviewer (`TRADE_REVIEWER=mock` keeps the site working).

---

## 6. Backtest and metrics

- **Engine:** `ml/backtest/` vectorised daily simulator on the walk-forward predictions (no re-fitting inside the backtest).
- **Short-term strategy:** each day after the close, go long the top decile by `prob_up` (US) / top 3 (KZ), equal weight, hold 1 or 5 days (staggered sleeves for 5-day), only names passing liquidity filters; optional long-short (research only).
- **Long-term strategy:** monthly rebalance, long top quintile of the rank model, max 10 % per name, 30 % per sector.
- **Execution assumptions:** trade at next open (and at next close as a robustness check); costs US 5 bps commission + 5 bps slippage per side; KASE 15 bps + 30–100 bps by liquidity bucket; LSE GDR 10 bps + 20 bps.
- **Benchmarks:** buy-and-hold of the same universe (equal-weight), `SPY`/`^GSPC`, `QQQ`/`^NDX` for US; cap-weighted KASE Index proxy and buy-and-hold `KSPI.KZ`/`HSBK.KZ` for KZ; cash (Fed funds / NBK base rate).
- **Prediction metrics:** AUC and log-loss (direction), RMSE and MAE (returns), **Information Coefficient** (daily Spearman rank IC, mean, t-stat, IC IR), hit rate, calibration (reliability curve, Brier).
- **Strategy metrics:** CAGR, annualised volatility, **Sharpe**, **Sortino**, **max drawdown**, Calmar, **turnover**, average holding period, hit rate of trades, cost drag, exposure; all **after costs**, per year and per market.
- **Statistical sanity:** bootstrap CI for Sharpe; deflated Sharpe ratio for the number of configurations tried; report the survivorship-biased vs point-in-time universe difference (DATA_SOURCES §8).
- **Output:** `docs/BACKTEST_REPORT.md` generated from MLflow runs (tables + equity curves).

---

## 7. MLflow

- **Server:** `mlflow server --backend-store-uri postgresql://…/mlflow --artifacts-destination ./mlartifacts --host 0.0.0.0 --port 5000` (separate DB `mlflow` in the same Postgres; add as a `mlflow` service in `infra/docker-compose.yml` when needed).
- **Experiments:** `short_term_gbm`, `long_term_rank`, `sentiment_llm`, `ensemble`, `backtests`.
- **Logged per run:** git commit, config YAML, data snapshot hash (Parquet manifest), feature list + registry version, fold boundaries, metrics per fold and aggregated, SHAP summary plot, calibration plot, model artifact (`mlflow.lightgbm/xgboost/transformers`) with a **signature** and an input example.
- **Registry:** models `short_term_gbm`, `long_term_rank`, `news_sentiment`; aliases **`challenger`** (latest candidate) and **`production`** (what the site serves). Promotion only via `python -m ml.promote --model short_term_gbm --version N`, which checks: better or equal IC and Sharpe than the current `production` on the same folds, no look-ahead test failures, inference parity test passed.
- **Website pick-up:** `MLflowPredictionProvider` loads `models:/short_term_gbm@production` and `models:/long_term_rank@production` at startup and every hour checks whether the alias moved (hot reload). `model_version` stored with each prediction = `name:version`.

---

## 8. Integration with the website

Everything in this section is **configuration only** for the API — the interfaces already exist (`backend/app/ml_interface/`).

1. **Predictions:** implement `MLflowPredictionProvider(PredictionProvider)` in `ml/serving/provider.py` (imports `ml.features` for `build_features(as_of=t)`), register it in `backend/app/ml_interface/factory.py` (the `"mlflow"` branch already exists and currently falls back to the mock). Then set:
   ```env
   PREDICTION_PROVIDER=mlflow
   MLFLOW_TRACKING_URI=http://gpu-box:5000
   ```
   Every stored prediction then has `is_demo=false`; the API's `is_demo` flag turns the UI "Demo predictions" badge off automatically.
2. **Nightly inference:** Celery Beat task `generate_predictions` already runs at 23:30 UTC; with the real provider it computes features for all active tickers as of the last completed session and upserts `predictions` (one row per ticker × horizon × model_version × as_of_date). KZ predictions run after the KASE close via a second Beat entry at 13:00 UTC.
3. **Trade reviewer:** start vLLM on the GPU box (`scripts/gpu/setup_vllm.sh`), then in the website `.env`:
   ```env
   TRADE_REVIEWER=auto          # or llm
   LLM_BASE_URL=http://gpu-box:8001/v1
   LLM_API_KEY=<VLLM_API_KEY>
   LLM_MODEL=Qwen/Qwen3-8B      # or the merged fine-tuned model name
   ```
   `OpenAICompatibleTradeReviewer` already sends `response_format=json_object`, validates with Pydantic, retries once and falls back to the rule-based reviewer if the GPU box is down.
4. **News sentiment:** batch job writes `news.sentiment` and `news.embedding` (switch the column to `halfvec(1024)` in a migration if storage matters); the news API already returns `sentiment`.
5. **Monitoring:** daily job compares yesterday's predictions with realised returns (rolling 60-day IC/AUC per market) → shown on the "How the models work" page; alert (log + MLflow metric) if 20-day IC < 0 for 10 days.

---

## 9. Order of work and checklist

| Day | Step | Done when |
|---|---|---|
| 1 | Install OS, driver ≥ 580, Docker + NVIDIA toolkit (§1.2) | `nvidia-smi` shows RTX 5090, 32 GB, driver ≥ 580 |
| 1 | `scripts/gpu/setup_train_env.sh` | `verify_env.py --skip-vllm` prints `ALL CHECKS PASSED`; bf16 matmul ≥ 150 TFLOP/s |
| 1 | vLLM container + smoke test (§1.5) | JSON response; record tokens/s for 1 and 64 concurrent requests in this file |
| 1 | Start long downloads (Alpaca news, NBK history, KZ sitemaps) in the background | resumable jobs running, progress logged |
| 2 | Calendar, universe/membership, US + KZ prices, FX, macro, SEC (§2.1 #1–9) | Parquet lake filled; `docs/DATA_REPORT.md` v1 (coverage, gaps, cross-check flags) |
| 2 | Look-ahead tests + feature module v1 (technical, market, macro, KZ lead–lag) | `pytest ml/tests` green incl. `test_no_lookahead`, train/inference parity test |
| 3 | Gold-set labelling guideline; team labels 300/lang for evaluation (rest over the week) | 900 labelled items, κ measured |
| 3 | Zero-shot comparison of LLM candidates + baselines (§4.4) | table of macro-F1 / JSON-validity / tok/s in MLflow `sentiment_llm`; model chosen |
| 4 | Baselines + LightGBM/XGBoost short-term walk-forward (§4.1–4.2) | MLflow runs for all folds; IC, AUC vs baselines; SHAP sanity (no leakage-looking features) |
| 5 | Silver-set labelling with the teacher model; QLoRA fine-tune (§4.4) | fine-tuned model beats zero-shot by ≥ 5 macro-F1 on held-out gold; JSON validity ≥ 99 % |
| 6 | Batch sentiment (last 2 y + KZ) + embeddings; sentiment/news features | `news.sentiment` filled; feature importance of news features measured |
| 7 | Long-term ranking models (§4.3) + KZ settings (§4.6) | walk-forward NDCG/IC and long-only backtest vs benchmarks |
| 8 | Stacking ensemble (§4.5) + full backtest report (§6) | `docs/BACKTEST_REPORT.md`; ensemble kept only if it beats best single model after costs |
| 9 | MLflow registry + `MLflowPredictionProvider` + nightly inference (§7–8) | `PREDICTION_PROVIDER=mlflow` on staging: site shows real predictions, no demo badge; parity test green |
| 9 | LLM reviewer on vLLM (§8.3) | 20 sample trades reviewed in EN/RU/KK, all valid JSON, p95 latency < 6 s |
| 10 | Buffer, monitoring (§8.5), documentation, demo rehearsal | PROGRESS.md updated; known limitations documented |

### Main risks and fallbacks
| Risk | Signal | Fallback |
|---|---|---|
| bitsandbytes 4-bit does not work on `sm_120` | `verify_env.py` bnb check fails | bf16 LoRA (fits 32 GB); or AWQ/GPTQ-based QLoRA (`peft` + `gptqmodel`); or Unsloth in its own venv |
| vLLM wheel/container fails on Blackwell | smoke test error | build vLLM 0.32.0 from source with `TORCH_CUDA_ARCH_LIST="12.0"`; or SGLang; or llama.cpp server (OpenAI-compatible) with a GGUF Q5 model — the website does not care |
| KASE data becomes unavailable (Tradernet blocks or terms forbid) | HTTP 403 / written refusal | buy KASE "Market Prices of Securities" API (BLOCKERS #2); meanwhile use LSE GDRs + NASDAQ listings for KZ issuers and freeze KASE history already collected |
| Too little KZ data for stable models | wide fold-to-fold IC variance | pooled US+KZ transfer model, longer horizons only, report KZ as experimental |
| News history too large / slow | download > 2 nights | headlines + summaries only; LLM sentiment only for last 2 y; baseline classifier for older |
| Look-ahead leakage discovered | suspiciously high AUC (> 0.6 daily) or IC; leakage tests | stop, fix `available_at`, rerun; never report leaked numbers |
| GPU not delivered in time | — | §10 cloud fallback; all code runs on CPU with `--dry-run` |
| Overheating / power | throttling in `nvidia-smi -q -d PERFORMANCE` | power-limit to 450 W (`nvidia-smi -pl 450`): ≈ 5–10 % slower, much cooler |

---

## 10. Cloud fallback

All jobs above fit a single 32 GB GPU, so a **cloud RTX 5090** reproduces the plan exactly; A100 80 GB / H100 are only
needed if we move to larger teacher models. Prices from public trackers on **2026-10-28** (on-demand, per GPU-hour, vary hourly):

| Option | Price | Notes |
|---|---|---|
| **Vast.ai RTX 5090** (marketplace) | ≈ **$0.40–0.90/h** (lowest seen $0.21–0.43) | cheapest; hosts vary in reliability; use "verified" hosts, persistent volume for data |
| **RunPod RTX 5090** | **$0.69–0.99/h** Community, **$0.99–1.19/h** Secure | per-second billing; templates with CUDA 13 / vLLM; network volumes |
| RunPod L40S 48 GB | ≈ $0.86/h | Ada (sm_89) — no Blackwell quirks, slower than 5090 for LLM decode |
| RunPod A100 80 GB | ≈ $1.39–1.59/h | for 27–32 B teacher models in bf16 |
| RunPod H100 | ≈ $2.89–3.49/h | only if time-critical |

**Budget for the whole plan on a cloud 5090:** ≈ 60–80 GPU-hours (QLoRA ≈ 3 h, batch sentiment ≈ 4 h, teacher labelling ≈ 3 h,
GBM walk-forward + tuning ≈ 15 h, evaluation/experiments ≈ 30 h) → **≈ $40–90**. Keep data downloads and feature
building on a CPU machine (no GPU needed), copy only the Parquet panel (≈ 1 GB) to the cloud box; stop instances when idle.

---

### Sources (checked 2026-10-28)
- PyPI JSON API: torch, vllm, transformers, peft, trl, bitsandbytes, flash-attn, xgboost, lightgbm, mlflow versions and dependency pins.
- PyTorch wheel index `download.pytorch.org/whl/{cu126,cu129,cu130}/torch/`.
- Docker Hub `vllm/vllm-openai:v0.32.0` (pushed 2026-10-18, 9.2 GB amd64).
- vLLM issues [#35432](https://github.com/vllm-project/vllm/issues/35432) (closed 2026-05-15), [#31085](https://github.com/vllm-project/vllm/issues/31085), [#47749](https://github.com/vllm-project/vllm/issues/47749); PyTorch issue [#164342](https://github.com/pytorch/pytorch/issues/164342).
- flash-attention issues [#1638](https://github.com/Dao-AILab/flash-attention/issues/1638), [#2016](https://github.com/Dao-AILab/flash-attention/issues/2016); FA4 on sm_120 [investigation](https://gist.github.com/solatticus/aab6ec3a0436748b021cbbdd12e8c739).
- bitsandbytes [releases](https://github.com/bitsandbytes-foundation/bitsandbytes/releases) (0.48.0 CUDA 13, 0.50.x GB10 4-bit).
- Hugging Face model/dataset API: Qwen3-8B, Qwen3.5-9B (config `qwen3_5`), Qwen3.6-27B, Sherkala-8B-Chat, KazLLM-1.0-8B, YandexGPT-5-Lite-8B-instruct, FinBERT, XLM-R sentiment, bge-m3, multilingual-e5-large, financial_phrasebank, twitter-financial-news-sentiment, fiqa-sentiment-classification, KazSAnDRA; [Sherkala paper](https://arxiv.org/abs/2503.01493), [ISSAI KAZ-LLM](https://issai.nu.edu.kz/kazllm/).
- Prices: [computeprices.com RunPod 5090](https://computeprices.com/providers/runpod/gpus/rtx5090), [gpuperhour.com](https://gpuperhour.com/rent/rtx-5090), [gpufinder.dev](https://gpufinder.dev/gpu/rtx-5090), [RunPod pricing](https://www.runpod.io/gpu-cloud/pricing).
