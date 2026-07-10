# Independent-Evidence Aggregation: Algorithm and System Description

*A domain-neutral write-up of a mechanism for aggregating claims about contested factual questions, prepared for external review and critique. All examples below are illustrative and abstract — the mechanism itself never looks at subject matter.*

---

## 1. The one-sentence idea

A position on a contested question is only as strong as the number of **genuinely independent pieces of evidence** behind it — not the number of documents that assert it. The system counts *independent evidentiary roots*, collapsing everything that merely echoes, summarizes, or circularly cites the same underlying evidence.

Counting sources rewards whoever publishes (or re-publishes) the most. This system counts *roots* instead.

---

## 2. The problem being solved

Picture a debate where one side has 20 documents and the other has 4. A naive aggregator says "20 vs 4 — the first side wins." But suppose all 20 documents re-analyze the same underlying dataset. Then they aren't 20 independent pieces of evidence — they're closer to **one** piece of evidence cited 20 times. Counting them as 20 is misleading, and it's *gameable*: anyone can flood a position with re-hashed write-ups to manufacture the appearance of consensus.

Three failure modes break naive source-counting, and they look identical on a simple tally:

1. **Echo.** Ten summary articles all restating the same three original studies are *one* look, not ten. Yet each is a separate "source."
2. **Resource re-use.** One group publishes eight documents off a single underlying dataset or experiment. Eight sources, one independent basis.
3. **Circular corroboration.** Source A's main support is Source B; Source B's main support is Source A. Two sources, *zero* independent grounding. This is the adversarial case — designed to look like mutual confirmation.

All three are the same underlying problem: **sources that add no new evidentiary root.** The mechanism is one cure for all three.

A secondary problem: naive aggregation also buries *where* the disagreement actually is. Two camps in a dispute usually agree on most underlying considerations and disagree on a handful of specific points — but a flat list of sources doesn't show which points those are.

---

## 3. Core design commitment

> Aggregate, but weight by evidence quality and audit for independence — instead of counting sources. If a feature could be gamed by flooding the zone with low-quality or correlated material, it is the wrong feature. Adding correlated evidence to a position must make it look **less** settled, not more.

Everything in the system follows from that commitment.

---

## 4. Ontology — the five things that exist

| Thing | Plain meaning | Example |
|---|---|---|
| **Source** | A document that takes a position. | A paper, a report, a commentary, a guideline. |
| **Position** | A stance on the question. | "Yes," "No," "Depends on context." |
| **Root** (evidentiary basis) | The underlying thing that actually *generates* information. | A dataset, a cohort, an experiment, a model run, a field observation. |
| **Derivation** | What a source draws its support *from*. Points at roots and/or other sources. | "This summary rests on dataset D." |
| **Tier** | Does the source *make* evidence or *talk about* evidence? | **Primary** (makes) vs **Secondary** (talks about). |

The key move: **sources and roots are different kinds of node.** Many sources can share one root. Independence is a property of *roots*, counted *per position*.

---

## 5. What is recorded for each source

For every source, a labeller (human or AI model) records:

1. **Position** — the single stance it argues.
2. **Evidence type** — from a controlled vocabulary specific to the question's domain. This determines the **tier**:
   - **Primary** tiers *make* evidence: e.g., original observation, controlled experiment, mechanistic/model-based finding.
   - **Secondary** tiers *talk about* evidence: e.g., meta-analysis / systematic review, narrative commentary, evidence synthesis, expert advisory statement, institutional statement, editorial/perspective. A synthesis only counts as independent if it **names the individual studies it pools**; otherwise it collapses into the position's one secondary voice. (This is the common real failure: ten syntheses of the same overlapping underlying studies are one look, not ten.)
   - Tier is a property attached to each vocabulary term, not guessed per source — deterministic and auditable, and a specific case can override it.
3. **`restsOn`** — the heart of the mechanism. A list of what the source draws support from. Each entry is one of:
   - a **root** (a dataset / experiment / observation set), by id or a "new" marker;
   - **another source** already in the knowledge base, when the source in question *is* citing that other source — this is how citation/derivation is captured and how circularity is detected;
   - nothing (the list is empty) — the source is **ungrounded**.
4. **Provenance quote** — the verbatim sentence that justifies the position, which is separately checked against the source text.

**Labelling principle:** tag what the source *actually leans on*, even for summary pieces. A review of an underlying dataset **rests on that dataset** — say so, and it will collapse into that root automatically. Only leave `restsOn` empty when the source genuinely grounds in nothing checkable (pure opinion). Good tagging makes the tier rule mostly unnecessary; the tier rule is the fallback for incomplete tagging.

