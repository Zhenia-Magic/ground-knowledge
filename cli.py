#!/usr/bin/env python3
"""epistemic -- CLI orchestrator tying the three layers together.

  INGESTION (ingest/)   discover sources or turn one link/document into a delta
  STRUCTURE (engine/merge.py)   fold the delta into the KB (entity resolution)
  ASSESSMENT (engine/assess.py) recompute every metric, deterministically
  DIFF + BUILD          report what changed; bake a self-contained viewer

Cold start = `discover` then `ingest` looped over the results.  An update = one `ingest`
(of a link or a PDF/docx).  Same path either way -- that is what makes the KB "living".

  python cli.py init <id> "<question>"            > cases/<id>.kb.json
  python cli.py discover <kb.json> [--k N] [--dry-run]
  python cli.py ingest  <kb.json> <link-or-file> [--dry-run] [--apply]
  python cli.py add     <kb.json> <delta.json>      # merge + recompute + diff (in place)
  python cli.py show    <kb.json>
  python cli.py assess  <kb.json>
  python cli.py build   <kb.json> [<kb2.json> ...] [--out viewer/index.html]
"""
import argparse
import json
import os
import sys

from engine.assess import assess, diff_assessments
from engine.merge import merge_delta
from engine.render import json_for_script
from engine.schema import empty_kb
from engine.migrate import load_migrated
from engine.io import atomic_write_json, atomic_write_text

ROOT = os.path.dirname(os.path.abspath(__file__))


def read_json(p):
    with open(p, encoding="utf-8") as f:
        return load_migrated(json.load(f))


def write_json(p, o):
    atomic_write_json(p, o)


def pct(x):
    return str(round(x * 100)) + "%"


def _print_numbered(errors):
    for i, error in enumerate(errors, 1):
        print("  {}. {}".format(i, error))


def _trust_preview(delta):
    """Notes on caller-supplied fields the trust boundary will IGNORE on `add`.

    Not errors — just so an agent knows a verifiedQuote/admission/textDepth it wrote by hand will
    not be believed. The CLI re-verifies quotes against fetched text; admission is a curator action.
    """
    notes = []
    src = delta.get("source") if isinstance(delta, dict) else None
    if isinstance(src, dict):
        if src.get("textDepth") not in (None, "unknown"):
            notes.append("source.textDepth='{}' will be reset to 'unknown' — depth only counts for "
                         "text the CLI fetched itself".format(src.get("textDepth")))
        for name, prov in (src.get("provenance") or {}).items():
            if isinstance(prov, dict) and (prov.get("verifiedQuote") or prov.get("quoteVerification")):
                notes.append("source.provenance.{}: verifiedQuote/quoteVerification will be dropped — "
                             "the CLI re-verifies quotes against the text it fetched".format(name))
        for i, edge in enumerate(src.get("restsOn") or []):
            if not isinstance(edge, dict):
                continue
            if edge.get("admission"):
                notes.append("restsOn[{}].admission will be dropped — admitting a root is a curator "
                             "action (confirm-dataset / confirm-edge)".format(i))
            prov = edge.get("provenance")
            if isinstance(prov, dict) and (prov.get("verifiedQuote") or prov.get("quoteVerification")):
                notes.append("restsOn[{}].provenance verification will be dropped — the CLI "
                             "re-verifies edge quotes".format(i))
    for i, factor in enumerate((delta.get("factorWeights") or []) if isinstance(delta, dict) else []):
        if isinstance(factor, dict) and (factor.get("verifiedQuote") or factor.get("quoteVerification")):
            notes.append("factorWeights[{}] verification will be dropped".format(i))
    return notes


def cmd_lint(args):
    """Validate an agent-written delta file (or a KB) WITHOUT merging anything.

    This is the pre-flight to run on hand/agent-authored JSON before `add`: it never mutates state,
    reports numbered actionable problems, and exits nonzero on failure. A KB is routed to the full
    schema/cross-reference validator; anything else is treated as a delta (or a batch array)."""
    data = read_json(args.path)
    # A KB carries meta + the top-level arrays -> reuse the full schema/cross-reference validator.
    if isinstance(data, dict) and "meta" in data and "positions" in data and "sources" in data:
        from engine.migrate import migrate_kb, validation_errors
        kb, _ = migrate_kb(data)
        errors = validation_errors(kb)
        if errors:
            print("{}: {} problem(s)".format(args.path, len(errors)))
            _print_numbered(errors)
            raise SystemExit(1)
        print("{}: valid KB (schema v{}, {} sources)".format(
            args.path, kb["meta"]["schemaVersion"], len(kb["sources"])))
        return
    # Otherwise a single delta, or a batch array of deltas.
    from engine.validate import delta_validation_errors
    deltas = data if isinstance(data, list) else [data]
    total = 0
    for idx, delta in enumerate(deltas):
        label = "delta" if len(deltas) == 1 else "delta[{}]".format(idx)
        if not isinstance(delta, dict):
            print("{}: must be a JSON object".format(label))
            total += 1
            continue
        errors = delta_validation_errors(delta)
        title = (delta.get("source") or {}).get("title") if isinstance(delta.get("source"), dict) else None
        head = label + (" — " + title if title else "")
        if errors:
            print("{}: {} formatting problem(s)".format(head, len(errors)))
            _print_numbered(errors)
        else:
            print("{}: well-formed".format(head))
        for note in _trust_preview(delta):
            print("     note: " + note)
        total += len(errors)
    if total:
        print("\n{} problem(s) total — fix before `add`.".format(total))
        raise SystemExit(1)
    print("\nAll well-formed. Safe to `add`.")


