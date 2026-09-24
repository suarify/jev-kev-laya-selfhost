# Kaggle notebook — host JevK5 + Kev + Laya as one API via cloudflare tunnel
#
# Three TypeSafe-style decision models on one Kaggle GPU session:
#   JevK5  (allebee/jevk5)    -> :8090   /v1/systemone   Qwen3.5-4B + LoRA, ~9GB bf16
#   Kev    (jaredpalmer/kev)  -> :8009   /v1/systemone   serves BOTH kev-latest and jev-latest
#   Laya   (our app.py)       -> :8000   /v1/systemone   requires Authorization: Bearer sk-laya-...
#
# For training/testing only. Session ends (~12h) -> tunnel URL dies.
#
# Setup: Settings -> Accelerator "GPU T4 x2"  |  Internet ON
#        If the runtime is Python <3.12, Kev install fails (needs 3.12-3.13);
#        JevK5 + Laya still work.

# ==================================================================
# Cell 1 — sanity: python version + GPU
# ==================================================================
import sys, subprocess
print("python", sys.version.split()[0])
subprocess.run(["nvidia-smi"], check=False)
assert sys.version_info >= (3, 12), "Kev needs Python 3.12+ (switch runtime or drop Kev)"

# ==================================================================
# Cell 2 — install JevK5 + Laya + server deps
# ==================================================================
# !pip -q install "jevk5[fast] @ git+https://github.com/allebee/jevk5@v0.2.0"
# !pip -q install "laya>=0.3.6" "fastapi" "uvicorn" "httpx" "cloudflared"

# ==================================================================
# Cell 3 — install Kev from GitHub (serves kev-latest + jev-latest)
# ==================================================================
# !git clone --depth 1 https://github.com/jaredpalmer/kev /kaggle/working/kev
# !cd /kaggle/working/kev && pip -q install -e ".[serve]"

# ==================================================================
# Cell 4 — bring our Laya wrapper (app.py: SUPER_KEYS + CORS) into the notebook
# ==================================================================
# Upload app.py as a Dataset, or paste it, then:
# import shutil; shutil.copy('/kaggle/input/<your-dataset>/app.py', '/kaggle/working/app.py')

# ==================================================================
# Cell 5 — launch all three servers (GPU)
# ==================================================================
import os, threading, subprocess

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ["LAYA_DEVICE"] = "cuda"
os.environ["LAYA_PRELOAD"] = "1"
os.environ["LAYA_MAX_LOADED"] = "3"

def _run(cmd, cwd):
    print("start", cmd[0], flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)

# JevK5 on :8090
threading.Thread(target=_run, args=(
    ["jevk5-serve", "--model", "alibiserikbay/JevK5", "--host", "0.0.0.0", "--port", "8090"],
    "/kaggle/working"), daemon=True).start()

# Kev on :8009 (kev-latest / jev-latest aliases; bf16 on the T4)
threading.Thread(target=_run, args=(
    ["python", "-m", "kev.serve", "--run", "jaredpalmer/kev-4b", "--port", "8009"],
    "/kaggle/working/kev"), daemon=True).start()

# Laya on :8000 (our app.py, requires the super key)
threading.Thread(target=_run, args=(
    ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"],
    "/kaggle/working"), daemon=True).start()

print("all three launching...")

# ==================================================================
# Cell 6 — fan-out proxy with CORS (single public URL, 3 models)
#   /jevk5/* -> :8090    /kev/* -> :8009    /laya/* -> :8000
# ==================================================================
PROXY_CODE = r'''
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

proxy = FastAPI()
proxy.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                     allow_methods=["*"], allow_headers=["*"])
client = httpx.AsyncClient(timeout=180)

BACKENDS = {"jevk5": "http://127.0.0.1:8090", "kev": "http://127.0.0.1:8009", "laya": "http://127.0.0.1:8000"}

@proxy.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def route(service: str, path: str, request: Request):
    base = BACKENDS.get(service)
    if base is None:
        return Response("unknown service", status_code=404)
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    try:
        r = await client.request(request.method, f"{base}/{path}", content=body, headers=headers,
                                 params=request.query_params)
    except Exception as e:
        return Response(f"proxy error: {e}", status_code=502)
    return Response(r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")})
'''

# ==================================================================
# Cell 7 — start the proxy on :8080
# ==================================================================
with open("/kaggle/working/proxy.py", "w") as f:
    f.write(PROXY_CODE)
threading.Thread(target=_run, args=(
    ["uvicorn", "proxy:proxy", "--host", "0.0.0.0", "--port", "8080"],
    "/kaggle/working"), daemon=True).start()
print("proxy starting on :8080 ...")

# ==================================================================
# Cell 8 — sanity check all three BEFORE the tunnel
# ==================================================================
import httpx, time
time.sleep(60)  # let models download + load

def check(path, **kw):
    try:
        r = httpx.post("http://127.0.0.1:8080" + path, timeout=180, **kw)
        return f"{r.status_code} {str(r.json())[:120]}"
    except Exception as e:
        return f"ERR {e}"

body = {"state": "hi", "questions": {"q": {"type": "choice", "instructions": "?",
                                           "criteria": ["a", "b"]}}}
print("jevk5:", check("/jevk5/v1/systemone", json=body))
print("kev  :", check("/kev/v1/systemone", json=body))
print("laya :", check("/laya/v1/systemone",
                      json={"state": "hi", "questions": {"q": {"type": "choice", "instructions": "?",
                                                                "criteria": ["a", "b"]}}},
                      headers={"Authorization": "Bearer sk-laya-super-9f4a7c2e-ops-primary"}))

# ==================================================================
# Cell 9 — cloudflare tunnel to :8080 (prints PUBLIC URL)
# ==================================================================
# import subprocess, time
# p = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:8080"],
#                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
# time.sleep(12)
# for line in p.stdout:
#     if "trycloudflare.com" in line:
#         print(line.strip().split(" ")[-1])
#         break

# ==================================================================
# Your clients then call:
#   POST https://<tunnel>.trycloudflare.com/jevk5/v1/systemone
#   POST https://<tunnel>.trycloudflare.com/kev/v1/systemone
#   POST https://<tunnel>.trycloudflare.com/laya/v1/systemone   + Authorization: Bearer sk-laya-super-...
#
# Reminder: JevK5 questions use "criteria" (dict or list). Kev/Laya accept
# "options"/"criteria"/"levels". All three return {model, answers, usage, latency_ms}.
# ==================================================================