---

## 6. The algorithm

### 6.1 Build the dependency graph
Nodes are **sources** and **roots**. For each source, draw an edge to every entry in its `restsOn` list (a root, or another source). Self-edges are dropped.

### 6.2 Resolve every source to its root set
Walk each source's edges down to the primary evidence it ultimately depends on:

- rests on **root(s)** → those are its roots.
- rests on **other source(s)** → its roots are the *union* of those sources' root sets (recursive).
- rests on **nothing** (names no evidence base):
  - **primary tier** → it joins the position's single **ungrounded-primary pool** — one shared "unnamed first-hand voice" per position. A source that claims original data but names none is unverifiable and indistinguishable from an assertion, so many of them collapse to one voice, exactly as reviews do. **You earn a distinct root by naming a distinct evidence base (a dataset/cohort/experiment), not by claiming the primary tier** — a real study names its own trial/sample and keeps full credit. *(An earlier version gave each ungrounded primary its own root "on benefit of the doubt"; that was the flooding hole — see §9, §10.1.)*
  - **secondary tier** → it joins the position's single **ungrounded-secondary pool** — one shared "review voice" per position (the "collapse all echo to one voice" rule).
  - an **unrecognised** evidence label is treated as secondary (conservative — a novel or opinion label must not mint a free primary root; a case with a genuinely new primary *design* opts it in via its evidence vocabulary).

### 6.3 Collapse cycles — circular corroboration
Following source→source edges can produce a **cycle** (A→B→A, or longer). Compute the **strongly connected components (SCCs)** of the source graph. For each SCC of size > 1:

- The whole component **collapses to one root** — no member adds independence the others lack.
- If the component also reaches a real root (someone in the loop is actually grounded), it collapses *into that root* — redundant, not vacuous.
- If it reaches **no** root and **no** primary source, it is **pure circular corroboration**: it collapses to one placeholder root and **raises a flag** naming the loop.

### 6.4 Count effective independent roots per position
For each position, map every one of its sources to its resolved root(s) and count **each distinct root exactly once, at its strength**:

```
nEff = Σ strength(root_i)     over the position's DISTINCT resolved roots

strength = 1.0   for a real root
         × 0.5   if the root is known only via secondary sources (edge case 5, §8)
         × 0.5   if the root is backed only by weakly-applicable evidence (edge case 6, §8)
         = 1.0   for the one pooled secondary voice, the one pooled unnamed-primary voice,
                 or a collapsed circular loop (each per position, counted once)
```

This is the "effective number of independent looks," as a full-strength-equivalent root count. One root used by everyone → nEff = 1. Ten roots → nEff = 10, whether each is used once or one of them is used a hundred times. **How many sources land on each root is deliberately excluded from this number** — it feeds a separate *concentration* display ("82% of this position's sourcing leans on one root"), which is where a pile-up honestly belongs.

*Design revision, found by adversarially testing the metric against its own claims:* an earlier formulation computed a Herfindahl numbers-equivalent over the per-root **source tallies** (`nEff = 1/Σ share_i²`). That statistic measures how *evenly discussion is spread* across roots, not how many roots exist — and anything reading per-source tallies is movable by adding worthless sources. Two concrete breaks: echoing derivative summaries onto a position's *minority* root evens out the shares and **raises** such an index (flooding fakes independence), and piling junk "support" onto a rival's biggest root skews their shares and **tanks** theirs (poisoning by agreement). Counting each distinct root once makes both attacks inert by construction; the two legitimate ways nEff moves — a genuinely new root, or an upgrade of a halved root (a primary source landing on a review-only root; directly-applicable evidence landing on a weakly-applicable one) — are exactly the ways it *should* move. This invariant is enforced in the test suite, including a randomized never-decreases monotonicity test over incremental source additions.

### 6.5 What's reported
- **By source count** — the naive tally (kept, honestly labelled as naive).
- **By independent evidence** — sized by nEff over resolved roots.
- **The derivation shown**, always: e.g. "25 sources → 7 independent bases (15 secondary summaries counted as 1 voice; two lines of argument share the same underlying dataset)." Each base's one-time strength contribution is part of the breakdown, and the strengths sum to nEff exactly — the number is never a black box.

