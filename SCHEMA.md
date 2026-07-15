# Knowledge-base schema (v2) and the design problems it answers

The KB is a single JSON document — the **compounding artifact**. Everything else
(ingestion, the viewer, the metrics) produces or consumes it; nothing else owns state.
A new case is a new KB with the same shape, so the tooling is domain-general: only the
data changes, never the code.

The machine-readable contract is [`schema/kb-v2.schema.json`](schema/kb-v2.schema.json). Runtime
loaders use `engine.migrate.migrate_kb` for additive v1→v2 migration and
`engine.migrate.validation_errors` for unique-ID and cross-reference integrity checks. Migration
never invents trust fields such as quote verification or dataset confirmation.

There are deliberately two versions. `meta.version` is the semantic history inside the portable KB
and advances when its evidence state changes. The hosted portal's top-level API `version` is a
separate server revision that advances on **every stored write**, including review-queue changes and
whole-KB replacement. Clients must send that server revision back when updating; a stale value gets
a conflict instead of silently overwriting another contributor.

Validate with `python cli.py validate cases/example.kb.json`. Migrate non-destructively with
`python cli.py migrate old.kb.json --out migrated.kb.json` (or use `--apply` explicitly).

## Shape

```jsonc
{
  "meta":      { "id", "question", "version", "updated", "note", "schemaVersion": 2 },
  "positions": [ { "id", "label", "hue" } ],                 // the camps
  "datasets":  [ { "id", "label", "aliases": [..], "kind"?, "proposition"?, "confirmation"? } ],
                                //   underlying EVIDENCE BASES (the key stays "datasets" for back-compat).
                                //   kind = dataset | experiment | observation | argument | model |
                                //   document (absent = dataset). argument/model/document are THEORETICAL
                                //   roots — first-class coverage bases, exempt from the empirical
                                //   (non-human population) discount; proposition states the claim.
                                //   kind is NEVER inferred: the labeller sets it via a restsOn edge's
                                //   "datasetKind" (ingest.md), or a curator via curate.set_kind /
                                //   the manage page. source_inventory flags document-labelled datasets.
                                //   confirmation = {status: confirmed|provisional|disputed,
                                //   method: curator|verified-edge, by, source?, ts, note?} -- an
                                //   AUDITABLE record of HOW the root was admitted (replaces the bare
                                //   legacy "confirmed": true, still read for old KBs). A root also
                                //   confirms dynamically when a fetched source's PER-EDGE restsOn
                                //   quote has a current hashed exact verification AND names THAT dataset's label/alias.
                                //   An UNCONFIRMED root
                                //   (only unverified/paste-back input) is visible but contributes
                                //   ZERO headline nEff until confirmed -- see engine/roots (admission)
  "vocab":     { "evidence":   [ { "label", "aliases": [..],
                                   "tier"?, "methodClass"? } ],    // per-case controlled
                 "population": [ { "label", "aliases": [..] } ],   //   tag vocabularies
                 "funding":    [ { "label", "aliases": [..] } ] }, // closed funder categories
  "factors":   [ { "id", "label", "weights": {posId: high|med|low|n/a},   // cell = MODE of the
                                //   exact-verified claims only; an unverified proposal cannot vote
                   "rationale", "provenance": [{source, pos, quote, verifiedQuote?}] } ],
  "contextSources": [ { ...source citation/provenance fields..., "role": "factor-only" } ],
                                //   optional methodological/context evidence referenced by factors;
                                //   deliberately excluded from position, distribution, and root counts
  "sources":   [ { "id", "title", "year", "url",
                   "authors": [ "name", ... ],               // citation metadata (Zotero import/export)
                   "venue", "citations", "retracted",        // evidence-quality signals (from the fetch)
                   "position": posId,
                   "evidence",                                // controlled (see vocab.evidence)
                   "funding",   // Government/public | Nonprofit/charity | Academic/institutional
                   "fundingDetails": ["named grant or explicit no-funding statement", ...], // optional
                                //   | Industry | Advocacy | Undisclosed  (default Undisclosed)
                   "population", "confidence",
                   "methodClass"?,                         // optional correlated-error class override
                   "restsOn": [datasetId | "src:sourceId"          // evidentiary roots: datasets
                                //   AND/OR other sources (derivation edges) -> independence +
                                //   circular-corroboration detection (see MECHANISM.md).
                     | {ref: datasetId | "src:sourceId",
                        provenance?: {quote, verifiedQuote, quoteVerification?},
                        admission?: {status: confirmed,
                                     method: curator | legacy-migration,
                                     by, ts, note?}} ],              // OR an EDGE OBJECT
                                //   carrying THIS edge's own dependency quote, so a verified quote
                                //   confirms only the one dataset it annotates. admission records
                                //   that THIS source→root/citation support link was reviewed.
                   "textDepth",                    // full | abstract | partial | unknown -- how
                                //   much of the source the labeller actually saw (engine/verify.py)
                   "provenance": { field: {quote, extractionConfidence, verifiedQuote?,
                                            quoteVerification?} },
                                // exact is trusted only with a verbatim-sentence-v2 record and
                                // checked-text SHA-256. fuzzy means altered/paraphrased, NOT verified.
                   "modelAgreement"?: { models, positionAgreement, flagged,   // multi-model ensemble
                                        disagreedFields, positionVote, proposals },  //   report (ingest/ensemble.py)
                   "addedIn": version } ],                    // powers the diff
  "pendingReview": [ { "id", "title", "url", "year", "abstract",  // public/untrusted + ensemble review queue:
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
   `rename`, `tidy`, `dups`; the UI Curate panel) plus lexical/acronym suggestions and optional
   embedding suggestions (`dups --embed`) to flag likely pairs. Suggestions never auto-merge.
   Confirmation blocks a likely duplicate unless a curator records an explicit override. Each merge
   learns the folded label as an alias, so future ingests resolve correctly. New labels also run
   through `prettify_label` so id-style slugs
   (`Finnish_cohort_Knekt_1996_4697_women`) become readable names on creation.

2. **Determinism & cost.** All assessment (`engine/assess.py`) is pure functions of the KB.
   Ingestion is O(new sources); recompute is O(whole KB) but just counting. Prompt entity/source
   context is bounded and uses deterministic lexical retrieval (configurable `EPISTEMIC_CONTEXT_*`
   caps), so the 1000th source does not make every model prompt grow without limit. No large-corpus
   performance study is claimed.

3. **Provenance on load-bearing claims.** Current ingestion requests a `quote` +
   `extractionConfidence` for the position, every dataset-dependency edge, and factor weights.
   Source-citation edges require explicit curator admission before propagating roots. Categorical
   metadata is not claimed to be quote-backed. Legacy case relationships carry explicit
   `legacy-migration` records that mean "adopted from the curated artifact," not quote verification.

   A quote is only as trustworthy as what the labeller actually saw. Ingestion does not always
   get the full paper: `ingest/extract.py` tries open full text (OA PDF, Europe PMC fullTextXML,
   a local file) first, but for many DOI/PubMed/arXiv links the only thing available is an
   abstract, and a plain page scrape is sometimes the real article body and sometimes a
   paywall's abstract-only landing page. Every fetched doc is honestly tagged with a `kind`
   (`full` / `abstract` / `partial`), copied onto the source as `textDepth`.

   `engine/verify.py::ground_quote(quote, text)` then checks each provenance quote against that
   **same fetched text** — not against "the true paper," which the tool may not have. `exact` has
   a deliberately narrow meaning: one verbatim non-title sentence in one source-text segment. The
   verifier canonicalizes a verbatim fragment to its complete sentence and records a
   `quoteVerification` object with method `verbatim-sentence-v2`, text depth, source URL, normalized
   character offsets, and separate SHA-256 hashes of the checked text and displayed sentence. The
   quote hash means editing wording after verification immediately invalidates the checkmark.
   `fuzzy` means altered/paraphrased/cross-boundary and is explicitly **not** a
   verified quotation; `missing` means not found in the material checked. This is wired into `_carry_meta`
   in `ingest/pipeline.py`, the one place a freshly fetched doc and its LLM-produced delta are
   both in scope in the same process (the automated `--ai` / API paths). Deltas built from a
   pasted-back chatbot response never have the original doc in scope, so they get `textDepth:
   "unknown"` and no `verifiedQuote` rather than a guessed value.

   Factor claims follow the same trust rule. `engine/merge._recompute_factor_cell` admits a
   source's high/medium/low vote only when `is_verified_exact` binds its displayed sentence to the
   fetched-text hash. Unverified wording remains in provenance for review but cannot create a crux
   cell. A `contextSources` record can support a methodological factor (for example, a funding-bias
   review) without being misrepresented as a position source or inflating root-coverage metrics.

   Dependency provenance is stricter than ordinary field provenance: every dataset edge carries its
   own quote, and root admission requires both a text match and that the quote name the edge's
   canonical label or learned alias. Copying one real sentence onto unrelated sibling edges therefore
   does not confirm them. A legacy source-level dependency quote is honored only when there is exactly
   one direct dataset; with multiple datasets it is ambiguous and confirms none.

   The crucial reading rule, enforced in `engine/assess.py::quote_audit` and
   `engine/verify.py::is_verified_exact`: **a checkmark requires the current method plus the checked
   text hash.** Old/manual `verifiedQuote: exact` flags do not pass. Every fuzzy, missing, or unchecked
   excerpt is surfaced and rendered as a stored summary without quotation marks. Text depth explains
   what was checked; it never turns an unchecked excerpt into a verified quote. Only current audited
   exact dependency quotes may automatically admit an evidence root. Textual verification is not
   semantic verification: the checkmark means only that the displayed sentence occurs verbatim in
   the hashed fetched text. `extractionConfidence` is the separate, fallible judgement that the
   sentence supports its assigned field. A positioned source with no `provenance.position.quote` is
   therefore counted as missing position grounding and surfaced by `quote_audit`, even if it has
   exact dependency or factor excerpts.

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
   root-coverage engine) and `methodClass` (the correlated-error family used only by the
   method-monoculture audit; see `MECHANISM.md` §12). A source-level `methodClass` can override the
   vocabulary for curated cases, but it does not change `restsOn` or the primary root-coverage
   metric.
   `funding` is a **closed** vocabulary (`BASE_FUNDING`: Government/public, Nonprofit/charity,
   Academic/institutional, Industry, Advocacy, Undisclosed) — `merge._resolve_funding` snaps to
   it and **defaults to "Undisclosed", never "independent"**, so a missing funding statement
   surfaces the gap instead of fabricating independence.

   *Two blindspot/crux refinements keep this readable at scale (`engine/assess.py`):* a type
   counts as "present in the case" only if ≥2 sources use it (`blindspots(min_support=2)`), so a
   single source's hyper-specific population isn't everyone's blindspot; and each factor reports
   `engaged` (how many positions weighed it), so the divergence view separates cross-camp cruxes,
   shared high pivots, one-sided high assumptions, unanswered high factors, and mild contests.

5. **Adversarial robustness = the thesis, enforced at ingestion + assessment.** Defences span
   `engine/merge.py` and the root-coverage engine `engine/roots.py` (full spec: `MECHANISM.md`):
   (a) **alias-splitting** — incoming names match exact/learned aliases; automatically verified
   lexical lookalikes admit at most one root; lexical/acronym and optional embedding checks suggest
   novel paraphrases, and confirmation gates likely duplicates; (b) **duplicate sources** — same url, or same
   **title+year even under a different url**, are refused; (c) **off-topic** sources are judged at
   labelling time and refused at merge; (d) confirmed-root coverage counts **admitted, deduplicated
   evidentiary roots**, not sources — re-used cohorts and review/meta-analysis **echo** collapse, while a pure
   **circular citation** loop (A↔B) is visible and flagged but counts **zero**. Animal/in-vitro or
   review-only roots count at half. Provisional/unverified roots remain visible but count zero.
   Each confirmed distinct root then counts **once**, no matter how many sources rest on it —
   so flooding with correlated/derivative evidence cannot move coverage. With graph identity
   fixed, only a genuinely new root or grounding upgrade raises it; graph corrections can lower it
   by merging aliases or revealing a cycle. Verified in `tests/test_independence.py`, including a
   randomized fixed-graph property test and an explicit pending-edge cycle correction.

   `restsOn` therefore holds a bare evidence-base/source ref or an edge object `{ref, provenance}`.
   A `"src:<sourceId>"` derivation edge lets the audit follow citation chains to their root and
   detect circular corroboration; dataset edge objects bind dependency quotes per root. The labeller
   writes `SRC:<id>` / `NEW-SRC:<title>`; merge
   resolves it. Evidence **tier** (primary makes evidence; secondary — reviews, meta-analyses,
   commentary — only talks about it) drives the echo collapse; `population` carries the non-human
   marker (`Mice` / `Rats` / `In vitro`) that down-weights animal evidence on a clinical question.

## Label trust: the ensemble report and the review queue

### Ingestion delta boundary

Every model or public contribution delta is structurally validated before merge. Batched labelling
uses an opaque `sourceId` attached to each fetched document: every model must return each ID exactly
once, and the pipeline rejects missing, repeated, or unknown IDs before pairing output with fetched
text. Fetch-derived URL, title, author, venue, citation, and retraction metadata then overwrite model
claims. Models may propose roots and quotes, but they cannot supply an `admission` object; only the
authenticated curator path can create one. These checks prevent reordered batch output or forged
trust fields from being attached to the wrong source.

Labelling is the one load-bearing AI step, so the schema records *how much the models agreed*, not
just the winning label. When labelling runs as a **multi-model ensemble** (`ingest/ensemble.py`),
the fused delta carries a `modelAgreement` report on the source: how many models ran, the position
agreement fraction, which fields split (`disagreedFields`), the per-label `positionVote` tally, and
each camp's best-confidence `proposals` (label + votes + quote). A `restsOn` edge is kept only on a
**strict majority** (more than half the models proposed it), so at 2 models one model's spurious
dataset/citation edge never survives the vote; edge-vote disagreement is recorded in `disagreedFields`.

A `modelAgreement.flagged` delta does **not** merge on the normal ensemble path. A genuine position
split or primary/secondary tier split is routed to review: `engine/review.py` parks the whole delta in the top-level
`pendingReview` queue for a human to resolve (pick one of the `proposals`' positions, pick any
existing position, or drop the paper). The queue lives in the KB file, so it persists, travels with
the case on push/pull, and resumes; **pending items are not sources and count toward no metric**
until resolved. Both surfaces (local console review panel, portal admin *manage* view) read and
resolve the same queue. Legacy or paste-back sources that were already merged with a flag are also
shown on that review surface and can be re-labelled, accepted, or dropped.

## Why cold-start and update are the same path

A cold start is the update loop run N times over discovered sources; an update is the same
loop run once. `python cli.py ingest` (or `add`) is the only mutation. This is what makes the
KB "living, not a snapshot" (FLF) by construction — there is no separate batch build to drift
out of sync with the incremental path.
