"""STRUCTURE layer (Layer 2): deterministic merge + entity resolution.

The LLM ingestion step (ingest/pipeline.py via prompts/ingest.md) PROPOSES links -- by
existing id, or "NEW:<label>" when it believes nothing matches. This code DISPOSES:
resolution is normalized-string + alias matching, so it is reproducible and auditable,
never dependent on LLM nondeterminism. "Propose, then deterministically resolve" is the
contract that keeps a living KB stable as contributors and models change.

Adversarial defences live here:
  * alias-splitting -- an incoming dataset name is matched against existing labels AND
    learned aliases, so one cohort can't be smuggled in under five names to fake independence.
  * duplicate sources -- same url (or title+year) are refused, so a camp can't be inflated
    by re-submitting the same study. Flooding the zone is refused at the door.
"""
import re
import datetime
import urllib.parse

HUES = ["#2E8B6F", "#B4502E", "#586A7A", "#8a6510", "#2f6296", "#7a4fa3"]


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s if s is not None else "").lower()).strip()


def slug(s):
    return re.sub(r"\s+", "_", norm(s))[:44] or "x"


_FUNDING_FALLBACK = ["Government/public", "Nonprofit/charity", "Academic/institutional",
                     "Industry", "Advocacy", "Undisclosed"]
_SIZE_CLAUSE = re.compile(
    r"[\s,(–-]*\b\d[\d,]*\s+(?:women|men|adults|participants|people|subjects|patients|cases)\b.*$",
    re.I)


def _split_camel_token(tok):
    """Split a heavily-camelCased token ('AngryBirdsMeta' → 'Angry Birds Meta') while leaving
    ordinary proper nouns alone: only tokens with 2+ interior case transitions are split, so
    'McGill' / 'McDonald' (one transition) pass through unchanged."""
    if len(re.findall(r"[a-z][A-Z]", tok)) >= 2:
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", tok)
    return tok


def prettify_label(s):
    """Turn an id-like label into something readable for the website: underscores → spaces,
    heavy camelCase split, a space before a trailing year ('Ferguson2015' → 'Ferguson 2015'),
    a capitalized first letter, and a trailing sample-size clause stripped
    ('Finnish_cohort_Knekt_1996_4697_women' → 'Finnish cohort Knekt 1996').
    Clean labels pass through (apart from the capital)."""
    s = (s or "").strip()
    if "_" in s:
        s = s.replace("_", " ")
    s = " ".join(_split_camel_token(t) for t in s.split(" "))
    s = re.sub(r"(?<=[A-Za-z])(?=\d{4}\b)", " ", s)     # Ferguson2015 -> Ferguson 2015
    s = _SIZE_CLAUSE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip() or (s or "")
    return (s[:1].upper() + s[1:]) if s[:1].islower() else s


def _resolve_funding(kb, value):
    """Snap the funder to the closed funding vocabulary; default 'Undisclosed' (never assume
    independence when the text is silent). Tolerant of free-text / legacy values."""
    terms = (kb.get("vocab", {}) or {}).get("funding") or [{"label": x} for x in _FUNDING_FALLBACK]
    v = value[4:].strip() if str(value).startswith("NEW:") else (value or "")
    probe = norm(v)
    if not probe:
        return "Undisclosed"
    for t in terms:
        if norm(t["label"]) == probe or any(norm(a) == probe for a in t.get("aliases", [])):
            return t["label"]
    if "industr" in probe or "commercial" in probe or "company" in probe:
        return "Industry"
    if "advoca" in probe or "dairy council" in probe or "egg board" in probe \
            or "nutrition center" in probe or "commodity board" in probe or "meat board" in probe:
        return "Advocacy"
    if "govern" in probe or probe.startswith("nih") or "national institute" in probe \
            or "research council" in probe or "public" in probe:
        return "Government/public"
    if "charit" in probe or "foundation" in probe or "nonprofit" in probe or "society" in probe:
        return "Nonprofit/charity"
    if "univers" in probe or "academ" in probe or "institute" in probe:
        return "Academic/institutional"
    return "Undisclosed"  # incl. legacy "independent" — we don't actually know the funder type


def _unique_id(prefix, base, exists):
    cid, n = prefix + base, 2
    while exists(cid):
        cid = prefix + base + "_" + str(n)
        n += 1
    return cid


