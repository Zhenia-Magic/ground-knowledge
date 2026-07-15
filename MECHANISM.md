# The Evidence-Independence Mechanism

*The conceptual core of Ground Knowledge, in plain language. This is the spec we label against
and compute against. Read it adversarially — the point is to find the weak spots before they find
us.*

---

## 0. The one-sentence idea

> Source volume is not evidence coverage. The mechanism maps **distinct admitted evidentiary roots**
> behind each position, collapsing documents that reuse, summarize, or circularly cite the same
> underlying basis. The resulting coverage count is not itself a verdict on evidence quality.

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
Root identity and support-edge admission are recorded per source/position; method independence is a
separate audit rather than assumed from root count.

---

## 3. What we record when we label a source

For every source, the labeller (human, a single LLM, or a multi-model **ensemble** whose per-field
majority vote is combined deterministically — `ingest/ensemble.py`) records:

1. **Position** — the single stance it argues. (Already in the schema.)
2. **Evidence type** — from the case's controlled vocabulary. This determines the **tier**:
   - **Primary** tiers *make* evidence: `Observational`, `Experimental (RCT)`, `Mechanistic`.
   - **Secondary** tiers *talk about* evidence: `Meta-analysis` / `Systematic review`,
     `Narrative/Commentary`, `Evidence-synthesis`, `Expert advisory`, `Institutional statement`,
     `Editorial/Perspective`. A meta-analysis is a *synthesis* — it earns root-coverage credit only
     for **admitted links to the trials it pools** (then it resolves through them, tier aside); an
     untagged one is echo and collapses into a visible, zero-credit secondary pool. (This is the common real failure:
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
4. **Provenance quote** — the verbatim sentence offered to justify the position. The deterministic
   verification pass checks only that the sentence is exact source text; it cannot prove that the
   sentence entails the position. That second judgement is recorded separately as labelling
   confidence. A positioned source with no position excerpt is an explicit audit failure, not a
   quote-less but otherwise fully grounded classification.

> **Labelling principle for `restsOn`:** tag what the source *actually leans on*, even for reviews.
> A review of the proximal-origin paper **rests on the proximal-origin dataset** — say so, and it
> will collapse into that root automatically. Only leave `restsOn` empty when the source genuinely
> grounds in nothing checkable (pure opinion). This is what makes the mechanism degrade *gracefully*:
> good tagging makes the tier rule unnecessary; the tier rule is the safety net for bad tagging.

---

## 4. How confirmed-root coverage is computed (the algorithm, in plain language)

### 4.1 Build the dependency graph
Nodes are **sources** and **roots**. A stored `restsOn` assertion becomes a traversable edge only
when that particular support link has a verified, specifically identifying dependency quote or an
explicit curator/trusted-migration admission. Unadmitted links remain stored and visible at zero.
Self-edges are dropped.

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
    **ungrounded-secondary pool** — one shared visibility marker per position.
  - an **unrecognised** evidence label resolves as **secondary** (conservative — a coined/opinion
    label can't mint a primary root; a new primary *design* is opted in via `kb.vocab` tier).

### 4.3 Collapse cycles — *circular corroboration*
While following source→source edges we may hit a **cycle**: A→B→A, or longer. Compute the
**strongly connected components** (SCCs) of the source graph. For each SCC of size > 1 (a group of
sources that mutually depend):

- The whole component **collapses to one marker**, because no member adds independence the others
  don't already have.
- If the component **also** reaches a real dataset (someone in the loop is actually grounded),
  it collapses *into that dataset's root* — redundant, not vacuous.
- If the component reaches **no** evidence base — it is **pure circular corroboration**. It collapses
  to one visible cycle marker, contributes **zero** to `nEff`, and raises a
  `circularCorroboration` flag naming the loop. This is the adversarial pattern, surfaced loudly.

### 4.4 Count confirmed-root coverage per position
For each position, take all its sources, map each to its resolved root(s), and count **each
distinct root exactly once, at its strength**:

```
nEff = Σ strength(root_i)     over the position's DISTINCT resolved roots

strength = 0.0   if the root is PROVISIONAL — not yet confirmed by a fetched source whose
                 per-edge `restsOn` quote verified against its text **and identifies the base's
                 specific label/learned alias**, or by an explicit curator decision.
                 It remains visible as a proposed base but is quarantined from headline nEff.
         = 0.0   if this position's source→root support edge is unadmitted, even when the root's
                 identity was confirmed elsewhere
         = 0.0   for pure ungrounded circular-citation and pooled assertion markers (visible)
         = 1.0   for a confirmed real root (a NAMED dataset / cohort / experiment)
         × 0.5   if the root is known only via secondary sources (§6.5)
         × 0.5   if the root is backed only by animal / in-vitro studies (§6.5b)
```

This is **confirmed-root coverage**, a full-strength-equivalent root count. One admitted root used
by everyone → nEff = 1. Ten admitted roots → nEff = 10, whether each is used once or one is used a
hundred times. It is deliberately **not** a support, quality, confidence, effect-size, or truth
score: one decisive trial may outweigh several weak roots, and distinct roots may share a bias.
Source incidence feeds the separate concentration display.

*Why not a share-based concentration index (Herfindahl) over the per-root source tallies?* Because
any formula that reads per-source tallies is movable by adding worthless sources: echoing reviews
onto a position's *minority* root evens out the shares and raises such an index (flooding fakes
independence), and piling junk "support" onto a rival's biggest root skews the shares and tanks
theirs (poisoning by agreement). Counting each root once makes both attacks inert by construction
— for a fixed entity/edge graph, the only ways nEff moves are adding a genuinely **new admitted
root** or **upgrading** a root's strength (a primary source landing on a review-only dataset; a
human study landing on an animal-only root), and both of those *should* move it. Graph corrections
can legitimately lower it: merging aliases or resolving a pending edge that reveals a pure cycle.

