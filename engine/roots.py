"""Root-basis resolution — the engine behind the independence metric (see MECHANISM.md).

Resolves every source to the primary EVIDENTIARY ROOTS it ultimately depends on, by following
`restsOn` edges (to datasets AND to other sources), collapsing strongly-connected citation cycles
(circular corroboration) to a single root, and falling back to evidence-tier defaults for ungrounded
sources. Pure functions of the KB; deterministic; no side effects.

Root keys produced:
    ds:<id>           a real dataset / cohort / experiment
    primpool:<posId>  the single 'unnamed first-hand voice' for a position — every ungrounded
                      PRIMARY source that names NO evidence base collapses here (you earn a
                      distinct root by NAMING a distinct dataset, not by claiming the primary tier)
    secpool:<posId>   the single 'ungrounded secondary' voice for a position (all echo collapses here)
    cycle:<sourceId>  a circular-corroboration loop with no primary grounding (flagged)

Design note (why ungrounded primaries pool): an earlier version gave each ungrounded primary its
OWN root (prim:<sourceId>, 'benefit of the doubt'). That is the flooding hole — an adversary (or a
careless labeller) marks ten rehashes 'Observational' with an empty restsOn and mints ten roots,
bypassing the echo collapse that only fired for the secondary tier. Pooling makes ungrounded
primaries collapse symmetrically with ungrounded secondaries: a source that claims original data but
names none is epistemically indistinguishable from an assertion and is worth one pooled voice. A
REAL primary study keeps full, distinct credit by naming its own trial/cohort/sample in restsOn
(the labelling prompt requires this). prim:<sourceId> keys from older KBs still resolve for
back-compat but are no longer produced.
"""
import re

# Evidence-base kinds. Empirical bases carry data (population, samples) and take the empirical
# discounts; theoretical bases are derivations/claims and must not be halved for 'non-human'
# population. A base with no kind defaults to 'dataset' (empirical) for full back-compat.
_EMPIRICAL_KINDS = {"dataset", "experiment", "observation"}
_NON_EMPIRICAL_KINDS = {"argument", "model", "document"}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s if s is not None else "").lower()).strip()


# Evidence type -> tier. Only matters for UNGROUNDED sources: a grounded source resolves through its
# dataset(s) regardless of tier. A case can override by putting "tier" on the evidence vocab term.
# Keys are normalised (see _norm) so that punctuation like "Experimental (RCT)" or
# "Narrative/Commentary" still matches. An UNRECOGNISED type defaults to SECONDARY (see tier_of):
# the conservative direction — a novel/opinion label must not mint a free independent root; a case
# that has a genuinely new primary DESIGN adds it to its vocab with tier="primary".
_TIER = {_norm(k): v for k, v in {
    # -- primary: designs that MAKE new evidence (a first-hand data collection) --
    "observational": "primary", "experimental (rct)": "primary", "experimental": "primary",
    "randomized controlled trial": "primary", "randomised controlled trial": "primary",
    "rct": "primary", "clinical trial": "primary", "controlled trial": "primary",
    "cohort": "primary", "cohort study": "primary", "prospective cohort": "primary",
    "retrospective cohort": "primary", "case-control": "primary", "case control": "primary",
    "cross-sectional": "primary", "cross sectional": "primary", "longitudinal": "primary",
    "case series": "primary", "ecological": "primary", "field study": "primary",
    "mechanistic": "primary", "theoretical analysis": "primary",
    "theoretical critique": "primary", "modelling": "primary", "simulation": "primary",
    # A meta-analysis / systematic review is a SYNTHESIS of others' studies, not new primary data.
    # It only counts as independent if it TAGS the trials it pools (then it resolves through them);
    # an untagged one is echo and collapses into the position's one secondary voice (MECHANISM.md §3).
    "meta-analysis": "secondary", "systematic review": "secondary", "scoping review": "secondary",
    "umbrella review": "secondary",
    "evidence-synthesis": "secondary", "expert advisory": "secondary", "expert review": "secondary",
    "narrative/commentary": "secondary", "narrative": "secondary", "commentary": "secondary",
    "institutional statement": "secondary", "position statement": "secondary",
    "consensus statement": "secondary", "editorial": "secondary", "perspective": "secondary",
    "opinion": "secondary", "letter": "secondary", "review": "secondary", "guideline": "secondary",
}.items()}


