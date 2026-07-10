# The Evidence-Independence Mechanism

*The conceptual core of Ground Knowledge, in plain language. This is the spec we label against
and compute against. Read it adversarially — the point is to find the weak spots before they find
us.*

---

## 0. The one-sentence idea

> A position is only as strong as the number of **genuinely independent pieces of evidence** behind
> it — not the number of documents that assert it. The mechanism counts *independent evidentiary
> roots*, collapsing everything that merely echoes, summarizes, or circularly cites the same
> underlying evidence.

Counting sources rewards whoever publishes (or re-publishes) most. We count *roots*.

---

## 1. The problem we are solving

Three failure modes break naive source-counting, and they look identical on a bar chart:

1. **Echo.** Ten review articles all summarizing the same three primary studies are *one* look,
   not ten. Yet each is a separate "source."
2. **Cohort re-use.** One research group publishes eight papers off a single cohort. Eight
   sources, one independent dataset.
3. **Circular corroboration.** Source A's main evidence is Source B; Source B's main evidence is
   Source A. Two sources, *zero* independent grounding. This is the adversarial case — it is
   designed to look like mutual confirmation.

All three are the same disease: **sources that add no new root.** The mechanism is one cure for
all three.

---

## 2. Ontology — the five things that exist

| Thing | Plain meaning | Example |
|---|---|---|
| **Source** | A document that takes a position. | A paper, a report, a commentary, a guideline. |
| **Position** | A stance on the question. | "Zoonotic origin." |
| **Root** (evidentiary basis) | The underlying thing that actually *generates* information. | A dataset, a cohort, an experiment, a model run, a field observation. |
| **Derivation** | What a source draws its support *from*. Points at roots and/or other sources. | "This review rests on the proximal-origin dataset." |
| **Tier** | Does the source *make* evidence or *talk about* evidence? | **Primary** (makes) vs **Secondary** (talks about). |

The key move: **sources and roots are different kinds of node.** Many sources can share one root.
Independence is a property of *roots*, counted *per position*.

---

## 3. What we record when we label a source

For every source, the labeller (human, a single LLM, or a multi-model **ensemble** whose per-field
majority vote is combined deterministically — `ingest/ensemble.py`) records:

1. **Position** — the single stance it argues. (Already in the schema.)
2. **Evidence type** — from the case's controlled vocabulary. This determines the **tier**:
   - **Primary** tiers *make* evidence: `Observational`, `Experimental (RCT)`, `Mechanistic`.
   - **Secondary** tiers *talk about* evidence: `Meta-analysis` / `Systematic review`,
     `Narrative/Commentary`, `Evidence-synthesis`, `Expert advisory`, `Institutional statement`,
     `Editorial/Perspective`. A meta-analysis is a *synthesis* — it only counts as independent if it
     **tags the trials it pools** (then it resolves through them, tier aside); an untagged one is
     echo and collapses into the position's one secondary voice. (This is the common real failure:
     ten meta-analyses of the same overlapping RCTs are one look, not ten.)
   - Tier is a property attached to each vocabulary term, not guessed per source — so it is
     deterministic and auditable, and a case can override it.
3. **`restsOn`** — the heart of the mechanism. A list of what this source draws support from.
   Each entry is one of:
   - a **root** (a dataset / cohort / experiment), by id or `NEW:<label>`;
   - **another source** in this KB, by id, when the source's case *is* that other source
     (`SRC:<id>` or `NEW-SRC:<title>`) — this is how we capture citation/derivation and catch
     circularity;
   - nothing (the list is empty) — the source is **ungrounded**.
4. **Provenance quote** — the verbatim sentence that justifies the position (already in schema;
   also what the *verification* pass checks).

> **Labelling principle for `restsOn`:** tag what the source *actually leans on*, even for reviews.
> A review of the proximal-origin paper **rests on the proximal-origin dataset** — say so, and it
> will collapse into that root automatically. Only leave `restsOn` empty when the source genuinely
> grounds in nothing checkable (pure opinion). This is what makes the mechanism degrade *gracefully*:
> good tagging makes the tier rule unnecessary; the tier rule is the safety net for bad tagging.

---

## 4. How independence is computed (the algorithm, in plain language)

### 4.1 Build the dependency graph
Nodes are **sources** and **roots**. For each source, draw an edge to every thing in its
`restsOn` (a root, or another source). Self-edges (a source resting on itself) are dropped.

