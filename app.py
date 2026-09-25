import os

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

import itertools
import random
import uuid
from functools import lru_cache
from time import perf_counter
from typing import Any

import torch
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
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

LAYA_RELEASE = "2026-01-01"


def require_api_key(
    authorization: str | None = Header(default=None, description="Bearer <super-key> (optional)"),
    x_api_key: str | None = Header(default=None, description="Alternative: X-API-Key header (optional)"),
) -> str:
    # Auth is optional: a valid key is still accepted if sent, but requests
    # without one are allowed (matches the open Kev default).
    token = ""
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if not token and x_api_key:
        token = x_api_key.strip()
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
        "Request/response wire-compatible with TypeSafe System One and jaredpalmer/kev: "
        "POST /v1/systemone with {model, state, questions} returns "
        "{model, answers, usage, latency_ms}."
    ),
    version="3.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


class PermuteRequest(BaseModel):
    request: DecideRequest
    question: str = Field(..., description="Id of one choice question inside request.questions")
    n_perm: int = Field(default=6, ge=1, le=64, description="Number of option orders to run")


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


def _stamp(response: Response) -> None:
    response.headers["x-typesafe-request-id"] = uuid.uuid4().hex


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "device": DEVICE,
        "preload": PRELOAD,
        "torch_threads": THREADS,
    }


def _normalize_state(state: Any) -> Any:
    if isinstance(state, str):
        return {"body": state}
    if isinstance(state, list):
        return {"items": state}
    return state


def _resolve_model(model: str | None) -> dict[str, Any]:
    requested = (model or "").strip()
    if requested and requested not in AUTO_MODEL_ALIASES and requested not in CHECKPOINTS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown model '{requested}'; use laya-latest, english, multilingual, or typed-decisions",
        )
    kwargs: dict[str, Any] = {}
    if requested in CHECKPOINTS:
        kwargs["model"] = requested
    effective = requested if requested in CHECKPOINTS else "laya-latest"
    return {"kwargs": kwargs, "effective": effective}


