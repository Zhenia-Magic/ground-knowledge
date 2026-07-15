# Epistemic Coverage — Project Overview

*A plain-language but thorough walkthrough of what this project is, why it exists, how it works,
and what has been built. Written to be readable on its own.*

---

## 1. The one-sentence version

**It's "Ground News, but for research disputes — with the neutrality flipped."**

Ground News is a news aggregator: it shows you how many outlets cover a story, what their
political lean is, and which side isn't covering something ("blindspots"). It is deliberately
**neutral about who is right** — which is correct for political news.

This project ports that idea to **research questions** ("Do eggs raise heart-disease risk?",
"Did COVID come from a lab?", "Could the LHC create a dangerous black hole?") — but inverts the
neutrality. In a research dispute, some positions genuinely *are* better supported, so simply
counting sources rewards whoever is loudest, most numerous, or best funded. That's **false
balance**. So instead of counting heads, the tool reports **confirmed-root coverage**: how much
admitted, deduplicated evidence-base coverage is represented for each position. It displays
evidence design/funding alongside that count. This is not a GRADE-style quality, effect-size,
confidence, or truth score.

The headline behaviour: **adding papers to an already resolved root adds no coverage credit.**
The raw count can grow while confirmed-root coverage stays fixed; unnamed rehashes remain visible
in a zero-credit pool, and a pure citation loop adds zero.

---

## 2. The problem it solves

Imagine a debate where one side has 20 papers and the other has 4. A naive aggregator says "20
vs 4 — the first side wins." But what if all 20 papers re-analyse the *same underlying dataset*?
Then they aren't 20 independent pieces of evidence — they're closer to **one** piece of evidence
cited 20 times. Counting them as 20 is misleading, and it's *gameable*: anyone can flood a
position with re-hashed studies to manufacture the appearance of consensus.

Three things go wrong with naive source-counting in research:

1. **Correlated evidence looks like independent evidence.** Twenty studies on one cohort ≠ twenty
   cohorts.
2. **Funding bias hides in the pile.** An industry-funded study and an independent one count the
   same if you just tally them.
3. **The real disagreement gets buried.** Two camps usually agree on most things and disagree on
   a few specific "cruxes" — but a list of sources doesn't show you *where* the disagreement
   actually lives.

This tool is built to surface exactly those three things.

---

## 3. The core idea (the "thesis")

> **Aggregate, but count confirmed, deduplicated evidence bases and audit quality separately — instead of
> counting sources.** If a feature could be gamed by flooding the zone with low-quality or correlated
> papers, it's the wrong feature.

Everything in the project follows from that commitment.

---

## 4. What it actually produces

For each research question, the tool builds a **knowledge base** — a single structured JSON file
— and renders it as a clean web report with four tabs:

- **Coverage & warnings** — how the evidence splits across positions (the naive view), *immediately
  complicated* by a funding-bias flag and, when triggered, a shared-method-bias warning banner.
- **Divergence matrix** — a grid showing which specific factors the camps actually disagree on (the
  "cruxes"), versus what they agree on.
- **Root coverage & bias** — the heart of it: for each position, how concentrated its evidence is on
  a few datasets (the anti-false-balance audit), plus the method-bias and quote-verification
  warnings for that position.
- **Changes** — a running history of what each newly added source did to the metrics.

The knowledge base is the durable artifact. The web report is just a view of it. Anyone can take
the JSON file and keep extending it — it's designed to **compound** over time and across people.

---

## 5. The architecture: three layers around one file

The project mirrors the competition's own framework — **Ingestion → Structure → Assessment** —
arranged around a single source of truth (the knowledge-base JSON).

```
 question → INGESTION → (one source) → STRUCTURE → the KB file → ASSESSMENT → DIFF → web report
            find · fetch · label        merge + resolve          recompute (pure math)
            (search/API + AI)           (deterministic code)      (deterministic code)
```

**Layer 1 — Ingestion (finding and reading sources).**
Three sub-steps, and only the last needs an AI model:
- **Find** candidate papers via a scholarly search engine (OpenAlex — a free, open index of
  250M+ academic works). No AI, no API key.
- **Fetch** the best available text of each paper by its identifier (DOI / PubMed / arXiv)
  through open academic APIs — including the **full open-access PDF** when available, which is
  where the funding statement and methods live. No web scraping, so no bot-walls. Not every
  source yields full text (some APIs only ever return an abstract) — the tool records honestly
  which it got (`textDepth`: full / abstract / partial) instead of claiming more than it fetched.