### 4.2 Resolve every source to its **root set**
Walk each source's edges down to the primary evidence it ultimately depends on:

- rests on **dataset(s)** → those datasets are its roots.
- rests on **other source(s)** → its roots are the *union of those sources' root sets*
  (follow the chain recursively).
- rests on **nothing**:
  - **primary** tier, but names **no** evidence base → the position's single **ungrounded-primary
    pool** (`primpool:<pos>`), one shared "unnamed first-hand voice" per position. A primary that
    *names* its own trial/cohort/sample keeps a distinct root; one that names nothing is an
    unverifiable assertion and pools, symmetric with reviews. *(Earlier this minted a per-source
    root "on benefit of the doubt" — the echo-as-primary flooding hole; see §7, §8.1.)*
  - **secondary** tier → it has **no root of its own**. It joins this position's single
    **ungrounded-secondary pool** — one shared pseudo-root per position. (This is the
    "collapse all echo to one voice" decision.)
  - an **unrecognised** evidence label resolves as **secondary** (conservative — a coined/opinion
    label can't mint a primary root; a new primary *design* is opted in via `kb.vocab` tier).

### 4.3 Collapse cycles — *circular corroboration*
While following source→source edges we may hit a **cycle**: A→B→A, or longer. Compute the
**strongly connected components** (SCCs) of the source graph. For each SCC of size > 1 (a group of
sources that mutually depend):

- The whole component **collapses to one root**, because no member adds independence the others
  don't already have.
- If the component **also** reaches a real dataset (someone in the loop is actually grounded),
  it collapses *into that dataset's root* — redundant, not vacuous.
- If the component reaches **no** dataset and **no** primary source — it is **pure circular
  corroboration**. It collapses to one pool root **and raises a `circularCorroboration` flag**
  naming the loop. This is the adversarial pattern, surfaced loudly.

### 4.4 Count effective independent roots per position
For each position, take all its sources, map each to its resolved root(s), and count **each
distinct root exactly once, at its strength**:

```
nEff = Σ strength(root_i)     over the position's DISTINCT resolved roots

strength = 1.0   for a real root (a NAMED dataset / cohort / experiment)
         × 0.5   if the root is known only via secondary sources (§6.5)
         × 0.5   if the root is backed only by animal / in-vitro studies (§6.5b)
         = 1.0   for the pooled secondary voice, the pooled unnamed-primary voice, or a
                 collapsed circular loop (one of each per position, counted once)
```

This is the "effective number of independent looks," as a full-strength-equivalent root count.
One root used by everyone → nEff = 1. Ten roots → nEff = 10, whether each is used once or one of
them is used a hundred times. **How many sources land on each root is deliberately excluded from
this number** — it feeds the separate *concentration* display ("82% of this position's sourcing
leans on one cohort"), which is where a pile-up honestly belongs.

*Why not a share-based concentration index (Herfindahl) over the per-root source tallies?* Because
any formula that reads per-source tallies is movable by adding worthless sources: echoing reviews
onto a position's *minority* root evens out the shares and raises such an index (flooding fakes
independence), and piling junk "support" onto a rival's biggest root skews the shares and tanks
theirs (poisoning by agreement). Counting each root once makes both attacks inert by construction
— the only ways nEff moves are adding a genuinely **new root** or **upgrading** a root's strength
(a primary source landing on a review-only dataset; a human study landing on an animal-only root),
and both of those *should* move it.

### 4.5 The two bars the reader sees
- **By source count** — the naive tally (kept, honestly labelled as naive).
- **By independent evidence** — sized by `nEff` over resolved roots.
- Plus, always, **the derivation shown**: "25 sources → 7 independent bases (15 secondary reviews
  counted as 1 voice; furin-cleavage + proximal-origin share the Andersen dataset)." The number is
  never a black box.

---

## 5. Worked examples

**E1 — Echo.** Position has 1 primary study (dataset D) + 12 narrative reviews, all `restsOn`
empty, all secondary. → roots = {D, secondary-pool}. nEff = 2. The 12 reviews are one voice.

**E2 — Echo, well-tagged.** Same, but each review `restsOn` D (we tagged what they summarize). →
every node resolves to D. nEff = 1. Even cleaner — and no tier rule was needed.

**E3 — Cohort re-use.** 8 papers, all `restsOn` cohort C. → nEff = 1. (Existing behavior.)

