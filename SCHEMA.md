# Knowledge-base schema (v2) and the design problems it answers

The KB is a single JSON document — the **compounding artifact**. Everything else
(ingestion, the viewer, the metrics) produces or consumes it; nothing else owns state.
A new case is a new KB with the same shape, so the tooling is domain-general: only the
data changes, never the code.

The machine-readable contract is [`schema/kb-v2.schema.json`](schema/kb-v2.schema.json). Runtime
loaders use `engine.migrate.migrate_kb` for additive v1→v2 migration and
`engine.migrate.validation_errors` for unique-ID and cross-reference integrity checks. Migration
never invents trust fields such as quote verification or dataset confirmation.

Validate with `python cli.py validate cases/example.kb.json`. Migrate non-destructively with
`python cli.py migrate old.kb.json --out migrated.kb.json` (or use `--apply` explicitly).

## Shape

```jsonc
{
  "meta":      { "id", "question", "version", "updated", "note", "schemaVersion": 2 },
  "positions": [ { "id", "label", "hue" } ],                 // the camps
  "datasets":  [ { "id", "label", "aliases": [..], "confirmation"? } ], // underlying evidence bases;
                                //   confirmation = {status: confirmed|provisional|disputed,
                                //   method: curator|verified-edge, by?, source?, ts?, note?} -- an
                                //   AUDITABLE record of HOW the root was admitted (replaces the bare
                                //   legacy "confirmed": true, still read for old KBs). A root also
                                //   confirms dynamically when a fetched source's PER-EDGE restsOn
                                //   quote verified exact/fuzzy for THAT dataset. An UNCONFIRMED root
                                //   (only unverified/paste-back input) is visible but contributes
                                //   ZERO headline nEff until confirmed -- see engine/roots (admission)
  "vocab":     { "evidence":   [ { "label", "aliases": [..],
                                   "tier"?, "methodClass"? } ],    // per-case controlled
                 "population": [ { "label", "aliases": [..] } ],   //   tag vocabularies
                 "funding":    [ { "label", "aliases": [..] } ] }, // closed funder categories
  "factors":   [ { "id", "label", "weights": {posId: high|med|low|n/a},   // cell = MODE of the
                   "rationale", "provenance": [{source, pos, quote, verifiedQuote?}] } ],
  "sources":   [ { "id", "title", "year", "url",
                   "authors": [ "name", ... ],               // citation metadata (Zotero import/export)
                   "venue", "citations", "retracted",        // evidence-quality signals (from the fetch)
                   "position": posId,
                   "evidence",                                // controlled (see vocab.evidence)
                   "funding",   // Government/public | Nonprofit/charity | Academic/institutional
                                //   | Industry | Advocacy | Undisclosed  (default Undisclosed)
                   "population", "confidence",
                   "methodClass"?,                         // optional correlated-error class override
                   "restsOn": [datasetId | "src:sourceId"          // evidentiary roots: datasets
                                //   AND/OR other sources (derivation edges) -> independence +
                                //   circular-corroboration detection (see MECHANISM.md).
                     | {ref: datasetId, provenance: {quote, verifiedQuote}} ],  // OR an EDGE OBJECT
                                //   carrying THIS edge's own dependency quote, so a verified quote
                                //   confirms only the one dataset it annotates -- never a sibling
                                //   edge, never an inherited root (engine/roots._edges)
                   "textDepth",                    // full | abstract | partial | unknown -- how
                                //   much of the source the labeller actually saw (engine/verify.py)
                   "provenance": { field: {quote, extractionConfidence, verifiedQuote?} },
                                //   verifiedQuote: exact | fuzzy | missing -- read together with
                                //   textDepth, never alone (see problem 3 below)
                   "modelAgreement"?: { models, positionAgreement, flagged,   // multi-model ensemble
                                        disagreedFields, positionVote, proposals },  //   report (ingest/ensemble.py)
                   "addedIn": version } ],                    // powers the diff
  "pendingReview": [ { "id", "title", "url", "year", "abstract",  // ensemble-disagreement queue:
                       "proposals": [{position, votes, quote, confidence}],  //   sources NOT yet
                       "delta", "ts" } ],                     //   merged, awaiting a human decision
                                //   (engine/review.py) -- counted in NO metric until resolved
  "refused":   [ { "title", "url", "year", "reason", "ts" } ],  // off-topic sources refused at
                                //   merge -- RECORDED (not silently dropped) so a wrongly-refused
                                //   source is visible + reversible; counted in NO metric
  "log":       [ { "version", "action", "source", "ts", ... } ]  // audit trail
}
```

