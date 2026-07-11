# Deep-research baselines

This directory contains two live independent baseline sets over the same three questions:

- ChatGPT Deep Research captures at the directory root;
- Claude Code web-research captures under `claude-code/`.

Both use the operator-confirmed prompt files and hashed provenance manifests. They were run without
the repository, case source lists, or Ground Knowledge framework. The former authored COVID stand-in
is retained as `covid.authored-standin.md` for audit history but is not an active baseline.

Record capture provenance in `manifest.json` (model/product, timestamp, and prompt/output SHA-256).
Then run `python eval/run_benchmark.py --require-live-baseline`. Submission CI should use this strict
mode: it verifies that all captures are marked independent, required provenance fields exist, files
are present, and prompt/output hashes match.

The comparison in `eval/RESULTS.md` treats the baseline seriously: the reports themselves notice
shared evidence and recycled arguments. They remain prose rather than a recomputable root graph,
versioned contributor artifact, or executable adversarial contract.

Export caveat: the Markdown downloads preserve ChatGPT's internal citation tokens but not portable
URLs. Retain the original chat/share links or PDF exports alongside the submission.
