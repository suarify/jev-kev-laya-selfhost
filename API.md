# Laya API — Self-Hosted System 1 Decision Model

A drop-in, Jev-compatible HTTP API for [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya) — a non-autoregressive **System 1 decision model**. Ask many typed questions about any piece of state (email, ticket, JSON, plain text) in a single forward pass. **No per-token cost, no cloud dependency, fully offline.**

```bash
docker compose up -d
curl http://localhost:8000/health
# {"status":"ok","device":"cpu","preload":true,"torch_threads":8}
```

> Built on **[laya](https://huggingface.co/convaiinnovations/laya)** by **convaiinnovations** ([GitHub](https://github.com/convaiinnovations/laya)) — a non-autoregressive System 1 decision model. Please credit the original authors when you share deployments of this wrapper.

---

## 📦 Setup (from zero to running)

### Prerequisites

- Docker + Docker Compose v2 ([docs.docker.com](https://docs.docker.com/compose/))
- ~5 GB disk for image + model weights
- Internet on first run (weights download once into a Docker volume)

### 1. Get the project

```bash
git clone <this-repo-url>
cd opensource-jev
```

### 2. Configure (optional — sensible defaults are baked in)

All knobs are environment variables in `docker-compose.yml`:

| Variable | Default | Meaning |
|---|---|---|
| `LAYA_DEVICE` | `cpu` | Set `cuda` for GPU (needs NVIDIA container toolkit) |
| `LAYA_PRELOAD` | `1` | Preload checkpoints at startup |
| `LAYA_MAX_LOADED` | `2` | Checkpoints kept in memory (LRU) |
| `TORCH_NUM_THREADS` | `8` | CPU threads — match your physical cores |
| `TORCH_INTEROP_THREADS` | `4` | Torch interop threads |
| `USE_TF` | `0` | Keep `0` — TF runtime deadlocks on CPU |
| `LAYA_MODEL` | *(fixed)* | Model id — `convaiinnovations/laya`, edit `app.py` to change |

**Rotate the API keys** before any shared deployment: edit `SUPER_KEYS` in `app.py` (3 strings, hardcoded as requested).

### 3. First launch

```bash
docker compose up -d --build
docker compose logs -f laya-api   # watch weight download + preload (first run only)
```

Wait until the healthcheck passes:

```bash
curl http://localhost:8000/health
# {"status":"ok","device":"cpu","preload":true,"torch_threads":8}
```

First **request** after boot takes ~2 s (Router warmup), steady state ~600 ms on CPU.

### 4. Verify with a keyed request

```bash
curl -X POST http://localhost:8000/v1/decide \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-laya-super-9f4a7c2e-ops-primary" \
  -d '{"state":"Billing double charged us","questions":{"team":{"type":"choice","instructions":"Route this","criteria":{"billing":"payments","tech":"bugs","other":"x"}}}}'
```

### Useful commands

```bash
docker compose up -d --build     # rebuild after code changes
docker compose logs -f laya-api  # follow logs
docker compose restart            # restart (warmup repeats, weights stay cached)
docker compose down               # stop (cache volume is preserved)
docker volume rm opensource-jev_laya-cache   # force re-download of weights
```

Weights persist in the `laya-cache` volume across restarts and rebuilds — you only download once.

---

## 🔑 Authentication

All decision endpoints require **exactly one** of three super keys. Requests without a valid key get `401`.

```
sk-laya-super-9f4a7c2e-ops-primary
sk-laya-super-3b8d1e6a-batch-worker
sk-laya-super-c7f20a95-readonly-demo
```

Send it either way:

```bash
# Jev / OpenAI style
-H "Authorization: Bearer sk-laya-super-9f4a7c2e-ops-primary"

# API-key style
-H "X-API-Key: sk-laya-super-3b8d1e6a-batch-worker"
```

> `/health` stays open for Docker healthchecks. Keys are hardcoded — rotate them if the image is ever shared publicly.

---

## 🚀 Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/decide` | Main endpoint (Jev-style) |
| `POST` | `/v1/systemone` | Alias matching TypeSafe's official path — swap base URLs, keep clients |
| `POST` | `/predict` | Legacy alias, same format |
| `POST` | `/route` | Language/checkpoint routing only (no forward pass) |
| `GET` | `/health` | Liveness + runtime info (no auth) |
| `GET` | `/docs` | Interactive Swagger UI |

---

## 📨 Request format

```jsonc
{
  "model": "laya-latest",          // optional — see Model selection
  "state": "…text… or object or array",   // the thing you're deciding about
  "questions": {
    "<id>": {
      "type": "choice | score | noul",     // required
      "instructions": "…",                 // required
      "criteria": { … }                    // required for choice/score, optional for noul
    }
  }
}
```

- **`state`** — a bare string (wrapped as `{body: …}`), a mapping, or an array. Emails, tickets, logs, form payloads, anything.
- **`questions`** — evaluated **together in one forward pass**. Add as many as you like; latency barely moves.
- **`model`** — `laya-latest` (default) auto-routes per request; pass `english` / `multilingual` / `typed-decisions` to pin a checkpoint. Unknown values → `422`.

### Full curl example

```bash
curl -X POST http://localhost:8000/v1/decide \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-laya-super-9f4a7c2e-ops-primary" \
  -d '{
    "model": "laya-latest",
    "state": "We were billed twice for March. Refund the duplicate today or we cancel our plan.",
    "questions": {
      "department": {
        "type": "choice",
        "instructions": "Which team handles this?",
        "criteria": {
          "billing": "invoices, payments, refunds",
          "technical": "bugs, outages",
          "sales": "pricing, contracts",
          "other": "anything else"
        }
      },
      "urgency": {
        "type": "score",
        "instructions": "How urgent is this?",
        "criteria": ["relaxed", "soon", "blocking / deadline today"]
      },
      "churn_risk": { "type": "noul", "instructions": "Does the user threaten to cancel?" },
      "refund_asked": { "type": "noul", "instructions": "Is a refund explicitly requested?" }
    }
  }'
```

## 📬 Response format

Flat Jev envelope `{model, answers, usage}` plus Laya's `routing` block. Latency is in the `X-Latency-Ms` **header** so the body stays wire-compatible with Jev clients.

```jsonc
{
  "model": "laya-latest",
  "answers": {
    "department": {
      "type": "choice",
      "choice": "billing",
      "probabilities": { "billing": 0.966, "technical": 0.028, "sales": 0.005, "other": 0.001 },
      "confidence": 0.851
    },
    "urgency": {
      "type": "score",
      "score": 1.44,                       // 0-based weighted score
      "legend": { "0": "relaxed", "1": "soon", "2": "blocking / deadline today" },
      "probabilities": { "0": 0.12, "1": 0.33, "2": 0.56 },
      "confidence": 0.14
    },
    "churn_risk":    { "type": "noul", "noul": 0.83, "confidence": 0.83 },
    "refund_asked":  { "type": "noul", "noul": 0.84, "confidence": 0.84 }
  },
  "usage": { "input_tokens": 86, "output_tokens": 0 },
  "routing": {
    "model": "english",
    "repo": "convaiinnovations/laya",
    "reason": "English Latin text",
    "detection": { "script": "latin", "language": "en", "is_english": true, … }
  }
}
```

---

## 🧠 The three question types — and what to use them for

### 1. `choice` — pick one label from a menu

Returns `choice`, per-option `probabilities`, and `confidence` (top-prob minus runner-up → *how much the model hesitated*).

**Best for: routing, classification, triage.**

| Use case | Sample `criteria` |
|---|---|
| Support ticket routing | `billing` / `technical` / `sales` / `other` |
| Spam / intent classification | `spam` / `promotion` / `genuine` |
| Bug report triage | `ui` / `backend` / `perf` / `docs` |
| Interview-schedule picker | candidate's available slots |
| Content moderation | `safe` / `borderline` / `block` |
| Lead qualification | `hot` / `warm` / `cold` (use `score` if ordered — see below) |
| Commit-message / PR label | `feat` / `fix` / `chore` / `docs` |
| Stack-trace cause | `npe` / `timeout` / `auth` / `config` |

> 💡 **Low confidence** = genuinely ambiguous input. Use it as a human-review trigger:
> `if (confidence < 0.4) → escalate to a person`.

---

### 2. `score` — place on an ordered 2–10 level scale

Returns weighted `score` (0-based), `legend`, full `probabilities`, `confidence`. The levels are **ordered** — the model understands `2` is "more" than `0`.

**Best for: magnitude, severity, ratings, priorities.**

| Use case | Scale (`criteria`) |
|---|---|
| Ticket severity | `cosmetic` → `degraded` → `down for everyone` |
| Customer sentiment | `furious` → `annoyed` → `neutral` → `delighted` |
| Churn risk level | `loyal` → `meh` → `restless` → `about to leave` |
| Deal stage / intent | `browsing` → `evaluating` → `ready to buy` |
| Pain intensity (health/feedback) | `none` → `mild` → `severe` → `emergency` |
| Email priority for inbox zero | `ignore` → `reply later` → `reply now` |
| Story estimation (fib-ish) | `trivial` → `small` → `medium` → `large` → `epic` |
| Model-output quality judge | `wrong` → `partial` → `correct` → `excellent` |
| Discount approval ladder | `no discount` → `10%` → `25%` → `custom (escalate)` |

> 💡 Because you get the **full distribution**, you can compute expected value instead of argmax:
> `expected = Σ p(level) × weight(level)` → feed into SLAs, pricing, or alerting thresholds.

---

### 3. `noul` — Yes/No as a probability (0–1)

Returns a single float `noul`. It's a **soft boolean**: `0.0` = confidently no, `0.5` = model has no clue, `1.0` = confidently yes. Many `noul`s in one pass = a **checklist evaluated atomically**.

**Best for: flags, gates, extractors, guardrails — anywhere you'd write `if` statements.**

| Use case | Sample `instructions` |
|---|---|
| Refund requested? | "Does the user explicitly ask for a refund?" |
| PII / secret in text? | "Does this text contain an email, phone number, or API key?" |
| Legal disclaimer needed? | "Does this output give financial, medical, or legal advice?" |
| Duplicate ticket? | "Is this a re-report of an already-known issue?" |
| SLA breached? | "Was the promised response deadline already missed?" |
| Escalation required? | "Does the message demand a manager or mention legal action?" |
| Onboarding complete? | "Has the user finished all 3 setup steps described above?" |
| Safe to auto-merge? | "Does this diff only touch tests and comments?" |
| Subscription cancelled? | "Does the user state they want to cancel or stop billing?" |
| Hallucination guard | "Is every proper noun in this answer present in the source text?" |
| Emotion: apology present | "Does the reply apologize without blaming the customer?" |
| Meeting action items | one `noul` per candidate action → "Is this an action item?" |

> 💡 **Threshold tuning:** don't hardcode `> 0.5`. Calibrate per use case — e.g. auto-send at `> 0.95`, human-review band `0.3–0.95`, auto-reject `< 0.3`.

---

### 🧩 Combining them — the real power

One request = one forward pass, N decisions:

```
ticket arrives
   ├─ choice:  department        → auto-assign owner
   ├─ score:   urgency           → SLA timer (p50 of distribution)
   ├─ noul:    contains_pii      → block webhook if > 0.9
   ├─ noul:    refund_asked      → route to billing queue if > 0.8
   └─ choice:  sentiment_bucket  → manager digest on "angry"
```

All five answers arrive together with per-answer probabilities — build if/else trees, expected-value math, and escalation gates on top.

---

## ⚡ Performance notes

- **~600 ms** steady state on this CPU (8 torch threads), **~33 ms** on GPU.
- Cost: **$0** — weights live in the `laya-cache` volume, inference is fully offline.
- First request after boot ≈ 2 s (Router warmup); checks `english` + `multilingual` are preloaded.
- Adding questions is nearly free — batching is what the architecture is for.
- `POST /route` costs nothing (classification only) if you just need to know which checkpoint would run.

## 🔀 Jev / TypeSafe compatibility

| | TypeSafe Jev | This API |
|---|---|---|
| Path | `api.typesafe.ai/v1/systemone` | `localhost:8000/v1/systemone` (alias) |
| Auth | `Authorization: Bearer <key>` | same + `X-API-Key` |
| Request | `{model, state, questions}` | **identical** |
| Answers | `choice` / `score` / `noul` | **wire-compatible** |
| Envelope | `{model, answers, usage}` | same + `routing` extra |
| Cost | per-token | free |

Point an existing Jev client at this container (change base URL + key) and it just works — `jev-latest` is accepted as a `model` alias for auto-routing.

---

## 🌍 Deploy on your own URL

The container listens on `0.0.0.0:8000` inside Docker. Put a TLS reverse proxy in front of it and point DNS at your server. Both examples assume DNS `laya.example.com → your-server-ip`.

**Server prep (both paths):**

```bash
# open only 22/80/443 (ufw example)
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
git clone <this-repo-url> && cd opensource-jev
docker compose up -d --build    # API on :8000
```

---

### Option A — Caddy (recommended: automatic HTTPS)

Caddy provisions and renews Let's Encrypt certs by itself — no certbot, no cron.

**Bare-metal install:**

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

`/etc/caddy/Caddyfile`:

```
laya.example.com {
    reverse_proxy localhost:8000
}
```

```bash
sudo systemctl reload caddy
```

**Or as a container next to the API** — add to `docker-compose.yml`:

```yaml
  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on: [laya-api]
    restart: unless-stopped

volumes:
  caddy_data:
```

Same `Caddyfile` content; on the compose network use `reverse_proxy laya-api:8000` and don't publish `8000` to the host.

Done — `https://laya.example.com/v1/decide` is live with valid TLS.

---

### Option B — Nginx (+ Certbot)

**Install:**

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/laya`:

```nginx
server {
    listen 80;
    server_name laya.example.com;

    # API bodies are small JSON; raise if you send huge states
    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # model inference can take a few seconds on cold start
        proxy_read_timeout    60s;
        proxy_send_timeout    60s;
        proxy_connect_timeout 10s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/laya /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d laya.example.com     # auto-HTTPS + auto-renew
```

> Bind the API to localhost only when using a host nginx/caddy: set
> `ports: ["127.0.0.1:8000:8000"]` in `docker-compose.yml` so :8000
> is never reachable from the internet (auth is defense-in-depth, not the only wall).

---

### Deployment checklist

- [ ] Rotated the 3 `SUPER_KEYS` in `app.py`
- [ ] API port bound to `127.0.0.1` (not `0.0.0.0`) when behind a reverse proxy
- [ ] TLS active (`curl -I https://laya.example.com/health` → 200)
- [ ] `docker compose restarts` covered (`restart: unless-stopped` already set)
- [ ] Health monitoring pings `/health` (no key needed)

---

## 🛠 Local commands

```bash
docker compose up -d --build     # rebuild after code changes
docker compose logs -f laya-api  # watch startup (weight download on first run)
docker compose down              # stop
curl http://localhost:8000/docs  # Swagger UI (add a Bearer key to try endpoints)
```