**E4 — Pure circular corroboration.** A `restsOn` [SRC:B], B `restsOn` [SRC:A], no datasets. →
SCC {A,B}, no dataset → collapses to 1 pool root, **flagged**. nEff contribution = 1, with a
warning the reader can see.

**E5 — Circular but grounded.** A `restsOn` [SRC:B, dataset D]; B `restsOn` [SRC:A]. → SCC {A,B}
reaches D → collapses into D. nEff via D. Redundant, not flagged vacuous.

**E6 — Chain.** A `restsOn` [SRC:B]; B `restsOn` [SRC:C]; C `restsOn` [dataset D]. → all resolve
to D. A review-of-a-review-of-a-study counts as the study.

**E7 — Contested dataset.** Dataset D is cited by a source under Position X *and* a source under
Position Y. → D is one root under X and one root under Y (independence is per-position). Optional
meta-flag: "this root is read both ways" (contested evidence).

---

## 6. Edge cases and how each resolves

1. **Ungrounded primary source** (claims original data, names no dataset) → the position's one
   **unnamed-primary pool**, not a per-source root. Mislabelling a flood of commentaries as
   `Observational` therefore mints ONE voice, not one root each — the echo-as-primary hole is
   closed by pooling (symmetric with reviews). A real study keeps its root by *naming* its own
   data. *Remaining risk:* fabricating a distinct named dataset per source still mints roots (edge
   fabrication, §8.3) — bounded by quote verification, the vocab, the ensemble + human review, not
   by the count.

2. **Meta-analysis** — *secondary or primary?* If it produces a **new pooled dataset** (re-analyzes
   raw data), it is primary: tag that pooled dataset as a root and it counts. If it only narrates
   others' conclusions, it is secondary. **The `restsOn` tag decides, not the word "meta."**

3. **Self-citing research group** → shared cohort root → collapses to 1. (Alias resolution stops
   the cohort being smuggled in under many names.)

4. **Long / transitive chains** → resolve to the terminal root. (E6.)

5. **One source resting on many roots** (a broad synthesis on 10 datasets) → contributes those 10
   roots. *Weak spot:* a single review could *assert* breadth that isn't independently present in
   the KB. *Proposed handling:* a root supported **only** by secondary sources is marked
   "asserted, not directly present" and can be down-weighted or shown distinctly. (Open: do we
   count it fully in v1?)

5b. **Non-human evidence on a clinical question.** A root backed **only** by animal / in-vitro
   sources (per the `population` tag: Mice, Rats, In vitro, …) is weaker evidence for a *human*
   question, so it counts at **half** — same mechanism as the secondary-only halving, and the two
   stack. A root that any human source also rests on keeps full weight. This needs the population
   tag to be set, so it only fires on sources labelled with the animal/in-vitro convention.

6. **Same dataset under multiple positions** → counts once per position; optional "contested"
   meta-flag. Not double-counting — independence is a within-position question.

7. **Cross-position circular corroboration** (A in X cites B in Y, B cites A) → an SCC spanning
   positions. v1: collapse to one root, contribute to each touched position, flag. *Weak spot:*
   semantics of a cross-side loop are genuinely odd; flagged as open.

8. **Missing/garbled `restsOn`** → tier default kicks in (primary→own root, secondary→pool).
   Graceful degradation; never crashes the metric.

9. **Duplicate roots under different names** → relies on root-identity resolution
   (normalized-string + learned aliases). *Weak spot:* a brand-new alias nobody has seen can slip
   through until curated. *Defense:* `dups`/`merge` tools + verification.

10. **Self-loop** (A rests on A) → edge dropped; A treated by its other edges / tier default.

11. **Empty position** (0 sources) → nEff 0, 0%.

12. **A secondary source that is the *only* thing citing an otherwise-absent primary study** → see
    (5). The primary study isn't in the KB; we only have a claim about it.

13. **Position whose entire support is one SCC of commentaries** → nEff 1 + circular/secondary
    flag. The chart shows "1 independent voice" — which is the honest answer.

---

## 7. Adversarial robustness (attack → defense)

