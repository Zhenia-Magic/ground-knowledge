# WORKFLOW — how to use the tool

A practical runbook. Pick the section that matches what you want to do. Every command below
is real and runnable from the repo root.

---

## 0. One-time setup

- **Python 3.10+.** The core (build a viewer, read metrics, merge sources, `--dry-run`
  ingestion) needs **no packages**.
- **Optional — document ingestion:** `pip install -r requirements.txt` (only for `.pdf` / `.docx`).
- **Reading sources needs no key.** A paper is resolved by its DOI/PMID/arXiv id through open APIs
  (and the full open-access PDF when there is one) — keyless and free of publisher scraping.
- **Discovery is AI-first.** By default the model searches the web for real sources (told what's
  already in the KB so it returns *new* ones); a keyless OpenAlex search is the `--source api`
  fallback. *AI web search / deep research need an Anthropic key; every provider can label.*
- **Automatic labelling — set one API key (your choice of provider):**

  ```bash
  export ANTHROPIC_API_KEY=sk-ant-...   # Claude (recommended; needed for web search), or any of:
  export NVIDIA_API_KEY=...             # free (build.nvidia.com) — labels by default when set
  export OPENAI_API_KEY=...  DEEPSEEK_API_KEY=...  MISTRAL_API_KEY=...  GROQ_API_KEY=...
  export GEMINI_API_KEY=...  OPENROUTER_API_KEY=...
  # export EPISTEMIC_SEARCH_PROVIDER=... EPISTEMIC_LABEL_PROVIDER=...  # pin a phase's provider
  # export EPISTEMIC_SEARCH_MODEL=...  EPISTEMIC_LABEL_MODEL=...       # pin a phase's model
  # export EPISTEMIC_LABEL_MODELS=z-ai/glm-5.2,openai/gpt-oss-120b,mistralai/mistral-nemotron  # ensemble
  # export EPISTEMIC_RATE_LIMIT_RPM=40   # cap req/min for the free provider (ensemble pacing)
  # export EPISTEMIC_MODEL=...   # legacy global override (single-provider setups only)
  # export EPISTEMIC_PORTAL=https://groundknowledge.org   # for pull/push
  # export EPISTEMIC_CONTACT_EMAIL=you@org        # faster OpenAlex "polite pool"
  ```
  Search and labelling pick their provider independently (Claude searches, the first other key —
  NVIDIA free first — labels); the local console's **Models & access** panel shows and pins this
  per session.
  Without a key you use the *manual path*: the tool finds + fetches sources for free, then prints a
  labelling prompt (or a single bundle file) to paste into any chatbot; you paste the JSON back.
  A multi-source bundle gives every source an opaque `sourceId`. Return every ID exactly once; if an
  item is missing, duplicated, or renamed, the import stops instead of guessing which fetched text
  belongs to which label.

**Two modes — know which you're in:**

| | With an API key | Without a key |
|---|---|---|
| Find sources | `harvest` / `discover` — AI web search (or `--source api`) | OpenAlex (`--source api`) works keyless |
| Read a source | by identifier via OpenAlex/arXiv/etc — **same** | **same** — fetch is keyless |
| Label a source | `ingest <link/doc> --apply` is automatic | `ingest --dry-run` prints a prompt; you paste, save JSON, `add` it |
| Everything else | identical | identical |

The mechanical layers (merge, metrics, viewer) are **always** deterministic and offline; reading is
a keyless API call. Only *labelling* a fetched source (and AI discovery) uses an LLM.

---

## 1. Mental model (the whole tool in one picture)

```
                    you pick a question
                            │
          ┌─────────────────▼─────────────────┐
          │   discover → OpenAlex finds papers   │   Ingestion
          │   fetch    → API reads by identifier │   (search·API, fetch·API,
          │   label    → LLM tags the text       │    label·LLM)
          └─────────────────┬─────────────────┘
                            │  delta (one structured source)
                            ▼
                  merge  →  cases/<id>.kb.json      ← the artifact you own & share
                  (entity resolution; dedupe)        (one JSON file)
                            │
                            ▼
                  assess → every metric, recomputed (deterministic)
                            │
                            ▼
                  build  →  viewer/index.html         ← self-contained; double-click to open
```

**`cases/<id>.kb.json` is the thing you own.** Commands read and update it; the viewer is just a
baked snapshot of it. Cold-start and "add one source later" are the *same* action repeated.

---

## A. Look at what's already here (30 seconds)

```bash
python cli.py show  cases/eggs.kb.json                      # metrics in the terminal
python cli.py build cases/eggs.kb.json  # bake the viewer
open viewer/index.html                                      # or double-click it
```

