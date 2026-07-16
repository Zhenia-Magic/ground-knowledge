"""Curation ops (workstream B): merge near-duplicate entities and rename labels.

Deterministic, no LLM. These clean up the residue the string-matching resolver can't catch on
its own — paraphrase duplicates that slip in as a case grows (e.g. three "Women (mixed …)"
population terms). Every op leaves the KB internally consistent, so the metrics in assess.py
just recompute. Each op bumps the version and appends a log entry, so the Changes tab records
the curation alongside source additions.
"""
import copy

from .merge import norm, now_iso, prettify_label


# ---- reference resolution: accept an id, an exact label, or a unique substring -------------
def _resolve(items, ref, kind):
    ref_s = str(ref or "").strip()
    for it in items:                                   # exact id
        if it.get("id") == ref_s:
            return it
    n = norm(ref_s)
    exact = [it for it in items if norm(it["label"]) == n]
    if exact:
        return exact[0]
    sub = [it for it in items if n and n in norm(it["label"])]
    if len(sub) == 1:
        return sub[0]
    if len(sub) > 1:
        raise ValueError("'{}' is ambiguous among {} {}s — use the id".format(ref, len(sub), kind))
    raise ValueError("no {} matches '{}'".format(kind, ref))


def _resolve_source(kb, ref):
    """Resolve a source by id, exact title, or a unique title substring."""
    ref_s = str(ref or "").strip()
    sources = kb.get("sources", [])
    for source in sources:
        if source.get("id") == ref_s:
            return source
    n = norm(ref_s)
    exact = [source for source in sources if norm(source.get("title")) == n]
    if exact:
        return exact[0]
    sub = [source for source in sources if n and n in norm(source.get("title"))]
    if len(sub) == 1:
        return sub[0]
    if len(sub) > 1:
        raise ValueError("'{}' is ambiguous among {} sources — use the id".format(ref, len(sub)))
    raise ValueError("no source matches '{}'".format(ref))


def _vocab_kind(kind):
    if kind not in ("evidence", "population"):
        raise ValueError("vocab kind must be 'evidence' or 'population'")
    return kind


def dedupe_sources(kb):
    """Remove duplicate SOURCES (the same paper ingested twice): same canonical id (DOI/PMID/PMCID),
    or same year with one title a prefix of the other (catches publisher-vs-PMC title-truncation).
    Keeps the entry with the most text/provenance; re-points source edges, root confirmations, and
    factor provenance off the dropped ids."""
    from engine.merge import paper_ident, norm
    srcs = kb["sources"]

    def _richness(s):
        return (len((s.get("provenance") or {})), len(s.get("restsOn") or []), len(s.get("title") or ""))

    keep, dropped = [], []                         # dropped: (loser_id, winner_id)
    for s in srcs:
        ident = paper_ident(s)
        tn, yr = norm(s.get("title")), str(s.get("year") or "")
        match = None
        for k in keep:
            ki, ktn, kyr = paper_ident(k), norm(k.get("title")), str(k.get("year") or "")
            same_id = ident and ki == ident
            same_paper = (yr and yr == kyr and tn and ktn and min(len(tn), len(ktn)) >= 25 and
                          (tn.startswith(ktn) or ktn.startswith(tn)))
            if same_id or same_paper:
                match = k
                break
        if not match:
            keep.append(s)
            continue
        winner, loser = (s, match) if _richness(s) > _richness(match) else (match, s)
        if winner is s:                            # the new one is richer: swap it in
            keep[keep.index(match)] = s
        dropped.append((loser["id"], winner["id"]))

    if not dropped:
        return {"version": kb["meta"].get("version", 0), "summary": "no duplicate sources found",
                "removed": []}
    remap = dict(dropped)
    resolved_remap = {}
    for loser, winner in dropped:
        # A richer duplicate source replaces the old id everywhere, including optional dataset
        # confirmation support. Follow a short replacement chain if successive duplicates folded.
        final = winner
        seen_chain = {loser}
        while final in remap and final not in seen_chain:
            seen_chain.add(final)
            final = remap[final]
        resolved_remap[loser] = final
        repoint_confirmation_source(kb, loser, final, "duplicate source merged into retained record")
    kept_ids = {s["id"] for s in keep}
    kb["sources"] = keep
    for source in keep:
        edges = source.get("restsOn", [])
        for loser, winner in resolved_remap.items():
            edges = _repoint_and_dedup_edges(edges, "src:" + loser, "src:" + winner)
        source["restsOn"] = _without_self_source_edges(edges, source["id"])
    for f in kb["factors"]:                        # re-point or drop provenance of removed sources
        prov = []
        for p in f.get("provenance", []):
            sid = resolved_remap.get(p.get("source"), p.get("source"))
            if sid in kept_ids:
                p = dict(p); p["source"] = sid; prov.append(p)
        f["provenance"] = _dedupe_claims(prov)
    from engine.merge import recompute_factor_weights
    recompute_factor_weights(kb)
    removed = [{"removed": lid, "kept": resolved_remap[lid]} for lid, _wid in dropped]
    return dict(_commit(kb, "dedupe-sources",
                        "removed {} duplicate source(s)".format(len(dropped))), removed=removed)


