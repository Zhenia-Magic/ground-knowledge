# CLAUDE.md

This repo is **Ground Knowledge** — a living, recomputing knowledge base for research disputes.

**If you are here to grow or fill in a case (add sources, deepen the evidence, fix a delta), read
[`AGENTS.md`](AGENTS.md) first.** It is the playbook for driving this repo with your subscription
instead of an API key: you do the web search and reading; the deterministic CLI (`lint` → `add` →
`doctor`) verifies, sanitizes, and merges. The golden rules there are non-negotiable — most
importantly: never invent a quote, never write trust fields (`admission` / `verifiedQuote`), reuse
existing entity IDs, and always `lint` a delta before `add`.

Quick pointers:

- **Build a case:** [`AGENTS.md`](AGENTS.md) — the keyless agent loop, the delta format, the guardrails.
- **How to use the tool by hand:** [`WORKFLOW.md`](WORKFLOW.md)
- **Data model:** [`SCHEMA.md`](SCHEMA.md)
- **The metric and why it's built this way:** [`README.md`](README.md), [`MECHANISM.md`](MECHANISM.md)
- **Deploying the portal:** [`DEPLOYMENT.md`](DEPLOYMENT.md)

Pre-flight before any `add`: `python cli.py lint delta.json`.
Health check before you hand off: `python cli.py doctor cases/<id>.kb.json`.
