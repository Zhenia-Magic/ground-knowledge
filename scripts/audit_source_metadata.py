#!/usr/bin/env python3
"""Fetch candidate scholarly metadata for every case source without mutating the KBs.

Uses OpenAlex's public API. Results include a conservative title-match score so a curator can
distinguish a genuine identifier match from a noisy title search before applying anything.

    python scripts/audit_source_metadata.py cases/*.kb.json --out /tmp/source-metadata.json
"""
import argparse
import glob
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.io import atomic_write_json  # noqa: E402

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()


SELECT = "doi,title,publication_year,authorships,primary_location,funders,type"
DOI_RE = re.compile(r"10\.\d{4,9}/[^?#\s]+", re.I)


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def clean_title(value):
    value = str(value or "")
    if " — " in value:
        value = value.split(" — ", 1)[1]
    value = re.sub(r"^\[PDF\]\s*", "", value, flags=re.I)
    # Curated case titles often append a venue, cohort, or explanatory gloss in parentheses.  It is
    # useful to readers but harms catalogue lookup, so remove trailing parentheticals for the query.
    while re.search(r"\s*\([^()]*\)\s*$", value):
        value = re.sub(r"\s*\([^()]*\)\s*$", "", value)
    return value.strip(" .")


def similarity(a, b):
    aa, bb = set(norm(a).split()), set(norm(b).split())
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def doi_from_url(url):
    m = DOI_RE.search(urllib.parse.unquote(str(url or "")))
    return m.group(0).rstrip("/).,;\"").lower() if m else None


def get_json(url, retries=5):
    req = urllib.request.Request(url, headers={
        "User-Agent": "GroundKnowledge-source-audit/1.0 (mailto:opensource@groundknowledge.org)"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25, context=SSL_CONTEXT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if attempt + 1 == retries:
                raise
            wait = float(exc.headers.get("Retry-After") or (5 * (attempt + 1))) \
                if exc.code == 429 else 1.0 + attempt
            time.sleep(wait)
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(1.0 + attempt)


def openalex(source):
    doi = doi_from_url(source.get("url"))
    if doi:
        key = urllib.parse.quote("https://doi.org/" + doi, safe="")
        url = "https://api.openalex.org/works/{}?select={}".format(key, SELECT)
        try:
            return get_json(url), "doi"
        except Exception:
            pass
    query = urllib.parse.quote(clean_title(source.get("title")))
    url = "https://api.openalex.org/works?search={}&per-page=1&select={}".format(query, SELECT)
    data = get_json(url)
    rows = data.get("results") or []
    return (rows[0] if rows else None), "title-search"


def compact(work, source, method):
    if not work:
        return {"match": 0.0, "method": method, "error": "not found"}
    location = work.get("primary_location") or {}
    journal = (location.get("source") or {}).get("display_name")
    authors = [((a.get("author") or {}).get("display_name")) for a in work.get("authorships") or []]
    funders = [f.get("display_name") for f in work.get("funders") or [] if f.get("display_name")]
    return {
        "match": round(similarity(clean_title(source.get("title")), work.get("title")), 3),
        "method": method,
        "title": work.get("title"),
        "year": work.get("publication_year"),
        "doi": work.get("doi"),
        "authors": [a for a in authors if a],
        "venue": journal,
        "funders": funders,
        "type": work.get("type"),
    }


def crossref(source):
    doi = doi_from_url(source.get("url"))
    if doi:
        url = "https://api.crossref.org/works/{}".format(urllib.parse.quote(doi, safe=""))
        message = get_json(url).get("message")
        return message, "crossref-doi"
    params = urllib.parse.urlencode({"query.title": clean_title(source.get("title")), "rows": 5,
                                     "select": "DOI,title,published,author,container-title,funder,type"})
    rows = (get_json("https://api.crossref.org/works?" + params).get("message") or {}).get("items") or []
    if not rows:
        return None, "crossref-title-search"
    best = max(rows, key=lambda row: similarity(clean_title(source.get("title")),
                                                (row.get("title") or [None])[0]))
    return best, "crossref-title-search"


def compact_crossref(work, source, method):
    if not work:
        return {"match": 0.0, "method": method, "error": "not found"}
    title = (work.get("title") or [None])[0]
    venue = (work.get("container-title") or [None])[0]
    parts = ((work.get("published") or {}).get("date-parts") or [[]])[0]
    authors = []
    for author in work.get("author") or []:
        name = " ".join(x for x in (author.get("given"), author.get("family")) if x)
        if name:
            authors.append(name)
    funders = [f.get("name") for f in work.get("funder") or [] if f.get("name")]
    return {"match": round(similarity(clean_title(source.get("title")), title), 3),
            "method": method, "title": title, "year": parts[0] if parts else None,
            "doi": ("https://doi.org/" + work["DOI"]) if work.get("DOI") else None,
            "authors": authors, "venue": venue, "funders": funders, "type": work.get("type")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="case KB globs or paths")
    ap.add_argument("--out", required=True)
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--resume", action="store_true",
                    help="reuse already successful rows from --out and checkpoint after each source")
    ap.add_argument("--provider", choices=("openalex", "crossref"), default="openalex")
    args = ap.parse_args(argv)
    files = []
    for pattern in args.files:
        files.extend(glob.glob(pattern) or [pattern])
    report = {"generatedBy": args.provider + " public API", "cases": {}}
    if args.resume and os.path.isfile(args.out):
        with open(args.out, encoding="utf-8") as f:
            report = json.load(f)

    def checkpoint():
        atomic_write_json(args.out, report)

    for path in sorted(set(files)):
        with open(path, encoding="utf-8") as f:
            kb = json.load(f)
        old = {row.get("id"): row for row in report.get("cases", {}).get(path, [])}
        rows = []
        report.setdefault("cases", {})[path] = rows
        for i, source in enumerate(kb.get("sources", []), 1):
            prior = old.get(source.get("id"))
            if prior and (prior.get("candidate") or {}).get("match", 0) >= 0.5:
                candidate = prior["candidate"]
            else:
                try:
                    if args.provider == "crossref":
                        work, method = crossref(source)
                        candidate = compact_crossref(work, source, method)
                    else:
                        work, method = openalex(source)
                        candidate = compact(work, source, method)
                except Exception as exc:
                    candidate = {"match": 0.0, "method": "error", "error": str(exc)[:240]}
            rows.append({"index": i, "id": source.get("id"), "storedTitle": source.get("title"),
                         "storedUrl": source.get("url"), "candidate": candidate})
            print("{} {:03d}/{} {:.3f} {}".format(
                os.path.basename(path), i, len(kb.get("sources", [])), candidate.get("match", 0),
                candidate.get("title") or candidate.get("error") or ""), flush=True)
            checkpoint()
            time.sleep(args.delay)
    checkpoint()
    print("wrote " + args.out)


if __name__ == "__main__":
    main()
