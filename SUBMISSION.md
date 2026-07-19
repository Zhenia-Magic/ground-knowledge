# Ground Knowledge: core submission

*Ground Knowledge maps a research dispute as a graph: the positions, the sources backing each one, and the evidence bases those sources actually rest on. For every position it then reports how many distinct, admitted evidence bases stand behind it, instead of counting papers.*

**Start with the deployed portal: [groundknowledge.org](https://groundknowledge.org). There's nothing to install and no account needed.** It hosts the three prepared cases:

- [Eggs & heart disease](https://groundknowledge.org/q/04329878656c): mundane but contested, and the clearest illustration of the gap between paper count and evidence count.
- [COVID origin](https://groundknowledge.org/q/ac81b4cae8d0): a live, expertise-heavy dispute.
- [LHC black holes](https://groundknowledge.org/q/c6c6ad01ec11): an essentially settled question resting on a layered safety argument.

A five-minute look, using the eggs case, one tab at a time:

- **Overview** shows each position twice: first by raw source count, then by the adjusted count after shared evidence is collapsed. The "no increased risk" camp lists 12 sources but resolves to 8.0 adjusted evidence bases, and that gap is the finding.
- **Evidence reuse** shows which sources collapsed together, and onto which cohorts.
- **Key issues** is a grid of the specific factors the camps weigh differently.
- **Changes** logs what every added source did to the numbers.

One representative slice makes the collapse concrete: 6 of the 12 sources in the eggs case's "no increased risk" camp reuse the Nurses' Health Study / Health Professionals Follow-up Study evidence base. Those six sources remain individually inspectable, but together that cohort contributes one unit to the adjusted count. The camp still reaches seven other admitted bases, hence 12 sources → 8.0 evidence bases.

## Why counting papers fails, and what to count instead

If one camp has 20 papers and the other has 4, a naive count declares a winner. But a paper count breaks in three ways, and on a bar chart all three look identical to real agreement:

- **Echo.** Ten reviews summarising the same three studies are one look, not ten, yet each is counted as a separate source.
- **Cohort re-use.** One research group publishes eight papers off a single cohort. Eight sources, one dataset underneath.
- **Circular corroboration.** Source A's evidence is Source B, and B's evidence is A. Two sources, zero independent grounding. This is the adversarial case: it is built to look like mutual confirmation.

All three are the same problem: sources that add no new evidence underneath. And it is easy to do on purpose, since flooding your side with reviews and re-analyses manufactures an apparent consensus out of one real study.

The fix is to stop treating every document as its own unit. A **source** (a paper, review, report, or guideline) and a **root** (the dataset, cohort, experiment, field observation, argument, model, or document it actually rests on) are different kinds of thing, and many sources can share one root. Ground Knowledge traces each source down to its roots and counts, per position, the *distinct* roots underneath. Twenty papers on one cohort count as one. A review that only summarises other papers adds nothing of its own, and two papers that cite each other with nothing primary underneath add nothing at all.

The resulting number (internally `nEff`, the *adjusted evidence-base count*) measures how broad a position's admitted evidentiary footing is. It does not establish that distinct roots are statistically independent. It is deliberately not a quality, effect-size, or truth score: seven weak datasets are not better evidence than one decisive trial, and the report says so. Study design, funding, method concentration, and quote verification are shown alongside the count, never folded into it.

## How the number is computed

Every number comes from deterministic code over a single JSON file per case. In most cases the AI does the legwork, searching for the sources and labelling them, but it computes nothing: every number is the code's, not the model's.

**Step 1: decide what to trust.** Nothing counts just because a source claims it. Two separate checks, each recorded in the file:

- *Is this root a real, distinct evidence base?* Confirmed once, either by a curator (a logged, attributed decision) or by an exact quote, verified against a source's fetched text, that names it.
- *Does this particular source actually rest on it?* Every source that wants credit for that root needs its own verified quote, or its own curator sign-off, showing reliance rather than a name appearing somewhere in a reference list.

Often one sentence settles both at once: a primary study whose methods say it analysed egg intake in the Framingham Heart Study cohort names a real dataset and shows its own reliance in the same breath. The checks come apart for everyone downstream. A later review that only lists Framingham among its references clears the first check (the dataset is real) but not the second (it never says it used the data), so it earns nothing until it does. That gap is deliberate: it is what stops one confirmed dataset from being claimed by every paper that merely name-drops it.

The pipeline deletes any trust fields that arrive from a model or a public contribution before merging. Only the tool's own quote verification, or a logged curator decision, can set them.

**Step 2: trace every source down to its roots.**

```
for each source:
    follow its trusted links downward
    (source → cited source → … → root)

roots(source) = every evidence base reachable this way
```

The metric handles citation loops first: it merges A-cites-B-cites-A into one unit, and if that unit reaches no root it flags it as circular, carrying nothing. A source that reaches no root at all gets a visible "unsupported" marker instead of quietly disappearing.

**Step 3: score each position.** Each source carries a tier: *primary* if it makes evidence (a cohort, an experiment, a field observation), *secondary* if it only talks about evidence (a review, a commentary, a guideline). A root's credit depends on the best tier resting on it.

```
credit(root) = 1.0   confirmed, with at least one primary human study on it
             = 0.5   only reviews (secondary) rest on it, or only animal / in-vitro work
             = 0.0   unconfirmed, unsupported, or circular (still shown, at zero)

coverage(position) = sum of credit over the DISTINCT roots
                     reachable from its sources
```

Each root is counted once, no matter how many sources rest on it. That single rule is what makes echo and volume inert: piling more papers onto an already-counted root moves nothing. Bad sources can never lower a position's count; at worst they add nothing. The only thing that lowers it is an explicit graph correction, like merging two names that turn out to be the same cohort, because that removes a double-count rather than real evidence.

**Step 4: find what actually divides the camps.** Each case lists the factors in play (e.g. "prior on lab accidents", "hyper-responder subgroups"), and each camp's weight on each factor, sourced from quotes. A factor becomes a *key disagreement* when camps weigh it very differently, and a *shared uncertainty* when two camps both call it decisive but it stays unresolved. Factors only one camp leans on are shown separately, so they don't inflate the headline.

## The design choices doing the work

- **Root identity and reliance are two separate trust decisions.** A root being real does not let a new source attach itself to it; the reliance claim needs its own evidence. If these were one decision, a single unreviewed paper that merely mentions a trusted evidence base could borrow it for its own side.
- **Each root counts once, and unsupported material stays visible at zero.** Piling on more papers about the same root therefore does nothing to the score. Volume can't buy a higher number, and that follows from the structure itself, not from a penalty we tuned in to punish it.
- **The AI proposes, the code disposes.** Models label; deterministic code computes. Given the same labelled JSON, every result reproduces exactly. Model variance can change proposed labels, so an ensemble records field-level agreement and escalates genuine position or evidence-tier splits instead of pretending the labelling step is deterministic.
- **Coverage never becomes a verdict.** The one thing the count must not turn into is a truth score; holding that line is what keeps the tool honest about uncertainty.

## What the report puts in front of a reader

The point is not a single score but a picture you can interrogate. For any dispute the report makes the load-bearing evidence explicit: which cohorts actually carry a position, where a dozen papers collapse onto one dataset, and where a camp's whole case rests on a single study. Funding sits beside the count, so an industry-funded meta-analysis never blurs into an independent cohort, and the report flags method concentration the same way. The key-issues grid names the specific factors the camps actually clash on, and separates genuine disagreement from points only one side has engaged. Position, dependency, and factor claims link to their provenance sentence; exact matches display as quotations, while altered or unchecked wording is visibly downgraded to a summary. Every number recomputes from the file, and a versioned diff shows exactly what each new source changed.

## What is new, and what is not

Systematic reviews already distinguish studies from reports, so counting underlying studies rather than papers is not new. The contribution here is to make that discipline one deterministic, cross-case mechanism: a typed derivation graph, separate trust decisions for root identity and source reliance, strongly-connected-component collapse for circular corroboration, and a strength-weighted distinct-root count with an executable flooding-immunity contract.

An earlier share-based concentration formula exposed why this matters. Flooding derivative papers onto a minority root can make source shares look more balanced, while piling junk "support" onto a rival's dominant root can make its evidence look more concentrated. Any headline metric that reads those per-source tallies is movable by worthless papers. Counting each admitted root once makes both attacks inert by construction.

## It compounds, and it travels

A case is one JSON file, and it moves the way a git repository does. You pull a case, merge new sources into it locally (each addition folds in and records its own diff), and push the result back. If someone else changed it in the meantime, the push is rejected until you reconcile, the same way git refuses a stale push, so the history reads like a commit log and the base grows across people and time instead of being re-researched from scratch. Sources go in and out through the standard citation formats (BibTeX, RIS, and CSL-JSON), so a case round-trips with Zotero, Mendeley, or EndNote. The case format is open in its own right: documented in [`SCHEMA.md`](SCHEMA.md), validated against a published JSON Schema (draft 2020-12), and released under Apache-2.0. `cli.py assess` emits the complete assessment as JSON, so another submission can consume the source/position/root/provenance records and computed metrics without adopting this portal or renderer.

Labelling is model-agnostic and can run as a multi-model ensemble that escalates genuine disagreements to a human instead of averaging them away, so the pipeline improves as the models do. A coding agent (Claude Code, Codex) can drive the whole loop with no API key: the agent proposes changes, but it can't grant itself trust, because the deterministic CLI re-checks every quote itself and discards any "verified" flag the model tries to set. Exact text checks and unambiguous identity reuse scale automatically; genuinely ambiguous aliases, support relationships, and model splits still require a logged curator decision. That remaining human bottleneck is bounded and visible, not claimed away, and no large-corpus scale result is claimed yet.

The same CLI was also run end-to-end on a fourth, non-provided question, saturated fat and cardiovascular risk: 11 sources, 3 positions, and 10 evidence bases, with the largest camp collapsing from 6 sources to 4.5 adjusted bases. The run also exposed limits rather than hiding them: the free labeller produced no factors, and abstract-only quotes required curator admissions. More generally, the mechanism is intended for empirical-causal disputes whose support bottoms out in data, observations, models, documents, or arguments. It is not a universal dispute metric: legal authority can be cumulative, and mathematical validity is not a counting problem.

## Hard to game, and what it doesn't claim

Manufacturing consensus is the obvious attack, so the benchmark carries it out rather than arguing about it. It runs nine contracts against each case: twelve rehashed reviews; twelve fabricated roots; one real dependency quote copied to a sibling root; a twelve-source citation ring; a known root alias; a generic label ("cohort") fished from methods prose; two unknown lexical aliases; confirmed roots attached to another camp through unreviewed edges; and a forged curator sign-off inside model output. Purely unearned additions must contribute zero. In the two mixed contracts, at most the one legitimate root may enter while the copied or colliding sibling stays proposed. All nine contracts pass on all three cases.

Three limits are worth stating plainly. A genuinely novel paraphrase of an existing dataset's name can slip past the automatic matcher until a human reviews it. A labeller can omit a real dependency because the system does not yet crawl citation databases; exact quote matching catches false wording, not a missing edge. And the arithmetic, deterministic and hard to game as it is, does not certify a curator's semantic judgment. The 0.5 review-only and non-human credits are declared heuristics, not calibrated likelihood ratios. Coverage is not quality or truth. A blinded reader-uplift study is designed and written up under [`eval/reader_study/`](eval/reader_study/) (the protocol, the scored questions, and a self-serve portal version), but we did not have time to run it, so no reader-uplift result is claimed. The full list of open problems is in [`MECHANISM.md`](MECHANISM.md) §8.

---

## Run it yourself

The core engine, benchmark, and viewer build use only the Python standard library: no build step, package install, or API key. Optional PDF, DOCX, and production Postgres features have optional dependencies.

```
git clone https://github.com/Zhenia-Magic/ground-knowledge && cd ground-knowledge
python cli.py demo                              # one-command case tour + benchmark
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
- [`eval/RESULTS.md`](eval/RESULTS.md): the benchmark output (structure recall, root collapse, and the nine adversarial contracts).
- [`eval/reader_study/PROTOCOL.md`](eval/reader_study/PROTOCOL.md): the reader-uplift study, designed and built but not run for lack of time (no result claimed).
- [`runs/saturated-fat-2026-07-16.md`](runs/saturated-fat-2026-07-16.md): a fourth end-to-end run, including failures and limitations.
- [`cases/`](cases/) holds the three knowledge bases themselves; [`eval/`](eval/) holds the benchmark, results, and quote audit.

License: Apache-2.0.