### 4.5 The two bars the reader sees
- **By source count** — the naive tally (kept, honestly labelled as naive).
- **By confirmed-root coverage** — sized by `nEff` over admitted resolved roots.
- Plus, always, **the derivation shown**: "25 sources → 7.0 confirmed-root coverage; 15 ungrounded
  reviews collapse to a visible zero-credit marker; furin-cleavage + proximal-origin share a root." The number is
  never a black box.

---

## 5. Worked examples

**E1 — Echo.** Position has 1 primary study (dataset D) + 12 narrative reviews, all `restsOn`
empty. → markers = {D, secondary-pool}. nEff = 1. The reviews stay visible but add zero grounding.

**E2 — Echo, well-tagged.** Same, but each review `restsOn` D (we tagged what they summarize). →
every node resolves to D. nEff = 1. Even cleaner — and no tier rule was needed.

**E3 — Cohort re-use.** 8 papers, all `restsOn` cohort C. → nEff = 1. (Existing behavior.)

**E4 — Pure circular corroboration.** A `restsOn` [SRC:B], B `restsOn` [SRC:A], no datasets. →
SCC {A,B}, no evidence base → one visible cycle marker, **flagged**. nEff contribution = 0.

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
   `Observational` therefore mints one visible marker and **zero** coverage — the echo-as-primary
   hole is closed. A real study keeps its root by *naming* its own
   data. A fabricated named dataset remains visible as a proposed root but contributes zero headline
   nEff until a fetched dependency quote verifies that specific edge **and names a specific base**, or
   a curator confirms it. Generic labels ("cohort") and lexical alias collisions are quarantined.
   *Remaining risk:*
   false confirmation of that edge
   (edge fabrication, §8.3) is a semantic-verification problem the count cannot solve.

2. **Meta-analysis** — *secondary or primary?* If it produces a **new pooled dataset** (re-analyzes
   raw data), it is primary: tag that pooled dataset as a root and it counts. If it only narrates
   others' conclusions, it is secondary. **The `restsOn` tag decides, not the word "meta."**

3. **Self-citing research group** → shared cohort root → collapses to 1. (Alias resolution stops
   the cohort being smuggled in under many names.)

4. **Long / transitive chains** → resolve to the terminal root. (E6.)

5. **One source resting on many roots** (a broad synthesis on 10 datasets) → exposes those roots,
   but they count only when admitted. A confirmed root supported **only** by secondary sources is
   marked "via review only" and contributes 0.5; an unconfirmed root contributes zero. This is
   implemented in `root_strength`, not proposed future work.

