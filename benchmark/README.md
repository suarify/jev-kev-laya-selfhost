# Laya vs Kev benchmark

Side-by-side curl-style test suite: same inputs → both servers → agreement report.

📊 **Latest full-run results → [REPORT.md](./REPORT.md)** (8/8 structure, 6/8 choice, 7/8 score, 12/16 noul)

## Cases

8 cases, 2 per language, each exercising `choice` + `noul` + `score` questions:

| Case | Lang | Use case |
|---|---|---|
| `en-support-mixed` | English | Support ticket: route / escalate / threat / frustration |
| `en-inbox-triage` | English | Email triage: label / priority / 2 nouls |
| `zh-support-refund` | 中文 | Refund + duplicate charge, consumer-council threat |
| `zh-content-moderation` | 中文 | Abusive post: toxicity / public-shaming / action |
| `ms-support-delivery` | Bahasa Malaysia | Delivery + double charge, KPDN complaint threat |
| `ms-whatsapp-appointment` | Bahasa Malaysia | Clinic reschedule: intent / urgency / politeness |
| `ta-support-refund` | தமிழ் | Refund + late order, consumer forum threat |
| `ta-booking-triage` | தமிழ் | Train reschedule: intent / urgency / complexity |

Non-English cases use **native-language instructions and criteria labels** — question ids stay stable so agreement can be computed across models.

## Run

```powershell
# both servers up (Laya :8000, Kev :8009)
.\benchmark\run.ps1

# one language
.\benchmark\run.ps1 -Lang zh,ta

# specific case
.\benchmark\run.ps1 -Id ta-support-refund

# CI-style: exit 1 on any choice disagreement or transport error
.\benchmark\run.ps1 -FailOnDiff
```

## What is compared

| Check | Criterion |
|---|---|
| Structure | Envelope keys equal (Laya's extra `routing` ignored) |
| `choice` | Exact SAME / DIFF on picked answer |
| `score` | CLOSE if \|gap\| < 0.50 (0–N scale) |
| `noul` | CLOSE if \|gap\| < 0.30 |
| Types | `choice`/`noul`/`score` present and equal per question id |

Inherent (accepted) differences: `routing` block only on Laya, `usage.output_tokens` always 0 on Laya, Laya requires an API key.
