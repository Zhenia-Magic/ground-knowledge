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
    # a gold crux is "surfaced" if the tool flags the factor as doing real work in the dispute —
    # a headline crux (cross-camp disagreement / shared pivot) OR a one-sided load-bearing / left-
    # unanswered factor. The headline isCrux count stays tight; this is the "surface what matters" set.
    cruxes = {c["label"] for c in assess.cruxes(kb) if c.get("loadBearing")}
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


# Paraphrase synonyms for the comparison ONLY. The gold labels were written from Ground Knowledge's
# own structured vocabulary, so a bare substring test under-credits a prose report that discusses the
# same concept in different words ("safe" for "No risk", "lab leak" for "research-related accident").
# These synonyms level that bias so the comparison is fair to prose; they are NOT used to score GK's
# own structure recall (structure_recall stays strict). Kept deliberately small and obvious.
_COMPARE_SYNONYMS = {
    "covid": {"Undetermined": ["unresolved", "undetermined", "inconclusive", "cannot be determined"],
              "research-related accident": ["lab leak", "laboratory", "lab-associated", "research-related"],
              "Epidemiological proximity": ["proximity", "clustering", "near the market", "epicenter"],
              "genomic sequences": ["genomic", "genome", "lineage a", "lineage b", "two lineages"]},
    "blackholes": {"No risk": ["safe", "no danger", "poses no risk", "not dangerous"],
                   "Residual concern": ["residual", "cannot be excluded", "precaution", "small probability"],
                   "Cosmic-ray empirical bound": ["cosmic ray", "cosmic-ray", "white dwarf", "neutron star"],
                   "cosmic-ray safety analogy": ["cosmic ray", "cosmic-ray"],
                   "safety argument itself": ["safety argument", "argument could be wrong", "flawed argument"]},
    "eggs": {"Increases risk": ["increase", "raises risk", "higher risk", "harmful"],
             "No association": ["no association", "no link", "no significant", "null result"],
             "Context-dependent": ["context", "depends", "population-dependent", "it depends"],
             "Nurses' Health Study": ["nurses", "nhs"],
             "industry funding": ["industry", "egg board", "funding"],
             "Subgroups": ["subgroup", "diabetic", "hyper-responder"],
             "biomarkers": ["biomarker", "ldl", "cholesterol"]},
}


def _hits(items, haystacks, syn):
    """Which of `items` appear in any of `haystacks` (list of strings), counting paraphrase synonyms.
    Symmetric: used for both GK's structured labels and a baseline's prose."""
    low = [h.lower() for h in haystacks]
    got = set()
    for e in items:
        for cand in [e.lower()] + [s.lower() for s in syn.get(e, [])]:
            if any(cand in h for h in low):
                got.add(e)
                break
    return got


def _text_hits(text, items, syn):
    return _hits(items, [text or ""], syn)


def _gk_hits(kb, gold, syn):
    """Which gold items Ground Knowledge surfaces in its STRUCTURED output — position labels, resolved
    root labels, and load-bearing crux labels — the structured analogue of a prose mention."""
    pos_labels = [p["label"] for p in assess.independence(kb)]
    roots = list(_root_labels(kb))
    crux_labels = [c["label"] for c in assess.cruxes(kb) if c.get("loadBearing")]
    return {"positions": _hits(gold["positions"], pos_labels, syn),
            "keyRoots": _hits(gold["keyRoots"], roots, syn),
            "cruxes": _hits(gold.get("cruxes", []), crux_labels, syn)}


def comparative_recall(gold):
    """Score the deep-research baseline REPORTS against the SAME gold Ground Knowledge is scored on:
    a keyword-recall proxy over prose, symmetric with GK's structured recall. Reporting this honestly
    is the whole point of the check — a good prose report usually MATCHES GK on which items it
    surfaces; GK's advantage is the recomputable collapse / robustness / diff, not surfacing more.
    Returns, per case, each system's set of hit gold items per category (or None if no report)."""
    cats = ("positions", "keyRoots", "cruxes")
    out = {}
    for name, path in CASES.items():
        kb, g = _load(path), gold[name]
        syn = _COMPARE_SYNONYMS.get(name, {})
        systems = {"Ground Knowledge": _gk_hits(kb, g, syn)}
        for bname, rel_manifest in BASELINE_MANIFESTS.items():
            manifest_path = os.path.join(ROOT, rel_manifest)
            if not os.path.isfile(manifest_path):
                systems[bname] = None
                continue
            base_dir = os.path.dirname(manifest_path)
            rel = _load(rel_manifest).get(name, {}).get("file")
            report = os.path.join(base_dir, rel) if rel else None
            if not report or not os.path.isfile(report):
                systems[bname] = None
                continue
            with open(report, encoding="utf-8") as f:
                text = f.read()
            systems[bname] = {c: _text_hits(text, g.get(c, []), syn) for c in cats}
        out[name] = {"gold": g, "systems": systems}
    return out


def print_comparative(gold):
    cats = ("positions", "keyRoots", "cruxes")
    print("\n" + "=" * 78)
    print("COMPARATIVE STRUCTURE RECALL  (same gold; GK structured output vs baseline prose)")
    print("CAVEAT: this is a keyword-recall PROXY (paraphrase synonyms included). A strong deep-research")
    print("report surfaces the same positions/roots/cruxes — near parity is the expected, honest result.")
    print("GK's differentiator is NOT recall; it is the recomputable collapse (raw->independent bases),")
    print("the EXECUTED flooding/fabrication contract, and the versioned diff. Read losses as the signal.")
    print("=" * 78)
    for name, data in comparative_recall(gold).items():
        g = data["gold"]
        print("\n### %s" % name.upper())
        print("     %-24s %s" % ("", "  ".join("%-10s" % c for c in cats)))
        for sysname, hits in data["systems"].items():
            if hits is None:
                print("     %-24s  (no captured report)" % sysname)
                continue
            cells = "  ".join("%-10s" % ("%d/%d" % (len(hits[c]), len(g.get(c, [])))) for c in cats)
            print("     %-24s %s" % (sysname, cells))
        gk = data["systems"]["Ground Knowledge"]
        for sysname, hits in data["systems"].items():          # honest wins AND losses, item-level
            if sysname == "Ground Knowledge" or hits is None:
                continue
            for c in cats:
                if hits[c] - gk[c]:
                    print("       · %s surfaces %s that GK misses" % (sysname, sorted(hits[c] - gk[c])))
                if gk[c] - hits[c]:
                    print("       · GK surfaces %s that %s misses" % (sorted(gk[c] - hits[c]), sysname))


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

        cx = assess.cruxes(kb)
        n_crux = sum(1 for c in cx if c["isCrux"])
        n_one = sum(1 for c in cx if c["oneSidedLoadBearing"])
        n_miss = sum(1 for c in cx if c["missingCounterassessment"])
        print("  crux types: %d headline crux (disagreement/shared pivot) · %d one-sided load-bearing"
              " · %d left-unanswered  (of %d factors)" % (n_crux, n_one, n_miss, len(cx)))

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

    print_comparative(gold)

    print("\n" + "=" * 78)
    print("BASELINE STATUS:", "{} LIVE/INDEPENDENT SETS (files + hashes verified)".format(
          len(baseline_manifests)) if not baseline_issues else
          "INCOMPLETE: " + "; ".join(baseline_issues))
    print("OVERALL adversarial robustness:", "PASS" if all_ok else "FAIL")
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