- **Label** the fetched text with an AI model — or an **ensemble** of several models, combined by a
  deterministic field-level majority vote: which position does it take, what kind of evidence
  is it, who funded it, which datasets does it rest on, which factors does it weigh. This is the
  *only* step that uses an AI. Running several models and voting means a label no longer hinges on
  one model's quirk, and the per-field agreement is recorded. When the models genuinely **disagree
  on the position or on the primary/secondary evidence tier**, the source isn't merged under a guessed label — it's parked in a *needs-review*
  queue (inside the KB itself) for a human to resolve: pick a position, or drop the paper. Pending
  items count toward no metric. The requested position, per-dataset-edge, and factor-weight quotes
  are spot-checked against the text that was actually fetched — a quote that doesn't match is flagged, but only counted as a
  real warning on a full-text source; the same check on an abstract-only source is expected
  noise, not an accusation (see §8).
  Multi-source output is joined back to fetched documents by an opaque `sourceId`, never by array
  position. The whole batch is rejected if an id is missing/duplicated/unknown, fetched bibliographic
  metadata wins over model metadata, and model-authored curator/admission fields are removed.

**Layer 2 — Structure (merging it in).**
A small piece of **deterministic, plain-Python code** folds each labelled source into the
knowledge base. "Deterministic" means: same input → same output, every time, no AI randomness.
This is where entity resolution happens (is "the Nurses' Health Study" the same cohort we already
have, or a new one?). The design rule is **"the AI proposes, the code disposes"**: the AI suggests
links by name, and reproducible string-matching code decides whether to reuse or create.

**Layer 3 — Assessment (the metrics).**
A set of **pure functions** — the only place numbers are computed. Given the knowledge base, they
recompute every metric from scratch. Because they're pure math over the file (not AI), the results
are reproducible and auditable: anyone can re-run them and get the same answer.

The key design property: **cold-start and update are the same code path.** Building a knowledge
base from scratch is just the "add one source" loop run many times. There's no separate batch
process to drift out of sync. That's what makes the knowledge base "living" rather than a snapshot.

---

## 6. The building blocks (the data model)

A knowledge base is made of a few simple entity types:

