#!/usr/bin/env python3
"""Backfill explicit support-edge admissions for the repository's already curated case artifacts.

This is a one-time schema-hardening migration. It does not claim quote verification: each record is
labelled ``legacy-migration`` and says only that the existing authored relationship was adopted when
source→root admission became separate from root-identity confirmation.
"""
import argparse
import glob
import json
import os


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD = {
    "status": "confirmed",
    "method": "legacy-migration",
    "by": "repository-migration",
    "ts": "2026-07-14T00:00:00Z",
    "note": "Existing curated relationship adopted during edge-admission schema migration; not quote verification.",
}


def migrate(kb):
    changed = 0
    for source in kb.get("sources", []):
        edges = []
        for edge in source.get("restsOn") or []:
            if isinstance(edge, dict):
                item = edge
            else:
                item = {"ref": edge}
            if not item.get("admission"):
                item["admission"] = dict(RECORD)
                changed += 1
            edges.append(item)
        source["restsOn"] = edges
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if a case still needs migration")
    args = ap.parse_args(argv)
    pending = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "cases", "*.kb.json"))):
        with open(path, encoding="utf-8") as f:
            kb = json.load(f)
        changed = migrate(kb)
        pending += changed
        print("{}: {} edge(s) {}".format(os.path.basename(path), changed,
              "need admission" if args.check else "migrated"))
        if changed and not args.check:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(kb, f, ensure_ascii=False, indent=2)
                f.write("\n")
    return 1 if args.check and pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
