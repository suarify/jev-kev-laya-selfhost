# -*- coding: utf-8 -*-
"""Build a simple JevK5-only Kaggle notebook: install -> serve -> cloudflare tunnel."""
import json

def code(src):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": [l + "\n" for l in src.rstrip("\n").split("\n")]}

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in src.rstrip("\n").split("\n")]}

cells = []

cells.append(md("""# JevK5 on Kaggle GPU + Cloudflare tunnel

JevK5 (allebee/jevk5, Qwen3.5-4B + LoRA) served as a TypeSafe-style `/v1/systemone` API and exposed via a temporary Cloudflare Quick Tunnel.

* **Accelerator:** GPU T4 x2
* **Internet:** ON
* Session + tunnel die after ~12h or on close. For training/testing only."""))

cells.append(code("""import sys, subprocess
print("python", sys.version.split()[0])
subprocess.run(["nvidia-smi"], check=False)"""))

cells.append(code("""# --- install JevK5 (clone + editable; pip's git+ filter=blob:none fails on Kaggle) ---
!git clone --depth 1 --branch v0.2.0 https://github.com/allebee/jevk5 /kaggle/working/jevk5
!cd /kaggle/working/jevk5 && pip -q install -e .
print("jevk5 installed")"""))

cells.append(code("""# --- fix torch/torchvision mismatch (torchvision::nms does not exist) ---
!pip -q install --upgrade --force-reinstall --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121
import torch, torchvision, transformers
print("torch", torch.__version__, "| cuda", torch.cuda.is_available())
print("torchvision", torchvision.__version__)
print("transformers", transformers.__version__, "| ok")"""))

cells.append(code("""# --- start jevk5-serve on :8090 (GPU) ---
import threading, subprocess, time
def _run(cmd, cwd):
    print("start", cmd[0], flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)

threading.Thread(target=_run, args=(["jevk5-serve", "--model", "alibiserikbay/JevK5",
                                     "--host", "0.0.0.0", "--port", "8090"],
                                    "/kaggle/working"), daemon=True).start()
print("jevk5 starting on :8090 ... (weights download ~9GB first time)")"""))

cells.append(code("""# --- local sanity check ---
import httpx, time
time.sleep(20)
body = {"state": "Order #7120 shows delivered to No. 17; the customer lives at No. 71.",
        "questions": {"what": {"type": "choice", "instructions": "What happened to the parcel?",
                               "criteria": ["delivered", "misdelivered", "unknown"]}}}
for _ in range(30):
    try:
        r = httpx.post("http://127.0.0.1:8090/v1/systemone", json=body, timeout=180)
        print("jevk5:", r.status_code, str(r.json())[:200])
        break
    except Exception as e:
        print("waiting...", type(e).__name__)
        time.sleep(10)"""))

cells.append(code("""# --- cloudflare tunnel -> prints PUBLIC URL (non-blocking) ---
import subprocess, time
log = open("/kaggle/working/cf.log", "w")
p = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:8090"],
                     stdout=log, stderr=subprocess.STDOUT, text=True)
url = None
for _ in range(15):
    time.sleep(10)
    log.flush()
    try:
        txt = open("/kaggle/working/cf.log").read()
    except Exception:
        txt = ""
    for line in txt.splitlines():
        if "trycloudflare.com" in line:
            url = line.strip().split(" ")[-1]
            break
    if url:
        break
print("TUNNEL_URL=", url)"""))

cells.append(md("""### Public endpoint
* `POST https://<tunnel>.trycloudflare.com/v1/systemone`

Request:
```json
{"state": "Order #7120 shows delivered to No. 17; the customer lives at No. 71.",
 "questions": {"what": {"type": "choice", "instructions": "What happened to the parcel?",
                        "criteria": ["delivered", "misdelivered", "unknown"]}}}
```
Response: `{model, answers, usage, latency_ms}`. JevK5 supports `noul` / `choice` / `score` (criteria = dict or list). Keep the notebook + tunnel running to keep the URL live."""))

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12.0"}},
      "nbformat": 4, "nbformat_minor": 5}

out = r"benchmark/kaggle_jevk5_simple.ipynb"
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
with open(r"C:\Users\Acer\AppData\Local\Temp\opencode\kaggle_jevk5_simple.txt", "w", encoding="utf-8") as f:
    f.write(json.dumps(nb, ensure_ascii=False))
import os
print("wrote", out, os.path.getsize(out), "bytes")
print("compact bytes:", os.path.getsize(r"C:\Users\Acer\AppData\Local\Temp\opencode\kaggle_jevk5_simple.txt"))