- **Positions** — the camps / stances on the question (e.g. "eggs increase risk", "no
  association", "context-dependent").
- **Evidence bases** (stored under the legacy `datasets` key) — a specific cohort, trial, observation,
  argument, model, or document. This is what powers the independence audit across empirical and
  theoretical cases.
- **Sources** — the individual papers. Each is tagged with its position, evidence type, funding
  category, population, and dependencies. Position and dataset-dependency edges request quotes;
  factor weights do too. Categorical metadata can come from fetched APIs and is not falsely described
  as quote-backed field by field.
- **Factors** — the dimensions of the debate (e.g. "hormones in dairy", "confounding by overall
  diet"). Each factor records how strongly *each position* weighs it.

And then the metrics computed from these:

- **Distribution** — share of sources per position. The naive view.
- **Funding pattern** — how *interested* money (industry/advocacy) is distributed across positions,
  explicitly reporting ties, plus how
  many sources don't disclose funding at all. Funding is a fixed set of categories
  (Government, Nonprofit, Academic, Industry, Advocacy, Undisclosed) and **defaults to
  "Undisclosed" — it never assumes independence** when a source is silent.
- **Confirmed-root coverage / concentration** — *the core metric.* For each position, it resolves
  admitted source-support edges down to underlying evidence bases and credits **each distinct,
  confirmed evidentiary root once** (at half credit when a root is known only via a review, or
  backed only by animal / in-vitro work). If five sources all rest on one admitted dataset, that is
  **1 unit of root coverage, not 5** — and adding a sixth, sixtieth, or six-hundredth source on that
  dataset moves the coverage by exactly nothing; the pile-up shows only in the separate
  *concentration* share. An ungrounded flood remains visible in a zero-credit pool. Relabelling an
  echo as original research does not bypass that quarantine: credit requires a **specific confirmed
  base and an admitted support edge for this position**. The result is not a claim that roots are
  statistically independent, equally informative, or true.
- **Cruxes** — from the factor grid: cross-camp disagreement, shared high pivots, one-sided high
  assumptions, unanswered high factors, and milder contests are separately typed. This localises
  where disagreement or missing engagement actually lives without calling every factor a crux.
- **Blindspots** — evidence types or populations present elsewhere in the debate but missing from
  a given position's own sources. "What is this camp not looking at?"

---

## 7. How you use it — three surfaces, one knowledge base

The same engine is reachable three ways, so different people can contribute:

**(a) The web portal** (deployed, multi-user, no setup, no API key).
Browse and search questions, open the live report, or add sources. The "add source" flow is
**keyless**: you find papers via the free search (or paste a URL directly), the server fetches
the best available text and bundles it into a single file, you upload that file to *your own*
ChatGPT or Claude to label it, and paste the result back. **No API key ever touches the server** — the
expensive AI step happens in the user's own chatbot, and folding the result in is just the
deterministic merge. This sidesteps the "would you trust a website with your API key?" problem
entirely.

**(b) The local console** (for power users with their own API key).
A local web app that does the whole pipeline automatically with your key — find, fetch, label,
merge — and can **pull** a question from the portal, work on it locally, and **push** the result
back. It's "git for knowledge bases": pull → work → push, with version checks so two people don't
clobber each other.

The portal revision is server-controlled and advances on every successful write, even when the KB's
own semantic `meta.version` is unchanged. The KB update and its contribution-log entry commit in one
database transaction. Public request size/rate/concurrency limits and bounded PDF extraction protect
availability; see `SECURITY.md` and `DEPLOYMENT.md`.

**(c) The command line.**
Everything scriptable: `discover`, `harvest`, `ingest`, `add`, `push`, `pull`, `build`, plus
cleanup tools (`merge`, `rename`, `tidy`, `dups`) for tidying duplicate entities.

A guiding principle throughout: **finding and reading sources are free and keyless** (open APIs);
**only the labelling step needs an AI.** So a huge amount works with no account at all.

---

## 8. The clever / non-obvious design decisions

- **"Propose, then deterministically resolve."** The AI is powerful but unpredictable, so it's
  confined to *proposing* (read this paper, suggest its labels). All the reproducible parts —
  which datasets, which counts, every metric — are computed by deterministic code that never
  depends on AI randomness. The precise claim: everything *downstream of the labels* is
  reproducible regardless of which AI (or no AI) produced them. The labels themselves can vary
  between models — and that variance is now *measured and acted on*, not just acknowledged: an
  **ensemble** of several models labels each source, a deterministic field-level vote combines them
  (recording per-field agreement), and a real disagreement on the position is escalated to a human
  review queue rather than averaged into a guess. Determinism doesn't erase model variance; the
  ensemble measures it and the review queue handles the cases where it matters.

- **The server holds no API key and does no AI work.** Because merging is deterministic, the
  hosted portal is cheap and has no billable AI-key surface. It still fetches public documents, so
  URL validation, byte/page caps, rate limits, and a small expensive-operation semaphore bound that
  remaining abuse surface.

- **Full open-access PDFs, not just abstracts.** Early on it only read abstracts, but abstracts
  rarely contain the funding statement or name the datasets. Now it fetches the full PDF when the
  paper is open-access and pulls out the funding/acknowledgments section specifically — so the
  funding and root-identity audits get real signal.

- **Funding identification has three tiers.** Full-text funding statement → OpenAlex grant data →
  Crossref funder data → and only then "Undisclosed." It honestly reports the disclosure gap
  rather than pretending a silent paper is independent.

- **Relevance filtering that doesn't take sides.** When searching for sources, the tool filters
  by the dispute's *subject* (using the academic index's topic classification) and by the
  question's *exposure term* (e.g. "alcohol"), but **never by which side a paper takes** — so it
  keeps both camps of a debate while dropping off-topic papers. Filtering by stance would
  reintroduce the very bias the project fights.

- **Duplicate and alias defences.** The same study can't be added twice (same URL or title+year
  is refused). Exact and learned aliases resolve automatically; unknown lexical lookalikes are
  quarantined at confirmation and shown for curator merge/override. Novel semantic paraphrases can
  still evade the advisory embedding check, so renaming is reduced rather than claimed solved.

- **A second, separate axis for correlated *bias*, not just correlated *data*.** The independence
  metric catches sources sharing a dataset — but 15 sources on 15 *distinct* cohorts can still all
  share the same uncontrolled confounder (the textbook case: "moderate alcohol" cohorts sharing
  abstainer/sick-quitter bias). A method-bias audit flags when a position's evidence leans heavily
  on one correlated-error family (e.g. observational confounding, Mendelian-randomisation
  pleiotropy) as a clearly separate warning — deliberately *not* folded into the independent-bases
  count, so the primary metric's claim stays narrow and defensible while the warning still surfaces
  the risk (see `MECHANISM.md` §12).

