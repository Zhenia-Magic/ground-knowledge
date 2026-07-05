"""Quote verification (Layer 3 companion). Pure, deterministic, stdlib only -- see MECHANISM.md.

A source's `provenance[field].quote` is a claim: "the fetched text actually says this." The only
honest way to check that claim is against the text the labeller actually saw -- not against "the
real paper," which the tool may never have had (see SCHEMA.md on `textDepth`). Checking against
anything else would silently promise a stronger guarantee than the tool can deliver.
"""
import difflib
import re

_WS = re.compile(r"\s+")


def _norm(s):
    return _WS.sub(" ", (s or "").strip().lower())


def match_quote(quote, text):
    """exact | fuzzy | missing -- is `quote` grounded in `text`?

    exact:   a verbatim substring after whitespace/case normalization.
    fuzzy:   not verbatim, but a near-identical passage exists (small edits, same order) --
             ellipses, added brackets, minor re-punctuation.
    missing: no such passage. On a full-text source this is a real red flag (the labeller
             said something the fetched text doesn't support); on an abstract-only source it
             is expected background noise whenever the quote draws on body content the tool
             never had -- always read `verifiedQuote` alongside `textDepth`, never alone.

    A quote under 8 normalized characters is too short to mean anything either way and is
    treated as missing (too easy to "match" by accident).
    """
    q, t = _norm(quote), _norm(text)
    if len(q) < 8 or not t:
        return "missing"
    if q in t:
        return "exact"
    # One matcher over the full (long) text vs the (short) quote, not a whole-string ratio --
    # SequenceMatcher indexes the shorter sequence, so this is close to linear in len(text)
    # rather than the O(text/step) re-scans a sliding window would cost. get_matching_blocks()
    # gives the aligned common chunks; only count blocks of >= 4 chars (roughly a short word) --
    # otherwise common short letter-runs between an unrelated quote and a long text accumulate
    # into a spuriously high ratio (verified against a fabricated-quote regression test).
    sm = difflib.SequenceMatcher(None, t, q, autojunk=False)
    matched = sum(size for _, _, size in sm.get_matching_blocks() if size >= 4)
    return "fuzzy" if (matched / len(q)) >= 0.72 else "missing"
