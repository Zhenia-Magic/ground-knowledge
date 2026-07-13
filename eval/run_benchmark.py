#!/usr/bin/env python3
"""Ground Knowledge — evaluation harness.

Runs three checks the competition rubric asks for and prints a one-page report:

  1. STRUCTURE-RECALL  — against a small gold fixture per case (eval/gold.json): did the tool surface
                         the expected positions, the key evidentiary roots, and the known cruxes?
                         Reports recall over a deliberately non-exhaustive set of key items.
  2. COLLAPSE          — the headline claim, quantified: raw source count vs distinct independent
                         bases per position (how much apparent support is correlated).
  3. ADVERSARIAL-ROBUSTNESS — the robustness contract, executed: flood a position with ungrounded
                         echo and fabricated roots; copy a real quote onto a fake sibling edge;
                         construct a citation ring; and reuse a known alias. Assert that confirmed
                         independence moves only for the one genuinely verified edge. Proposed roots
                         stay visible but quarantined. This is executable, unlike prose.

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
from engine import assess, roots                            # noqa: E402
from engine.merge import merge_delta, resolve_pending_refs  # noqa: E402
from ingest.pipeline import _carry_meta                     # noqa: E402

CASES = {"covid": "cases/covid.kb.json",
         "blackholes": "cases/blackholes.kb.json",
         "eggs": "cases/eggs.kb.json"}
BASELINE_MANIFESTS = {
    "chatgpt-deep-research": "eval/baselines/manifest.json",
    "claude-code": "eval/baselines/claude-code/manifest.json",
}


def _load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def _root_labels(kb):
    ind = assess.independence(kb)
    return {b["label"] for p in ind for b in p["bases"]}


def structure_recall(name, kb, gold):
    ind = {p["label"]: p for p in assess.independence(kb)}
    # Structure recall asks whether the expected crux CONCEPT is present in the visible divergence
    # matrix, not whether the ordinal detector promotes it to a headline badge. Promotion quality is
    # reported separately below (headline / one-sided / unanswered counts), so the two questions are
    # not conflated and a visible medium-vs-low factor is not scored as wholly absent.
    cruxes = {f["label"] for f in kb.get("factors", [])}
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
    """Execute the attack contract against one case and return a structured result.

    Covers volume, fabricated roots, quote-to-edge binding, circular corroboration, and a known
    alias. The last two attacks exercise the ordinary merge/pending-ref and ingestion-verification
    paths rather than calling resolver internals directly.
    """
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

    # (c) one real fetched dependency sentence copied onto a legitimate edge and a fabricated
    # sibling. Literal quote presence alone is insufficient: only the edge whose dataset the quote
    # actually names may be admitted.
    kb_edge = copy.deepcopy(kb)
    anchor = "Benchmark verified anchor for " + kb["meta"]["id"]
    quote = "We analyzed the {} as the primary evidence base for this study.".format(anchor)
    edge_delta = _src("edge_binding", target, "Observational", [
        {"ref": "NEW:" + anchor, "provenance": {"quote": quote, "extractionConfidence": 0.9}},
        {"ref": "NEW:Fabricated sibling for " + kb["meta"]["id"],
         "provenance": {"quote": quote, "extractionConfidence": 0.9}},
    ], depth="unknown")
    _carry_meta(edge_delta, {"kind": "full", "text": quote})
    merge_delta(kb_edge, edge_delta)
    edge_ind = {p["label"]: p for p in assess.independence(kb_edge)}[target]
    after_edge = round(edge_ind["nEff"], 2)
    proposed_after_edge = edge_ind["provisionalCount"]

    # (d) twelve commentaries arranged in one ungrounded citation ring. The SCC is visible and
    # flagged, but contributes ZERO evidence rather than laundering the loop into one basis.
    kb_cycle = copy.deepcopy(kb)
    for i in range(12):
        merge_delta(kb_cycle, _src("cycle_%02d" % i, target, "Narrative/Commentary",
                                   ["NEW-SRC:cycle_%02d" % ((i + 1) % 12)]))
    resolve_pending_refs(kb_cycle)
    cycle_assessment = assess.assess(kb_cycle)
    after_cycle = round({p["label"]: p for p in cycle_assessment["independence"]}[target]["nEff"], 2)
    cycle_flagged = any(p.get("circular") for p in cycle_assessment["independence"])

    # (e) a known alias of a root already supporting the target must resolve back to that root and
    # leave nEff unchanged. Novel semantic paraphrases remain a curator-review problem, reported in
    # the benchmark caveat rather than falsely claimed as an automatic defense.
    kb_alias = copy.deepcopy(kb)
    target_bases = next(p for p in assess.independence(kb_alias) if p["label"] == target)["bases"]
    ds_key = next((b["key"] for b in target_bases if b["key"].startswith("ds:")), None)
    after_alias = before
    if ds_key:
        did = ds_key[3:]
        d = next(x for x in kb_alias["datasets"] if x["id"] == did)
        alias = "Benchmark known alias for " + kb["meta"]["id"]
        d.setdefault("aliases", []).append(alias)
        merge_delta(kb_alias, _src("alias_reuse", target, "Observational", ["NEW:" + alias]))
        after_alias = round({p["label"]: p for p in assess.independence(kb_alias)}[target]["nEff"], 2)

    # (f) a generic methods word is present verbatim but does not identify a unique evidence base.
    kb_generic = copy.deepcopy(kb)
    generic_quote = "This cohort included 400 adults."
    generic_delta = _src("generic_identity", target, "Observational", [
        {"ref": "NEW:Cohort", "provenance": {"quote": generic_quote,
                                                "extractionConfidence": 0.9}}
    ], depth="unknown")
    _carry_meta(generic_delta, {"kind": "full", "text": generic_quote})
    merge_delta(kb_generic, generic_delta)
    generic_ind = {p["label"]: p for p in assess.independence(kb_generic)}[target]
    after_generic = round(generic_ind["nEff"], 2)

    # (g) two newly proposed labels are lexical aliases and the same fetched sentence names both.
    # Literal edge verification must admit at most one until a curator merges or overrides them.
    kb_split = copy.deepcopy(kb)
    split_quote = "We analyzed the Sentinel Outcomes Registry (SOR) cohort."
    split_delta = _src("unknown_alias_split", target, "Observational", [
        {"ref": "NEW:Sentinel Outcomes Registry", "provenance": {
            "quote": split_quote, "extractionConfidence": 0.9}},
        {"ref": "NEW:SOR", "provenance": {"quote": split_quote, "extractionConfidence": 0.9}},
    ], depth="unknown")
    _carry_meta(split_delta, {"kind": "full", "text": split_quote})
    merge_delta(kb_split, split_delta)
    split_ind = {p["label"]: p for p in assess.independence(kb_split)}[target]
    split_res = roots.resolve(kb_split)
    after_split = round(split_ind["nEff"], 2)

    # Contract: 12 ungrounded echo collapse to the position's ONE pooled voice (+1.0 at most, not
    # +12); fabricated named datasets on the unverified path are visible as proposed roots but add
    # ZERO confirmed nEff until a fetched dependency quote verifies or a curator confirms them.
    echo_ok = after_echo <= before + 1.0 + 1e-6
    fab_quarantined = abs(after_fab - before) <= 1e-6
    edge_bound = abs(after_edge - (before + 1.0)) <= 1e-6 and proposed_after_edge >= 1
    cycle_zero = abs(after_cycle - before) <= 1e-6 and cycle_flagged
    alias_stable = abs(after_alias - before) <= 1e-6
    generic_quarantined = abs(after_generic - before) <= 1e-6 and generic_ind["provisionalCount"] >= 1
    split_bounded = abs(after_split - (before + 1.0)) <= 1e-6 and bool(split_res["alias_suspects"])
    ok = (echo_ok and fab_quarantined and edge_bound and cycle_zero and alias_stable
          and generic_quarantined and split_bounded)
    return {"target": target, "before": before, "echo": after_echo, "fabricated": after_fab,
            "edgeBound": after_edge, "edgeProvisional": proposed_after_edge,
            "cycle": after_cycle, "cycleFlagged": cycle_flagged, "knownAlias": after_alias,
            "genericLabel": after_generic, "unknownAliasSplit": after_split,
            "aliasSplitFlagged": bool(split_res["alias_suspects"]),
            "verdict": "PASS" if ok else "FAIL"}


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
                   "Production impossibility": ["production", "produce", "planck scale", "extra dimension"],
                   "Accretion-timescale": ["accretion", "accrete", "growth time", "grow dangerous"],
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
    crux_labels = [f["label"] for f in kb.get("factors", [])]
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

        adv = adversarial_invariance(kb)
        all_ok = all_ok and adv["verdict"] == "PASS"
        print("  adversarial robustness on '%s' (confirmed nEff %.2f):" %
              (adv["target"][:36], adv["before"]))
        print("     +12 ungrounded echo             -> %.2f   (12 sources collapse to <=1 pooled voice)" % adv["echo"])
        print("     +12 fabricated unverified roots -> %.2f   (proposed+visible, but quarantined; naive count %.2f)"
              % (adv["fabricated"], adv["before"] + 12))
        print("     +1 verified edge + copied sibling -> %.2f   (only named edge +1; sibling stays proposed)"
              % adv["edgeBound"])
        print("     +12-source circular citation ring -> %.2f   (flagged; zero independent grounding)"
              % adv["cycle"])
        print("     +1 source using a known root alias -> %.2f   (resolves to existing root)"
              % adv["knownAlias"])
        print("     +1 generic fetched label          -> %.2f   (ordinary methods word stays proposed)"
              % adv["genericLabel"])
        print("     +2 unknown lexical aliases        -> %.2f   (at most one admitted; collision flagged)"
              % adv["unknownAliasSplit"])
        print("     %s  (seven volume, identity, edge-binding, cycle, and alias contracts)"
              % adv["verdict"])

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