| Attack | What the attacker wants | Defense |
|---|---|---|
| Flood with review articles | Inflate independence with echo | Secondary tier collapses to one voice per position |
| Flood with ungrounded "primary" rehashes (empty `restsOn`) | Mint a root each, bypassing the review collapse | Ungrounded primaries pool to one voice per position too — a distinct root needs a *named* evidence base |
| Flood echo onto a *minority* root the position already has | Even out the per-root source shares so a share-based index reads "more independent" | nEff counts each distinct root once (§4.4) — share-shuffling is arithmetic on a number the metric doesn't use |
| Pile junk "support" onto a **rival's** biggest root | Poison by agreement: skew their shares, tank their score | Same — presence, not tallies. The rival's nEff holds; the pile-up surfaces as *their concentration rising*, clearly labelled as a warning about correlation, not a lower independence count |
| Re-submit one cohort under many names | Fake many independent datasets | Normalized + alias root resolution; concentration *rises*, not falls |
| Mutual citation ring (A↔B↔C↔A) | Manufacture corroboration from nothing | SCC collapse to one root + `circularCorroboration` flag |
| Mislabel a commentary as `Observational` (empty `restsOn`) | Mint a free independent root | Ungrounded primaries **pool to one voice per position** (like reviews); a distinct root needs a *named* evidence base; unrecognised labels default secondary; + verification pass + relevance gate |
| Flood rehashes as `Observational`, each *naming a fabricated dataset* | Mint roots past the pool | **Not fully defended** (edge fabrication, §8.3) — bounded by quote verification, vocab, ensemble + human review, not the count |
| Single review asserting broad dataset support | Fake breadth | "Root present only via secondary" mark → that root counts at half |
| Re-submit the same study | Inflate count | Duplicate refusal (same url / title+year) |
| Add an off-topic but real study | Pad a position | Relevance gate refuses it at merge |

The deep property, stated precisely (and enforced by a randomized monotonicity test in
`tests/test_independence.py`): **adding a source never lowers any position's nEff, and raises it
only by introducing a new root or upgrading an existing root's strength** (primary grounding for a
review-only dataset; human evidence for an animal-only root — both of which *should* raise it).
Correlated, derivative, and circular evidence lands on roots already counted, so it moves nEff
nowhere; a first wave of ungrounded echo adds at most the two pooled voices (one unnamed-primary,
one secondary), once each. (Scope: the invariant is a theorem about the counting step with entity
identity fixed — the merge step's alias resolution can retroactively fold two roots into one and so
*lower* nEff, a curation event the arithmetic doesn't cover.)
An earlier formulation (a Herfindahl index over per-root source tallies) passed the ungrounded
attacks in this table but failed the two grounded ones — found by adversarially testing the metric
against its own claims, which is why the grounded rows above exist and why the invariant is now a
tested property rather than a slogan.

What this arithmetic cannot see is a source that **fabricates a root outright** — claiming a
dataset that doesn't actually back it. That is edge *fabrication*, the dual of the edge *omission*
in §8.3, and it is a labelling-integrity problem, not a counting problem: the partial defenses are
the per-`restsOn` provenance quote, quote verification against fetched text, and the relevance
gate. Named in §8 rather than hidden behind the invariant.

---

## 8. Weak spots we acknowledge (open problems — document, don't hide)

1. **Tier mislabelling.** The whole "primary vs secondary" floor depends on the evidence type
   being right. If a contributor (or model) calls opinion "Observational," it earns a root it
   shouldn't. *Partial defenses exist; not airtight.* This is the single biggest lever and the
   first place to attack the system. Since first draft, labelling can run as a **multi-model
   ensemble** whose field-level vote out-votes a single model's mislabel, and a genuine split on
   the position is **escalated to a human** (`engine/review.py`: pick a position or drop the paper)
   rather than merged under a guess — but a blind spot *shared* across models, or a deliberately
   mislabelled submission, still gets through.
2. **Roots asserted only by secondary sources.** We may credit a dataset that no primary source in
   the KB actually instantiates (edge case 5/12). v1 may over-count these.
3. **Citation data is self-reported.** We only know A rests on B because the labeller said so.
   We do not crawl real citation graphs. A truly adversarial actor can *omit* a `SRC:` edge to hide
   a dependency and look more independent than they are — and the dual attack, *fabricating* a
   `restsOn` edge to a dataset that doesn't actually back the source, mints a root the position
   hasn't earned (§7). The verification pass can catch *false quotes* (including the quote each
   `restsOn` edge is supposed to carry) but not *missing* edges; crawling an external citation
   graph (OpenAlex/Crossref) and diffing declared-vs-crawled edges is the known fix for the
   omission half, not yet built.
