"""ASSESSMENT layer (Layer 3 of the FLF stack).

Pure, deterministic functions over a knowledge base (KB). No LLM, no I/O, stdlib only.
Adding evidence never re-runs these by hand on old data -- they just recount, so recompute
is O(whole KB) but cheap, while ingestion stays O(new sources). This is the single
implementation of every number the tool reports; the viewer renders these outputs, it does
not recompute them, so there is no drift between pipeline and UI.
"""

import re

from engine import roots as _roots

# factor weighting vocabulary -> ordinal, for crux spread
WV = {"high": 3, "med": 2, "low": 1, "n/a": 0}


def _ds_label(kb, did):
    for d in kb["datasets"]:
        if d["id"] == did:
            return d["label"]
    return did


def _ds_meta(kb, did):
    """(kind, proposition) for an evidence base — kind defaults to 'dataset'; proposition is the
    plain-language claim of an argument/model root (empty for a plain dataset)."""
    for d in kb["datasets"]:
        if d["id"] == did:
            return (d.get("kind") or "dataset"), (d.get("proposition") or "")
    return "dataset", ""


def _src_by_pos(kb):
    by = {}
    for s in kb["sources"]:
        by.setdefault(s["position"], []).append(s)
    return by


def _root_incidence(kb, res):
    """Per position, the source-weighted INCIDENCE of each resolved evidentiary root: how much of
    the position's sourcing leans on each root (root strength summed once per source resting on
    it). This drives the CONCENTRATION share, the topDataset display, and the bases 'weight'
    column — the "everyone is leaning on one look" signal, which legitimately rises when sources
    pile onto one root. It is deliberately NOT the basis for nEff (see _root_presence): a tally
    that grows with source count must never feed confirmed-root coverage, or piling sources on a
    minority root would shift the shares and move nEff without adding any new evidence."""
    src_by_pos = _src_by_pos(kb)
    secondary_only = res["secondary_only"]
    nonhuman_only = res.get("nonhuman_only", frozenset())
    provisional = res.get("provisional", frozenset())
    per_pos = {}
    for p in kb["positions"]:
        weights = {}
        for s in src_by_pos.get(p["id"], []):
            for r in res["source_roots"].get(s["id"], ()):
                if r.startswith(("secpool:", "primpool:", "cycle:")):
                    weights[r] = 0            # visible assertion marker; no confirmed grounding
                else:                          #   sources fell into it; real roots accumulate per
                    weights[r] = weights.get(r, 0) + _roots.root_strength(
                        r, secondary_only, nonhuman_only, provisional)   # source (halved for
            for r in res.get("unadmitted_source_roots", {}).get(s["id"], ()):
                weights.setdefault(r, 0.0)     # asserted and visible; support edge not admitted
        per_pos[p["id"]] = weights                          # review/animal; zero if unconfirmed)
    return per_pos


def _root_presence(kb, res):
    """Per position, each resolved root's OWN strength, counted exactly once no matter how many
    sources rest on it: {posId: {rootKey: strength}}. Strength is 1.0 for a real root, halved for
    a dataset known only via a secondary source, halved again for a root backed only by animal /
    in-vitro studies. Collapsed secondary/unnamed-primary assertions and pure citation loops remain
    in the map for inspection but have strength 0: unsupported volume is not an evidence base.
    This idempotent map is the basis for nEff — writing the same key again cannot change it, which
    is what makes confirmed-root coverage immune to flooding by construction."""
    src_by_pos = _src_by_pos(kb)
    secondary_only = res["secondary_only"]
    nonhuman_only = res.get("nonhuman_only", frozenset())
    provisional = res.get("provisional", frozenset())
    per_pos = {}
    for p in kb["positions"]:
        pres = {}
        for s in src_by_pos.get(p["id"], []):
            for r in res["source_roots"].get(s["id"], ()):
                # Pooled primary/secondary voices are one assertion. A PURE citation cycle is shown
                # in the incidence/bases table but has zero independent grounding, so it contributes
                # zero headline nEff rather than laundering circularity into one evidentiary base.
                pres[r] = _roots.root_strength(
                    r, secondary_only, nonhuman_only, provisional)
            for r in res.get("unadmitted_source_roots", {}).get(s["id"], ()):
                pres.setdefault(r, 0.0)        # source asserted it, but the support link is untrusted
        per_pos[p["id"]] = pres
    return per_pos


def _n_indep(presence):
    """Confirmed-root coverage = the sum of distinct-root strengths (a full-strength-equivalent
    root count). Fixed-graph monotonicity invariant, relied on by tests/test_independence.py: adding
    a source with only outgoing edges can only add new keys to the presence map or raise an existing
    root's strength (secondary_only / nonhuman_only sets only ever shrink, and existing SCCs are
    untouched). Therefore nEff never decreases for that operation, and stays EXACTLY equal unless the
    source introduces a new root or upgrades one (a primary source landing on a review-only
    dataset, a human study landing on an animal-only root). A graph correction can legitimately lower
    nEff — e.g. resolving a pending edge that reveals a pure citation cycle, or merging aliases that
    were mistakenly split. Piling sources onto already-counted roots with identity fixed moves nothing."""
    return sum(presence.values())


