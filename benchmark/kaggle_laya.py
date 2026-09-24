# Kaggle notebook: run Laya on GPU (T4/P100)
#
# 1. New notebook -> Settings -> Accelerator: "GPU T4 x2" (or P100)
# 2. Settings -> Internet: ON (needed to pip install + download weights)
# 3. Paste cells below, run.
#
# Notebook cells:

# ------------------------------------------------------------------
# Cell 1: install
# ------------------------------------------------------------------
# !pip -q install "laya>=0.3.6"

# ------------------------------------------------------------------
# Cell 2: load router on GPU (run once; ~30-60s first time downloads weights)
# ------------------------------------------------------------------
import os, json, time
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

import torch
print("cuda:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")

from laya import Router

router = Router(device="cuda", preload=True, max_loaded=3)
print("checkpoints preloaded")

# ------------------------------------------------------------------
# Cell 3: helper — your payload uses criteria values = null, which Laya
#         rejects. Convert any choice question's criteria to an options list.
# ------------------------------------------------------------------
def fix_questions(questions):
    out = {}
    for qid, q in questions.items():
        q = dict(q)
        if q.get("type") == "choice":
            crit = q.get("criteria")
            if isinstance(crit, dict):
                # options = keys whose value is not None; drop null-only options
                q["options"] = [k for k, v in crit.items() if v is not None]
                q.pop("criteria", None)
        out[qid] = q
    return out

# ------------------------------------------------------------------
# Cell 4: load YOUR driving payload from a file (see below for format)
# ------------------------------------------------------------------
payload = json.load(open("/kaggle/input/your-payload/payload.json"))  # or paste dict inline

state = payload["state"]
questions = fix_questions(payload["questions"])

# ------------------------------------------------------------------
# Cell 5: predict (GPU) + timing
# ------------------------------------------------------------------
t0 = time.time()
result = router.predict(state, questions)   # model auto-routes; or model="english" to pin
ms = (time.time() - t0) * 1000

print(f"latency: {ms:.1f} ms")
for qid, ans in (result.get("answers") or {}).items():
    if isinstance(ans, dict):
        choice = ans.get("choice") or (f"score={ans.get('score')}" if "score" in ans else f"noul={ans.get('noul')}")
        print(f"  {qid}: {choice}")
        if "probabilities" in ans:
            top = sorted(ans["probabilities"].items(), key=lambda kv: -kv[1])[:3]
            print(f"      top: {top}")

# ------------------------------------------------------------------
# Optional: serve the same FastAPI endpoint from the notebook
# (not needed unless you want to curl it from elsewhere)
# ------------------------------------------------------------------
# !pip -q install fastapi uvicorn
# import threading
# from app import app   # you'd need app.py + the laya Router wired to cuda
# threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=8000), daemon=True).start()