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
               {ref:"ds_x", provenance:{quote, verifiedQuote:"exact|fuzzy|missing"}}
                                             a dataset edge carrying its OWN dependency quote
dataset.confirmation : {status:"confirmed", method:"curator"|"verified-edge", by, ts,
                        source?}    # source is optional for curator, required for verified-edge
dataset.kind         : dataset | experiment | observation | argument | model | document
                       (absent = dataset). argument/model/document are THEORETICAL roots — first-
                       class independent bases, exempt from the empirical non-human discount. So a
                       "safe" position resting on 4 distinct safety ARGUMENTS counts 4 bases, not 1.
```

## Step 1 — resolve every source to its evidentiary ROOTS

```
def resolve(kb):
    # collapse circular corroboration: SCCs of the source→source citation graph (Tarjan).
    # a cycle with no grounding becomes one VISIBLE "cycle" marker, flagged and worth zero.
    components = tarjan(citation_graph(kb))            # each SCC = one node in a DAG

    for component in reverse_topological(components):  # iterative post-order (no recursion limit)
        roots = { "ds:"+d for src in component for d in dataset_edges(src) }
        roots |= union(roots_of(dep) for dep in components_this_one_cites)
        if roots is empty:
            if len(component) > 1:  roots = { "cycle:"+min(component) }      # circular, ungrounded
            else:
                s = the one source
                # NAMING proposes a distinct root; admission is Step 2. Claiming a tier does neither.
                roots = { "primpool:"+s.position } if tier(s)=="primary"     # one pooled voice / camp
                        else { "secpool:"+s.position }                        # one review voice / camp
        memo[component] = roots
    source_roots = { s: memo[component_of(s)] for s in sources }
```

Consequences: ten reviews of the same study all resolve to that study's dataset root (echo → one
look); eight papers off one cohort → one root; `A→B→A` with nothing primary → one visible, flagged,
**zero-strength** cycle marker.

## Step 2 — admit roots PER EDGE (confirmation)

A named dataset is provisional (worth **zero** in the headline) until confirmed one of two auditable
ways. Confirmation is strictly per **direct** edge — never a sibling, never an inherited root.

```
confirmed_by = {}                                     # root → {method, source}
for d in datasets:
    if curator_confirmed(d):                          # {status:"confirmed", ...}  OR legacy bool
        confirmed_by["ds:"+d.id] = {method:"curator", ...}

for s in sources where textDepth in {full, abstract, partial}:
    direct = { "ds:"+d for d in dataset_edges(s) }    # DIRECT dataset edges only
    for edge in s.restsOn:
        if edge is a dataset edge AND edge.provenance.verifiedQuote in {exact, fuzzy}
           AND edge.quote names edge.ref's label/alias:
            confirmed_by.setdefault("ds:"+edge.ref, {method:"verified-edge", source:s.id})
    # legacy: source-level quote is accepted only when this source has EXACTLY ONE direct dataset

# Literal quote presence does not settle root identity. Generic labels cannot auto-confirm;
# within each lexical duplicate component, explicit curator records win, otherwise at most one
# verified root is admitted and the other labels remain visible for review.

provisional = { every dataset root } − keys(confirmed_by)
```

Why per-edge: one verified quote must not admit ten datasets, and a review that merely *cites* a
study must not confirm that study's data by inheritance. On the untrusted paste-back path,
`textDepth` and `verifiedQuote` are stripped, so a contributor cannot self-declare a fabricated
edge as verified — fabricated roots stay visible but quarantined.

## Step 3 — strength of a root, and the headline count

```
def strength(root):
    if root in provisional:        return 0.0         # unconfirmed → quarantined
    if root is an ungrounded cycle: return 0.0         # visible warning, no independent grounding
    w = 1.0
    if root in secondary_only:     w *= 0.5           # no primary source instantiates it
    if root in nonhuman_only:      w *= 0.5           # animal / in-vitro only, for a human question
    return w

def nEff(position):
    # each DISTINCT root counted ONCE, at its strength. primpool/secpool count once at 1.0;
    # an ungrounded cycle counts at 0. Idempotent: writing the same root again cannot change it.
    return sum( strength(r) for r in distinct_roots_supporting(position) )
```

**Fixed-graph invariant (property-tested):** adding a source with only outgoing edges never lowers
`nEff`; it rises only by introducing a new admitted root or upgrading one. Correlated/echo sources land on
already-counted roots and move it nowhere. A graph correction can lower it intentionally: merging
aliases or resolving a pending edge that reveals an ungrounded cycle removes false independence.

## Step 4 — surface what matters (cruxes)

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

Deterministic and gaming-resistant by construction, but not self-certifying: a **mislabelled tier**
can mint or deny a root, an **omitted citation edge** hides a dependency (we don't crawl real
citation graphs), and a **wrong curator confirmation** admits a bad root. These are semantic
labelling-integrity problems; the defences are per-edge quote verification, the multi-model
ensemble, human review, and — honestly — publishing this list rather than hiding it.
