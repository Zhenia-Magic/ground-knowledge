# Ground Knowledge — submission

*A living, recomputing knowledge base that maps **confirmed evidence-root coverage** instead of source count — and is hardened against volume, echo, circular citation, and support-edge laundering.*

**Live, no setup, no API key → [groundknowledge.org](https://groundknowledge.org)**
**Repo → https://github.com/Zhenia-Magic/ground-knowledge**

---

## Judge, start here (10 minutes)

1. **See the thesis in 60 seconds.** Run the reproducible benchmark from a clean clone:
   ```
   python eval/run_benchmark.py
   ```
   It prints, per case: *structure recall* against a hand-written gold, the *collapse* (raw source
   count → adjusted evidence-base count), the *key disagreement taxonomy*, and an *executed* adversarial contract.
   Or run `python cli.py demo` for the same plus a per-case assessment and links to the live viewer.

2. **Read three worked cases** (open on the live site or `python cli.py assess cases/<case>.kb.json`):
   - **COVID** — `cases/covid.kb.json` — [origin of SARS-CoV-2](https://groundknowledge.org/q/ac81b4cae8d0). The current artifact shows 13 zoonotic sources → **5.0** adjusted evidence-base count, 7 laboratory-origin → **3.5**, and 6 unresolved → **3.0**.
   - **Eggs** — `cases/eggs.kb.json` — [do eggs raise CVD risk?](https://groundknowledge.org/q/04329878656c). The three positions show 4 → **4.0**, 9 → **5.0**, and 7 → **4.0**; industry funding is surfaced separately from coverage.
   - **Black holes** — `cases/blackholes.kb.json` — [could the LHC destroy Earth?](https://groundknowledge.org/q/c6c6ad01ec11). The "No risk" position has 11 sources and **4.0** adjusted evidence-base count across production impossibility, Hawking evaporation, accretion timescale, and the empirical dense-star bound. This is a map of the layered safety case, not a quality-weighted verdict. The *residual* concern is surfaced as a one-sided load-bearing key disagreement.

3. **Read the two core functions** — this is a ≤2-page algorithm, not a black box:
   - `engine/roots.py` → `resolve()` — separates root-identity trust from source→root support-edge trust, resolves admitted edges, and collapses cohort reuse / echo / circular citation.
   - `engine/assess.py` → `independence()` and `cruxes()` — computes *adjusted evidence-base count* and surfaces *what matters*. The internal key remains `nEff` for compatibility.
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

Instead of counting heads, it resolves each admitted support link to the **evidentiary roots** underneath it and reports, per position, **adjusted evidence-base count** (`nEff`): each distinct admitted root counted once with declared 0.5 discounts for review-only and non-human grounding. With root and edge identity fixed, adding a source to an existing root moves `nEff` nowhere. Source incidence, study design, funding, method monoculture, and quote quality are shown separately.

This number is a **coverage and de-duplication diagnostic, not a support, evidence-quality, effect-size, confidence, or truth score**. Seven weak roots are not necessarily better evidence than one decisive trial; distinct roots can share the same confounder. The viewer labels it accordingly and displays each root's one-time coverage credit separately from source incidence.

The number is produced by one deterministic, stdlib-only function over a portable JSON knowledge base. The viewer renders that function's output; it never recomputes, so there is no drift between pipeline and UI.

## How it works — four layers, one code path

The pipeline maps onto FLF's three-layer stack and produces a **living** KB (not a snapshot). Cold-start and incremental update are the *same code path*, run N times or once.

1. **Ingestion** (`ingest/`) — an AI **discovers** sources (keyless via OpenAlex) and **labels** each source into a structured *delta*: which position it supports, its evidence tier, funding, population, and — crucially — its `restsOn` edges (the datasets and other sources it depends on). Labelling can run as a **multi-model ensemble** with a field-level majority vote; a genuine position or primary/secondary-tier split is escalated to a human, not averaged into a guess.

2. **Structure** (`engine/merge.py`) — the model *proposes* ids; deterministic code *disposes*. Normalized-string + learned-alias resolution folds exact/known variants onto one entity; lexical and optional embedding suggestions flag novel paraphrases for an explicit human merge. A likely duplicate is blocked at the confirmation boundary unless the curator records an override. Duplicate URLs/DOIs are refused at the door.

3. **Assessment** (`engine/roots.py`, `engine/assess.py`) — pure, deterministic, no LLM. Resolves the derivation graph to its roots and computes every number the tool reports: independence, concentration, funding skew, method-monoculture, key disagreements, blindspots, and a structured **diff** of what each update changed.

4. **View** (`viewer/`, `app/`) — a self-contained viewer and a multi-user portal (Postgres-backed). Public paste-back contributions are queued and affect no metric until an administrator reviews them; full-KB pushes are token-gated and optimistic-version-locked. The portal bounds request bodies, fetch batches, expensive concurrent work, request threads, and per-IP mutation rates. Each KB write and its audit entry commit together, and stale writers receive a conflict instead of overwriting newer work.

### The independence engine (the heart)

`resolve()` builds the source→source citation graph, collapses each **strongly-connected component** via Tarjan's algorithm, then resolves every source — through evidence-base and citation edges alike — to the roots underneath it. A grounded cycle resolves into its real roots; an ungrounded loop remains visible and flagged but contributes **zero** headline evidence.

- **Naming plus admission earns coverage.** An ungrounded source collapses into a visible position-level assertion marker with **zero** coverage credit. A distinct root needs a specific named base, confirmed root identity, and an admitted support edge.
- **Secondary echo pools at zero.** Ungrounded reviews/commentary collapse into one visible marker but do not become an evidence base merely by existing.
- **Roots count once.** `nEff` sums distinct-root strengths; piling sources onto an already-counted root cannot move it. A randomized fixed-graph property test checks that adding a source with only outgoing edges never lowers `nEff`; separately, graph corrections are allowed to remove false independence.

### Separate, auditable root and support-edge admission (recent hardening)

A named dataset is not trusted just because a source claims it. The implementation makes two separate decisions:

- **Root identity:** is this a real, distinct evidence base? A curator record or a verified, specifically identifying dependency quote can confirm it.
- **Support edge:** does this particular source actually rely on that base/citation? The edge needs its own verified dependency quote or `{status, method, by, ts}` curator admission. `python cli.py confirm-edge ...` is the auditable human fallback.

An already confirmed root therefore cannot be attached to another camp by an unreviewed source. Generic names such as “cohort” cannot bind ordinary methods prose; automatically verified lexical lookalikes admit at most one root while the collision is surfaced. Existing case relationships carry explicit `legacy-migration` edge records that disclose they were adopted from the curated artifact and are **not** quote verification.

## Adversarial robustness — a contract we *execute*

The robustness claim is not prose; the benchmark runs nine attacks on every case:

- **+12 ungrounded echo** sources under the strongest position → `nEff` moves by **0.0**; the pooled assertion marker is visible at zero.
- **+12 fabricated named datasets** on the unverified paste-back path → `nEff` moves by **0.0** (visible as proposed roots, quarantined until confirmed), versus a naive count of +12.
- **one real dependency quote copied onto a fabricated sibling edge** → only the dataset the quote actually names enters `nEff`; the sibling stays proposed.
- **a 12-source unreviewed circular citation ring** → its source links are blocked pending admission and contribute **0.0**; an admitted ungrounded ring is collapsed by the SCC detector.
- **a known alias of an existing root** → it resolves to that root and contributes **0.0** additional independence.
- **a generic fetched label** (`Cohort`) → ordinary methods prose does not identify a root; **0.0** gain.
- **two newly proposed lexical aliases** named by one real sentence → at most one enters `nEff`; the collision is flagged for curation.
- **all confirmed roots from one camp attached to another through an unreviewed source** → the target camp moves by **0.0**; the unsupported links remain visible.
- **a fetched model delta that forges a curator `admission` object** → the trust field is removed before merge and the target camp moves by **0.0**.

All nine must hold for every case or the benchmark fails. They pass. A genuinely novel semantic paraphrase can still evade the lexical gate; optional embeddings and human review reduce, not eliminate, that risk.

## Surfacing what matters — the key disagreement taxonomy

A single "camps disagree by a lot" test misses most of the factors that actually decide a dispute. `cruxes()` types each factor:

- **crossCampCrux** — camps weigh it very differently (active disagreement).
- **sharedPivot** — two+ camps both rate it *decisive* (agreement that it matters, unresolved — e.g. "is Hawking radiation guaranteed?").
- **oneSidedLoadBearing** — one camp's case rests on a factor no other camp has engaged (e.g. "the safety argument itself may be wrong").
- **missingCounterassessment** — a decisive factor a camp has left unanswered.

The headline key disagreement count stays tight (cross-camp disagreement or shared uncertainty) so it does not balloon to "every factor", while the one-sided and unanswered factors are surfaced separately. All hand-written gold key disagreement concepts appear in the visible matrices (**3/3 per case**); promotion is intentionally stricter (e.g. COVID currently surfaces 3 headline key disagreements of 7 factors, not 7).

## Does it actually help? (honest evaluation)

The benchmark ([`eval/run_benchmark.py`](eval/run_benchmark.py)) runs three checks and **verifies the baselines it compares against** (files + SHA-256 hashes), so a boolean is never taken as evidence. Two independent deep-research baseline sets — **ChatGPT Deep Research** and **Claude Code / Opus 4.8** — are captured with provenance and hash-checked.

- **Structure recall** (positions / key roots / key disagreements surfaced) is scored against a small, deliberately non-exhaustive gold per case.
- **Collapse/coverage** quantifies the headline: COVID **13 → 5.0**, **7 → 3.5**, **6 → 3.0**; black holes **11 → 4.0**, **4 → 2.0**; eggs **4 → 4.0**, **9 → 5.0**, **7 → 4.0**. [`eval/RESULTS.md`](eval/RESULTS.md) is generated from the benchmark, and CI fails if it is stale.
- **Adversarial robustness** is executed, not asserted (above).

**Comparative recall (honest).** The benchmark also scores the ChatGPT / Claude reports against the *same* small, developer-authored gold, as a keyword-recall proxy (with declared paraphrase synonyms). The result is **near-parity** — a good deep-research report surfaces the same positions, roots, and key disagreement concepts GK does. Structure recall counts concepts visible anywhere in GK's factor matrix; the separate key disagreement-type counts show which ones the detector actually promotes. This diagnostic is not held-out evaluation or evidence of reader uplift; hashes establish capture integrity, not output quality.

**What we do NOT claim.** The Claude/ChatGPT baselines are strong comparators: they *do* notice reused evidence, funding, key disagreements, and source overlap qualitatively. So the honest advantage is narrower than "deep research misses correlation" — it does not. What Ground Knowledge adds is a **structured, recomputable artifact**: an explicit root graph, a deterministic coverage/de-duplication count, a versioned update **diff**, an executable adversarial contract, and portable citations another team can extend. The arithmetic is deterministic and gaming-resistant but **not self-certifying**: an incorrect curator decision or omitted edge can still move the numbers wrongly. No reader study is claimed for this submission. [`eval/reader_study/`](eval/reader_study/) is future-work scaffolding only, not evidence of uplift.

## What is genuinely novel

Counting underlying data sources rather than papers is not itself new (meta-analysis handles it as a unit-of-analysis problem). The contribution is the **portable updateable artifact and trust boundary**: deterministic root resolution, separate root/edge admission, visible zero-credit assertions, key disagreement/funding/method audits, versioned diffs, and an executable adversarial contract. Labelling and curation remain partly human; this is not claimed to be automatic or calibrated over arbitrary disputes.

## Reproduce in 60 seconds

```
git clone https://github.com/Zhenia-Magic/ground-knowledge && cd ground-knowledge
python -m unittest discover -s tests -t .     # full stdlib suite, no dependencies
python eval/run_benchmark.py                  # recall · collapse · adversarial (all PASS)
python cli.py assess cases/covid.kb.json      # the full assessment for one case
```

Everything the metric needs is stdlib Python; there is no build step and no API key. License: **Apache-2.0**.