def clean_url(u):
    """Unwrap a URL that arrived markdown-wrapped — [text](url) or a bare [url] — and trim stray
    punctuation. Chatbots routinely return links this way in pasted deltas, which would otherwise
    be stored verbatim and break dedup + any later DOI/identifier enrichment."""
    u = (u or "").strip()
    m = re.search(r"\((https?://[^)\s]+)\)", u)   # markdown [text](https://…)
    if m:
        u = m.group(1)
    else:
        m = re.search(r"https?://[^\s\]\)>]+", u)  # first bare URL anywhere in the string
        u = m.group(0) if m else u
    try:
        parsed = urllib.parse.urlsplit(u)
    except ValueError:
        return ""
    # Stored source URLs are rendered as links. Keep only absolute web URLs, never executable
    # schemes (javascript:, data:) or relative values supplied by an untrusted delta.
    return u if parsed.scheme.lower() in ("http", "https") and parsed.hostname else ""


def source_key(s):
    if s.get("url"):
        return "u:" + norm(clean_url(s["url"]))
    return "t:" + norm(s.get("title")) + ":" + str(s.get("year") or "")


def paper_ident(s):
    """A canonical paper identifier (DOI / PMID / PMCID) pulled from the source's url — so the SAME
    paper under two links (publisher vs PMC vs doi.org) dedupes to one. None if no id is present."""
    u = clean_url(s.get("url") or "")
    m = re.search(r"10\.\d{4,9}/[^\s?#\"'<>]+", u)
    if m:
        return "doi:" + norm(m.group(0).rstrip(").,;'\""))
    m = re.search(r"PMC\d{4,}", u, re.I)
    if m:
        return "pmc:" + m.group(0).upper()
    m = re.search(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|/pubmed/)(\d{6,9})", u)
    if m:
        return "pmid:" + m.group(1)
    return None


def _resolve_source_ref(kb, ref):
    """Resolve a labeller's reference to another source (by exact id, else normalized title) to its
    id, or None if that source isn't in the KB yet. Used for source->source derivation edges."""
    ref = (ref or "").strip()
    for s in kb["sources"]:
        if s["id"] == ref:
            return s["id"]
    probe = norm(ref)
    if not probe:
        return None
    for s in kb["sources"]:
        if norm(s.get("title")) == probe:
            return s["id"]
    return None


def _dataset_is_source_ref(kb, proposed):
    """Catch a restsOn entry that REFERENCES AN EXISTING SOURCE but was written without the SRC:
    prefix (labellers copy raw ids like 'src_violent_video_game_effects_...' or paste the title).
    Left unguarded, merge minted phantom datasets named after sources ('ds_src_*'), so echo never
    collapsed through the citation edge. Returns the source id, or None for a real dataset name.
    Conservative: only fires on a normalized match of a source's id or full title."""
    label = proposed[4:].strip() if proposed.startswith("NEW:") else proposed
    probe = norm(label)
    if not probe:
        return None
    for s in kb["sources"]:
        sid_n = norm(s["id"])
        if probe == sid_n or (probe.startswith("src ") and sid_n.startswith("src ")
                              and (probe[4:].startswith(sid_n[4:][:20]) if len(sid_n) > 24
                                   else probe[4:] == sid_n[4:])):
            return s["id"]
        if norm(s.get("title")) == probe:
            return s["id"]
    return None


def _resolve_dataset(kb, proposed):
    is_new = proposed.startswith("NEW:")
    label = proposed[4:].strip() if is_new else None
    if not is_new:
        for d in kb["datasets"]:
            if d["id"] == proposed:
                return d["id"], False
    probe = norm(label or proposed)
    for d in kb["datasets"]:
        # normalized match against the canonical label OR any learned alias. A raw variant that
        # normalizes to an existing label needs no new alias (normalization already unifies them);
        # genuinely different surface forms ("NHS" vs "Nurses' Health Study") are learned as aliases
        # by the explicit curate.merge ops, not here -- ingestion resolution stays purely normalized
        # so it is deterministic and never silently widens a match. (An earlier inline alias-learning
        # branch here was dead code: its condition contradicted the match above.)
        if norm(d["label"]) == probe or any(norm(a) == probe for a in d.get("aliases", [])):
            return d["id"], False
    nice = prettify_label(label or proposed)
    cid = _unique_id("ds_", slug(nice),
                     lambda x: any(d["id"] == x for d in kb["datasets"]))
    kb["datasets"].append({"id": cid, "label": nice, "aliases": []})
    return cid, True


