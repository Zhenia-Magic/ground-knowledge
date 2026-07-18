# Ground Knowledge: core submission

*Ground Knowledge maps a research dispute as a graph: the positions, the sources backing each one, and the datasets those sources actually rest on. For every position it then reports how many genuinely independent pieces of evidence stand behind it, instead of counting papers.*

**Start with the deployed portal: [groundknowledge.org](https://groundknowledge.org). There's nothing to install and no account needed.** It hosts the three prepared cases:

- [Eggs & heart disease](https://groundknowledge.org/q/04329878656c): mundane but contested, and the clearest illustration of the gap between paper count and evidence count.
- [COVID origin](https://groundknowledge.org/q/ac81b4cae8d0): a live, expertise-heavy dispute.
- [LHC black holes](https://groundknowledge.org/q/c6c6ad01ec11): an essentially settled question resting on a layered safety argument.

A five-minute look, using the eggs case: the **Overview** tab shows each position twice, first by raw source count and then by the adjusted count after shared evidence is collapsed. The "no increased risk" camp lists 12 sources but resolves to 8.0 independent evidence bases, and that gap is the finding. **Evidence reuse** shows which sources collapsed together and onto which cohorts. **Key issues** is a grid of the specific factors the camps weigh differently. **Changes** logs what every added source did to the numbers.

## Why counting papers fails, and what to count instead

If one camp has 20 papers and the other has 4, a naive aggregator declares a winner. But if the 20 all re-analyse the same cohort, the dispute is closer to 1 piece of evidence against 4. And the failure is easy to weaponise: flood your side with reviews and re-analyses and you manufacture apparent consensus.

So instead of counting papers, Ground Knowledge traces each paper down to the evidence underneath it (the datasets, experiments, and observations it rests on) and counts, per position, the *distinct* pieces of underlying evidence. Twenty papers on one cohort count as one. A review that only summarises other papers adds nothing of its own, and two papers that cite each other with nothing primary underneath add nothing at all.

The resulting number (internally `nEff`, the *adjusted evidence-base count*) measures how broad a position's independent evidentiary footing is. It is deliberately not a quality, effect-size, or truth score: seven weak datasets are not better evidence than one decisive trial, and the report says so. Study design, funding, method concentration, and quote verification are shown alongside the count, never folded into it.

## How the number is computed

Every number comes from deterministic code over a single JSON file per case. The AI's only job is labelling sources; it computes nothing.

**Step 1: decide what to trust.** Nothing counts just because a source claims it. Two separate checks, each recorded in the file:

- *Is this dataset real?* A dataset is confirmed either by a curator (a logged, attributed decision) or by an exact quote, verified against the fetched text of a source, that names it.
- *Does this source actually rest on it?* The link from a source to a dataset needs its own verified quote or its own curator sign-off.

The pipeline deletes any trust fields that arrive from a model or a public contribution before merging. Only the tool's own quote verification, or a logged curator decision, can set them.

**Step 2: trace every source down to its roots.**

```
for each source:
    follow its trusted links downward
    (source → cited source → … → dataset)

roots(source) = every dataset reachable this way
```

The metric handles citation loops first: it merges A-cites-B-cites-A into one unit, and if that unit reaches no dataset it flags it as circular, carrying nothing. A source that reaches no dataset at all gets a visible "unsupported" marker instead of quietly disappearing.

**Step 3: score each position.**

```
credit(dataset) = 1.0   confirmed, with at least one primary human study on it
                = 0.5   only reviews rest on it, or only animal / in-vitro work
                = 0.0   unconfirmed, unsupported, or circular (still shown, at zero)

coverage(position) = sum of credit over the DISTINCT datasets
                     reachable from its sources
```

Each dataset is counted once, no matter how many sources rest on it. That single rule is what makes echo and volume inert: piling more papers onto an already-counted dataset moves nothing. A test enforces exactly this: no source you add can ever push the count down. The only thing that lowers it is an explicit graph correction, like merging two names that turn out to be the same cohort, because that removes a double-count rather than real evidence.

**Step 4: find what actually divides the camps.** Each case lists the factors in play (e.g. "prior on lab accidents", "hyper-responder subgroups"), and each camp's weight on each factor, sourced from quotes. A factor becomes a *key disagreement* when camps weigh it very differently, and a *shared uncertainty* when two camps both call it decisive but it stays unresolved. Factors only one camp leans on are shown separately, so they don't inflate the headline.

## The design choices doing the work

- **Dataset identity and reliance are two separate trust decisions.** A dataset being real does not let a new source attach itself to it; the reliance claim needs its own evidence. If these were one decision, a single unreviewed paper that merely mentions a trusted dataset could borrow that dataset's credibility for its own side.
- **Each dataset counts once, and unsupported material stays visible at zero.** Piling on more papers about the same dataset therefore does nothing to the score. Volume can't buy a higher number, and that follows from the structure itself, not from a penalty we tuned in to punish it.
- **The AI proposes, the code disposes.** Models label; deterministic code computes. Results are reproducible from the JSON alone and do not depend on model randomness.
- **Coverage never becomes a verdict.** The one thing the count must not turn into is a truth score; holding that line is what keeps the tool honest about uncertainty.

## What the report puts in front of a reader

The point is not a single score but a picture you can interrogate. For any dispute the report makes the load-bearing evidence explicit: which cohorts actually carry a position, where a dozen papers collapse onto one dataset, and where a camp's whole case rests on a single study. Funding sits beside the count, so an industry-funded meta-analysis never blurs into an independent cohort, and the report flags method concentration the same way. The key-issues grid names the specific factors the camps actually clash on, and separates genuine disagreement from points only one side has engaged. Because every claim is one click from the exact sentence it came from and every number recomputes from the file, a reader can check a conclusion rather than take it on trust. A versioned diff then shows exactly what each new source changed.

## It compounds, and it travels

A case is one JSON file, and it moves the way a git repository does. You pull a case, merge new sources into it locally (each addition folds in and records its own diff), and push the result back. If someone else changed it in the meantime, the push is rejected until you reconcile, the same way git refuses a stale push, so the history reads like a commit log and the base grows across people and time instead of being re-researched from scratch. Sources go in and out through the standard citation formats (BibTeX, RIS, and CSL-JSON), so a case round-trips with Zotero, Mendeley, or EndNote. Labelling is model-agnostic and can run as a multi-model ensemble that escalates genuine disagreements to a human instead of averaging them away, so the pipeline improves as the models do. A coding agent (Claude Code, Codex) can drive the whole loop with no API key: the agent proposes changes, but it can't grant itself trust, because the deterministic CLI re-checks every quote itself and discards any "verified" flag the model tries to set. The base gets richer as base models improve and as more people contribute, and adversarial scrutiny only hardens it, because every new source is audited the same way, whichever side it favours.

## Hard to game, and what it doesn't claim

Manufacturing consensus is the obvious attack, so the benchmark carries it out rather than arguing about it. It runs nine attacks against each of the three cases: flooding a position with twelve rehashed reviews, inventing twelve named datasets, a twelve-source circular citation ring, reusing a known dataset alias, a generic label ("cohort") fished from methods prose, attaching one camp's confirmed datasets to another camp through an unreviewed source, and forging a curator's sign-off inside model output. Every one must leave the count exactly unchanged, and all nine pass on all three cases.

Two limits are worth stating plainly. A genuinely novel paraphrase of an existing dataset's name can slip past the automatic matcher until a human reviews it. And the arithmetic, deterministic and hard to game as it is, does not certify itself: a wrong curator decision, or a dependency a source never actually mentions, can still move the numbers the wrong way (we do not crawl citation databases). Coverage is not quality or truth. The full list of open problems is in [`MECHANISM.md`](MECHANISM.md) §8.

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

- [`ALGORITHM.md`](ALGORITHM.md): the full pseudocode of the metric.
- [`MECHANISM.md`](MECHANISM.md): the mechanism in depth, edge cases, and open problems.
- [`SCHEMA.md`](SCHEMA.md): the data model of a case file.
- [`AGENTS.md`](AGENTS.md): driving the whole pipeline with a coding agent, no API key.
- [`README.md`](README.md): repo map and setup.
- [`cases/`](cases/) holds the three knowledge bases themselves; [`eval/`](eval/) holds the benchmark, results, and quote audit.

License: Apache-2.0.
