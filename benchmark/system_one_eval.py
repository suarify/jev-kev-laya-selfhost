"""System-One-style TypeSafe eval: our 3 Laya checkpoints vs published baselines.

Methodology follows system-one/evaluate.py (typesafe slice):
  - 20 cases / ~372 reference pairs from evals.typesafe.ai (4 workflows)
  - noul: yes iff p >= 0.5   ·   score: argmax level   ·   choice: picked option
  - accuracy overall / by kind / by workflow, ECE, latency median+p90
  - cost: input tokens priced at TypeSafe Jev published rate $0.042 / M tokens
          + wall-clock time on this machine

Models under test (our 3, pinned checkpoints of convaiinnovations/laya):
  english | multilingual | typed-decisions

Usage:
  python benchmark/system_one_eval.py [--base http://127.0.0.1:8000] [--cap 0]
"""
import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
EVAL = HERE / "typesafe_full.json"
OUT_JSON = HERE / "system_one_results.json"
OUT_MD = HERE / "SYSTEM_ONE_REPORT.md"

API_KEY = "sk-laya-super-9f4a7c2e-ops-primary"
MODELS = ["english", "multilingual", "typed-decisions"]
JEV_RATE_PER_M = 0.042  # TypeSafe published price, $ per 1M input tokens


def post_systemone(base, model, state, questions, timeout=600, retries=3):
    payload = json.dumps(
        {"model": model, "state": state, "questions": questions}
    ).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            f"{base}/v1/systemone",
            data=payload,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {API_KEY}",
            },
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            wall_ms = (time.perf_counter() - t0) * 1000
            return body, wall_ms
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries - 1:
                print(f"    retry {attempt + 1}/{retries - 1} after {e!r}; waiting 45s")
                time.sleep(45)
    raise last_err


def to_api_questions(case):
    """Map system-one question format -> Laya criteria format."""
    qs = {}
    for q in case["questions"]:
        item = {"type": q["kind"], "instructions": q["text"]}
        if q["kind"] == "choice":
            if isinstance(q["descs"], list) and any(q["descs"]):
                item["criteria"] = dict(zip(q["options"], q["descs"]))
            else:
                item["criteria"] = {o: o for o in q["options"]}
        elif q["kind"] == "score":
            item["criteria"] = q["descs"] if q["descs"] else [o for o in q["options"]]
        else:  # noul
            if isinstance(q["descs"], list) and len(q["descs"]) == 2 and any(q["descs"]):
                item["criteria"] = {"false": q["descs"][0], "true": q["descs"][1]}
        qs[q["qid"]] = item
    return qs


def predict(kind, ans):
    """Return (pred:str, conf:float) using system-one scoring rules."""
    if kind == "noul":
        p = float(ans["noul"])
        return ("yes" if p >= 0.5 else "no"), max(p, 1 - p)
    if kind == "score":
        probs = {str(k): float(v) for k, v in ans["probabilities"].items()}
        best = max(probs, key=probs.get)
        return str(int(round(float(best)))), probs[best]
    probs = {str(k): float(v) for k, v in ans["probabilities"].items()}
    best = max(probs, key=probs.get)
    return best, probs[best]


def ece(conf, ok, n_bins=10):
    if not conf:
        return float("nan")
    bins = [[] for _ in range(n_bins)]
    for c, o in zip(conf, ok):
        bins[min(n_bins - 1, int(c * n_bins))].append((c, float(o)))
    total = len(conf)
    e = 0.0
    for b in bins:
        if not b:
            continue
        acc = sum(o for _, o in b) / len(b)
        cf = sum(c for c, _ in b) / len(b)
        e += (len(b) / total) * abs(acc - cf)
    return e