The viewer has four tabs — Overview, Key issues, Evidence reuse, Changes (see §D).

---

## B. Start a NEW question from scratch (cold start)

```bash
python cli.py init eggs "Do eggs increase cardiovascular disease risk?" --out cases/eggs.kb.json
```

Then populate it. **With an API key — one command:**

```bash
python cli.py harvest cases/eggs.kb.json --k 10 --build
```

`harvest` = OpenAlex finds candidate papers → fetch each by identifier (no scraping) → label +
merge → rebuild the viewer. It's resumable: re-run it and already-known sources are skipped.

**Without a key — the manual path (finding + fetching are still automatic):**

```bash
python cli.py discover cases/eggs.kb.json --k 10 > candidates.json   # 1. OpenAlex search, no key
#    (real papers with DOIs — no chatbot needed for this step)
python cli.py ingest cases/eggs.kb.json <link> --dry-run     # 2. per link: fetches text, prints a labelling prompt
#    paste that → save the JSON it returns as delta.json
python cli.py add cases/eggs.kb.json delta.json --build      # 3. merge it + rebuild
#    repeat 2–3 for each link
```

---

## C. Add a source you already have (a link OR a document)

**With a key (automatic):**

```bash
python cli.py ingest cases/eggs.kb.json https://www.bmj.com/content/368/bmj.m513 --apply --build
python cli.py ingest cases/eggs.kb.json ./paper.pdf  --apply --build     # PDF / docx / html / txt
```

**Without a key (manual):**

```bash
python cli.py ingest cases/eggs.kb.json ./paper.pdf --dry-run   # prints the extraction prompt
#   paste into any LLM → save its JSON as delta.json
python cli.py add cases/eggs.kb.json delta.json --build
```

**If the labelling ensemble disagrees** on a source's position, the source is NOT merged: in a
terminal you are asked right there (abstract + each model's proposal — pick a position or drop
it); in the console (or a non-interactive run) it lands in a **Needs your review** panel, and
the case chip shows a ⏸ count until you resolve it. Pending sources count in no metric.

Either way the terminal prints **WHAT CHANGED** (which metrics moved), and it's appended to the
viewer's **Changes** tab. Duplicate sources (same url, or title+year) are refused automatically.

---

## D. Read the outputs — what each view answers

| View | Question it answers | Watch for |
|------|--------------------|-----------|
| **Overview** | Who holds which position? Where's the industry money? | the **funding-skew** banner — which camp industry funding favours; a **shared-method-bias** banner when many sources lean on the same correlated-error family |
| **Key issues** | What do the camps *actually* disagree on? | rows badged **KEY DISAGREEMENT** (spread ≥2); the rest is hidden agreement |
| **Evidence reuse** | Is the source list concentrated on the same admitted evidence bases? | a camp marked **CONCENTRATED** + the case-wide most-reused dataset; the same method-bias warning, plus an **unverified-quote** warning when a full-text source's quote doesn't match its fetched text |
| **Changes** | What did each new source do to the picture? | concentration/​distribution shifts, new key disagreements, blindspots opening/closing |

Reading rules of thumb:
- **High concentration = weak consensus.** "5 sources, 80% on one dataset" ≈ ~2 independent looks.
  Adding *correlated* sources makes this **worse**, not better — by design.
- **Funding skew** is a flag to weigh, not a verdict: it tells you where to apply scrutiny.
- **Few key disagreements** is the normal, healthy finding: most disagreement is local.
- **Method-bias and quote warnings never change the independence count.** They're a separate
  signal shown alongside it, not folded into the number — see `MECHANISM.md` §12.
- **An unverified quote only means something on a full-text source.** The same "missing" verdict
  on an abstract-only source is expected — the tool never had the text to check against.

Prefer the terminal? `python cli.py show <kb>` prints the same summary;
`python cli.py assess <kb>` dumps the full metrics as JSON (for scripting / diffing).

---

## E. Share it / hand it off

- **For a person:** send `viewer/index.html` — it's self-contained, opens with a double-click,
  no server or internet needed.
- **For another team to extend:** send `cases/<id>.kb.json` — the portable artifact. They run
  `build` to view it, and `ingest`/`add` to keep growing it. Nothing is locked in the UI.

When syncing through the hosted portal, the response's top-level `version` is a server revision,
not the KB's `meta.version`. `push` sends that revision back automatically. If another contributor
writes first, the portal returns a conflict; pull the latest KB, reapply/review your change, and push
again. Every accepted KB write and its contribution-log entry are committed together.

---

## F. Drive it with a coding agent (no API key)

