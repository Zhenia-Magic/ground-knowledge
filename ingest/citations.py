"""Citation interchange — import from / export to Zotero & other reference managers.

Researchers live in Zotero / Mendeley / EndNote / Papers, which all read & write the same
plain-text formats: RIS (.ris), BibTeX (.bib), and CSL-JSON (.json). This module:

  parse(text[, fmt])  ->  candidate sources [{title, url, year, authors, why}]
       — each entry's DOI becomes a doi.org URL, so the existing fetch->label->merge pipeline
         resolves it exactly like a search hit. Import is just "your library as the candidate list."

  export(kb, fmt)     ->  (text, mime, extension)
       — a question's sources serialised back out, with position/funding kept in a note so the
         curation isn't lost on round-trip.

Pure stdlib. The BibTeX reader is brace-aware (the fussy format); RIS and CSL-JSON are simple.
"""
import json
import re

from engine.merge import slug

_DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")


def _year(s):
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", str(s or ""))
    return int(m.group(1)) if m else None


def _doi_of(url):
    m = _DOI.search(url or "")
    return m.group(0).rstrip(").,;'\"") if m else None


def _candidate(title, url, year, authors):
    return {"title": (title or "").strip(), "url": (url or "").strip(),
            "year": year, "authors": [a.strip() for a in (authors or []) if a.strip()],
            "why": "imported from citation file"}


# ---- RIS ----------------------------------------------------------------------------------

def parse_ris(text):
    out, cur = [], {}
    for line in (text or "").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  -? ?(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {"authors": []}
        elif tag in ("AU", "A1", "A2", "A3"):
            cur.setdefault("authors", []).append(val)
        elif tag in ("TI", "T1") and not cur.get("title"):
            cur["title"] = val
        elif tag in ("PY", "Y1") and not cur.get("year"):
            cur["year"] = _year(val)
        elif tag == "DO":
            cur["doi"] = val
        elif tag == "UR" and not cur.get("url"):
            cur["url"] = val
        elif tag == "ER":
            if cur.get("title"):
                doi = cur.get("doi")
                url = ("https://doi.org/" + doi) if doi else cur.get("url", "")
                out.append(_candidate(cur["title"], url, cur.get("year"), cur.get("authors")))
            cur = {}
    return out


# ---- BibTeX (brace-aware) -----------------------------------------------------------------

def _bibtex_entries(text):
    i, n = 0, len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            return
        brace = text.find("{", at)
        if brace < 0:
            return
        depth, j = 0, brace
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield text[brace + 1:j]
        i = j + 1


def _bibtex_fields(body):
    comma = body.find(",")          # drop the citekey
    body = body[comma + 1:] if comma >= 0 else body
    fields, i, n = {}, 0, len(body)
    while i < n:
        eq = body.find("=", i)
        if eq < 0:
            break
        key = body[i:eq].strip(" ,\t\r\n").lower()
        i = eq + 1
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        if body[i] == "{":
            depth, j = 0, i
            while j < n:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            val, i = body[i + 1:j], j + 1
        elif body[i] == '"':
            j = body.find('"', i + 1)
            val, i = (body[i + 1:j], j + 1) if j >= 0 else (body[i + 1:], n)
        else:
            j = i
            while j < n and body[j] != ",":
                j += 1
            val, i = body[i:j], j + 1
        if key:
            fields[key] = val.strip()
    return fields


def _clean_tex(s):
    s = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", s or "")   # \emph{x} -> x
    s = re.sub(r'\\[\'"`^~=.]\{?([a-zA-Z])\}?', r"\1", s)   # accents: {\"o} -> o
    s = s.replace("\\&", "&").replace("~", " ").replace("--", "-")
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "")).strip()


def parse_bibtex(text):
    out = []
    for body in _bibtex_entries(text or ""):
        f = _bibtex_fields(body)
        title = _clean_tex(f.get("title", ""))
        if not title:
            continue
        authors = [_clean_tex(a) for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip()]
        doi = f.get("doi", "").strip()
        url = ("https://doi.org/" + doi) if doi else f.get("url", "").strip()
        out.append(_candidate(title, url, _year(f.get("year")), authors))
    return out


# ---- CSL-JSON -----------------------------------------------------------------------------

def parse_csl(text):
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("items") or [data]
    out = []
    for it in data or []:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        authors = []
        for a in it.get("author") or []:
            name = " ".join(x for x in (a.get("given"), a.get("family")) if x).strip() \
                or a.get("literal", "")
            if name:
                authors.append(name)
        doi = (it.get("DOI") or "").strip()
        url = ("https://doi.org/" + doi) if doi else (it.get("URL") or "")
        year = None
        issued = it.get("issued") or {}
        dp = issued.get("date-parts") if isinstance(issued, dict) else None
        if dp and dp[0]:
            year = dp[0][0]
        out.append(_candidate(title, url, year, authors))
    return out