5b. **Non-human evidence on a clinical question.** A root backed **only** by animal / in-vitro
   sources (per the `population` tag: Mice, Rats, In vitro, …) is weaker evidence for a *human*
   question, so it counts at **half** — same mechanism as the secondary-only halving, and the two
   stack. A root that any human source also rests on keeps full weight. This needs the population
   tag to be set, so it only fires on sources labelled with the animal/in-vitro convention.

6. **Same dataset under multiple positions** → counts once per position; optional "contested"
   meta-flag. Not double-counting — independence is a within-position question.

7. **Cross-position circular corroboration** (A in X cites B in Y, B cites A) → an SCC spanning
   positions. Collapse to one zero-strength marker under each touched position and flag. *Weak spot:*
   semantics of a cross-side loop are genuinely odd; it is shown rather than silently interpreted.

8. **Missing/garbled `restsOn`** → the source names no evidence base, so it pools per its tier
   (a primary with nothing named → the position's one unnamed-first-hand voice; a secondary → the
   review voice). Graceful degradation; never crashes the metric, and never mints a per-source root.

9. **Duplicate roots under different names** → relies on root-identity resolution
   (normalized-string + learned aliases). *Weak spot:* a brand-new alias nobody has seen can slip
   through until curated. *Defense:* `dups`/`merge` tools + verification.

10. **Self-loop** (A rests on A) → edge dropped; A treated by its other edges / tier default.

11. **Empty position** (0 sources) → nEff 0, 0%.

12. **A secondary source that is the *only* thing citing an otherwise-absent primary study** → see
    (5). The primary study isn't in the KB; we only have a claim about it.

13. **Position whose entire support is one SCC of commentaries** → nEff 0 + circular flag. The loop
    remains inspectable, but the chart does not call it independent grounding.

---

## 7. Adversarial robustness (attack → defense)

| Attack | What the attacker wants | Defense |
|---|---|---|
| Flood with review articles | Inflate coverage with echo | Secondary tier collapses to one visible zero-credit marker per position |
| Flood with ungrounded "primary" rehashes (empty `restsOn`) | Mint a root each | Ungrounded primaries pool to a zero-credit marker too — a distinct root needs a named and admitted base |
| Flood echo onto a *minority* root the position already has | Even out the per-root source shares so a share-based index reads "more independent" | nEff counts each distinct root once (§4.4) — share-shuffling is arithmetic on a number the metric doesn't use |
| Pile junk "support" onto a **rival's** biggest root | Poison by agreement: skew their shares, tank their score | Same — presence, not tallies. The rival's nEff holds; the pile-up surfaces as *their concentration rising*, clearly labelled as a warning about correlation, not a lower independence count |
| Re-submit one cohort under many names | Fake many independent datasets | Normalized + alias root resolution; concentration *rises*, not falls |
| Mutual citation ring (A↔B↔C↔A) | Manufacture corroboration from nothing | SCC becomes one visible marker, contributes zero + `circularCorroboration` flag |
| Mislabel a commentary as `Observational` (empty `restsOn`) | Mint a free independent root | Ungrounded primaries **pool to one voice per position** (like reviews); a distinct root needs a *named* evidence base; unrecognised labels default secondary; + verification pass + relevance gate |
| Flood rehashes as `Observational`, each *naming a fabricated dataset* | Mint roots past the pool | Unverified roots remain visible but contribute **zero confirmed nEff**; a verified dependency quote must also name that edge's label/alias; false curator confirmation remains the semantic risk (§8.3) |
| Attach an already-confirmed root to another camp | Launder trusted root identity into unearned support | Root identity and support-edge admission are separate; the unreviewed edge stays visible at zero |
| Single review asserting broad dataset support | Fake breadth | "Root present only via secondary" mark → that root counts at half |
| Re-submit the same study | Inflate count | Duplicate refusal (same url / title+year) |
| Add an off-topic but real study | Pad a position | Relevance gate refuses it at merge |

