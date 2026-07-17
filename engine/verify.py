"""Deterministic quote grounding against the exact text supplied to the labeller.

``verifiedQuote == "exact"`` has a deliberately narrow meaning: the stored excerpt is one
verbatim, non-title sentence found in a single textual segment of the fetched document.  Merely
finding most of the same words, joining a page title to an abstract sentence, or storing a model
paraphrase is not verification.  Every exact result carries a v2 verification record with a hash of
the checked text so downstream code can distinguish a computed result from a hand-authored flag.
"""
import difflib
import hashlib
import re
import unicodedata

_WS = re.compile(r"\s+")
_PARAGRAPH = re.compile(r"\n\s*\n+")
# Keep the two fixed-width lookbehinds separate because Python's regular-expression engine does
# not permit variable-width lookbehinds.  The second alternative matters for prose such as
# ``... is “suboptimal.” We also ...``: a closing quotation mark must not join two sentences into
# one supposedly verified excerpt.
_SENTENCE = re.compile(
    r"(?:(?<=[.!?])|(?<=[.!?][\"'”’]))\s+(?=[\"'“‘(\[]*[A-Z0-9])")
_HEADING = re.compile(
    r"^(abstract|background|objective|objectives|methods?|results?|discussion|conclusions?|"
    r"introduction|keywords?|highlights?|summary|article info)\s*:?$", re.I)
_INLINE_HEADING = re.compile(
    r"^(?:-+\s*full text\s*-+\s*)?(?:abstract|background|objective|objectives|methods?|results?|"
    r"discussion|conclusions?|summary)\s*:\s*", re.I)
_METHOD = "verbatim-sentence-v2"


def _unicode(s):
    """Apply Unicode compatibility normalization without rewriting visible punctuation."""
    return unicodedata.normalize("NFKC", str(s or ""))


def _exact_norm(s):
    return _WS.sub(" ", _unicode(s).strip())


def _loose_norm(s):
    return re.sub(r"[^a-z0-9]+", " ", _unicode(s).lower()).strip()


def _title_core(title):
    title = str(title or "").strip()
    if " — " in title:
        title = title.split(" — ", 1)[1]
    return title.split(" | ", 1)[0].strip()


def _title_like(sentence, title):
    a, b = _loose_norm(sentence), _loose_norm(_title_core(title))
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    overlap = len(ta & tb) / max(1, len(ta | tb))
    return overlap >= 0.82 and len(a) <= len(b) * 1.35


def _segments(text):
    """Yield sentence-sized segments without ever crossing a paragraph/heading boundary."""
    out = []
    raw = _unicode(text).replace("\r\n", "\n").replace("\r", "\n")
    for paragraph in _PARAGRAPH.split(raw):
        paragraph = _WS.sub(" ", paragraph).strip()
        if not paragraph or _HEADING.match(paragraph):
            continue
        for sentence in _SENTENCE.split(paragraph):
            sentence = _INLINE_HEADING.sub("", sentence.strip())
            if sentence and not _HEADING.match(sentence):
                out.append(sentence)
    return out


def _fuzzy_score(a, b):
    aa, bb = _loose_norm(a), _loose_norm(b)
    if not aa or not bb:
        return 0.0
    seq = difflib.SequenceMatcher(None, aa, bb, autojunk=False).ratio()
    ta, tb = set(aa.split()), set(bb.split())
    jac = len(ta & tb) / max(1, len(ta | tb))
    whole = 0.65 * seq + 0.35 * jac

    # A stored excerpt is often shorter than its containing sentence.  Score comparable token
    # windows as well as the whole sentence so altered wording is surfaced as fuzzy rather than
    # "missing" merely because the verifier now canonicalises to complete sentences.
    a_tokens, b_tokens = aa.split(), bb.split()
    short, long = (a_tokens, b_tokens) if len(a_tokens) <= len(b_tokens) else (b_tokens, a_tokens)
    partial = 0.0
    if short:
        for width in range(max(1, len(short) - 3), min(len(long), len(short) + 3) + 1):
            for start in range(0, len(long) - width + 1):
                window = long[start:start + width]
                ratio = difflib.SequenceMatcher(None, short, window, autojunk=False).ratio()
                overlap = len(set(short) & set(window)) / max(1, len(set(short)))
                partial = max(partial, 0.7 * ratio + 0.3 * overlap)
    return max(whole, partial)


