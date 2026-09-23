"""Small sample comparison: 1 customer_service case x 4 models (our 3 + kev).

Scores like system-one/evaluate.py (noul@0.5, score argmax, choice pick),
reports accuracy vs reference + latency + tokens + cost at Jev rate $0.042/M.
"""
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

DATA = json.loads(
    (Path(__file__).parent / "typesafe_full.json").read_text(encoding="utf-8")
)
CASE = DATA["workflows"]["customer_service"]["cases"][0]
KEY = "sk-laya-super-9f4a7c2e-ops-primary"
JEV = 0.042
TARGETS = [
    ("english", "http://127.0.0.1:8000", True),
    ("multilingual", "http://127.0.0.1:8000", True),
    ("typed-decisions", "http://127.0.0.1:8000", True),
    ("kev-latest", "http://127.0.0.1:8009", False),
]


def to_api_questions(case):
    qs = {}
    for q in case["questions"]:
        item = {"type": q["kind"], "instructions": q["text"]}
        if q["kind"] == "choice":
            item["criteria"] = (
                dict(zip(q["options"], q["descs"]))
                if q["descs"]
                else {o: o for o in q["options"]}
            )
        elif q["kind"] == "score":
            item["criteria"] = q["descs"] or q["options"]
        qs[q["qid"]] = item
    return qs


def predict(kind, ans):
    if kind == "noul":
        p = float(ans["noul"])
        return ("yes" if p >= 0.5 else "no"), max(p, 1 - p)
    probs = {str(k): float(v) for k, v in ans["probabilities"].items()}
    best = max(probs, key=probs.get)
    if kind == "score":
        best = str(int(round(float(best))))
    return best, probs[best]


def call(base, model, need_key, state, questions, timeout=300):
    payload = json.dumps({"model": model, "state": state, "questions": questions}).encode()
    hdrs = {"content-type": "application/json"}
    if need_key:
        hdrs["authorization"] = f"Bearer {KEY}"
    req = urllib.request.Request(f"{base}/v1/systemone", data=payload, headers=hdrs)
    t0 = time.perf_counter()
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
            wall = (time.perf_counter() - t0) * 1000
            return body, wall
        except Exception as e:
            last = e
            if attempt < 2:
                print(f"    retry after {e}; wait 30s")
                time.sleep(30)
    raise last


def main():
    api_q = to_api_questions(CASE)
    print(
        f"case={CASE['case_id']}  chars={CASE['state_chars']}  "
        f"questions={len(CASE['questions'])}  refs={len(CASE['questions'])}\n"
    )
    rows = []
    for model, base, need_key in TARGETS:
        try:
            body, wall = call(base, model, need_key, CASE["state"], api_q)
        except Exception as e:
            print(f"{model:<18} ERROR {e}")
            continue
        lat = float(body.get("latency_ms", wall))
        tok = int(body.get("usage", {}).get("input_tokens", 0))
        ok = n = 0
        detail = []
        for q in CASE["questions"]:
            ans = body["answers"].get(q["qid"])
            if ans is None:
                continue
            pred, conf = predict(q["kind"], ans)
            match = pred == q["ref_value"]
            ok += match
            n += 1
            mark = "+" if match else "X"
            detail.append(f"      {mark} {q['qid']:<32} pred={pred:<6} ref={q['ref_value']:<6} conf={conf:.2f}")
        acc = ok / n if n else 0
        cost = tok / 1e6 * JEV
        rows.append((model, acc, ok, n, lat, wall, tok, cost))
        print(f"{model:<18} acc={acc:.0%} ({ok}/{n})  lat={lat:.0f}ms  wall={wall:.0f}ms  "
              f"tok={tok}  ${cost:.5f} @jev-rate")
        for d in detail:
            print(d)
    if rows:
        print("\n" + "=" * 72)
        print(f"{'model':<18} {'acc':>6} {'lat ms':>8} {'wall ms':>9} {'tokens':>7} {'cost$':>8}")
        for m, acc, ok, n, lat, wall, tok, cost in rows:
            print(f"{m:<18} {acc:>6.0%} {lat:>8.0f} {wall:>9.0f} {tok:>7} {cost:>8.5f}")
    out = Path(__file__).parent / "sample_results.json"
    out.write_text(
        json.dumps(
            {
                "case": CASE["case_id"],
                "state_chars": CASE["state_chars"],
                "results": [
                    {"model": m, "acc": a, "ok": k, "n": n, "lat_ms": l,
                     "wall_ms": w, "tokens": t, "cost_jev": c}
                    for m, a, k, n, l, w, t, c in rows
                ],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
