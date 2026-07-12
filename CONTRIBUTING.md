# Contributing to Ground Knowledge

Thanks for helping build a knowledge base that weights research disputes by **independent evidence**
instead of source count. This guide covers the dev loop, the invariants you must not break, and the
rules for confirming roots and curating a case. For the big picture read [`README.md`](README.md),
[`SUBMISSION.md`](SUBMISSION.md), and [`ALGORITHM.md`](ALGORITHM.md); for the mechanism and its open
problems read [`MECHANISM.md`](MECHANISM.md) and [`SCHEMA.md`](SCHEMA.md).

## Two surfaces, one rule

- **Engine + eval** (`engine/`, `eval/`, `cli.py` assessment path) — **pure, deterministic, stdlib
  only.** No LLM, no network, no third-party import in the assessment path. Every number the tool
  reports is a pure function of the KB. This is what makes the metric reproducible and auditable.
- **Deployment layer** (`app/`, `ingest/`) — the portal and the AI ingestion. Third-party packages
  live here and are all **lazy imports** (`pypdf`, `python-docx` for full-text/docx; `psycopg` for
  Postgres). Local dev uses the stdlib sqlite store; nothing in `requirements.txt` is needed to run
  the tests or the benchmark.

**The rule:** never introduce a dependency, network call, or nondeterminism into the engine/eval
path. If you need an LLM, it belongs in `ingest/` and must *propose*, never *decide*.

## Dev loop (zero setup)

```
python -m unittest discover -s tests -t .    # the whole suite, stdlib only, < 1s
python eval/run_benchmark.py                  # recall · collapse · adversarial · comparative
python cli.py assess cases/covid.kb.json      # full assessment for one case (JSON)
python cli.py show   cases/covid.kb.json      # human-readable view
python cli.py demo                            # one-command tour + benchmark
bash scripts/smoke.sh                         # everything above, as CI runs it
```

CI (`.github/workflows/ci.yml`) runs the suite on Python 3.10–3.13, validates every case KB, runs
the **strict** benchmark (`--require-live-baseline`, which hash-checks the baseline reports), and a
clean-clone smoke test. A PR must be green.

## Invariants you must not break

These are enforced by tests; if your change trips one, the design question is real — ask, don't
weaken the test.

1. **Independence monotonicity.** Adding a source never *lowers* any position's `nEff`. It rises
   only by introducing a genuinely new root or upgrading one (a primary source grounding a
   review-only dataset; human evidence for an animal-only root). Correlated/echo/circular sources
   land on already-counted roots and move `nEff` nowhere. (`tests/test_independence.py`, incl. a
   randomized property test.)
2. **Adversarial robustness contract.** +12 ungrounded echo raises `nEff` by ≤ 1.0 (they pool to one
   voice); +12 fabricated named datasets on the unverified path add **0** (quarantined). Executed on
   every case by the benchmark; must stay PASS.
3. **Determinism / no drift.** The viewer renders `engine/assess.assess()` output; it never
   recomputes. One `assess()` is one `resolve()`. Same KB in → same numbers out, always.
4. **Confirmation is per edge** (see below) — never re-widen it to a source-level boolean.

## How a knowledge base is shaped (`SCHEMA.md` is authoritative)

- **positions** — the camps.
- **datasets** — the underlying **evidence bases** (the JSON key stays `datasets` for back-compat).
  Each may carry a `kind`: `dataset | experiment | observation | argument | model | document`
  (absent = `dataset`). `argument`/`model`/`document` are **theoretical roots** — first-class
  independent bases, and exempt from the empirical (non-human population) discount. Give an argument
  root a `proposition` stating its claim.
- **sources** — each supports a position with an evidence tier, funding, population, and `restsOn`
  edges. A `restsOn` entry is a bare ref string (`"ds_x"` or `"src:<id>"`) **or** an edge object
  `{ref, provenance:{quote, verifiedQuote}}` carrying that edge's own dependency quote.
- **factors** — the cross-cutting questions; their per-position weights drive the crux taxonomy.

## Root-confirmation rules

A named dataset is not trusted just because a source claims it. A root is **provisional** — it
contributes **zero** to the headline `nEff` — until confirmed one of two auditable ways:

- **Curator confirmation.** A human vouches that the base is real, recorded as an *auditable object*
  `confirmation: {status:"confirmed", method:"curator", by, source, ts}` — **not** a bare boolean, so
  a reader can see *how* and *by whom* it was admitted. Use `engine.curate.confirm_dataset(...)`.
- **Verified edge.** A source that was actually fetched (`textDepth` full/abstract/partial) carries a
  dependency quote that verified against the fetched text **for that specific dataset edge**.

Two things are deliberately **not** enough (do not re-introduce them):

- a verified quote on one edge does **not** confirm sibling datasets on the same source — ten
  datasets need ten verified edges, not one;
- an inherited root (reached only through a `src:` citation) is **never** confirmed by the citing
  source's own quote — only a source that *directly* names the base can vouch for it.

On the untrusted paste-back path, `textDepth` and `verifiedQuote` are stripped, so a contributor can
never self-declare a fabricated edge as verified. Fabricated roots stay visible but quarantined.

## Curation rules

- **Propose, then deterministically resolve.** Ingestion *proposes* ids (or `NEW:<label>`);
  `engine/merge.py` *disposes* by normalized-string + alias matching. Never make resolution depend on
  LLM output. A cohort must not be smuggled in under five names — fold variants with an explicit
  `curate.merge` / learned alias, and dedupe sources by URL/DOI.
- **Finding paraphrase duplicates.** `python cli.py dups <kb>` suggests likely-same entities via
  acronym + token-overlap (deterministic, no key). Add `--embed` to *also* surface **semantic**
  paraphrases that lexical overlap misses (needs an OpenAI-compatible API key; backend in
  `ingest/embed.py`). These are **suggestions only** — every merge is an explicit `curate.merge`; the
  engine never auto-merges a semantic candidate, and the deterministic pipeline never depends on
  embeddings.
- **Evidence tier is load-bearing.** `primary` designs earn a distinct root by *naming* their data;
  ungrounded "primaries" that name nothing pool into one voice per position, as do reviews. A
  meta-analysis is `secondary` unless it tags the trials it pools. Add a genuinely new *primary
  design* to a case's `vocab.evidence` with `tier:"primary"`; don't hardcode.
- **Model theoretical arguments as `kind:"argument"` roots**, not empirical datasets, so a position
  resting on several independent arguments counts them independently (see the black-hole case).

## Submitting a change

1. Keep the engine/eval path stdlib-only and deterministic.
2. `bash scripts/smoke.sh` is green (tests + validation + strict benchmark + demo).
3. Add/adjust tests for new behavior; if you touched a case KB, keep `cli.py validate` clean and the
   benchmark PASS.
4. Update the docs you invalidated (`SCHEMA.md`, `MECHANISM.md`, `SUBMISSION.md`, `ALGORITHM.md`).
5. Match the surrounding code: comments explain *why*, not *what*; small, legible functions.

By contributing you agree your contribution is licensed under the repository's
[Apache-2.0 license](LICENSE).
