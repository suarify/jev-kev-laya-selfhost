# Benchmark & Kaggle tooling

Self-hosted decision models and the notebooks to run them on a Kaggle GPU behind a Cloudflare tunnel.

| File | What it is |
|---|---|
| `kaggle_laya.py` | Run our **Laya** wrapper on Kaggle GPU (direct `Router.predict` + optional FastAPI) |
| `jevk5_adapter.py` | CORS + format adapter (Kev/Laya `options`/`levels` → JevK5 `criteria`) for serving JevK5 |
| `kaggle_jevk5_run.ipynb` | ✅ **Current JevK5 recipe** — install → server → adapter → tunnel (v5) |
| `kaggle_jevk5_simple.ipynb` | Minimal JevK5-only server + tunnel (no adapter) |
| `kaggle_jevk5_v5.ipynb` | Clean JevK5 v5 (graphs OFF + fast kernels + adapter + 2 tunnels) |
| `build_kaggle_*.py` | Builders that regenerate the `.ipynb` files |

## Quick path to a public JevK5 API (Kaggle, GPU T4, Internet ON)

1. Run `kaggle_jevk5_v5.ipynb` top-to-bottom.
2. Last cell prints `RAW_JEVK5_URL` (:8090, native `criteria`) and `ADAPTER_URL` (:8080, accepts `options`/`levels` + CORS for `localhost:5178`).
3. Point your client at `{ADAPTER_URL}/v1/systemone`.

```bash
curl -X POST "{ADAPTER_URL}/v1/systemone" \
  -H "Content-Type: application/json" \
  -d '{"state": "Double charged, wants refund",
       "questions": {"department": {"type": "choice", "instructions": "Route",
                                     "options": ["billing", "shipping", "returns"]}}}'
```

Sessions and tunnels are temporary (~12h) — for training/testing only.

## Model format notes

- **JevK5 native:** `criteria` (dict or list) — server rejects `options`/`levels`.
- **Kev/Laya format:** `options` / `levels` — the **adapter** maps these to `criteria`, so the same payload works for all three.