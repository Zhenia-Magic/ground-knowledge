# Ground Knowledge — core submission

*A living knowledge base that scores **confirmed independent evidence-root coverage** per position, not source count — and ships an **executable** adversarial contract instead of a robustness claim.*

**Deployed demo, no setup and no API key:** **[groundknowledge.org](https://groundknowledge.org)** — three worked cases: [COVID origin](https://groundknowledge.org/q/ac81b4cae8d0), [LHC black holes](https://groundknowledge.org/q/c6c6ad01ec11), [eggs & heart disease](https://groundknowledge.org/q/04329878656c).

**Run the whole thing from a clean machine in ~1 minute** (stdlib Python, no build, no key):
```
git clone https://github.com/Zhenia-Magic/ground-knowledge && cd ground-knowledge
python -m unittest discover -s tests -t .     # full suite, no dependencies
python eval/run_benchmark.py                  # recall · collapse · 9-attack contract (all PASS)
python cli.py assess cases/covid.kb.json      # every number the tool reports, for one case
```

This page is the core (~2 pp). The full pseudocode is [`ALGORITHM.md`](ALGORITHM.md) (≤2 pp); the mechanism and its open problems are [`MECHANISM.md`](MECHANISM.md); the data model is [`SCHEMA.md`](SCHEMA.md). **Beyond the core** (outside the budget): *supporting* — [`AGENTS.md`](AGENTS.md) (drive the whole pipeline with a coding agent, no API key), [`README.md`](README.md) (repo map); *appendix / reference* — the full `cases/*.kb.json` knowledge bases and [`eval/`](eval/) (benchmark, `RESULTS.md`, quote audit).

## The move

If one camp has 20 papers and another has 4, counting rewards volume, echo, and funding. Ground Knowledge instead resolves every **admitted** support edge down to the **evidentiary root** beneath it — a dataset, a specific argument, a collider run — and reports, per position, the **adjusted evidence-base count** `nEff`: each distinct admitted root counted **once**, with declared 0.5 discounts for review-only and non-human grounding. Twenty papers off one cohort become one root; `A → B → A` with nothing primary underneath contributes zero. The number is a **coverage / de-duplication diagnostic, explicitly not a quality, effect-size, confidence, or truth score** — seven weak roots are not "better" than one decisive trial, and the viewer says so. Source count, study design, funding skew, method monoculture, and quote quality are shown *separately*, never folded into the number.

## The algorithm (deterministic, stdlib, no LLM in the metric)

```
# engine/roots.py — resolve every source through ADMITTED edges to its roots
def resolve(kb):
    # Trust is TWO independent decisions. A source claiming a dataset does not make the
    # dataset real, nor the reliance true:
    #   root identity — a curator record, OR a verified quote that names the base
    #   support edge  — the source's own verified dependency quote, OR a curator admission
    # Paste-back and model-supplied trust fields are STRIPPED before anything merges.
    components = tarjan(admitted_citation_graph(kb))      # collapse circular corroboration (SCC)
    for c in reverse_topological(components):
        roots  = { ds for s in c for ds in admitted_dataset_edges(s) }
        roots |= union(roots_of(dep) for dep in components_c_cites)
        if not roots:                                     # nothing grounded underneath
            roots = { pool_or_cycle_marker(c) }           # stays VISIBLE, counts zero
        memo[c] = roots

# engine/assess.py — strength of a root, then per-position coverage
def strength(r):
    if r.unconfirmed or r.edge_unadmitted or r.is_pool_or_cycle: return 0.0
    w = 1.0
    if r.secondary_only: w *= 0.5     # no primary source instantiates it (review-only)
    if r.nonhuman_only:  w *= 0.5     # animal / in-vitro, no explicit human primary
    return w

def nEff(position):
    return sum(strength(r) for r in distinct_roots_supporting(position))   # each root ONCE

# engine/assess.py — cruxes(): surface what matters, over ordinal factor weights (high/med/low)
crossCampCrux  = (>=2 camps weigh it) and (max - min >= 2)   # active disagreement
sharedPivot    = (>=2 camps rate it "high")                  # agreed-decisive, still unresolved
oneSidedLoadBearing / missingCounterassessment               # surfaced, but never inflate the headline
```

**Fixed-graph invariant (property-tested):** adding a source with only outgoing edges never lowers `nEff`; correlated/echo sources land on already-counted roots and move it nowhere. A graph *correction* (merging aliases, resolving a pending edge that reveals an ungrounded cycle) is allowed to lower it — that is removing false independence, not evidence.

## Why it is shaped this way (the load-bearing decisions)

- **Root identity and support-edge trust are admitted separately** so a real, globally-confirmed dataset cannot be laundered into another camp by one unreviewed source. This is the primitive most naive aggregators lack.
- **Roots count once, pools stay visible at zero** so volume and echo are inert by construction, not by a tuned penalty.
- **The model proposes, the code disposes.** The LLM only labels; every number comes from pure functions over portable JSON, so there is no pipeline↔UI drift and no dependence on model randomness.
- **Coverage is not quality.** The one thing the number must never become is a verdict; keeping that line is what makes it faithful to uncertainty.

## How it engages the judging dimensions

1. **Epistemic uplift.** The number makes the load-bearing evidence explicit: the "no increased risk" egg camp *lists 10 sources but resolves to 6.0 independent bases*; COVID's six Bayesian re-analyses collapse onto shared underlying evidence, not six new roots. Cruxes show what actually divides camps; funding/method audits flag rhetorical-vs-evidential moves. **Honest bar:** scored against ChatGPT Deep Research and Claude Code / Opus on the same gold, structure recall is **near-parity** — a good deep-research report already notices reuse and funding. The uplift is not "it notices more"; it is that the noticing becomes a **recomputable, inspectable artifact** with an explicit root graph a reader can audit and rerun.
2. **Generalizability.** Same engine, only the JSON differs, across three deliberately different shapes: a mundane-but-contested curated debate (eggs), a confident answer over a layered safety case (black holes), and a live, expertise-heavy dispute (COVID). Nothing in `roots.py`/`assess.py` is case-specific.
3. **Compounding & shareability.** The artifact is a portable JSON knowledge base with a versioned **diff** of what each update changed; anyone can `pull`, add sources, and `push`, and a keyless coding agent (Claude Code / Codex) can drive the whole loop on its own subscription. Citations import/export for Zotero. Another team's sources drop straight into the same schema.
4. **Scalability.** No single hand-designed human step gates throughput: labelling is model-agnostic and improves as base models do (and can run as a multi-model ensemble that escalates genuine disagreement instead of averaging it); the metric is deterministic and unbounded in sources; **more adversarial scrutiny only helps** — every edge is audited, and the nine-attack contract runs on every case.
5. **Methodological transparency.** The spec is written down (`ALGORITHM` / `MECHANISM` / `SCHEMA`), the key decisions and tradeoffs are called out, and where we are uncertain we say so: the 0.5 discounts are declared heuristics, not calibrated weights, and no reader-uplift study is claimed.
6. **Adversarial robustness.** Nine attacks — echo flooding, +12 fabricated datasets, a 12-source circular ring, a known-alias reuse, a generic fetched label, cross-camp root laundering, a forged curator `admission` — run on every case and must each move `nEff` by **0.0**. The two-layer admission and the trust-stripping boundary are what make that hold under motivated reading; failure modes are named and bounded (a genuinely novel paraphrase can still evade the lexical gate until human review).
7. **Insight contribution.** The reframe: the interesting quantity in a research dispute is not sources but **distinct admitted evidence roots**, and the load-bearing primitive is **separating root-identity trust from support-edge trust**. And the honest comparative it forces: deep research already *notices* correlation qualitatively, so the frontier is not detection — it is a **portable, recomputable, adversarially-tested artifact** that another investigator can extend and that survives being read by someone who wants a different answer.

## What it does not claim

The arithmetic is deterministic and gaming-resistant but **not self-certifying**: an incorrect curator decision or an omitted citation edge can still move the numbers wrongly (we do not crawl real citation graphs). Coverage is not quality, effect size, or truth. No blinded reader study is claimed — [`eval/reader_study/`](eval/reader_study/) is future-work scaffolding only. A genuinely novel semantic alias can evade automatic identity matching until review. These are named in `MECHANISM.md §8`, not hidden.

*Reproduce · inspect · attack: everything above runs from the clone with stdlib Python. License: Apache-2.0.*
