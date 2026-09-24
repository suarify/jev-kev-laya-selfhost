# Kaggle notebook — host Laya (:8000) + Kev (:8009) as one API via cloudflare tunnel
#
# For training/testing only. Session dies after ~12h / on close; tunnel URL changes each restart.
#
# Setup:
#   New notebook -> Settings -> Accelerator: "GPU T4 x2"   Internet: ON
#   Paste cells below in order. Last cell prints the public URL(s).

# ==================================================================
# Cell 1 — install Laya + Kev + server deps
# ==================================================================
# !pip -q install "laya>=0.3.6" "fastapi" "uvicorn" "httpx"
# !pip -q install "torch>=2.6,<2.9" "transformers>=5.17,<6" "peft>=0.21" "accelerate>=1.15" "typesafe-sdk>=0.6.0" "scikit-learn" "datasets"
# !git clone --depth 1 https://github.com/jaredpalmer/kev /kaggle/working/kev
# !cd /kaggle/working/kev && pip -q install -e .
# !pip -q install cloudflared

# ==================================================================
# Cell 2 — bring your app.py (Laya wrapper, already has CORS) into the notebook
# ==================================================================
# Create /kaggle/working/app.py with your repo's app.py (the one with SUPER_KEYS + CORSMiddleware).
# Quick way: upload it as a Dataset, then:
# import shutil; shutil.copy('/kaggle/input/<your-dataset>/app.py', '/kaggle/working/app.py')

# ==================================================================
# Cell 3 — launch Laya (GPU) on :8000 and Kev on :8009
# ==================================================================
import os, threading, subprocess

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ["LAYA_DEVICE"] = "cuda"
os.environ["LAYA_PRELOAD"] = "1"
os.environ["LAYA_MAX_LOADED"] = "3"

def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True)

threading.Thread(target=_run, args=(
    ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"],
    "/kaggle/working"), daemon=True).start()

threading.Thread(target=_run, args=(
    ["python", "-m", "kev.serve", "--run", "jaredpalmer/kev-0.6b", "--port", "8009"],
    "/kaggle/working/kev"), daemon=True).start()

print("servers launching...")

# ==================================================================
# Cell 4 — fan-out proxy: single URL, both models
#   GET/POST /laya/*  -> :8000   (Laya)
#   GET/POST /kev/*   -> :8009   (Kev)
# Paths under the prefix are forwarded verbatim, so your client calls:
#   POST {tunnel}/laya/v1/systemone   (with Authorization: Bearer sk-laya-...)
#   POST {tunnel}/kev/v1/systemone
# ==================================================================
PROXY_CODE = r'''
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

proxy = FastAPI()
client = httpx.AsyncClient(timeout=120)

@proxy.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def route(service: str, path: str, request: Request):
    base = {"laya": "http://127.0.0.1:8000", "kev": "http://127.0.0.1:8009"}.get(service)
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
# Cell 5 — start the proxy on :8080 + cloudflare tunnel to it
# ==================================================================
# write proxy code to a file and run it
with open("/kaggle/working/proxy.py", "w") as f:
    f.write(PROXY_CODE)

threading.Thread(target=_run, args=(
    ["uvicorn", "proxy:proxy", "--host", "0.0.0.0", "--port", "8080"],
    "/kaggle/working"), daemon=True).start()

print("proxy starting on :8080 ...")

# ==================================================================
# Cell 6 — cloudflare tunnel to :8080 (prints the PUBLIC URL)
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
# Cell 7 — quick local sanity check (run this BEFORE the tunnel)
# ==================================================================
# import httpx, time
# time.sleep(20)  # let models load
# r = httpx.post("http://127.0.0.1:8000/v1/systemone",
#                headers={"Authorization": "Bearer sk-laya-super-9f4a7c2e-ops-primary",
#                         "Content-Type": "application/json"},
#                json={"state": "hi", "questions": {"q": {"type": "choice", "instructions": "?",
#                                                         "options": ["a", "b"]}}})
# print("laya:", r.status_code, r.json().get("answers"))
# r2 = httpx.post("http://127.0.0.1:8009/v1/systemone",
#                 json={"state": "hi", "questions": {"q": {"type": "choice", "instructions": "?",
#                                                          "options": ["a", "b"]}}})
# print("kev :", r2.status_code, r2.json().get("answers"))