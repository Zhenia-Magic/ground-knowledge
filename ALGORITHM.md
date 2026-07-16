# Ground Knowledge — the algorithm (≤2 pages)

Everything below is pure, deterministic, stdlib-only Python over a portable JSON knowledge base
(`cases/*.kb.json`). No LLM, no I/O, no randomness. The live implementation is
`engine/roots.py` + `engine/assess.py`; this is the readable version.

## Data model (what a source carries)

```
position   : which camp the source supports
evidence   : tier, mapped to primary | secondary (a review/meta-analysis is secondary)
funding, population, textDepth ("full" | "abstract" | "partial" | "unknown")
restsOn    : list of edges. Each is EITHER
               "ds_x"                        a dataset root
               "src:<id>"                    a citation/derivation edge to another source
               {ref:"ds_x", provenance:{quote, verifiedQuote:"exact|fuzzy|missing"},
                            admission?:{status:"confirmed", method:"curator|legacy-migration",
                                        by, ts, note?}}
                                             an edge with its own quote and/or curator admission
dataset.confirmation : {status:"confirmed", method:"curator"|"verified-edge", by, ts,
                        source?}    # source is optional for curator, required for verified-edge
dataset.kind         : dataset | experiment | observation | argument | model | document
                       (absent = dataset). argument/model/document are THEORETICAL roots — first-
                       class roots, exempt from the empirical non-human discount.
```

## Step 1 — admit root identity and support edges separately

A named dataset can be real while a new source's claim to rely on it is false. The resolver therefore
requires both (a) confirmed root identity and (b) an admitted source→root/citation support link. A
verified dataset-edge sentence may establish both; a curator may record either decision explicitly.
Only current hashed `exact` verification counts—`fuzzy` is visibly unverified.

Public paste-back deltas cannot provide either trust field: the portal strips spoofable verification
and admission fields and queues the whole contribution for human review.
The same is true on the fetched-text path: quote verification may be computed there, but a model's
`admission` key is always deleted. Only `curate.confirm_edge` can write curator admission. Before
mutation, a total validator bounds arrays/strings and rejects malformed types. In a batch, opaque
`sourceId` values bind each delta to its fetched document; array order is never treated as identity.

## Step 2 — resolve every source through admitted edges to evidentiary roots

```
def resolve(kb):
    # collapse circular corroboration: SCCs of the source→source citation graph (Tarjan).
    # a cycle with no grounding becomes one VISIBLE "cycle" marker, flagged and worth zero.
    components = tarjan(admitted_citation_graph(kb))   # each SCC = one node in a DAG

    for component in reverse_topological(components):  # iterative post-order (no recursion limit)
        roots = { "ds:"+d for src in component for d in admitted_dataset_edges(src) }
        roots |= union(roots_of(dep) for dep in components_this_one_cites)
        if roots is empty:
            if len(component) > 1:  roots = { "cycle:"+min(component) }      # circular, ungrounded
            else:
                s = the one source
                # NAMING proposes a distinct root; admission is Step 2. Claiming a tier does neither.
                roots = { "primpool:"+s.position } if tier(s)=="primary"     # visible, zero credit
                        else { "secpool:"+s.position }                        # visible, zero credit
        memo[component] = roots
    source_roots = { s: memo[component_of(s)] for s in sources }
```

Consequences: ten reviews of the same study all resolve to that study's dataset root (echo → one
look); eight papers off one cohort → one root; `A→B→A` with admitted citation edges and nothing
primary → one visible, flagged, **zero-strength** cycle marker. Unadmitted links remain visible but
are not traversed.

The core admission sketch is:

```
confirmed_by = {}                                     # root → {method, source}
for d in datasets:
    if curator_confirmed(d):                          # {status:"confirmed", ...}  OR legacy bool
        confirmed_by["ds:"+d.id] = {method:"curator", ...}

for s in sources:
    direct = { "ds:"+d for d in dataset_edges(s) }    # DIRECT dataset edges only
    for edge in s.restsOn:
        if edge has valid curator/migration admission:
            admit_support(s, edge)
        if edge is a dataset edge AND edge.provenance has current hashed exact verification
           AND edge.quote names edge.ref's label/alias:
            admit_support(s, edge)
            confirmed_by.setdefault("ds:"+edge.ref, {method:"verified-edge", source:s.id})
    # legacy: source-level quote is accepted only when this source has EXACTLY ONE direct dataset

# Literal quote presence does not settle root identity. Generic labels cannot auto-confirm;
# within each lexical duplicate component, explicit curator records win, otherwise at most one
# verified root is admitted and the other labels remain visible for review.

provisional = { every dataset root } − keys(confirmed_by)
```

Why per-edge: one verified quote must not admit ten datasets, a review quote must not confirm data
by inheritance, and globally confirmed root identity must not let a new source launder that root
into another camp.

## Step 3 — strength of a root, and adjusted evidence-base count

```
def strength(root):
    if root in provisional:        return 0.0         # root identity unconfirmed
    if support edge unadmitted:    return 0.0         # support assertion unconfirmed
    if root is pool or cycle:      return 0.0         # visible, no grounding
    w = 1.0
    if root in secondary_only:     w *= 0.5           # no primary source instantiates it
    if root in nonhuman_only:      w *= 0.5           # animal/in-vitro; no explicit human primary
    return w

def nEff(position):
    # each DISTINCT admitted root counted ONCE, at its strength. Pools/cycles count at zero.
    return sum( strength(r) for r in distinct_roots_supporting(position) )
```

**Fixed-graph invariant (property-tested):** adding a source with only outgoing edges never lowers
`nEff`; it rises only by introducing a new admitted root/support edge or upgrading one. Correlated/echo sources land on
already-counted roots and move it nowhere. A graph correction can lower it intentionally: merging
aliases or resolving a pending edge that reveals an ungrounded cycle removes false independence.

## Step 4 — surface what matters (key disagreements)

For each factor, over ordinal weights `high=3, med=2, low=1` (n/a and un-weighed excluded):

```
crossCampCrux            = (≥2 camps weigh it)  and  (max−min ≥ 2)      # active disagreement
sharedPivot              = (≥2 camps rate it "high")                    # both call it decisive
oneSidedLoadBearing      = (exactly 1 camp weighs it)  and  (that weight = high)
missingCounterassessment = (≥2 engaged, some camp silent)  and  (some camp rates it high)

isCrux       = crossCampCrux or sharedPivot            # tight headline; does NOT balloon
loadBearing  = isCrux or oneSidedLoadBearing or missingCounterassessment
```

## What the arithmetic cannot do (see `MECHANISM.md §8`)

Deterministic and gaming-resistant by construction, but not self-certifying or a quality score: a **mislabelled tier**
can mint or deny a root, an **omitted citation edge** hides a dependency (we don't crawl real
citation graphs), and a **wrong curator root/edge admission** can add bad coverage. The 0.5 discounts
are declared heuristics rather than calibrated evidence weights. These are semantic
labelling-integrity problems; the defences are per-edge quote verification, the multi-model
ensemble, human review, and — honestly — publishing this list rather than hiding it.

The deployed store adds a separate server revision for optimistic concurrency. It increments on
every write independently of `meta.version`, so two updates with the same semantic version cannot
silently overwrite one another; persistence and its audit entry are one transaction.