def ground_quote(quote, text, source_title=None, text_depth="unknown", source_url=None):
    """Return a verification result and, when exact, the canonical source sentence.

    Status values remain ``exact | fuzzy | missing`` for schema compatibility.  ``fuzzy`` now
    explicitly means *not a verified quotation*: it covers paraphrases, case/punctuation changes,
    fragments spanning structural boundaries, and title+abstract concatenations.
    """
    q = _exact_norm(quote)
    t = str(text or "")
    digest = hashlib.sha256(t.encode("utf-8", "ignore")).hexdigest() if t else None
    base = {"method": _METHOD, "status": "missing", "textSha256": digest,
            "textDepth": text_depth or "unknown"}
    if source_url:
        base["sourceUrl"] = source_url
    if len(q) < 20 or len(q.split()) < 4:
        base["reason"] = "too-short-to-verify"
        return base
    if not t.strip():
        base["reason"] = "no-text"
        return base

    segments = _segments(t)
    exact = []
    for sentence in segments:
        sn = _exact_norm(sentence)
        if q in sn and not _title_like(sentence, source_title):
            exact.append(sentence)
    if exact:
        # Prefer the tightest containing sentence. Expanding a verbatim fragment to the full
        # sentence prevents a selectively clipped clause from being displayed as the paper's claim.
        sentence = min(exact, key=lambda item: len(_exact_norm(item)))
        canonical = _exact_norm(sentence)
        normalized_text = _exact_norm(t)
        start = normalized_text.find(canonical)
        base.update({"status": "exact", "reason": "verbatim-single-sentence",
                     "quote": sentence,
                     "canonicalized": canonical != q,
                     "quoteSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                     "normalizedCharStart": start,
                     "normalizedCharEnd": start + len(canonical) if start >= 0 else -1,
                     "normalization": "NFKC-typography-whitespace-v1"})
        return base

    # If the normalized quote occurs only in the whole document, it crossed a paragraph/sentence
    # boundary (the Worobey title+abstract failure) and is therefore not a quotation.
    if q in _exact_norm(t):
        base.update({"status": "fuzzy", "reason": "crosses-structural-boundary"})
        return base

    candidates = [( _fuzzy_score(q, sentence), sentence) for sentence in segments
                  if not _title_like(sentence, source_title)]
    if candidates:
        score, sentence = max(candidates, key=lambda item: item[0])
        if score >= 0.72:
            base.update({"status": "fuzzy", "reason": "paraphrase-or-altered-text",
                         "similarity": round(score, 3), "candidate": sentence})
            return base
    base["reason"] = "not-found"
    return base


def apply_quote_verification(provenance, text, source_title=None, text_depth="unknown",
                             source_url=None):
    """Recompute one provenance object's trust fields and canonicalize exact fragments."""
    if not isinstance(provenance, dict):
        return None
    provenance.pop("verifiedQuote", None)
    provenance.pop("quoteVerification", None)
    quote = provenance.get("quote")
    if not quote:
        return None
    result = ground_quote(quote, text, source_title=source_title, text_depth=text_depth,
                          source_url=source_url)
    provenance["verifiedQuote"] = result["status"]
    provenance["quoteVerification"] = {
        key: value for key, value in result.items()
        if key not in {"quote", "candidate"} and value is not None
    }
    if result["status"] == "exact" and result.get("quote"):
        provenance["quote"] = result["quote"]
    return result


def is_verified_exact(provenance):
    """True only for an exact quote computed by the current verifier against hashed text."""
    if not isinstance(provenance, dict) or provenance.get("verifiedQuote") != "exact":
        return False
    audit = provenance.get("quoteVerification")
    if not (isinstance(audit, dict) and audit.get("method") == _METHOD and
            audit.get("status") == "exact" and audit.get("textSha256") and
            audit.get("quoteSha256")):
        return False
    # Bind the audit record to the displayed wording. Editing a quote after verification must
    # invalidate its checkmark even if a stale text hash/status is accidentally retained.
    actual = hashlib.sha256(_exact_norm(provenance.get("quote")).encode("utf-8")).hexdigest()
    return actual == audit.get("quoteSha256")


def strip_untrusted_verification(delta):
    """Remove client/model-supplied verification claims from a delta that was not fetched here."""
    if isinstance(delta, dict):
        # A delta describes ONE source; it never carries KB meta. Drop any client-supplied meta so a
        # forged stewardship flag (meta.curated) can't ride in — belt-and-suspenders on top of the
        # merge already being source-shaped and ignoring meta entirely.
        delta.pop("meta", None)
    source = delta.get("source") if isinstance(delta, dict) else None
    if isinstance(source, dict):
        source.pop("textAudit", None)
        # A caller may describe its source depth, but without a local fetch it cannot use that depth
        # as verification evidence. Preserve the honest unknown default.
        source["textDepth"] = "unknown"
        for provenance in (source.get("provenance") or {}).values():
            if isinstance(provenance, dict):
                provenance.pop("verifiedQuote", None)
                provenance.pop("quoteVerification", None)
        for edge in source.get("restsOn") or []:
            if isinstance(edge, dict):
                # Admission is a curator/trusted-migration decision, never a client assertion.
                edge.pop("admission", None)
            provenance = edge.get("provenance") if isinstance(edge, dict) else None
            if isinstance(provenance, dict):
                provenance.pop("verifiedQuote", None)
                provenance.pop("quoteVerification", None)
    for factor in (delta.get("factorWeights") or []) if isinstance(delta, dict) else []:
        if isinstance(factor, dict):
            factor.pop("verifiedQuote", None)
            factor.pop("quoteVerification", None)
    return delta