def cmd_doctor(args):
    """Health check for a KB: structure + completeness + trust hygiene.

    Structural/reference breakage is a hard failure (nonzero exit); everything else is a warning that
    still lets you build/push. Complements `show` (metrics) and `gaps` (evidence thinness): doctor
    answers "is this file in good shape to hand off?"."""
    from engine.migrate import migrate_kb, validation_errors, _edge_ref
    kb, _ = migrate_kb(read_json(args.kb))
    a = assess(kb)
    positions, sources, datasets, factors = (
        kb["positions"], kb["sources"], kb["datasets"], kb["factors"])
    print("DOCTOR — {}  (v{})".format(kb["meta"]["question"], kb["meta"].get("version", 0)))
    warnings = 0

    # 1. STRUCTURE (hard) --------------------------------------------------
    errors = validation_errors(kb)
    print("\nSTRUCTURE")
    if errors:
        print("  x {} schema/reference problem(s):".format(len(errors)))
        _print_numbered(errors)
    else:
        print("  ok  schema v{} + cross-references valid".format(kb["meta"]["schemaVersion"]))

    # 2. COMPLETENESS ------------------------------------------------------
    print("\nCOMPLETENESS")
    src_per_pos = {}
    for s in sources:
        src_per_pos[s.get("position")] = src_per_pos.get(s.get("position"), 0) + 1
    empty_pos = [p for p in positions if src_per_pos.get(p.get("id"), 0) == 0]
    print("  {}  {} sources across {} positions".format(
        "!!" if empty_pos else "ok", len(sources), len(positions)))
    if empty_pos:
        warnings += 1
        print("      {} position(s) have no source yet: {}".format(
            len(empty_pos), ", ".join(p.get("label", p.get("id")) for p in empty_pos)))
    used = set()
    for s in sources:
        for edge in s.get("restsOn", []):
            ref = _edge_ref(edge)
            if ref and not ref.startswith("src:"):
                used.add(ref)
    confirmed_ids = {d.get("id") for d in datasets if isinstance(d.get("confirmation"), dict)
                     and d["confirmation"].get("status") == "confirmed"}
    proposed = [d for d in datasets if d.get("id") not in confirmed_ids]
    print("  {}  {} evidence bases — {} confirmed, {} still proposed".format(
        "!!" if proposed else "ok", len(datasets), len(confirmed_ids), len(proposed)))
    if proposed:
        warnings += 1
        print("      confirm identities with `confirm-dataset` / admit support with `confirm-edge` "
              "(or curate proposed bases in the portal) so they count toward coverage")
    orphan_ds = [d for d in datasets if d.get("id") not in used]
    if orphan_ds:
        warnings += 1
        print("  !!  {} evidence base(s) referenced by no source: {}".format(
            len(orphan_ds), ", ".join(d.get("label", d.get("id")) for d in orphan_ds)))
    if factors:
        no_claim = [f for f in factors if not f.get("provenance")]
        # A factor with claims but no derived weights isn't broken: its cells populate only from
        # quote-verified claims (engine/merge._recompute_factor_cell), so it stays empty until a
        # full-text quote check confirms it. Surface that as info, not a counted warning.
        unrendered = [f for f in factors if f.get("provenance") and not f.get("weights")]
        print("  {}  {} factors{}".format(
            "!!" if no_claim else "ok", len(factors),
            " — {} with no supporting claim".format(len(no_claim)) if no_claim else ""))
        if no_claim:
            warnings += 1
        if unrendered:
            print("      note: {} factor(s) have a claim but no verified quote yet, so they will "
                  "not render as key issues until a full-text quote check confirms them"
                  .format(len(unrendered)))
    else:
        print("  --  no factors yet (the Key issues / divergence view will be empty)")

    # 3. TRUST HYGIENE -----------------------------------------------------
    print("\nTRUST HYGIENE")
    unverifiable = 0
    for s in sources:
        for prov in (s.get("provenance") or {}).values():
            if isinstance(prov, dict) and prov.get("verifiedQuote") in ("exact", "fuzzy") \
                    and not prov.get("quoteVerification"):
                unverifiable += 1
    print("  {}  {} provenance quote(s) marked verified with no verification record".format(
        "!!" if unverifiable else "ok", unverifiable))
    if unverifiable:
        warnings += 1
    qa = a.get("quoteAudit")
    unverified_full = sum(p.get("unverifiedFull", 0) for p in (qa["positions"] if qa else []))
    if unverified_full:
        warnings += 1
        print("  !!  {} full-text source(s) carry an unverified quote (run scripts/audit_quotes.py)"
              .format(unverified_full))
    else:
        print("  ok  no full-text source carries an unverified quote")

    # 4. SIZE --------------------------------------------------------------
    print("\nSIZE")
    size_warn = []
    if not sources:
        size_warn.append("0 sources — nothing to assess")
    if len(positions) < 2:
        size_warn.append("< 2 positions — a dispute needs at least two")
    if len(sources) > 400:
        size_warn.append("{} sources — unusually large, check for duplicates".format(len(sources)))
    if size_warn:
        warnings += len(size_warn)
        for w in size_warn:
            print("  !!  " + w)
    else:
        print("  ok  {} sources / {} positions / {} bases / {} factors — within normal bounds".format(
            len(sources), len(positions), len(datasets), len(factors)))

    # summary --------------------------------------------------------------
    print("\n" + ("-" * 52))
    if errors:
        print("UNHEALTHY — {} structural problem(s) must be fixed (see STRUCTURE).".format(len(errors)))
        raise SystemExit(1)
    if warnings:
        print("OK with {} warning(s) — safe to build/push, but address the flagged items for a "
              "submission-grade case.".format(warnings))
    else:
        print("HEALTHY — no structural problems and no warnings.")


def cmd_mark_curated(args):
    """Admin/curator marks (or, with --off, unmarks) a question as officially curated & maintained.

    A trusted, admin-only stewardship label — see engine/curate.set_curated. It is shown to readers
    next to the *computed* confirmed-coverage percentage, never as a substitute for it."""
    from engine import curate
    if not args.off and not (args.by or "").strip():
        raise SystemExit("marking a question curated requires --by <curator/admin name> (or use --off to remove).")
    kb = read_json(args.kb)
    res = curate.set_curated(kb, curated=not args.off, by=args.by, note=args.note)
    write_json(args.kb, kb)
    a = assess(kb).get("curation", {})
    print(res["summary"] + "  (KB now v{})".format(kb["meta"]["version"]))
    if not args.off:
        print("  paired signal: evidence {}% confirmed ({}/{} bases), {}% of quotes verified".format(
            a.get("basesPct", 0), a.get("confirmedBases", 0), a.get("totalBases", 0),
            a.get("quotesPct", 0)))


def cmd_validate(args):
    from engine.migrate import migrate_kb, validation_errors
    with open(args.kb, encoding="utf-8") as f:
        kb, changes = migrate_kb(json.load(f))
    errors = validation_errors(kb)
    if errors:
        for error in errors:
            print("ERROR:", error)
        raise SystemExit(1)
    print("Valid KB schema v{}{}".format(
        kb["meta"]["schemaVersion"], " (migration available: " + "; ".join(changes) + ")" if changes else ""))


def cmd_migrate(args):
    from engine.migrate import migrate_kb, validation_errors
    with open(args.kb, encoding="utf-8") as f:
        kb, changes = migrate_kb(json.load(f))
    errors = validation_errors(kb)
    if errors:
        raise SystemExit("migration produced invalid KB: " + "; ".join(errors))
    if args.apply:
        write_json(args.kb, kb)
        print("Migrated {} in place: {}".format(args.kb, "; ".join(changes) or "already v2"))
    elif args.out:
        write_json(args.out, kb)
        print("Migrated {} -> {}: {}".format(args.kb, args.out, "; ".join(changes) or "already v2"))
    else:
        print(json.dumps(kb, indent=2, ensure_ascii=False))


def pad(s, n):
    s = str(s)
    return s if len(s) >= n else s + " " * (n - len(s))


