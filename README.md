# laya-selfhost

**Self-hosted [Laya](https://huggingface.co/convaiinnovations/laya) API** — a Dockerized, Jev-compatible HTTP wrapper around the System 1 decision model by **[convaiinnovations](https://huggingface.co/convaiinnovations)** ([GitHub](https://github.com/convaiinnovations/laya)). One forward pass, many typed answers (`choice` / `score` / `noul`) with probabilities — **$0 per call, fully offline, no cloud dependency.**

```bash
docker compose up -d
curl http://localhost:8000/health
```

---

## Quickstart

```bash
git clone git@github-suarify:suarify/laya-selfhost.git
cd laya-selfhost
docker compose up -d --build          # first run downloads weights (~once, cached in volume)

curl -X POST http://localhost:8000/v1/decide \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-laya-super-9f4a7c2e-ops-primary" \
  -d '{"state":"Double charged, refund today or we cancel","questions":{"team":{"type":"choice","instructions":"Route","criteria":{"billing":"payments","tech":"bugs","other":"x"}},"urgent":{"type":"noul","instructions":"Is this urgent?"}}}'
```

- **~600 ms** on CPU (8 threads), ~33 ms on GPU · health at `GET /health` · Swagger at `/docs`
- 3 super keys required (`Authorization: Bearer …` or `X-API-Key`) — rotate them in `app.py` before deploying

---

## Docs

| File | What's inside |
|---|---|
| **[API.md](./API.md)** | Full setup guide, request/response format, question-type use cases, **Caddy & nginx deployment to your own URL** |
| **[SKILL.md](./SKILL.md)** | Agent skill — drop into `~/.config/opencode/skills/laya-api/` or `.claude/skills/laya-api/` so coding agents can call this API |
| **[benchmark/REPORT.md](./benchmark/REPORT.md)** | 📊 8-case parity report (EN / 中文 / Bahasa Malaysia / தமிழ்) — Laya vs Kev |
| **[benchmark/README.md](./benchmark/README.md)** | How to run the benchmark suite (`run.ps1`, `-Lang`, `-FailOnDiff`) |

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/systemone` | Main decision endpoint (TypeSafe + Kev wire-compatible) |
| `POST` | `/v1/systemone/separate` | One forward pass per question |
| `POST` | `/v1/systemone/permute` | Option-order robustness for a choice question |
| `GET` | `/v1/models` | Loaded checkpoint cards |
| `POST` | `/v1/decide`, `/predict` | Aliases |
| `POST` | `/route` | Checkpoint routing only |
| `GET` | `/health` | Health (no auth) |

Responses are `{model, answers, usage, latency_ms}` + `routing` (Laya extra), with an `x-typesafe-request-id` header — same shapes as [jaredpalmer/kev](https://github.com/jaredpalmer/kev).

### Question types

- **`choice`** → label + full probability distribution + confidence — routing, classification, triage
- **`score`** → ordered 2–10 levels + weighted score + distribution — severity, sentiment, urgency
- **`noul`** → yes/no probability 0–1 — flags, gates, guardrails (refund asked? PII present? cancel threat?)

All three batch into a single forward pass — add more questions, latency barely moves.

---

## Benchmarks & comparisons

Everything lives in [`benchmark/`](./benchmark/) — same inputs → side-by-side models → agreement report.

| Suite | Models | What it shows |
|---|---|---|
| [`run.ps1`](./benchmark/run.ps1) + [`REPORT.md`](./benchmark/REPORT.md) | Laya vs [Kev](https://github.com/jaredpalmer/kev) | 8 cases × 4 languages (EN/ZH/MS/TA): **structure 8/8**, choice 6/8, score 7/8, noul 12/16 |
| [`three_way_compare.py`](./benchmark/three_way_compare.py) | Laya + Kev + [System-One](https://github.com/mithalouni/system-one-open) | 3-way on the EN sample; System-One (L4 GPU) ≈ 100–260 ms vs local CPU seconds |
| [`system_one_eval.py`](./benchmark/system_one_eval.py) | our 3 checkpoints (`english` / `multilingual` / `typed-decisions`) | TypeSafe public eval (20 cases / 372 pairs) following System-One's `evaluate.py` methodology — accuracy, ECE, latency, cost @ Jev's $0.042/M |
| [`build_typesafe_eval.py`](./benchmark/build_typesafe_eval.py) | — | Rebuilds the TypeSafe eval set locally from `evals.typesafe.ai` (no Modal) |

**System-One** ([mithalouni/system-one-open](https://github.com/mithalouni/system-one-open), MIT) is an open Jev-style replica (Gemma 4 E2B + attention LoRA). Their code runs on CPU (`S1_GPU=none`), but their trained weights live on *their* Modal volume — HF upload pending — so today you can (a) call their live Modal endpoint, or (b) train your own from the repo with downloadable base weights (`google/gemma-4-E2B-it` / `gemma-3-270m-it`). Our clone sits in [`system-one/`](./system-one/).

---

## Related useful links

- 🏗️ [**system-one-open**](https://github.com/mithalouni/system-one-open) — open Jev replica we benchmark against (MIT); methodology source for our TypeSafe eval runner
- 📊 [**Jev model benchmarks**](https://benchmarkheaven.com/jev-models) — benchmarkheaven leaderboard comparing Jev-class System 1 decision models
- 🎯 [**Benchmark artifact (Claude)**](https://claude.ai/artifact/9HPcmXJPaKWdYAJedgN1uf) — interactive benchmark artifact with results
- 🌐 [**layaForWeb**](https://github.com/vishalmysore/layaForWeb) — unofficial browser port (ONNX Runtime Web) — run Laya client-side with no server, by [vishalmysore](https://github.com/vishalmysore)

---

## Credits & license notes

- Model: **[convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)** (Apache-2.0) by ConvAI Innovations — built on ModernBERT-large (Answer.AI & LightOn)
- This repo: Docker + FastAPI wrapper only; please credit the original authors when you share deployments
- `system-one/` clone: **[mithalouni/system-one-open](https://github.com/mithalouni/system-one-open)** (MIT) — used for eval methodology and 3-way comparison
- `layaForWeb` is an unofficial port, not affiliated with ConvAI Innovations