Three entity tables (`positions`, `datasets`, `factors`) carry **stable IDs**; sources
and factor-weights reference those IDs. That indirection is what makes the KB mergeable.

## The five hard problems, and where each is handled

1. **Entity resolution on merge.** When a new source cites "the Nurses' Health Study",
   is that `ds_nhs` or a new dataset? Handled in `engine/merge.py`: the ingestion LLM
   *proposes* (`existing_id` or `"NEW:<label>"`); the code *disposes* by normalized-string
   + alias matching. Deterministic and auditable — never dependent on LLM nondeterminism.
   String matching can't catch *paraphrase* duplicates, though (three "Women (mixed …)" terms),
   so `engine/curate.py` adds explicit, deterministic **merge / rename / tidy** ops (CLI `merge`,
   `rename`, `tidy`, `dups`; the UI Curate panel) plus a token-overlap `suggest_duplicates` to
   flag likely pairs. Each merge learns the folded label as an alias, so future ingests resolve
   correctly. New labels are also run through `prettify_label` so id-style slugs
   (`Finnish_cohort_Knekt_1996_4697_women`) become readable names on creation.

2. **Determinism & cost.** All assessment (`engine/assess.py`) is pure functions of the KB.
   Ingestion is O(new sources); recompute is O(whole KB) but just counting. Adding the
   1000th source never re-reasons over the first 999. That is the scalability story.

3. **Provenance per edge.** Every extracted field carries a `quote` + `extractionConfidence`
   back to the source. Without it the KB can't be audited and fails "withstands motivated
   reading." (Seed data leaves these empty and says so; real ingestion fills them.)

   A quote is only as trustworthy as what the labeller actually saw. Ingestion does not always
   get the full paper: `ingest/extract.py` tries open full text (OA PDF, Europe PMC fullTextXML,
   a local file) first, but for many DOI/PubMed/arXiv links the only thing available is an
   abstract, and a plain page scrape is sometimes the real article body and sometimes a
   paywall's abstract-only landing page. Every fetched doc is honestly tagged with a `kind`
   (`full` / `abstract` / `partial`), copied onto the source as `textDepth`.

   `engine/verify.py::match_quote(quote, text)` then checks each provenance quote against that
   **same fetched text** — not against "the true paper," which the tool may not have — and
   records `exact` / `fuzzy` / `missing` as `verifiedQuote`. This is wired into `_carry_meta`
   in `ingest/pipeline.py`, the one place a freshly fetched doc and its LLM-produced delta are
   both in scope in the same process (the automated `--ai` / API paths). Deltas built from a
   pasted-back chatbot response never have the original doc in scope, so they get `textDepth:
   "unknown"` and no `verifiedQuote` rather than a guessed value.

   The crucial reading rule, enforced in `engine/assess.py::quote_audit`: **never read
   `verifiedQuote` without `textDepth`.** A `missing` quote on a `full`-text source is a real
   red flag — the labeller asserted something the fetched document doesn't support — and is
   what `quote_audit` counts as a warning. The identical `missing` verdict on an `abstract` or
   `unknown` source is expected background noise (the quote may be true, drawn from body text
   the tool never had) and is reported only as coverage, never as a warning.

4. **Open schema (interoperability vs nuance).** A small fixed *core* the metrics operate on
   (source, position, dataset, factor, edge) plus *open vocabularies* as tags (`evidence`,
   `funding`, `population`). New domains add vocabulary, not new code — this is what lets one
   renderer/engine serve COVID, black holes, and eggs alike. The catch: the **blindspot**
   metric compares the *set* of evidence/population values across positions, so fully free-text
   tags make every camp "miss" everything (one source = one unique string). The fix is a
   **per-case controlled vocabulary** (`kb.vocab`), resolved by the *same* "propose, then
   deterministically resolve" discipline as datasets: `merge._resolve_vocab` snaps an incoming
   tag onto the case's canonical term (normalized + alias match) or adds a new one. A small
   global base for `evidence` is seeded into every case (`engine/schema.py:BASE_EVIDENCE`);
   `population` starts empty and grows per topic. The vocabulary lives in the artifact, not in
   code — so it is per-domain by construction while staying small enough for blindspots to mean
   something. The ingestion prompt shows the model the current vocabulary so it reuses terms.
   Evidence vocabulary terms may optionally carry `tier` (primary vs secondary for the
   independence engine) and `methodClass` (the correlated-error family used only by the
   method-monoculture audit; see `MECHANISM.md` §12). A source-level `methodClass` can override the
   vocabulary for curated cases, but it does not change `restsOn` or the primary independence
   metric.
   `funding` is a **closed** vocabulary (`BASE_FUNDING`: Government/public, Nonprofit/charity,
   Academic/institutional, Industry, Advocacy, Undisclosed) — `merge._resolve_funding` snaps to
   it and **defaults to "Undisclosed", never "independent"**, so a missing funding statement
   surfaces the gap instead of fabricating independence.

   *Two blindspot/crux refinements keep this readable at scale (`engine/assess.py`):* a type
   counts as "present in the case" only if ≥2 sources use it (`blindspots(min_support=2)`), so a
   single source's hyper-specific population isn't everyone's blindspot; and each factor reports
   `engaged` (how many positions weighed it), so the divergence view separates **cruxes** (spread
   ≥2) from **shared** factors and **one-sided** ones (only one camp engages).