def _n_eff(weights):
    # Herfindahl numbers-equivalent (an EVENNESS measure over a tally). Used only by the method
    # audit's diversity-of-methods reading; root coverage uses _n_indep over _root_presence
    # instead, because an evenness measure over per-source tallies is movable by flooding.
    total = sum(weights.values())
    hhi = sum((w / total) ** 2 for w in weights.values()) if total else 0
    return (1 / hhi) if hhi else 0


def weighted_distribution(kb, res=None):
    """Distribution weighted by confirmed-root coverage. Each position is sized not by raw source
    count but by admitted, deduplicated evidence ROOTS: each
    distinct resolved root counted once at its strength (MECHANISM.md). Sources sharing a dataset,
    echoing as secondary reviews, or citing each other in a loop are de-duplicated. A position
    propped up by re-used or derivative evidence shrinks vs. its raw bar; a pure, ungrounded
    circular loop contributes zero to the weighted bar."""
    res = _roots.resolve(kb) if res is None else res
    pres = _root_presence(kb, res)
    provisional = res.get("provisional", frozenset())
    secondary_only = res.get("secondary_only", frozenset())
    nonhuman_only = res.get("nonhuman_only", frozenset())
    out, weights = [], []
    for p in kb["positions"]:
        mine = [s for s in kb["sources"] if s["position"] == p["id"]]
        n_eff = _n_indep(pres[p["id"]])
        unsupported = {r for s in mine
                       for r in res.get("unadmitted_source_roots", {}).get(s["id"], ())}
        proposed = [r for r in pres[p["id"]] if r in provisional or r in unsupported]
        potential_secondary = secondary_only - res.get("unadmitted_primary_roots", set())
        proposed_potential = sum(
            _roots.root_strength(r, potential_secondary, nonhuman_only, frozenset()) for r in proposed)
        weights.append(n_eff)
        out.append({"id": p["id"], "label": p["label"], "hue": p["hue"],
                    "raw": len(mine), "weight": round(n_eff, 2),
                    "provisionalCount": len(proposed),
                    "provisionalPotential": round(proposed_potential, 2)})
    tot = sum(weights) or 1
    for o, w in zip(out, weights):
        o["pct"] = round(100 * w / tot)
    return out


def distribution(kb):
    """Share of sources by position. The naive aggregator's view -- shown, then
    immediately complicated by funding skew and the independence audit."""
    by = {p["id"]: 0 for p in kb["positions"]}
    for s in kb["sources"]:
        by[s["position"]] = by.get(s["position"], 0) + 1
    total = len(kb["sources"]) or 1
    return [{"id": p["id"], "label": p["label"], "hue": p["hue"],
             "count": by[p["id"]], "pct": round(100 * by[p["id"]] / total)}
            for p in kb["positions"]]




def _low(s):
    return str(s or "").strip().lower()


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s if s is not None else "").lower()).strip()


_METHOD_DEFAULTS = {
    # Conservative biomedical / causal defaults. Cases can override by putting
    # methodClass on the evidence vocab term; unknown terms stay inert.
    "observational": "confounding",
    "cohort": "confounding",
    "case control": "confounding",
    "case-control": "confounding",
    "cross sectional": "confounding",
    "cross-sectional": "confounding",
    "ecological": "confounding",
    "mendelian randomisation": "pleiotropy",
    "mendelian randomization": "pleiotropy",
}

_METHOD_LABELS = {
    "confounding": "observational confounding risk",
    "pleiotropy": "genetic-instrument pleiotropy risk",
    "surrogate-endpoint": "surrogate-endpoint risk",
    "measurement": "measurement-error risk",
}


def _method_label(method):
    return _METHOD_LABELS.get(method, method.replace("-", " "))


def method_class_of(kb, source):
    """Correlated-error method class for a source, or None.

    This is a separate audit axis from evidentiary-root independence. It first honors a source-level
    or vocab-level methodClass, then falls back to a small conservative default map for common
    biomedical causal designs. Secondary evidence types stay inert unless a case explicitly tags
    them; review echo is already handled by the primary independence mechanism.
    """
    if "methodClass" in source:
        if source.get("methodClass"):
            return _norm(source.get("methodClass")).replace(" ", "-")
        return None

    ev = _norm(source.get("evidence"))
    for t in (kb.get("vocab", {}).get("evidence") or []):
        labels = [_norm(t.get("label"))] + [_norm(a) for a in t.get("aliases", [])]
        if ev in labels:
            if t.get("methodClass"):
                return _norm(t.get("methodClass")).replace(" ", "-")
            # A case can explicitly opt an evidence type out with methodClass: "" / null.
            if "methodClass" in t:
                return None
            break

    # Unknown/secondary types remain inert unless explicitly tagged. This keeps the audit from
    # guessing method structure from reviews, guidelines, or commentary.
    if _roots.tier_of(kb, source) == "secondary":
        return None
    return _METHOD_DEFAULTS.get(ev)