# ---------------------------------------------------------------- show
def cmd_show(args):
    kb = read_json(args.kb)
    a = assess(kb)
    L = ["# {}   (v{})".format(kb["meta"]["question"], kb["meta"]["version"]),
         "{} sources · {} positions · {} factors · {} datasets".format(
             len(kb["sources"]), len(kb["positions"]), len(kb["factors"]), len(kb["datasets"])),
         "", "DISTRIBUTION"]
    for d in a["distribution"]:
        L.append("  " + pad(d["label"], 22) + pad(d["count"], 3) + "  " + str(d["pct"]) + "%")
    if a["fundingSkew"]:
        fs = a["fundingSkew"]
        if fs.get("top"):
            L.append('  funding skew: interested money most backs "{}" ({} industry/advocacy sources)'.format(
                fs["top"]["label"], fs["n"]))
        elif fs.get("tied"):
            L.append("  funding pattern: tied — " + "; ".join(
                "{} ({})".format(x["label"], x["count"]) for x in fs.get("leaders", [])))
        elif fs.get("undisclosed"):
            L.append("  funding gap: {} of {} sources undisclosed".format(
                fs["undisclosed"], fs["total"]))
    L += ["", "CONFIRMED-ROOT COVERAGE  (not a quality/truth score; concentration shown alongside)"]
    for p in a["independence"]:
        t = "{} {}/{}".format(p["topDataset"]["label"], p["topDataset"]["count"], p["raw"]) \
            if p["topDataset"] else "—"
        L.append("  " + pad(p["label"], 22) + pad(pct(p["concentration"]), 5) + " on " +
                 pad(t, 34) + " coverage={:.1f}".format(p["nEff"]) +
                 ("   [CONCENTRATED]" if p["concentrated"] else ""))
    if a["dominantDataset"]:
        dd = a["dominantDataset"]
        L.append("  most reused case-wide: {} — {}/{} ({})".format(
            " / ".join(dd["labels"]), dd["count"], dd["total"], pct(dd["share"])))
    if a.get("methodAudit"):
        L += ["", "METHOD-BIAS CHECK  (shared study-method risks; does not change nEff)"]
        for p in a["methodAudit"]:
            if not p["top"]:
                continue
            top = p["top"]
            suffix = "   [METHOD-BIAS WARNING]" if p["monoculture"] else ""
            all_share = top["count"] / p["raw"] if p["raw"] else 0
            L.append("  {} — {} of {} sources share {} ({})  method nEff≈{:.1f}{}".format(
                p["label"], top["count"], p["raw"], top["label"],
                pct(all_share), p["nEff"], suffix))
    qa = a.get("quoteAudit")
    if qa and any(p["depthKnown"] for p in qa["positions"]):
        L += ["", "QUOTE CHECK  (does the provenance quote match the text we actually fetched?)"]
        for p in qa["positions"]:
            if not p["depthKnown"]:
                continue
            L.append("  {} — {} of {} sources fetched as full text".format(
                p["label"], p["full"], p["depthKnown"]) +
                (", {} with an unverified quote  [QUOTE WARNING]".format(p["unverifiedFull"])
                 if p["unverifiedFull"] else ""))
    # One unified feed for every "this needs scrutiny" signal above (concentration, method-bias,
    # unverified quotes) -- see engine/assess.py::warnings. Each table still shows its own
    # per-position detail; this is just the single, consistent place their headline warning lands.
    if a.get("warnings"):
        L += ["", "WARNINGS"]
        for w in a["warnings"]:
            L.append("  ⚠ {} {}".format(w["headline"], w["detail"]))
    L += ["", "CRUXES  (● crux = active disagreement or shared pivot ; ◐ one camp leans on it ;"
          " ! left unanswered by a camp)"]
    order = sorted(a["cruxes"],
                   key=lambda c: (0 if c["isCrux"] else 1 if c.get("loadBearing") else 2, -c["spread"]))
    for c in order:
        mark = "●" if c["isCrux"] else ("◐" if c.get("oneSidedLoadBearing") else
                                        "!" if c.get("missingCounterassessment") else
                                        "·" if c.get("contestedWeight") else " ")
        tags = []
        if c.get("sharedPivot"):
            tags.append("both-high")
        if c.get("oneSidedLoadBearing"):
            tags.append("one camp only")
        if c.get("missingCounterassessment"):
            tags.append("a camp is silent")
        note = ("  [" + ", ".join(tags) + "]") if tags else ""
        L.append("  " + mark + " " + c["label"] + "  (spread {}){}".format(c["spread"], note))
    L += ["", "BLINDSPOTS"]
    for p in a["blindspots"]:
        miss = p["missingEvidence"] + p["missingPop"]
        L.append("  " + pad(p["label"], 22) +
                 ("skips: " + ", ".join(miss) if miss else "covers every type & subgroup"))
    print("\n".join(L))


# ---------------------------------------------------------------- assess
def cmd_assess(args):
    print(json.dumps(assess(read_json(args.kb)), indent=2, ensure_ascii=False))


def cmd_demo(args):
    """One-command tour: per-case collapse + headline cruxes, live viewer links, and the full
    reproducible benchmark (structure recall · collapse · adversarial robustness)."""
    here = os.path.dirname(os.path.abspath(__file__))
    links = {"covid": "ac81b4cae8d0", "eggs": "04329878656c", "blackholes": "c6c6ad01ec11"}
    print("GROUND KNOWLEDGE — demo      live, no setup: https://groundknowledge.org\n")
    for name in ("covid", "eggs", "blackholes"):
        kb = read_json(os.path.join(here, "cases", name + ".kb.json"))
        a = assess(kb)
        print("### %s — %s" % (name.upper(), kb["meta"]["question"]))
        for p in a["independence"]:
            print("   %-42s %2d sources -> %.1f confirmed-root coverage"
                  % (p["label"][:42], p["raw"], p["nEff"]))
        heads = [c["label"] for c in a["cruxes"] if c["isCrux"]]
        print("   headline cruxes: " + (", ".join(heads) or "—"))
        print("   view: https://groundknowledge.org/q/%s\n" % links[name])
    sys.path.insert(0, os.path.join(here, "eval"))    # run the reproducible benchmark inline
    import run_benchmark
    return run_benchmark.main([])


def cmd_gaps(args):
    """Show where this KB's evidence is thin — the steering wheel for gap-driven deep search."""
    from engine.gaps import find_gaps, gap_queries
    kb = read_json(args.kb)
    queries = gap_queries(kb, find_gaps(kb))
    if args.json:
        print(json.dumps(queries, indent=2, ensure_ascii=False))
        return
    if not queries:
        print("No gaps found — every position rests on independent primary evidence.")
        return
    print("{} gap(s) — aim the next search here:\n".format(len(queries)))
    icon = {3: "!!", 2: "! ", 1: "  "}
    for q in queries:
        g = q["gap"]
        print("  [{}] {:18} {}".format(icon.get(g["severity"], "  "), g["kind"], g["why"]))
        print("       search: {}".format(q["query"]))


# ---------------------------------------------------------------- add
def _review_prompt(kb_path, delta):
    """Interactive resolution of an ensemble position disagreement — the models split, so the
    person running the ingestion decides: shows the abstract and each model's proposal, then asks
    to pick a position or drop the paper. Non-interactive runs queue it for the console instead.
    Returns the delta to merge (position resolved), or None when dropped/queued."""
    import sys as _sys
    from engine import review
    src = delta.get("source") or {}
    ma = src.get("modelAgreement") or {}
    if not _sys.stdin.isatty():                       # no human present -> queue for the console
        kb = read_json(kb_path)
        if review.queue_for_review(kb, delta):
            write_json(kb_path, kb)
        print("⏸ models disagreed — queued for review (resolve in the console: cli.py ui): "
              + (src.get("title") or "")[:70])
        return None
    print("\n" + "=" * 72)
    print("MODELS DISAGREED on the position of:\n  {} ({})".format(
        src.get("title") or "(untitled)", src.get("year") or "?"))
    if src.get("url"):
        print("  " + src["url"])
    abstract = (delta.get("reviewText") or "").strip()
    if abstract:
        print("\nABSTRACT / LEAD (what the models read):\n" + abstract[:900])
    props = ma.get("proposals") or []
    print("\nPROPOSALS:")
    for i, p in enumerate(props, 1):
        print("  [{}] {}  ({} vote{})".format(
            i, p.get("position"), p.get("votes"), "" if p.get("votes") == 1 else "s"))
        if p.get("quote"):
            print('       "{}"'.format(p["quote"][:160]))
    print("  [d] drop this paper    [other] type any position label to use instead")
    while True:
        ans = input("your call> ").strip()
        if not ans:
            continue
        if ans.lower() == "d":
            print("dropped.")
            return None
        chosen = (props[int(ans) - 1]["position"]
                  if ans.isdigit() and 1 <= int(ans) <= len(props) else ans)
        src["position"] = chosen
        ma["flagged"] = False
        ma["resolvedBy"] = "human"
        ma["resolvedTo"] = chosen
        delta.pop("reviewText", None)
        return delta


def _apply_delta(kb_path, delta, verification_trusted=False):
    from engine import review
    if not verification_trusted:
        from engine.verify import strip_untrusted_verification
        delta = strip_untrusted_verification(delta)
    from engine.validate import delta_validation_errors
    errors = delta_validation_errors(delta)
    if errors:
        print("Delta rejected — {} formatting problem(s). Nothing was added:".format(len(errors)))
        _print_numbered(errors)
        print("Fix these and re-run `add`, or run `python cli.py lint <file>` first.")
        return False
    if review.needs_review(delta):
        delta = _review_prompt(kb_path, delta)
        if delta is None:
            return False
    kb = read_json(kb_path)
    before = assess(kb)
    report = merge_delta(kb, delta)
    if report.get("offTopic"):
        write_json(kb_path, kb)                           # persist the auditable refusal record
        print("Off-topic — not added: {}".format(report.get("reason", "doesn't bear on the question")))
        return False
    if report["duplicate"]:
        print("Duplicate source — already in KB, not added. (anti-flooding)")
        return False
    after = assess(kb)
    lines = diff_assessments(before, after)
    kb["log"][-1]["diff"] = lines  # persist the diff so the viewer can show a changelog
    write_json(kb_path, kb)
    print("Added {}  (KB now v{})".format(report["addedSource"], kb["meta"]["version"]))
    for k, lbl in (("newDatasets", "new datasets"), ("newPositions", "new positions"),
                   ("newFactors", "new factors")):
        if report[k]:
            print("  {}: {}".format(lbl, ", ".join(report[k])))
    print("\nWHAT CHANGED")
    print("\n".join("  " + x for x in lines) if lines else "  (no metric changes)")
    return True