def _commit(kb, action, summary):
    v = (kb["meta"].get("version", 0) or 0) + 1
    kb["meta"]["version"] = v
    kb["meta"]["updated"] = now_iso()
    kb.setdefault("log", []).append(
        {"version": v, "action": action, "summary": summary, "ts": kb["meta"]["updated"]})
    return {"version": v, "summary": summary}


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _edge_ref(edge):
    return str(edge.get("ref") or "").strip() if isinstance(edge, dict) else str(edge or "").strip()


def _verified_rank(value):
    status = (value or {}).get("verifiedQuote") if isinstance(value, dict) else None
    return {"exact": 3, "fuzzy": 2, "missing": 1}.get(status, 0)


def _merge_edge_objects(left, right):
    """Combine collapsed edges without discarding the stronger provenance/admission audit."""
    if not isinstance(left, dict):
        return right
    if not isinstance(right, dict):
        return left
    out = dict(left)
    lp, rp = left.get("provenance"), right.get("provenance")
    if isinstance(rp, dict) and (not isinstance(lp, dict) or
                                 _verified_rank(rp) > _verified_rank(lp)):
        out["provenance"] = copy.deepcopy(rp)
    if not isinstance(out.get("admission"), dict) and isinstance(right.get("admission"), dict):
        out["admission"] = copy.deepcopy(right["admission"])
    return out