def method_audit(kb):
    """Per-position method-class concentration.

    This does not change nEff. It is a warning lens for cases where many sources are independent
    as datasets but still share a dominant correlated-error structure, such as observational
    alcohol cohorts sharing confounding risk.
    """
    by_pos = {p["id"]: {} for p in kb["positions"]}
    classed = {p["id"]: 0 for p in kb["positions"]}
    for s in kb["sources"]:
        pid = s["position"]
        m = method_class_of(kb, s)
        if not m:
            continue
        by_pos.setdefault(pid, {})
        by_pos[pid][m] = by_pos[pid].get(m, 0) + 1
        classed[pid] = classed.get(pid, 0) + 1

    out = []
    for p in kb["positions"]:
        counts = by_pos.get(p["id"], {})
        n_eff = _n_eff(counts)
        top_key, top_count = None, 0
        for k, n in counts.items():
            if n > top_count:
                top_key, top_count = k, n
        top = None
        share = 0
        coverage = 0
        if top_key and classed[p["id"]]:
            share = top_count / classed[p["id"]]
            raw = len([s for s in kb["sources"] if s["position"] == p["id"]])
            coverage = classed[p["id"]] / raw if raw else 0
            top = {"method": top_key, "label": _method_label(top_key),
                   "count": top_count, "share": share}
        else:
            raw = len([s for s in kb["sources"] if s["position"] == p["id"]])
        out.append({
            "id": p["id"], "label": p["label"], "hue": p["hue"],
            "raw": raw,
            "classed": classed[p["id"]],
            "coverage": coverage,
            "nEff": n_eff,
            "top": top,
            "methods": [{"method": k, "label": _method_label(k), "count": n}
                        for k, n in sorted(counts.items(), key=lambda x: -x[1])],
            "monoculture": bool(top and top_count >= 3 and share >= 0.70 and coverage >= 0.30),
        })
    return out


def quote_audit(kb):
    """Audit every stored source, dependency, and factor quotation.

    Exact means a current ``verbatim-sentence-v2`` record with the checked-text hash. ``fuzzy`` is
    an altered/paraphrased passage, not a verified quote; an old hand-authored ``exact`` flag with no
    v2 record is ``unchecked``.  All non-exact excerpts are surfaced regardless of text depth.  A
    missing body passage on an abstract-only fetch may be understandable, but it is still not honest
    to render it with quotation marks or a checkmark.
    """
    from .verify import is_verified_exact
    by_pos = {p["id"]: {"raw": 0, "depthKnown": 0, "full": 0, "unverifiedFull": 0,
                         "quotes": 0, "exact": 0, "altered": 0, "missing": 0,
                         "unchecked": 0}
              for p in kb["positions"]}
    factor_quotes = {}
    for factor in kb.get("factors", []):
        for claim in factor.get("provenance", []):
            if claim.get("source") and claim.get("quote"):
                factor_quotes.setdefault(claim["source"], []).append(
                    ("factor:" + factor.get("id", "?"), claim))
    flagged = []
    for s in kb["sources"]:
        pid = s["position"]
        if pid not in by_pos:
            continue
        by_pos[pid]["raw"] += 1
        depth = s.get("textDepth", "unknown")
        if depth != "unknown":
            by_pos[pid]["depthKnown"] += 1
        if depth == "full":
            by_pos[pid]["full"] += 1
        source_provenance = s.get("provenance") or {}
        position_provenance = source_provenance.get("position") or {}
        quotes = [("source:" + field, prov) for field, prov in source_provenance.items()
                  if isinstance(prov, dict) and prov.get("quote")]
        quotes += [("edge:{}".format(i), edge.get("provenance"))
                   for i, edge in enumerate(s.get("restsOn") or []) if isinstance(edge, dict)
                   and isinstance(edge.get("provenance"), dict)
                   and edge["provenance"].get("quote")]
        quotes += factor_quotes.get(s.get("id"), [])
        bad = []
        # The position is itself a substantive claim about the source.  Earlier migrations could
        # remove an unsupported quote while preserving the old classification, which made the
        # source look fully auditable even though readers could not see why it belonged in that
        # camp.  Count that as missing grounding; a dependency/factor quote is not a substitute.
        if not position_provenance.get("quote"):
            by_pos[pid]["missing"] += 1
            bad.append("source:position (absent)")
        for field, prov in quotes:
            by_pos[pid]["quotes"] += 1
            if is_verified_exact(prov):
                by_pos[pid]["exact"] += 1
                continue
            status = prov.get("verifiedQuote")
            bucket = "altered" if status == "fuzzy" else "missing" if status == "missing" else "unchecked"
            by_pos[pid][bucket] += 1
            bad.append(field)
        if bad:
            if depth == "full":
                by_pos[pid]["unverifiedFull"] += 1
            flagged.append({"id": s["id"], "title": s.get("title"), "position": pid,
                            "fields": bad, "textDepth": depth})
    positions = []
    for p in kb["positions"]:
        c = by_pos[p["id"]]
        positions.append({"id": p["id"], "label": p["label"], "hue": p["hue"], **c})
    return {"positions": positions, "flagged": flagged}


_LOW_CONFIDENCE = 0.5


