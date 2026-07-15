# Ground Knowledge
### Confirmed-root coverage with separate quality/bias audits — a spec for compounding, adversarially robust knowledge bases for research disputes

*FLF "Lab Leaks, Black Holes, and Eggs" Epistemic Case Study Competition. Live at
[groundknowledge.org](https://groundknowledge.org). Read with the prototype in this repo:
`README.md` to run it, `MECHANISM.md` for the independence engine in depth, `WORKFLOW.md` to
operate it, `SCHEMA.md` for the data model. This document is the method.*

---

## 1. The insight, stated once

Ground News aggregates the news: it labels each outlet's lean, shows the distribution of
coverage, and flags "blindspots" — what one side isn't covering. It is deliberately **neutral
on who is right**, which is the correct stance for political framing.

Port that interface to a *research* dispute and the neutrality becomes a bug. In a research
dispute some positions genuinely are better supported, so naive source-counting rewards the
loud, the numerous, and the industry-funded over the correct. That is **false balance** — the
opposite of good epistemics.

So our one design commitment, from which everything else follows:

> **Aggregate, but map confirmed evidence-root coverage and audit quality separately instead of
> counting sources.** Sources landing on an already represented root add no coverage; unsupported
> rehashes collapse to a visible zero-credit marker.

Everything below is in service of that inversion.

---

## 2. What it produces, and what it adds to the baseline

The honest baseline for any entry is *"a careful analyst with a deep-research tool on the same
sub-question."* Deep research is very good and improving. It produces **one prose answer, once.**

We produce a different kind of object:

| | Deep-research summary | Ground Knowledge |
|---|---|---|
| Output | prose, for one reader, one time | a **structured JSON artifact** another team forks and extends |
| Numbers | asserted in text | each recomputed by one **legible function**; inspectable |
| Gaming | a flood of weak papers reads as "growing consensus" | sources on an existing root add zero; unsupported floods and loops add zero; unreviewed edges cannot launder a confirmed root into another camp |
| Updating | re-run the whole query | add one source → **O(new) ingest**, deterministic recompute, **diff of what changed** |
| Audit | trust the narrator | position, dataset-dependency, and factor-weight claims request **provenance quotes**; the metric is a pure function you can re-run |

The value isn't a better paragraph. It's a knowledge base that **compounds**, an audit that
**holds under motivated reading**, and a record of **what each new source did to the picture.**

---

## 3. Architecture: three layers around one artifact

We adopt FLF's own decomposition — **Ingestion → Structure → Assessment** — and add the
property FLF asks for explicitly ("living knowledge bases, not merely snapshots… track how the
structure evolves over time").

```
 question ─► INGESTION ─► (delta) ─► STRUCTURE ─► cases/<id>.kb.json ─► ASSESSMENT ─► DIFF ─► viewer
            search→fetch→label       merge+resolve      the artifact       recompute (pure)
            (API · API · LLM)        (deterministic)    you own & share    (deterministic)
```

Two design decisions carry most of the weight:

**(a) The knowledge base is the source of truth; everything else is a producer or consumer of
it.** Ingestion writes deltas into it; the metrics are pure functions of it; the viewer is a
*baked snapshot* of it. State lives in exactly one place — a single JSON file a judge can read,
diff, and hand to another team.

**(b) Cold-start and incremental update are the *same code path*.** A cold start is the update
loop run N times over discovered sources; an update is the same loop run once. `ingest`/`add` is
the only mutation. There is no separate batch build to drift out of sync with the incremental
path — which is precisely what makes the base "living" rather than a snapshot.

**Ingestion is three steps, and only the last needs a model.** *Finding* sources is **AI-driven by
default** — the model searches the web for real, citable sources, and is told what's already in the
KB so it returns *new* ones (a keyless OpenAlex scholarly search is the fallback, `ingest/search.py`).
*Reading* a source resolves its DOI/PMID/arXiv id back through open APIs (OpenAlex → arXiv →
Semantic Scholar → Europe PMC, `ingest/extract.py`), preferring the **full open-access PDF** when
one exists so the funding/COI statement and named cohorts in the methods are captured — deterministic
and free of publisher scraping. Only *labelling* the fetched text uses an LLM, and the model is the
contributor's choice: **Anthropic, OpenAI, DeepSeek, Mistral, Groq, Gemini, or OpenRouter** (one
stdlib code path, since all but Anthropic speak the OpenAI protocol). The labeller judges, in order:
**relevance** (off-topic sources are refused at merge, like duplicates), then position, evidence
type, funding, population, the datasets the source rests on (or the *other sources* it derives from).
It requests a verbatim quote for the position, each dataset edge, and each factor weight; source→source
citation edges need not carry one. So cold start works with **no LLM key** up to the
labelling step, and AI web search / deep research is an Anthropic feature while every provider can
label fetched text. The OpenAlex fallback keeps relevance high with two *stance-neutral* filters
(subject-topic cluster + exposure term) so a statin trial sharing "cardiovascular risk" is dropped
while *both* sides are kept.

**The "propose, then deterministically resolve" contract.** The LLM is powerful but
non-deterministic, so we confine it to *proposing*: it reads one fetched source and emits a delta
that links to existing entity ids *or* marks something `"NEW:<label>"`. Deterministic code then
*disposes* — resolving links by normalized-string + alias matching. The reproducible, auditable
parts (which datasets, which positions, counts, metrics) never depend on model temperature; merge,
metrics, and viewer are deterministic and offline. The precise claim: **everything downstream of
the labels is reproducible regardless of which model — or no model — produced them.** The labels
themselves can vary between models (position, tier, and `restsOn` assignments are judgment calls),
and that variance is now **measured and acted on**: labelling can run as an **ensemble** of several
models over the same source, combined by a deterministic field-level majority vote
(`ingest/ensemble.py`), with per-field agreement recorded on each source. A `restsOn` edge survives
only if a **strict majority** (> half) of distinct models proposed it; a genuine split on the
*position or primary/secondary evidence tier* is **not** merged under a
guessed label — it is queued in the KB for a human to resolve (pick a position or drop the paper;
`engine/review.py`), and pending items count toward no metric. Labelling stays the one load-bearing
AI step and the system's honestly-stated biggest lever (MECHANISM.md §8.1); the ensemble narrows it,
it does not erase a blind spot shared across models.

---

## 4. The assessment metrics — what each computes, and what it resists

Every metric is a pure function over the KB (`engine/assess.py`). Four of them, each chosen to
serve the thesis:

**Distribution — naive source volume *and* confirmed-root coverage.** Two views shown together.
The first is the naive aggregator's view (share of *sources* per position). The second re-sizes
each position by its **confirmed-root coverage** — each distinct admitted *resolved root* counted
once at its declared credit (`weighted_distribution`; see the root engine below), so sources sharing
a dataset collapse, ungrounded reviews pool into a zero-credit marker, and
an ungrounded citation loop is flagged but contributes zero. The weighted bar therefore exposes how
far raw source volume exceeds represented root coverage. It is not a quality or truth score. **Funding pattern** then complicates it further:
where does *interested* money (Industry or Advocacy) cluster? On the real eggs case it is tied:
two industry-funded meta-analyses back "No association," while two industry-funded trials back the
context-dependent camp. The tool reports both instead of picking a winner by position order. Funding
is a **closed vocabulary** (Government/public,
Nonprofit/charity, Academic/institutional, Industry, Advocacy, Undisclosed) that **defaults to
Undisclosed, never "independent"** — so the metric also reports how much of a case rests on
sources that don't disclose funding, surfacing the data gap instead of fabricating independence.

**Divergence / cruxes** (intellectual lineage: Heuer's *Analysis of Competing Hypotheses*). A
factors × positions matrix distinguishes: a cross-camp crux (spread ≥2), a shared pivot (two camps
rate it high), a one-sided high assumption, a high factor a camp leaves unanswered, and a milder
contested weight. The tight headline `isCrux` is only cross-camp/shared-pivot; `loadBearing` also
includes one-sided and unanswered factors. On black holes the current artifact has one headline
crux plus two one-sided load-bearing factors — not an inflated claim of three headline cruxes.

**Confirmed-root coverage — the anti-false-balance core** (the full mechanism is `engine/roots.py` /
[`MECHANISM.md`](MECHANISM.md)). Echo, cohort re-use, and circular corroboration are one disease —
*a source that adds no new root* — so the metric counts admitted evidentiary-root credit per
position, not sources. It follows only support edges with a verified specific dependency quote or
explicit curator/migration admission; unadmitted links remain visible at zero. Then:
- **shared datasets** collapse to one root (eight papers off one cohort = one look);
- **ungrounded sources that name no evidence base** collapse to a single zero-credit marker per position —
  one for reviews/commentary/untagged meta-analyses, and one for **primaries that name no data**
  (an original study earns a distinct root only by *naming* its trial/cohort/sample, not by claiming
  the tier — this closes the "label your echo Observational" flooding hole); an unrecognised evidence
  label defaults to secondary;
- **strongly-connected citation cycles** (A→B→A with no grounding) become one visible,
  zero-strength marker and raise a **circular-corroboration flag**;
- a dataset known **only via a review**, or a root backed **only by animal / in-vitro** sources,
  counts at **half** (weak evidence, shown distinctly).

The coverage count (`nEff`) counts **each distinct admitted resolved root once, at its credit** — never
how many sources landed on it — and the audit **shows its work**: each position is broken down into
its bases (each base's one-time `strength` contribution sums to `nEff` exactly), with the
collapsed-source count surfaced separately. The fixed-graph invariant, enforced by a randomized
test: **adding a source with only outgoing edges cannot lower `nEff`; only a genuinely new root or
grounding upgrade can raise it.** A graph correction can legitimately lower it by merging aliases
or revealing a pure citation cycle. Flooding with correlated or derivative evidence moves nothing;
junk "support" aimed at a rival moves nothing of theirs either — the pile-up surfaces only as
*concentration*, honestly labelled. This is the metric that refuses to be
flooded, and it produces differing coverage diagnostics (e.g. on the real COVID-origin case one
camp's source list reaches several admitted primary roots while other listed sources collapse onto
fewer roots — invisible to a source count). That difference is not itself a verdict on which camp
is true or best supported.

One scope line, stated where the number is defined rather than discovered by a skeptical reader:
**root coverage is deliberately orthogonal to per-study quality and correctness.** `nEff` answers
"which admitted roots are represented under this position?", not "how strong is the case?" — one
decisive RCT is a single root and seven weak anecdotes can be seven. It composes with, and does not replace,
GRADE-style per-study quality appraisal; read it next to the evidence-type, confidence, and method
audits, never as a settledness score. The two 0.5 discounts are declared heuristics, not calibrated
evidence weights.

**Blindspots.** Evidence types and populations present elsewhere in the case but absent from a
position's own sources — operationalising FLF's "surface what's missing." Two data-quality
guards make this meaningful at scale: it computes over a *controlled vocabulary* (§8), and a type
counts as "present" only if **≥2 sources** use it, so one source's hyper-specific population isn't
flagged as every other position's blindspot.

---

## 5. The five hard problems, and the tradeoffs we accept

This is the part to read for the method. None are solved by the prototype's seed data; they are
structural and named honestly.

1. **Entity resolution on merge.** Is "the Nurses' Health Study" the existing `ds_nhs` or new?
   Handled by normalized-string + learned-alias matching in `engine/merge.py`. *Tradeoff:* robust
   to casing/aliases, **not** to paraphrase ("Wuhan market dataset" vs "Huanan seafood market").
   We chose deterministic string matching first because reproducibility matters more than recall
   at this layer — a wrong silent merge corrupts every downstream metric. Two mitigations close
   the gap without giving up determinism: strong **prompt discipline** (reuse aggressively; a
   mechanism is a factor not a position; `restsOn` is a named cohort, never "the literature"),
   which cut a 31-source test case from 6 positions / 24 datasets to 3 / 10; and explicit
   **curation ops** (`engine/curate.py`: merge, rename, tidy, plus lexical/acronym duplicate
   suggestions) exposed in the CLI and UI. Optional embedding suggestions (`dups --embed`) surface
   paraphrases a string match misses but never auto-merge. Confirmation blocks a likely duplicate
   unless the curator records an explicit override.

2. **Determinism & cost (scalability).** All assessment is pure counting over the KB. Ingestion is
   **O(new sources)**; recompute is **O(whole KB) but cheap**. Adding the 1000th source never
   re-reasons over the first 999. That is the scalability story: it gets better with more
   contributors and compute, not bottlenecked on re-doing prior work.

3. **Provenance on load-bearing claims.** Position, each dataset-dependency edge, and factor weight
   carry a quote + extraction-confidence when produced by the current fetch/label path. The quote is
   checked against the exact model-visible text. Source-citation edges and categorical API metadata
   are not falsely claimed to be quote-backed. *Tradeoff:* extraction confidence is the model's
   self-report; it bounds, but does not eliminate, extraction error.

4. **Open schema — interoperability vs nuance** (a tension FLF names explicitly). A small fixed
   *core* the metrics operate on (source, position, dataset, factor, edge) plus *open
   vocabularies* (evidence, funding, population) as tags. New domains add vocabulary, not code —
   which is why one engine serves eggs, COVID, and black holes unchanged. *Tradeoff:* fully open
   vocabularies degrade the blindspot metric; a light controlled vocabulary is the working
   compromise (§8).

5. **Adversarial robustness = the thesis, enforced at ingestion + assessment.** Concrete defences
   live in `engine/merge.py` (duplicate / alias / off-topic refusal) and `engine/roots.py` (echo,
   cohort, and circular-corroboration collapse) — see §8 for what they do *and* do not cover.

---

## 6. Generalization: one engine, three differently-shaped cases

FLF chose three cases with deliberately different profiles; a general tool must handle all three
with **only the data changing.** It does:

- **Eggs — contested, mundane, malformed question** (20 sources, 3 camps). The curator-authored
  structure makes two auditable patterns visible: interested funding is **tied** between the
  no-association camp (two industry-funded meta-analyses) and context-dependent camp (two
  industry-funded trials), and the shared-cohort collapse — the *No
  increased-risk* camp lists 9 sources and has **5.0 confirmed-root coverage** after cohort reuse is
  collapsed. The subgroup crux (diabetics/hyper-responders)
  flags that "are eggs healthy?" is mis-posed: the answer is "for whom?"

- **COVID — live, contested, expertise-heavy** (26 sources, 3 camps). The root audit tells
  the honest story a source count hides: current source→coverage values are **13→5.0, 7→3.5,
  6→3.0**. The **six Bayesian re-analyses (Rootclaim, Weissman, Miller, …) rest on substantially shared
  underlying evidence** — so they count as re-analysis, not six new roots, the "23 orders of
  magnitude from one evidence base" made visible. Cruxes: prior on lab accidents, furin site,
  ascertainment bias.

- **Black holes — essentially settled** (15 sources, 2 camps). The 11 "safe" sources have **4.0
  confirmed-root coverage**: production impossibility, Hawking evaporation, slow accretion, and the
  cosmic-ray/dense-star observation. Four residual-concern sources have **2.0**. The count maps
  layers; it does not independently establish that the conclusion is correct.

Same `assess()`; same renderer; three lines of `build`. That is the generalization evidence.

---

## 7. Scalability, compounding, shareability

- **Scales with better models** (ingestion/extraction quality), **more compute** (broader
  discovery), and **more contributors**. Entity/source context in model prompts is bounded by
  configurable caps and deterministic lexical retrieval rather than growing with the whole KB.
  Public paste-back sources are queued; reviewed/local updates use the same merge. Human review is
  deliberately concentrated at confirmation, alias resolution, and ensemble disagreements; it is a
  real integrity bottleneck, not hidden.
- **Bounds resource use:** portal bodies, fetch batches, extracted PDFs, request threads, expensive
  fetches, and per-IP mutation rates all have configurable ceilings. Question cards are read from
  indexed summary columns rather than reparsing every KB. This removes obvious denial-of-service and
  list-page scaling failures, but is operational hardening rather than a large-corpus benchmark.
- **Does not lose concurrent work:** the hosted store keeps a server revision separate from the KB's
  semantic version. Every write advances it, stale writers receive a conflict, and each KB update and
  its contribution record commit in one database transaction.
- **Compounds:** the artifact is a JSON file another team forks and keeps growing; nothing is
  locked in the UI. The `Changes` tab and append-only log make the evolution legible.
- **Shareable two ways:** `viewer/index.html` is self-contained (double-click, no server) for a
  reader; `cases/<id>.kb.json` is the portable artifact for an extender.
- **No drift:** because the metrics are computed once in Python and the viewer only renders, what
  the pipeline concludes and what a reader sees are guaranteed identical.

---

## 8. Adversarial robustness — failure modes named and bounded

**Defended (verified in the prototype, with tests in `tests/test_independence.py`):**
- *Flooding the zone with echo.* Sources landing on an existing root add zero. A pile of otherwise
  ungrounded reviews / commentary / untagged meta-analyses collapse to one visible marker with
  **zero coverage credit**. Re-used cohorts collapse exactly.
- *Echo relabelled "primary".* The same flood dressed as original observations with an empty
  `restsOn` no longer mints a root each — **ungrounded primaries pool at zero per position**
  too, so a distinct root requires a *specific named and admitted* evidence base, not a claimed tier
  (`test_echo_as_primary_flood_cannot_inflate_independence`). An unrecognised evidence label
  defaults to secondary for the same reason. Fabricating distinct *named* datasets on the unverified
  path is quarantined at zero; the remaining semantic attack is a fetched or curator-confirmed false
  identity, bounded by the per-edge identity and duplicate gates below.
- *Circular corroboration.* Sources whose only support is citing one another become a visible,
  strongly-connected cycle, contribute **zero**, and are flagged.
- *Confirmed-root support laundering.* Root identity and support-edge admission are separate. A new
  source cannot attach all of another camp's already confirmed roots without edge-specific review;
  the eighth benchmark attack executes this case.
- *Forged curator admission.* A model cannot make its proposed edge trusted by emitting an
  `admission` object, even on the locally fetched path. Delta validation rejects it generally, the
  trusted fetch boundary strips it before merge, and the ninth benchmark attack executes the path.
- *Alias-splitting.* Exact and learned aliases resolve deterministically. Automatically verified
  lexical lookalikes admit at most one root and expose the collision; curator confirmation blocks
  lexical/acronym duplicates unless an override reason is recorded. Optional embeddings surface
  further semantic candidates but do not auto-merge them.
- *Duplicate submission.* Same url, or same **title+year even under a different url** (the same paper
  via PMC vs DOI vs publisher), is refused — a camp can't be inflated by re-submitting a study.
- *Off-topic padding.* A real but tangential source is judged at labelling time and refused at merge,
  so it never pads a position.
- *Tier laundering.* A meta-analysis or review earns coverage only through **named, admitted**
  evidence bases (then it collapses into them); an untagged one is a zero-credit assertion marker.
- *Animal evidence passed off as human.* A root backed only by animal / in-vitro sources counts at
  half on a clinical question.

**Partially addressed since first draft:**
- *Paraphrase-level entity collision* — a determined actor can still propose a novel name. Optional
  embedding suggestions and the confirmation-time duplicate gate reduce this risk, but the semantic
  decision remains human; the metric deliberately does not auto-merge uncertain entities.
- *Advocacy / undisclosed funding* — the `funding` axis is no longer binary. It is a closed
  vocabulary (Industry, Advocacy, Government/public, Nonprofit/charity, Academic/institutional,
  Undisclosed) that captures *advocacy* stake (e.g. a dairy council) separately, and **defaults
  to Undisclosed rather than independent** — so the skew metric reports the disclosure gap instead
  of asserting independence it can't verify. (It still can't read a funder's true intent from an
  abstract that omits the funding statement — those land in Undisclosed, honestly.)

**Not defended (stated plainly):**
- *Self-reported citation edges* — the independence engine only sees a dependency if the labeller
  recorded it, so an actor who **omits** a `src:` edge can look more independent than they are. We
  state this in [`MECHANISM.md`](MECHANISM.md) §8 rather than paper over it. Quote verification is
  implemented for the claims the prompt requests; comparing stored dependencies with an external
  citation graph is the complementary defence that remains future work.
- *Tier mislabelling* — the primary/secondary floor depends on the evidence type being right. Calling
  opinion "Observational" no longer *mints a root* on its own (an ungrounded primary now pools, §4),
  but it can still deny the review-collapse a genuine review deserves. A **fabricated named dataset**
  remains visible but contributes zero confirmed nEff until a fetched dependency quote verifies it
  or a curator confirms it; false confirmation remains a semantic integrity risk.
  Partial defences (controlled vocab, relevance gate, funding-defaults-to-Undisclosed, provisional
  root admission, and an **ensemble vote plus human review** that out-votes or escalates a single
  model's mislabel) exist; not airtight against
  a blind spot shared across models or a deliberately mislabelled submission.
- *Curated factor weights* — positions' factor weightings are a human/LLM summary, not mechanical;
  they are the softest input. The *mechanical* parts (counts, datasets, funding category, the
  independence resolution) are what resist gaming.

Naming these is the point: the metrics are **heuristics that redirect scrutiny**, not oracles.

---

## 9. What we are *not* claiming

We are not claiming the tool decides who is right. It claims something narrower and, we think,
more useful: that **counting sources is the wrong primitive for a research dispute**, and that a
small set of computable, gaming-resistant metrics — independent-evidence-bases, funding skew, crux
localisation, blindspots — re-aim a reader's scrutiny at the places that actually move the
conclusion. The seed weights are illustrative; the architecture, the metrics, and the eggs
evidence base are real and runnable.

---

## 10. Artifacts in this repo

| file | what |
|---|---|
| `engine/assess.py` | the metrics — every number the tool reports |
| `engine/roots.py` | the independence engine — tier-aware root resolution + circular-corroboration detection ([`MECHANISM.md`](MECHANISM.md)) |
| `engine/gaps.py` | gap analysis — where a position's evidence is thin — that steers gap-driven deep search |
| `engine/merge.py` | deterministic merge + entity resolution + duplicate / alias / off-topic defences + source→source edges |
| `engine/curate.py` | curation ops — merge / rename / tidy duplicates + duplicate suggester |
| `ingest/extract.py` | fetch text by identifier (OpenAlex / arXiv / Semantic Scholar / Europe PMC); full open-access PDF when available |
| `ingest/llm.py` | model-agnostic LLM access — Anthropic / OpenAI / DeepSeek / Mistral / Groq / Gemini / OpenRouter; single-model or a multi-model **ensemble** |
| `ingest/ensemble.py` | deterministic field-level majority vote combining several models' labels into one delta + a per-source agreement report |
| `engine/review.py` | human-in-the-loop queue: a genuine ensemble disagreement is parked in the KB for a human to resolve (pick a position / drop the paper), counted in no metric |
| `ingest/search.py` + `prompts/` | keyless OpenAlex fallback search; the labelling / discovery / research prompts |
| `cli.py` | `new · init · show · assess · gaps · deepen · add · build · ingest · ingest-batch · discover · research · harvest · merge · rename · tidy · dups · ui · pull · push · questions · import-citations · export` |
| `app/` | the deployed keyless **portal** ([groundknowledge.org](https://groundknowledge.org)) + a portable store (sqlite local / Postgres prod) the CLI pushes & pulls to |
| `ui/` | the local web console (`python cli.py ui`): find → fetch → label → import, **gap-driven deepen**, Curate, and pull/push |
| `cases/*.kb.json` | five local, url-cited KBs: eggs, COVID, black holes, alcohol, and video games |
| `viewer/index.html` | self-contained, render-only viewer (Coverage · Divergence · Independence · Changes) |
| `MECHANISM.md` / `SCHEMA.md` / `QUICKSTART.md` / `WORKFLOW.md` | the independence mechanism / data model / step-by-step tasks / operator runbook |

Run `python cli.py show cases/eggs.kb.json`, then `python cli.py build cases/eggs.kb.json` and open
the viewer — or just visit [groundknowledge.org](https://groundknowledge.org). Total time to a
running local demo on a fresh machine: about a minute, no dependencies.