4. **Cross-position cycles** have genuinely ambiguous semantics (edge case 7).
5. **Alias gaps.** A novel name for an existing cohort counts as new until someone curates it.
6. **"One voice" is a modelling choice, not a measurement.** Two truly independent review teams
   *might* deserve >1. We chose the conservative floor (B) on purpose; it is a stance, not a fact.

If we publish the system, we publish this list. That is the epistemically honest move — the same
instinct as documenting dataset errors instead of silently fixing them.

---

## 9. Why it is novel

Most tools in this space do one of: (a) count studies; (b) score each study's *internal* quality
(risk-of-bias, GRADE); or (c) build a citation graph for *influence* (who's cited most). None of
them measure **how many independent evidentiary roots actually support a claim**, and none treat
**echo, cohort re-use, and circular citation as one phenomenon** resolved by collapsing a
derivation graph to its roots. The combination — *tier-aware grounding* + *root-resolution over a
derivation graph* + *strongly-connected-component collapse for circular corroboration* + a
*strength-weighted distinct-root count* with a tested flooding-immunity invariant — is, as far as
we know, new as a single, deterministic, auditable metric. (The honest lineage: this is the
"studies vs. reports" de-duplication discipline systematic-review craft applies by hand in one
domain, generalized to arbitrary disputes, automated, and made adversarially robust.)

## 10. Why it is general

The mechanism never looks at domain content. It operates on the abstract ontology of §2 —
source, position, root, derivation, tier. The *vocabulary* (what counts as a dataset, what evidence
types exist) lives in the per-case KB, not in code. So the identical engine maps a virology dispute,
a nutrition dispute, and a physics dispute. A new field adds vocabulary, never code. That is what
lets one renderer and one metric serve every question on the portal.

---

## 11. Data-model change this requires

`restsOn` today holds dataset ids. We extend each entry to be **either** a dataset id **or** a
reference to another source (`SRC:<id>` / `NEW-SRC:<title>`). Everything else (positions, factors,
provenance) is unchanged. Migration is trivial: existing KBs have only dataset entries, which are a
valid subset, so old data resolves exactly as before — except that ungrounded *secondary* sources
now collapse (the §4.2 rule), which is the intended re-weighting.

**Computation lands in `engine/assess.py`** (pure functions, recomputed from the KB — no drift).
**Labelling guidance lands in `prompts/ingest.md` + `ingest/pipeline.py`** (the `restsOn` rule and
the tier table). **Verification** is a separate axis (truthfulness of a quote), not part of this
file.

---

## 12. Triangulation — a second independence axis (v1 method audit implemented)

### 12.0 The gap this closes

Sections 1–11 count **datasets**. If 15 sources rest on 15 *distinct* cohorts, the mechanism
correctly reports 15 independent bases. But independence-of-**data** is not the same as
independence-against-**being-wrong**. If all 15 cohorts share the same uncontrolled confounder —
the textbook case is "moderate alcohol" studies sharing abstainer/sick-quitter bias — they can all
be wrong in the same direction for the same reason. Fifteen distinct datasets, one shared way to
fail. The existing metric is blind to this, because it was never designed to see it: it answers
"how many different pieces of data?", not "how many different ways this could be an artifact?".

This section proposes a **second, separate metric** for the latter question. It does **not** change
the existing independence metric (§1–11) at all — that metric's claim ("distinct datasets count
distinctly, echo and circularity collapse") is clean, defensible, and stays exactly as specified.
Triangulation is an additional lens shown *alongside* it, not a replacement.

### 12.1 The precise principle: correlated vs. independent error

Replication only buys confidence when the studies being replicated can fail for **independent**
reasons. This is standard epistemology of evidence (triangulation; Munafo & Davey Smith 2018), not
a new invention:

| Dominant error source | Correlated across studies of the same design? | More studies help? |
|---|---|---|
| Chance / sampling variation | No — each trial's randomization is its own coin flip | Yes (this is why RCT meta-analysis works) |
| Unmeasured confounding (same lurking variable) | Yes — every cohort fails to measure the same thing | No — replication cannot fix a shared blind spot |
| Shared measurement error (e.g. self-reported exposure) | Yes | No |
| Surrogate-endpoint validity (LDL instead of heart attacks) | Yes, across everyone using that surrogate | No |
| Genetic-instrument pleiotropy (Mendelian randomisation) | Yes, for studies sharing the same instrument | Partially |

So: **observational studies of the same question sharing the same design generally share the same
confounding risk; RCTs generally do not share a systematic risk with each other.** This is not
"RCT good, observational bad" — it is domain-general: whenever two studies would be wrong *for the
same reason*, they should count as one look for triangulation purposes, however many datasets they
individually rest on.

**The test this must pass:** it must give the *opposite, correct* verdict on cases where
observational evidence is right. Smoking→lung cancer was established by cohorts + dose-response +
animal experiments + mechanism + natural experiments — several genuinely *different* method
families agreeing, not one design repeated. The audit should therefore warn on an alcohol-style
single-method literature while staying quieter on a genuinely triangulated smoking-style literature.
Same lens, opposite verdicts, both right — that is the bar for this becoming a real metric and not a
thumb on the scale.

### 12.2 Ontology addition: Method class

One new concept, parallel to **Tier** (§2):

| Thing | Plain meaning | Example |
|---|---|---|
| **Method class** | The correlated-error signature shared by a design family — the *way* a source could be systematically wrong. | `confounding` (observational designs sharing an unmeasured variable), `pleiotropy` (Mendelian-randomisation studies sharing a genetic instrument's off-target effects). |

A method class is usually derived from the source's evidence type, with an optional source-level
override for curated cases:

- **Tier 1 (default, always on):** from the source's existing `evidence` type, via a small
  conservative default table plus an optional `methodClass` property on the case's
  evidence-vocabulary term — the exact same pattern `tier` already uses (§2.3, §3.2). A case can
  override or opt out of a default by setting `methodClass` on the evidence-vocabulary term.
- **Tier 2 (optional, sharper, needs one new field):** a `biases` tag on the source itself, drawn
  from a **per-case controlled vocabulary** (a new `kb.vocab.bias` kind, resolved by the same
  normalized-string + alias "propose, then deterministically resolve" discipline as datasets and
  funding — never free text; see §12.7 for why this matters). When present, the specific tag
  **replaces** the tier-1 default for that source (more specific information wins; the source
  does not count toward both at once).

**Default tier-1 mapping** (biomedical causal questions; a case may override or extend):

| Evidence type | Method class |
|---|---|
| Observational (cohort / case-control / cross-sectional / ecological) | `confounding` |
| Mendelian randomisation *(a case-introduced evidence type, not in the base vocab)* | `pleiotropy` |
| Experimental (RCT) | — none (chance error is independent across trials) |
| Mechanistic / animal / in-vitro | — none in *this* axis (already discounted by the existing non-human halving, §6.5b — deliberately not double-counted here, see §12.7) |
| Secondary tiers (review, commentary, meta-analysis, …) | — none (already collapsed into the secondary-voice pool by the existing mechanism, §4.2) |

For a non-causal, non-empirical question (a physics dispute, a legal one), the default table should
not recognize the evidence labels, so sources fall through to "no method class" unless the case
vocabulary explicitly opts in. The axis silently does nothing rather than inventing a method
structure it does not understand. This preserves the "new domain adds vocabulary, not code"
property (§10).

### 12.3 Implemented v1 — method concentration audit

The first build is intentionally a **warning lens**, not a second weighted-distribution bar and not
a replacement for §1–11. For each source, the assessment layer derives a `methodClass` (§12.2).
Then, per position, it counts how many sources have a recognizable method-risk family and computes:

- `classed`: internal field name for "sources with a recognizable method-risk family";
- `top`: the most common method class, with count and share;
- `method nEff`: Herfindahl numbers-equivalent over method classes only;
- `monoculture`: true when at least 3 sources have a method-risk family, at least 70% of those
  sources share one family, and they cover at least 30% of the position's sources.

This ships as a first-screen warning, an annotation on the Independence tab, and in `cli.py show`:
*"N of M sources share observational confounding risk."* It deliberately **changes no existing
metric**. It is a prompt for scrutiny: "these datasets may still fail together for the same
methodological reason."

### 12.4 Why the full triangulation number is deferred

The tempting formula is: take each source's resolved data roots, add a synthetic `method:<class>`
root, and run a Herfindahl-style share calculation over the enriched tallies (note: the *primary*
metric deliberately does not use share arithmetic at all — §4.4 — which is one more reason not to
bolt this on). That gives the useful alcohol arithmetic:

```
15 distinct observational datasets + one shared method root
HHI  = 15 × (1/30)^2 + (15/30)^2 = 0.2667
nEff = 3.75
```

But this enriched-root formula is **not** safe as a general second number yet. Adding a synthetic
method root can *increase* `nEff` in small or already-concentrated cases: one shared dataset plus
one shared method root has weights `[N, N]`, which yields `nEff = 2` even though the primary data
independence is `1`. So the invariant "triangulation never exceeds primary independence" is false
unless we explicitly bound or redesign the formula.

For that reason, v1 reports **method concentration**, not "independent looks against bias." A later
triangulation score should either be explicitly bounded by the primary independence count or use a
different combination rule whose semantics are clearer than "add one more root."

### 12.5 Staged build plan (cheapest, lowest-risk first)

1. **Method-monoculture flag — implemented.** No new source field; uses source/vocab
   `methodClass` when present, with conservative defaults for obvious primary designs such as
   `Observational → confounding`. It changes no numbers.
2. **Bounded triangulation score — design still open.** Candidate formulas must not inflate beyond
   primary data independence and must be labelled separately from the dataset-root count.
3. **`kb.vocab.bias` controlled vocabulary + `biases` tag (tier 2)** — sharpens tier 1 when a
   contributor names the actual confounder (`abstainer-bias`, `surrogate-endpoint`, …), resolved
   through the standard vocab-resolution discipline (§12.7 explains why this step cannot skip that).
4. **Supersession edges** (`supersedes`/`refutes` between sources) — deliberately **out of scope
   for this section**. Kept as a lineage/timeline feature only (what the Changes tab shows), with
   no automatic re-weighting of any metric. Revisit only as a narrative feature.

### 12.6 Why this is a second axis and not a change to §1–11

Keeping the two axes structurally separate (not blended into one composite score) matters for
three reasons: (a) the existing metric's claim is narrow and easy to defend ("distinct data counts
distinctly"); blending would make it defend a broader, more contestable claim instead. (b) A single
blended number would hide *which* kind of independence a position lacks — data or method — exactly
the transparency §7/§8 are built to preserve. (c) Tier-2 bias tags are more interpretive than
dataset identity (§12.7); keeping them on a clearly separate, clearly labelled axis stops that
softer judgment from contaminating the harder, more mechanical primary metric.

### 12.7 New weak spots this would introduce (name them before building, not after)

1. **Tier-2 tags are a new gaming surface.** Free-text bias tags would let a contributor invent a
   unique fake confounder per source specifically to dodge collapse — worse than not having tier 2
   at all. This is only safe if bias tags are a **controlled, alias-resolved vocabulary**
   (`kb.vocab.bias`, same discipline as `dataset`/`funding`/`population`) — never free text. This is
   a hard requirement on any implementation, not a nice-to-have.
2. **Tier-1 buckets are coarse by construction.** Two observational studies that actually adjust for
   *different* confounders get lumped into one `confounding` bucket until someone adds tier-2 tags.
   This under-counts genuine (if partial) triangulation within the observational literature. It is
   the deliberate, documented floor — sharpening is opt-in, not automatic.
3. **Tier-2 tags are judgment calls, more so than dataset identity.** Naming "the" confounder a
   study shares with others is closer to the "curated factor weights" soft spot already named in
   `SPEC.md` §8 than to the hard, mechanical parts of this system (counts, dataset ids). It should
   be labelled as such wherever it is surfaced, not presented with the same confidence as the
   primary metric.
4. **The tier-1 mapping is itself a domain judgment**, made once per case (or inherited from a
   default table) rather than derived from the text. A case that mis-sets `methodClass` — or a
   domain where the biomedical default is silently wrong — will mis-triangulate. This is the same
   class of risk as tier mislabelling (§8.1), one level up.
5. **Interaction with the non-human halving (§6.5b) must stay disjoint**, or a mechanistic/animal
   source could get discounted twice for what is really one underlying concern (translational
   validity). §12.2 resolves this by giving mechanistic/animal sources no method class in this axis
   at all — but that is a design choice to keep stated, not an accident to rediscover later.
6. **Conservative MR grouping** (all Mendelian-randomisation studies sharing one `pleiotropy` root,
   regardless of which genetic instrument each one actually used) will over-collapse a position that
   in fact has several MR studies using genuinely different, uncorrelated instruments. This is a
   known, deliberate simplification for a first build — the sharper fix is instrument-level tier-2
   tags, deferred.

If this is built, this list ships with it — the same "document the weak spot, don't hide it"
discipline as §8.