def confidence_audit(kb):
    """Whether a source's POSITION assignment rests on a confident quote (see prompts/ingest.md
    / ingest/pipeline.py's "quote RELEVANCE, not just presence" rule and SCHEMA.md's
    extractionConfidence field).

    This is a different failure mode from quote_audit: that checks whether a quote is REAL
    (present in the fetched text); this checks whether a real quote is actually a confident
    basis for the position it's filed under. A low extractionConfidence means the labeller
    itself flagged the quote as a loose or partial match -- worth a curator's second look,
    same spirit as the funding/method/quote audits: never block ingestion, always surface the
    soft spot honestly. Sources with no recorded extractionConfidence (legacy data, or a
    paste-back delta that never set it) are excluded from both the warning and the denominator,
    never guessed as confident or not."""
    by_pos = {p["id"]: {"raw": 0, "classed": 0, "low": 0} for p in kb["positions"]}
    flagged = []
    for s in kb["sources"]:
        pid = s["position"]
        if pid not in by_pos:
            continue
        by_pos[pid]["raw"] += 1
        prov = (s.get("provenance") or {}).get("position") or {}
        conf = prov.get("extractionConfidence")
        if conf is None:
            continue
        by_pos[pid]["classed"] += 1
        if conf < _LOW_CONFIDENCE:
            by_pos[pid]["low"] += 1
            flagged.append({"id": s["id"], "title": s.get("title"), "position": pid,
                            "confidence": conf})
    positions = []
    for p in kb["positions"]:
        c = by_pos[p["id"]]
        share = (c["low"] / c["classed"]) if c["classed"] else 0
        positions.append({"id": p["id"], "label": p["label"], "hue": p["hue"], "share": share,
                          "weak": bool(c["low"] >= 3 or (c["low"] >= 2 and share >= 0.3)), **c})
    flagged.sort(key=lambda f: f["confidence"])
    return {"positions": positions, "flagged": flagged}


def funding_skew(kb):
    """Which position *interested* money (industry or advocacy) most favours, plus how much of
    the case rests on sources that don't disclose funding. Defaulting unclear funding to
    'Undisclosed' (not 'independent') is what makes this honest: it surfaces the gap instead of
    fabricating independence."""
    interested = [s for s in kb["sources"] if _low(s["funding"]) in ("industry", "advocacy")]
    undisclosed = sum(1 for s in kb["sources"] if _low(s["funding"]) == "undisclosed")
    total = len(kb["sources"])
    if not interested and not undisclosed:
        return None
    top, leaders, counts = None, [], []
    if interested:
        by = {p["id"]: 0 for p in kb["positions"]}
        for s in interested:
            by[s["position"]] = by.get(s["position"], 0) + 1
        high = max(by.values())
        leaders = [{"id": p["id"], "label": p["label"], "count": by[p["id"]]}
                   for p in kb["positions"] if by[p["id"]] == high and high > 0]
        counts = [{"id": p["id"], "label": p["label"], "count": by[p["id"]]}
                  for p in kb["positions"] if by[p["id"]] > 0]
        top = leaders[0] if len(leaders) == 1 else None
    return {"n": len(interested), "top": top, "leaders": leaders, "counts": counts,
            "tied": len(leaders) > 1, "undisclosed": undisclosed, "total": total}


def blindspots(kb, min_support=2):
    """Evidence types / populations present in the case but absent from a position's own
    sources. Operationalises FLF's 'surface what's missing'.

    Only types backed by >= min_support sources case-wide count as 'present' — otherwise a
    single source with a hyper-specific population (e.g. one cohort's exact group) becomes a
    'blindspot' for every other position, drowning the real gaps in noise. (Workstream C.)"""
    evc, popc = {}, {}
    for s in kb["sources"]:
        evc[s["evidence"]] = evc.get(s["evidence"], 0) + 1
        if s["population"] and s["population"] != "—":
            popc[s["population"]] = popc.get(s["population"], 0) + 1
    all_ev = [e for e in dict.fromkeys(s["evidence"] for s in kb["sources"])
              if evc.get(e, 0) >= min_support]
    all_pop = [x for x in dict.fromkeys(s["population"] for s in kb["sources"])
               if x and x != "—" and popc.get(x, 0) >= min_support]
    out = []
    for p in kb["positions"]:
        mine = [s for s in kb["sources"] if s["position"] == p["id"]]
        ev = {s["evidence"] for s in mine}
        pop = {s["population"] for s in mine}
        out.append({"id": p["id"], "label": p["label"], "hue": p["hue"],
                    "missingEvidence": [e for e in all_ev if e not in ev],
                    "missingPop": [x for x in all_pop if x not in pop]})
    return out


def crux_score(factor, positions):
    """Spread of a factor's weighting across positions (0..3). A factor becomes a crux only
    once enough positions have weighed in -- so cruxes emerge as the KB grows."""
    vals = [WV.get(factor["weights"].get(p["id"])) for p in positions]
    vals = [v for v in vals if v]  # drop None (no weight) and 0 (n/a)
    if len(vals) < 2:
        return 0
    return max(vals) - min(vals)