def strip_untrusted_kb(kb):
    """Sanitize a WHOLE KB pushed by a non-admin (keyless) client.

    A keyless contributor may seed a new question's structure and sources, but may not assert any
    trust the portal cannot vouch for: stewardship (``meta.curated``), curator dataset confirmations,
    support-edge admissions, and quote-verification flags are all removed. Curator trust (bases stay
    **proposed**) can only be restored by an authenticated curator. Quote verification is different:
    it is deterministic, so the portal re-earns it itself by calling ``verify_kb`` (fetched-text
    grounding) right after this strip — a keyless push therefore lands with proposed bases but its
    quotes GROUNDED by the server, no admin token needed. Mutates and returns ``kb``."""
    meta = kb.get("meta")
    if isinstance(meta, dict):
        meta.pop("curated", None)
    for dataset in kb.get("datasets", []) or []:
        if isinstance(dataset, dict):
            dataset.pop("confirmation", None)
            dataset.pop("confirmed", None)                 # legacy boolean, honored on read
    for source in kb.get("sources", []) or []:
        if isinstance(source, dict):
            strip_untrusted_verification({"source": source})  # textDepth/admission/verifiedQuote/…
    for factor in kb.get("factors", []) or []:
        if isinstance(factor, dict):
            for claim in factor.get("provenance", []) or []:
                if isinstance(claim, dict):
                    claim.pop("verifiedQuote", None)
                    claim.pop("quoteVerification", None)
            factor["weights"] = {}   # cells derive only from verified claims; none survive the strip
    return kb


def verify_kb(kb, fetch_text):
    """Deterministically ground every stored quote in a WHOLE kb against source text.

    ``fetch_text(url) -> str | None`` is injected by the caller (the CLI passes the ingest fetcher,
    the portal passes its own), so this stays dependency-free and identical everywhere. Grounds each
    source's position quote, every dependency-edge quote (an exact match may promote a proposed
    root), and every factor/crux claim, then rebuilds the crux grid from the newly verified claims.

    Trust comes from the FETCH happening here — never from client-supplied verification — so this is
    safe to run for anyone: it recomputes the record rather than believing it. Returns a
    ``{exact, fuzzy, missing, unfetched}`` tally. Best-effort: a source that will not fetch simply
    leaves its quotes unverified.
    """
    sources = kb.get("sources", []) or []
    src_by_id = {s.get("id"): s for s in sources}
    text_cache = {}
    counts = {"exact": 0, "fuzzy": 0, "missing": 0, "unfetched": 0}

    def text_for(src):
        sid = src.get("id")
        if sid in text_cache:
            return text_cache[sid]
        text = None
        url = src.get("url")
        if url:
            try:
                text = fetch_text(url)
            except Exception:
                text = None
        text_cache[sid] = text
        return text

    def ground(prov, src):
        if not (isinstance(prov, dict) and prov.get("quote")):
            return
        text = text_for(src)
        if not text:
            counts["unfetched"] += 1
            return
        result = apply_quote_verification(prov, text, source_title=src.get("title"),
                                          text_depth=src.get("textDepth", "unknown"),
                                          source_url=src.get("url"))
        counts[result["status"]] = counts.get(result["status"], 0) + 1

    for src in sources:
        ground((src.get("provenance") or {}).get("position"), src)
        for edge in src.get("restsOn", []) or []:
            if isinstance(edge, dict):
                ground(edge.get("provenance"), src)
    for factor in kb.get("factors", []) or []:
        for entry in factor.get("provenance", []) or []:
            src = src_by_id.get(entry.get("source"))
            if src:
                ground(entry, src)

    from engine.merge import recompute_factor_weights   # lazy: merge imports verify at load time
    recompute_factor_weights(kb)
    return counts


def match_quote(quote, text, source_title=None):
    """Compatibility wrapper returning ``exact | fuzzy | missing``."""
    return ground_quote(quote, text, source_title=source_title)["status"]
