# Ground Knowledge: core submission

*Ground Knowledge maps a research dispute as a graph: the positions, the sources behind each one, and the actual datasets and experiments those sources rest on. For each position it counts how many separate pieces of evidence really stand behind it, instead of counting papers.*

**Start with the deployed portal: [groundknowledge.org](https://groundknowledge.org). There's nothing to install and no account needed.** It hosts the three prepared cases:

- [Eggs & heart disease](https://groundknowledge.org/q/04329878656c): mundane but contested, and the clearest illustration of the gap between paper count and evidence count.
- [COVID origin](https://groundknowledge.org/q/ac81b4cae8d0): a live, expertise-heavy dispute.
- [LHC black holes](https://groundknowledge.org/q/c6c6ad01ec11): an essentially settled question resting on a layered safety argument.

A five-minute look, using the eggs case, one tab at a time:

- **Overview** shows each position twice: first by raw source count, then by the adjusted count after shared evidence is collapsed. The "no increased risk" camp lists 12 sources but resolves to 8.0 adjusted evidence bases, and that gap is the finding.
- **Evidence reuse** shows which sources collapsed together, and onto which cohorts.
- **Key issues** is a grid of the specific factors the camps weigh differently.
- **Changes** logs what every added source did to the numbers.

Take that "no increased risk" camp: 6 of its 12 sources reuse the Nurses' Health Study / Health Professionals Follow-up Study evidence base. Each stays individually inspectable, but together they contribute one unit to the count. Seven other admitted bases make up the rest, hence 12 sources → 8.0 evidence bases.

## Why counting papers fails, and what to count instead

If one camp has 20 papers and the other has 4, a naive count declares a winner. But a paper count breaks in three ways, and on a bar chart all three look identical to real agreement:

- **Echo.** Ten reviews summarising the same three studies are one look, not ten, yet each is counted as a separate source.
- **Cohort re-use.** One research group publishes eight papers off a single cohort. Eight sources, one dataset underneath.
- **Circular corroboration.** Source A's evidence is Source B, and B's evidence is A. Two sources, zero independent grounding. This is the adversarial case: it is built to look like mutual confirmation.

All three are the same problem: sources that add no new evidence underneath. And it is easy to do on purpose, since flooding your side with reviews and re-analyses manufactures an apparent consensus out of one real study.

The fix is to stop treating every document as its own unit. A **source** (a paper, review, report, or guideline) and a **root** (the dataset, experiment, or observation it actually rests on) are different kinds of thing, and many sources can share one root. Ground Knowledge traces each source down to its roots and counts, per position, the *distinct* roots underneath. Twenty papers on one cohort count as one. A review that only summarises other papers adds nothing of its own, and two papers that cite each other with nothing primary underneath add nothing at all.

The resulting number (internally `nEff`, the *adjusted evidence-base count*) measures how many separate pieces of evidence really stand behind a position. It does not claim those pieces are statistically independent of each other. It is deliberately not a quality, effect-size, or truth score: seven weak datasets are not better evidence than one decisive trial, and the report says so. Study design, funding, method concentration, and quote verification are shown alongside the count, never folded into it.

## How the number is computed

Every number comes from deterministic code over a single JSON file per case. In most cases the AI does the legwork, searching for the sources and labelling them, but it computes nothing: every number is the code's, not the model's.

**Step 1: decide what to trust.** Nothing counts just because a source claims it. Two separate checks, each recorded in the file:

- *Is this root a real, distinct evidence base?* Confirmed once, either by a curator (a logged, attributed decision) or by an exact quote, verified against a source's fetched text, that names it.
- *Does this particular source actually rest on it?* Every source that wants credit for that root needs its own verified quote, or its own curator sign-off, showing reliance rather than a name appearing somewhere in a reference list.

Often one sentence settles both at once: a study whose methods say it analysed egg intake in the Framingham Heart Study names a real dataset and shows its own reliance in the same breath. But a later review that only lists Framingham in its references clears the first check, not the second, and earns nothing until it says it actually used the data. That gap is deliberate: it stops one confirmed dataset from being claimed by every paper that name-drops it.

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
- **Each root counts once, and unsupported material stays visible at zero.** The count is over distinct roots, so piling on more papers about the same root does nothing: a repeat just lands on a root that is already counted. Volume has nowhere to go.
- **The AI proposes, the code disposes.** Models label; deterministic code computes, so the same labelled JSON always yields the same numbers, independent of model randomness.
- **Coverage never becomes a verdict.** The one thing the count must not turn into is a truth score; holding that line is what keeps the tool honest about uncertainty.

## What the report puts in front of a reader

The point is not a single score but a picture you can interrogate. For any dispute the report makes the load-bearing evidence explicit: which cohorts actually carry a position, where a dozen papers collapse onto one dataset, and where a camp's whole case rests on a single study. Funding sits beside the count, so an industry-funded meta-analysis never blurs into an independent cohort, and the report flags method concentration the same way. The key-issues grid names the specific factors the camps actually clash on, and separates genuine disagreement from points only one side has engaged. Every position, dependency, and factor links back to the exact sentence it came from, shown as a quotation when the wording matches the source and as a flagged summary when it does not. Every number recomputes from the file, and a versioned diff shows exactly what each new source changed.

## What is new, and what is not

Systematic reviews already separate studies from the reports about them, so counting the studies underneath rather than the papers is not the new part. The new part is doing it as one piece of code that behaves the same across cases: it builds the graph of what rests on what, checks a dataset's identity and a source's reliance on it as two separate questions, folds citation loops into a single node, and counts each distinct dataset once. And the promise that flooding can't move the number is a test that runs, not a claim in prose.

## It compounds, and it travels

A case is one JSON file, and it moves like a git repository: you pull it, add sources locally (each addition records its own diff), and push it back. A stale push is rejected until you reconcile, just as git refuses one, so the history reads like a commit log and the base grows across people and time instead of being re-researched from scratch. Sources import and export through the standard citation formats (BibTeX, RIS, CSL-JSON), so a case round-trips with Zotero, Mendeley, or EndNote. The format is open: documented in [`SCHEMA.md`](SCHEMA.md), validated against a published JSON Schema (draft 2020-12), and Apache-2.0. One command, `cli.py assess`, dumps the whole analysis as JSON, so another project can read every source, position, dataset, quote, and number without touching this portal or viewer.

The labelling works with any model, and can run several models at once: when they genuinely disagree it asks a human rather than averaging the answers, so the whole thing gets better as models do. A coding agent like Claude Code or Codex can run the entire loop with no API key. The agent can propose changes but cannot bless its own work: the CLI re-checks every quote against the real source text and throws away any "verified" flag the model tried to set. The easy calls (exact-text matches, obvious duplicate names) are automatic; the genuinely ambiguous ones still need a person to sign off, and that step stays visible in the log. I do not yet claim results at large scale.

The mechanism is built for disputes that ultimately come down to data, observations, models, or arguments. It is not a universal dispute metric: in law, authority can genuinely pile up (twenty rulings citing one precedent still each carry weight), and in mathematics, whether something is true is not a counting question at all.

## Hard to game, and what it doesn't claim

Manufacturing consensus is the obvious attack, so the benchmark actually runs the attack instead of arguing it can't happen. Nine of them run against each case:

- twelve rehashed reviews piled onto one position
- twelve invented datasets
- one real dependency quote copied onto a second, look-alike dataset
- a twelve-source citation ring (papers that only cite each other)
- one dataset resubmitted under a name the tool already knows
- a generic word ("cohort") lifted from a methods section and passed off as a dataset
- two brand-new made-up dataset names
- one camp's confirmed datasets attached to a rival camp through unreviewed links
- a forged curator sign-off buried in model output

Every attack that adds nothing real has to move the count by zero. In the two that also mix in one genuine dataset, only that real one is allowed in; its copied or look-alike twin stays unconfirmed. All nine pass on all three cases.

Three limits are worth stating plainly. A dataset renamed in a genuinely new way can slip past the automatic matcher until a human catches it. A labeller can leave out a real dependency, and since the tool doesn't crawl citation databases, checking quotes catches wrong wording but not a missing link. And however hard the arithmetic is to game, it can't vouch for a curator's judgement call. The half-credit for review-only and animal evidence is a deliberate rule of thumb, not a calibrated number. Coverage is not quality or truth. A blinded reader study is fully designed and built under [`eval/reader_study/`](eval/reader_study/) (protocol, scored questions, and a self-serve portal version), but I ran out of time to run it, so I claim no result from it. The full list of open problems is in [`MECHANISM.md`](MECHANISM.md) §8.

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
- [`eval/reader_study/PROTOCOL.md`](eval/reader_study/PROTOCOL.md): the reader study, designed and built but not run for lack of time (no result claimed).
- [`cases/`](cases/) holds the three knowledge bases themselves; [`eval/`](eval/) holds the benchmark, results, and quote audit.

License: Apache-2.0.
