# -*- coding: utf-8 -*-
"""JevK5 v5: clean working recipe. graphs OFF (OOM-safe) + fast kernels + adapter + tunnels."""
import json

def code(src):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": [l + "\n" for l in src.rstrip("\n").split("\n")]}

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in src.rstrip("\n").split("\n")]}

cells = []

cells.append(md("""# JevK5 v5 — clean run (GPU + Cloudflare tunnel)

JevK5 (Qwen3.5-4B + LoRA) as a public TypeSafe `/v1/systemone` API.

* **Accelerator:** GPU T4 x2 · **Internet:** ON
* graphs OFF (OOM-safe) + fast linear-attention kernels for speed
* adapter on :8080 = CORS + accepts `options`/`levels` (Kev/Laya format)
* two tunnels: raw JevK5 (:8090) and adapter (:8080)
* For training/testing only; session + tunnels die on close."""))

cells.append(code("""import sys, subprocess
print("python", sys.version.split()[0])
subprocess.run(["nvidia-smi"], check=False)"""))

cells.append(code("""# --- install JevK5 + fast kernels + cloudflared ---
!git clone --depth 1 --branch v0.2.0 https://github.com/allebee/jevk5 /kaggle/working/j5
!cd /kaggle/working/j5 && pip -q install -e .
!pip -q install --upgrade "Pillow>=11.2"
!pip -q install "flash-linear-attention>=0.5" "einops" 2>/dev/null
!pip -q install "causal-conv1d" 2>/dev/null || echo "causal-conv1d build skipped (ok)"
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
!dpkg -i cloudflared-linux-amd64.deb 2>/dev/null || true
print("installed")"""))

cells.append(code("""# --- import fix (no stale cache, real package) ---
import os, sys
for k in list(sys.modules):
    if k == "jevk5" or k.startswith("jevk5."):
        del sys.modules[k]
sys.path.insert(0, "/kaggle/working/j5")
from jevk5 import JevK5
print("import ok:", jevk5.__file__)"""))

cells.append(code("""# --- quick sanity: load + one decide (downloads ~9GB first time) ---
import time
os.environ["JEVK5_GRAPHS"] = "0"
t0 = time.time()
model = JevK5("alibiserikbay/JevK5")
print(f"loaded {time.time()-t0:.0f}s device={model.device}")
print(model.decide("hi", {"type": "choice", "instructions": "?",
                          "criteria": ["a", "b"]}))
del model            # free GPU before the server starts
import gc; gc.collect()"""))

cells.append(code("""# --- start JevK5 server :8090 (graphs OFF, detached) ---
import os, subprocess
os.environ["JEVK5_GRAPHS"] = "0"
os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
subprocess.run("pkill -f jevk5-serve", shell=True)
subprocess.Popen("nohup jevk5-serve --model alibiserikbay/JevK5 --host 0.0.0.0 --port 8090 "
                 "> /kaggle/working/serve.log 2>&1 &", shell=True, cwd="/kaggle/working")
print("server starting ...")"""))

cells.append(code("""# --- wait for readiness + local test (native criteria format) ---
import subprocess, time
for _ in range(60):
    out = subprocess.run(["tail", "-n", "3", "/kaggle/working/serve.log"],
                         capture_output=True, text=True).stdout
    if "serving" in out or "8090" in out:
        print("server READY"); break
    time.sleep(5)
else:
    print("not ready yet; log tail:"); print(out)"""))