def _short_label(s, limit=20):
    """Trim a position's short label to <=limit chars at a WORD boundary, so the chart bar / matrix
    header never shows a mid-word cut like 'Cold-chain reintrodu'. A single over-long word is hard-
    cut as a last resort."""
    s = re.sub(r"\s+", " ", str(s if s is not None else "")).strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if s[limit] != " " and " " in cut[1:]:   # only trim back when we'd cut mid-word
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:-/")


_POS_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "with", "and", "or", "by", "at",
             "is", "are", "be", "that", "this", "it", "its"}
_PAREN_RE = re.compile(r"\s*\([^)]*\)")


def _pos_tokens(label):
    """Content tokens of a position label, minus pure connectives. STANCE words (increase/
    decrease/no/protective/…) are DELIBERATELY kept — they are what distinguishes camps."""
    return set(norm(label).split()) - _POS_STOP


def _position_dup(kb, label):
    """The existing position an incoming label should fold into, or None — the deterministic guard
    against camp-splitting (SCHEMA.md problem 1, positions edition). Two conservative, stance-SAFE
    rules, so opposite stances are never merged:
      1. same label once trailing/parenthetical qualifiers are stripped ("No clear effect (after
         bias adjustment)" -> "No clear effect");
      2. one label's content tokens are a SUBSET of the other's (a condition/qualifier variant:
         "No clear effect" ⊆ "No clear effect after bias adjustment"), requiring >=2 shared tokens.
    We do NOT use token-overlap (Jaccard) similarity: on long labels it merges OPPOSITE stances
    that differ in one word ("…alcohol increases CV risk" vs "…decreases CV risk" overlap ~0.67).
    Subset can't do that — opposite stances are never subsets of one another."""
    probe_bare = norm(_PAREN_RE.sub("", label))
    probe_tokens = _pos_tokens(label)
    for p in kb["positions"]:
        if norm(_PAREN_RE.sub("", p["label"])) == probe_bare and probe_bare:
            return p
        pt = _pos_tokens(p["label"])
        if probe_tokens and pt and (probe_tokens <= pt or pt <= probe_tokens) \
                and min(len(probe_tokens), len(pt)) >= 2:
            return p
    return None


def _resolve_position(kb, proposed, short_label=None):
    is_new = proposed.startswith("NEW:")
    label = proposed[4:].strip() if is_new else None
    if not is_new:
        for p in kb["positions"]:
            if p["id"] == proposed:
                return p["id"], False
    probe = norm(label or proposed)
    for p in kb["positions"]:
        if norm(p["label"]) == probe:
            return p["id"], False
    dup = _position_dup(kb, label or proposed)          # near-duplicate / condition-split guard
    if dup is not None:
        return dup["id"], False
    nice = prettify_label(label or proposed)
    cid = _unique_id("pos_", slug(nice),
                     lambda x: any(p["id"] == x for p in kb["positions"]))
    entry = {"id": cid, "label": nice, "hue": HUES[len(kb["positions"]) % len(HUES)]}
    if short_label:
        entry["shortLabel"] = _short_label(short_label)  # word-boundary trim, never mid-word
    kb["positions"].append(entry)
    return cid, True


def _resolve_vocab(kb, kind, value):
    """Snap a free-text evidence/population tag to the case's controlled vocabulary
    (normalized-string + alias match), or add it as a new canonical term. Same
    'propose, then deterministically resolve' discipline as datasets: paraphrases collapse
    onto one term instead of multiplying, so the blindspot metric stays meaningful. "—" and
    empty values pass through unchanged (population may be genuinely not-applicable)."""
    if not value or value == "—":
        return value
    vocab = kb.setdefault("vocab", {})
    terms = vocab.setdefault(kind, [])
    is_new = value.startswith("NEW:")
    label = value[4:].strip() if is_new else value
    probe = norm(label)
    for t in terms:
        if norm(t["label"]) == probe or any(norm(a) == probe for a in t.get("aliases", [])):
            return t["label"]  # snap to the canonical label
    terms.append({"label": label, "aliases": []})  # genuinely new term for this case
    return label


