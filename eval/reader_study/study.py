"""Reader-study logic: assignment, auto-scoring, aggregation. Pure, stdlib, deterministic.

The web form (app/portal.py -> app/web.study_form_html) collects a participant's answers across
their assigned cases; POST /api/study scores the OBJECTIVE items here and stores everything. Free
text is captured but never auto-scored — it stays for optional later human scoring (PROTOCOL.md).
"""
import json
import os

from eval.reader_study.randomize import CASES, ORDERS

_HERE = os.path.dirname(os.path.abspath(__file__))
_GOLD_PATH = os.path.join(_HERE, "gold_questions.json")


def load_gold():
    with open(_GOLD_PATH, encoding="utf-8") as f:
        return json.load(f)


def assign(i):
    """Participant #i (0-based) -> their ordered [{sequence, case, condition}] rows, matching the
    balanced crossover in randomize.assignments (condition depends on the replication block, so
    order/fatigue cannot masquerade as a treatment effect)."""
    order = ORDERS[i % len(ORDERS)]
    block = i // len(ORDERS)
    return [{"sequence": s, "case": CASES[c],
             "condition": "DR+GK" if (block + c) % 2 else "DR"}
            for s, c in enumerate(order, 1)]


def _correct(answer, gold):
    """gold may be a single acceptable answer or a list of them; matching is exact (trimmed)."""
    a = (answer or "").strip()
    accepted = gold if isinstance(gold, list) else [gold]
    return a != "" and any(a == str(g).strip() for g in accepted)


def score_case(case, answers, gold=None):
    """Score one case's OBJECTIVE items (flood trap + the case's multiple-choice questions).
    `answers` is {flood, bases, crux, ...}. Returns per-item correctness + a 0..1 objective score."""
    gold = gold or load_gold()
    spec = gold["cases"][case]
    items = {"flood": _correct(answers.get("flood"), gold["flood_gold"])}
    for q in spec["questions"]:
        items[q["id"]] = _correct(answers.get(q["id"]), q["gold"])
    n_correct = sum(1 for v in items.values() if v)
    return {"items": items, "nCorrect": n_correct, "nItems": len(items),
            "objective": n_correct / len(items) if items else 0.0}


def score_response(response, gold=None):
    """Score every case-observation in a participant submission. Returns a list of scored
    observations: {participant, case, condition, seconds, confidence, score{...}, free{...}}."""
    gold = gold or load_gold()
    out = []
    for obs in response.get("cases", []):
        case = obs.get("case")
        if case not in gold["cases"]:
            continue
        out.append({
            "participant": response.get("participant"),
            "case": case,
            "condition": obs.get("condition"),
            "seconds": obs.get("seconds"),
            "confidence": obs.get("confidence"),
            "free": obs.get("free") or {},
            "score": score_case(case, obs.get("answers") or {"flood": obs.get("flood")}, gold),
        })
    return out


def aggregate(scored_observations):
    """Compare DR vs DR+GK over all scored case-observations: n, mean objective score, and per-item
    accuracy (flood / bases / crux). A between-observations read — honest for a fast pilot; a paired
    within-participant analysis is the rigorous follow-up (PROTOCOL.md)."""
    conds = {}
    for o in scored_observations:
        c = o.get("condition")
        if c not in ("DR", "DR+GK"):
            continue
        b = conds.setdefault(c, {"n": 0, "objectiveSum": 0.0, "items": {}, "itemsN": {}})
        b["n"] += 1
        b["objectiveSum"] += o["score"]["objective"]
        for k, v in o["score"]["items"].items():
            b["items"][k] = b["items"].get(k, 0) + (1 if v else 0)
            b["itemsN"][k] = b["itemsN"].get(k, 0) + 1
    out = {}
    for c, b in conds.items():
        out[c] = {
            "n": b["n"],
            "meanObjective": round(b["objectiveSum"] / b["n"], 3) if b["n"] else None,
            "itemAccuracy": {k: round(b["items"][k] / b["itemsN"][k], 3) for k in b["items"]},
        }
    if "DR" in out and "DR+GK" in out and out["DR"]["meanObjective"] is not None:
        out["upliftDRplusGK"] = round(out["DR+GK"]["meanObjective"] - out["DR"]["meanObjective"], 3)
    return out
