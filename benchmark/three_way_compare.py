"""3-way small-sample: System-One (live Modal) vs Laya (:8000) vs Kev (:8009).

Reuses the earlier EN sample cases from benchmark/cases.json (laya-vs-kev suite),
adds the system-one replica as third arm. Reports per-question values,
3-way agreement, latency, and cost.

Cost model:
  laya/kev  : input_tokens x $0.042/M (TypeSafe published rate, normalized)
  system-one: GPU-seconds on L4 @ $0.80/hr  (their serve.py GPU_RATE)
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

CASES_PATH = Path(__file__).parent / "cases.json"
OUT_PATH = Path(__file__).parent / "three_way_results.json"

LAYA = "http://127.0.0.1:8000"
KEV = "http://127.0.0.1:8009"
S1 = "https://mithalouni--jev-serve-e2b-full-server-web.modal.run"
API_KEY = "sk-laya-super-9f4a7c2e-ops-primary"
JEV_RATE = 0.042  # $/M tokens
L4_RATE = 0.80  # $/hr GPU

IDS = ["en-support-mixed", "en-inbox-triage"]


def post(url, payload, headers=None, timeout=300):
    hdrs = {"content-type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=hdrs, method="POST"
    )
    t0 = time.perf_counter()
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
            return body, (time.perf_counter() - t0) * 1000
        except Exception as e:
            last = e
            if attempt < 2:
                print(f"    retry after {e!r}; wait 30s")
                time.sleep(30)
    raise last


def to_dict_questions(case):
    """cases.json already stores questions as {id: {...}} (laya/kev shape)."""
    return case["questions"]


def to_list_questions(case):
    """system-one /decide shape: [{id, type, instructions, options|levels|criteria}]."""
    qs = []
    for qid, q in case["questions"].items():
        item = {"id": qid, "type": q["type"], "instructions": q["instructions"]}
        if q["type"] == "choice":
            item["options"] = q["criteria"]
        elif q["type"] == "score":
            item["levels"] = q["criteria"]
        elif "criteria" in q:
            item["criteria"] = q["criteria"]
        qs.append(item)
    return qs


def answers_to_dict(raw):
    """system-one returns answers as a list; laya/kev as a dict."""
    if isinstance(raw, dict):
        return raw
    return {a["id"]: a for a in raw}


def fmt(kind, a):
    if a is None:
        return "n/a"
    if kind == "choice":
        return str(a.get("choice"))
    if kind == "noul":
        return f"{float(a.get('noul', 0)):.2f}"
    probs = a.get("probabilities") or {}
    if probs:
        best = max(probs, key=lambda k: float(probs[k]))
        return f"{float(a.get('score', best)):.2f} (top {best})"
    return f"{float(a.get('score', 0)):.2f}"


def main():
    all_cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = [c for c in all_cases if c["id"] in IDS]
    print(f"3-way sample: {', '.join(c['id'] for c in cases)}")
    print(f"system-one: {S1}\n")

    # wake system-one (cold ~60s)
    t0 = time.perf_counter()
    req = urllib.request.Request(f"{S1}/info")
    with urllib.request.urlopen(req, timeout=120) as r:
        info = json.loads(r.read())
    print(f"system-one /info: {info['model']} device={info['device']} wake={time.perf_counter()-t0:.0f}s\n")

    results = []
    agreement = {"choice_all3": [0, 0], "noul_close3": [0, 0], "score_close3": [0, 0]}

    for case in cases:
        print("=" * 78)
        print(f"CASE {case['id']} — {case['title']}")
        print("=" * 78)
        state = case["state"]
        row = {"id": case["id"], "systems": {}}

        # --- Laya ---
        try:
            lb, lw = post(
                f"{LAYA}/v1/systemone",
                {"model": "laya-latest", "state": state, "questions": to_dict_questions(case)},
                {"authorization": f"Bearer {API_KEY}"},
            )
            row["systems"]["laya"] = {
                "ok": True,
                "lat_ms": lb.get("latency_ms", lw),
                "wall_ms": lw,
                "tokens": lb.get("usage", {}).get("input_tokens", 0),
                "answers": lb["answers"],
                "routing": lb.get("routing", {}).get("model"),
            }
        except Exception as e:
            row["systems"]["laya"] = {"ok": False, "error": str(e)}
            print(f"  LAYA ERROR {e}")

        # --- Kev ---
        try:
            kb, kw = post(
                f"{KEV}/v1/systemone",
                {"model": "kev-latest", "state": state, "questions": to_dict_questions(case)},
            )
            row["systems"]["kev"] = {
                "ok": True,
                "lat_ms": kb.get("latency_ms", kw),
                "wall_ms": kw,
                "tokens": kb.get("usage", {}).get("input_tokens", 0),
                "answers": kb["answers"],
            }
        except Exception as e:
            row["systems"]["kev"] = {"ok": False, "error": str(e)}
            print(f"  KEV ERROR {e}")

        # --- System-One ---
        try:
            sb, sw = post(
                f"{S1}/decide",
                {"state": state, "questions": to_list_questions(case), "max_state_tokens": 4096},
            )
            s_answers = answers_to_dict(sb.get("answers", []))
            s_lat = float(sb.get("latency_ms", sw))
            row["systems"]["system-one"] = {
                "ok": True,
                "lat_ms": s_lat,
                "wall_ms": sw,
                "tokens": None,  # /decide does not report tokens
                "answers": s_answers,
                "model": sb.get("model"),
                "cost_gpu": s_lat / 1000 * L4_RATE / 3600,
            }
        except Exception as e:
            row["systems"]["system-one"] = {"ok": False, "error": str(e)}
            print(f"  S1 ERROR {e}")

        # --- per-question comparison ---
        for qid, q in case["questions"].items():
            kind = q["type"]
            vals = {}
            for sys in ("laya", "kev", "system-one"):
                s = row["systems"].get(sys, {})
                vals[sys] = fmt(kind, s.get("answers", {}).get(qid)) if s.get("ok") else "ERR"
            mark = ""
            la = row["systems"].get("laya", {}).get("answers", {}).get(qid)
            ka = row["systems"].get("kev", {}).get("answers", {}).get(qid)
            sa = row["systems"].get("system-one", {}).get("answers", {}).get(qid)
            if la and ka and sa:
                if kind == "choice":
                    same = la.get("choice") == ka.get("choice") == sa.get("choice")
                    agreement["choice_all3"][1] += 1
                    agreement["choice_all3"][0] += int(same)
                    mark = "3-SAME" if same else "SPLIT"
                elif kind == "noul":
                    xs = [float(la["noul"]), float(ka["noul"]), float(sa["noul"])]
                    close = max(xs) - min(xs) < 0.30
                    agreement["noul_close3"][1] += 1
                    agreement["noul_close3"][0] += int(close)
                    mark = "3-CLOSE" if close else "GAP"
                else:
                    xs = [float(la.get("score", 0)), float(ka.get("score", 0)), float(sa.get("score", 0))]
                    close = max(xs) - min(xs) < 0.50
                    agreement["score_close3"][1] += 1
                    agreement["score_close3"][0] += int(close)
                    mark = "3-CLOSE" if close else "SPLIT"
            print(f"  [{kind:<6}] {qid:<26} laya={vals['laya']:<22} kev={vals['kev']:<22} s1={vals['system-one']:<22} {mark}")
        results.append(row)
        print()

    # --- summary ---
    print("=" * 78)
    print("LATENCY / COST")
    print("=" * 78)
    print(f"{'system':<14} {'lat ms':>9} {'tokens':>8} {'cost$':>10}  notes")
    for row in results:
        for sys in ("laya", "kev", "system-one"):
            s = row["systems"].get(sys, {})
            if not s.get("ok"):
                print(f"{sys:<14} {'ERROR':>9}")
                continue
            if sys == "system-one":
                cost = s["cost_gpu"]
                note = f"GPU L4 @ $0.80/h · {row['id']}"
                tok = "-"
            else:
                cost = s["tokens"] / 1e6 * JEV_RATE
                tok = str(s["tokens"])
                note = f"@jev-rate · {row['id']}" + (f" · ckpt={s.get('routing')}" if sys == "laya" else "")
            print(f"{sys:<14} {s['lat_ms']:>9.0f} {tok:>8} {cost:>10.5f}  {note}")

    print("\n3-WAY AGREEMENT (both cases)")
    for k, (ok, n) in agreement.items():
        print(f"  {k:<14} {ok}/{n}" if n else f"  {k:<14} n/a")

    OUT_PATH.write_text(json.dumps({"results": results, "agreement": agreement}, indent=1), encoding="utf-8")
    print(f"\n-> {OUT_PATH}")


if __name__ == "__main__":
    main()
