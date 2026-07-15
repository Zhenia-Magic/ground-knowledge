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
    agreement = src.get("modelAgreement")
    return bool(isinstance(agreement, dict) and agreement.get("flagged"))


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
    _bump(kb, "queue-review", "queued for human review: " + entry["title"])
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
        kb["meta"]["version"] = kb["meta"].get("version", 0) + 1   # a real decision: version it
        kb["meta"]["updated"] = now_iso()
        kb.setdefault("log", []).append({
            "version": kb["meta"]["version"], "action": "review-drop",
            "title": entry["title"], "ts": kb["meta"]["updated"],
            "summary": "dropped after model disagreement: " + entry["title"]})
        return {"dropped": True, "title": entry["title"]}
    if action != "position":
        raise ValueError("action must be 'position' or 'drop'")
    chosen = _position_ref(kb, position)
    delta = entry["delta"]
    src = delta.setdefault("source", {})
    src["position"] = chosen
    ma = src.setdefault("modelAgreement", {})
    ma["flagged"] = False
    ma["resolvedBy"] = "human"
    ma["resolvedTo"] = chosen
    report = merge_delta(kb, delta)
    if report.get("duplicate"):
        _bump(kb, "review-duplicate", "removed duplicate review item: " + entry["title"])
    return report


def _position_ref(kb, chosen):
    """Normalize a human's position choice to something merge/_resolve_position accepts: an
    existing id, an existing label mapped to its id, or NEW:<label>. Raises on empty."""
    chosen = (chosen or "").strip()
    if not chosen:
        raise ValueError("pick a position (or drop the source)")
    if chosen.startswith("NEW:"):
        return chosen
    if chosen in {p["id"] for p in kb["positions"]}:
        return chosen
    by_label = {norm(p["label"]): p["id"] for p in kb["positions"]}
    return by_label.get(norm(chosen)) or "NEW:" + chosen


def _bump(kb, action, summary):
    kb["meta"]["version"] = kb["meta"].get("version", 0) + 1
    kb["meta"]["updated"] = now_iso()
    kb.setdefault("log", []).append({"version": kb["meta"]["version"], "action": action,
                                     "summary": summary, "ts": kb["meta"]["updated"]})


def _review_item(kind, ident, title, url, year, abstract, proposals, current=None):
    return {"kind": kind, "id": ident, "title": title or ident, "url": url, "year": year,
            "abstract": abstract or "", "currentPosition": current,
            "proposals": proposals or []}


def flagged_sources(kb):
    """Already-MERGED sources that still carry an unresolved disagreement flag — labelled with a
    tie-break guess (legacy path, or the paste-back path that has no queue). They belong in the
    same review UI as pending items, so a disagreement is resolvable no matter how it was created.
    Proposals reconstruct from the stored vote (older sources have no per-proposal quotes)."""
    out = []
    for s in kb.get("sources", []):
        ma = s.get("modelAgreement") or {}
        if not ma.get("flagged"):
            continue
        props = ma.get("proposals") or [{"position": k, "votes": v, "quote": "", "confidence": None}
                                        for k, v in (ma.get("positionVote") or {}).items()]
        out.append(_review_item("flagged", s["id"], s.get("title"), s.get("url"), s.get("year"),
                                "", props, current=s.get("position")))
    return out


def review_items(kb):
    """Everything awaiting a human position decision: not-yet-merged queue items AND already-merged
    flagged sources. One list so the console and portal render a single review panel."""
    pend = [_review_item("pending", p["id"], p.get("title"), p.get("url"), p.get("year"),
                         p.get("abstract"), p.get("proposals")) for p in kb.get("pendingReview", [])]
    return pend + flagged_sources(kb)


def review_count(kb):
    return len(kb.get("pendingReview", [])) + len(flagged_sources(kb))


def resolve_flagged_source(kb, sid, action, position=None):
    """Re-decide an ALREADY-MERGED flagged source, in place (no un-merge):
      action="position" -> change its position to the chosen one and clear the flag.
      action="accept"   -> keep the tie-break label; just clear the flag (the guess was right).
      action="drop"     -> remove the source and prune its factor provenance.
    Mutates kb; caller persists. Metrics recompute from the KB either way."""
    s = next((x for x in kb.get("sources", []) if x.get("id") == sid), None)
    if s is None:
        raise ValueError("no source '{}'".format(sid))
    title = s.get("title") or sid
    if action == "drop":
        kb["sources"] = [x for x in kb["sources"] if x.get("id") != sid]
        for f in kb.get("factors", []):
            f["provenance"] = [pv for pv in f.get("provenance", []) if pv.get("source") != sid]
        from .curate import repoint_confirmation_source
        repoint_confirmation_source(kb, sid, reason="supporting source dropped during human review")
        from .merge import recompute_factor_weights
        recompute_factor_weights(kb)
        _bump(kb, "review-drop", "dropped after model disagreement: " + title)
        return {"dropped": True, "title": title}
    ma = s.setdefault("modelAgreement", {})
    if action == "accept":
        ma["flagged"] = False
        ma["resolvedBy"] = "human"
        _bump(kb, "review-accept", "kept the label despite model disagreement: " + title)
        return {"resolved": sid, "position": s.get("position"), "kept": True}
    if action != "position":
        raise ValueError("action must be 'position', 'accept', or 'drop'")
    from .merge import _resolve_position
    pid, created = _resolve_position(kb, _position_ref(kb, position))
    s["position"] = pid
    ma["flagged"] = False
    ma["resolvedBy"] = "human"
    ma["resolvedTo"] = pid
    _bump(kb, "review-resolve",
          "re-labelled after model disagreement: {} -> {}".format(title, pid))
    return {"resolved": sid, "position": pid, "newPosition": created}