### 6.6 Scope: independence is orthogonal to per-study quality
nEff answers "how many independent looks support this position," **not** "how good is each look." One decisive randomized trial is a single root; seven independent anecdotes are seven roots. The metric is deliberately an *independence audit* that composes with — and does not replace — per-study quality appraisal (GRADE-style risk-of-bias and similar), and it should be read next to the evidence-type, confidence, and method-class displays, never alone as a settledness score. The only quality-like terms inside nEff are the two root halvings in §6.4, which grade *provenance strength* (how directly the knowledge base actually instantiates a root), not study quality. Weighting roots by elicited quality is an open extension, named rather than smuggled in.

---

## 7. Worked examples (abstract)

- **Echo.** Position has 1 primary study (root D) + 12 narrative summaries, all ungrounded, all secondary. → roots = {D, secondary-pool}. nEff = 2.
- **Echo, well-tagged.** Same, but each summary is tagged as resting on D. → every node resolves to D. nEff = 1 — cleaner, and no tier rule was needed.
- **Resource re-use.** 8 documents, all resting on the same underlying resource C. → nEff = 1.
- **Pure circular corroboration.** A rests on [Source B], B rests on [Source A], no roots underneath. → SCC {A,B}, no root reached → collapses to 1 pool root, **flagged**.
- **Circular but grounded.** A rests on [Source B, Root D]; B rests on [Source A]. → SCC {A,B} reaches D → collapses into D. Redundant, not flagged as vacuous.
- **Chain.** A rests on [Source B]; B rests on [Source C]; C rests on [Root D]. → all resolve to D. A summary-of-a-summary-of-a-study counts as the study.
- **Contested root.** Root D is cited by a source under Position X *and* a source under Position Y. → D is one root under X and one root under Y (independence is a within-position measure). Optional flag: "this root is read both ways."

---

## 8. Edge cases and how each resolves

1. **Ungrounded primary source** (claims original data, names no evidence base) → joins the position's one **unnamed-primary pool**, not its own root. This is the fix for the old "benefit of the doubt" hole: mislabelling ten opinion pieces as primary observations no longer mints ten roots — they collapse to one voice, symmetric with the review pool. A *real* primary study keeps a distinct root by naming its own trial/cohort/sample. *Remaining exposure:* an adversary who **fabricates a named dataset** per source (not merely leaves it blank) still mints roots — that is edge fabrication (§9, §10.3), a labelling-integrity problem the arithmetic can't see, defended by quote verification, the controlled vocabulary, the ensemble vote, and human review, not by the count.
2. **Synthesis pieces (e.g., meta-analyses)** — secondary or primary? If a synthesis produces a genuinely new pooled dataset (re-analyzing raw data), it is primary and that pooled dataset is its root. If it only narrates others' conclusions, it is secondary. The `restsOn` tag decides, not the label "synthesis."
3. **Self-citing group** → shared underlying resource → collapses to 1. Alias resolution stops the same resource being smuggled in under many names.
4. **Long / transitive chains** → resolve to the terminal root.
5. **One source resting on many roots** (a broad synthesis spanning 10 datasets) → contributes those 10 roots. *Weak spot:* a single synthesis could *assert* breadth that isn't independently present elsewhere in the knowledge base. *Proposed handling:* a root supported **only** by secondary sources is marked "asserted, not directly present" and can be down-weighted or shown distinctly.
6. **Weak-population evidence on a narrower question.** A root backed **only** by evidence from a different, less directly applicable population or setting (per a population/context tag) counts at **half weight** when the question at hand is about a different population/context. A root that any directly-applicable source also rests on keeps full weight.
7. **Same root under multiple positions** → counts once per position; optional "contested" flag. Not double-counting — independence is a within-position question.
8. **Cross-position circular corroboration** (A in Position X cites B in Position Y, B cites A) → an SCC spanning positions. Current handling: collapse to one root, contribute to each touched position, and flag. *Weak spot:* the semantics of a cross-position loop are genuinely ambiguous; left as an open problem.
9. **Missing / incomplete `restsOn`** → the tier default kicks in (primary → own root, secondary → pool). Degrades gracefully; never breaks the computation.
10. **Duplicate roots under different names** → relies on root-identity resolution (normalized-string matching plus a learned-alias table). *Weak spot:* a brand-new alias nobody has seen before can slip through until curated.
11. **Self-loop** (A rests on A) → edge dropped; A treated by its other edges / tier default.
12. **Empty position** (0 sources) → nEff 0.
13. **A secondary source that is the only thing citing an otherwise-absent primary study** → the primary study isn't actually present in the knowledge base; only a claim about it is.
14. **Position whose entire support is one cluster of mutually-citing commentary** → nEff 1 plus a circular/secondary flag. The honest answer is "1 independent voice."