def _run_predict(state: Any, questions: dict[str, Any], kwargs: dict[str, Any]) -> tuple[dict[str, Any], float]:
    router = get_router()
    t0 = perf_counter()
    try:
        result = router.predict(state, questions, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result, (perf_counter() - t0) * 1000


def _envelope(effective: str, answers: dict[str, Any], usage: dict[str, Any], latency_ms: float,
              routing: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": effective,
        "answers": answers,
        "usage": usage,
        "latency_ms": round(latency_ms, 1),
    }
    if routing:
        payload["routing"] = routing
    return payload


def _decide(req: DecideRequest, response: Response) -> dict[str, Any]:
    _stamp(response)
    plan = _resolve_model(req.model)
    state = _normalize_state(req.state)
    result, latency_ms = _run_predict(state, req.questions, plan["kwargs"])
    return _envelope(
        plan["effective"],
        result.get("answers", {}),
        result.get("usage", {}),
        latency_ms,
        result.get("routing"),
    )


@app.post("/v1/systemone", dependencies=[Depends(require_api_key)])
def systemone(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide(req, response)


def _format_v2_answer(answer: dict[str, Any]) -> dict[str, Any]:
    """Reformat one Laya answer to the Jev browser-use (/v2) shape.

    - drops the `action` block
    - noul -> {type, noul} (no confidence)
    - choice -> {type, choice, confidence, probabilities}
    - score -> {type, score, confidence, legend:{idx:{what}}, probabilities}
    """
    kind = answer.get("type")
    out: dict[str, Any] = {"type": kind}
    if kind == "noul":
        out["noul"] = answer.get("noul")
    else:
        if "confidence" in answer:
            out["confidence"] = answer.get("confidence")
    if kind == "choice":
        out["choice"] = answer.get("choice")
        out["probabilities"] = answer.get("probabilities") or {}
    elif kind == "score":
        out["score"] = answer.get("score")
        legend = answer.get("legend") or {}
        out["legend"] = {str(k): {"what": v} if isinstance(v, str) else v for k, v in legend.items()}
        out["probabilities"] = answer.get("probabilities") or {}
    return out


def _resolve_model_v2(model: str | None) -> dict[str, Any]:
    """v2 model resolution: tolerate unknown names (Jev clients send jev-1.13.0) by echoing them back and
    routing to the default checkpoint instead of 422. v1 keeps the strict check."""
    requested = (model or "").strip()
    if not requested:
        return {"kwargs": {}, "effective": "laya-latest"}
    try:
        return _resolve_model(requested)
    except HTTPException:
        return {"kwargs": {}, "effective": requested}


def _decide_v2(req: DecideRequest, response: Response) -> dict[str, Any]:
    _stamp(response)
    plan = _resolve_model_v2(req.model)
    state = _normalize_state(req.state)
    result, latency_ms = _run_predict(state, req.questions, plan["kwargs"])
    answers = {
        qid: _format_v2_answer(a)
        for qid, a in (result.get("answers") or {}).items()
        if isinstance(a, dict)
    }
    payload: dict[str, Any] = {
        "model": plan["effective"],
        "answers": answers,
        "usage": result.get("usage", {}),
        "latency_ms": round(latency_ms, 1),
    }
    routing = result.get("routing")
    if routing:
        payload["routing"] = routing
    return payload


@app.post("/v2/systemone", dependencies=[Depends(require_api_key)])
def systemone_v2(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide_v2(req, response)


@app.post("/v2/decide", dependencies=[Depends(require_api_key)])
def decide_v2(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide_v2(req, response)


@app.post("/v1/systemone/separate", dependencies=[Depends(require_api_key)])
def systemone_separate(req: DecideRequest, response: Response) -> dict[str, Any]:
    _stamp(response)
    plan = _resolve_model(req.model)
    state = _normalize_state(req.state)

    merged: dict[str, Any] = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    total_ms = 0.0
    for qid, question in req.questions.items():
        result, ms = _run_predict(state, {qid: question}, plan["kwargs"])
        merged.update(result.get("answers", {}))
        u = result.get("usage", {}) or {}
        usage["input_tokens"] += int(u.get("input_tokens", 0) or 0)
        usage["output_tokens"] += int(u.get("output_tokens", 0) or 0)
        total_ms += ms

    routing = None
    try:
        route_decision = get_router().route(state, {})
        routing = {
            "model": getattr(route_decision, "model", None),
            "repo": getattr(route_decision, "repo", None),
            "reason": getattr(route_decision, "reason", None),
        }
    except Exception:
        pass
    return _envelope(plan["effective"], merged, usage, total_ms, routing)


def _choice_orders(options: list[str], n_perm: int) -> list[list[str]]:
    if len(options) <= 8:
        all_perms = list(itertools.permutations(options))
        if n_perm >= len(all_perms):
            orders = [list(p) for p in all_perms]
            random.shuffle(orders)
            return orders[:n_perm] if n_perm < len(orders) else orders
        return [list(p) for p in random.sample(all_perms, n_perm)]
    orders: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    attempts = 0
    while len(orders) < n_perm and attempts < n_perm * 20:
        candidate = options.copy()
        random.shuffle(candidate)
        key = tuple(candidate)
        attempts += 1
        if key not in seen or attempts > n_perm * 10:
            seen.add(key)
            orders.append(candidate)
    return orders


@app.post("/v1/systemone/permute", dependencies=[Depends(require_api_key)])
def systemone_permute(req: PermuteRequest, response: Response) -> dict[str, Any]:
    _stamp(response)
    inner = req.request
    if req.question not in inner.questions:
        raise HTTPException(status_code=422, detail=f"question '{req.question}' not found in request.questions")
    question = inner.questions[req.question]
    if not isinstance(question, dict) or question.get("type") != "choice":
        raise HTTPException(status_code=422, detail="permute only supports a choice-type question")
    criteria = question.get("criteria") or {}
    if not isinstance(criteria, dict) or len(criteria) < 2:
        raise HTTPException(status_code=422, detail="choice criteria must be a dict with >= 2 options")

    plan = _resolve_model(inner.model)
    state = _normalize_state(inner.state)
    options = list(criteria.keys())
    orders = _choice_orders(options, max(1, min(req.n_perm, 64)))
    if not orders:
        raise HTTPException(status_code=422, detail="could not generate option orders")

    runs: list[dict[str, Any]] = []
    per_option: dict[str, list[float]] = {opt: [] for opt in options}
    choices_seen: list[str] = []
    for order in orders:
        shuffled_criteria = {opt: criteria[opt] for opt in order}
        permuted_question = {**question, "criteria": shuffled_criteria}
        result, ms = _run_predict(state, {req.question: permuted_question}, plan["kwargs"])
        answer = (result.get("answers") or {}).get(req.question, {})
        probabilities = answer.get("probabilities") or {}
        choice = answer.get("choice")
        runs.append(
            {
                "order": order,
                "probabilities": probabilities,
                "choice": choice,
                "latency_ms": round(ms, 1),
            }
        )
        choices_seen.append(choice)
        for opt in options:
            per_option[opt].append(float(probabilities.get(opt, 0.0)))

    spread = {opt: round(max(vals) - min(vals), 6) for opt, vals in per_option.items() if vals}
    return {
        "runs": runs,
        "argmax_stable": len(set(choices_seen)) == 1,
        "spread": spread,
    }


def _model_entry(name: str, description: str, run: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "release_date": LAYA_RELEASE,
        "run": run,
        "base": "ModernBERT-large",
        "lora": None,
        "device": DEVICE,
        "backend": "torch",
        "dtype": "float32" if DEVICE == "cpu" else "bfloat16",
        "temperature": None,
        "prefix_cache": None,
    }


@app.get("/v1/models", dependencies=[Depends(require_api_key)])
def models(response: Response) -> dict[str, Any]:
    _stamp(response)
    entries = [
        _model_entry(
            "laya-latest",
            "convaiinnovations/laya with automatic per-request checkpoint routing",
            "convaiinnovations/laya",
        )
    ]
    for ckpt in sorted(CHECKPOINTS):
        entries.append(
            _model_entry(
                ckpt,
                f"pinned checkpoint '{ckpt}' of convaiinnovations/laya",
                f"convaiinnovations/laya:{ckpt}",
            )
        )
    return {"models": entries}


# Laya-only extras (Kev parity endpoints are above)
@app.post("/v1/decide", dependencies=[Depends(require_api_key)])
def decide_v1(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide(req, response)


@app.post("/predict", dependencies=[Depends(require_api_key)])
def predict(req: DecideRequest, response: Response) -> dict[str, Any]:
    return _decide(req, response)


@app.post("/route", dependencies=[Depends(require_api_key)])
def route(req: RouteRequest, response: Response) -> dict[str, Any]:
    _stamp(response)
    state = _normalize_state(req.state)
    router = get_router()
    try:
        decision = router.route(state, req.questions)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "model": getattr(decision, "model", None),
        "repo": getattr(decision, "repo", None),
        "reason": getattr(decision, "reason", None),
    }
