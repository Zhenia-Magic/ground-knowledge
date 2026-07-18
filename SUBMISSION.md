# Ground Knowledge — core submission

*Ground Knowledge maps a research dispute as a graph: the positions, the sources backing each one, and the datasets those sources actually rest on. For every position it then reports how many genuinely independent pieces of evidence stand behind it, instead of counting papers.*

**Start with the deployed portal — [groundknowledge.org](https://groundknowledge.org). Nothing to install, no account.** It hosts the three prepared cases:

- [Eggs & heart disease](https://groundknowledge.org/q/04329878656c) — mundane but contested; the clearest illustration of the gap between paper count and evidence count.
- [COVID origin](https://groundknowledge.org/q/ac81b4cae8d0) — a live, expertise-heavy dispute.
- [LHC black holes](https://groundknowledge.org/q/c6c6ad01ec11) — an essentially settled question resting on a layered safety argument.

A five-minute look, using the eggs case: the **Overview** tab shows each position twice, first by raw source count and then by the adjusted count after shared evidence is collapsed. The "no increased risk" camp lists 10 sources but resolves to 6.0 independent evidence bases, and that gap is the finding. **Evidence reuse** shows which sources collapsed together and onto which cohorts. **Key issues** is a grid of the specific factors the camps weigh differently. **Changes** logs what every added source did to the numbers.

## Why counting papers fails, and what to count instead

If one camp has 20 papers and the other has 4, a naive aggregator declares a winner. But if the 20 all re-analyse the same cohort, the dispute is closer to 1 piece of evidence against 4. And the failure is easy to weaponise: flood your side with reviews and re-analyses and you manufacture apparent consensus.

So instead of counting papers, Ground Knowledge traces each paper down to the evidence underneath it — the datasets, experiments, and observations it rests on — and counts, per position, the **distinct** pieces of underlying evidence. Twenty papers on one cohort count as one. A review that only summarises other papers adds nothing of its own. Two papers that cite each other, with nothing primary underneath, add nothing at all.

The resulting number (internally `nEff`, the *adjusted evidence-base count*) measures how broad a position's independent evidentiary footing is. It is deliberately **not** a quality, effect-size, or truth score: seven weak datasets are not better evidence than one decisive trial, and the report says so. Study design, funding, method concentration, and quote verification are shown alongside the count, never folded into it.

## How the number is computed

Every number comes from deterministic code over a single JSON file per case. The AI's only job is labelling sources; it computes nothing.

**Step 1 — decide what to trust.** Nothing counts just because a source claims it. Two separate checks, each recorded in the file:

- *Is this dataset real?* A dataset is confirmed either by a curator (a logged, attributed decision) or by an exact quote, verified against the fetched text of a source, that names it.
- *Does this source actually rest on it?* The link from a source to a dataset needs its own verified quote or its own curator sign-off.

Any trust fields arriving from a model or from a public contribution are deleted before merging. Only the tool's own quote verification, or a logged curator decision, can set them.

**Step 2 — trace every source down to its roots.**

```
for each source:
    follow its trusted links downward
    (source → cited source → … → dataset)

roots(source) = every dataset reachable this way
```

Citation loops are handled first: A-cites-B-cites-A is merged into one unit, and if the loop reaches no dataset it is flagged as circular and carries nothing. A source that reaches no dataset at all gets a visible "unsupported" marker instead of quietly disappearing.

**Step 3 — score each position.**

```
credit(dataset) = 1.0   confirmed, with at least one primary human study on it
                = 0.5   only reviews rest on it, or only animal / in-vitro work
                = 0.0   unconfirmed, unsupported, or circular (still shown, at zero)

coverage(position) = sum of credit over the DISTINCT datasets
                     reachable from its sources
```

Each dataset is counted once, no matter how many sources rest on it. That single rule is what makes echo and volume inert: piling more papers onto an already-counted dataset moves nothing. A property-based test pins this down — adding a new source can never lower the count; only an explicit graph correction (say, merging two names that turn out to be the same cohort) can, because that removes false independence rather than evidence.

**Step 4 — find what actually divides the camps.** Each case lists the factors in play (e.g. "prior on lab accidents", "hyper-responder subgroups"), and each camp's weight on each factor, sourced from quotes. A factor becomes a *disagreement crux* when camps weigh it very differently, and a *shared pivot* when two camps both call it decisive but it remains unresolved. Factors only one camp leans on are surfaced separately rather than inflating the headline.

## The design choices doing the work

- **Dataset identity and reliance are two separate trust decisions.** A dataset being real does not let a new source attach itself to it; the reliance claim needs its own evidence. Without this split, anyone could launder an established dataset into their own camp with one unreviewed paper.
- **Each dataset counts once, and unsupported material stays visible at zero.** Gaming by volume is dead on arrival, by construction rather than by a tuned penalty.
- **The AI proposes, the code disposes.** Models label; deterministic code computes. Results are reproducible from the JSON alone and do not depend on model randomness.
- **Coverage never becomes a verdict.** The one thing the count must not turn into is a truth score; holding that line is what keeps the tool honest about uncertainty.

## The honest comparison

We scored the tool against ChatGPT Deep Research and a careful Claude Code investigation on the same hand-written gold standard (positions, key evidence, cruxes). The result is near-parity on recall: a good deep-research report already notices reused cohorts and industry funding. The difference is what you hold afterwards. A prose report's observations evaporate on the next question; here they become a portable, inspectable artifact — an explicit evidence graph, numbers anyone can recompute from the file, and a versioned diff of what each new source changed.

## It compounds, and it travels

A case is one JSON file. Anyone can pull it, add sources, and push it back; every write carries a diff, so the base grows across people and time instead of being re-researched from scratch. Citations import from and export to Zotero. Labelling is model-agnostic and can run as a multi-model ensemble that escalates genuine disagreements to a human instead of averaging them away, so the pipeline improves as models do. A coding agent (Claude Code, Codex) can drive the whole loop with no API key, with the deterministic CLI as the trust boundary. Nothing in the path depends on one hand-designed human step.

## Hard to game

Manufacturing consensus is the obvious attack, so the benchmark executes it rather than arguing about it. Nine attacks run against every case: flooding a position with twelve rehashed reviews, inventing twelve named datasets, a twelve-source circular citation ring, reusing a known dataset alias, a generic label ("cohort") fished from methods prose, attaching one camp's confirmed datasets to another camp through an unreviewed source, and forging a curator's sign-off inside model output. Each attack must leave the count exactly unchanged, and all nine pass on all three cases. What still gets through: a genuinely novel paraphrase of an existing dataset's name can evade the automatic matcher until a human reviews it. That limit is stated, not hidden.

## What it does not claim

The arithmetic is deterministic and hard to game, but not self-certifying: a wrong curator decision, or a dependency a source simply never mentions, can still move the numbers wrongly (we do not crawl citation databases). Coverage is not quality or truth. No blinded reader study backs an "uplift" claim; [`eval/reader_study/`](eval/reader_study/) is a protocol for future work, nothing more. The full list of open problems is in [`MECHANISM.md`](MECHANISM.md) §8.

---

## Run it yourself

Everything is plain-library Python: no build step, no dependencies, no API key.

```
git clone https://github.com/Zhenia-Magic/ground-knowledge && cd ground-knowledge
python -m unittest discover -s tests -t .     # full test suite
python eval/run_benchmark.py                  # recall + collapse + the nine attacks (all PASS)
python cli.py assess cases/covid.kb.json      # every reported number, for one case
```

## Additional material

- [`ALGORITHM.md`](ALGORITHM.md) — the full pseudocode of the metric.
- [`MECHANISM.md`](MECHANISM.md) — the mechanism in depth, edge cases, and open problems.
- [`SCHEMA.md`](SCHEMA.md) — the data model of a case file.
- [`AGENTS.md`](AGENTS.md) — driving the whole pipeline with a coding agent, no API key.
- [`README.md`](README.md) — repo map and setup.
- [`cases/`](cases/) — the three knowledge bases themselves; [`eval/`](eval/) — benchmark, results, quote audit.

License: Apache-2.0.
