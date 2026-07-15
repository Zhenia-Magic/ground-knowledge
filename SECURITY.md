# Security and trust boundaries

Ground Knowledge treats model output, public contributions, remote URLs, uploaded files, and stored
JSON as untrusted. The metric is deterministic, but its answer is only as reliable as the admitted
graph. This document states what code is allowed to create trust and what remains a human judgement.

## The central rule

A model may **propose** a source, root, quote, position, and factor. It may not admit them as trusted.
Only deterministic verification of text the system actually fetched, or an authenticated curator,
can create a trust record.

- `engine/validate.py` rejects malformed deltas and model-supplied `admission` objects before merge.
- Batched labelling binds each result to an opaque `sourceId`; missing, repeated, and unknown IDs are
  rejected. Output order is never used as identity.
- URL, title, authors, venue, citation count, and retraction status from the fetch replace model
  claims. Quote verification is computed only against the exact text slice shown to that model.
- `engine/migrate.py` validates KB shape, IDs, references, admissions, factor claims, and vocabulary
  before a full document is accepted. Migration never invents verification or confirmation.
- Public paste-back contributions enter a review queue and affect no metric until reviewed.

Quote verification proves only that displayed wording occurs in the fetched material. It does not
prove the paper is correct, that the sentence entails the assigned label, or that an omitted
dependency does not exist.

## Hosted portal protections

- Whole-KB replacement, moderation, reader-study results, and deletion require `ADMIN_TOKEN`.
- Every stored write advances a server revision. A stale writer receives a conflict instead of
  overwriting newer work. The KB and its audit entry commit in the same database transaction.
- Remote fetches accept only absolute HTTP(S) URLs whose DNS answers are globally routable. The
  connection is pinned to a validated address, redirects are rechecked, proxy environment variables
  are ignored, credentials in URLs are rejected, and response size is capped.
- Request bodies, fetch URL counts, delta batches, PDF pages, source text, request threads, expensive
  concurrent operations, and per-IP mutation rates are bounded. Security headers include a content
  security policy, MIME sniffing protection, referrer policy, and HSTS on production requests.
- Question-list cards use indexed summary columns instead of loading every KB document.

The built-in limiter is per process. A multi-replica deployment should also use a shared edge or
gateway rate limit.

## Local console protections

The console binds to localhost and rejects non-local Host/Origin values. Case IDs are constrained to
safe names, resolved paths must remain inside the case directory, uploads are size/type limited, and
JSON writes use a temporary file plus `fsync` and atomic replacement. The local console is not an
internet-facing service and should not be exposed through port forwarding or a public proxy.

## Reader-study data

Assignments are generated and stored by the server under single-use opaque tokens. Submitted case
sets must exactly match the assignment, client-supplied condition labels are ignored, and results
require administrator authentication. Participant tokens should never contain names or email
addresses. No reader-study result is claimed in this repository.

## Known limits

- A curator can still make a wrong semantic decision, confirm a false root, or accept an incorrect
  factor weight. The audit trail makes this reviewable; software cannot make it true.
- A source or model can omit a real citation/dependency edge. External citation-graph comparison is
  future work.
- Lexical duplicate blocking cannot prove two semantically renamed roots are the same. Embedding
  suggestions and human review reduce this risk but do not eliminate it.
- In-process limits do not coordinate across replicas, and the stdlib server is intended for the
  current modest load behind Railway's proxy, not as a general high-volume edge server.
- Remote content may be malicious or misleading even when transport and address checks pass. It is
  treated as text, capped, and never executed.

For mechanism-level epistemic failure modes, see [`MECHANISM.md`](MECHANISM.md). For release and
rollback operations, see [`DEPLOYMENT.md`](DEPLOYMENT.md).
