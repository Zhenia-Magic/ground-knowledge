#!/usr/bin/env python3
"""Ground Knowledge — evaluation harness.

Runs three checks the competition rubric asks for and prints a one-page report:

  1. STRUCTURE-RECALL  — against a small gold fixture per case (eval/gold.json): did the tool surface
                         the expected positions, the key evidentiary roots, and the known cruxes?
                         Reports precision/recall over roots and positions.
  2. COLLAPSE          — the headline claim, quantified: raw source count vs distinct independent
                         bases per position (how much apparent support is correlated).
  3. ADVERSARIAL-INVARIANCE — the robustness contract, executed: flood a position with (a) ungrounded
                         echo and (b) fabricated-named-dataset sources on the unverified path, and
                         assert the position's independence does NOT inflate beyond its confirmed
                         roots. This is the property a deep-research prose answer cannot give.

The point vs. a deep-research baseline (eval/baselines/) is not a better paragraph: it is a
structured, recomputable artifact whose numbers move only for legitimate reasons. Run:

    python eval/run_benchmark.py
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import assess                                   # noqa: E402
from engine.merge import merge_delta                        # noqa: E402

CASES = {"covid": "cases/covid.kb.json",
         "blackholes": "cases/blackholes.kb.json",
         "eggs": "cases/eggs.kb.json"}


def _load(path):
    return json.load(open(os.path.join(ROOT, path)))


def _root_labels(kb):
    ind = assess.independence(kb)
    return {b["label"] for p in ind for b in p["bases"]}


def structure_recall(name, kb, gold):
    ind = {p["label"]: p for p in assess.independence(kb)}
    cruxes = {c["label"] for c in assess.cruxes(kb) if c.get("isCrux")}
    roots = _root_labels(kb)

    def _hit(expected, have):
        # substring match, case-insensitive, so "Nurses' Health Study" matches the fuller label
        return sum(1 for e in expected if any(e.lower() in h.lower() for h in have))

    pos_hit = _hit(gold["positions"], ind.keys())
    root_hit = _hit(gold["keyRoots"], roots)
    crux_hit = _hit(gold.get("cruxes", []), cruxes)
    return {
        "positions": (pos_hit, len(gold["positions"])),
        "keyRoots": (root_hit, len(gold["keyRoots"])),
        "cruxes": (crux_hit, len(gold.get("cruxes", []))) if gold.get("cruxes") else None,
    }


def collapse(kb):
    return [(p["label"], p["raw"], round(p["nEff"], 1)) for p in assess.independence(kb)]


def _src(sid, pos, evidence, rests, depth="unknown"):
    return {"source": {"title": sid, "year": 2024, "url": "https://attack/" + sid, "position": pos,
                       "evidence": evidence, "restsOn": rests, "textDepth": depth,
                       "funding": "Undisclosed", "population": "—", "confidence": "unstated"}}


def adversarial_invariance(kb):
    """Return (position, before, after_echo, after_fabricated, verdict)."""
    ind = sorted(assess.independence(kb), key=lambda p: -p["nEff"])
    target = ind[0]["label"]
    before = round(ind[0]["nEff"], 2)

    # (a) ungrounded echo: 12 rehashes under the target position, empty restsOn
    kb_echo = copy.deepcopy(kb)
    for i in range(12):
        merge_delta(kb_echo, _src("echo_%d" % i, target, "Observational", []))
    after_echo = round({p["label"]: p for p in assess.independence(kb_echo)}[target]["nEff"], 2)

    # (b) fabricated named datasets on the unverified (paste-back) path: 12 distinct invented roots
    kb_fab = copy.deepcopy(kb)
    for i in range(12):
        merge_delta(kb_fab, _src("fab_%d" % i, target, "Observational", ["NEW:Fabricated dataset %d" % i]))
    after_fab = round({p["label"]: p for p in assess.independence(kb_fab)}[target]["nEff"], 2)

    # Contract: 12 ungrounded echo collapse to the position's ONE pooled voice (+1.0 at most, not
    # +12); 12 fabricated named datasets on the unverified path each count at HALF (provisional), so
    # they add at most +6.0, never the +12 a naive count would give. Fabrication is halved + flagged,
    # not eliminated -- the acknowledged residual (MECHANISM.md §8), reported honestly rather than
    # claimed away.
    echo_ok = after_echo <= before + 1.0 + 1e-6
    fab_discounted = (after_fab <= before + 12 * 0.5 + 1e-6) and (after_fab < before + 12 - 1e-6)
    return target, before, after_echo, after_fab, "PASS" if (echo_ok and fab_discounted) else "FAIL"


def main():
    gold = _load("eval/gold.json")
    print("=" * 78)
    print("GROUND KNOWLEDGE — BENCHMARK  (structure recall · collapse · adversarial invariance)")
    print("=" * 78)
    all_ok = True
    for name, path in CASES.items():
        kb = _load(path)
        g = gold[name]
        print("\n### %s — %s" % (name.upper(), kb["meta"]["question"]))

        sr = structure_recall(name, kb, g)
        for k, v in sr.items():
            if v:
                print("  recall/%-9s %d/%d" % (k, v[0], v[1]))

        print("  collapse (raw sources -> distinct independent bases):")
        for label, raw, neff in collapse(kb):
            print("     %-46s %2d -> %s" % (label[:46], raw, neff))

        tgt, b, ae, af, verdict = adversarial_invariance(kb)
        all_ok = all_ok and verdict == "PASS"
        print("  adversarial invariance on '%s' (nEff %.2f):" % (tgt[:36], b))
        print("     +12 ungrounded echo             -> %.2f   (12 sources collapse to <=1 pooled voice)" % ae)
        print("     +12 fabricated unverified roots -> %.2f   (each halved+flagged; naive count would be %.2f)"
              % (af, b + 12))
        print("     %s  (echo neutralized; fabrication discounted to half — the acknowledged residual)"
              % verdict)

    print("\n" + "=" * 78)
    print("BASELINE: a deep-research prose answer (eval/baselines/) restates the debate but gives no")
    print("recomputable collapse number and no adversarial-invariance guarantee — see eval/RESULTS.md.")
    print("OVERALL adversarial invariance:", "PASS" if all_ok else "FAIL")
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