cells.append(code("""# --- adapter :8080 (CORS + options/levels -> criteria), detached ---
ADAPTER = r'''
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

JEVK5 = "http://127.0.0.1:8090"
app = FastAPI(title="JevK5 adapter")
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:5178"],
                   allow_credentials=True,
                   allow_methods=["POST", "OPTIONS"],
                   allow_headers=["Content-Type", "Authorization"])
client = httpx.AsyncClient(timeout=180)

def normalize(questions: dict) -> dict:
    out = {}
    for qid, q in questions.items():
        q = dict(q)
        t = q.get("type", "choice")
        if t == "choice":
            if "options" in q and "criteria" not in q:
                opts = q["options"]
                q["criteria"] = list(opts) if isinstance(opts, list) else opts
                q.pop("options", None)
            elif isinstance(q.get("criteria"), list):
                q["criteria"] = dict.fromkeys(q["criteria"])
        elif t == "score":
            if "levels" in q and "criteria" not in q:
                q["criteria"] = q["levels"]
                q.pop("levels", None)
        out[qid] = q
    return out

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def route(path: str, request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=200)
    body = await request.json()
    if "questions" in body and isinstance(body["questions"], dict):
        body = {**body, "questions": normalize(body["questions"])}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    r = await client.request(request.method, f"{JEVK5}/{path}", json=body, headers=headers)
    return Response(r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")})
'''
with open("/kaggle/working/jevk5_adapter.py", "w") as f:
    f.write(ADAPTER)
subprocess.run("pkill -f 'uvicorn jevk5_adapter'", shell=True)
subprocess.Popen("nohup uvicorn jevk5_adapter:app --host 0.0.0.0 --port 8080 "
                 "> /kaggle/working/adapter.log 2>&1 &", shell=True, cwd="/kaggle/working")
print("adapter starting ...")"""))

cells.append(code("""# --- test adapter with Kev/Laya format (options/levels) ---
import httpx, time
time.sleep(5)
body = {"state": "Double charged for order #4821, wants refund today or we cancel",
        "questions": {
          "department": {"type": "choice", "instructions": "Route the ticket", "options": ["billing", "shipping", "returns"]},
          "escalate":   {"type": "noul",   "instructions": "Needs human escalation?"},
          "frustration":{"type": "score",  "instructions": "Customer tone", "levels": ["calm", "frustrated", "very angry"]}}}
for _ in range(30):
    try:
        r = httpx.post("http://127.0.0.1:8080/v1/systemone", json=body, timeout=180)
        print("adapter:", r.status_code, str(r.json())[:200])
        break
    except Exception as e:
        print("waiting...", type(e).__name__); time.sleep(5)"""))

cells.append(code("""# --- tunnels: RAW :8090 and ADAPTER :8080 ---
import subprocess, time, os, re

def tunnel(port, logname):
    log = open(f"/kaggle/working/{logname}", "w")
    subprocess.Popen(["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
                     stdout=log, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        time.sleep(10)
        log.flush()
        txt = open(f"/kaggle/working/{logname}").read()
        m = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", txt)
        if m:
            return m.group(0)
    return None

RAW = tunnel(8090, "cf_raw.log")
ADP = tunnel(8080, "cf_adapter.log")
print("RAW_JEVK5_URL=", RAW)
print("ADAPTER_URL=", ADP)"""))

cells.append(md("""### Use these
* **Adapter (use this for your app):** `POST {ADAPTER_URL}/v1/systemone` — accepts `options`/`levels` (Kev/Laya format), CORS for `localhost:5178`.
* **Raw JevK5:** `POST {RAW_JEVK5_URL}/v1/systemone` — native `criteria` format only.

Both return `{model, answers, usage, latency_ms}`. Keep this notebook running to keep tunnels alive."""))

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12.0"}},
      "nbformat": 4, "nbformat_minor": 5}

out = r"benchmark/kaggle_jevk5_v5.ipynb"
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
with open(r"C:\Users\Acer\AppData\Local\Temp\opencode\kaggle_jevk5_v5.txt", "w", encoding="utf-8") as f:
    f.write(json.dumps(nb, ensure_ascii=False))
import os
print("wrote", out, os.path.getsize(out), "bytes")
print("compact:", os.path.getsize(r"C:\Users\Acer\AppData\Local\Temp\opencode\kaggle_jevk5_v5.txt"))