---

## 9. Adversarial robustness (attack → defense)

| Attack | What the attacker wants | Defense |
|---|---|---|
| Flood with summary/commentary pieces | Inflate independence with echo | Secondary tier collapses to one voice per position |
| Flood echo onto a *minority* root the position already has | Even out the per-root source shares so a share-based index reads "more independent" | nEff counts each distinct root once (§6.4) — share-shuffling is arithmetic on a number the metric doesn't use |
| Pile junk "support" onto a **rival's** biggest root | Poison by agreement: skew their shares, tank their score | Same — presence, not tallies. The rival's nEff holds; the pile-up surfaces as *their concentration rising*, labelled as a correlation warning, not a lower independence count |
| Re-submit one underlying resource under many names | Fake many independent datasets | Normalized + alias root resolution; concentration *rises*, not falls |
| Mutual citation ring (A↔B↔C↔A) | Manufacture corroboration from nothing | Strongly-connected-component collapse to one root + explicit flag |
| Mislabel opinion as a primary observation (empty `restsOn`) | Mint a free independent root | Ungrounded primaries **pool to one voice per position** (like reviews) — a distinct root requires *naming* a distinct evidence base, not claiming the tier; an unrecognised label defaults to secondary; plus verification pass + relevance gate |
| Label a flood of rehashes "primary", each *naming a fabricated dataset* | Mint many roots past the pool | **Not fully defended** (edge fabrication) — raises the bar (each fake dataset is a checkable, alias-collidable, quote-verified claim) but relies on labelling integrity, not the count; named openly in §10.3 |
| Single summary asserting broad support | Fake breadth | "Root present only via secondary source" mark → that root counts at half |
| Re-submit the same study | Inflate count | Duplicate refusal (same URL, or same title+year) |
| Add an off-topic but real study | Pad a position | Relevance gate refuses it at merge time |

The deep property, stated precisely and enforced by a randomized monotonicity test: **adding a source never lowers any position's nEff, and raises it only by introducing a new root or upgrading an existing root's strength** — both of which *should* raise it. Correlated, derivative, and circular evidence lands on roots already counted, so it moves nEff nowhere; a first wave of ungrounded echo adds at most the two pooled voices (one primary, one secondary), once each. *(Scope of the invariant: it is a theorem about the counting step with entity identity held fixed. The pipeline's entity-resolution can, on a source that teaches a new alias, retroactively **merge** two previously-distinct roots and so lower nEff — a curation event, not evidence loss; the invariant covers the arithmetic, not that step.)* (Not covered by this arithmetic: a source that *fabricates* a root outright — claiming an underlying resource that doesn't actually back it. That is edge fabrication, the dual of the edge omission in §10.3 — a labelling-integrity problem partially caught by per-edge provenance quotes and quote verification, named there rather than hidden behind the invariant.)

---

## 10. Known weak spots (stated openly)

1. **Tier mislabelling.** The whole primary/secondary floor depends on the evidence type being correctly assigned. If a contributor (human or AI) mislabels opinion as an original observation, it earns a root it shouldn't. This is the single biggest lever an adversary — or a careless labeller — has, and the first place to attack the system. *Partial mitigation added since:* labelling can run as an **ensemble** of several models with a deterministic field-level vote, and a genuine split on the position **escalates to a human** (pick a position or drop the paper) rather than a silent guess — so one model's mislabel is out-voted by the others or surfaced for review. What this does *not* fix is a blind spot **shared across models** (or an adversary submitting a deliberately mislabelled source), which the ensemble cannot out-vote; those still rely on the verification pass, the controlled vocabulary, and human review.
2. **Roots asserted only by secondary sources.** The system may credit an underlying resource that no primary source in the knowledge base actually instantiates directly.
3. **Citation data is self-reported.** The system only knows that A rests on B because the labeller said so; it does not independently crawl citation graphs. An adversarial actor can *omit* a derivation edge to hide a dependency and appear more independent than they are — and the dual attack, *fabricating* an edge to an underlying resource that doesn't actually back the source, mints a root the position hasn't earned (§9). A verification pass can catch *false quotes* (including the quote each derivation edge is supposed to carry) but not *missing* edges; diffing declared edges against an external scholarly citation graph is the known fix for the omission half, not yet built.
4. **Cross-position cycles** have genuinely ambiguous semantics (see edge case 8 above).
5. **Alias gaps.** A novel name for an existing resource counts as new until a human curates it.
6. **"One voice" is a modelling choice, not a measurement.** Two truly independent review efforts *might* deserve to count as more than one. The system chose a conservative floor deliberately; this is a stance, not a proven fact.