def _snap_weight(w):
    """Snap a factor weight onto the {high, med, low, n/a} vocabulary. Labellers drift ('medium',
    'moderate', 'High'); an off-vocabulary value silently drops out of the crux-spread math, so
    normalize deterministically here. Unknown values pass through lowercased (never guessed)."""
    v = str(w or "").strip().lower()
    if v.startswith("hi"):
        return "high"
    if v.startswith(("med", "mod")):
        return "med"
    if v.startswith("lo"):
        return "low"
    if v in ("n/a", "na", "none", "not applicable"):
        return "n/a"
    return v


def _resolve_factor(kb, f_label):
    # The factor convention is "reference by exact label", but models often copy the
    # "NEW:<label>" convention used for positions/datasets. Strip it so a decorated label
    # resolves to the existing factor instead of minting a phantom duplicate.
    label = f_label[4:].strip() if f_label.startswith("NEW:") else f_label
    probe = norm(label)
    for f in kb["factors"]:
        if norm(f["label"]) == probe:
            return f["id"], False
    # near-duplicate guard, same subset discipline as positions: a qualifier/paraphrase variant
    # ("Publication bias concerns") folds into the existing crux instead of minting a parallel one.
    probe_t = _pos_tokens(label)
    for f in kb["factors"]:
        ft = _pos_tokens(f["label"])
        if probe_t and ft and (probe_t <= ft or ft <= probe_t) \
                and min(len(probe_t), len(ft)) >= 2:
            return f["id"], False
    nice = prettify_label(label)
    cid = _unique_id("f_", slug(nice),
                     lambda x: any(f["id"] == x for f in kb["factors"]))
    kb["factors"].append({"id": cid, "label": nice, "weights": {},
                          "rationale": "", "provenance": []})
    return cid, True


