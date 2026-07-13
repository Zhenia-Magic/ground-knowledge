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
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[\"'“‘(\[]*[A-Z0-9])")
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
            provenance = edge.get("provenance") if isinstance(edge, dict) else None
            if isinstance(provenance, dict):
                provenance.pop("verifiedQuote", None)
                provenance.pop("quoteVerification", None)
    for factor in (delta.get("factorWeights") or []) if isinstance(delta, dict) else []:
        if isinstance(factor, dict):
            factor.pop("verifiedQuote", None)
            factor.pop("quoteVerification", None)
    return delta


def match_quote(quote, text, source_title=None):
    """Compatibility wrapper returning ``exact | fuzzy | missing``."""
    return ground_quote(quote, text, source_title=source_title)["status"]