def _dedupe_claims(claims):
    """Keep the best-audited claim for each source/position after entity folding."""
    out, where = [], {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        key = (claim.get("source"), claim.get("pos"))
        rank = (_verified_rank(claim), len(str(claim.get("quote") or "")),
                bool(claim.get("quoteVerification")))
        if key not in where:
            where[key] = len(out); out.append(claim)
            continue
        old = out[where[key]]
        old_rank = (_verified_rank(old), len(str(old.get("quote") or "")),
                    bool(old.get("quoteVerification")))
        if rank > old_rank:
            out[where[key]] = claim
    return out


def _repoint_and_dedup_edges(edges, src_id, dst_id):
    """Rewrite dataset refs inside both string and object edges, deduping by resolved ref.

    When a bare edge and a provenance-carrying object collapse to the same target, keep the object:
    dropping its dependency quote during curation would erase the audit trail.
    """
    out, where = [], {}
    for edge in edges or []:
        ref = _edge_ref(edge)
        if not ref:
            continue
        if ref == src_id:
            if isinstance(edge, dict):
                edge = dict(edge)
                edge["ref"] = dst_id
            else:
                edge = dst_id
            ref = dst_id
        key = ref.lower() if ref.lower().startswith("src:") else ref
        if key not in where:
            where[key] = len(out)
            out.append(edge)
        else:
            out[where[key]] = _merge_edge_objects(out[where[key]], edge)
    return out


def _without_self_source_edges(edges, source_id):
    """Drop a citation edge that became self-referential after two source records were folded."""
    self_ref = "src:" + str(source_id)
    return [edge for edge in edges if _edge_ref(edge) != self_ref]


def repoint_confirmation_source(kb, source_id, replacement=None, reason=None):
    """Maintain dataset-confirmation integrity when a supporting source is removed or deduped.

    Curator confirmations remain valid without their optional supporting-source pointer, but the
    removal is recorded. A `verified-edge` record is different: deleting its verification source
    removes the basis for admission, so it becomes provisional. Dedupe operations repoint either
    method to the retained source.
    """
    changed = 0
    why = reason or "supporting source removed"
    for d in kb.get("datasets", []):
        c = d.get("confirmation")
        if not isinstance(c, dict) or c.get("source") != source_id:
            continue
        if replacement:
            c["source"] = replacement
            c.setdefault("sourceHistory", []).append({"from": source_id, "to": replacement,
                                                       "ts": now_iso(), "reason": why})
        elif c.get("method") == "verified-edge":
            d["confirmation"] = {"status": "provisional", "ts": now_iso(),
                                 "note": why + "; verified-edge admission withdrawn"}
        else:
            c.pop("source", None)
            c.setdefault("sourceHistory", []).append({"removed": source_id, "ts": now_iso(),
                                                       "reason": why})
        changed += 1
    return changed


def remove_source(kb, ref, reason, by, replacement=None):
    """Remove an irrelevant or duplicate source without leaving stale derived state.

    A reason and curator identity are mandatory because relevance is an editorial judgment.  If
    ``replacement`` is supplied, source-to-source edges, factor provenance, and dataset-confirmation
    support are redirected to that retained record; otherwise those dependencies are withdrawn.
    Evidence bases referenced only by the removed source are pruned as orphans.  Factor cells are
    then re-derived from their remaining provenance claims.
    """
    reason = str(reason or "").strip()
    by = str(by or "").strip()
    if not reason:
        raise ValueError("source removal requires a reason")
    if not by:
        raise ValueError("source removal requires a curator identity")
    source = _resolve_source(kb, ref)
    target = _resolve_source(kb, replacement) if replacement else None
    if target and target.get("id") == source.get("id"):
        raise ValueError("replacement is the source being removed")
    sid = source["id"]
    target_id = target.get("id") if target else None
    source_ref = "src:" + sid
    target_ref = "src:" + target_id if target_id else None

    # Only datasets touched by this source are candidates for pruning; pre-existing empty/proposed
    # entities are not silently swept up by an unrelated curation action.
    candidate_datasets = {
        _edge_ref(edge) for edge in source.get("restsOn", [])
        if _edge_ref(edge) and not _edge_ref(edge).lower().startswith("src:")
    }

    rewired = 0
    for other in kb.get("sources", []):
        if other is source:
            continue
        edges = []
        for edge in other.get("restsOn", []):
            if _edge_ref(edge) != source_ref:
                edges.append(edge)
                continue
            rewired += 1
            if not target_ref:
                continue
            if isinstance(edge, dict):
                edge = dict(edge)
                edge["ref"] = target_ref
            else:
                edge = target_ref
            edges.append(edge)
        # Deduplicate after a replacement, retaining verified provenance/curator admission.
        other["restsOn"] = _without_self_source_edges(
            _repoint_and_dedup_edges(edges, "__never__", "__never__"), other.get("id"))

    for factor in kb.get("factors", []):
        claims = []
        for claim in factor.get("provenance", []):
            if claim.get("source") == sid:
                if not target_id:
                    continue
                claim = dict(claim)
                claim["source"] = target_id
            claims.append(claim)
        factor["provenance"] = _dedupe_claims(claims)

    repoint_confirmation_source(kb, sid, target_id, reason)
    kb["sources"] = [item for item in kb.get("sources", []) if item.get("id") != sid]

    used_datasets = {
        _edge_ref(edge) for item in kb.get("sources", []) for edge in item.get("restsOn", [])
        if _edge_ref(edge) and not _edge_ref(edge).lower().startswith("src:")
    }
    orphaned = sorted(candidate_datasets - used_datasets)
    if orphaned:
        kb["datasets"] = [d for d in kb.get("datasets", []) if d.get("id") not in orphaned]

    from engine.merge import recompute_factor_weights
    recompute_factor_weights(kb)
    summary = "removed source “{}”: {}".format(source.get("title"), reason)
    report = _commit(kb, "remove-source", summary)
    kb["log"][-1].update({"source": sid, "title": source.get("title"), "by": by,
                           "reason": reason, "replacement": target_id,
                           "rewiredEdges": rewired, "prunedDatasets": orphaned})
    report.update({"removed": sid, "replacement": target_id, "rewiredEdges": rewired,
                   "prunedDatasets": orphaned})
    return report


def move_source(kb, ref, position_ref, reason, by):
    """Re-file a source under a different existing position, preserving an editorial audit trail."""
    reason = str(reason or "").strip()
    by = str(by or "").strip()
    if not reason:
        raise ValueError("source move requires a reason")
    if not by:
        raise ValueError("source move requires a curator identity")
    source = _resolve_source(kb, ref)
    position = _resolve(kb.get("positions", []), position_ref, "position")
    old = source.get("position")
    if old == position.get("id"):
        raise ValueError("source is already filed under that position")
    source["position"] = position["id"]
    for factor in kb.get("factors", []):
        for claim in factor.get("provenance", []):
            if claim.get("source") == source.get("id") and claim.get("pos") == old:
                claim["pos"] = position["id"]
    from engine.merge import recompute_factor_weights
    recompute_factor_weights(kb)
    old_label = next((p.get("label") for p in kb.get("positions", []) if p.get("id") == old), old)
    summary = "moved source “{}”: “{}” → “{}”".format(
        source.get("title"), old_label, position.get("label"))
    report = _commit(kb, "move-source", summary)
    kb["log"][-1].update({"source": source.get("id"), "title": source.get("title"),
                           "from": old, "to": position.get("id"), "by": by, "reason": reason})
    report.update({"source": source.get("id"), "from": old, "to": position.get("id")})
    return report


def _merge_confirmation(src, dst):
    """Preserve admission audit records when two dataset identities are explicitly merged."""
    src_c = copy.deepcopy(src.get("confirmation"))
    dst_c = dst.get("confirmation")
    src_confirmed = isinstance(src_c, dict) and src_c.get("status") == "confirmed"
    dst_confirmed = isinstance(dst_c, dict) and dst_c.get("status") == "confirmed"
    if src_confirmed and not dst_confirmed:
        src_c.setdefault("mergedFrom", []).append({"dataset": src["id"], "label": src["label"],
                                                    "ts": now_iso()})
        dst["confirmation"] = src_c
        dst.pop("confirmed", None)
    elif src_confirmed and dst_confirmed:
        dst_c.setdefault("mergedConfirmations", []).append({
            "dataset": src["id"], "label": src["label"], "confirmation": src_c,
            "ts": now_iso(),
        })
    elif src.get("confirmed") and not dst_confirmed and not dst.get("confirmed"):
        # Preserve the old boolean only for legacy files; the audit migration can convert it later.
        dst.pop("confirmation", None)
        dst["confirmed"] = True


# ---- merges -------------------------------------------------------------------------------
def merge_positions(kb, src_ref, dst_ref):
    """Fold position src into dst: reassign its sources, move its factor weights (dst wins on
    conflict), re-point provenance, drop src."""
    src = _resolve(kb["positions"], src_ref, "position")
    dst = _resolve(kb["positions"], dst_ref, "position")
    if src["id"] == dst["id"]:
        raise ValueError("source and target are the same position")
    moved = 0
    for s in kb["sources"]:
        if s["position"] == src["id"]:
            s["position"] = dst["id"]
            moved += 1
    for f in kb["factors"]:
        for p in f.get("provenance", []):
            if p.get("pos") == src["id"]:
                p["pos"] = dst["id"]
        f["provenance"] = _dedupe_claims(f.get("provenance", []))
    kb["positions"] = [p for p in kb["positions"] if p["id"] != src["id"]]
    from engine.merge import recompute_factor_weights
    recompute_factor_weights(kb)
    return _commit(kb, "merge-position",
                   "merged position “{}” → “{}” ({} sources)".format(src["label"], dst["label"], moved))


def merge_datasets(kb, src_ref, dst_ref):
    """Fold dataset src into dst: rewrite restsOn references, learn src's label as a dst alias
    (so future ingests of the same name resolve correctly), drop src. This is what restores an
    honest independence/concentration reading when one cohort got split under two names."""
    src = _resolve(kb["datasets"], src_ref, "dataset")
    dst = _resolve(kb["datasets"], dst_ref, "dataset")
    if src["id"] == dst["id"]:
        raise ValueError("source and target are the same dataset")
    n = 0
    for s in kb["sources"]:
        ro = s.get("restsOn", [])
        if any(_edge_ref(edge) == src["id"] for edge in ro):
            s["restsOn"] = _repoint_and_dedup_edges(ro, src["id"], dst["id"])
            n += 1
    dst.setdefault("aliases", [])
    for al in [src["label"]] + src.get("aliases", []):
        if al not in dst["aliases"]:
            dst["aliases"].append(al)
    _merge_confirmation(src, dst)
    kb["datasets"] = [d for d in kb["datasets"] if d["id"] != src["id"]]
    return _commit(kb, "merge-dataset",
                   "merged dataset “{}” → “{}” ({} sources)".format(src["label"], dst["label"], n))


def merge_factors(kb, src_ref, dst_ref):
    """Fold factor src into dst: merge weights (dst wins on conflict) and provenance, drop src."""
    src = _resolve(kb["factors"], src_ref, "factor")
    dst = _resolve(kb["factors"], dst_ref, "factor")
    if src["id"] == dst["id"]:
        raise ValueError("source and target are the same factor")
    dst.setdefault("provenance", []).extend(src.get("provenance", []))
    dst["provenance"] = _dedupe_claims(dst["provenance"])
    if not dst.get("rationale") and src.get("rationale"):
        dst["rationale"] = src["rationale"]
    kb["factors"] = [f for f in kb["factors"] if f["id"] != src["id"]]
    from engine.merge import recompute_factor_weights
    recompute_factor_weights(kb)
    return _commit(kb, "merge-factor",
                   "merged factor “{}” → “{}”".format(src["label"], dst["label"]))


def merge_vocab(kb, kind, src_label, dst_label):
    """Fold one evidence/population term into another: re-point sources, learn src as an alias
    of dst, drop src."""
    kind = _vocab_kind(kind)
    terms = kb.setdefault("vocab", {}).setdefault(kind, [])
    src = _resolve(terms, src_label, kind)
    dst = _resolve(terms, dst_label, kind)
    if norm(src["label"]) == norm(dst["label"]):
        raise ValueError("source and target are the same term")
    n = 0
    for s in kb["sources"]:
        if s.get(kind) == src["label"]:
            s[kind] = dst["label"]
            n += 1
    dst.setdefault("aliases", [])
    for al in [src["label"]] + src.get("aliases", []):
        if al not in dst["aliases"]:
            dst["aliases"].append(al)
    kb["vocab"][kind] = [t for t in terms if norm(t["label"]) != norm(src["label"])]
    return _commit(kb, "merge-vocab",
                   "merged {} “{}” → “{}” ({} sources)".format(kind, src["label"], dst["label"], n))


def rename(kb, kind, ref, new_label):
    """Rename a position / dataset / factor / evidence / population label. For datasets and
    vocab the old label is kept as an alias so future ingests still resolve to it. Good for the
    ugly auto-generated labels (e.g. 'UK_Biobank_206263_women_aged_40_69')."""
    new_label = (new_label or "").strip()
    if not new_label:
        raise ValueError("new label is empty")
    if kind == "position":
        e = _resolve(kb["positions"], ref, "position")
        old = e["label"]; e["label"] = new_label
    elif kind == "factor":
        e = _resolve(kb["factors"], ref, "factor")
        old = e["label"]; e["label"] = new_label
    elif kind == "dataset":
        e = _resolve(kb["datasets"], ref, "dataset")
        old = e["label"]
        e.setdefault("aliases", [])
        if old not in e["aliases"]:
            e["aliases"].append(old)
        e["label"] = new_label
    elif kind in ("evidence", "population"):
        terms = kb.setdefault("vocab", {}).setdefault(kind, [])
        t = _resolve(terms, ref, kind)
        old = t["label"]
        for s in kb["sources"]:
            if s.get(kind) == old:
                s[kind] = new_label
        t.setdefault("aliases", [])
        if old not in t["aliases"]:
            t["aliases"].append(old)
        t["label"] = new_label
    else:
        raise ValueError("unknown type '{}'".format(kind))
    return _commit(kb, "rename", "renamed {} “{}” → “{}”".format(kind, old, new_label))


_ROOT_KINDS = {"dataset", "document", "argument", "model"}


def set_kind(kb, ref, kind):
    """Set an evidence base's KIND: dataset | document | argument | model.

    'dataset' is the empirical default and is stored implicitly (the field is removed so the KB stays
    clean); document/argument/model are theoretical roots — a proposal/record, a chain of reasoning,
    a model/calculation — and are exempt from the empirical (non-human) discount (engine/roots
    ._NON_EMPIRICAL_KINDS). Display-and-discount only; it never changes a root's admission."""
    k = str(kind or "dataset").strip().lower()
    if k not in _ROOT_KINDS:
        raise ValueError("kind must be one of {}".format(sorted(_ROOT_KINDS)))
    d = _resolve(kb["datasets"], ref, "dataset")
    if k == "dataset":
        d.pop("kind", None)
    else:
        d["kind"] = k
    return _commit(kb, "set-kind", "set kind of “{}” to {}".format(d["label"], k))


def confirm_dataset(kb, ref, confirmed=True, by=None, method="curator", source=None, note=None,
                    allow_similar=False, embed=None):
    """Curator vouches that a dataset is a REAL, identified evidence base (or un-vouches it).
    A confirmed dataset root counts at full strength; an unconfirmed one asserted only by
    unverified/paste-back input is quarantined at zero (see engine/roots.root_strength). This is how
    a human resolves the 'is this a fabricated root?' question the arithmetic can't answer.

    Writes an AUDITABLE confirmation record — {status, method, by, ts, source?, note?} — rather than an
    opaque boolean, so a reader can see HOW and by WHOM a root was admitted (engine/roots
    ._dataset_confirmation). The legacy `confirmed` flag is removed once the object is written; it is
    still honored on read for KBs that predate this."""
    d = _resolve(kb["datasets"], ref, "dataset")
    if confirmed:
        actor = str(by or "").strip()
        if method != "curator":
            raise ValueError("manual confirmation method must be 'curator'; verified edges are admitted automatically")
        if not actor:
            raise ValueError("curator confirmation requires a non-empty 'by' identity")
        if source and not any(s.get("id") == source for s in kb.get("sources", [])):
            raise ValueError("confirmation source '{}' does not exist in the knowledge base".format(source))
        # Confirmation is the point at which a proposed name can start moving headline nEff. Stop a
        # likely alias split here, before two spellings of one cohort become two trusted roots.
        candidates = []
        for pair in suggest_duplicates(kb, embed=embed).get("dataset", []):
            if d["id"] in {pair["a"]["ref"], pair["b"]["ref"]}:
                candidates.append(pair)
        if candidates and not allow_similar:
            other = [p["b"]["label"] if p["a"]["ref"] == d["id"] else p["a"]["label"]
                     for p in candidates]
            raise ValueError("possible duplicate evidence base: {} — merge first, or explicitly "
                             "override with allow_similar=True and a note".format(", ".join(other)))
        if candidates and allow_similar and not str(note or "").strip():
            raise ValueError("a similarity override requires a note explaining why the bases are distinct")
        rec = {"status": "confirmed", "method": method, "ts": now_iso()}
        rec["by"] = actor
        if source:
            rec["source"] = source
        if note:
            rec["note"] = note
        if candidates:
            rec["similarityOverride"] = [
                {"ref": p["b"]["ref"] if p["a"]["ref"] == d["id"] else p["a"]["ref"],
                 "reason": p["reason"], "similarity": p["sim"]} for p in candidates]
        d["confirmation"] = rec
    else:
        d["confirmation"] = {"status": "provisional", "ts": now_iso()}
        if by:
            d["confirmation"]["by"] = by
    d.pop("confirmed", None)                     # replace the legacy boolean with the audit record
    verb = "confirmed" if confirmed else "un-confirmed"
    return _commit(kb, "confirm-dataset", "{} dataset “{}” as a real evidence base".format(verb, d["label"]))


def confirm_edge(kb, source_ref, edge_ref, confirmed=True, by=None, note=None):
    """Admit or un-admit one source→dataset/source support edge with an audit record.

    Root confirmation and support-edge confirmation are deliberately distinct. Confirming dataset D
    establishes D's identity; this operation establishes that a particular source actually relies on
    D (or on ``src:<id>``). It is the human fallback when no fetched dependency quote can verify the
    link automatically.
    """
    actor = str(by or "").strip()
    if not actor:
        raise ValueError("edge confirmation requires a non-empty 'by' identity")
    source = _resolve_source(kb, source_ref)
    probe = str(edge_ref or "").strip()
    refs = []
    for edge in source.get("restsOn") or []:
        ref = _edge_ref(edge)
        if ref == probe or norm(ref) == norm(probe):
            refs.append((edge, ref))
    if not refs:
        raise ValueError("source '{}' has no restsOn edge matching '{}'".format(source["id"], edge_ref))
    if len(refs) > 1:
        raise ValueError("edge '{}' is duplicated on source '{}' — dedupe it first".format(edge_ref, source["id"]))
    target, canonical = refs[0]
    edges = source.get("restsOn") or []
    idx = edges.index(target)
    item = dict(target) if isinstance(target, dict) else {"ref": canonical}
    if confirmed:
        item["admission"] = {"status": "confirmed", "method": "curator", "by": actor,
                             "ts": now_iso()}
        if note:
            item["admission"]["note"] = str(note).strip()
    else:
        item.pop("admission", None)
    edges[idx] = item
    source["restsOn"] = edges
    verb = "admitted" if confirmed else "un-admitted"
    return _commit(kb, "confirm-edge", "{} support edge {} → {}".format(
        verb, source["id"], canonical))


def set_curated(kb, curated=True, by=None, note=None):
    """Mark (or unmark) a whole QUESTION as officially curated and maintained by an admin/curator.

    This is a STEWARDSHIP label shown to readers — a maintainer vouches for the question. It is NOT a
    claim that the evidence is all verified: that is the separate, *computed* confirmed-coverage
    signal shown alongside it (engine/assess.curation_summary), so the badge can never launder an
    unverified number into looking authoritative.

    Deliberately an admin-only, trusted act. It lives on ``meta``, which no ingestion delta can write
    (the merge is source-shaped and never copies meta), so it cannot be forged through the public
    contribute path — only a curator CLI run or the admin-token-gated portal endpoint sets it. Writes
    an auditable record ``{by, since, note?}``."""
    meta = kb.setdefault("meta", {})
    if curated:
        actor = str(by or "").strip()
        if not actor:
            raise ValueError("marking a question curated requires a non-empty 'by' identity")
        rec = {"by": actor, "since": now_iso()}
        if note:
            rec["note"] = str(note).strip()
        meta["curated"] = rec
        msg = "marked the question as curated & maintained by {}".format(actor)
    else:
        meta.pop("curated", None)
        msg = "removed the curated & maintained label"
    return _commit(kb, "set-curated", msg)


def tidy_labels(kb):
    """Prettify any id-style / slug labels across positions, datasets, and factors (underscores
    → spaces, drop trailing sample-size clauses). For datasets the old label is kept as an alias."""
    changed = []
    for d in kb["datasets"]:
        nice = prettify_label(d["label"])
        if nice and nice != d["label"]:
            d.setdefault("aliases", [])
            if d["label"] not in d["aliases"]:
                d["aliases"].append(d["label"])
            changed.append("{} → {}".format(d["label"], nice))
            d["label"] = nice
    for coll in ("positions", "factors"):
        for e in kb[coll]:
            nice = prettify_label(e["label"])
            if nice and nice != e["label"]:
                changed.append("{} → {}".format(e["label"], nice))
                e["label"] = nice
    if not changed:
        return {"version": kb["meta"].get("version", 0), "summary": "labels already clean"}
    return _commit(kb, "tidy", "tidied {} label(s)".format(len(changed)))


# ---- duplicate suggestions (token Jaccard) ------------------------------------------------
def _tokens(s):
    return set(t for t in norm(s).split() if t)


def _similarity(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_ACRONYM_STOP = {"a", "an", "and", "of", "the", "for", "in", "on", "cohort", "dataset"}
_DUPLICATE_GENERIC = _ACRONYM_STOP | {"study", "studies", "registry", "trial", "trials",
                                      "data", "sample", "samples", "analysis"}


def _acronym(s):
    words = [w for w in norm(s).split() if w not in _ACRONYM_STOP]
    return "".join(w[0] for w in words if w) if len(words) >= 2 else ""


def _acronym_match(a, b):
    """Suggest NHS ↔ Nurses' Health Study without silently merging either entity."""
    ta, tb = _tokens(a), _tokens(b)
    aa, ab = _acronym(a), _acronym(b)
    return (len(aa) >= 2 and aa in tb) or (len(ab) >= 2 and ab in ta)


def _cosine(u, v):
    import math
    dot = sum(a * b for a, b in zip(u, v))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    return (dot / (nu * nv)) if nu and nv else 0.0


def suggest_duplicates(kb, threshold=0.4, embed=None, embed_threshold=0.83, max_pairs=500):
    """Flag entity pairs whose labels look like the SAME entity, so a curator doesn't have to hunt.
    **Suggestions only — the merge is always explicit; nothing here is ever auto-merged.**

    Two candidate generators:
      * lexical (always on, deterministic, no deps) — acronym match (NHS ↔ Nurses' Health Study) and
        token-overlap Jaccard ≥ `threshold`.
      * semantic (optional) — if `embed` (a label->vector function, from ingest/embed.py) is supplied,
        pairs whose label embeddings have cosine ≥ `embed_threshold` are ALSO surfaced, catching novel
        paraphrases lexical overlap misses ("Huanan market swabs" ↔ "Wuhan seafood-market samples").
        Embeddings live in the ingestion layer and are ADVISORY: the deterministic merge never depends
        on them, and every candidate still needs a human `curate.merge` to act.
    Each suggestion carries its `reason` (acronym | token-overlap | embedding) and score."""
    max_pairs = max(1, int(max_pairs))
    groups = {
        "position": [(p["id"], p["label"]) for p in kb["positions"]],
        "dataset": [(d["id"], d["label"]) for d in kb["datasets"]],
        "factor": [(f["id"], f["label"]) for f in kb["factors"]],
        "population": [(t["label"], t["label"]) for t in kb.get("vocab", {}).get("population", [])],
        "evidence": [(t["label"], t["label"]) for t in kb.get("vocab", {}).get("evidence", [])],
    }
    out = {}
    for kind, items in groups.items():
        pairs, flagged = [], set()
        by_token = {}
        for i, (_ident, label) in enumerate(items):
            for token in _tokens(label) - _DUPLICATE_GENERIC:
                by_token.setdefault(token, []).append(i)
        candidates = set()
        frequency_cap = min(100, max(10, int(len(items) * 0.2)))
        candidate_cap = max(1000, max_pairs * 20)
        for token in sorted(by_token):
            indices = by_token[token]
            if len(indices) > frequency_cap:  # a ubiquitous word is not useful identity evidence
                continue
            for offset, left in enumerate(indices):
                for right in indices[offset + 1:]:
                    candidates.add((left, right))
                    if len(candidates) >= candidate_cap:
                        break
                if len(candidates) >= candidate_cap:
                    break
            if len(candidates) >= candidate_cap:
                break
        for i, (_ident, label) in enumerate(items):
            if len(candidates) >= candidate_cap:
                break
            acronym = _acronym(label)
            if len(acronym) >= 2:
                for j in by_token.get(acronym, []):
                    if i != j:
                        candidates.add((min(i, j), max(i, j)))
                        if len(candidates) >= candidate_cap:
                            break

        for i, j in sorted(candidates):
            acronym = _acronym_match(items[i][1], items[j][1])
            sim = 1.0 if acronym else _similarity(items[i][1], items[j][1])
            if sim >= threshold:
                pairs.append({"a": {"ref": items[i][0], "label": items[i][1]},
                              "b": {"ref": items[j][0], "label": items[j][1]},
                              "sim": round(sim, 2),
                              "reason": "acronym" if acronym else "token-overlap"})
                flagged.add((i, j))
                if len(pairs) >= max_pairs:
                    break
        # Semantic matching is optional and advisory. Bound it to keep one request predictable.
        semantic_items = items[:500]
        if embed is not None and len(semantic_items) >= 2 and len(pairs) < max_pairs:
            vecs = [embed(lbl) for _, lbl in semantic_items]
            for i in range(len(semantic_items)):
                if not vecs[i]:
                    continue
                for j in range(i + 1, len(semantic_items)):
                    if len(pairs) >= max_pairs:
                        break
                    if (i, j) in flagged or not vecs[j]:
                        continue
                    cs = _cosine(vecs[i], vecs[j])
                    if cs >= embed_threshold:
                        pairs.append({"a": {"ref": semantic_items[i][0], "label": semantic_items[i][1]},
                                      "b": {"ref": semantic_items[j][0], "label": semantic_items[j][1]},
                                      "sim": round(cs, 2), "reason": "embedding"})
                if len(pairs) >= max_pairs:
                    break
        if pairs:
            out[kind] = sorted(pairs, key=lambda x: -x["sim"])
    return out