def pct(x):
    return f"{100 * x:.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--cap", type=int, default=0, help="max cases per workflow (0=all)")
    args = ap.parse_args()

    data = json.loads(EVAL.read_text(encoding="utf-8"))
    rows = []  # per answered pair
    per_model = {
        m: {"lat_ms": [], "wall_ms": [], "input_tokens": 0, "cases": 0, "errors": 0}
        for m in MODELS
    }

    cases_list = []
    for wf, d in data["workflows"].items():
        for c in d["cases"]:
            if args.cap and len([x for x in cases_list if x[0] == wf]) >= args.cap:
                break
            cases_list.append((wf, c))

    total_calls = len(cases_list) * len(MODELS)
    print(f"{len(cases_list)} cases x {len(MODELS)} models = {total_calls} calls")
    call_i = 0
    t_run0 = time.perf_counter()

    for wf, case in cases_list:
        api_q = to_api_questions(case)
        for model in MODELS:
            call_i += 1
            try:
                body, wall = post_systemone(args.base, model, case["state"], api_q)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                print(f"  [{call_i}/{total_calls}] {model} {wf}/{case['case_id']} ERROR {e}")
                per_model[model]["errors"] += 1
                continue
            per_model[model]["lat_ms"].append(float(body.get("latency_ms", wall)))
            per_model[model]["wall_ms"].append(wall)
            per_model[model]["input_tokens"] += int(body.get("usage", {}).get("input_tokens", 0))
            per_model[model]["cases"] += 1
            for q in case["questions"]:
                ans = body["answers"].get(q["qid"])
                if ans is None:
                    continue
                pred, conf = predict(q["kind"], ans)
                rows.append(
                    {
                        "model": model,
                        "wf": wf,
                        "case": case["case_id"],
                        "qid": q["qid"],
                        "kind": q["kind"],
                        "pred": pred,
                        "ref": q["ref_value"],
                        "ok": pred == q["ref_value"],
                        "conf": conf,
                    }
                )
            if call_i % 5 == 0 or call_i == total_calls:
                print(
                    f"  [{call_i}/{total_calls}] {model} {wf}/{case['case_id']} "
                    f"{wall:.0f}s  elapsed {time.perf_counter()-t_run0:.0f}s",
                    flush=True,
                )

    wall_total = time.perf_counter() - t_run0

    # ---- summaries per model ----
    summary = {}
    for m in MODELS:
        rs = [r for r in rows if r["model"] == m]
        if not rs:
            summary[m] = {"n": 0}
            continue
        by_kind = {}
        for k in ("choice", "score", "noul"):
            kr = [r for r in rs if r["kind"] == k]
            if kr:
                by_kind[k] = {"acc": sum(r["ok"] for r in kr) / len(kr), "n": len(kr)}
        by_wf = {}
        for wf in data["workflows"]:
            wr = [r for r in rs if r["wf"] == wf]
            if wr:
                by_wf[wf] = {"acc": sum(r["ok"] for r in wr) / len(wr), "n": len(wr)}
        conf = [r["conf"] for r in rs]
        ok = [r["ok"] for r in rs]
        lat = per_model[m]["lat_ms"]
        tokens = per_model[m]["input_tokens"]
        summary[m] = {
            "n": len(rs),
            "acc": sum(ok) / len(rs),
            "ece": ece(conf, ok),
            "by_kind": by_kind,
            "by_wf": by_wf,
            "lat_median_ms": statistics.median(lat) if lat else None,
            "lat_p90_ms": (sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else None),
            "lat_mean_ms": statistics.fmean(lat) if lat else None,
            "wall_s": sum(per_model[m]["wall_ms"]) / 1000,
            "input_tokens": tokens,
            "cost_jev_rate": tokens / 1e6 * JEV_RATE_PER_M,
            "errors": per_model[m]["errors"],
        }

    # ---- baselines (system-one style): per-type & per-question majority over refs ----
    from collections import Counter

    all_rows_no_model = [r for r in rows if r["model"] == MODELS[0]]  # refs identical
    maj_type = {
        k: Counter(r["ref"] for r in all_rows_no_model if r["kind"] == k).most_common(1)[0][0]
        for k in ("choice", "score", "noul")
    }
    baselines = {}
    for k, mv in maj_type.items():
        kr = [r for r in all_rows_no_model if r["kind"] == k]
        baselines[f"majority_{k}"] = {
            "value": mv,
            "acc": sum(r["ref"] == mv for r in kr) / len(kr),
            "n": len(kr),
        }

    # published models on the same pairs (from eval data)
    published = {}
    for pub in ("opus", "sol", "typesafe"):
        n_ok = n = 0
        for _, case in cases_list:
            for q in case["questions"]:
                v = case["published"].get(pub, {}).get(q["qid"])
                if v is None:
                    continue
                n += 1
                n_ok += v == q["ref_value"]
        if n:
            published[pub] = {"acc": n_ok / n, "n": n_ok, "den": n}

    result = {
        "meta": {
            "date": time.strftime("%Y-%m-%d"),
            "eval": "TypeSafe public eval via system-one approach",
            "workflows": list(data["workflows"]),
            "cases": len(cases_list),
            "models": MODELS,
            "jev_rate_per_m": JEV_RATE_PER_M,
            "wall_total_s": round(wall_total, 1),
            "base": args.base,
        },
        "models": summary,
        "baselines": baselines,
        "published": published,
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(result, indent=1), encoding="utf-8")

    # ---- console ----
    print("\n" + "=" * 78)
    print("SYSTEM-ONE STYLE TYPESAFE EVAL — our 3 Laya checkpoints")
    print("=" * 78)
    print(f"{'model':<18} {'acc':>7} {'ECE':>6} {'med ms':>8} {'p90 ms':>8} {'Mtok':>7} {'$@jev':>8}")
    for m in MODELS:
        s = summary[m]
        if not s.get("n"):
            print(f"{m:<18} ERROR no rows")
            continue
        print(
            f"{m:<18} {pct(s['acc']):>7} {s['ece']:>6.3f} "
            f"{s['lat_median_ms']:>8.0f} {s['lat_p90_ms']:>8.0f} "
            f"{s['input_tokens']/1e6:>7.3f} {s['cost_jev_rate']:>8.4f}"
        )
    print("\nby kind:")
    for m in MODELS:
        s = summary[m]
        if not s.get("n"):
            continue
        ks = "  ".join(
            f"{k}={pct(v['acc'])}({v['n']})" for k, v in s["by_kind"].items()
        )
        print(f"  {m:<18} {ks}")
    print("\npublished (same pairs):")
    for pub, v in published.items():
        print(f"  {pub:<12} {pct(v['acc'])}  ({v['n']}/{v['den']})")
    print("\nbaselines:")
    for name, v in baselines.items():
        print(f"  {name:<22} {pct(v['acc'])}")
    print(f"\nwall total: {wall_total:.0f}s   rows: {len(rows)}   -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