# ---- dispatch -----------------------------------------------------------------------------

def detect_format(text, filename=""):
    fn = (filename or "").lower()
    if fn.endswith(".ris"):
        return "ris"
    if fn.endswith(".bib") or fn.endswith(".bibtex"):
        return "bibtex"
    if fn.endswith(".json"):
        return "csl"
    head = (text or "").lstrip()
    if head.startswith("@"):
        return "bibtex"
    if head.startswith("[") or head.startswith("{"):
        return "csl"
    if re.search(r"(?m)^TY  -", text or "") or re.search(r"(?m)^[A-Z][A-Z0-9]  - ", text or ""):
        return "ris"
    return None


def parse(text, fmt=None, filename=""):
    fmt = fmt or detect_format(text, filename)
    if fmt == "ris":
        return parse_ris(text)
    if fmt == "bibtex":
        return parse_bibtex(text)
    if fmt == "csl":
        return parse_csl(text)
    raise ValueError("Unrecognised citation format — expected RIS, BibTeX, or CSL-JSON.")


# ---- export (kb -> citation file) ---------------------------------------------------------

def _source_rows(kb):
    """Flatten a KB's sources into citation-ready rows, resolving the position label + a note."""
    pos = {p["id"]: p["label"] for p in kb.get("positions", [])}
    rows = []
    for s in kb.get("sources", []):
        note_bits = []
        if s.get("position"):
            note_bits.append("Position: " + pos.get(s["position"], s["position"]))
        if s.get("funding") and s["funding"] != "Undisclosed":
            note_bits.append("Funding: " + s["funding"])
        rows.append({"title": s.get("title") or "", "authors": s.get("authors") or [],
                     "year": s.get("year"), "url": s.get("url") or "",
                     "doi": _doi_of(s.get("url")), "note": " · ".join(note_bits),
                     "keywords": pos.get(s.get("position"), "")})
    return rows


def to_ris(kb):
    out = []
    for r in _source_rows(kb):
        out.append("TY  - JOUR")
        out.append("TI  - " + r["title"])
        for a in r["authors"]:
            out.append("AU  - " + a)
        if r["year"]:
            out.append("PY  - " + str(r["year"]))
        if r["doi"]:
            out.append("DO  - " + r["doi"])
        if r["url"]:
            out.append("UR  - " + r["url"])
        if r["note"]:
            out.append("N1  - " + r["note"])
        if r["keywords"]:
            out.append("KW  - " + r["keywords"])
        out.append("ER  - ")
        out.append("")
    return "\n".join(out)


def _bibkey(r, used):
    surname = (r["authors"][0].split(",")[0].split()[-1] if r["authors"] else "source")
    base = slug("{}{}".format(surname, r["year"] or "")) or "source"
    key, n = base, 2
    while key in used:
        key, n = base + str(n), n + 1
    used.add(key)
    return key


def to_bibtex(kb):
    out, used = [], set()
    for r in _source_rows(kb):
        lines = ["@article{" + _bibkey(r, used) + ","]
        lines.append("  title = {" + r["title"] + "},")
        if r["authors"]:
            lines.append("  author = {" + " and ".join(r["authors"]) + "},")
        if r["year"]:
            lines.append("  year = {" + str(r["year"]) + "},")
        if r["doi"]:
            lines.append("  doi = {" + r["doi"] + "},")
        if r["url"]:
            lines.append("  url = {" + r["url"] + "},")
        if r["keywords"]:
            lines.append("  keywords = {" + r["keywords"] + "},")
        if r["note"]:
            lines.append("  note = {" + r["note"] + "},")
        lines.append("}")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def to_csl(kb):
    items = []
    for r in _source_rows(kb):
        it = {"type": "article-journal", "title": r["title"]}
        if r["authors"]:
            it["author"] = [{"literal": a} for a in r["authors"]]
        if r["year"]:
            it["issued"] = {"date-parts": [[r["year"]]]}
        if r["doi"]:
            it["DOI"] = r["doi"]
        if r["url"]:
            it["URL"] = r["url"]
        if r["note"]:
            it["note"] = r["note"]
        items.append(it)
    return json.dumps(items, indent=2, ensure_ascii=False)


def export(kb, fmt):
    fmt = (fmt or "bibtex").lower()
    if fmt in ("bib", "bibtex"):
        return to_bibtex(kb), "application/x-bibtex", "bib"
    if fmt == "ris":
        return to_ris(kb), "application/x-research-info-systems", "ris"
    if fmt in ("csl", "json", "csl-json"):
        return to_csl(kb), "application/json", "json"
    raise ValueError("Unknown export format: " + fmt)