5. **Adversarial robustness = the thesis, enforced at ingestion + assessment.** Defences span
   `engine/merge.py` and the independence engine `engine/roots.py` (full spec: `MECHANISM.md`):
   (a) **alias-splitting** — incoming dataset names match existing labels *and* learned aliases, so
   one cohort can't be smuggled in under many names; (b) **duplicate sources** — same url, or same
   **title+year even under a different url**, are refused; (c) **off-topic** sources are judged at
   labelling time and refused at merge; (d) the independence metric counts **independent evidentiary
   roots**, not sources — re-used cohorts, review/meta-analysis **echo**, and **circular citation**
   (A↔B) all collapse to one root (the cycle is flagged), and animal/in-vitro or review-only roots
   count at half. Provisional/unverified roots remain visible but count **zero** until confirmed.
   Each confirmed distinct root then counts **once**, no matter how many sources rest on it —
   so **flooding a position with correlated, derivative, or circular evidence cannot move its
   independence at all** (only a genuinely new root, or primary/human grounding upgrading a halved
   one, raises it), and junk "support" aimed at a rival can't tank theirs either — the pile-up
   surfaces only as concentration, honestly labelled. Verified in `tests/test_independence.py`,
   including a randomized never-decreases monotonicity test.

   `restsOn` therefore holds **two kinds of edge**: a dataset id, or `"src:<sourceId>"` — a
   derivation edge to another source, which is what lets the audit follow citation chains to their
   root and detect circular corroboration. The labeller writes `SRC:<id>` / `NEW-SRC:<title>`; merge
   resolves it. Evidence **tier** (primary makes evidence; secondary — reviews, meta-analyses,
   commentary — only talks about it) drives the echo collapse; `population` carries the non-human
   marker (`Mice` / `Rats` / `In vitro`) that down-weights animal evidence on a clinical question.

## Label trust: the ensemble report and the review queue

Labelling is the one load-bearing AI step, so the schema records *how much the models agreed*, not
just the winning label. When labelling runs as a **multi-model ensemble** (`ingest/ensemble.py`),
the fused delta carries a `modelAgreement` report on the source: how many models ran, the position
agreement fraction, which fields split (`disagreedFields`), the per-label `positionVote` tally, and
each camp's best-confidence `proposals` (label + votes + quote). A `restsOn` edge is kept only on a
**strict majority** (more than half the models proposed it), so at 2 models one model's spurious
dataset/citation edge never survives the vote; edge-vote disagreement is recorded in `disagreedFields`.

A `modelAgreement.flagged` source *did* merge (a majority formed, or the highest-confidence model
broke a mild tie) but is surfaced for a second look. A **genuine** split — no majority on the
position — does **not** merge at all: `engine/review.py` parks the whole delta in the top-level
`pendingReview` queue for a human to resolve (pick one of the `proposals`' positions, pick any
existing position, or drop the paper). The queue lives in the KB file, so it persists, travels with
the case on push/pull, and resumes; **pending items are not sources and count toward no metric**
until resolved. Both surfaces (local console review panel, portal admin *manage* view) read and
resolve the same queue.

## Why cold-start and update are the same path

A cold start is the update loop run N times over discovered sources; an update is the same
loop run once. `python cli.py ingest` (or `add`) is the only mutation. This is what makes the
KB "living, not a snapshot" (FLF) by construction — there is no separate batch build to drift
out of sync with the incremental path.