def _merge_deltas(kb_path, deltas, verification_trusted=False):
    """Merge a list of deltas one at a time (each recomputes + diffs against the prior KB)."""
    from engine.merge import resolve_pending_refs
    added = 0
    for d in deltas:
        if _apply_delta(kb_path, d, verification_trusted=verification_trusted):
            added += 1
        print("")
    # second pass: resolve NEW-SRC forward references now that the whole batch is present (so a
    # mutual A<->B citation added in one array actually forms the cycle it claims -- see MECHANISM.md)
    kb = read_json(kb_path)
    n = resolve_pending_refs(kb)
    if n:
        write_json(kb_path, kb)
        print("resolved {} forward citation edge{} across the batch".format(n, "" if n == 1 else "s"))
    return added


# ---------------------------------------------------------------- curate (merge / rename)
def _curate_write(args, report):
    print(report["summary"] + "  (KB now v{})".format(report["version"]))
    if getattr(args, "build", False):
        _build_viewer([args.kb])


def cmd_merge(args):
    from engine import curate
    kb = read_json(args.kb)
    if args.type in ("position", "dataset", "factor"):
        fn = {"position": curate.merge_positions, "dataset": curate.merge_datasets,
              "factor": curate.merge_factors}[args.type]
        report = fn(kb, args.src, args.dst)
    else:
        report = curate.merge_vocab(kb, args.type, args.src, args.dst)
    write_json(args.kb, kb)
    _curate_write(args, report)


def cmd_rename(args):
    from engine import curate
    kb = read_json(args.kb)
    report = curate.rename(kb, args.type, args.ref, args.label)
    write_json(args.kb, kb)
    _curate_write(args, report)


def cmd_dedupe(args):
    """Remove duplicate SOURCES (same paper ingested under two links / title variants)."""
    from engine import curate
    kb = read_json(args.kb)
    report = curate.dedupe_sources(kb)
    if report.get("removed"):
        write_json(args.kb, kb)
        for r in report["removed"]:
            print("  removed {}  (dup of {})".format(r["removed"], r["kept"]))
    print(report["summary"] + ("  (KB now v{})".format(report["version"]) if report.get("removed") else ""))
    if getattr(args, "build", False):
        _build_viewer([args.kb])


def cmd_remove_source(args):
    """Remove an editorially irrelevant source with an auditable reason."""
    from engine import curate
    kb = read_json(args.kb)
    report = curate.remove_source(kb, args.ref, args.reason, args.by, args.replacement)
    write_json(args.kb, kb)
    _curate_write(args, report)


def cmd_move_source(args):
    """Re-file a source under the position its actual finding supports."""
    from engine import curate
    kb = read_json(args.kb)
    report = curate.move_source(kb, args.ref, args.position, args.reason, args.by)
    write_json(args.kb, kb)
    _curate_write(args, report)


def cmd_tidy(args):
    from engine import curate
    kb = read_json(args.kb)
    report = curate.tidy_labels(kb)
    write_json(args.kb, kb)
    _curate_write(args, report)


def cmd_dups(args):
    from engine import curate
    embed = None
    if getattr(args, "embed", False):
        from ingest.embed import embedder
        embed = embedder()
        if embed is None:
            print("(--embed: no OpenAI-compatible API key set; using lexical suggestions only)")
    sug = curate.suggest_duplicates(read_json(args.kb), threshold=args.threshold, embed=embed)
    if not sug:
        print("No likely duplicates above threshold {}.".format(args.threshold))
        return
    for kind, pairs in sug.items():
        print("\n{}:".format(kind.upper()))
        for p in pairs:
            print('  {:.2f} [{}]  "{}"  ⇄  "{}"'.format(
                p["sim"], p["reason"], p["a"]["label"], p["b"]["label"]))
    print('\nThese are SUGGESTIONS only — nothing is merged. Confirm one with:')
    print('  python cli.py merge <kb> <type> "<source label>" "<target label>"')


def cmd_confirm_dataset(args):
    from engine import curate
    kb = read_json(args.kb)
    embed = None
    if args.embed:
        from ingest.embed import embedder
        embed = embedder()
        if embed is None:
            print("(--embed: no OpenAI-compatible API key set; using lexical suggestions only)")
    report = curate.confirm_dataset(
        kb, args.ref, confirmed=not args.provisional, by=args.by, source=args.source,
        note=args.note, allow_similar=args.allow_similar, embed=embed)
    write_json(args.kb, kb)
    _curate_write(args, report)


def cmd_confirm_edge(args):
    from engine import curate
    kb = read_json(args.kb)
    report = curate.confirm_edge(kb, args.source, args.edge, confirmed=not args.provisional,
                                 by=args.by, note=args.note)
    write_json(args.kb, kb)
    _curate_write(args, report)


def cmd_verify(args):
    """Deterministically ground every stored quote against source text the CLI FETCHES ITSELF —
    the keyless equivalent of the check the keyed `ingest --apply` pipeline runs inline.

    `add` deliberately strips model-supplied verification (the trust boundary), so quotes written
    by an agent stay unchecked until this step re-fetches each source and grounds them. It verifies
    three quote kinds: each source's POSITION quote, each dependency EDGE quote (an exact match may
    promote a proposed root), and every FACTOR/crux claim quote. Trust comes from the CLI doing the
    fetch — never from agent-supplied text.
    """
    from ingest.extract import extract_text
    from engine.verify import apply_quote_verification
    kb = read_json(args.kb)
    sources = kb.get("sources", [])
    src_by_id = {s.get("id"): s for s in sources}
    text_cache = {}                                   # source id -> fetched text (or None)

    def text_for(src):
        sid = src.get("id")
        if sid in text_cache:
            return text_cache[sid]
        url = src.get("url")
        text = None
        if url:
            try:
                doc = extract_text(url)
                text = (doc or {}).get("text")
            except Exception:
                text = None
        text_cache[sid] = text
        return text

    counts = {"exact": 0, "fuzzy": 0, "missing": 0, "unfetched": 0}

    def ground(prov, src):
        if not (isinstance(prov, dict) and prov.get("quote")):
            return
        text = text_for(src)
        if not text:
            counts["unfetched"] += 1
            return
        res = apply_quote_verification(prov, text, source_title=src.get("title"),
                                       text_depth=src.get("textDepth", "unknown"),
                                       source_url=src.get("url"))
        counts[res["status"]] = counts.get(res["status"], 0) + 1

    for s in sources:                                 # position + dependency-edge quotes
        ground((s.get("provenance") or {}).get("position"), s)
        for edge in s.get("restsOn", []):
            if isinstance(edge, dict):
                ground(edge.get("provenance"), s)
    for f in kb.get("factors", []):                   # factor / crux claim quotes
        for entry in f.get("provenance", []):
            src = src_by_id.get(entry.get("source"))
            if src:
                ground(entry, src)

    # Rebuild the crux grid: a factor cell only counts a claim whose quote just verified exact,
    # so cruxes stay dark until their wording is grounded (engine/merge.recompute_factor_weights).
    from engine.merge import recompute_factor_weights
    recompute_factor_weights(kb)

    write_json(args.kb, kb)
    print("Quote check — exact {exact}, fuzzy {fuzzy}, missing {missing}"
          "  ({unfetched} quote(s) on sources that could not be re-fetched)".format(**counts))
    if counts["missing"]:
        print("  ⚠ 'missing' means the stored quote was not found in the re-fetched text — "
              "fix the quote or lower extractionConfidence.")
    if getattr(args, "build", False):
        _build_viewer([args.kb])


