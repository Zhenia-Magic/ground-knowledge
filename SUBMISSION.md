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

## What a source count hides, made visible

The report opens each position three ways: raw source count, the adjusted evidence-base count beside it, and a funding-bias flag over both. The gap between the first two *is* the finding. The egg "no increased risk" camp lists **10 sources but resolves to 6.0** independent bases once shared cohorts and review echo collapse; COVID's six Bayesian re-analyses (Rootclaim, Weissman, Miller, …) rest on substantially the same underlying evidence, so they read as re-analysis, not six new roots. A separate grid names the specific factors camps actually clash on — the cruxes — and, distinctly, the factors one camp leans on that no other has engaged. Funding defaults to *Undisclosed* and is audited next to the count, so an industry meta-analysis and an independent cohort never blur into "two sources."

The honest comparison: scored against ChatGPT Deep Research and Claude Code / Opus on the same hand-written gold, structure recall is **near-parity** — a good deep-research report already notices reused evidence and funding. So the contribution is not sharper detection. It is turning that noticing into a **recomputable, inspectable artifact**: an explicit root graph, a number a reader can rerun from the JSON, and a versioned **diff** of what each new source changed.

## One engine, three differently-shaped disputes

Only the JSON differs across a mundane-but-contested curated debate (eggs), a confident answer over a layered safety case (black holes — eleven "safe" sources resolve to 5.0 coverage across five distinct lines, with the residual concern surfaced as a one-sided load-bearing factor rather than buried), and a live, expertise-heavy dispute (COVID). Nothing in `roots.py`/`assess.py` is case-specific; a fourth dispute is a new file, not new code.

## It compounds, and it travels

The artifact is a portable JSON knowledge base anyone can `pull`, extend, and `push`, with citations that import and export for Zotero — another team's sources drop straight into the same schema, and every write carries a diff so the base grows across people and time. Nothing in the path is bottlenecked on one hand-designed human step: discovery and labelling are model-agnostic and can run as a multi-model ensemble that escalates genuine disagreement instead of averaging it, so the pipeline improves as base models do; the metric itself is deterministic and unbounded in sources; and more scrutiny only helps, because every edge is audited rather than trusted. A keyless coding agent (Claude Code / Codex) can drive the entire loop on its own subscription, with the deterministic CLI (`lint → add → verify → doctor`) as the trust boundary.

## Hard to game

Manufacturing consensus is the obvious attack, so the benchmark tries it. Nine attacks run on every case — echo flooding, +12 fabricated named datasets, a 12-source circular citation ring, a known-alias reuse, a generic fetched label, all of one camp's roots laundered into another through an unreviewed source, and a forged curator `admission` — and each must move `nEff` by **0.0**. Two things make that hold: the two-layer admission (a real dataset cannot be attached to a camp by a source that only claims it), and a trust boundary that strips any model- or paste-back-supplied trust field before it merges. A genuinely novel paraphrase can still slip the lexical gate until a human reviews it; that limit is named, not hidden.

## What it does not claim

The arithmetic is deterministic and gaming-resistant but **not self-certifying**: an incorrect curator decision or an omitted citation edge can still move the numbers wrongly (we do not crawl real citation graphs). Coverage is not quality, effect size, or truth. No blinded reader study is claimed — [`eval/reader_study/`](eval/reader_study/) is future-work scaffolding only. These and the other open problems are named in `MECHANISM.md §8`.

*Reproduce · inspect · attack: everything above runs from the clone with stdlib Python. License: Apache-2.0.*