def tier_of(kb, source):
    """primary | secondary for a source: the case vocab's tier if set, else the default map, else
    SECONDARY for an unrecognised label (conservative — an unknown/opinion tier can't mint a root)."""
    ev = _norm(source.get("evidence"))
    for t in (kb.get("vocab", {}).get("evidence") or []):
        if _norm(t.get("label")) == ev or any(_norm(a) == ev for a in t.get("aliases", [])):
            if t.get("tier") in ("primary", "secondary"):
                return t["tier"]
            break
    return _TIER.get(ev, "secondary")


def _dataset_confirmation(d):
    """An auditable confirmation record for a dataset, or None if it is not curator-confirmed.

    Reads the structured object {status, method, by/source/curator, ts, note} and falls back to the
    legacy boolean {"confirmed": true}. A structured object whose status is anything other than
    'confirmed' (e.g. 'provisional', 'disputed') counts as NOT confirmed. This is what replaces the
    bare boolean: a confirmed root now records HOW it was confirmed and by whom, so a reader can audit
    the claim instead of trusting an opaque flag (see SCHEMA.md, MECHANISM.md §8)."""
    c = d.get("confirmation")
    if isinstance(c, dict):
        if c.get("status", "confirmed") != "confirmed":
            return None
        rec = {"method": c.get("method") or "curator"}
        for k in ("by", "source", "curator", "ts", "timestamp", "note"):
            if c.get(k):
                rec[k] = c[k]
        return rec
    if d.get("confirmed"):
        return {"method": "curator"}
    return None


# population tokens / phrases that mark a NON-human study (animal model or in-vitro). Token match
# for short words (so "moderate" can't match "rat"); phrase match for the multi-word ones.
_NONHUMAN_TOKENS = {"mice", "mouse", "murine", "rat", "rats", "rodent", "rodents", "animal",
                    "animals", "rabbit", "rabbits", "porcine", "swine", "canine", "feline",
                    "zebrafish", "drosophila", "bovine", "ovine", "vitro"}
_NONHUMAN_PHRASES = ("in vitro", "ex vivo", "cell line", "cell culture", "animal model")


def _is_nonhuman(source):
    """True if the source's population marks it as an animal or in-vitro study (see prompt rule)."""
    p = _norm(source.get("population"))
    if not p:
        return False
    return bool(set(p.split()) & _NONHUMAN_TOKENS) or any(ph in p for ph in _NONHUMAN_PHRASES)


def _edges(source):
    """Split a source's restsOn into (dataset ids, source ids, edge_provenance).

    A restsOn entry is EITHER a bare string ref, OR an edge object carrying its own dependency
    quote: {"ref": "<id>", "provenance": {"quote": "...", "verifiedQuote": "exact"}}. Both are
    accepted so per-edge verification is auditable without breaking string-only KBs. Source edges
    are stored as 'src:<id>'; everything else is a dataset root. Case-insensitive prefix check:
    merge.py always normalizes to lowercase, but a hand-authored/seed KB writing "SRC:<id>" should
    not silently become a fake dataset (see SCHEMA.md on seed data).

    edge_provenance maps the resolved ref key (dataset id, or 'src:<id>') to that ONE edge's
    provenance dict — so a verified quote confirms only the edge it actually annotates, never a
    sibling edge on the same source and never a root reached only by inheritance."""
    ds, src, edge_prov = [], [], {}
    for e in source.get("restsOn") or []:
        if isinstance(e, dict):
            ref = str(e.get("ref") or "").strip()
            prov = e.get("provenance") if isinstance(e.get("provenance"), dict) else None
        else:
            ref, prov = str(e).strip(), None
        if not ref:
            continue
        if ref.lower().startswith("src:"):
            key = "src:" + ref[4:]
            src.append(ref[4:])
        else:
            key = ref
            ds.append(ref)
        if prov:
            edge_prov[key] = prov
    return ds, src, edge_prov


def _tarjan(adj):
    """Strongly-connected components of the source->source graph. Returns (sccs, comp_of)."""
    index = {}; low = {}; onstack = {}; stack = []; counter = [0]; sccs = []

    def strong(v):
        # iterative Tarjan to avoid recursion limits on long chains
        work = [(v, 0)]
        while work:
            node, pi = work[-1]
            if pi == 0:
                index[node] = low[node] = counter[0]; counter[0] += 1
                stack.append(node); onstack[node] = True
            recurse = False
            neighbours = adj.get(node, [])
            for i in range(pi, len(neighbours)):
                w = neighbours[i]
                if w not in index:
                    work[-1] = (node, i + 1)
                    work.append((w, 0)); recurse = True; break
                elif onstack.get(w):
                    low[node] = min(low[node], index[w])
            if recurse:
                continue
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop(); onstack[w] = False; comp.append(w)
                    if w == node:
                        break
                sccs.append(comp)
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])

    for v in adj:
        if v not in index:
            strong(v)
    comp_of = {}
    for i, comp in enumerate(sccs):
        for sid in comp:
            comp_of[sid] = i
    return sccs, comp_of


