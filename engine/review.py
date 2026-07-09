"""Human-in-the-loop resolution for ensemble label disagreements.

When the labelling models split on a source's POSITION (ingest/ensemble.py flags it), the source
is NOT merged with a tie-break guess — it is queued in kb["pendingReview"] for the person running
the ingestion to decide: pick one of the models' proposed positions (or any existing position),
or drop the paper. The queue lives in the KB file itself, so it persists, travels with the case,
and is resumable like everything else. Pending entries are NOT sources: no metric counts them.

Consumers: the local console (review panel + /api/review endpoints) and the CLI (an interactive
prompt during harvest/ingest when run in a terminal; queued otherwise).
"""
import uuid

from .merge import merge_delta, norm, now_iso, source_key


def needs_review(delta):
    """True when this delta's ensemble labelling had no majority position."""
    src = (delta or {}).get("source") or {}
    return bool((src.get("modelAgreement") or {}).get("flagged"))


def pending_keys(kb):
    """Dedupe keys (url / title+year) of everything already awaiting review."""
    return {source_key(p.get("delta", {}).get("source") or {})
            for p in kb.get("pendingReview", [])}


def queue_for_review(kb, delta):
    """Park a flagged delta for human resolution. Returns the entry, or None when the same
    source is already queued OR already merged (a resumed run must not double-queue, and a
    duplicate must not be re-litigated). Mutates kb; caller persists."""
    src = delta.get("source") or {}
    key = source_key(src)
    if key in pending_keys(kb) or key in {source_key(s) for s in kb.get("sources", [])}:
        return None
    ma = src.get("modelAgreement") or {}
    entry = {
        "id": "pr_" + uuid.uuid4().hex[:8],
        "title": src.get("title") or "(untitled)",
        "url": src.get("url"), "year": src.get("year"),
        "abstract": delta.get("reviewText") or "",
        "proposals": ma.get("proposals") or
            [{"position": k, "votes": v, "quote": "", "confidence": None}
             for k, v in (ma.get("positionVote") or {}).items()],
        "delta": {k: v for k, v in delta.items() if k != "reviewText"},
        "ts": now_iso(),
    }
    kb.setdefault("pendingReview", []).append(entry)
    return entry


def _pop(kb, pr_id):
    pend = kb.get("pendingReview", [])
    entry = next((p for p in pend if p.get("id") == pr_id), None)
    if entry is None:
        raise ValueError("no pending review item '{}'".format(pr_id))
    kb["pendingReview"] = [p for p in pend if p.get("id") != pr_id]
    return entry


def resolve_review(kb, pr_id, action, position=None):
    """Apply the human's decision to a queued item.

    action="drop"     -> discard the source (logged; never merged).
    action="position" -> merge the queued delta with the CHOSEN position (an existing position id,
                         an existing label, or a NEW:<label>); the disagreement flag is cleared and
                         the human resolution recorded on the source's modelAgreement.
    Returns the merge report (or {"dropped": True}). Mutates kb; caller persists."""
    entry = _pop(kb, pr_id)
    if action == "drop":
        kb.setdefault("log", []).append({
            "version": kb["meta"].get("version", 0), "action": "review-drop",
            "title": entry["title"], "ts": now_iso(),
            "summary": "dropped after model disagreement: " + entry["title"]})
        return {"dropped": True, "title": entry["title"]}
    if action != "position":
        raise ValueError("action must be 'position' or 'drop'")
    chosen = (position or "").strip()
    if not chosen:
        raise ValueError("pick a position (or drop the source)")
    delta = entry["delta"]
    src = delta.setdefault("source", {})
    # accept an existing position id, an existing label, a proposed label, or NEW:<label>
    if not chosen.startswith("NEW:"):
        known_ids = {p["id"] for p in kb["positions"]}
        known_labels = {norm(p["label"]): p["id"] for p in kb["positions"]}
        if chosen not in known_ids:
            chosen = known_labels.get(norm(chosen.replace("NEW:", ""))) or "NEW:" + chosen
    src["position"] = chosen
    ma = src.setdefault("modelAgreement", {})
    ma["flagged"] = False
    ma["resolvedBy"] = "human"
    ma["resolvedTo"] = chosen
    return merge_delta(kb, delta)