def cruxes(kb):
    """Per factor: how the camps weigh it, and WHAT KIND of decision-relevant factor it is.

    A single spread>=2 test misses factors that matter for reasons other than a large weight
    disagreement (the old detector found ~1 of 3 hand-picked cruxes per case). So we surface
    principled, separately-labelled kinds, over ordinal weights (high=3/med=2/low=1; n/a and
    un-weighed excluded):

      crossCampCrux            >=2 camps weigh it AND their weights differ by >=2 -- the classic
                               point of active disagreement.
      sharedPivot              >=2 camps BOTH rate it 'high' -- both sides agree it is decisive and
                               it is unresolved; a spread of 0 hides this ("Hawking radiation").
      oneSidedLoadBearing      exactly ONE camp weighs it and rates it 'high' -- a load-bearing
                               assumption no other camp has engaged ("the safety argument itself").
      missingCounterassessment >=2 camps engaged and >=1 rates it 'high', but >=1 position gave it
                               NO weight -- a decisive point a camp has left unanswered.
      contestedWeight          >=2 camps weigh it and differ by exactly 1 -- a milder disagreement
                               (surfaced for the reader, but below the crux bar).

    isCrux (the headline "genuine divergence") stays tight = crossCampCrux OR sharedPivot, so the
    crux COUNT keeps its discriminating power (it does NOT balloon to every factor). loadBearing =
    isCrux OR oneSidedLoadBearing OR missingCounterassessment -- "this factor is doing real work in
    the dispute", which is what 'surface what matters' asks for. Factor label variants are folded at
    ingestion (engine/merge._resolve_factor), so aliases don't split a crux here."""
    num_pos = len(kb["positions"])
    out = []
    for f in kb["factors"]:
        ords = [WV.get(f["weights"].get(p["id"])) for p in kb["positions"]]
        ords = [v for v in ords if v]                       # drop None (no weight) and 0 (n/a)
        engaged = len(ords)
        maxw = max(ords) if ords else 0
        highs = sum(1 for v in ords if v == 3)
        sp = crux_score(f, kb["positions"])
        unaddressed = 0 < engaged < num_pos
        cross = engaged >= 2 and sp >= 2
        shared = highs >= 2
        one_sided = engaged == 1 and maxw == 3
        missing = engaged >= 2 and unaddressed and maxw == 3
        contested = engaged >= 2 and sp == 1
        is_crux = cross or shared
        out.append({"id": f["id"], "label": f["label"], "spread": sp, "engaged": engaged,
                    "isCrux": is_crux, "crossCampCrux": cross, "sharedPivot": shared,
                    "oneSidedLoadBearing": one_sided, "missingCounterassessment": missing,
                    "contestedWeight": contested,
                    "loadBearing": bool(is_crux or one_sided or missing)})
    return out


def _root_label(kb, rk, weight, secondary_only, nonhuman=frozenset(), provisional=frozenset()):
    """Human-readable description of a resolved root for the 'show your work' breakdown."""
    notes = []
    if rk in secondary_only:
        notes.append("cited only via a review")
    if rk in nonhuman:
        notes.append("animal / in-vitro")
    if rk in provisional:
        notes.append("proposed/unconfirmed")
    suffix = (" — " + ", ".join(notes)) if notes else ""
    if rk.startswith("ds:"):
        return _ds_label(kb, rk[3:]) + suffix
    if rk.startswith("primpool:"):
        return "unnamed first-hand claims (primary sources naming no evidence base, counted as one voice)"
    if rk.startswith("prim:"):        # legacy own-root from a pre-pooling KB
        sid = rk[5:]
        t = next((s.get("title") for s in kb["sources"] if s["id"] == sid), sid)
        return (t or sid)[:60] + (suffix or " — its own primary observation")
    if rk.startswith("secpool:"):
        return "secondary literature (reviews/commentary counted as one voice)"
    if rk.startswith("cycle:"):
        return "circular citation loop (no primary grounding)"
    return rk