def resolve(kb):
    """Resolve every source to its set of root keys.

    Returns a dict:
      source_roots : {source_id: set(root_key)}
      circular     : [ {sources:[ids], positions:[ids]} ]  pure circular-corroboration loops
      secondary_only : set(root_key)  dataset roots asserted ONLY via secondary sources
      kind         : {root_key: 'dataset'|'primary'|'secondary'|'cycle'}
    """
    sources = {s["id"]: s for s in kb["sources"]}
    adj = {sid: [t for t in _edges(s)[1] if t in sources] for sid, s in sources.items()}
    sccs, comp_of = _tarjan(adj)

    circular = []

    # component -> the OTHER components it draws roots from (via external source->source edges). The
    # SCC collapse guarantees this component graph is a DAG, so roots resolve by an ITERATIVE
    # post-order over it — recursion here used to raise RecursionError on a long derivation chain.
    comp_deps = {}
    for ci in range(len(sccs)):
        deps = set()
        for sid in sccs[ci]:
            for t in _edges(sources[sid])[1]:
                if t in comp_of and comp_of[t] != ci:
                    deps.add(comp_of[t])
        comp_deps[ci] = deps

    memo = {}

    def comp_roots(ci0):
        stack = [ci0]
        while stack:
            ci = stack[-1]
            if ci in memo:
                stack.pop()
                continue
            pending = [d for d in comp_deps[ci] if d not in memo]
            if pending:                       # resolve dependencies first (post-order)
                stack.extend(pending)
                continue
            comp = sccs[ci]
            roots = set()
            for sid in comp:                  # dataset roots from any member
                for d in _edges(sources[sid])[0]:
                    roots.add("ds:" + d)
            for d in comp_deps[ci]:           # roots inherited from depended-on components
                roots |= memo[d]
            if not roots:                     # ungrounded component
                if len(comp) > 1:             # circular corroboration with no grounding -> flag
                    roots = {"cycle:" + min(comp)}
                    circular.append({"sources": sorted(comp),
                                     "positions": sorted({sources[s]["position"] for s in comp})})
                else:
                    s = sources[comp[0]]
                    # ungrounded, no named evidence base: a primary that names nothing collapses to
                    # the position's one 'unnamed first-hand voice' (primpool), a secondary to its
                    # review voice (secpool). Both pool per position (flooding adds one voice once).
                    roots = {"primpool:" + s["position"]} if tier_of(kb, s) == "primary" \
                        else {"secpool:" + s["position"]}
            memo[ci] = roots
            stack.pop()
        return memo[ci0]

    source_roots = {sid: comp_roots(comp_of[sid]) for sid in sources}

    # a dataset root is 'asserted only via secondary' if no PRIMARY source rests on it directly
    primary_ds = set()
    for s in kb["sources"]:
        if tier_of(kb, s) == "primary":
            for d in _edges(s)[0]:
                primary_ds.add("ds:" + d)
    all_ds = {r for rs in source_roots.values() for r in rs if r.startswith("ds:")}
    secondary_only = all_ds - primary_ds

    # evidence-base KIND (dataset | experiment | observation | argument | model | document). Empirical
    # bases default to 'dataset'; theoretical ones (argument/model/document) are NOT empirical data, so
    # the population-based 'non-human' halving must never touch them (a safety proof has no 'population').
    base_kind = {"ds:" + d["id"]: (d.get("kind") or "dataset") for d in kb.get("datasets", [])}
    non_empirical = {r for r, k in base_kind.items() if k in _NON_EMPIRICAL_KINDS}

    # a root is 'non-human only' if EVERY source resting on it is an animal / in-vitro study — it's
    # weaker evidence for a human/clinical question, so it counts at half (like secondary-only). This
    # is an EMPIRICAL discount: it never applies to a theoretical argument/model root.
    human, animal = set(), set()
    _COLLAPSED = ("secpool:", "primpool:", "cycle:")            # pooled voices: halving n/a
    for s in kb["sources"]:
        target = animal if _is_nonhuman(s) else human
        for r in source_roots[s["id"]]:
            if not r.startswith(_COLLAPSED):
                target.add(r)
    nonhuman_only = (animal - human) - non_empirical

    # ROOT ADMISSION: a dataset root is 'provisional' (unconfirmed) until the KB verifies it PER EDGE,
    # one of two auditable ways:
    #   (1) curator confirmation — the dataset carries a confirmation record (or legacy confirmed:true);
    #   (2) verified edge — a source that was really FETCHED (textDepth full/abstract/partial) carries a
    #       dependency quote that matched the fetched text FOR THAT SPECIFIC DATASET EDGE.
    # Two things are deliberately NOT enough, closing the old whitewash where one source-level quote
    # admitted every dataset a source touched:
    #   * an INHERITED root (reached only through a src:<id> citation edge) is never confirmed by the
    #     citing source's own quote — only a source that DIRECTLY names the dataset can vouch for it;
    #   * a verified quote on ONE edge does not confirm SIBLING datasets on the same source — a source
    #     claiming ten datasets must verify ten edges, not one (MECHANISM.md §8).
    # Text depth alone is insufficient (a model can quote an unrelated real sentence). A brand-new root
    # asserted only by unverified/public input is QUARANTINED from nEff; it stays visible in the audit
    # as a proposed base and enters nEff only after confirmation. confirmed_by records HOW each root was
    # confirmed, so the admission is itself auditable.
    _DEPTH_OK = {"full", "abstract", "partial"}
    confirmed_by = {}                                          # root_key -> {method, source?/by?/...}
    for d in kb.get("datasets", []):
        rec = _dataset_confirmation(d)
        if rec:
            confirmed_by["ds:" + d["id"]] = rec
    for s in kb["sources"]:
        if s.get("textDepth") not in _DEPTH_OK:
            continue
        d_ids, _src_ids, edge_prov = _edges(s)
        direct = {"ds:" + d for d in d_ids}                   # this source's DIRECT dataset edges
        # legacy source-level dependency quote: back-compat only. Applies to the source's direct
        # dataset edges (never inherited roots). Ambiguous across siblings, so new ingestion should
        # attach provenance to the specific edge object instead.
        legacy = (s.get("provenance") or {}).get("restsOn")
        if isinstance(legacy, dict) and ("verifiedQuote" in legacy or "quote" in legacy) \
                and legacy.get("verifiedQuote") in {"exact", "fuzzy"}:
            for rk in direct:
                confirmed_by.setdefault(rk, {"method": "verified-edge", "source": s["id"]})
        for ref_key, ep in edge_prov.items():                 # per-edge object provenance
            if ref_key.startswith("src:"):
                continue                                       # a citation edge cannot self-confirm
            rk = "ds:" + ref_key
            if rk in direct and ep.get("verifiedQuote") in {"exact", "fuzzy"}:
                confirmed_by.setdefault(rk, {"method": "verified-edge", "source": s["id"]})
    provisional = {r for r in all_ds if r not in confirmed_by}

    def kind_of(r):
        return {"d": "dataset", "p": "primary", "s": "secondary", "c": "cycle"}[
            ("d" if r.startswith("ds:")
             else "p" if r.startswith(("prim:", "primpool:"))     # own-root (legacy) or pooled voice
             else "s" if r.startswith("secpool:") else "c")]
    kinds = {r: kind_of(r) for rs in source_roots.values() for r in rs}

    return {"source_roots": source_roots, "circular": circular,
            "secondary_only": secondary_only, "nonhuman_only": nonhuman_only,
            "provisional": provisional, "confirmed_by": confirmed_by,
            "kind": kinds, "base_kind": base_kind}


def root_strength(root_key, secondary_only, nonhuman_only=frozenset(), provisional=frozenset()):
    """Independence weight a root contributes. Halved for a dataset known only through a secondary
    source (we heard about it, no primary source brought it in), halved for a root backed only by
    animal / in-vitro studies (weak evidence for a human question), and halved for a PROVISIONAL
    (unconfirmed / unverified) root contributes ZERO until a fetched dependency quote verifies it or
    a curator explicitly confirms it.
    See MECHANISM.md §6."""
    if root_key in provisional:
        return 0.0
    w = 1.0
    if root_key in secondary_only:
        w *= 0.5
    if root_key in nonhuman_only:
        w *= 0.5
    return w