If a coding agent (Claude Code, Codex, …) is doing the work, you don't need an LLM key at all —
**the agent is the model.** It does the web search and reading that `harvest`/`deepen` would pay an
API for, and hands each source to the deterministic CLI, which stays the trust boundary. The full
playbook is **[`AGENTS.md`](AGENTS.md)** (Claude Code auto-loads it via `CLAUDE.md`; Codex auto-loads
`AGENTS.md`). The loop:

```bash
python cli.py gaps   cases/<id>.kb.json            # 1. where is the evidence thin? (steering wheel)
#  2. the agent searches the web itself for sources answering those gaps, and reads them
#     (or: python cli.py ingest <url> cases/<id>.kb.json --dry-run  to fetch text + the label prompt)
#  3. the agent writes delta.json for ONE source, quoting only text it actually fetched
python cli.py lint   delta.json                    # 4. validate WITHOUT merging — numbered errors, no key
python cli.py add    cases/<id>.kb.json delta.json # 5. verify quotes + strip trust claims + dedupe + merge
#  repeat 1–5 until `gaps` is quiet
python cli.py doctor cases/<id>.kb.json            # 6. health check before you hand off
```

The guardrails an agent leans on:

- **`lint`** never mutates anything — it just tells the agent what's malformed (numbered) and which
  hand-written trust fields (`verifiedQuote`, `admission`) the merge will ignore. Run it before every `add`.
- **`add`** is un-foolable: it re-verifies each quote against the text *it* fetched, strips any
  `admission`/`verifiedQuote` the model wrote, refuses off-topic/duplicate sources, and rejects a
  malformed delta with a clean numbered report (no traceback, KB untouched).
- **`doctor`** is the handoff gate: structure (hard-fails on broken cross-refs), completeness
  (empty positions, proposed-vs-confirmed bases, orphan bases), and trust hygiene. Warnings don't
  block a build; broken structure does.

**Golden rules for the agent** (full list in `AGENTS.md`): never invent a quote, never write trust
fields, reuse existing entity IDs, one source per delta, `lint` before `add`.

---

## Command reference

| Command | What it does |
|---------|-------------|
| `new "<question>"` | **create a question locally** (git-style; hex id like the portal) — work on it, then `push` |
| `init <id> "<question>" --out cases/<id>.kb.json` | create an empty KB with an explicit id (scripting) |
| `harvest <kb> [--k N] [--source web\|api\|both] [--deep] [--build]` | **cold start in one go** (key for labelling): search → fetch all → label → build |
| `discover <kb> [--k N] [--source web\|api\|both] [--deep] [--dry-run]` | find candidates: **AI web search (default)**, keyless OpenAlex, or both; `--k 0` = no limit; `--deep` = exhaustive pass |
| `deepen <kb> [--rounds N] [--source …] [--all]` | **gap-driven deep search**: find thin spots → search them → ingest → repeat (you pick which gaps) |
| `deepen <kb> --budget 3` | **thorough mode**: keep going until ~$3 (estimated) is spent or the gaps run dry; reports the spend |
| `gaps <kb> [--json]` | show where evidence is thin (steers `deepen`) |
| `ingest <kb> <link-or-file> [--apply] [--build] [--dry-run]` | fetch one source → label → delta (→ merge → build) |
| `lint <delta.json\|kb>` | **validate WITHOUT merging** — numbered errors, nonzero exit; the pre-flight for agent-written JSON (keyless) |
| `add <kb> <delta.json> [--build]` | merge a delta you already have; prints WHAT CHANGED (rejects a malformed delta cleanly) |
| `doctor <kb>` | **health check** — structure + completeness + trust hygiene; the handoff gate (keyless) |
| `import-citations <kb> <file> [--apply]` · `export <kb> --format bibtex\|ris\|csl` | Zotero/Mendeley/EndNote in & out |
| `show <kb>` · `assess <kb>` | metrics summary in the terminal · full metrics as JSON |
| `build <kb> [<kb2> ...] [--out FILE]` | bake the viewer (multiple KBs ⇒ a case switcher) |
| `pull <id>` · `push <kb>` · `questions` | sync with the portal (set `EPISTEMIC_PORTAL`). A **new/empty** question `push`es **keylessly** (the server strips trust records — confirmations, verified quotes, the curated badge); replacing a question that already has sources needs `--token` |

## Recipes

- **See an update in the viewer:** add `--build` to any `add`/`ingest`, or re-run `build`.
- **Resume an interrupted harvest:** just run `harvest` again — done sources are skipped.
- **Curate by hand:** `cases/<id>.kb.json` is plain JSON. Edit it, then `build`. (Keep `restsOn`
  pointing at real dataset ids; see `SCHEMA.md`.)
- **One viewer, several disputes:** `build cases/eggs.kb.json cases/<another>.kb.json` → switcher.
