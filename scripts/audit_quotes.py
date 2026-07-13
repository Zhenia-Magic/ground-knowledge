#!/usr/bin/env python3
"""Re-fetch every case source and recompute all quotation trust fields.

This deliberately uses no LLM.  It checks stored wording against the deterministic text extractor,
never rewrites an approximate match, and leaves altered wording visible but non-verified.  Full fetched documents are cached only
outside the repository; case files retain hashes/audit results, never copyrighted bodies.
"""
import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.verify import apply_quote_verification, is_verified_exact  # noqa: E402
from ingest.extract import extract_text  # noqa: E402

DEFAULT_CASES = sorted((ROOT / "cases").glob("*.kb.json"))


def _cache_path(cache_dir, url):
    return pathlib.Path(cache_dir) / (hashlib.sha256(url.encode()).hexdigest() + ".json.gz")


def _fetch(url, cache_dir):
    path = _cache_path(cache_dir, url)
    if path.exists():
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            pass
    try:
        doc = extract_text(url)
        result = {"ok": True, "doc": doc}
    except BaseException as exc:  # extract_text uses SystemExit for a clean fetch failure
        result = {"ok": False, "error": str(exc)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(result, handle)
    return result


def _all_factor_provenance(kb):
    out = {}
    for factor in kb.get("factors", []):
        for claim in factor.get("provenance") or []:
            if isinstance(claim, dict) and claim.get("source"):
                out.setdefault(claim["source"], []).append(("factor:" + factor.get("id", "?"), claim))
    return out


def _audit_provenance(provenance, doc, title, repair_threshold=None):
    old = provenance.get("quote") if isinstance(provenance, dict) else None
    if not old:
        return {"status": "empty", "changed": False}
    result = apply_quote_verification(
        provenance, doc.get("text") or "", source_title=title,
        text_depth=doc.get("kind", "unknown"), source_url=doc.get("url"))
    return {"status": (result or {}).get("status", "missing"), "changed": old != provenance.get("quote"),
            "repaired": False, "old": old, "new": provenance.get("quote")}


def _strip_status(provenance):
    if isinstance(provenance, dict):
        provenance.pop("verifiedQuote", None)
        provenance.pop("quoteVerification", None)


def _source_quote_objects(source, factor_map):
    objects = []
    for field, provenance in (source.get("provenance") or {}).items():
        if field != "restsOn" and isinstance(provenance, dict) and provenance.get("quote"):
            objects.append(("source:" + field, provenance))
    for index, edge in enumerate(source.get("restsOn") or []):
        if isinstance(edge, dict) and isinstance(edge.get("provenance"), dict):
            if edge["provenance"].get("quote"):
                objects.append(("edge:{}".format(index), edge["provenance"]))
    objects.extend(factor_map.get(source.get("id"), []))
    return objects


def _migrate_legacy_dependency(source, doc, repair_threshold):
    provenance = (source.get("provenance") or {}).pop("restsOn", None)
    if not isinstance(provenance, dict) or not provenance.get("quote"):
        return None
    direct = [(i, edge) for i, edge in enumerate(source.get("restsOn") or [])
              if not str(edge.get("ref") if isinstance(edge, dict) else edge).lower().startswith("src:")]
    if len(direct) != 1:
        return {"status": "discarded-ambiguous", "changed": True}
    result = _audit_provenance(provenance, doc, source.get("title"), repair_threshold)
    if not is_verified_exact(provenance):
        return {"status": "discarded-unverified", "changed": True}
    index, edge = direct[0]
    if isinstance(edge, dict):
        edge["provenance"] = provenance
    else:
        source["restsOn"][index] = {"ref": edge, "provenance": provenance}
    result["status"] = "migrated-exact"
    return result


def audit_case(path, fetched, repair_threshold):
    kb = json.loads(path.read_text(encoding="utf-8"))
    factors = _all_factor_provenance(kb)
    rows = []
    for source in kb.get("sources", []):
        url = source.get("url")
        fetch = fetched.get(url) if url else None
        if not fetch or not fetch.get("ok"):
            source["textDepth"] = "unknown"
            for _, provenance in _source_quote_objects(source, factors):
                _strip_status(provenance)
            legacy = (source.get("provenance") or {}).get("restsOn")
            _strip_status(legacy)
            rows.append({"id": source.get("id"), "title": source.get("title"), "fetch": "failed",
                         "error": (fetch or {}).get("error", "missing URL")})
            continue

        doc = fetch["doc"]
        source["textDepth"] = doc.get("kind", "unknown")
        quote_rows = []
        for field, provenance in _source_quote_objects(source, factors):
            result = _audit_provenance(provenance, doc, source.get("title"), repair_threshold)
            result["field"] = field
            quote_rows.append(result)
        legacy = _migrate_legacy_dependency(source, doc, repair_threshold)
        if legacy:
            legacy["field"] = "legacy:restsOn"
            quote_rows.append(legacy)
        rows.append({"id": source.get("id"), "title": source.get("title"),
                     "fetch": doc.get("kind", "unknown"), "quotes": quote_rows})

    # Re-running an audit replaces its prior audit marker; source history remains elsewhere and a
    # verification refresh should not manufacture a chain of content-change versions.
    kb["log"] = [entry for entry in kb.get("log", []) if entry.get("action") != "quote-reaudit"]
    kb["log"].append({
        "version": kb.get("meta", {}).get("version", 0), "action": "quote-reaudit",
        "method": "verbatim-sentence-v2", "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sources": len(kb.get("sources", []))})
    return kb, rows


def _summary(rows):
    counts = {}
    for row in rows:
        if row.get("fetch") == "failed":
            counts["fetch-failed"] = counts.get("fetch-failed", 0) + 1
        for quote in row.get("quotes", []):
            status = quote.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
            if quote.get("repaired"):
                counts["repaired-to-exact"] = counts.get("repaired-to-exact", 0) + 1
    return counts


def restore_unsafe_repairs(path, prior_case_report):
    """Undo the first audit implementation's fuzzy-candidate rewrites from its report."""
    kb = json.loads(path.read_text(encoding="utf-8"))
    source_map = {s.get("id"): s for s in kb.get("sources", [])}
    factor_map = {f.get("id"): f for f in kb.get("factors", [])}
    restored = 0
    for row in prior_case_report.get("sources", []):
        source = source_map.get(row.get("id"))
        if not source:
            continue
        for quote in row.get("quotes", []):
            # Keep safe exact-fragment -> complete-sentence canonicalisation. Undo every explicit
            # fuzzy repair and every changed candidate that failed to become exact.
            if not quote.get("old") or not (quote.get("repaired") or
                                             (quote.get("changed") and quote.get("status") != "exact")):
                continue
            field = quote.get("field", "")
            provenance = None
            if field.startswith("source:"):
                provenance = (source.get("provenance") or {}).get(field.split(":", 1)[1])
            elif field.startswith("edge:"):
                try:
                    edge = (source.get("restsOn") or [])[int(field.split(":", 1)[1])]
                    provenance = edge.get("provenance") if isinstance(edge, dict) else None
                except (IndexError, ValueError):
                    pass
            elif field.startswith("factor:"):
                factor = factor_map.get(field.split(":", 1)[1])
                provenance = next((p for p in (factor or {}).get("provenance", [])
                                   if p.get("source") == source.get("id")), None)
            elif field == "legacy:restsOn":
                direct = [edge for edge in source.get("restsOn") or []
                          if not str(edge.get("ref") if isinstance(edge, dict) else edge).lower().startswith("src:")]
                if len(direct) == 1 and isinstance(direct[0], dict):
                    provenance = direct[0].get("provenance")
            if isinstance(provenance, dict):
                provenance["quote"] = quote["old"]
                _strip_status(provenance)
                restored += 1
    path.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return restored


def write_markdown_report(cases, output):
    lines = ["# Quote audit", "",
             "Generated from the current case files by `scripts/audit_quotes.py`.", "",
             "A checkmark means one complete verbatim sentence was found in one fetched-text "
             "segment and is bound to both the displayed-sentence hash and checked-text hash. "
             "`fuzzy`, `missing`, and `unchecked` wording is not rendered as a quotation and cannot "
             "automatically confirm an evidence root.", "",
             "| Case | Sources | Position exact | Fuzzy | Missing | Unchecked |", "|---|---:|---:|---:|---:|---:|"]
    aggregate = {"exact": 0, "fuzzy": 0, "missing": 0, "unchecked": 0}
    overall = {"exact": 0, "fuzzy": 0, "missing": 0, "unchecked": 0}
    non_exact = []
    for path in cases:
        kb = json.loads(path.read_text(encoding="utf-8"))
        counts = dict(aggregate)
        for key in counts:
            counts[key] = 0
        for item in kb.get("sources", []):
            provenance = (item.get("provenance") or {}).get("position") or {}
            if not provenance.get("quote"):
                continue
            status = "exact" if is_verified_exact(provenance) else provenance.get("verifiedQuote") or "unchecked"
            counts[status] = counts.get(status, 0) + 1
            aggregate[status] = aggregate.get(status, 0) + 1
            if status != "exact":
                non_exact.append((path.name, status, item.get("title"), item.get("url")))
            all_provenance = [p for p in (item.get("provenance") or {}).values()
                              if isinstance(p, dict) and p.get("quote")]
            all_provenance += [edge["provenance"] for edge in item.get("restsOn") or []
                               if isinstance(edge, dict) and isinstance(edge.get("provenance"), dict)
                               and edge["provenance"].get("quote")]
            for claim in all_provenance:
                claim_status = "exact" if is_verified_exact(claim) else claim.get("verifiedQuote") or "unchecked"
                overall[claim_status] = overall.get(claim_status, 0) + 1
        for factor in kb.get("factors", []):
            for claim in factor.get("provenance") or []:
                if claim.get("quote"):
                    claim_status = "exact" if is_verified_exact(claim) else claim.get("verifiedQuote") or "unchecked"
                    overall[claim_status] = overall.get(claim_status, 0) + 1
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            path.name, len(kb.get("sources", [])), counts["exact"], counts["fuzzy"],
            counts["missing"], counts["unchecked"]))
    lines += ["", "Position excerpts: **{exact} exact of {total}**; {fuzzy} fuzzy, {missing} missing, "
              "{unchecked} unchecked.".format(total=sum(aggregate.values()), **aggregate), "",
              "All stored excerpts (position, dependency, and factor): **{exact} exact of {total}**; "
              "{fuzzy} fuzzy, {missing} missing, {unchecked} unchecked. Every non-exact item is "
              "visibly downgraded and excluded from automatic root confirmation.".format(
                  total=sum(overall.values()), **overall), "",
              "## Remaining non-exact position wording", "",
              "These entries remain visible as unquoted summaries with a warning; they are never silently certified.", ""]
    for case, status, title, url in non_exact:
        lines.append("- `{}` · **{}** · [{}]({})".format(case, status, title or "Untitled", url or "#"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", type=pathlib.Path, default=DEFAULT_CASES)
    parser.add_argument("--cache", default="/tmp/epistemic-quote-audit")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=pathlib.Path, default=ROOT / "eval" / "QUOTE_AUDIT.json")
    parser.add_argument("--markdown-report", type=pathlib.Path, default=ROOT / "eval" / "QUOTE_AUDIT.md")
    parser.add_argument("--restore-unsafe-from", type=pathlib.Path)
    args = parser.parse_args()

    cases = [p if p.is_absolute() else ROOT / p for p in args.cases]
    if args.restore_unsafe_from:
        prior = json.loads(args.restore_unsafe_from.read_text(encoding="utf-8"))
        for path in cases:
            restored = restore_unsafe_repairs(path, (prior.get("cases") or {}).get(path.name, {}))
            print("restored {} unsafe candidate rewrites in {}".format(restored, path.name))
    urls = []
    for path in cases:
        kb = json.loads(path.read_text(encoding="utf-8"))
        urls.extend(s.get("url") for s in kb.get("sources", []) if s.get("url"))
    urls = sorted(set(urls))
    fetched = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(_fetch, url, args.cache): url for url in urls}
        for number, future in enumerate(concurrent.futures.as_completed(jobs), 1):
            url = jobs[future]
            fetched[url] = future.result()
            print("[{}/{}] {} {}".format(number, len(jobs), "ok" if fetched[url].get("ok") else "FAIL", url),
                  flush=True)

    report = {"method": "verbatim-sentence-v2", "automaticFuzzyRepair": False,
              "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(), "cases": {}}
    for path in cases:
        kb, rows = audit_case(path, fetched, None)
        report["cases"][path.name] = {"summary": _summary(rows), "sources": rows}
        if args.write:
            path.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(path.name, _summary(rows), flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown_report(cases, args.markdown_report)


if __name__ == "__main__":
    main()