The project's own documentation states: publishing this list of weak spots alongside the tool is considered part of the epistemically honest approach — the same instinct as documenting known limitations rather than quietly working around them.

---

## 11. Why the designers consider it novel

Most existing tools in this space do one of: (a) count studies/documents; (b) score each document's *internal* quality (e.g. risk-of-bias frameworks); or (c) build a citation graph purely for *influence* (who is cited most). None of them measure **how many independent evidentiary roots actually support a claim**, and none treat **echo, resource re-use, and circular citation as one phenomenon** resolved by collapsing a derivation graph down to its roots. The combination — tier-aware grounding, root-resolution over a derivation graph, strongly-connected-component collapse for circular corroboration, and a strength-weighted distinct-root count with a tested flooding-immunity invariant — is presented as new as a single, deterministic, auditable metric. The honest lineage should be named too: systematic-review craft already distinguishes "studies vs. reports" and manually collapses multiple papers on one trial into one unit within its domain — this is that de-duplication discipline generalized to arbitrary disputes, automated, and made adversarially robust. The claim is novelty of *integration and operationalization*, not a new epistemology.

## 12. Why it is domain-general

The mechanism never looks at subject-matter content. It operates on the abstract ontology above — source, position, root, derivation, tier. The controlled vocabulary (what counts as a "dataset," what evidence types exist) lives in per-question configuration, not in the code. The same engine can, in principle, map a dispute in any empirical field — the vocabulary changes; the algorithm does not. A new domain adds vocabulary, never code.

---

## 13. A second, separate axis: correlated *error*, not just correlated *data*

Sections 1–12 above count distinct underlying resources (roots). If 15 sources rest on 15 *distinct* underlying datasets, the mechanism correctly reports 15 independent bases. But independence-of-data is not the same as independence-against-being-wrong. If all 15 datasets share the same uncontrolled bias or confound, they can all be wrong in the same direction for the same reason. Fifteen distinct datasets, one shared way to fail. The primary metric is blind to this by design — it answers "how many different pieces of data?", not "how many different ways could this be an artifact?"

**The distinction:** replication only buys confidence when the things being replicated can fail for *independent* reasons.

| Dominant error source | Correlated across studies of the same design? | More studies help? |
|---|---|---|
| Chance / sampling variation | No — each instance is its own random draw | Yes |
| Unmeasured confounding (shared lurking variable) | Yes — every instance fails to measure the same thing | No |
| Shared measurement error | Yes | No |
| Surrogate-outcome validity (measuring a stand-in instead of the real outcome of interest) | Yes, across everyone using that surrogate | No |
| Shared instrument/method artifact | Yes, for studies sharing the same instrument | Partially |

So: observational-style studies sharing the same design generally share the same bias risk; designs with independent randomization generally do not share a systematic risk with each other. This is domain-general: whenever two studies would be wrong *for the same reason*, they should count as one look for this purpose, however many distinct datasets they individually rest on.

**The test this must pass:** it must give the *opposite, correct* verdict on cases where a body of evidence is actually well-triangulated — several genuinely *different* method families agreeing, not one design repeated many times. The audit should warn on a single-method-family literature while staying quiet on a genuinely multi-method one. Same lens, opposite verdicts on different inputs, both correct — that is the bar for this becoming a fully trusted metric rather than a thumb on the scale.

**Current implementation status: a warning, not a second weighted score.** For each source, the system derives a "method class" (the correlated-error signature of its design family) from its evidence type via a conservative default table, optionally overridden by a case-specific tag. Per position, it then computes:

- the most common method class, with count and share;
- a Herfindahl numbers-equivalent over method classes;
- a "monoculture" flag: true when at least 3 sources have a recognizable method-risk family, at least 70% of those share one family, and they cover at least 30% of the position's sources.

This ships as a first-screen warning ("N of M sources share the same correlated-error risk family") — deliberately **not** folded into the primary independence count, so that metric's claim stays narrow and defensible.

**Why a fully bounded combined score is deferred.** The tempting formula — add a synthetic "method" root alongside the data roots and run a Herfindahl-style share calculation over the enriched tallies (note: the primary metric deliberately uses no share arithmetic at all, §6.4) — is not safe as a general second number yet. It can, in small or already-concentrated cases, actually *increase* the effective count relative to the primary data-only metric, which breaks the intended invariant that this axis should never suggest *more* independence than the primary metric already found. Until a combination rule is found whose behavior is provably bounded, the system reports the warning-only version rather than a number that could occasionally point the wrong way.