def independence(kb, res=None):
    """The anti-false-balance core. Per position, how much CONFIRMED evidentiary-root coverage
    support it — after collapsing shared datasets, secondary echo, and circular citation (see
    MECHANISM.md and engine/roots.py).
        raw          = source count
        distinct     = number of distinct resolved roots
        nEff         = sum of distinct-root strengths (each root ONCE) -> confirmed-root coverage
        concentration= share of the position's sourcing resting on the single most-relied-on root
        bases        = the full 'show your work' breakdown: per root, 'weight' (source-weighted
                       incidence, what concentration reads) and 'strength' (its one-time
                       contribution to nEff; the strengths sum to nEff exactly)
        collapsedSecondary = how many secondary sources folded into the one 'secondary voice'
        circular     = circular-corroboration loops touching this position

    The fixed-graph invariant (enforced by tests/test_independence.py, incl. a randomized property
    test): adding a source with only outgoing edges NEVER lowers any position's nEff, and raises it only by introducing a new
    root or upgrading an existing root's strength (primary grounding for a review-only dataset,
    human evidence for an animal-only root). Correlated, derivative, or circular evidence lands
    on roots already counted, so it moves nEff nowhere — it can only push CONCENTRATION up, and
    the pile-up is surfaced there. Correcting root identity or resolving a pending edge CAN lower
    nEff (intentionally). What this cannot see is a source that fabricates a new root
    outright (claiming a dataset that doesn't back it) — that is an edge-fabrication attack,
    caught (partially) by quote verification, not by this arithmetic; see MECHANISM.md §8."""
    res = _roots.resolve(kb) if res is None else res
    inc = _root_incidence(kb, res)
    pres = _root_presence(kb, res)
    sec_only = res["secondary_only"]
    nonhuman = res.get("nonhuman_only", frozenset())
    prov = res.get("provisional", frozenset())
    circ_by_pos = {}
    for c in res["circular"]:
        for pid in c["positions"]:
            circ_by_pos.setdefault(pid, []).append(c["sources"])
    out = []
    for p in kb["positions"]:
        mine = [s for s in kb["sources"] if s["position"] == p["id"]]
        weights = inc[p["id"]]
        strengths = pres[p["id"]]
        raw = len(mine)
        n_eff = _n_indep(strengths)
        unsupported = {rk for s in mine
                       for rk in res.get("unadmitted_source_roots", {}).get(s["id"], ())}
        provisional_count = sum(1 for rk in strengths if rk in prov or rk in unsupported)
        # What the proposed roots would contribute after confirmation, preserving any independent
        # secondary-only / non-human discounts. This is audit information only, never headline nEff.
        provisional_potential = sum(
            _roots.root_strength(rk, sec_only - res.get("unadmitted_primary_roots", set()),
                                 nonhuman, frozenset())
            for rk in strengths if rk in prov or rk in unsupported)
        total_w = sum(weights.values())
        top_key, top_w = None, 0.0
        for rk, w in weights.items():
            if w > top_w:
                top_key, top_w = rk, w
        conc = (top_w / total_w) if total_w else 0
        confirmed_by = res.get("confirmed_by", {})
        alias_suspects = res.get("alias_suspects", frozenset())
        base_kind = res.get("base_kind", {})
        bases = sorted(
            ({"key": rk, "label": _root_label(kb, rk, w, sec_only, nonhuman, prov), "kind": res["kind"][rk],
              "baseKind": base_kind.get(rk, "dataset") if rk.startswith("ds:") else None,
              "proposition": _ds_meta(kb, rk[3:])[1] if rk.startswith("ds:") else "",
              "weight": round(w, 2), "strength": round(strengths[rk], 2),
              "secondaryOnly": rk in sec_only, "nonHuman": rk in nonhuman, "provisional": rk in prov,
              "supportUnconfirmed": rk in unsupported,
              "aliasSuspect": rk in alias_suspects,
              "confirmedBy": confirmed_by.get(rk)}
             for rk, w in weights.items()), key=lambda b: -b["weight"])
        collapsed_secondary = sum(1 for s in mine
                                  if ("secpool:" + p["id"]) in res["source_roots"].get(s["id"], ()))
        # back-compat 'topDataset' only when the dominant root is an actual dataset. 'count' is the
        # (possibly fractional) source-weighted incidence that drives concentration; 'sources' is the
        # plain INTEGER number of this position's sources resting on it (for human-readable copy).
        top_ds = None
        if top_key and top_key.startswith("ds:"):
            top_src = sum(1 for s in mine if top_key in res["source_roots"].get(s["id"], ()))
            top_ds = {"label": _ds_label(kb, top_key[3:]), "id": top_key[3:],
                      "count": round(top_w, 2), "sources": top_src}
        # evidence-type / tier mix -- so nEff (a COUNT of roots) is never read as evidence QUALITY.
        # A position with one decisive RCT (nEff 1) and one with seven anecdotes (nEff 7) look very
        # different here even though the headline count favours the latter; this puts the design mix
        # next to the number so the reader weighs quality alongside independence.
        ev_counts = {}
        prim = 0
        for s in mine:
            ev = s.get("evidence") or "—"
            ev_counts[ev] = ev_counts.get(ev, 0) + 1
            if _roots.tier_of(kb, s) == "primary":
                prim += 1
        ev_mix = sorted(ev_counts.items(), key=lambda kv: -kv[1])
        out.append({
            "id": p["id"], "label": p["label"], "hue": p["hue"],
            "raw": raw, "distinct": len(weights), "nEff": n_eff, "concentration": conc,
            "provisionalCount": provisional_count,
            "provisionalPotential": round(provisional_potential, 2),
            "topDataset": top_ds,
            "datasets": [b["label"] for b in bases],
            "bases": bases,
            "collapsedSecondary": collapsed_secondary,
            "circular": circ_by_pos.get(p["id"], []),
            "concentrated": top_w >= 2 and conc >= 0.5,
            "evidenceMix": [{"evidence": e, "count": n} for e, n in ev_mix],
            "primaryCount": prim, "secondaryCount": len(mine) - prim,
        })
    return out


