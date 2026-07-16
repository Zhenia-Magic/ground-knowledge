# End-to-end CLI run — "Does dietary saturated fat increase cardiovascular disease risk?"

Date: 2026-07-16 · Portal: <https://groundknowledge.org/q/e9b9a1cd1960> · Artifact: `runs/saturated-fat-2026-07-16.kb.json`

A full run of the pipeline using **only the CLI** — question → harvest → deepen → curate → build →
push. This log records what actually happened, including the failures we hit and fixed, so the run
is reproducible and its limitations are honest.

## Commands (the happy path)

```bash
# 1. create the question locally
python cli.py new "Does dietary saturated fat increase cardiovascular disease risk?"
#    -> cases/34c53ea5e983.kb.json

# 2. harvest: discover + fetch + label.  With ANTHROPIC + NVIDIA keys set, Claude searches and
#    NVIDIA labels (the strong-search / free-label split).  --batch 1 = one source per label call.
export SSL_CERT_FILE=/etc/ssl/cert.pem      # macOS: point Python at the system CA bundle
python cli.py harvest cases/34c53ea5e983.kb.json --source both --k 16 --batch 1

# 3. deepen: gap-driven deep search, capped at ~$2 of estimated spend
python cli.py deepen cases/34c53ea5e983.kb.json --source both --budget 2 --all --batch 1

# 4. curate (all free, deterministic): confirm the real evidence bases and admit the support edges
python cli.py dups cases/34c53ea5e983.kb.json                      # no duplicates above threshold
for id in <dataset ids>; do
  python cli.py confirm-dataset cases/34c53ea5e983.kb.json "$id" --by "Evgeniia" --note "…"
done
for src ref in <unadmitted edges>; do
  python cli.py confirm-edge cases/34c53ea5e983.kb.json "$src" "$ref" --by "Evgeniia" --note "…"
done
python cli.py tidy cases/34c53ea5e983.kb.json                      # labels already clean
python cli.py validate cases/34c53ea5e983.kb.json                 # Valid KB schema v2
python cli.py show cases/34c53ea5e983.kb.json                     # inspect metrics

# 5. build + push
python cli.py build cases/34c53ea5e983.kb.json --out out.html
python cli.py push  cases/34c53ea5e983.kb.json --portal https://groundknowledge.org --as "Evgeniia"
#    -> Created question e9b9a1cd1960
```

## What the run produced

- **11 sources · 3 positions · 10 evidence bases** (0 factors — see limitations).
- Positions: *Saturated fat increases CVD risk* (6), *No clear effect* (4), *Replacing saturated fat
  with omega-6 linoleic acid increases CVD risk* (1).
- Evidence bases are the landmark trials/cohorts: **Oslo / Sydney / Minnesota Diet-Heart, DART,
  Veterans Admin, WHI, PURE, NIH-AARP**, plus pooled-cohort and pooled-linoleic-acid analyses.
- After confirming all 10 bases and admitting all 24 support edges: the *increases-risk* camp
  **collapses 6 sources → 4.5 adjusted evidence bases**, and Sydney Diet-Heart + the pooled cohorts
  are **reused across 5 of 11 sources (45%)** — a real reuse signal (Sydney and Minnesota are famous
  re-analysis cases). Whole-case coverage is ~11 (near 1:1: an 11-source sample spread thin across
  distinct trials, so the *net* collapse is modest — it would grow with more sources on shared data).

## Failures hit — and fixed

The first two harvest attempts crashed. Both were real robustness bugs in `ingest/pipeline.py`
(`ingest_batch`), now fixed and covered by `tests/test_merge_positions.IngestBatchResilienceTests`:

1. **One dropped connection killed the whole harvest.** A source fetch raised
   `http.client.RemoteDisconnected`; the loop only caught `SystemExit`, so the exception aborted the
   batch with **0 sources saved** — after the (paid) discovery had already run. Fix: catch
   `(SystemExit, OSError, http.client.HTTPException)` and skip that source.
2. **One malformed LLM response killed the whole harvest.** NVIDIA returned invalid JSON for a batch
   ("Could not parse model JSON"); that `SystemExit` propagated and aborted everything. Fix: retry
   the label call once, then skip that group; also skip an individual invalid delta. Dropping to
   `--batch 1` keeps a bad response to one source instead of four.

## External blockers (not code — quota/billing)

- **OpenAlex** now uses a prepaid model and returned `429 — Insufficient budget … resets at midnight
  UTC`. So `--source api` (keyless scholarly discovery) is unavailable when the daily free budget is
  exhausted; per-work metadata fetches also lean on it. Fetch still succeeds for most sources via the
  Europe PMC / reader-proxy fallbacks in `ingest/extract.py`.
- **Anthropic** web search needs credit; discovery via Claude only runs with a funded key.

## Limitations of this run (why it is a demo, not a submission-grade case)

- **0 factors.** The free NVIDIA labeller did not emit `factorWeights`, so the *Key issues*
  (divergence) view is empty. The prompt requests them; a stronger (Claude) labelling pass, or manual
  factor curation, would populate the cruxes.
- **Abstract-only quotes.** Sources were fetched as abstracts, so provenance quotes are unverified
  (shown as summaries, not checkmarks). Coverage counts only because a curator admitted the
  identity + edges; a full-text quote-audit (`scripts/audit_quotes.py`) would upgrade these.
- Kept **out of the repo's audited `cases/`** for those reasons (it would fail the quote-audit-scope
  and edge-admission drift gates). It lives on the portal and as this artifact.

## Cost

Discovery ran on the topped-up Anthropic key ($5 budget); labelling was free on NVIDIA. The deepen
step was stopped early — its gap-searches kept returning papers already in the case (no net new
sources), so it was burning budget without adding value.
