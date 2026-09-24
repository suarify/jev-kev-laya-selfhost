# -*- coding: utf-8 -*-
"""Rebuild benchmark/kaggle_jevk5_kev_laya.ipynb with install cells ACTIVE + robust tunnel."""
import json

def code(src):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": [l + "\n" for l in src.rstrip("\n").split("\n")]}

def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in src.rstrip("\n").split("\n")]}

app_py = open(r"app.py", encoding="utf-8").read()

cells = []

cells.append(md("""# JevK5 + Kev + Laya on Kaggle GPU (one API via Cloudflare tunnel)

Three TypeSafe-style decision models on one session:
* **JevK5** (allebee/jevk5) \u2192 `:8090` \u2014 Qwen3.5-4B + LoRA, ~9GB bf16, `/v1/systemone`
* **Kev** (jaredpalmer/kev) \u2192 `:8009` \u2014 serves `kev-latest` + `jev-latest`
* **Laya** (our app.py) \u2192 `:8000` \u2014 needs `Authorization: Bearer sk-laya-super-...`

For training/testing only (session ~12h, tunnel URL dies on close).
Setup: **Settings \u2192 Accelerator: GPU T4 x2** \u2192 **Internet: ON**.
If runtime is Python 3.11, Kev install will be skipped (needs 3.12+); JevK5 + Laya still work."""))

cells.append(code("""import sys, subprocess
print("python", sys.version.split()[0])
PY312 = sys.version_info >= (3, 12)
try:
    subprocess.run(["nvidia-smi"], check=False)
except Exception as e:
    print("nvidia-smi:", e)
print("Kev installable:", PY312)"""))

cells.append(code("""# --- installs: JevK5 (clone + editable; pip's git+ filter=blob:none fails on Kaggle) ---
!git clone --depth 1 --branch v0.2.0 https://github.com/allebee/jevk5 /kaggle/working/jevk5
!cd /kaggle/working/jevk5 && pip -q install -e .
!pip -q install "laya>=0.3.6" "fastapi" "uvicorn" "httpx"
print("base install done")"""))

cells.append(code("""# --- install cloudflared (wget+dpkg, per kumaresankp/kaggle_32gpu_free) ---
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
!dpkg -i cloudflared-linux-amd64.deb 2>/dev/null || true
!cloudflared --version 2>/dev/null || echo "cloudflared missing"

# --- install Kev (Python 3.12+ only) ---
if PY312:
    !git clone --depth 1 https://github.com/jaredpalmer/kev /kaggle/working/kev
    !cd /kaggle/working/kev && pip -q install -e ".[serve]"
    print("kev installed")
else:
    print("skipping kev (needs py3.12+); only jevk5+laya will run")"""))

cells.append(md("""## Write our Laya wrapper (app.py) into the working dir
Embedded from the opensource-jev repo \u2014 SUPER_KEYS + CORSMiddleware included."""))

cells.append(code("%%writefile /kaggle/working/app.py\n" + app_py.rstrip("\n")))

cells.append(code("""import os, threading, subprocess

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ["LAYA_DEVICE"] = "cuda"
os.environ["LAYA_PRELOAD"] = "1"
os.environ["LAYA_MAX_LOADED"] = "3"

def _run(cmd, cwd):
    print("start", cmd[0], flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)

threading.Thread(target=_run, args=(["jevk5-serve", "--model", "alibiserikbay/JevK5",
                                     "--host", "0.0.0.0", "--port", "8090"], "/kaggle/working"), daemon=True).start()

if PY312:
    threading.Thread(target=_run, args=(["python", "-m", "kev.serve", "--run", "jaredpalmer/kev-4b",
                                         "--port", "8009"], "/kaggle/working/kev"), daemon=True).start()

threading.Thread(target=_run, args=(["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"],
                                     "/kaggle/working"), daemon=True).start()
print("servers launching...")"""))

cells.append(code("""PROXY_CODE = r'''
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

proxy = FastAPI()
proxy.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                     allow_methods=["*"], allow_headers=["*"])
client = httpx.AsyncClient(timeout=180)

BACKENDS = {"jevk5": "http://127.0.0.1:8090", "kev": "http://127.0.0.1:8009", "laya": "http://127.0.0.1:8000"}

@proxy.api_route("/{service}/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
async def route(service: str, path: str, request: Request):
    base = BACKENDS.get(service)
    if base is None:
        return Response("unknown service", status_code=404)
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host","content-length")}
    try:
        r = await client.request(request.method, f"{base}/{path}", content=body, headers=headers,
                                 params=request.query_params)
    except Exception as e:
        return Response(f"proxy error: {e}", status_code=502)
    return Response(r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding","content-length","transfer-encoding")})
'''
with open("/kaggle/working/proxy.py", "w") as f:
    f.write(PROXY_CODE)
threading.Thread(target=_run, args=(["uvicorn", "proxy:proxy", "--host", "0.0.0.0", "--port", "8080"],
                                     "/kaggle/working"), daemon=True).start()
print("proxy starting on :8080 ...")"""))

cells.append(code("""import httpx, time
time.sleep(60)  # let models download + load

def check(path, **kw):
    try:
        r = httpx.post("http://127.0.0.1:8080" + path, timeout=180, **kw)
        return f"{r.status_code} {str(r.json())[:150]}"
    except Exception as e:
        return f"ERR {e}"

body = {"state": "hi", "questions": {"q": {"type": "choice", "instructions": "?",
                                           "criteria": ["a", "b"]}}}
print("jevk5:", check("/jevk5/v1/systemone", json=body))
print("kev  :", check("/kev/v1/systemone", json=body))
print("laya :", check("/laya/v1/systemone",
                      json={"state": "hi", "questions": {"q": {"type": "choice", "instructions": "?",
                                                                "criteria": ["a", "b"]}}},
                      headers={"Authorization": "Bearer sk-laya-super-9f4a7c2e-ops-primary"}))"""))

cells.append(code("""# --- cloudflare tunnel -> prints PUBLIC URL (non-blocking) ---
import subprocess, time
log = open("/kaggle/working/cf.log", "w")
p = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:8080"],
                     stdout=log, stderr=subprocess.STDOUT, text=True)
url = None
for _ in range(12):           # up to 120s
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

cells.append(md("""### Client endpoints
* `POST https://<tunnel>.trycloudflare.com/jevk5/v1/systemone`
* `POST https://<tunnel>.trycloudflare.com/kev/v1/systemone`
* `POST https://<tunnel>.trycloudflare.com/laya/v1/systemone` + `Authorization: Bearer sk-laya-super-9f4a7c2e-ops-primary`

All return `{model, answers, usage, latency_ms}`. JevK5 uses `criteria` (dict/list) for choices; Kev/Laya accept `options`/`criteria`/`levels`."""))

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.11.0"}},
      "nbformat": 4, "nbformat_minor": 5}

out = r"benchmark/kaggle_jevk5_kev_laya.ipynb"
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
import os
print("wrote", out, os.path.getsize(out), "bytes")

# write compact single-line version for the MCP push
with open(r"C:\Users\Acer\AppData\Local\Temp\opencode\kaggle_nb_run.txt", "w", encoding="utf-8") as f:
    f.write(json.dumps(nb, ensure_ascii=False))
print("compact bytes:", os.path.getsize(r"C:\Users\Acer\AppData\Local\Temp\opencode\kaggle_nb_run.txt"))
s = "".join(nb["cells"][0]["source"])
print("arrows ok:", "\u2192" in s)