The deep property, stated precisely (and enforced by a randomized test in
`tests/test_independence.py`): **with entity identity and existing edges fixed, adding a source with
only outgoing edges never lowers a position's nEff; it raises it only by introducing a new confirmed
root or upgrading an existing root's strength.** Correlated/derivative evidence lands on roots
already counted; any amount of ungrounded echo adds zero coverage. A graph
correction may intentionally lower nEff: alias resolution can fold duplicate roots, and resolving a
pending edge can reveal that apparent grounding is actually a pure zero-strength citation cycle.
An earlier formulation (a Herfindahl index over per-root source tallies) passed the ungrounded
attacks in this table but failed the two grounded ones — found by adversarially testing the metric
against its own claims, which is why the grounded rows above exist and why the invariant is now a
tested property rather than a slogan.

What this arithmetic cannot see is whether a fetched source or curator **falsely confirms a root or
support edge**. Unverified roots and unadmitted support links are quarantined at zero, closing the
public count-inflation and confirmed-root-laundering paths; false confirmation remains edge *fabrication*, the dual of edge
*omission* in §8.3. It is a semantic labelling-integrity problem: the defenses are per-`restsOn`
provenance, verification against fetched text, and review. Named in §8 rather than hidden.

---

## 8. Weak spots we acknowledge (open problems — document, don't hide)

1. **Tier mislabelling.** The primary/secondary discount depends on the evidence type being right.
   Calling opinion "Observational" no longer earns one root per source: without an admitted named
   base it enters a zero-credit marker; with an existing base **and an admitted support edge** it can
   still wrongly upgrade a review-only root. *Partial defenses exist; not airtight.* This remains a lever and the
   first place to attack the system. Since first draft, labelling can run as a **multi-model
   ensemble** whose field-level vote out-votes a single model's mislabel, and a genuine split on
   the position **or evidence tier** is escalated to a human (`engine/review.py`)
   rather than merged under a guess — but a blind spot *shared* across models, or a deliberately
   mislabelled submission, still gets through.
2. **Roots asserted only by secondary sources.** A confirmed one contributes 0.5 and is labelled
   "via review only"; an unconfirmed one contributes zero. The residual risk is a wrong curator
   confirmation, not an unimplemented weighting rule.
3. **Citation data is self-reported.** We only know A rests on B because the labeller said so.
   We do not crawl real citation graphs. A truly adversarial actor can *omit* a `SRC:` edge to hide
   a dependency and look more independent than they are — and the dual attack, *fabricating* a
   `restsOn` edge to a dataset that doesn't actually back the source, can add a root the position
   hasn't earned (§7). Root identity and support are now admitted **separately**: a fetched source confirms a dataset
   only through the specific `restsOn` edge whose own dependency quote verified against the fetched
   text **and names that root's canonical label or alias** (edge objects `{ref, provenance}`); a
   source citation (`src:`) propagates roots only after explicit edge admission. This closes the earlier whitewash where one source-level quote admitted *every*
   dataset a source touched (a source claiming ten datasets had to verify one quote, not ten) and
   where a review's quote confirmed the primary study's data by inheritance, and the later loophole
   where a confirmed root could be attached to a new camp. Curator root and edge admissions are
   **auditable records** (`status + method + by + ts`, with optional note/source),
   not an opaque boolean; a lexical/semantic duplicate candidate is blocked at this boundary unless
   the curator records an override. Automatically verified lexical lookalikes admit at most one root
   and surface the collision. It is still a human vouch, so a wrong confirmation or missing edge remains a risk.
   The verification pass catches *false quotes* but not *missing* edges; crawling an external
   citation graph (OpenAlex/Crossref) and diffing declared-vs-crawled edges is the known fix for the
   omission half, not yet built.
4. **Cross-position cycles** have genuinely ambiguous semantics (edge case 7).
5. **Alias gaps.** A novel name remains proposed until curated. Lexical/acronym and optional
   embedding suggestions plus the confirmation gate reduce this risk; they deliberately do not
   auto-decide semantic identity.
6. **The 0.5 discounts are modelling choices, not measurements.** Review-only and non-human roots
   receive half credit. Those coefficients are declared heuristics, not empirically calibrated
   likelihood ratios; the UI shows them per root and keeps evidence design separate.
7. **Claim granularity remains coarse.** A source has one top-level position and an unordered set of
   support links. It cannot yet represent that one paragraph supports claim A while another rebuts
   subclaim B without splitting the source into multiple claim records. Typed claim-level edges are
   a genuine architectural extension, not a deadline patch.
