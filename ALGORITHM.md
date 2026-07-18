# Ground Knowledge — the algorithm in full

This is the readable version of `engine/roots.py` + `engine/assess.py`: pure, deterministic, standard-library Python over one JSON file per case (`cases/*.kb.json`). No LLM, no network, no randomness — a model labels sources upstream, but nothing here depends on it. [`SUBMISSION.md`](SUBMISSION.md) gives the four-step summary; this document adds the data model and the edge-case rules.

## What a source record carries

```
position   : which camp the source supports
evidence   : its tier, mapped to primary | secondary   (a review or meta-analysis is secondary)
funding    : Government | Nonprofit | Academic | Industry | Advocacy | Undisclosed (default)
population : human | animal | in-vitro | …             textDepth: full | abstract | partial | unknown
restsOn    : the source's dependency edges. Each one is either
               "ds_x"       — this source rests on dataset ds_x
               "src:<id>"   — this source cites/derives from another source
               or the same, as an object carrying its own proof:
               {ref: "ds_x",
                provenance: {quote, verifiedQuote: "exact" | "fuzzy" | "missing"},
                admission?: {status: "confirmed", method: "curator" | "legacy-migration",
                             by, ts, note?}}
```

Datasets are records of their own. `dataset.confirmation` says who established that the dataset is real (`method: "curator"` for a logged human decision, `"verified-edge"` when an exact verified quote named it — in that case the confirming source is recorded too). `dataset.kind` distinguishes empirical roots (dataset, experiment, observation) from theoretical ones (argument, model, document); theoretical roots are first-class but exempt from the non-human discount below, which only makes sense for empirical evidence.

## Step 1 — decide what to trust

A named dataset can be real while a new source's claim to rely on it is false. So admission is two independent decisions, and a link only carries weight when both hold:

- **Root identity.** The dataset is confirmed by a curator record, or by a quote that was verified verbatim against the fetched text of a source *and* actually names the dataset (its label or a known alias). Only a current, hash-bound `exact` verification counts — a `fuzzy` match is displayed but earns nothing.
- **Support edge.** This particular source's reliance on the dataset (or citation of another source) needs its own verified quote or its own curator admission.

The trust boundary around these fields is strict. A public paste-back contribution cannot supply either: every verification and admission field it carries is deleted, and the contribution waits for review. On the fetched-text path the tool computes quote verification itself, but a model-written `admission` key is deleted too — only `curate.confirm_edge` (a logged, attributed human action) writes curator admissions. Before any merge, a validator bounds every array and string and rejects malformed types; in a batch, each labelled delta is bound to its fetched document by an opaque id, so array order is never treated as identity.

Three rules close the remaining loopholes:

- A quote from ordinary methods prose that matches a *generic* label ("cohort", "survey data") cannot confirm a root — generic names identify nothing.
- When two proposed dataset names are near-duplicates of each other, an explicit curator record wins; otherwise at most one of them is admitted by verified quote, and the collision is flagged for review instead of silently counting twice.
- A source-level quote (older data, before per-edge proofs) is accepted only when the source has exactly one direct dataset edge, so one quote can never vouch for several datasets at once.

Everything not admitted stays in the file and in the report — visible, marked, and worth zero. `provisional = every dataset − the confirmed ones`.

## Step 2 — trace every source down to its roots

```
def resolve(kb):
    # 1. Merge citation loops first. A→B→A becomes one unit (Tarjan's strongly-
    #    connected components), so circular corroboration cannot pose as depth.
    components = tarjan(admitted_citation_graph(kb))

    # 2. Walk the units bottom-up (iterative post-order — no recursion limit).
    for component in bottom_up(components):
        roots  = every admitted dataset edge of any source in the component
        roots += the roots of every component this one cites

        if roots is empty:                      # nothing grounded underneath
            if the component is a loop:  roots = { one "circular" marker }
            else:                        roots = { one "unsupported" marker,
                                                   kept per position and tier }
        memo[component] = roots

    return { source: memo[its component] for every source }
```

Consequences, spelled out: ten reviews of the same study all resolve to that study's dataset (echo becomes one look); eight papers on one cohort become one root; a citation ring with nothing primary underneath becomes a single flagged marker worth zero. Links that were never admitted are drawn in the report but not traversed here. And naming a dataset is only ever a *proposal* — an unconfirmed root resolves fine but scores zero until Step 1 is satisfied, so fabricating names moves nothing.

## Step 3 — score each position

```
def strength(root):                        # the credit one root can earn
    if root is provisional:        return 0.0    # identity never confirmed
    if its support edge unadmitted: return 0.0   # reliance never established
    if root is a marker (pool/loop): return 0.0  # visible, but not evidence
    w = 1.0
    if only secondary sources rest on it:  w *= 0.5   # reviews only — no primary study
    if only non-human evidence backs it:   w *= 0.5   # animal / in-vitro only
    return w                                          # theoretical roots skip the last check

def nEff(position):                        # the adjusted evidence-base count
    return sum(strength(r) for r in the DISTINCT roots under its sources)
```

Each root is counted once, however many sources rest on it — that single rule makes volume and echo inert. A property-based test over randomized graphs pins the invariant: **adding a source that only points outward can never lower `nEff`**; the count rises only when a new root (or a better-grounded edge) is admitted. Only an explicit graph correction — merging two aliases that turn out to be one cohort, or resolving a pending edge that exposes an ungrounded loop — can lower it, because that removes false independence, not evidence.

## Step 4 — surface what divides the camps

Each case lists factors (e.g. "prior on lab accidents"), and each camp's weight on each factor, sourced from quotes. Over ordinal weights `high = 3, med = 2, low = 1` (unweighed camps excluded):

```
crossCampCrux            = ≥2 camps weigh it  AND  max − min ≥ 2     # they actively disagree
sharedPivot              = ≥2 camps rate it high                     # agreed decisive, unresolved
oneSidedLoadBearing      = exactly 1 camp weighs it, at high         # one camp's case leans here
missingCounterassessment = ≥2 camps engaged, one silent, some high   # a decisive point unanswered

headline cruxes = crossCampCrux or sharedPivot        # kept tight on purpose
```

The one-sided and unanswered factors are surfaced separately so the headline never balloons to "every factor matters".

## What the arithmetic cannot do

It is deterministic and hard to game, but not self-certifying. A mislabelled evidence tier can mint or deny a root; a dependency a source simply never mentions stays invisible (we do not crawl citation databases); a wrong curator decision moves numbers wrongly, auditable but wrong. The 0.5 discounts are declared conventions, not calibrated weights. The defences are per-edge quote verification, the multi-model labelling ensemble, human review, and stating this list plainly (`MECHANISM.md` §8).

One deployment note: the shared portal adds a server-side revision counter, independent of the file's own version, so two concurrent edits cannot silently overwrite each other — the stale writer gets a conflict, and each write commits atomically with its audit entry.
