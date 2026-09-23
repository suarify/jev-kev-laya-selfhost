# Laya vs Kev — Benchmark Report

> **Date:** 2026-09-23 · **Suite:** 8 cases (EN / ZH / MS / TA) · **Endpoint:** `POST /v1/systemone`
> **Laya:** `convaiinnovations/laya` (Docker, CPU, auto-checkpoint routing) on `:8000`
> **Kev:** `jaredpalmer/kev-0.6B` (Qwen base, CPU) on `:8009`
> **Runner:** [`benchmark/run.ps1`](./run.ps1) · **Cases:** [`benchmark/cases.json`](./cases.json)

---

## Executive summary

| Metric | Result | Target |
|---|---|---|
| Structure parity (envelope keys) | **8 / 8** ✅ | 8/8 |
| `choice` agreement (exact same answer) | **6 / 8** | — |
| `score` agreement (CLOSE, \|gap\| < 0.5) | **7 / 8** | — |
| `noul` agreement (CLOSE, \|gap\| < 0.3) | **12 / 16** | — |
| Transport / type errors | **0** | 0 |

**Wire compatibility is perfect** — every response parsed identically on both sides
(`{model, answers, usage, latency_ms}` + Laya's extra `routing`). All disagreement is
in *model judgment*, not format.

### Key findings

1. **Checkpoint routing works** — Han (zh) and Tamil (ta) text routed to the `multilingual`
   checkpoint with a correct script-detection reason; English *and* Bahasa Malaysia (Latin
   script) stayed on the `english` checkpoint, by design.
2. **Clean cases agree strongly** — single-intent questions (reschedule, follow-up, billing)
   matched 6/6. All choice disagreements came from deliberately *mixed* tickets.
3. **Non-English guardrails diverge both ways:**
   - **ZH toxicity:** Laya `0.93` vs Kev `0.05` — Kev blind to Chinese abusive content;
     this flipped the `severity` score (1.34 vs 0.58), the suite's only score MISS.
   - **TA escalation:** Laya under-escalates an urgent Tamil refund complaint (0.16 vs 0.65).
4. **`usage.output_tokens` is always 0 on Laya** (non-autoregressive, nothing generated) vs
   ~200–300 on Kev (counts serialized answer tokens). Expected; documented.

---

## Scoreboard by language

| Lang | Cases | Structure | choice | score | noul | Notes |
|---|---|---|---|---|---|---|
| 🇬🇧 English | 2 | 2/2 | 1/2 | 2/2 | 3/4 | 1 mixed-ticket choice diff |
| 🇨🇳 中文 | 2 | 2/2 | 1/2 | 1/2 | 3/4 | Kev misses ZH toxicity (score MISS) |
| 🇲🇾 Bahasa Malaysia | 2 | 2/2 | **2/2** | **2/2** | **4/4** | perfect sweep |
| 🇮🇳 தமிழ் | 2 | 2/2 | **2/2** | 2/2 | 2/4 | 2 urgency-threshold gaps |

**Best language pair: Bahasa Malaysia (full marks). Biggest gap: non-English guardrail scores.**

---

## Case-by-case results

### 🇬🇧 `en-support-mixed` — Support ticket (mixed delivery + billing)

> *"Shoes arrived two weeks late and in the wrong size. Also I see two charges on my card."*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| department | choice | **returns** 0.47 | **billing** 0.51 | ❌ DIFF (mixed ticket) |
| escalate | noul | 0.73 | 0.64 | ✅ CLOSE |
| threat | noul | 0.26 | 0.02 | ✅ CLOSE |
| frustration | score | 1.35 | 1.04 | ✅ CLOSE |

*Routing:* `english` · *Latency:* Laya 18155 ms (first-call warmup) | Kev 2847 ms

---

### 🇬🇧 `en-inbox-triage` — Email triage

> *"just checking if you received my proposal from last Tuesday?…"*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| label | choice | **follow_up** 0.79 | **follow_up** 0.92 | ✅ SAME |
| priority | score | 0.86 | 1.07 | ✅ CLOSE |
| is_cold_lead | noul | 0.09 | 0.22 | ✅ CLOSE |
| needs_tiny_reply | noul | 0.28 | 0.70 | ⚠️ GAP |

*Routing:* `english` · *Latency:* 3152 ms | 888 ms

---

### 🇨🇳 `zh-support-refund` — Refund + duplicate charge (Simplified Chinese)

> *"我两周前下的订单到现在还没收到，而且信用卡被扣了两次款……不然我就去消费者协会投诉你们。"*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| department | choice | **shipping** 0.78 | **returns** 0.77 | ❌ DIFF (mixed ticket) |
| escalate | noul | 0.84 | 0.85 | ✅ CLOSE |
| threat | noul | 0.01 | 0.18 | ✅ CLOSE |
| frustration | score | 1.42 | 1.56 | ✅ CLOSE |

*Routing:* **`multilingual`** — *non-Latin script (han, 100% of letters); the English checkpoint cannot read it*
*Latency:* 2566 ms | 909 ms

---

### 🇨🇳 `zh-content-moderation` — Abusive chat message

> *"你们这个破平台就是骗钱的！客服都是机器人，垃圾东西，我已经截图发到微博上了，等着吧。"*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| toxic | noul | **0.93** | **0.05** | ❌ GAP — Kev misses Chinese toxicity |
| public_shaming_risk | noul | 0.12 | 0.07 | ✅ CLOSE |
| severity | score | **1.34** | **0.58** | ❌ DIFF — only score MISS (same root cause) |
| action | choice | **escalate_manager** 0.45 | **escalate_manager** 0.57 | ✅ SAME |

> ⚠️ **Headline finding:** on abusive Chinese content, Kev reports *toxic ≈ 0.05* while Laya
> correctly flags *0.93* and escalates severity. Chinese moderation should not rely on Kev.

*Routing:* **`multilingual`** (han 100%) · *Latency:* 817 ms | 912 ms

---

### 🇲🇾 `ms-support-delivery` — Late delivery + double charge (Bahasa Malaysia)

> *"Saya dah tunggu dua minggu tapi pesanan masih tak sampai. Sekarang kad saya kena caj dua kali…"*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| department | choice | **returns** 0.57 | **returns** 0.61 | ✅ SAME |
| escalate | noul | 0.79 | 0.84 | ✅ CLOSE |
| threat | noul | 0.79 | 0.83 | ✅ CLOSE — both catch KPDN complaint threat |
| frustration | score | 1.05 | 1.15 | ✅ CLOSE |

*Routing:* `english` (Latin script — by design) · *Latency:* 2557 ms | 1079 ms

---

### 🇲🇾 `ms-whatsapp-appointment` — Clinic reschedule request

> *"Assalamualaikum, saya nak tanya boleh ke temujanji klinik gigi esok puk 3 diganti ke pagi?…"*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| intent | choice | **reschedule** 0.55 | **reschedule** 0.88 | ✅ SAME |
| is_urgent | noul | 0.25 | 0.24 | ✅ CLOSE |
| reply_today | noul | 0.23 | 0.36 | ✅ CLOSE |
| politeness | score | 1.19 | 1.37 | ✅ CLOSE |

*Routing:* `english` · *Latency:* 2022 ms | 966 ms · **Case score: full marks ✅**

---

### 🇮🇳 `ta-support-refund` — Refund + late order (Tamil)

> *"என் ஆர்டர் இரண்டு வாரமாக வரவில்லை, மேலும் என் கார்டில் இருமுறை பணம் பிடிக்கப்பட்டுள்ளது…"*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| department | choice | **billing** 0.99 | **billing** 0.87 | ✅ SAME |
| escalate | noul | **0.16** | **0.65** | ⚠️ GAP — Laya under-escalates |
| threat | noul | 0.16 | 0.26 | ✅ CLOSE |
| frustration | score | 1.42 | 1.24 | ✅ CLOSE |

*Routing:* **`multilingual`** (tamil 100%) · *Latency:* 1165 ms | 4069 ms

---

### 🇮🇳 `ta-booking-triage` — Train reschedule request (Tamil)

> *"வணக்கம், நாளை சென்னை - மதுரை ரயில் டிக்கெட்டை ஒரு நாள் பின்னாக மாற்ற வேண்டும்…"*

| Q | Type | Laya | Kev | Verdict |
|---|---|---|---|---|
| intent | choice | **reschedule** 0.88 | **reschedule** 1.00 | ✅ SAME |
| is_urgent | noul | 0.35 | 0.41 | ✅ CLOSE |
| reply_today | noul | 0.21 | 0.53 | ⚠️ GAP — threshold read differs |
| complexity | score | 1.01 | 0.92 | ✅ CLOSE |

*Routing:* **`multilingual`** (tamil 100%) · *Latency:* 781 ms | 2393 ms

---

## All diffs & gaps (consolidated)

| # | Case / question | Type | Laya | Kev | Classification |
|---|---|---|---|---|---|
| 1 | en-support-mixed / department | choice | returns | billing | mixed ticket — both defensible |
| 2 | en-inbox-triage / needs_tiny_reply | noul | 0.28 | 0.70 | threshold difference |
| 3 | zh-support-refund / department | choice | shipping | returns | mixed ticket — both defensible |
| 4 | zh-content-moderation / toxic | noul | **0.93** | **0.05** | **Kev blindness (ZH toxicity)** |
| 5 | zh-content-moderation / severity | score | 1.34 | 0.58 | follows #4 — only score MISS |
| 6 | ta-support-refund / escalate | noul | 0.16 | 0.65 | **Laya under-escalation (TA)** |
| 7 | ta-booking-triage / reply_today | noul | 0.21 | 0.53 | threshold difference |

---

## Accepted (inherent) differences

| Difference | Laya | Kev | Why it's fine |
|---|---|---|---|
| `routing` block in response | ✅ present | ❌ | Laya-only extra; clients ignore unknown keys |
| `usage.output_tokens` | always `0` | ~200–300 | Laya is non-autoregressive; Kev counts serialized answer tokens |
| API key auth | 3 super keys required | open by default (`KEV_API_KEY` optional) | intentional hardening |
| `x-typesafe-request-id` header | ✅ | ✅ | identical behavior |

---

## Reproduce

```powershell
.\benchmark\run.ps1                 # all 8 cases
.\benchmark\run.ps1 -Lang zh,ta     # by language
.\benchmark\run.ps1 -FailOnDiff     # CI mode: exit 1 on choice diff / errors
```

Verdict rules: `choice` = exact match · `score` CLOSE if \|gap\| < 0.50 · `noul` CLOSE if \|gap\| < 0.30.