def merge_delta(kb, delta):
    """Fold one ingestion delta into the KB in place. Returns a change report.
    delta = {"source": {...}, "factorWeights": [...]} as produced by prompts/ingest.md."""
    report = {"addedSource": None, "duplicate": False, "offTopic": False, "newDatasets": [],
              "newPositions": [], "newFactors": [], "updatedFactors": []}
    src = delta["source"]

    # The labeller (which saw the real fetched text) can flag a source that doesn't bear on the
    # question; refuse it here, like a duplicate — so off-topic sources never pollute the metrics.
    # But DON'T drop it silently: a wrongly-refused source is invisible suppression of a possibly
    # legitimate voice, the inverse of the tool's job. Record it in kb["refused"] + the log so the
    # decision is auditable and reversible (a curator can re-admit it). No metric reads kb["refused"].
    if src.get("relevant") is False:
        reason = src.get("offTopicReason") or "not relevant to the question"
        report["offTopic"] = True
        report["reason"] = reason
        already = {source_key(r) for r in kb.get("refused", [])}
        if source_key(src) not in already:                # don't re-log the same refusal on re-runs
            kb.setdefault("refused", []).append({
                "title": src.get("title") or "(untitled)", "url": src.get("url"),
                "year": src.get("year"), "reason": reason, "ts": now_iso()})
            kb.setdefault("log", []).append({
                "version": kb.get("meta", {}).get("version", 0), "action": "refused-offtopic",
                "source": src.get("title"), "ts": now_iso(), "note": "off-topic: " + reason})
        return report

    # Refuse a duplicate by: same source_key (url, or title+year when url-less); same canonical
    # paper identifier (DOI/PMID/PMCID) even under a different url; or same normalized title+year.
    # The same paper routinely appears under publisher / PMC / DOI links, and counting it twice
    # fakes independence.
    t_norm, yr = norm(src.get("title")), str(src.get("year") or "")
    ident = paper_ident(src)

    def _dup(s):
        if source_key(s) == source_key(src):
            return True
        if ident and paper_ident(s) == ident:
            return True
        if bool(t_norm) and len(t_norm) >= 10 and norm(s.get("title")) == t_norm and \
                str(s.get("year") or "") == yr:
            return True
        # same paper under publisher-vs-mirror links (DOI on one, PMCID on the other) often shows
        # a title truncation/variant: same year + one normalized title a prefix of the other.
        # Mirrors curate.dedupe_sources so the duplicate is refused at the door, not cleaned later.
        s_norm = norm(s.get("title"))
        if bool(t_norm) and bool(s_norm) and yr and str(s.get("year") or "") == yr and \
                min(len(t_norm), len(s_norm)) >= 25 and \
                (t_norm.startswith(s_norm) or s_norm.startswith(t_norm)):
            return True
        # print-vs-online year drift: a mirror often lists the NEXT year (Nature 2018 print vs
        # PMC 2019 online). For an EXACT long title match, tolerate a 1-year difference.
        try:
            close_year = yr and s.get("year") and abs(int(yr) - int(s["year"])) <= 1
        except (TypeError, ValueError):
            close_year = False
        return bool(t_norm) and len(t_norm) >= 25 and s_norm == t_norm and close_year
    if any(_dup(s) for s in kb["sources"]):
        report["duplicate"] = True
        return report

    version = (kb["meta"].get("version", 0) or 0) + 1
    pos_id, pos_new = _resolve_position(kb, src["position"], src.get("positionShort"))
    if pos_new:
        report["newPositions"].append(pos_id)

    rests_on = []
    for d in src.get("restsOn", []):
        d = str(d).strip()
        # A source can rest on ANOTHER SOURCE (citation/derivation edge) -- this is what lets the
        # independence audit catch circular corroboration (see MECHANISM.md). The labeller writes
        # SRC:<existing id> or NEW-SRC:<title>; we resolve to an existing source and store "src:<id>".
        low = d.lower()
        if low.startswith("src:") or low.startswith("new-src:"):
            ref = d.split(":", 1)[1].strip()
            tid = _resolve_source_ref(kb, ref)
            if tid:
                rests_on.append("src:" + tid)
            else:
                report.setdefault("danglingRefs", []).append(ref)  # cited source not in the KB
            continue
        tid = _dataset_is_source_ref(kb, d)     # a source reference missing its SRC: prefix
        if tid:
            rests_on.append("src:" + tid)
            continue
        did, created = _resolve_dataset(kb, d)
        if created:
            report["newDatasets"].append(did)
        rests_on.append(did)

    sid = _unique_id("src_", slug(src["title"]) + "_" + str(src.get("year") or "0"),
                     lambda x: any(s["id"] == x for s in kb["sources"]))
    kb["sources"].append({
        "id": sid, "title": src["title"], "year": src.get("year"),
        "url": clean_url(src.get("url")) or None,
        "authors": [a for a in (src.get("authors") or []) if a],  # citation metadata
        "venue": src.get("venue") or "",
        "citations": src.get("citations"),
        "retracted": bool(src.get("retracted")),
        "position": pos_id,
        "evidence": _resolve_vocab(kb, "evidence", src.get("evidence", "Unspecified")),
        "funding": _resolve_funding(kb, src.get("funding")),
        "population": _resolve_vocab(kb, "population", src.get("population", "—")),
        "confidence": src.get("confidence", "unstated"),
        "restsOn": rests_on, "provenance": src.get("provenance", {}), "addedIn": version,
        # 'unknown' when nothing was fetched in-process (e.g. a pasted-back delta) -- see
        # SCHEMA.md and engine/verify.py. Never guessed as 'full'; that would overclaim.
        "textDepth": src.get("textDepth", "unknown"),
    })
    if src.get("modelAgreement"):        # multi-model ensemble agreement report (ingest/ensemble.py)
        kb["sources"][-1]["modelAgreement"] = src["modelAgreement"]
    report["addedSource"] = sid

    for fw in delta.get("factorWeights", []):
        fid, created = _resolve_factor(kb, fw.get("factorLabel") or fw.get("factor"))
        (report["newFactors"] if created else report["updatedFactors"]).append(fid)
        factor = next(f for f in kb["factors"] if f["id"] == fid)
        factor["weights"][pos_id] = _snap_weight(fw["weight"])
        if fw.get("rationale") and not factor.get("rationale"):
            factor["rationale"] = fw["rationale"]
        factor.setdefault("provenance", []).append(
            {"source": sid, "pos": pos_id, "quote": fw.get("quote", ""),
             "verifiedQuote": fw.get("verifiedQuote")})

    kb["meta"]["version"] = version
    kb["meta"]["updated"] = now_iso()
    kb.setdefault("log", []).append({
        "version": version, "action": "add-source", "source": sid,
        "title": src["title"], "ts": kb["meta"]["updated"],
        "newDatasets": report["newDatasets"], "newPositions": report["newPositions"],
    })
    return report
