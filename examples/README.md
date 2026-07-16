# examples/ — copy-and-adapt delta templates

Each file here is a **well-formed `delta.json`** (it passes `python cli.py lint`) showing one common
shape. Copy the closest one, replace every quote with a **verbatim sentence from text you actually
fetched**, and adjust the labels — then `lint` → `add`. The authoritative field-by-field contract is
[`../prompts/ingest.md`](../prompts/ingest.md); this is the by-example companion to it.

| file | the pattern it shows |
| --- | --- |
| [`delta-primary-study.json`](delta-primary-study.json) | A **primary study** (RCT/cohort) that names its **own** evidence base in `restsOn`, plus a `factorWeights` entry. |
| [`delta-review-meta-analysis.json`](delta-review-meta-analysis.json) | A **review / meta-analysis** resting on the **cohorts it pools** — one reusing an existing `ds_…` id, one `NEW:` — each edge with its **own** dependency quote. |
| [`delta-nonempirical-document.json`](delta-nonempirical-document.json) | A base that is **not empirical data** — a document/grant proposal — tagged `"datasetKind": "document"` (also `"argument"` / `"model"`), which exempts it from the empirical discount. |
| [`delta-citation-echo.json`](delta-citation-echo.json) | **Echo / commentary** that grounds in no data of its own: it points at another source with a `NEW-SRC:` edge (or `SRC:<id>`) instead of fabricating a dataset, so the audit can see the echo. |
| [`delta-batch.json`](delta-batch.json) | A **batch array** — several deltas in one file; `add` merges them one at a time and diffs each. |

## Try one

```bash
cp examples/delta-primary-study.json /tmp/delta.json
# ...edit /tmp/delta.json: real title/url, and quotes copied from the fetched text...
python cli.py lint /tmp/delta.json                    # validates WITHOUT merging — no key
python cli.py add  cases/<your-case>.kb.json /tmp/delta.json
python cli.py doctor cases/<your-case>.kb.json
```

## The load-bearing rules these templates encode

- **`provenance.position`** is keyed by the literal string `"position"` and holds **one complete
  verbatim sentence** stating the source's stance. Not the title, not a heading, not boilerplate.
- **Each `restsOn` edge carries its own `provenance.quote`** — a separate sentence that names *that*
  dataset. One sentence must never vouch for several roots.
- **Reuse an existing `ds_…` id** when the cohort is already in the KB (run `python cli.py show
  <kb>` to see them); use `"NEW:<label>"` only for a genuinely new base. Same cohort across sources
  ⇒ same label — that is what the coverage audit collapses.
- **Never write `admission`, `verifiedQuote`, or `quoteVerification`.** The CLI produces those; if
  you write them they are stripped. `lint` will tell you when it sees one.
- A **citation edge** (`SRC:` / `NEW-SRC:`) needs no dependency quote — it names a source, not data.

See [`../AGENTS.md`](../AGENTS.md) for the full loop and the golden rules.
