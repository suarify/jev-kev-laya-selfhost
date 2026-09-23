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

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/decide` | Main decision endpoint (Jev-compatible) |
| `POST` | `/v1/systemone` | TypeSafe-compatible alias |
| `POST` | `/predict` | Legacy alias |
| `POST` | `/route` | Checkpoint routing only |
| `GET` | `/health` | Health (no auth) |

### Question types

- **`choice`** → label + full probability distribution + confidence — routing, classification, triage
- **`score`** → ordered 2–10 levels + weighted score + distribution — severity, sentiment, urgency
- **`noul`** → yes/no probability 0–1 — flags, gates, guardrails (refund asked? PII present? cancel threat?)

All three batch into a single forward pass — add more questions, latency barely moves.

---

## Related useful links

- 📊 [**Jev model benchmarks**](https://benchmarkheaven.com/jev-models) — benchmarkheaven leaderboard comparing Jev-class System 1 decision models
- 🎯 [**Benchmark artifact (Claude)**](https://claude.ai/artifact/9HPcmXJPaKWdYAJedgN1uf) — interactive benchmark artifact with results
- 🌐 [**layaForWeb**](https://github.com/vishalmysore/layaForWeb) — unofficial browser port (ONNX Runtime Web) — run Laya client-side with no server, by [vishalmysore](https://github.com/vishalmysore)

---

## Credits & license notes

- Model: **[convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)** (Apache-2.0) by ConvAI Innovations — built on ModernBERT-large (Answer.AI & LightOn)
- This repo: Docker + FastAPI wrapper only; please credit the original authors when you share deployments
- `layaForWeb` is an unofficial port, not affiliated with ConvAI Innovations