def cmd_add(args):
    data = read_json(args.delta)
    deltas = data if isinstance(data, list) else [data]  # accept one delta or a batch array
    if len(deltas) == 1:
        _apply_delta(args.kb, deltas[0])
    else:
        print("Merging {} deltas from {}\n".format(len(deltas), args.delta))
        added = _merge_deltas(args.kb, deltas)
        print("Done: {} of {} added.".format(added, len(deltas)))
    if getattr(args, "build", False):
        _build_viewer([args.kb])


# ---------------------------------------------------------------- init
def cmd_init(args):
    kb = empty_kb(args.id, args.question)
    if args.out:
        write_json(args.out, kb)
        print("wrote " + args.out)
    else:
        print(json.dumps(kb, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- build (viewer)
def _build_viewer(kb_paths, out=None):
    cases, order = {}, []
    for p in kb_paths:
        kb = read_json(p)
        cid = kb["meta"]["id"]
        cases[cid] = {"kb": kb, "assessment": assess(kb)}
        order.append(cid)
    bundle = {"order": order, "cases": cases}
    with open(os.path.join(ROOT, "viewer", "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    html = tpl.replace("/*__DATA__*/null", json_for_script(bundle))
    out = out or os.path.join(ROOT, "viewer", "index.html")
    atomic_write_text(out, html)
    print("Built {} ({} case{}) — open it in a browser.".format(
        out, len(order), "" if len(order) == 1 else "s"))


def cmd_build(args):
    _build_viewer(args.kb, args.out)


# ---------------------------------------------------------------- portal sync (push / pull)
# Git-like: do the LLM work locally with your own env key, then push the structured result to a
# shared portal. The portal does NO LLM work and holds no key — see app/portal.py.

def cmd_pull(args):
    """Fetch a question's canonical KB from the portal into a local file, stamping its lineage
    (meta.portal = {id, baseVersion}) so a later `push` knows what it's updating."""
    from app import client
    base = client.portal_url(args.portal)
    data = client.get_question(base, args.id)
    kb = data["kb"]
    kb.setdefault("meta", {})["portal"] = {"id": data["id"], "baseVersion": data["version"], "url": base}
    out = args.out or "cases/{}.kb.json".format(data["id"])
    write_json(out, kb)
    print("Pulled '{}' (v{}) -> {}".format(data["question"], data["version"], out))


def cmd_push(args):
    """Push a local KB to the portal. Creates a new question if the file has no portal lineage,
    otherwise updates it (optimistic version check on the baseVersion we pulled)."""
    from app import client
    base = client.portal_url(args.portal)
    token = client.optional_admin_token(args.token)   # keyless for a new/empty question; token only
                                                       # needed to replace a question that has sources
    kb = read_json(args.kb)
    who = args.as_ or "anonymous"
    portal_meta = (kb.get("meta") or {}).get("portal") or {}
    qid, expected = portal_meta.get("id"), portal_meta.get("baseVersion", 0)
    if not qid:                                   # first push -> create the question, then upload
        created = client.create_question(base, kb["meta"]["question"], who)
        qid, expected = created["id"], 0
        print("Created question {} on the portal.".format(qid))
    res = client.put_kb(base, qid, kb, expected, who, token=token)
    kb["meta"]["portal"] = {"id": qid, "baseVersion": res["version"], "url": base}
    write_json(args.kb, kb)                       # restamp lineage so the next push is clean
    print("Pushed '{}' -> {} (now v{}).".format(kb["meta"]["question"], qid, res["version"]))


def cmd_new(args):
    """Create a new question LOCALLY (git-style): a local case file you can harvest/deepen, then
    `push` to the portal when ready. The id is derived from the question unless you pass --id."""
    import uuid
    qid = args.id or uuid.uuid4().hex[:12]        # same id format the portal mints
    out = args.out or "cases/{}.kb.json".format(qid)
    if os.path.exists(out) and not args.force:
        raise SystemExit("{} already exists — pass --id, --out, or --force.".format(out))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    write_json(out, empty_kb(qid, args.question))
    print("Created local question '{}' -> {}".format(args.question, out))
    print("Next:  python cli.py harvest {}   then   python cli.py push {}".format(out, out))


def cmd_questions(args):
    """List/search questions on the portal."""
    from app import client
    base = client.portal_url(args.portal)
    rows = client.list_questions(base, args.search)
    if not rows:
        print("No questions found.")
        return
    for q in rows:
        c = q.get("counts", {})
        print("  {}  v{:<3} {:>3} sources  {}".format(
            q["id"], c.get("version", 0), c.get("sources", 0), q["question"]))


# ---------------------------------------------------------------- ingest / discover
def _write_prompt_files(prompts, stem, tail=True):
    """Write dry-run extraction prompt(s) to out/ and print short pointers — keeps huge
    prompts out of the terminal. tail=False suppresses the generic paste instructions when the
    caller prints its own."""
    if not prompts:
        print("No prompts written (no sources fetched successfully).")
        return
    outdir = os.path.join(ROOT, "out")
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i, p in enumerate(prompts, 1):
        name = stem + ".txt" if len(prompts) == 1 else "{}-{}.txt".format(stem, i)
        path = os.path.join(outdir, name)
        atomic_write_text(path, p)
        paths.append(os.path.relpath(path, ROOT))
    print("Wrote {} file(s):".format(len(paths)))
    for p in paths:
        print("  " + p)
    if tail:
        print("\nPaste each file's contents into any LLM. Save the JSON it returns (one object, or")
        print("an array for a batch), then:  python cli.py add <kb.json> <saved.json> --build")


def cmd_ingest(args):
    from ingest.pipeline import ingest_source
    kb = read_json(args.kb)
    res = ingest_source(args.target, kb, dry_run=args.dry_run)
    if args.dry_run:  # res is the prompt string
        _write_prompt_files([res], "ingest-prompt")
        return
    delta = res
    if args.apply:
        # write delta then merge so there is an auditable artifact on disk
        dpath = args.target.split("/")[-1].split("?")[0] or "source"
        dpath = os.path.join(ROOT, "cases", "delta-" + dpath + ".json")
        write_json(dpath, delta)
        print("delta → " + dpath)
        _apply_delta(args.kb, delta, verification_trusted=True)
        if getattr(args, "build", False):
            _build_viewer([args.kb])
    else:
        print(json.dumps(delta, indent=2, ensure_ascii=False))


def cmd_discover(args):
    from ingest.pipeline import discover
    kb = read_json(args.kb)
    found = discover(kb["meta"]["question"], k=args.k, dry_run=args.dry_run,
                     source=args.source, deep=args.deep)
    if found is None:
        return
    print(json.dumps(found, indent=2, ensure_ascii=False))


def _targets_from_args(args):
    """Collect ingest targets from positional URLs/paths and/or a --from candidates file
    (the JSON array produced by `discover`, or {"sources":[...]})."""
    targets = list(getattr(args, "target", None) or [])
    if getattr(args, "from_file", None):
        data = read_json(args.from_file)
        items = data if isinstance(data, list) else data.get("sources", [])
        for it in items:
            u = it.get("url") if isinstance(it, dict) else it
            if u:
                targets.append(u)
    return targets


def cmd_ui(args):
    """Launch the simple web console (no extra dependencies)."""
    from ui.server import run
    run(port=args.port, open_browser=not args.no_open)


def cmd_research(args):
    """The single-operation cold start. Emits ONE self-contained prompt (discovery + extraction)
    to paste into a browsing chatbot; it returns a JSON array you save and `add`. With --apply
    and an API key, runs it through web search and merges directly."""
    from ingest.pipeline import build_research_prompt
    prompt = build_research_prompt(read_json(args.kb), k=args.k)
    if not args.apply:
        _write_prompt_files([prompt], "research-prompt")
        print("\nThen save the JSON array the chatbot returns and run:")
        print("  python cli.py add {} <sources.json> --build".format(args.kb))
        return
    from ingest import llm
    from ingest.pipeline import _parse_json
    print("Researching (web search) — this is one LLM call; use a smaller --k if it truncates.")
    arr = _parse_json(llm.complete(prompt, web=True))
    if isinstance(arr, dict):
        arr = [arr]
    dpath = os.path.join(ROOT, "cases", "sources-research.json")
    write_json(dpath, arr)
    print("sources → {} ({} found)\n".format(dpath, len(arr)))
    added = _merge_deltas(args.kb, arr)
    print("Research complete: {} of {} added to {}.".format(added, len(arr), args.kb))
    if args.build:
        _build_viewer([args.kb])


def _write_labelling_bundle(kb_path, targets, max_text, empty_error, upload_msg, fetch_msg=None):
    """Fetch every target's text into ONE labelling bundle file to paste into a chatbot --
    the shared mechanics behind `ingest-batch --dry-run --bundle` and `import-citations
    --dry-run` (which is bundle-only). Callers keep their own exact wording; only the
    fetch/build/write-file logic is shared."""
    from ingest.pipeline import fetch_docs, build_batch_extract_prompt
    if fetch_msg:
        print(fetch_msg)
    docs, skipped = fetch_docs(targets)
    for s in skipped:
        print("  skipped (couldn't fetch): {}".format(s["target"]))
    if not docs:
        raise SystemExit(empty_error)
    bundle = build_batch_extract_prompt(read_json(kb_path), docs, max_text=max_text)
    _write_prompt_files([bundle], "label-sources", tail=False)
    print(upload_msg.format(kb=kb_path))


def _extract_and_report(kb_path, targets, batch, max_text, apply_, build, success_msg,
                        dpath=None):
    """Shared tail for a non-dry-run batch ingest: extract via ingest_batch, then either
    merge + report (--apply) or print the raw deltas as JSON. `ingest-batch` and
    `import-citations` differ only in where `targets` came from (a URL list/--from file vs a
    parsed citation export) -- this is everything after that point."""
    from ingest.pipeline import ingest_batch
    deltas = ingest_batch(targets, read_json(kb_path), batch=batch, max_text=max_text)
    if not apply_:
        print(json.dumps(deltas, indent=2, ensure_ascii=False))
        return deltas
    if dpath:
        write_json(dpath, deltas)
        print("deltas → {} ({} source(s))\n".format(dpath, len(deltas)))
    added = _merge_deltas(kb_path, deltas, verification_trusted=True)
    print(success_msg.format(added=added, total=len(deltas), kb=kb_path))
    if build:
        _build_viewer([kb_path])
    return deltas


def cmd_ingest_batch(args):
    """Ingest many sources with FEWER LLM calls — `--batch N` sources per call. Feed a
    discover JSON with --from, and/or list URLs/paths. --dry-run prints the combined prompt(s)
    to paste; --apply fetches, calls the model, and merges. Dedupe makes it resumable."""
    from ingest.pipeline import ingest_batch
    targets = _targets_from_args(args)
    if not targets:
        raise SystemExit("No sources. Pass URLs/paths and/or --from <candidates.json>.")
    # --bundle (manual path): fetch ALL sources and write ONE labelling file to upload to a
    # chatbot once, instead of several paste-sized prompts. Richer per-source text (it's a file).
    if args.dry_run and args.bundle:
        _write_labelling_bundle(
            args.kb, targets, args.max_text,
            fetch_msg="Fetching best available text for {} source(s)…".format(len(targets)),
            empty_error="Nothing fetched — no labelling file written.",
            upload_msg="\nUpload that ONE file to Claude/ChatGPT, tell it to follow the "
                       "instructions inside,\nthen save the JSON array it returns and run:  "
                       "python cli.py add {kb} <delta.json> --build")
        return
    print("Sources to ingest: {}  (batch size {})".format(len(targets), args.batch))
    if args.dry_run:  # several paste-sized prompts (one per batch), not the single --bundle file
        res = ingest_batch(targets, read_json(args.kb), dry_run=True,
                           batch=args.batch, max_text=args.max_text)
        _write_prompt_files(res, "ingest-batch-prompt")
        return
    dpath = os.path.join(ROOT, "cases", "deltas-batch.json") if args.apply else None
    _extract_and_report(args.kb, targets, args.batch, args.max_text, args.apply, args.build,
                        success_msg="Batch complete: {added} of {total} added to {kb}.",
                        dpath=dpath)


def cmd_import_citations(args):
    """Import a Zotero/Mendeley/EndNote export (.ris / .bib / .csl-json) as sources. Each entry's
    DOI/URL is fetched and labelled through the normal pipeline. --dry-run writes one labelling
    bundle file; --apply auto-labels with a key; default prints the deltas."""
    from ingest import citations
    with open(args.file, encoding="utf-8", errors="ignore") as f:
        cands = citations.parse(f.read(), filename=args.file)
    urls = [c["url"] for c in cands if c.get("url")]
    print("Parsed {} citation(s); {} have a DOI/URL to fetch.".format(len(cands), len(urls)))
    if not urls:
        raise SystemExit("No DOIs/URLs in that file — nothing to fetch.")
    if args.dry_run:
        _write_labelling_bundle(
            args.kb, urls, args.max_text,
            empty_error="Nothing fetched.",
            upload_msg="\nUpload that ONE file to your chatbot; paste the JSON array; then:  "
                       "python cli.py add {kb} <delta.json> --build")
        return
    _extract_and_report(args.kb, urls, args.batch, args.max_text, args.apply, args.build,
                        success_msg="Imported {added} of {total} into {kb}.")


def cmd_export(args):
    """Export a question's sources as a citation file (BibTeX / RIS / CSL-JSON) for Zotero etc."""
    from ingest import citations
    kb = read_json(args.kb)
    text, _mime, ext = citations.export(kb, args.format)
    if args.out:
        atomic_write_text(args.out, text)
        print("Wrote {} source(s) → {} ({})".format(len(kb.get("sources", [])), args.out, ext))
    else:
        print(text)


def cmd_harvest(args):
    """Cold start in one command: discover candidate sources, then ingest+merge each.
    Needs an API key (it makes LLM calls). Without one, use the manual path:
    `discover --dry-run` then `ingest <link> --dry-run` per source. Resumable — re-running
    skips sources already in the KB (dedupe)."""
    from ingest.pipeline import discover, ingest_source, ingest_batch
    kb0 = read_json(args.kb)
    question = kb0["meta"]["question"]
    have = [s.get("title") for s in kb0["sources"] if s.get("title")]
    print("Discovering sources for: " + question)
    found = discover(question, k=args.k, dry_run=False,
                     source=args.source, deep=args.deep, exclude=have) or []
    urls = [it.get("url") for it in found if it.get("url")]
    print("Found {} candidate source(s).\n".format(len(urls)))
    if args.batch > 1:
        # fewer LLM calls: extract several sources per call (trims per-source text)
        deltas = ingest_batch(urls, read_json(args.kb), batch=args.batch, max_text=args.max_text)
        added = _merge_deltas(args.kb, deltas, verification_trusted=True)
    else:
        # one call per source, full text — highest extraction fidelity
        added = 0
        for url in urls:
            print("=== {} ===".format(url))
            try:
                delta = ingest_source(url, read_json(args.kb), dry_run=False)
            except SystemExit as e:
                print("  skipped (extract/LLM failed): {}\n".format(e))
                continue
            if _apply_delta(args.kb, delta, verification_trusted=True):
                added += 1
            print("")
    print("Harvest complete: {} source(s) added to {}.".format(added, args.kb))
    if args.build:
        _build_viewer([args.kb])


def _choose_gaps(queries, tried, width, interactive):
    """Pick which thin spots to pursue this round. Non-interactive: the worst `width` untried.
    Interactive: list them and let the user choose (all / a subset / quit). Returns the chosen
    list, [] if none left, or None if the user asked to stop."""
    avail = [q for q in queries if q["query"].lower() not in tried]
    if not avail:
        return []
    if not interactive:
        return avail[:width]
    sev = {3: "!!", 2: "! ", 1: "  "}
    print("\nThin spots found:")
    for i, q in enumerate(avail, 1):
        g = q["gap"]
        print("  {:>2}. [{}] {:18} {}".format(i, sev.get(g["severity"], "  "), g["kind"], g["why"]))
    raw = input("\nWhich to explore? [Enter=all · e.g. 1,3,5 · q=quit]: ").strip().lower()
    if raw in ("q", "quit"):
        return None
    if raw in ("", "all", "a"):
        return avail
    picks = []
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(avail):
            picks.append(avail[int(tok) - 1])
    return picks or avail


def cmd_deepen(args):
    """Gap-driven deep search. Each round: find where evidence is THIN (engine/gaps.py), search
    those gaps, ingest what's new, then re-check. Stops when a round adds nothing or the round
    budget is hit — and ALWAYS reports the gaps still open. A plateau is a diagnostic, never a
    claim that the evidence is exhausted (more may be findable with new search angles)."""
    from engine.gaps import find_gaps, gap_queries
    from ingest.pipeline import discover, ingest_batch
    from engine.merge import source_key
    from ingest import llm

    budget = getattr(args, "budget", None)            # estimated USD cap; runs to cap or saturation
    if budget:
        llm.reset_usage()
        print("Thorough search — spending up to ${:.2f} (estimated), then stopping.".format(budget))
    max_rounds = 100 if budget else args.rounds       # budget mode: bounded by money, not rounds
    tried, total_added = set(), 0
    for rnd in range(1, max_rounds + 1):
        if budget and llm.usage()["usd"] >= budget:
            print("\nBudget reached (~${:.2f}). Stopping.".format(llm.usage()["usd"]))
            break
        gaps = gap_queries(read_json(args.kb), find_gaps(read_json(args.kb)))
        if budget and getattr(args, "broad", False):
            # broad mode: one wide sweep of the QUESTION per round (re-search; exclude grows).
            question = read_json(args.kb)["meta"]["question"]
            batch_q = [{"query": question, "gap": {"kind": "broad"}}]
        elif budget:
            # gaps mode: search the worst gaps; re-search is allowed (exclude grows each round).
            if not gaps:
                print("No gaps left — every position rests on independent primary evidence.")
                break
            batch_q = gaps[:args.width]
        else:
            if not gaps:
                print("No gaps left — every position rests on independent primary evidence.")
                break
            interactive = sys.stdin.isatty() and not args.all
            batch_q = _choose_gaps(gaps, tried, args.width, interactive)
            if batch_q is None:                  # user chose to quit
                print("Stopped at your request.")
                break
            if not batch_q:
                print("Round {}: every current gap-query already tried; {} gap(s) remain but need "
                      "fresh search angles (try --source both).".format(rnd, len(gaps)))
                break
            for q in batch_q:
                tried.add(q["query"].lower())
        print("\n=== Round {} — {} search(es) ===".format(rnd, len(batch_q)))
        kb_now = read_json(args.kb)
        existing = {source_key(s) for s in kb_now["sources"]}
        have = [s.get("title") for s in kb_now["sources"] if s.get("title")]
        urls = []
        for q in batch_q:
            if budget and llm.usage()["usd"] >= budget:
                break
            print("  search [{}]: {}".format(q["gap"]["kind"], q["query"][:68]))
            qk = max(args.per, 15) if q["gap"]["kind"] == "broad" else args.per  # wider for broad
            try:
                cands = discover(q["query"], k=qk, source=args.source, deep=False,
                                 exclude=have) or []
            except Exception as e:               # one bad/slow search must not stall the run
                print("    search failed, skipping: {}".format(str(e)[:80]))
                continue
            for it in cands:
                u = it.get("url")
                if u and source_key({"url": u}) not in existing:
                    existing.add(source_key({"url": u})); urls.append(u)
        if not urls:
            print("  no NEW candidates this round — saturated.")
            break
        print("  ingesting {} new candidate(s)…".format(len(urls)))
        added = _merge_deltas(args.kb, ingest_batch(urls, read_json(args.kb),
                                                    batch=args.batch, max_text=args.max_text),
                                verification_trusted=True)
        total_added += added
        remaining = find_gaps(read_json(args.kb))
        spent = "  ~${:.2f} spent".format(llm.usage()["usd"]) if budget else ""
        print("  round {}: +{} source(s); {} gap(s) remaining.{}".format(
            rnd, added, len(remaining), spent))
        if added == 0:
            print("  nothing merged — stopping (diminishing returns).")
            break

    final = gap_queries(read_json(args.kb), find_gaps(read_json(args.kb)))
    spend = "  Estimated spend: ${:.2f} over {} LLM call(s).".format(
        llm.usage()["usd"], llm.usage()["calls"]) if budget else ""
    print("\nDeep search done: +{} source(s) total. {} gap(s) still open.{}".format(
        total_added, len(final), spend))
    if final:
        print("Still thin (more may be findable — NOT a completeness claim):")
        for q in final[:6]:
            print("  - {}: {}".format(q["gap"]["kind"], q["gap"].get("why", "")))
    if args.build:
        _build_viewer([args.kb])


def main():
    from app.env import load_dotenv
    load_dotenv()  # pick up keys/config from .env before any command (and before llm import)
    ap = argparse.ArgumentParser(prog="epistemic")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("id"); s.add_argument("question")
    s.add_argument("--out"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("show"); s.add_argument("kb"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("assess"); s.add_argument("kb"); s.set_defaults(fn=cmd_assess)
    s = sub.add_parser("demo", help="one-command tour: per-case collapse + cruxes + full benchmark")
    s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("validate", help="validate schema v2 plus IDs and cross-references")
    s.add_argument("kb"); s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("lint", help="pre-flight an agent-written delta (or KB) WITHOUT merging — numbered errors")
    s.add_argument("path"); s.set_defaults(fn=cmd_lint)
    s = sub.add_parser("doctor", help="health check: structure + completeness + trust hygiene of a KB")
    s.add_argument("kb"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("mark-curated", help="admin: mark a question as officially curated & maintained (trusted stewardship label)")
    s.add_argument("kb"); s.add_argument("--by", help="curator/admin identity (required unless --off)")
    s.add_argument("--note"); s.add_argument("--off", action="store_true", help="remove the curated label")
    s.set_defaults(fn=cmd_mark_curated)
    s = sub.add_parser("migrate", help="additively migrate a v1 KB to schema v2")
    s.add_argument("kb"); migration_dest = s.add_mutually_exclusive_group()
    migration_dest.add_argument("--out"); migration_dest.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_migrate)
    s = sub.add_parser("gaps", help="show where evidence is thin (steers gap-driven deep search)")
    s.add_argument("kb"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_gaps)
    s = sub.add_parser("deepen", help="gap-driven deep search: find thin spots, search them, repeat")
    s.add_argument("kb"); s.add_argument("--rounds", type=int, default=3)
    s.add_argument("--width", type=int, default=4, help="thin spots targeted per round")
    s.add_argument("--per", type=int, default=6, help="candidates fetched per gap search")
    s.add_argument("--source", choices=["api", "web", "both"], default="web")
    s.add_argument("--budget", type=float,
                   help="THOROUGH mode: keep going until ~$N (estimated) is spent or it saturates")
    s.add_argument("--broad", action="store_true",
                   help="with --budget: wide-harvest the QUESTION instead of searching gaps")
    s.add_argument("--all", action="store_true", help="pursue all thin spots without prompting")
    s.add_argument("--batch", type=int, default=5)
    s.add_argument("--max-text", dest="max_text", type=int, default=None,
                   help="cap each source's text at N chars per LLM call (default: send the full fetched text)")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_deepen)
    s = sub.add_parser("add"); s.add_argument("kb"); s.add_argument("delta")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("verify", help="re-fetch each source and ground its quotes (positions, edges, factor/crux claims) — the keyless quote check")
    s.add_argument("kb"); s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("build"); s.add_argument("kb", nargs="+"); s.add_argument("--out")
    s.set_defaults(fn=cmd_build)
    s = sub.add_parser("ingest"); s.add_argument("kb"); s.add_argument("target")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--apply", action="store_true")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("discover"); s.add_argument("kb"); s.add_argument("--k", type=int, default=8)
    s.add_argument("--source", choices=["api", "web", "both"], default="web",
                   help="api=OpenAlex (no key), web=LLM web search, both=merge")
    s.add_argument("--deep", action="store_true", help="thorough multi-search web pass (with --source web/both)")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("research"); s.add_argument("kb"); s.add_argument("--k", type=int, default=20)
    s.add_argument("--apply", action="store_true"); s.add_argument("--build", action="store_true")
    s.set_defaults(fn=cmd_research)
    s = sub.add_parser("ingest-batch"); s.add_argument("kb"); s.add_argument("target", nargs="*")
    s.add_argument("--from", dest="from_file", help="discover JSON (array of {url,...}) to ingest")
    s.add_argument("--batch", type=int, default=5, help="sources per LLM call (default 5)")
    s.add_argument("--max-text", dest="max_text", type=int, default=None,
                   help="cap each source's text at N chars per call (default: send the full fetched text)")
    s.add_argument("--bundle", action="store_true",
                   help="with --dry-run: fetch all sources into ONE labelling file to upload to a chatbot")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--apply", action="store_true")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_ingest_batch)
    s = sub.add_parser("ui"); s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true"); s.set_defaults(fn=cmd_ui)
    TYPES = ["position", "dataset", "factor", "evidence", "population"]
    s = sub.add_parser("merge", help="fold a duplicate entity into another (id, label, or substring)")
    s.add_argument("kb"); s.add_argument("type", choices=TYPES)
    s.add_argument("src"); s.add_argument("dst"); s.add_argument("--build", action="store_true")
    s.set_defaults(fn=cmd_merge)
    s = sub.add_parser("rename"); s.add_argument("kb"); s.add_argument("type", choices=TYPES)
    s.add_argument("ref"); s.add_argument("label"); s.add_argument("--build", action="store_true")
    s.set_defaults(fn=cmd_rename)
    s = sub.add_parser("dedupe", help="remove duplicate SOURCES (same paper ingested twice)")
    s.add_argument("kb"); s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_dedupe)
    s = sub.add_parser("remove-source", help="remove an irrelevant source with a versioned audit record")
    s.add_argument("kb"); s.add_argument("ref", help="source id, exact title, or unique title substring")
    s.add_argument("--reason", required=True, help="why the source does not belong in this case")
    s.add_argument("--by", required=True, help="curator name or stable identifier")
    s.add_argument("--replacement", help="retained source to receive dependency references")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_remove_source)
    s = sub.add_parser("move-source", help="re-file a source under a different existing position")
    s.add_argument("kb"); s.add_argument("ref", help="source id, exact title, or unique title substring")
    s.add_argument("position", help="position id, exact label, or unique label substring")
    s.add_argument("--reason", required=True, help="why the current position is incorrect")
    s.add_argument("--by", required=True, help="curator name or stable identifier")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_move_source)
    s = sub.add_parser("dups", help="list likely-duplicate entities to merge (suggestions only)")
    s.add_argument("kb"); s.add_argument("--threshold", type=float, default=0.4)
    s.add_argument("--embed", action="store_true",
                   help="also surface SEMANTIC paraphrase candidates via embeddings (needs an "
                        "OpenAI-compatible API key; advisory, never auto-merged)")
    s.set_defaults(fn=cmd_dups)
    s = sub.add_parser("confirm-dataset", help="admit a proposed evidence base with an auditable curator record")
    s.add_argument("kb"); s.add_argument("ref")
    s.add_argument("--by", required=True, help="curator name or stable identifier")
    s.add_argument("--source", help="source id supporting the confirmation")
    s.add_argument("--note", help="reason/evidence for the decision")
    s.add_argument("--provisional", action="store_true", help="remove confirmation instead")
    s.add_argument("--embed", action="store_true", help="check semantic duplicate suggestions before confirming")
    s.add_argument("--allow-similar", action="store_true", help="override a duplicate suggestion (requires --note)")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_confirm_dataset)
    s = sub.add_parser("confirm-edge", help="admit one source→root/citation support link")
    s.add_argument("kb"); s.add_argument("source", help="source id, title, or unique title substring")
    s.add_argument("edge", help="exact restsOn ref (dataset id or src:source-id)")
    s.add_argument("--by", required=True, help="curator name or stable identifier")
    s.add_argument("--note", help="reason/evidence for the decision")
    s.add_argument("--provisional", action="store_true", help="remove this edge admission")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_confirm_edge)
    s = sub.add_parser("tidy", help="prettify id-style / slug labels for display")
    s.add_argument("kb"); s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_tidy)
    s = sub.add_parser("harvest"); s.add_argument("kb"); s.add_argument("--k", type=int, default=8)
    s.add_argument("--batch", type=int, default=1, help="sources per LLM call; >1 = fewer calls")
    s.add_argument("--max-text", dest="max_text", type=int, default=None,
                   help="cap each source's text at N chars per call (default: send the full fetched text)")
    s.add_argument("--source", choices=["api", "web", "both"], default="web",
                   help="api=OpenAlex (no key), web=LLM web search, both=merge")
    s.add_argument("--deep", action="store_true", help="thorough multi-search web pass (with --source web/both)")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_harvest)

    # portal sync (push/pull) — portal URL from --portal or EPISTEMIC_PORTAL
    s = sub.add_parser("pull"); s.add_argument("id"); s.add_argument("--out")
    s.add_argument("--portal"); s.set_defaults(fn=cmd_pull)
    s = sub.add_parser("push"); s.add_argument("kb")
    s.add_argument("--portal"); s.add_argument("--as", dest="as_", help="contributor name")
    s.add_argument("--token", help="portal admin token (or set EPISTEMIC_ADMIN_TOKEN)")
    s.set_defaults(fn=cmd_push)
    s = sub.add_parser("new", help="create a new question locally (git-style); push when ready")
    s.add_argument("question"); s.add_argument("--id"); s.add_argument("--out")
    s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("questions"); s.add_argument("--search"); s.add_argument("--portal")
    s.set_defaults(fn=cmd_questions)

    # citation interchange (Zotero / Mendeley / EndNote: .ris / .bib / .csl-json)
    s = sub.add_parser("import-citations"); s.add_argument("kb"); s.add_argument("file")
    s.add_argument("--batch", type=int, default=5)
    s.add_argument("--max-text", dest="max_text", type=int, default=None,
                   help="cap each source's text at N chars per call (default: send the full fetched text)")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--apply", action="store_true")
    s.add_argument("--build", action="store_true"); s.set_defaults(fn=cmd_import_citations)
    s = sub.add_parser("export"); s.add_argument("kb")
    s.add_argument("--format", choices=["bibtex", "ris", "csl"], default="bibtex")
    s.add_argument("--out"); s.set_defaults(fn=cmd_export)

    args = ap.parse_args()
    return args.fn(args)          # propagate a command's exit code (e.g. `demo` returns benchmark PASS/FAIL)


if __name__ == "__main__":
    sys.exit(main())
