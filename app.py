import os

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

from functools import lru_cache
from time import perf_counter
from typing import Any

import torch
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from laya import Router

DEVICE = os.environ.get("LAYA_DEVICE", "cpu")
PRELOAD = os.environ.get("LAYA_PRELOAD", "1") == "1"
MAX_LOADED = int(os.environ.get("LAYA_MAX_LOADED", "2"))
THREADS = int(os.environ.get("TORCH_NUM_THREADS", "8"))

# 3 hardcoded super keys — exactly one must be sent on every decision request
SUPER_KEYS = {
    "sk-laya-super-9f4a7c2e-ops-primary",
    "sk-laya-super-3b8d1e6a-batch-worker",
    "sk-laya-super-c7f20a95-readonly-demo",
}

# request "model" values that mean "auto-route" (aliases let Jev clients drop in)
AUTO_MODEL_ALIASES = {"laya-latest", "laya", "auto", "jev-latest", "jev", ""}
CHECKPOINTS = {"english", "multilingual", "typed-decisions"}


def require_api_key(
    authorization: str | None = Header(default=None, description="Bearer <super-key>"),
    x_api_key: str | None = Header(default=None, description="Alternative: X-API-Key header"),
) -> str:
    token = ""
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if not token and x_api_key:
        token = x_api_key.strip()
    if token not in SUPER_KEYS:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key. Send Authorization: Bearer <super-key> or X-API-Key: <super-key>.",
        )
    return token

torch.set_num_threads(THREADS)
if hasattr(torch, "set_num_interop_threads"):
    try:
        torch.set_num_interop_threads(max(1, THREADS // 2))
    except RuntimeError:
        pass

app = FastAPI(
    title="Laya API",
    description=(
        "Non-autoregressive System 1 decision model (convaiinnovations/laya). "
        "Jev-compatible request/response format: POST /v1/decide with {model, state, questions} "
        "returns {model, answers, usage}."
    ),
    version="2.0.0",
)


class DecideRequest(BaseModel):
    model: str = Field(
        default="laya-latest",
        description=(
            "Checkpoint override: english | multilingual | typed-decisions. "
            "laya-latest (default) auto-routes per request."
        ),
    )
    state: dict[str, Any] | list[Any] | str = Field(
        ..., description="Text, email, ticket or JSON state (string is wrapped as {body})"
    )
    questions: dict[str, Any] = Field(..., description="Typed questions (choice/score/noul)")


class RouteRequest(BaseModel):
    state: dict[str, Any] | list[Any] | str
    questions: dict[str, Any] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def get_router() -> Router:
    router = Router(preload=PRELOAD, device=DEVICE, max_loaded=MAX_LOADED)
    if PRELOAD:
        try:
            router.preload(["english", "multilingual"])
        except Exception:
            pass
    return router


@app.on_event("startup")
def _startup() -> None:
    get_router()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "device": DEVICE,
        "preload": PRELOAD,
        "torch_threads": THREADS,
    }


def _decide(req: DecideRequest, response: Response) -> dict[str, Any]:
    router = get_router()

    requested = (req.model or "").strip()
    if requested and requested not in AUTO_MODEL_ALIASES and requested not in CHECKPOINTS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown model '{requested}'; use laya-latest, english, multilingual, or typed-decisions",
        )

    kwargs: dict[str, Any] = {}
    if requested in CHECKPOINTS:
        kwargs["model"] = requested

    # laya expects a mapping; Jev allows a bare string/array state
    state: Any = req.state
    if isinstance(state, str):
        state = {"body": state}
    elif isinstance(state, list):
        state = {"items": state}

    t0 = perf_counter()
    try:
        result = router.predict(state, req.questions, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # latency lives in a header so the body stays Jev-compatible
    response.headers["X-Latency-Ms"] = f"{(perf_counter() - t0) * 1000:.1f}"

    effective = requested if requested in CHECKPOINTS else "laya-latest"

    # Jev-compatible envelope: {model, answers, usage} + routing (Laya extra)
    payload: dict[str, Any] = {
        "model": effective,
        "answers": result.get("answers", {}),
        "usage": result.get("usage", {}),
    }
    if "routing" in result:
        payload["routing"] = result["routing"]
    return payload


@app.post("/v1/decide", dependencies=[Depends(require_api_key)])
def decide_v1(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide(req, response)


# alias: official TypeSafe path shape, for drop-in client swaps
@app.post("/v1/systemone", dependencies=[Depends(require_api_key)])
def decide_systemone(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide(req, response)


# legacy alias
@app.post("/predict", dependencies=[Depends(require_api_key)])
def predict(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide(req, response)


@app.post("/route", dependencies=[Depends(require_api_key)])
def route(req: RouteRequest) -> dict[str, Any]:
    router = get_router()
    state: Any = req.state
    if isinstance(state, str):
        state = {"body": state}
    elif isinstance(state, list):
        state = {"items": state}
    try:
        decision = router.route(state, req.questions)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "model": getattr(decision, "model", None),
        "repo": getattr(decision, "repo", None),
        "reason": getattr(decision, "reason", None),
    }
