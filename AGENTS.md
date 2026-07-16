# AGENTS.md — build a case with your agent, no API key

**Audience: Claude Code, Codex, or any coding agent.** You are reading this because someone wants
to grow or fill in a Ground Knowledge case (an epistemic-dispute knowledge base) and would rather
spend their Claude/Codex *subscription* than wire up a separate model API key.

That works because **you are the model.** The `harvest` / `deepen` CLI commands normally call a paid
LLM API to search the web and label sources. When an agent is driving, you do that part yourself —
your own web search and reading — and hand the result to the **deterministic CLI**, which does the
part that must not be left to a model: verifying quotes against the fetched text, stripping any
trust claims you assert, de-duplicating evidence, and merging into the knowledge base.

So the division of labour is:

| You (the agent)                                   | The CLI (deterministic, trusted)                        |
| ------------------------------------------------- | ------------------------------------------------------- |
| Find real sources on the web                      | Fetch/verify, merge, recompute every metric             |
| Read them and write a `delta.json` per source     | Re-verify each quote against the text it fetched        |
| Reuse existing entity IDs; keep extraction honest | Strip `admission` / `verifiedQuote` you supplied        |
| Run `lint` → `add` → `doctor`                     | Refuse off-topic / duplicate / malformed deltas         |

You never hand-edit the KB JSON. You write **deltas** and run `add`. The KB is the CLI's to change.

---

## For the person setting this up — how to actually run it

