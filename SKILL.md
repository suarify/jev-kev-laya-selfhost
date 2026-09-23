---
name: laya-api
description: Use when calling a self-hosted Laya System 1 decision API (Jev-compatible POST /v1/decide), when the user wants fast typed yes/no, multiple-choice, or ordinal-score judgments over text/JSON state in one request, or mentions laya, System 1 decisions, convaiinnovations/laya, noul probabilities, or a local alternative to TypeSafe Jev. Covers auth keys, request/response format, question types (choice/score/noul), setup, and Caddy/nginx deployment.
---

# Laya API skill

**Model credit:** [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya) ([GitHub](https://github.com/convaiinnovations/laya)) — non-autoregressive System 1 decision model. This skill documents a local Docker wrapper with a Jev-compatible HTTP API. Always link and credit the original authors when sharing.

## What it does

One forward pass → many typed answers. Given a `state` (string / object / array) and a map of `questions`, the API returns per-question answers with probabilities. No chat, no generation — pure typed decisions.

- Base URL (local): `http://localhost:8000`
- Endpoints (wire-identical to jaredpalmer/kev): `POST /v1/systemone` (primary), `POST /v1/systemone/separate`, `POST /v1/systemone/permute`, `GET /v1/models`; Laya extras: `POST /v1/decide`, `POST /predict`, `POST /route`, `GET /health` (no auth), `GET /docs` (Swagger)
- Every response includes an `x-typesafe-request-id` header

## Auth (mandatory)

Every decision endpoint requires **one** of these hardcoded super keys (401 otherwise):

```
sk-laya-super-9f4a7c2e-ops-primary
sk-laya-super-3b8d1e6a-batch-worker
sk-laya-super-c7f20a95-readonly-demo
```

Send as `Authorization: Bearer <key>` or `X-API-Key: <key>`. Rotate in `app.py` (`SUPER_KEYS`) before sharing an image publicly.

## Request shape (Jev wire-compatible)

```json
{
  "model": "laya-latest",
  "state": "text or object or array",
  "questions": {
    "<id>": {
      "type": "choice | score | noul",
      "instructions": "what to decide",
      "criteria": {}
    }
  }
}
```

- `model`: `laya-latest` (default) auto-routes; pin `english` | `multilingual` | `typed-decisions`. `jev-latest` accepted as auto alias. Unknown → 422.
- `state`: bare string is wrapped as `{"body": ...}`.
- Many questions batch into one forward pass — latency barely grows.

## Response shape

```json
{
  "model": "laya-latest",
  "answers": { "<id>": { ... } },
  "usage": { "input_tokens": N, "output_tokens": 0 },
  "latency_ms": 612.4,
  "routing": { "model": "english", "reason": "...", ... }
}
```

`latency_ms` sits in the body (same as Kev). `routing` is the only extra field — which checkpoint ran and why.

## Question types

### `choice` — one label from a menu
Returns `choice`, `probabilities` (per option), `confidence` (top minus runner-up → hesitation).
Use for: routing, classification, triage, moderation.
`criteria`: `{ "opt1": "hint", "opt2": "hint", ... }` (≤255 options).
Tip: `confidence < 0.4` → escalate to a human.

### `score` — ordered 2–10 levels
Returns `score` (0-based weighted), `legend`, full `probabilities`, `confidence`.
Use for: severity, sentiment, urgency, priority, ratings.
`criteria`: ordered array `["low", "medium", "high"]`.
Tip: compute expected value `Σ p(level)·weight(level)` from the distribution instead of argmax.

### `noul` — yes/no probability (0–1)
Returns `noul` float (+ `confidence`). Soft boolean: ~0 = no, ~0.5 = unsure, ~1 = yes.
`criteria` optional: `{ "true": "...", "false": "..." }`.
Use for: flags, gates, extractors, guardrails — refunds asked? PII present? cancel threat? legal advice? safe to auto-merge?
Tip: calibrate thresholds per use case (`>0.95` auto-act, `0.3–0.95` human review, `<0.3` reject).

## Canonical call (PowerShell-safe: write JSON to a temp file, UTF-8, `--data-binary @file`)

```bash
curl -X POST http://localhost:8000/v1/decide \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-laya-super-9f4a7c2e-ops-primary" \
  -d '{"model":"laya-latest","state":"Double charged, refund today or we cancel","questions":{"team":{"type":"choice","instructions":"Route","criteria":{"billing":"payments","tech":"bugs","other":"x"}},"urgent":{"type":"noul","instructions":"Is this urgent?"},"sev":{"type":"score","instructions":"Severity","criteria":["cosmetic","degraded","down"]}}}'
```

Success: HTTP 200 with `model/answers/usage/routing`. No/wrong key: 401. Bad `model`: 422.

## Setup

1. Prereqs: Docker + Compose v2, ~5 GB disk, internet for first weight pull.
2. `docker compose up -d --build` → wait for `/health` → weights cached in volume `laya-cache`.
3. Knobs in `docker-compose.yml`: `LAYA_DEVICE=cpu|cuda`, `LAYA_PRELOAD=1`, `LAYA_MAX_LOADED=2`, `TORCH_NUM_THREADS=<physical cores>`, `USE_TF=0` (keep 0 — TF deadlocks on CPU).
4. Performance: ~600 ms CPU steady state, first request after boot ~2 s; cost $0, fully offline.
5. Full guide: `API.md` in the repo (setup + question-type use cases + deployment).

## Deploy on your own URL

- **Caddy (recommended):** `laya.example.com { reverse_proxy localhost:8000 }` — automatic HTTPS; or add a `caddy:2` service to compose and use `reverse_proxy laya-api:8000`.
- **Nginx + certbot:** `proxy_pass http://127.0.0.1:8000;` with forwarded headers, `proxy_read_timeout 60s`, `client_max_body_size 2m`, then `certbot --nginx -d laya.example.com`.
- Bind API to `127.0.0.1:8000:8000` when behind a proxy; keep keys rotated; monitor `/health`.

## Jev / TypeSafe drop-in

Request `{model, state, questions}` and answer types `choice/score/noul` are wire-identical to TypeSafe Jev — point an existing client at this base URL + one of the super keys. Differences: local path/key, envelope adds `routing`, no per-token billing.