**New weak spots this second axis introduces:**
1. Any free-text tagging of the specific bias/confound would let a contributor invent a unique fake category per source just to dodge collapse — this is only safe as a small, controlled, alias-resolved vocabulary, never free text.
2. The default method-class buckets are coarse by construction; two studies that actually control for *different* confounds still land in one bucket until someone adds a finer tag. This is a deliberate, documented floor.
3. Finer tagging is a more interpretive judgment call than root identity is, and should be visually/textually flagged as such wherever shown, not presented with the same confidence as the primary metric.
4. The default evidence-type → method-class mapping is itself a domain judgment made once per question configuration; a case that mis-sets it will mis-diagnose this axis.
5. This axis must stay logically separate from the "different population/context" half-weighting (edge case 6, §8) — a study with weaker applicability shouldn't be discounted twice for what is really one underlying concern.

---

## 14. System architecture: three layers around one artifact

```
 question → INGESTION → (one source) → STRUCTURE → knowledge-base file → ASSESSMENT → DIFF → report
            find · fetch · label        merge + resolve                    recompute (pure math)
            (search/API + AI)           (deterministic code)                (deterministic code)
```

Two design decisions carry most of the weight:

**(a) The knowledge-base file is the single source of truth.** Ingestion writes updates into it; the metrics are pure functions of it; the rendered report is a snapshot view of it. State lives in exactly one place — a structured file that can be read, diffed, and handed to anyone else.

**(b) Cold-start and incremental update are the same code path.** Building a knowledge base from scratch is just the "add one source" loop run many times; adding a new source later is the identical loop run once. There is no separate batch process that can drift out of sync with the incremental path — which is what makes the knowledge base "living" rather than a one-time snapshot.

### 14.1 Layer 1 — Ingestion (finding and reading sources)
Three sub-steps, only the last of which needs an AI model:

- **Find** candidate documents via a search process — either an AI-driven web search, or a keyless scholarly-index search as a fallback. Filtering is by the dispute's *subject* and *key term*, but **never by which side a document takes** — this keeps both camps of a debate while dropping off-topic material, since filtering by stance would reintroduce the very bias the system is designed to fight.
- **Fetch** the best available text of each document by its stable identifier through open APIs, preferring the full text over an abstract when available, since the full text is typically where funding disclosures and named underlying resources live. The system honestly records how much text it actually retrieved (full / abstract-only / partial) rather than claiming more than it has.
- **Label** the fetched text with an AI model — or, preferably, an **ensemble of several models** run independently and combined by a **deterministic field-level majority vote**: which position does it take, what kind of evidence is it, who funded it, what population/context does it concern, what does it rest on, and a verbatim quote backing each of those judgments. This is the *only* step that uses an AI. Because a single model's labelling is the system's biggest lever (§10.1), running several and voting turns an idiosyncratic call into a *measured* one: each field is decided by majority (a derivation/root edge survives only if at least half the models proposed it, so one model's spurious dataset or citation link is dropped), and the per-field agreement is recorded on the source. Every extracted quote is then spot-checked against the text that was actually fetched; a mismatch on a full-text source is a real flag, while the same mismatch on an abstract-only source is expected noise (the claim may be true but drawn from body text never retrieved) — these two situations are never conflated.
- **Escalate genuine disagreement, don't average it.** When the ensemble reaches no majority on the *position* — only a plurality or a tie — the source is **not** silently forced under a guessed label. It is parked in a **review queue carried inside the knowledge-base file itself** (so it persists, travels with the case, and resumes like everything else), and the person running ingestion is shown the abstract and each model's proposed position and asked to **pick a position or drop the paper**. Nothing in the queue counts toward any metric until a human resolves it. When the split is mild enough that a majority *did* form, the source merges under the winning label but is **flagged** — surfaced in a warning and marked in the per-source table — so a curator can still re-open it. This is the concrete operationalization of "labelling is the load-bearing step": model disagreement is quantified, and *real* disagreement is handed to a human rather than laundered into false confidence.

### 14.2 Layer 2 — Structure (merging into the knowledge base)
A small piece of **deterministic, plain code** folds each labelled source into the knowledge base. "Deterministic" means: same input → same output, every time, with no model randomness involved. This is where entity resolution happens (is this the same underlying resource already recorded, or a genuinely new one?). The governing rule is **"the AI proposes, the code disposes"**: the AI suggests links by name; reproducible string-matching code decides whether to reuse an existing entity or create a new one.

Defenses built into this layer: duplicate refusal (same URL, or same title+year even under a different URL), alias resolution (the same resource submitted under different names collapses to one entity, so nobody can fake independence by renaming), and off-topic refusal (a real but irrelevant document is dropped rather than padding a position).

### 14.3 Layer 3 — Assessment (the metrics)
A set of **pure functions** — the only place any number is computed. Given the knowledge base, they recompute every metric from scratch. Because they are ordinary deterministic math over a file (not an AI call), results are reproducible: anyone can re-run them and get the same answer.

The metrics computed:

- **Distribution** — naive share of *sources* per position, and, alongside it, the independence-weighted version (each position resized by its effective independent bases). Seeing a position contract between the two views is the central point made visible.
- **Funding skew** — which position the *interested* money favors, using a fixed set of categories (government, nonprofit, academic, industry, advocacy, undisclosed), defaulting to "undisclosed" rather than assuming independence when a source is silent about funding, and reporting how much of the evidence base doesn't disclose funding at all.
- **Independence / concentration** — the core metric described in §6 above.
- **Method-class monoculture** — the secondary warning axis described in §13.
- **Divergence / cruxes** — a factor-by-position grid; a factor becomes a "crux" once its weighting spreads widely across positions, which localizes *where* camps actually disagree instead of implying they disagree on everything. Cruxes emerge only once enough positions have weighed in on a given factor, so the crux list grows honestly as the knowledge base grows. Each factor expands to show, per position, the sources that weigh it and the **verbatim quote each camp gives** — so a crux is not just a shaded cell but a click-through to the actual competing evidence, with the same per-quote verification badge used elsewhere.
- **Blindspots** — evidence types or populations/contexts present elsewhere in the dispute but absent from a given position's own sources, computed only over evidence types that appear at least twice elsewhere (so one source's idiosyncratic detail isn't flagged as everyone else's blindspot).

