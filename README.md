# Ground Knowledge — a living, recomputing knowledge base for research disputes

> *Ground News, but for research disputes — with the aggregator's neutrality inverted.*
> Ground News counts and labels sources but stays neutral on who's right. In a research
> dispute, naive source-counting rewards the loud, the numerous, and the industry-funded.
> So we **aggregate, but weight by independent evidence and audit for independence** instead of
> counting heads. Adding more *correlated* papers — re-used cohorts, review echo, or two sources
> that cite each other — makes a position look **less** independently supported, not more.

**Live, no setup, no API key → [groundknowledge.org](https://groundknowledge.org)**

> **Judge, start here →** [`SUBMISSION.md`](SUBMISSION.md) (10-minute tour) · [`ALGORITHM.md`](ALGORITHM.md)
> (≤2-page pseudocode) · or run **`python cli.py demo`** for per-case collapse + the full benchmark.

A Python pipeline that maps onto FLF's three-layer stack and produces a **living** knowledge
base (not a snapshot): an AI **discovers** sources → **labels** each link/document into a
structured delta → **merges** deterministically → **recomputes** every metric → shows a
**diff** of what changed → **bakes** a self-contained viewer. Cold-start and incremental
update are the *same code path*, run N times or once.

## The core idea: count independent evidence, not sources

If one side has 20 papers and the other has 4, a naive aggregator declares a winner. But if all
20 re-analyse the same dataset they're closer to **one** piece of evidence cited 20 times — and
that's easy to game: flood a position with re-hashed reviews to manufacture consensus. Three
failures hide in a flat source count, and **[`MECHANISM.md`](MECHANISM.md)** is one cure for all
three:

- **Echo** — ten reviews summarizing the same three studies are one look, not ten.
- **Cohort re-use** — eight papers off one cohort are one independent dataset.
- **Circular corroboration** — A cites B, B cites A, with nothing primary underneath: two
  sources, *zero* independent grounding (the adversarial case).

The independence engine (`engine/roots.py`) resolves every source down to the primary
**evidentiary roots** it actually depends on, collapsing all three into a single, honest count of
*independent bases* per position — and flags circular loops explicitly. It's adversarially robust
by construction: flooding a position with echo can neither inflate it **nor** tank a rival.

## Layout

| path | layer | what it is |
|------|-------|-----------|
| `ingest/pipeline.py` · `prompts/` | **Ingestion** | discovery + one-source labelling (link / PDF / docx / txt); tells the model what's already in the KB so it finds *new* sources |
| `ingest/extract.py` | Ingestion | fetch text by identifier — OpenAlex / arXiv / Semantic Scholar / Europe PMC; uses the **full open-access PDF** when available (+ Crossref funder lookup); no scraping |
| `ingest/search.py` | Ingestion | keyless scholarly search via OpenAlex (the *fallback* discovery engine) |
| `ingest/llm.py` | Ingestion | model-agnostic LLM access — **Anthropic / NVIDIA (free) / OpenAI / DeepSeek / Mistral / Groq / Gemini / OpenRouter**; used only to *label* (single model or a multi-model **ensemble**); `--dry-run` needs no key |
| `ingest/ensemble.py` | Ingestion | deterministic field-level majority vote fusing several models' labels into one delta + a per-source agreement report |
| `engine/merge.py` | **Structure** | deterministic merge + entity resolution (LLM proposes ids, code disposes); duplicate / alias / off-topic defences; resolves source→source citation edges |
| `engine/review.py` | Structure | human-in-the-loop queue: a genuine ensemble disagreement is parked in the KB (counted in no metric) for a human to resolve — pick a position, or drop the paper |
| `engine/roots.py` | Structure | the independence mechanism: tier-aware root resolution + circular-corroboration detection ([`MECHANISM.md`](MECHANISM.md)) |
| `engine/gaps.py` | Structure | gap analysis — where is a position's evidence thin? — that steers gap-driven deep search |
| `engine/curate.py` | Structure | curation ops: merge / rename / tidy duplicate entities |
| `engine/assess.py` | **Assessment** | the only place numbers are computed: distribution, **weighted (independence) distribution**, independence audit, funding skew, blindspots, cruxes |
| `cli.py` | orchestrator | `new · init · show · assess · gaps · deepen · add · build · ingest · ingest-batch · discover · research · harvest · merge · rename · tidy · dups · ui · pull · push · questions · import-citations · export` |
| `ui/` (`cli.py ui`) | UI | local **workstation** console: find → fetch → label → import, Curate, and **pull/push** to a portal |
| `app/` (`python -m app.portal`) | **Deployment** | a shared multi-user **portal** (browse/search, contribute keyless, AI-retrieval docs, admin moderation) + a portable store (sqlite local / Postgres prod) the CLI pushes & pulls to |
| `viewer/template.html` → `viewer/index.html` | UI | render-only; baked by `build`; opens with a double-click |
| `cases/*.kb.json` | artifact | the knowledge bases (`eggs` is real & sourced; pull others from the portal) |
| `MECHANISM.md` · `SCHEMA.md` · `SPEC.md` | spec | the independence mechanism, the schema, and the written submission |

**Core (engine + viewer build + URL/txt ingestion + `--dry-run` + the local portal store) is
pure stdlib — no `pip install`.** Full-text PDF labelling needs `pypdf`, `.docx` needs
`python-docx`, and Postgres-in-prod needs `psycopg` (`requirements.txt`); all degrade gracefully
without. Tested on Python 3.9–3.10.

> ### Reviewers — start here
> **Try the live instance — no setup, no API key: [groundknowledge.org](https://groundknowledge.org)**
> — browse the cases, open a report (Coverage & warnings · Divergence matrix · Independence & bias ·
> Changes), or add a source to one. The **Independence** tab is the thesis made visible: each
> position shown as its count of genuinely independent evidence bases, with echo collapsed and
> circular citation flagged — plus a separate warning when evidence shares a correlated-error
> family (e.g. observational confounding) or a provenance quote doesn't match its fetched text.
>
> Or run it locally (core is pure stdlib — no `pip install`; find + fetch are keyless, only
> *labelling* needs a model):
> ```bash
> python -m app.portal                                   # your own portal → localhost:8800
> python cli.py ui                                       # the local workstation console
> # create a question and harvest it (AI discovery + label, or keyless --dry-run):
> python cli.py init salt "Does dietary salt raise cardiovascular risk?" --out cases/salt.kb.json
> python cli.py harvest cases/salt.kb.json
> python cli.py build cases/salt.kb.json && open viewer/index.html
> ```
>
> **Reading for the method?** [`MECHANISM.md`](MECHANISM.md) is the independence mechanism in
> plain language (ontology, algorithm, edge cases, adversarial robustness, why it's novel/general).
> [`SPEC.md`](SPEC.md) is the written submission; [`QUICKSTART.md`](QUICKSTART.md) is task-by-task.

## Run it (≈1 minute, no API key)

```bash
python cli.py show  cases/eggs.kb.json      # every metric, recomputed from a KB
python cli.py gaps  cases/eggs.kb.json      # where is the evidence thin?
python cli.py build cases/eggs.kb.json && open viewer/index.html
```

`cases/eggs.kb.json` maps a **real** dispute — 20 sourced studies with citable urls, funding
disclosures, and named cohorts (Zhong 2019 JAMA, Drouin-Chartier 2020 BMJ, Dehghan 2020 PURE, Qin
2018 China Kadoorie, Zhuang 2021 NIH-AARP, Fuller 2018 DIABEGG, Alexander/Tran industry meta-analyses,
Carson 2020 AHA, Hu 1999, …). **Verified vs authored:** anchor sources whose full text we could fetch
carry quotes checked against the real text (`verifiedQuote: exact`, `textDepth: full/partial`); the
rest are faithful reconstructions with **authored** quotes (`textDepth: unknown`), clearly marked.
An unverified newly proposed root contributes zero headline nEff unless a fetched dependency quote
verifies it or an explicit curator confirmation admits it. Two findings fall out of the data:

- **Funding skew (real):** the interested-money studies cluster on one answer — the two industry-funded
  meta-analyses (Alexander → American Egg Board; Tran → Egg Nutrition Center) both back *"No
  association,"* which is where the funding-skew flag points.
- **Independence (real):** the *"No association"* camp lists 9 sources but 6 resolve to the same
  Nurses' Health / Health Professionals cohort, so it is closer to **~4 independent bases than 9** —
  the shared-cohort collapse the source count hides.

### The update loop — recalculation made visible

```bash
cp cases/eggs.kb.json /tmp/eggs.json
python cli.py add   /tmp/eggs.json cases/eggs.delta-zhuang2021.json   # a real, independent cohort
python cli.py build /tmp/eggs.json                                    # rebuild; see the Changes tab
```

The added source is real — Zhuang 2021 (PLOS Medicine, NIH-AARP, 521,120 people, egg/cholesterol
→ higher mortality). It argues *"Increases risk"* and brings a **genuinely independent** cohort,
so the recompute *adds an independent base* to the minority camp rather than padding a count. A
naive aggregator just logs "+1 source"; here the **independence metric distinguishes independent
evidence from correlated evidence**, and the **Changes tab** records the recompute as a diff.

### Add a source — automatic, manual, or from a citation manager

```bash
# With any supported key (ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, …): fully automatic
python cli.py ingest cases/eggs.kb.json https://doi.org/10.1161/CIR.0000000000000743 --apply
python cli.py ingest cases/eggs.kb.json ./some-paper.pdf --apply        # PDF / docx / txt too

# Without a key: print the labelling prompt, paste into any chatbot, save its JSON, then merge:
python cli.py ingest cases/eggs.kb.json ./some-paper.pdf --dry-run
python cli.py add    cases/eggs.kb.json delta.json

# From Zotero / Mendeley / EndNote (.ris / .bib / .csl-json):
python cli.py import-citations cases/eggs.kb.json my-library.ris --apply
python cli.py export cases/eggs.kb.json --format bibtex
```

### Cold start & gap-driven deep search

```bash
python cli.py init eggs "Do eggs increase cardiovascular disease risk?" --out cases/eggs.kb.json
python cli.py harvest cases/eggs.kb.json --k 12              # AI discovery + label (default)
python cli.py deepen  cases/eggs.kb.json --rounds 3          # find thin spots → search them → repeat
```

**Discovery is AI-first** (the competition is about AI): the default `--source web` lets the model
search the web and propose real sources, told which sources are already in the KB so it returns
*new* ones. `--source api` uses keyless [OpenAlex](https://openalex.org) as a fallback, and
`--source both` merges. `--deep` runs an exhaustive multi-search pass. **`deepen`** is the
principled "deep search": it reads the independence audit for where evidence is *thin* (positions
with no independent primary evidence, datasets cited only via a review, blindspots, one-sided
factors), searches exactly there, ingests, and re-checks — letting you choose which gaps to pursue
each round, and always reporting what's still open (a plateau is a diagnostic, never a completeness
claim). *Web search / deep research need an Anthropic key; every provider can label fetched text.*

## How it generalises across case shapes

Same engine, only the KB JSON differs. Browse these on the [live portal](https://groundknowledge.org)
or `pull` them locally (`python cli.py pull <id>`):

- **Eggs (real, malformed question):** funding skew, modest real concentration, and a lone non-crux
  factor (subgroups, weighted `med` by *all* camps) flagging that "are eggs healthy?" is mis-posed —
  the answer is "for whom?".
- **COVID origin (contested):** the independence audit shows the headline honestly — the
  best-supported position rests on several genuinely independent primary datasets, while others
  turn out to rest on *zero* primary evidence (government reports / commentary collapsed to one
  voice each). Source counts alone hide this entirely.
- **Black holes (settled):** distribution collapses to "No risk", but the audit shows it resting on
  one load-bearing argument (the cosmic-ray empirical bound) — and the lone dissent attacks exactly
  that. The tool surfaces the single dependency of even a settled consensus (FLF's ask for this case).

## Two surfaces, one compounding knowledge base

- **The portal** (`python -m app.portal`) — a shared, multi-user site: browse and search questions,
  open the live report, and add sources **with no API key** (we fetch the best available text —
  open full text when accessible, otherwise abstract/metadata — you label it in *your own* chatbot
  via one downloadable file → import). The server does **no LLM work and holds no key** — merging is
  the deterministic stdlib function, so the hosted instance is cheap and has no
  key-trust problem. Admin moderation is gated by a shared token. Stores KBs as JSON documents
  (sqlite locally, Postgres in production — e.g. Railway). For the best, AI-driven retrieval, the
  portal points users to the CLI / local console.
- **The local workstation** (`python cli.py ui`, or the CLI) — for power users with their own key:
  it's **git for knowledge bases**. `pull` a question, `harvest`/`deepen` it with your own
  compute/key, `push` the result back (admin-token protected, optimistic version-locked). Discovery
  and fetch are keyless; only labelling uses your key, on your machine. Works with Anthropic, NVIDIA
  (free, build.nvidia.com), OpenAI, DeepSeek, Mistral, Groq, Gemini, or OpenRouter — and search vs.
  labelling pick a provider independently, so an Anthropic + NVIDIA pair does Claude web search with
  free NVIDIA labelling. Set `EPISTEMIC_LABEL_MODELS` to a comma-separated list to label with a
  multi-model **ensemble**: the labels are fused by a deterministic vote, and a genuine
  disagreement on a source's position surfaces in a **Needs-your-review** panel to resolve (pick a
  position or drop it) before it enters any metric.

Both write the same portable `cases/<id>.kb.json` through the same merge. Labelling reads the **full
open-access PDF** when one exists (richer positions, named datasets from the methods, and the
funding/COI statement the abstract omits), with a Crossref funder lookup as backup.

## Why this beats off-the-shelf deep research (the baseline)

Deep research answers *this* question *once*, as prose. This produces a **structured artifact**
another team can extend; every number is recomputed by one legible function; it **resists being
gamed by volume, echo, or circular citation**; it **shows what each new source changed**; and it
**compounds across contributors** through the portal. The value isn't a better paragraph — it's a
knowledge base that holds up under motivated reading and gets better as more people add to it.

## Honest limitations

- `cases/eggs.kb.json` is real and sourced (every entry has a citable url + funding + underlying
  dataset). Evidence tiers and provenance quotes come from the labelling pipeline, but most sources
  are abstract/unknown text depth and **dataset confirmation is curator-asserted, not fetch-verified**
  (no `restsOn` dependency quote has been checked against fetched text in this case yet — see the
  confirmation caveat below); positions and factor *weights* are a curator's faithful summary of each
  camp — the mechanical parts (datasets, funding, counts, independence) are what the metrics run on.
- **Independence depends on self-reported edges.** The mechanism collapses echo and detects circular
  citation, but only sees a dependency if the labeller recorded it. We don't crawl real citation
  graphs, so an adversary who *omits* a `src:` edge can still look more independent than they are —
  stated plainly in [`MECHANISM.md`](MECHANISM.md) §8 rather than papered over.
- **Tier classification** (primary vs secondary evidence) leans on the evidence label being right;
  a mislabel can mint or deny an independent base. Defenses: **ungrounded primaries pool to one
  voice per position** (a distinct root needs a *named* evidence base, not a claimed tier — so
  relabelling echo "Observational" can't inflate), unrecognised labels default to secondary,
  controlled vocab, relevance gate, funding-defaults-to-Undisclosed, and a multi-model **ensemble
  vote** that escalates genuine tier/position disagreements to a human review queue. Unverified
  named datasets add zero confirmed nEff; false confirmation or a blind spot shared across models
  remains possible.
- Entity resolution is normalized-string + alias matching — robust to casing/aliases, not to
  paraphrase. The `dups`/`merge` curation tools + a token-overlap suggester mitigate; embedding-match
  with human confirmation is the next step.
- The viewer is render-only by design; to see an update you re-run `build`.
