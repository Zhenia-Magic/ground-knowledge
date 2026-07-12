# Ground Knowledge — submission

*A living, recomputing knowledge base that weights research disputes by **independent evidence**, not source count — and is hardened against being gamed by volume, echo, or circular citation.*

**Live, no setup, no API key → [groundknowledge.org](https://groundknowledge.org)**
**Repo → https://github.com/Zhenia-Magic/ground-knowledge**

---

## Judge, start here (10 minutes)

1. **See the thesis in 60 seconds.** Run the reproducible benchmark from a clean clone:
   ```
   python eval/run_benchmark.py
   ```
   It prints, per case: *structure recall* against a hand-written gold, the *collapse* (raw source
   count → independent bases), the *crux taxonomy*, and an *executed* adversarial-robustness contract.
   Or run `python cli.py demo` for the same plus a per-case assessment and links to the live viewer.

2. **Read three worked cases** (open on the live site or `python cli.py assess cases/<case>.kb.json`):
   - **COVID** — `cases/covid.kb.json` — [origin of SARS-CoV-2](https://groundknowledge.org/q/ac81b4cae8d0). Watch the zoonotic position's 15 sources collapse to ~5 independent bases; the shared Chinese market dataset, overlapping author group, and recycled advocacy documents fold into single roots.
   - **Eggs** — `cases/eggs.kb.json` — [do eggs raise CVD risk?](https://groundknowledge.org/q/04329878656c). The literature reduces to ~4–5 genuinely distinct strands; industry funding is surfaced as a crux.
   - **Black holes** — `cases/blackholes.kb.json` — [could the LHC destroy Earth?](https://groundknowledge.org/q/c6c6ad01ec11). A near-settled question where the "No risk" position rests on **four distinct theoretical safety arguments** modelled as first-class `argument`/`observation` roots (production impossibility, Hawking evaporation, accretion timescale, empirical dense-star bound) — so its independence count reflects the *layered* safety case, not a single empirical dataset. The *residual* concern (the safety argument itself might be wrong) is surfaced as a one-sided load-bearing crux.

3. **Read the two core functions** — this is a ≤2-page algorithm, not a black box:
   - `engine/roots.py` → `resolve()` — resolves every source to the primary evidentiary **roots** it depends on, collapses echo / cohort-reuse / circular citation, and admits a root to the count only when it is **confirmed per edge**.
   - `engine/assess.py` → `independence()` and `cruxes()` — turns roots into the headline *effective independent bases* per position, and surfaces *what matters*.
   - The one-page pseudocode is in **[`ALGORITHM.md`](ALGORITHM.md)**.

4. **Check the honest limitations** — `MECHANISM.md §8`. We publish the open problems rather than hide them.

---

## The problem

If one side of a dispute has 20 papers and the other has 4, a naive aggregator declares a winner. But if the 20 all re-analyse the same dataset or echo the same reviews, they may be closer to **one** piece of evidence cited 20 times; if they form a pure ungrounded citation loop, the loop contributes **zero** independent grounding. Worse, that failure is **easy to weaponise**: flood a position with re-hashed reviews and you manufacture apparent consensus. Three correlated-evidence failures hide inside any flat source count:

- **Echo** — ten reviews summarising the same three studies are one look, not ten.
- **Cohort re-use** — eight papers off one cohort are one independent dataset (Nurses' Health Study; the Huanan-market environmental dataset in COVID).
- **Circular corroboration** — A cites B, B cites A, nothing primary underneath: two sources, *zero* independent grounding.

Deep-research prose *notices* these correlations qualitatively, in a good report, once. What it does not give you is a **recomputable number** that survives an adversary and updates as the dispute grows.

## What Ground Knowledge does

It aggregates like Ground News — but **inverts the aggregator's neutrality**. Instead of counting heads and staying agnostic, it resolves every source to the primary **evidentiary roots** it ultimately rests on, and reports, per position, the **effective number of independent bases** (`nEff`): each distinct root counted **once**, no matter how many sources pile onto it. With root identity fixed, adding a source to an existing root moves `nEff` **nowhere**. Source-weighted concentration is shown separately and may rise or fall depending on which root receives the source; a graph correction (merging aliases or revealing a citation loop) can legitimately lower `nEff`.

The number is produced by one deterministic, stdlib-only function over a portable JSON knowledge base. The viewer renders that function's output; it never recomputes, so there is no drift between pipeline and UI.

## How it works — four layers, one code path

The pipeline maps onto FLF's three-layer stack and produces a **living** KB (not a snapshot). Cold-start and incremental update are the *same code path*, run N times or once.

1. **Ingestion** (`ingest/`) — an AI **discovers** sources (keyless via OpenAlex) and **labels** each source into a structured *delta*: which position it supports, its evidence tier, funding, population, and — crucially — its `restsOn` edges (the datasets and other sources it depends on). Labelling can run as a **multi-model ensemble** with a field-level majority vote; a genuine position or primary/secondary-tier split is escalated to a human, not averaged into a guess.

2. **Structure** (`engine/merge.py`) — the model *proposes* ids; deterministic code *disposes*. Normalized-string + learned-alias resolution folds exact/known variants onto one entity; lexical and optional embedding suggestions flag novel paraphrases for an explicit human merge. A likely duplicate is blocked at the confirmation boundary unless the curator records an override. Duplicate URLs/DOIs are refused at the door.

3. **Assessment** (`engine/roots.py`, `engine/assess.py`) — pure, deterministic, no LLM. Resolves the derivation graph to its roots and computes every number the tool reports: independence, concentration, funding skew, method-monoculture, cruxes, blindspots, and a structured **diff** of what each update changed.

4. **View** (`viewer/`, `app/`) — a self-contained viewer and a multi-user portal (Postgres-backed) where anyone can add a question or contribute sources; every contribution is append-only and logged.

### The independence engine (the heart)

`resolve()` builds the source→source citation graph, collapses each **strongly-connected component** via Tarjan's algorithm, then resolves every source — through evidence-base and citation edges alike — to the roots underneath it. A grounded cycle resolves into its real roots; an ungrounded loop remains visible and flagged but contributes **zero** headline evidence.

- **Naming plus admission earns a root.** An ungrounded "primary" source that names *no* dataset collapses into one pooled "unnamed first-hand voice" per position. A distinct root needs a specific named base *and* an auditable confirmation; generic labels and unverified names remain proposed.
- **Secondary echo pools.** All ungrounded reviews/commentary for a position collapse into one "secondary voice."
- **Roots count once.** `nEff` sums distinct-root strengths; piling sources onto an already-counted root cannot move it. A randomized fixed-graph property test checks that adding a source with only outgoing edges never lowers `nEff`; separately, graph corrections are allowed to remove false independence.

### Auditable, per-edge root confirmation (recent hardening)

A named dataset is not trusted just because a source claims it. A root is **provisional** (contributes **zero** to the headline count) until it is confirmed one of two auditable ways:

- **curator confirmation** — the base carries a required `{status, method, by, ts}` record and normally a direct supporting `source`; likely aliases are blocked unless the curator records why they are distinct; **or**
- **a verified edge** — a source that was actually fetched carries a dependency quote that both matches the fetched text and identifies **that specific evidence base**.

Confirmation is strictly **per edge**: a verified quote admits only the dataset it annotates — never a sibling dataset on the same source, and never a root reached only by inheritance through a citation edge. Generic names such as “cohort” cannot bind ordinary methods prose, and automatically verified lexical lookalikes admit at most one root while the collision is surfaced. This closes real whitewashes and means a public contributor cannot mint independent support by fabricating dataset names on the paste-back path — fabricated roots stay **visible but quarantined**.

## Adversarial robustness — a contract we *execute*

The robustness claim is not prose; the benchmark runs seven attacks on every case:

- **+12 ungrounded echo** sources under the strongest position → `nEff` rises by **at most 1.0** (the twelve collapse to a single pooled voice), not +12.
- **+12 fabricated named datasets** on the unverified paste-back path → `nEff` moves by **0.0** (visible as proposed roots, quarantined until confirmed), versus a naive count of +12.
- **one real dependency quote copied onto a fabricated sibling edge** → only the dataset the quote actually names enters `nEff`; the sibling stays proposed.
- **a 12-source circular citation ring** → it is flagged and contributes **0.0**.
- **a known alias of an existing root** → it resolves to that root and contributes **0.0** additional independence.
- **a generic fetched label** (`Cohort`) → ordinary methods prose does not identify a root; **0.0** gain.
- **two newly proposed lexical aliases** named by one real sentence → at most one enters `nEff`; the collision is flagged for curation.

All seven must hold for every case or the benchmark fails. They pass. A genuinely novel semantic paraphrase can still evade the lexical gate; optional embeddings and human review reduce, not eliminate, that risk.

## Surfacing what matters — the crux taxonomy

A single "camps disagree by a lot" test misses most of the factors that actually decide a dispute. `cruxes()` types each factor:

- **crossCampCrux** — camps weigh it very differently (active disagreement).
- **sharedPivot** — two+ camps both rate it *decisive* (agreement that it matters, unresolved — e.g. "is Hawking radiation guaranteed?").
- **oneSidedLoadBearing** — one camp's case rests on a factor no other camp has engaged (e.g. "the safety argument itself may be wrong").
- **missingCounterassessment** — a decisive factor a camp has left unanswered.

The headline crux count stays tight (cross-camp disagreement or shared pivot) so it does not balloon to "every factor", while the one-sided and unanswered factors are surfaced separately. All hand-written gold crux concepts appear in the visible matrices (**3/3 per case**); promotion is intentionally stricter (e.g. COVID surfaces 2 headline cruxes of 7 factors, not 7).

## Does it actually help? (honest evaluation)

The benchmark ([`eval/run_benchmark.py`](eval/run_benchmark.py)) runs three checks and **verifies the baselines it compares against** (files + SHA-256 hashes), so a boolean is never taken as evidence. Two independent deep-research baseline sets — **ChatGPT Deep Research** and **Claude Code / Opus 4.8** — are captured with provenance and hash-checked.

- **Structure recall** (positions / key roots / cruxes surfaced) is scored against a small, deliberately non-exhaustive gold per case.
- **Collapse** quantifies the headline: e.g. COVID's *zoonotic* position — **15 sources → ~5 independent bases**; *lab-associated* — **8 → 3.5**. Eggs' *no-association* — **9 → 4**.
- **Adversarial robustness** is executed, not asserted (above).

**Comparative recall (honest).** The benchmark also scores the ChatGPT / Claude reports against the *same* small, developer-authored gold, as a keyword-recall proxy (with declared paraphrase synonyms). The result is **near-parity** — a good deep-research report surfaces the same positions, roots, and crux concepts GK does. Structure recall counts concepts visible anywhere in GK's factor matrix; the separate crux-type counts show which ones the detector actually promotes. This diagnostic is not held-out evaluation or evidence of reader uplift; hashes establish capture integrity, not output quality.

**What we do NOT claim.** The Claude/ChatGPT baselines are strong comparators: they *do* notice reused evidence, funding, cruxes, and source overlap qualitatively. So the honest advantage is narrower than "deep research misses correlation" — it does not. What Ground Knowledge adds is a **structured, recomputable artifact**: an explicit root graph, a deterministic collapse count, a versioned update **diff**, an executable adversarial contract, and portable citations another team can extend. The arithmetic is deterministic and gaming-resistant but **not self-certifying**: an incorrect curator confirmation or omitted edge can still move the numbers wrongly. The strongest next evidence is a blinded reader study; the preregistration-ready protocol, response schema, and deterministic assignment generator are included in [`eval/reader_study/`](eval/reader_study/), but no reader outcome is claimed before it is run.

## What is genuinely novel

Counting independent data sources rather than papers is not itself new (meta-analysis handles it as a "unit-of-analysis" problem). The contribution is a **deterministic, recomputable metric over structured empirical-causal disputes**, combining echo/cohort/cycle resolution, per-edge auditable admission, and an executable adversarial contract. Labelling and confirmation remain partly human; this is not claimed to be automatic over arbitrary disputes.

## Reproduce in 60 seconds

```
git clone https://github.com/Zhenia-Magic/ground-knowledge && cd ground-knowledge
python -m unittest discover -s tests -t .     # full stdlib suite, no dependencies
python eval/run_benchmark.py                  # recall · collapse · adversarial (all PASS)
python cli.py assess cases/covid.kb.json      # the full assessment for one case
```

Everything the metric needs is stdlib Python; there is no build step and no API key. License: **Apache-2.0**.
