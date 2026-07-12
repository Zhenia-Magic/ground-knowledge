#!/usr/bin/env python3
"""Backfill audit metadata on already curator-confirmed evidence bases.

This does NOT newly verify a dependency quote. It preserves an existing curator decision while
making the actor, time, and a direct supporting source explicit. Dry-run by default.

  python scripts/backfill_confirmation_audit.py cases/*.kb.json --by project-curator
  python scripts/backfill_confirmation_audit.py cases/*.kb.json --by project-curator --apply
"""
import argparse
import datetime
import json
import os


def _ref(edge):
    return str(edge.get("ref") or "").strip() if isinstance(edge, dict) else str(edge or "").strip()


def _supporting_source(kb, dataset_id):
    candidates = []
    depth = {"full": 3, "partial": 2, "abstract": 1, "unknown": 0}
    for source in kb.get("sources", []):
        matching = [e for e in source.get("restsOn") or [] if _ref(e) == dataset_id]
        if not matching:
            continue
        verified = any(isinstance(e, dict) and
                       (e.get("provenance") or {}).get("verifiedQuote") in ("exact", "fuzzy")
                       for e in matching)
        candidates.append((verified, depth.get(source.get("textDepth"), 0), source.get("id")))
    return max(candidates)[2] if candidates else None


def backfill(kb, actor, timestamp):
    changed = []
    for d in kb.get("datasets", []):
        c = d.get("confirmation")
        legacy = bool(d.get("confirmed"))
        already_confirmed = legacy or (isinstance(c, dict) and c.get("status") == "confirmed")
        if not already_confirmed:
            continue
        c = dict(c) if isinstance(c, dict) else {}
        complete = c.get("method") == "curator" and c.get("by") and c.get("ts")
        if complete and not legacy:
            continue
        source = c.get("source") or _supporting_source(kb, d["id"])
        record = {"status": "confirmed", "method": "curator", "by": c.get("by") or actor,
                  "ts": c.get("ts") or timestamp,
                  "note": c.get("note") or
                  "Audit metadata backfill: preserves the case's prior curator-confirmed decision; "
                  "the source is a direct supporting source, not a verified dependency quote."}
        if source:
            record["source"] = source
        d["confirmation"] = record
        d.pop("confirmed", None)
        changed.append(d["id"])
    if changed:
        version = (kb.get("meta", {}).get("version", 0) or 0) + 1
        kb["meta"]["version"] = version
        kb["meta"]["updated"] = timestamp
        kb.setdefault("log", []).append({
            "version": version, "action": "backfill-confirmation-audit-metadata", "by": actor,
            "ts": timestamp, "datasets": changed,
            "summary": "added actor/time/direct-source metadata to {} existing curator confirmations"
                       .format(len(changed)),
        })
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--by", required=True, help="stable curator identity recorded in each case")
    ap.add_argument("--timestamp", help="ISO-8601 time (default: now, UTC)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    ts = args.timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            kb = json.load(f)
        changed = backfill(kb, args.by, ts)
        print("{}: {} confirmation record(s){}".format(
            path, len(changed), " updated" if args.apply else " would update"))
        if changed and args.apply:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(kb, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