- **Requested provenance quotes are checked, not just collected.** Position quotes, per-dataset-edge
  dependency quotes, and factor-weight quotes are matched against the exact
  text the labeller actually saw. A mismatch on a full-text source is a real red flag (the model
  said something the paper doesn't support); the identical mismatch on an abstract-only source is
  expected noise, since the quote may be true but drawn from body text the tool never had — the two
  are never conflated (see `SCHEMA.md`).

---

## 9. The honest limitations (stated on purpose)

A core value of the project is naming what it *doesn't* solve:

- **Paraphrase collisions.** String matching handles known aliases. Optional embedding suggestions
  (`dups --embed`) surface semantic candidates, and confirmation blocks likely duplicates unless a
  curator records an override; the final identity decision remains deliberately human.
- **Curated factor weights.** How strongly each camp weighs each factor is a human/AI judgment —
  the softest input. The *mechanical* parts (counts, datasets, funding category, concentration)
  are what resist gaming.
- **Sparse factor grid.** A source only records weights for *its own* position, and only on
  factors it mentions; older sources aren't re-scored when a new factor appears. So the grid fills
  in only as sources across camps happen to address the same factors — a deliberate trade for
  determinism and provenance.
- **Data realism.** All three competition cases use real, citable sources. Their structure and factor
  weights are curator-authored, and most evidence-base confirmations are curator decisions rather
  than fetched, per-edge dependency verification; the audit records say so explicitly.
- **Method-bias is a warning, not yet a bounded second score.** The natural next step — a single
  "triangulation" number that discounts independence for shared correlated error, the way the
  primary metric discounts for shared datasets — turned out not to have a safe general formula
  (a naive version could make independence look *higher* after adding the bias signal, the
  opposite of the intent). Shipping a warning instead of a wrong number was the deliberate choice;
  the honest math problem is written up, unsolved, in `MECHANISM.md` §12.
- **Quote verification depends on what got fetched.** A quote can only be checked against text the
  tool actually retrieved. Sources ingested before this feature existed, or added through the
  keyless portal's paste-back flow (which never fetches server-side), show `textDepth: "unknown"`
  and get no verdict at all — never a guessed one.

---

## 10. What's been built (status)

- A working three-layer pipeline (find → fetch → label → merge → recompute → view).
- Real scholarly discovery (OpenAlex) + identifier-based full-text fetch (OpenAlex / arXiv /
  Semantic Scholar / Europe PMC) + Crossref funding lookup — all keyless.
- Batch ingestion sends each source's full fetched text to the labeller by default (no more
  silently trimming a paper down to a few thousand characters to save tokens).
- The deterministic merge engine with entity resolution and anti-gaming defences.
- All the assessment metrics + a self-contained web viewer, plus the method-bias audit and
  quote-verification warnings described in §8.
- A **deployed, multi-user portal** (live on the web, backed by a Postgres database) where anyone
  can browse, search, create questions, and contribute sources keyless.
- A local power-user console with automatic labelling and git-like pull/push sync.
- Curation tools, full documentation, and a public code repository.

**Live demo:** the portal is deployed and running (multi-user, with the demo cases pre-loaded).
**Code:** a public GitHub repository with a one-minute "run it yourself" path that needs no API key.

---

## 11. Why this exists (the competition)

It's built for the **Future of Life Foundation's "Lab Leaks, Black Holes, and Eggs" Epistemic
Case Study Competition**, which asks for workflows and tools that help people (with AI) reason
better about contested evidence. The judging rewards: genuine epistemic uplift over off-the-shelf
AI research, generalising across different kinds of disputes, producing structured artifacts
others can build on, scaling with more contributors/compute, transparency about method, and
robustness against being gamed. This project is designed around exactly those criteria — the
anti-false-balance independence audit is the central bet.

---

## 12. The tech, briefly

- **Language:** Python. The core (engine, viewer, metrics, local store) is **pure standard
  library — no installation needed.** Only full-text PDF reading and the production database need
  extra packages.
- **Storage:** the knowledge base is a single JSON document. Locally it's a file (or a small
  built-in SQLite database for the portal); in production it's PostgreSQL — but always the same
  portable JSON inside.
- **Hosting:** the portal runs on Railway with a Postgres database.
- **AI:** provider-agnostic — works with Claude, OpenAI, and several others, and is used *only*
  to label fetched text (one model, or a multi-model ensemble with a deterministic vote).
  Discovery, fetching, merging, metrics, and the viewer involve no AI at
  all ("provider-agnostic" means any model can do the labelling — not that different models
  produce identical labels, which is exactly why the ensemble and the review queue exist; see §8
  on what is and isn't deterministic).

---

*In short: it takes the familiar "map the coverage" idea from news aggregators and rebuilds it for
science, where the first questions are not merely "how many sources?" but "which admitted evidence
bases recur, which links remain unconfirmed, and who paid for the work?" The tool computes that
coverage diagnostic, shows where camps disagree, resists being gamed by volume, and lets a shared
knowledge base grow as more people contribute. It does not decide which position is true.*