*(This section is for the human operator. The agent can read it too; the rest of the file is the
agent's playbook.)*

**You need:** a coding agent that can **browse/search the web** — Claude Code or Codex — opened in a
clone of this repo. No API key, no `pip install` for the core loop (Python 3.10+ stdlib). The agent
supplies the search + reading; the CLI does the rest.

**1. Open your agent in the repo.** Claude Code auto-loads `CLAUDE.md` → this file; Codex auto-loads
this file. So the playbook is already in context — you don't paste it in.

**2. Point it at a case and say what to add.** Example prompts you can paste verbatim:

> *"Read AGENTS.md. Add 3 recent sources on statins and cardiovascular mortality to
> `cases/eggs.kb.json` — for each: search the web, read it, write a delta, `lint` it, then `add` it.
> Run `doctor` when you're done and tell me what still needs a curator."*

> *"Start a new case: `python cli.py new \"Does intermittent fasting improve metabolic health?\"`,
> then follow the AGENTS.md loop to fill it with 6–8 sources covering each side. Show me `doctor` at
> the end."*

> *"Run `python cli.py gaps cases/covid.kb.json`, then find and add one source for the single
> thinnest gap. Lint before adding."*

**3. Your job while it runs** (the few things the agent can't or shouldn't decide alone):

- **Position-split reviews.** If two labels disagree on a source's stance, `add` parks it in a review
  queue instead of guessing — the agent will surface it; you pick the position or drop the source.
- **Curator confirmations.** A new evidence base stays *proposed* (counts toward nothing) until a
  human confirms it: `python cli.py confirm-dataset <kb> <id> --by "<you>"` and, to admit a support
  edge, `confirm-edge`. `doctor` lists what's still proposed. Do this yourself, or tell the agent to
  do it *as you* only if you've checked the base is real — it's an identity decision, not a label.
- **The `doctor` gate before you publish.** Skim its output; resolve the ⚠ items or accept them
  knowingly. Then `python cli.py build <kb> --out out.html` (local view) or `push` (to the portal).

**Where your work lands:** everything is in `cases/<id>.kb.json` — one portable JSON file you own.
The agent grows it; you view it with `build`, or `pull`/`push` it to a portal.

**One caveat:** the CLI in this mode does **not** search for the agent — it fetches a *given* URL
(`ingest --dry-run`) and does all the deterministic work, but *finding* sources is the agent's own
web-search capability. An agent without web access can only work from URLs you hand it.

---

## Golden rules (read before writing any JSON)

1. **Never invent a quote.** Every `quote` must be copied character-for-character from text you
   actually fetched and read for *that* source. No quote from memory, from the search snippet, from
   the title, or from a different paper. If you can't find a sentence that states the finding, lower
   `extractionConfidence` (≤ 0.3) or leave `quote` empty — an empty quote is fine, a fabricated one
   corrupts the audit.
2. **Never write trust fields.** Do not emit `admission`, `verifiedQuote`, or `quoteVerification`.
   Those are produced only by the CLI's fetched-text verification or by an authenticated human
   curator. If you write them, the CLI strips them (see *The trust boundary* below) — so at best
   they are ignored, and asserting them is a bug in your output.
3. **Reuse entity IDs; do not proliferate.** Prefer an existing `position` / `dataset` / `factor`
   over a new one. A shared cohort under a new name defeats the whole point (the coverage audit
   collapses shared evidence to one root). Introduce `"NEW:<label>"` only for something genuinely
   distinct. The merge code — not you — mints IDs.
4. **`lint` before `add`; `doctor` before you hand off.** These are your guardrails. `lint` catches
   a malformed delta *without* touching the KB; `doctor` tells you whether the case is in good shape
   to submit. Both exit nonzero on failure, so they compose in a script.
5. **One source → one delta.** The cold start is this loop run over many sources; an update is one
   run. Same path. Keep each delta about a single source you read.

---

## The loop

Run everything from the repo root. Core commands (`init`, `lint`, `add`, `doctor`, `show`, `gaps`,
`build`, `validate`) need **no packages and no key**.

```bash
# 0. Pick a case, or start one.
python cli.py init eggs "Do eggs raise cardiovascular risk?" --out cases/eggs.kb.json
#   ... or work on an existing cases/<id>.kb.json

# 1. See where the evidence is thin. This is your steering wheel — it prints the questions
#    to search next, ranked by severity. --json gives machine-readable gap queries.
python cli.py gaps cases/eggs.kb.json
python cli.py gaps cases/eggs.kb.json --json      # for programmatic looping

# 2. SEARCH THE WEB YOURSELF for real sources answering those gap queries (your own tools).
#    Prefer primary studies, cohorts, trials, and systematic reviews over news/blogs.

# 3. FETCH THE REAL TEXT. Two ways:
#    (a) let the CLI fetch + hand you the exact labelling contract for a URL/DOI/PMID/arXiv id:
python cli.py ingest "https://doi.org/10.xxxx/xxxxx" cases/eggs.kb.json --dry-run
#        -> writes an ingest-prompt file: the fetched text + the schema + the current entity tables.
#    (b) or read the source with your own fetch/browse tools.
#    Either way, WRITE QUOTES ONLY FROM TEXT YOU ACTUALLY HAVE.

# 4. WRITE delta.json for that one source, following prompts/ingest.md exactly (schema below).

# 5. LINT it — no merge, no mutation, numbered actionable errors:
python cli.py lint delta.json

# 6. ADD it — the CLI verifies quotes, strips your trust claims, dedupes, merges, recomputes,
#    and prints exactly what changed:
python cli.py add cases/eggs.kb.json delta.json

# 7. Repeat 1–6 until `gaps` is quiet or you've covered the dispute.

# 8. HEALTH CHECK before handing off:
python cli.py doctor cases/eggs.kb.json

# 9. Build a local viewer to eyeball it (optional):
python cli.py build cases/eggs.kb.json --out out.html
```

`add` also accepts a **batch array** of deltas in one file (`[ {delta}, {delta}, ... ]`) — it merges
them one at a time, each recomputing and diffing against the prior KB. `lint` accepts the same array.

---

## The delta format

The full, authoritative contract — every field, every rule that prevents entity proliferation and
ungrounded positions — is **[`prompts/ingest.md`](prompts/ingest.md)**. Read it. The shape:

```jsonc
{
  "source": {
    "title": "...", "year": 2020, "url": "...",
    "position": "pos_none" | "NEW:Some new stance",   // the source's DIRECTIONAL answer to the question
    "evidence": "Observational",                       // closest existing type, or "NEW:<label>"
    "funding": "Industry" | "Government/public" | "Academic/institutional" | "Undisclosed" | ...,
    "population": "US health professionals",           // the studied GROUP; "—" if not specific
    "confidence": "moderate",                          // the source's OWN stated strength
    "restsOn": [                                        // the PRIMARY evidence bases it stands on
      { "ref": "ds_nhs", "provenance": {
          "quote": "Participants were drawn from the Nurses' Health Study.",
          "extractionConfidence": 0.9 }},
      { "ref": "NEW:US pooled meta", "provenance": {
          "quote": "We pooled individual-level data from the US cohorts.",
          "extractionConfidence": 0.8 }}
    ],
    "provenance": {
      "position": { "quote": "<one verbatim sentence stating the finding>", "extractionConfidence": 0.85 }
    }
  },
  "factorWeights": [
    { "factor": "Discount for healthy-user confounding", "weight": "low",
      "quote": "...", "rationale": "..." }
  ]
}
```

The load-bearing decisions (all detailed in `prompts/ingest.md`):

- **`position`** is the *answer to the question* (increases / decreases / no clear effect / it
  depends). A mechanism, biomarker, subgroup, or funding point is **not** a position — it's a
  `factorWeight`. Keep positions to ~3–5.
- **`restsOn`** names the underlying cohorts / trials / datasets. Same cohort across sources ⇒ the
  **same** label. A primary study names its *own* data; a review `restsOn` the cohorts it *pools*,
  not "the literature". To cite another source (echo / commentary), use `"SRC:<id>"` or
  `"NEW-SRC:<title>"` instead of inventing a dataset for it.
- **`datasetKind`** — most bases are empirical data and need nothing. When a base is a document
  (grant proposal, memo, leaked record), an `argument` (a chain of reasoning), or a `model`
  (a calculation), write the edge as an object and add `"datasetKind": "document" | "argument" |
  "model"`. Those are exempt from the empirical animal/in-vitro discount. Nothing else is a valid
  `datasetKind`, and you may not set `admission` on an edge.
- **`provenance`** — one complete verbatim sentence per position, and a *separate* one per dataset
  edge that specifically names that dataset as evidence this source used. Never let one sentence
  vouch for several roots. Never quote a title, heading, or boilerplate line.

**Copy-and-adapt templates live in [`examples/`](examples/)** — one per common shape (a primary
study naming its own base, a review resting on pooled cohorts, a non-empirical `document`, an
echo/commentary `NEW-SRC:` edge, and a batch array). Each one already passes `lint`; start from the
closest and swap in your fetched title/URL and *real* quotes. `prompts/ingest.md`'s "Output schema"
section has an inline filled example too, and `cli.py ingest --dry-run` prints a ready-to-fill
prompt for a specific source.

---

## The trust boundary — what the CLI ignores from you

`add` sanitizes every delta before it touches the KB. Anything in this list that you write is
**silently dropped** (the CLI re-derives it from fetched text or a curator action):

- `source.provenance.*.verifiedQuote` and `.quoteVerification` — the CLI re-verifies each quote
  against the text *it* fetched, and stamps the result itself.
- `source.restsOn[*].admission` — admitting a root is a **curator** decision, never a claim in a delta.
- `source.restsOn[*].provenance.verifiedQuote` / `.quoteVerification` — same re-verification.
- `source.textDepth` — reset to `"unknown"`; depth only counts for text the CLI fetched.
- `factorWeights[*].verifiedQuote` / `.quoteVerification`.

`lint` will *tell you* which of these it sees (as `note:` lines) so you can stop writing them, but it
won't fail on them — they're harmless, just ignored. Everything else (structure, types, bounds, valid
`datasetKind`, reused-vs-NEW refs) `lint` and `add` **do** enforce, and a violation rejects the delta.

You literally cannot corrupt the KB through `add`: an off-topic source is refused (and logged), a
duplicate is dropped (anti-flooding), a malformed delta is rejected with numbered errors, and a
model-split on position is queued for a human rather than guessed.

---

## Curation — the human's job, not yours

Two things only an authenticated curator does (via the CLI or the portal), because they're identity
and admission decisions the model isn't trusted to make:

- `python cli.py confirm-dataset <kb> <dataset-id> --by "<name>" --note "..."` — confirm that a
  proposed evidence base is really the study it claims to be.
- `python cli.py confirm-edge <kb> <source-id> <ref> --by "<name>" --note "..."` — admit a specific
  source→root support edge.

Until a base is confirmed (or grounded by a verified exact quote) it stays **proposed** and does not
count toward coverage. `doctor` reports how many are still proposed. Surface that to the human — don't
try to route around it.

---

## Reference — every command you'll use

| Command | What it does | Needs a key? |
| --- | --- | --- |
| `init <id> <question> --out <kb>` | Create an empty case | no |
| `gaps <kb>` / `gaps <kb> --json` | Where evidence is thin; the search steering wheel | no |
| `ingest <url> <kb> --dry-run` | Fetch text + print the labelling prompt for one source | no |
| `lint <delta-or-kb>` | Validate WITHOUT merging; numbered errors; nonzero on failure | no |
| `add <kb> <delta>` | Verify + sanitize + dedupe + merge one delta or a batch array | no |
| `doctor <kb>` | Health check: structure + completeness + trust hygiene | no |
| `validate <kb>` | Strict schema + cross-reference check | no |
| `show <kb>` | Print the metrics (distribution, coverage, warnings) | no |
| `build <kb...> --out <html>` | Build the standalone viewer | no |
| `confirm-dataset` / `confirm-edge` | **Curator** admission (a human, not you) | no |
| `harvest` / `deepen` | The *keyed* auto-pipeline — you replace these with your own search | yes (skip it) |

**Pre-flight before every `add`:** `python cli.py lint delta.json`
**Handoff gate when you're done:** `python cli.py doctor cases/<id>.kb.json` — resolve the flags, or
tell the human which ones need a curator.

**Templates to copy:** [`examples/`](examples/) — one well-formed delta per shape, each lint-clean.

For the bigger picture — the metric, the schema, the deployment — see
[`WORKFLOW.md`](WORKFLOW.md), [`SCHEMA.md`](SCHEMA.md), and [`README.md`](README.md).