---

## 15. Data model (building blocks)

A knowledge base is made of a few entity types:

- **Positions** — the camps / stances on the question.
- **Roots (datasets/resources)** — the underlying primary evidence (a specific study population, experiment, or data collection effort). This is what powers the independence audit.
- **Sources** — the individual documents. Each is tagged with its position, evidence type, funding category, applicable population/context, and what it rests on — every tag backed by a quote from the source.
- **Factors** — the dimensions of the debate (the specific considerations camps weigh differently or similarly). Each factor records how strongly *each position* weighs it.

---

## 16. How the system is used

Three interchangeable surfaces reach the same underlying engine:

**(a) A shared web portal** (multi-user, no local setup, no API key required to browse or contribute). A contributor finds documents via free search or pastes a URL directly; the server fetches the best available text and bundles it into a single file; the contributor uploads that file to their own AI chat client to label it, then pastes the labelled result back into the portal. **No API key ever touches the server** — the AI labelling step happens in the contributor's own chat client, and folding the result into the knowledge base is a purely deterministic merge. This sidesteps any "would you trust a website with your API key?" concern entirely, and keeps the hosted service cheap with no abuse surface for expensive AI calls. An admin-gated **manage** view lets a moderator resolve any parked labelling-disagreement item in place — pick the position or drop the paper — without leaving the portal.

**(b) A local console** for users with their own API key — runs the whole pipeline automatically (find, fetch, label, merge) and can pull a question from the shared portal, work on it locally, and push the result back, with version checks so two contributors don't overwrite each other's work. It surfaces a **"needs your review"** panel for the ensemble-disagreement queue described in §14.1, so a split label is resolved by a human before it ever enters a metric.

**(c) A command line**, fully scriptable, including cleanup tools for merging and renaming duplicate entities that a string-matching pass didn't catch on its own.

A guiding principle throughout: finding and reading sources is free and keyless (open APIs); only the labelling step needs an AI model of any kind, and the design is explicitly provider-agnostic (works with several different AI providers — meaning any model can do the labelling, not that different models produce identical labels; see §17).

---

## 17. Non-obvious design decisions worth naming