8. **No reader-uplift result.** The benchmark tests structure and invariants, not whether readers
   become better calibrated. The reader-study materials are future-work scaffolding only.

If we publish the system, we publish this list. That is the epistemically honest move — the same
instinct as documenting dataset errors instead of silently fixing them.

---

## 9. Why it is novel

Most tools in this space do one of: (a) count studies; (b) score each study's *internal* quality
(risk-of-bias, GRADE); or (c) build a citation graph for *influence* (who's cited most). Counting
independent data sources rather than papers is **not new** — meta-analysis handles multiple
estimates from one cohort as a "unit-of-analysis" problem, and systematic reviews distinguish
"studies vs. reports." What isn't standard is applying one **deterministic, recomputable metric to a
structured empirical-causal dispute and testing explicit adversarial contracts** — treating **echo, cohort re-use, and
circular citation as one phenomenon** resolved by collapsing a derivation graph to its roots. The combination — *tier-aware grounding* + *root-resolution over a
derivation graph* + *strongly-connected-component collapse for circular corroboration* + a
*strength-weighted distinct-root count* with a tested flooding-immunity invariant — is, as far as
we know, new as a single, deterministic, auditable metric. (The honest lineage: this is the
"studies vs. reports" de-duplication discipline systematic-review craft applies by hand in one
domain, operationalized across several empirical case shapes, partly automated, and adversarially tested.)

## 10. Why it is general

The mechanism never looks at domain content. It operates on the abstract ontology of §2 —
source, position, root, derivation, tier. The *vocabulary* (what counts as a dataset, what evidence
types exist) lives in the per-case KB, not in code. So the identical engine maps a virology dispute,
a nutrition dispute, and an empirical physics-risk dispute. A new field adds vocabulary, never code.
That is what lets one renderer and one metric serve every question on the portal.

**Scope, honestly.** This is general across **empirical-causal** disputes — where a position bottoms
out in data-generating processes and *shared data is a reason to discount, not to add*. It is not a
universal dispute-mapper: in **law**, authority is partly cumulative (collapsing twenty rulings that
cite one precedent would be *wrong*); in **mathematics**, validity isn't a counting exercise at all.
And the primary/secondary tier table + the animal/in-vitro halving are biomedicine-shaped defaults a
distant empirical field must re-specify — more than a vocabulary swap. "Vocabulary, not code" holds
inside the empirical-causal family and degrades outside it.

---

## 11. Current data model

`restsOn` entries are either an evidence-base id, a source reference (`src:<id>`), or an edge object
`{ref, provenance}` carrying that specific dependency quote. Bare strings remain backward-compatible;
new fetched ingestion requests edge objects for dataset dependencies. Computation is in
`engine/roots.py` + `engine/assess.py`; labelling guidance is in `prompts/` + `ingest/pipeline.py`;
quote matching is in `engine/verify.py`. Current shipped cases still contain legacy string edges and
curator confirmations, so per-edge fetch verification coverage is not overstated.

---

## 12. Triangulation — a second independence axis (v1 method audit implemented)

### 12.0 The gap this closes

Sections 1–11 count **evidence bases** (datasets, experiments, observations, arguments, models, or
documents). If 15 sources rest on 15 admitted *distinct* cohorts, the mechanism reports 15.0
confirmed-root coverage. But independence-of-**data** is not the same as
independence-against-**being-wrong**. If all 15 cohorts share the same uncontrolled confounder —
the textbook case is "moderate alcohol" studies sharing abstainer/sick-quitter bias — they can all
be wrong in the same direction for the same reason. Fifteen distinct datasets, one shared way to
fail. The existing metric is blind to this, because it was never designed to see it: it answers
"how many different pieces of data?", not "how many different ways this could be an artifact?".

This section proposes a **second, separate metric** for the latter question. It does **not** change
the existing root-coverage metric (§1–11) at all — that metric's claim ("confirmed, admitted evidence bases
count distinctly, echo pools, and pure circularity counts zero") stays narrow and testable.
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

This ships as a first-screen warning, an annotation on the Root coverage tab, and in `cli.py show`:
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
