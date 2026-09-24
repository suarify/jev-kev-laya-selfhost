"""JevK5 adapter: accepts Kev/Laya format (options/levels) AND native criteria,
adds CORS, forwards to the real JevK5 server on :8090. Runs on CPU kernel, 0 GPU.

  uvicorn jevk5_adapter:app --host 0.0.0.0 --port 8080
"""
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

JEVK5 = "http://127.0.0.1:8090"
app = FastAPI(title="JevK5 adapter")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5178"],
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
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