- **"Propose, then deterministically resolve."** The AI is powerful but unpredictable, so it is confined to *proposing* (read this document, suggest labels for it). Every reproducible part — which underlying resource, which counts, every metric — is computed by deterministic code that never depends on model randomness. The precise claim: **everything downstream of the labels is reproducible regardless of which AI model (or none) produced them.** The labels themselves can vary between models — position, tier, and derivation-edge assignments are judgment calls — so model-invariance of *conclusions* is not claimed. That variance is now **measured and acted on rather than left as future work**: labelling can run as an ensemble of several models over the same source, combined by a deterministic field-level majority vote, with per-field agreement recorded on each source (§14.1). Where the models agree, the label is more trustworthy than any single model's; where they split on the position, the source is escalated to a human — pick a position or drop the paper — instead of being averaged into a guess. Labelling remains the one load-bearing AI step and the system's honestly-stated biggest lever (§10.1); the ensemble narrows the lever, it does not remove a blind spot shared across models.
- **The hosted server holds no API key and does no AI work.** Because merging is fully deterministic, the shared service is cheap, safe, and carries no risk of expensive-AI-call abuse.
- **Full source text, not just abstracts, when available.** Abstracts rarely contain funding disclosures or name the underlying datasets a study rests on; the system specifically seeks out full text when openly available so those signals are actually captured.
- **Funding identification has multiple fallback tiers** before landing on "undisclosed" — it reports the disclosure gap honestly rather than assuming a silent document is independent.
- **Duplicate and alias defenses.** The same document can't be added twice; the same underlying resource submitted under different names is matched to one entity, closing an obvious gaming vector.

---

## 18. Honest limitations, stated on purpose

- **Paraphrase collisions.** String-matching can resolve superficial naming differences ("the X study" vs. its formal name) via a learned-alias table, but not genuine paraphrase where two very differently worded descriptions refer to the same underlying resource. Human curation tools exist to fix these after the fact; full automation would need embedding-based matching, planned as a future step.
- **Curated factor weights** are the softest input — how strongly each camp weighs each consideration is a human/AI judgment call, not a mechanical count. The mechanical parts (counts, resource identities, funding category, concentration) are what actually resist gaming.
- **Sparse factor grid.** A source only records weights for its own position, and only on the considerations it explicitly addresses; the grid fills in only as sources across camps happen to address the same considerations — a deliberate trade favoring determinism and provenance over completeness.
- **Method-class monoculture is a warning, not yet a bounded second score** (see §13) — the natural next step, a single number that discounts independence for shared correlated error the way the primary metric discounts for shared datasets, does not yet have a demonstrably safe general formula; shipping an honest warning instead of a number that could occasionally mislead was the deliberate choice.
- **Quote verification depends on what text was actually fetched.** A quote can only be checked against text the system actually retrieved; sources added through the keyless-portal paste-back flow (which never fetches server-side) are marked as unverified rather than given a guessed verdict.
- **Self-reported citation edges.** The independence engine only sees a dependency between sources if a labeller recorded it; it does not independently crawl citation graphs. An adversarial contributor who omits an edge can look more independent than they actually are — a known, stated gap rather than a hidden one.

---

## 19. Summary framing

The system does not claim to decide who is right in a dispute. It claims something narrower: that **counting sources is the wrong primitive for aggregating a contested factual question**, and that a small set of computable, gaming-resistant metrics — independent-evidence-bases, funding skew, crux localization, blindspots, and method-class monoculture — redirect a reader's scrutiny toward the places that actually should move their conclusion.

---

## 20. Questions for review

Areas where outside critique would be most useful:

1. *(Resolved since the first review round, which correctly flagged the original Herfindahl-over-source-tallies statistic as gameable.)* The effective count is now a strength-weighted distinct-root count with a tested never-decreases invariant (§6.4). The successor question: are the two ×0.5 root halvings (secondary-only, weakly-applicable-only) the right magnitudes, and is there a principled elicitation for root strengths rather than two hard-coded constants?
2. Is there a safe, provably-bounded way to combine the primary independence count with the method-class (correlated-error) axis into one number, given that the naive combination can push the effective count *up* in small or already-concentrated cases (§13)?
3. How real is the self-reported-citation-edge gap (§10.3, §18) in practice — is there a lightweight, mostly-automated way to at least partially verify derivation edges against actual citation data, without reintroducing non-determinism?
4. Is the "one shared voice" treatment of ungrounded secondary sources (§6.2) too conservative, too generous, or about right — and is there a principled way to let genuinely independent secondary efforts count as more than one voice without reopening the echo-inflation problem?
5. Are there failure modes or gaming strategies against this mechanism that are not already named in §9 and §10?
6. *(New since the ensemble landed.)* Is a **field-level majority vote across models** the right combiner for labelling, and is the escalation threshold right — hand a *position* split to a human, merge-but-flag a milder split? Or does an ensemble mainly launder *correlated* model errors (all trained on similar data) into unwarranted confidence, so that the agreement signal it reports is weaker than it looks?
