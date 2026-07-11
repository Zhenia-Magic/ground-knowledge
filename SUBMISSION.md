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
   - **Black holes** — `cases/blackholes.kb.json` — [could the LHC destroy Earth?](https://groundknowledge.org/q/c6c6ad01ec11). A near-settled question where the *residual* concern is that the safety argument itself might be wrong — surfaced as a one-sided load-bearing crux.

3. **Read the two core functions** — this is a ≤2-page algorithm, not a black box:
   - `engine/roots.py` → `resolve()` — resolves every source to the primary evidentiary **roots** it depends on, collapses echo / cohort-reuse / circular citation, and admits a root to the count only when it is **confirmed per edge**.
   - `engine/assess.py` → `independence()` and `cruxes()` — turns roots into the headline *effective independent bases* per position, and surfaces *what matters*.
   - The one-page pseudocode is in **[`ALGORITHM.md`](ALGORITHM.md)**.

4. **Check the honest limitations** — `MECHANISM.md §8`. We publish the open problems rather than hide them.

---

## The problem

If one side of a dispute has 20 papers and the other has 4, a naive aggregator declares a winner. But if the 20 all re-analyse the same dataset, echo the same three reviews, or cite each other in a loop, they are closer to **one** piece of evidence cited 20 times. Worse, that failure is **easy to weaponise**: flood a position with re-hashed reviews and you manufacture apparent consensus. Three correlated-evidence failures hide inside any flat source count:

- **Echo** — ten reviews summarising the same three studies are one look, not ten.
- **Cohort re-use** — eight papers off one cohort are one independent dataset (Nurses' Health Study; the Huanan-market environmental dataset in COVID).
- **Circular corroboration** — A cites B, B cites A, nothing primary underneath: two sources, *zero* independent grounding.

Deep-research prose *notices* these correlations qualitatively, in a good report, once. What it does not give you is a **recomputable number** that survives an adversary and updates as the dispute grows.

## What Ground Knowledge does

It aggregates like Ground News — but **inverts the aggregator's neutrality**. Instead of counting heads and staying agnostic, it resolves every source to the primary **evidentiary roots** it ultimately rests on, and reports, per position, the **effective number of independent bases** (`nEff`): each distinct root counted **once**, no matter how many sources pile onto it. Adding more *correlated* sources moves `nEff` **nowhere** — it can only raise the visible *concentration*. Adding genuinely new evidence is the only way up.

The number is produced by one deterministic, stdlib-only function over a portable JSON knowledge base. The viewer renders that function's output; it never recomputes, so there is no drift between pipeline and UI.

## How it works — four layers, one code path

The pipeline maps onto FLF's three-layer stack and produces a **living** KB (not a snapshot). Cold-start and incremental update are the *same code path*, run N times or once.

1. **Ingestion** (`ingest/`) — an AI **discovers** sources (keyless via OpenAlex) and **labels** each source into a structured *delta*: which position it supports, its evidence tier, funding, population, and — crucially — its `restsOn` edges (the datasets and other sources it depends on). Labelling can run as a **multi-model ensemble** with a field-level majority vote; a genuine split is escalated to a human, not averaged into a guess.

2. **Structure** (`engine/merge.py`) — the model *proposes* ids; deterministic code *disposes*. Normalized-string + alias resolution folds paraphrased dataset/position/factor names onto one entity, so a cohort cannot be smuggled in under five names to fake independence. Duplicate URLs/DOIs are refused at the door.

3. **Assessment** (`engine/roots.py`, `engine/assess.py`) — pure, deterministic, no LLM. Resolves the derivation graph to its roots and computes every number the tool reports: independence, concentration, funding skew, method-monoculture, cruxes, blindspots, and a structured **diff** of what each update changed.

4. **View** (`viewer/`, `app/`) — a self-contained viewer and a multi-user portal (Postgres-backed) where anyone can add a question or contribute sources; every contribution is append-only and logged.

### The independence engine (the heart)

`resolve()` builds the source→source citation graph, collapses each **strongly-connected component** (a circular-corroboration loop) to a single root via Tarjan's algorithm, then resolves every source — through dataset edges and citation edges alike — to the set of primary roots underneath it. Key design choices, each an adversarial defence:

- **Naming, not claiming, earns a root.** An ungrounded "primary" source that names *no* dataset collapses into one pooled "unnamed first-hand voice" per position. You earn a distinct root by naming a distinct dataset — not by asserting the primary tier. This closes the echo-as-primary flooding hole.
- **Secondary echo pools.** All ungrounded reviews/commentary for a position collapse into one "secondary voice."
- **Roots count once.** `nEff` sums distinct-root strengths; piling sources onto an already-counted root cannot move it. This is a monotonicity invariant, checked by a randomized property test: adding a source never lowers any position's `nEff` and raises it only by introducing a *new* root or upgrading one.

### Auditable, per-edge root confirmation (recent hardening)

A named dataset is not trusted just because a source claims it. A root is **provisional** (contributes **zero** to the headline count) until it is confirmed one of two auditable ways:

- **curator confirmation** — the dataset carries a record `{status, method, by, source, ts}` (not an opaque boolean), so a reader can see *how* and *by whom* it was admitted; **or**
- **a verified edge** — a source that was actually fetched carries a dependency quote that verified against the fetched text **for that specific dataset edge**.

Confirmation is strictly **per edge**: a verified quote admits only the dataset it annotates — never a sibling dataset on the same source, and never a root reached only by inheritance through a citation edge. This closes a real whitewash (one quote could otherwise admit every dataset a source touched) and means a public contributor cannot mint independent support by fabricating dataset names on the paste-back path — fabricated roots stay **visible but quarantined**.

## Adversarial robustness — a contract we *execute*

The robustness claim is not prose; it is a test the benchmark runs on every case:

- **+12 ungrounded echo** sources under the strongest position → `nEff` rises by **at most 1.0** (the twelve collapse to a single pooled voice), not +12.
- **+12 fabricated named datasets** on the unverified paste-back path → `nEff` moves by **0.0** (visible as proposed roots, quarantined until confirmed), versus a naive count of +12.

Both must hold for every case or the benchmark fails. It passes.

## Surfacing what matters — the crux taxonomy

A single "camps disagree by a lot" test misses most of the factors that actually decide a dispute. `cruxes()` types each factor:

- **crossCampCrux** — camps weigh it very differently (active disagreement).
- **sharedPivot** — two+ camps both rate it *decisive* (agreement that it matters, unresolved — e.g. "is Hawking radiation guaranteed?").
- **oneSidedLoadBearing** — one camp's case rests on a factor no other camp has engaged (e.g. "the safety argument itself may be wrong").
- **missingCounterassessment** — a decisive factor a camp has left unanswered.

The headline crux count stays tight (cross-camp disagreement or shared pivot) so it does not balloon to "every factor", while the one-sided and unanswered factors are surfaced separately. Against a hand-written gold this lifted crux recall from 1/3·0/3·1/3 to **3/3·2/3·2/3** across the three cases without inflating the headline count (COVID surfaces 2 headline cruxes of 7 factors, not 7).

## Does it actually help? (honest evaluation)

The benchmark ([`eval/run_benchmark.py`](eval/run_benchmark.py)) runs three checks and **verifies the baselines it compares against** (files + SHA-256 hashes), so a boolean is never taken as evidence. Two independent deep-research baseline sets — **ChatGPT Deep Research** and **Claude Code / Opus 4.8** — are captured with provenance and hash-checked.

- **Structure recall** (positions / key roots / cruxes surfaced) is scored against a small, deliberately non-exhaustive gold per case.
- **Collapse** quantifies the headline: e.g. COVID's *zoonotic* position — **15 sources → ~5 independent bases**; *lab-associated* — **8 → 3.5**. Eggs' *no-association* — **9 → 4**.
- **Adversarial robustness** is executed, not asserted (above).

**What we do NOT claim.** The Claude/ChatGPT baselines are strong comparators: they *do* notice reused evidence, funding, cruxes, and source overlap qualitatively. So the honest advantage is narrower than "deep research misses correlation" — it does not. What Ground Knowledge adds is a **structured, recomputable artifact**: an explicit root graph, a deterministic collapse count that moves only for legitimate reasons, a versioned update **diff**, an **executable** flooding/fabrication contract, and portable citations another team can extend. The arithmetic is deterministic and gaming-resistant by construction — but it is **not self-certifying**: an incorrect curator confirmation or an omitted citation edge can still move the numbers wrongly (`MECHANISM.md §8`). The single strongest way to move this from "promising" to "proven" is a blinded head-to-head reader study; that is a human study we have scoped but not yet run.

## What is genuinely novel

Counting independent data sources rather than papers is not itself new (meta-analysis handles it as a "unit-of-analysis" problem). What is not standard is doing it **automatically, as one deterministic metric, over an arbitrary dispute, and hardened against an adversary** — treating echo, cohort re-use, and circular citation as *one* phenomenon resolved by collapsing a derivation graph to its roots, with per-edge auditable admission and an executable robustness contract.

## Reproduce in 60 seconds

```
git clone https://github.com/Zhenia-Magic/ground-knowledge && cd ground-knowledge
python -m unittest discover -s tests -t .     # 206 tests, stdlib only, no deps
python eval/run_benchmark.py                  # recall · collapse · adversarial (all PASS)
python cli.py assess cases/covid.kb.json      # the full assessment for one case
```

Everything the metric needs is stdlib Python; there is no build step and no API key. License: **Apache-2.0**.