def warnings(kb, ind=None, ma=None, qa=None, ca=None):
    """Unified warning feed -- one consistent shape for every 'this needs scrutiny' signal the
    assessment produces (concentration, method-bias, unverified quotes, weak quote grounding),
    so the CLI and viewer render every warning through ONE mechanism instead of a bespoke
    banner/print-block per audit. No new signal lives here: each condition and its wording is
    exactly what independence()/method_audit()/quote_audit()/confidence_audit() already
    compute -- this only collects and picks the single worst instance of each kind, matching
    what was shown before this existed (worstConcentration / methodMonoculture /
    quoteAudit["flagged"])."""
    ind = independence(kb) if ind is None else ind
    ma = method_audit(kb) if ma is None else ma
    qa = quote_audit(kb) if qa is None else qa
    ca = confidence_audit(kb) if ca is None else ca
    out = []

    unsupported = [(p, b) for p in ind for b in p.get("bases", [])
                   if b.get("supportUnconfirmed") and not b.get("strength")]
    if unsupported:
        p, b = unsupported[0]
        out.append({
            "kind": "support-edge", "positionId": p["id"], "label": p["label"], "hue": p["hue"],
            "badge": "unconfirmed support link",
            "headline": "A claimed evidence link is excluded pending review.",
            "detail": ('{} source-to-root link{} {} a verified dependency sentence or curator '
                       'admission. They remain visible but add zero confirmed root coverage — e.g. '
                       '"{}" under "{}".').format(
                           len(unsupported), "s" if len(unsupported) != 1 else "",
                           "lack" if len(unsupported) != 1 else "lacks", b["label"], p["label"]),
        })

    cand = [p for p in ind if p["concentrated"] and p["topDataset"]]
    cand.sort(key=lambda p: (p["topDataset"]["count"], p["concentration"], p["raw"]), reverse=True)
    if cand:
        w = cand[0]
        out.append({
            "kind": "concentration", "positionId": w["id"], "label": w["label"], "hue": w["hue"],
            "badge": "concentration risk",
            "headline": "Apparent consensus is correlated.",
            "detail": ('The "{}" position lists {} sources, but {} of them rest on one dataset — {}. '
                           'That is {:g} confirmed-root coverage, not {} separate evidence bases. Counting sources '
                       'here overstates the weight of evidence.').format(
                           w["label"], w["raw"], w["topDataset"]["sources"], w["topDataset"]["label"],
                           round(w["nEff"], 1), w["raw"]),
        })

    mcand = [m for m in ma if m["monoculture"]]
    mcand.sort(key=lambda m: (m["top"]["count"], m["top"]["share"], m["raw"]), reverse=True)
    if mcand:
        m = mcand[0]
        out.append({
            "kind": "method-monoculture", "positionId": m["id"], "label": m["label"], "hue": m["hue"],
            "badge": "method-bias risk",
            "headline": "Method-bias warning.",
            "detail": ('In the "{}" position, {} of {} sources fall into the same method-risk '
                       'family: {}. Separate datasets can still be wrong together when studies '
                       'share the same design weakness.').format(
                           m["label"], m["top"]["count"], m["raw"], m["top"]["label"]),
        })

    flagged = qa.get("flagged") or []
    if flagged:
        f = flagged[0]
        pos_by_id = {p["id"]: p for p in ind}
        p = pos_by_id.get(f["position"])
        out.append({
            "kind": "quote", "positionId": f["position"],
            "label": p["label"] if p else f["position"], "hue": p["hue"] if p else "#8a6510",
            "badge": "unverified quote{}".format("" if len(flagged) == 1 else "s"),
            "headline": "Unverified quote{}.".format("" if len(flagged) == 1 else "s"),
            "detail": ('{} source{} {} stored quote wording without a current verbatim audit '
                       'against hashed fetched text — e.g. "{}". It may be altered, absent from '
                       'the fetched material, or a legacy unchecked excerpt; it is shown as a '
                       'summary rather than inside quotation marks until reverified.').format(
                           len(flagged), "" if len(flagged) == 1 else "s",
                           "has" if len(flagged) == 1 else "have",
                           f.get("title") or f["id"]),
        })

    wcand = [p for p in ca["positions"] if p["weak"]]
    wcand.sort(key=lambda p: (p["low"], p["share"], p["raw"]), reverse=True)
    if wcand:
        w = wcand[0]
        out.append({
            "kind": "low-confidence", "positionId": w["id"], "label": w["label"], "hue": w["hue"],
            "badge": "weak quote grounding",
            "headline": "Some position assignments rest on a weak quote.",
            "detail": ('In the "{}" position, {} of {} sources have a labelling confidence '
                       'below 50% — a real quote that only loosely supports the position it is '
                       'filed under, not a fabricated one. Worth a curator\'s second look.').format(
                           w["label"], w["low"], w["classed"]),
        })

    # multi-model ensemble: sources where the models had NO majority position (ingest/ensemble.py).
    # The warning CARRIES the flagged sources and each one's vote breakdown, so a reader sees
    # exactly which sources are contested and what each model proposed — not just a count.
    dis = [s for s in kb["sources"] if (s.get("modelAgreement") or {}).get("flagged")]
    if dis:
        n = len(dis)
        out.append({
            "kind": "model-disagreement", "positionId": None,
            "label": "{} source{} to review".format(n, "" if n == 1 else "s"),
            "hue": "#8a6510", "badge": "model disagreement",
            "headline": "The labelling models disagreed on {} source{}.".format(
                n, "" if n == 1 else "s"),
            "detail": ('When several models label a source independently, they usually agree; on '
                       'these they split on which POSITION the source supports, and the '
                       'highest-confidence model\'s label was used. These sources ARE included in '
                       'every count under that label — the flag marks them for a curator\'s '
                       're-check (re-label or remove via curation), not an exclusion. Each is '
                       'listed with every model\'s proposal — read the source itself to '
                       'adjudicate.'),
            "sources": [{"id": s["id"], "title": s.get("title") or s["id"],
                         "position": s["position"],
                         "vote": (s.get("modelAgreement") or {}).get("positionVote") or {},
                         "fields": (s.get("modelAgreement") or {}).get("disagreedFields") or []}
                        for s in dis],
        })
    return out


