#!/usr/bin/env python3
"""Ground Knowledge — evaluation harness.

Runs three checks the competition rubric asks for and prints a one-page report:

  1. STRUCTURE-RECALL  — against a small gold fixture per case (eval/gold.json): did the tool surface
                         the expected positions, the key evidentiary roots, and the known cruxes?
                         Reports recall over a deliberately non-exhaustive set of key items.
  2. COLLAPSE          — the headline claim, quantified: raw source count vs distinct independent
                         bases per position (how much apparent support is correlated).
  3. ADVERSARIAL-ROBUSTNESS — the robustness contract, executed: flood a position with (a) ungrounded
                         echo and (b) fabricated-named-dataset sources on the unverified path, and
                         assert the position's CONFIRMED independence does not inflate. Proposed
                         roots stay visible but quarantined. This is executable, unlike prose.

The point vs. a deep-research baseline (eval/baselines/) is not a better paragraph: it is a
structured, recomputable artifact. The arithmetic is deterministic and immune to flooding/echo by
construction, but it is not self-certifying: an incorrect curator confirmation or an omitted `src:`
edge can still move the numbers wrongly (see MECHANISM.md §8). Run:

    python eval/run_benchmark.py
"""
import copy
import argparse
import hashlib
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
BASELINE_MANIFESTS = {
    "chatgpt-deep-research": "eval/baselines/manifest.json",
    "claude-code": "eval/baselines/claude-code/manifest.json",
}


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
    # +12); fabricated named datasets on the unverified path are visible as proposed roots but add
    # ZERO confirmed nEff until a fetched dependency quote verifies or a curator confirms them.
    echo_ok = after_echo <= before + 1.0 + 1e-6
    fab_quarantined = abs(after_fab - before) <= 1e-6
    return target, before, after_echo, after_fab, "PASS" if (echo_ok and fab_quarantined) else "FAIL"


def baseline_status():
    """Verify every configured baseline set's provenance and hashes; a Boolean is not evidence."""
    manifests, issues = {}, []
    for baseline_name, rel_manifest in BASELINE_MANIFESTS.items():
        path = os.path.join(ROOT, rel_manifest)
        if not os.path.isfile(path):
            issues.append(baseline_name + ": missing manifest")
            continue
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        manifests[baseline_name] = manifest
        base_dir = os.path.dirname(path)
        issues.extend(_baseline_manifest_issues(baseline_name, base_dir, manifest))
    return manifests, issues


def _baseline_manifest_issues(baseline_name, base_dir, manifest):
    issues = []
    for name in CASES:
        entry = manifest.get(name, {})
        if not entry.get("independent"):
            issues.append(baseline_name + "/" + name + ": not independently captured")
            continue
        for field in ("file", "promptFile", "product", "capturedAt", "promptSha256", "outputSha256"):
            if not entry.get(field):
                issues.append(baseline_name + "/" + name + ": missing " + field)
        for file_field, hash_field in (("file", "outputSha256"), ("promptFile", "promptSha256")):
            rel = entry.get(file_field)
            if not rel:
                continue
            target = os.path.normpath(os.path.join(base_dir, rel))
            if not os.path.isfile(target):
                issues.append(baseline_name + "/" + name + ": missing file " + rel)
                continue
            with open(target, "rb") as captured:
                actual = hashlib.sha256(captured.read()).hexdigest()
            if entry.get(hash_field) != actual:
                issues.append(baseline_name + "/" + name + ": " + hash_field + " mismatch")
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run Ground Knowledge's reproducible evaluation")
    ap.add_argument("--require-live-baseline", action="store_true",
                    help="fail unless all three cases have independently captured live baselines")
    args = ap.parse_args(argv)
    baseline_manifests, baseline_issues = baseline_status()
    if args.require_live_baseline and baseline_issues:
        print("LIVE BASELINE REQUIRED but provenance failed: " + "; ".join(baseline_issues))
        return 2
    gold = _load("eval/gold.json")
    print("=" * 78)
    print("GROUND KNOWLEDGE — BENCHMARK  (structure recall · collapse · adversarial robustness)")
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
        print("  adversarial robustness on '%s' (confirmed nEff %.2f):" % (tgt[:36], b))
        print("     +12 ungrounded echo             -> %.2f   (12 sources collapse to <=1 pooled voice)" % ae)
        print("     +12 fabricated unverified roots -> %.2f   (proposed+visible, but quarantined; naive count %.2f)"
              % (af, b + 12))
        print("     %s  (echo pooled; fabricated unverified roots add zero confirmed nEff)"
              % verdict)

    print("\n" + "=" * 78)
    print("BASELINE STATUS:", "{} LIVE/INDEPENDENT SETS (files + hashes verified)".format(
          len(baseline_manifests)) if not baseline_issues else
          "INCOMPLETE: " + "; ".join(baseline_issues))
    print("OVERALL adversarial robustness:", "PASS" if all_ok else "FAIL")
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