def dominant_dataset(kb, res=None):
    """Case-wide, which single dataset ROOT underlies the most sources -- counted over RESOLVED
    roots (a review that restsOn a study counts toward that study's dataset), not raw restsOn
    strings, so derivation edges and src: references don't distort it. The Huanan-market / NHS-HPFS
    detector. Ties returned together."""
    res = _roots.resolve(kb) if res is None else res
    counts = {}
    for s in kb["sources"]:
        for r in res["source_roots"].get(s["id"], ()):
            if r.startswith("ds:"):
                counts[r] = counts.get(r, 0) + 1
    if not counts:
        return None
    mx = max(counts.values())
    n = len(kb["sources"])
    return {"labels": [_ds_label(kb, r[3:]) for r in counts if counts[r] == mx],
            "count": mx, "total": n, "share": mx / n if n else 0}


def assess(kb, res=None):
    """The whole Assessment artifact -- one dict, diffable across versions. Resolves the derivation
    graph ONCE and threads it through every root-based metric (independence, weighted distribution,
    dominant dataset), instead of each re-resolving -- so one assess() is one resolve()."""
    res = _roots.resolve(kb) if res is None else res
    ind = independence(kb, res)
    ma = method_audit(kb)
    qa = quote_audit(kb)
    ca = confidence_audit(kb)
    return {
        "version": kb.get("meta", {}).get("version"),
        "distribution": distribution(kb),
        "weightedDistribution": weighted_distribution(kb, res),
        "fundingSkew": funding_skew(kb),
        "blindspots": blindspots(kb),
        "cruxes": cruxes(kb),
        "independence": ind,
        "methodAudit": ma,
        "quoteAudit": qa,
        "confidenceAudit": ca,
        "dominantDataset": dominant_dataset(kb, res),
        "warnings": warnings(kb, ind, ma, qa, ca),
    }


def _pct(x):
    return str(round(x * 100)) + "%"


def diff_assessments(before, after):
    """Structured, human-readable diff of two assessment dicts -- the 'what changed' that
    makes each update's epistemic effect visible. Returns a list of lines."""
    lines = []
    bd = {d["id"]: d["count"] for d in before["distribution"]}
    for d in after["distribution"]:
        was = bd.get(d["id"], 0)
        if d["count"] != was:
            lines.append("distribution: {} {} → {}".format(d["label"], was, d["count"]))
    bi = {p["id"]: p for p in before["independence"]}
    for p in after["independence"]:
        b = bi.get(p["id"])
        if not b:
            lines.append("+ new position: " + p["label"])
            continue
        # confirmed-root coverage (nEff) -- the headline number the old diff omitted
        if abs(p["nEff"] - b["nEff"]) > 0.05:
            lines.append("confirmed-root coverage: {} {} → {}".format(
                p["label"], round(b["nEff"], 1), round(p["nEff"], 1)))
        elif p["distinct"] != b["distinct"]:
            lines.append("distinct roots: {} {} → {}".format(
                p["label"], b["distinct"], p["distinct"]))
        if abs(p["concentration"] - b["concentration"]) > 1e-9:
            top = p["topDataset"]["label"] if p["topDataset"] else "—"
            lines.append("concentration: {} {} → {} (top: {})".format(
                p["label"], _pct(b["concentration"]), _pct(p["concentration"]), top))
        if (not b["concentrated"]) and p["concentrated"]:
            lines.append("⚠ {} crossed into CONCENTRATED".format(p["label"]))
    bdom, adom = before["dominantDataset"], after["dominantDataset"]
    if adom and (not bdom or "/".join(bdom["labels"]) != "/".join(adom["labels"])
                 or bdom["count"] != adom["count"]):
        prev = ("/".join(bdom["labels"]) + " " + str(bdom["count"])) if bdom else "—"
        lines.append("most-reused case-wide: {} → {} {}/{}".format(
            prev, "/".join(adom["labels"]), adom["count"], adom["total"]))
    bc = {c["id"] for c in before["cruxes"] if c["isCrux"]}
    for c in after["cruxes"]:
        if c["isCrux"] and c["id"] not in bc:
            lines.append("+ new crux: " + c["label"])
    bb = {p["id"]: set(p["missingEvidence"]) | set(p["missingPop"]) for p in before["blindspots"]}
    for p in after["blindspots"]:
        was = bb.get(p["id"])
        if was is None:
            continue
        now = set(p["missingEvidence"]) | set(p["missingPop"])
        for x in was - now:
            lines.append('blindspot closed: {} now covers "{}"'.format(p["label"], x))
        for x in now - was:
            lines.append('blindspot opened: {} missing "{}"'.format(p["label"], x))
    # warnings appearing / clearing -- so the diff records when a source trips or resolves a flag
    bw = {(w["kind"], w.get("positionId")): w for w in before.get("warnings", [])}
    aw = {(w["kind"], w.get("positionId")): w for w in after.get("warnings", [])}
    for k, w in aw.items():
        if k not in bw:
            lines.append("⚠ new warning: {} — {}".format(w.get("badge", w["kind"]), w.get("label", "")))
    for k, w in bw.items():
        if k not in aw:
            lines.append("✓ warning cleared: {} — {}".format(w.get("badge", w["kind"]), w.get("label", "")))
    return lines
