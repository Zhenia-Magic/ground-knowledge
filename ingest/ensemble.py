"""Multi-model labelling ensemble — combine several models' extraction deltas into ONE consensus
delta per source, so a label doesn't depend on any single model's idiosyncrasy (see
ingest/llm.complete_ensemble; wired in ingest/pipeline.label_batch).

Field-level majority vote:
  * relevance   — majority; a majority "off-topic" refuses the source (like the single-model path).
  * position    — vote by normalized proposed label. A real majority wins outright. A tie / mere
                  plurality falls to the HIGHEST-confidence model and is FLAGGED (the settled
                  policy) so a curator can look — nothing is silently forced.
  * evidence / funding / population / confidence — mode (most common), ties by first-seen.
  * restsOn     — an evidentiary edge is kept only if >= half the models proposed it (a lone
                  model's spurious dataset/citation edge is dropped; a shared one survives).
  * factorWeights — a factor is kept if >= half propose it; its weight is the mode.
The winning model's provenance quote is carried, so the quote matches the chosen position.

Every combined source carries a `modelAgreement` report (models, position agreement, flagged,
which fields split) — persisted by engine.merge and surfaced by engine.assess. Pure, deterministic
given the inputs.
"""
import re
from collections import Counter, OrderedDict

from engine.roots import _TIER as _ROOT_TIER, _norm as _root_norm


def _tier_of_label(evidence):
    """primary | secondary for a raw evidence label, via the engine's default tier map (an
    unrecognised label -> secondary, matching engine.roots.tier_of). Used only to detect a
    primary/secondary SPLIT across the ensemble; the case-vocab tier override isn't in scope here."""
    return _ROOT_TIER.get(_root_norm(evidence), "secondary")


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s if s is not None else "").lower()).strip()


def _src(d):
    return (d or {}).get("source") or {}


def _edge_ref(edge):
    """Raw reference carried by a restsOn string or per-edge provenance object."""
    if isinstance(edge, dict):
        return str(edge.get("ref") or "").strip()
    return str(edge or "").strip()


def _conf(d):
    prov = (_src(d).get("provenance") or {}).get("position") or {}
    try:
        return float(prov.get("extractionConfidence"))
    except (TypeError, ValueError):
        return 0.0


def _edge_conf(edge):
    if not isinstance(edge, dict):
        return 0.0
    try:
        return float((edge.get("provenance") or {}).get("extractionConfidence") or 0)
    except (TypeError, ValueError):
        return 0.0


_POS_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "with", "and", "or", "by", "at",
             "is", "are", "be", "that", "this", "it", "its", "new", "pos"}


def _pos_key_tokens(proposal):
    """Stance tokens of a proposed position, for vote clustering: strip a 'NEW:'/'pos_' decoration
    and parentheticals, normalize, drop connectives, and lightly de-plural (increases->increase)
    so 'NEW:Violent video games increase aggression', 'increases aggression', and an existing
    'pos_increases_aggression' id all reduce to overlapping stance tokens — while opposite stances
    (increase vs decrease) stay disjoint."""
    p = str(proposal or "")
    if p.lower().startswith("new:"):
        p = p[4:]
    p = re.sub(r"\([^)]*\)", " ", p)
    p = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", p)   # split camelCase: IncreaseAggression -> Increase Aggression
    out = set()
    for t in _norm(p).split():
        if t in _POS_STOP:
            continue
        out.add(t[:-1] if len(t) > 4 and t.endswith("s") else t)   # light plural stem
    return out


def _same_stance(a, b):
    """Two proposals are the same camp if one's stance tokens are a subset of the other's (subset
    is stance-safe: opposite stances are never subsets). Empty token sets never match."""
    return bool(a) and bool(b) and (a <= b or b <= a)


# generic dataset-name filler that shouldn't drive edge clustering ("cohort" alone is not identity)
_DS_GENERIC = {"ds", "dataset", "data", "cohort", "cohorts", "study", "studies", "sample",
               "samples", "trial", "trials", "longitudinal", "experiment", "experimental",
               "intervention", "meta", "analysis", "new"}


def _edge_tokens(label):
    """Distinguishing tokens of a proposed dataset edge (camelCase-split, normalized, generic
    filler dropped) — the identity signal for clustering two models' names for the SAME cohort."""
    p = re.sub(r"\([^)]*\)", " ", str(label or ""))
    if p.lower().startswith("new:"):
        p = p[4:]
    p = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", p)
    return {t for t in _norm(p).split() if t not in _DS_GENERIC}


def _same_edge(a, b):
    """Two dataset-edge proposals name the same underlying cohort: distinguishing-token Jaccard
    >= 0.4 or subset. ('GTA V vs Sims 3 ... cohort' ~ 'GTA V ... 2018' clusters; 'ds_a' vs 'ds_b'
    or two genuinely different cohorts do not.)"""
    if not a or not b:
        return False
    if a <= b or b <= a:
        return True
    inter = len(a & b)
    return inter / len(a | b) >= 0.4


def _factor_tokens(label):
    """Content tokens of a proposed factor label (camelCase-split, normalized, de-pluralled,
    connectives dropped) — the identity signal for clustering two models' names for one crux."""
    p = re.sub(r"\([^)]*\)", " ", str(label or ""))
    p = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", p)
    return {t[:-1] if len(t) > 4 and t.endswith("s") else t
            for t in _norm(p).split() if t not in _POS_STOP}


def _same_factor(a, b):
    """Two factor proposals name the same crux: token subset (a qualifier variant — 'Publication
    bias' ⊆ 'Publication bias concerns') or Jaccard >= 0.6. The higher bar than datasets keeps
    genuinely different axes sharing words apart ('Effect size magnitude' vs 'Effect size
    heterogeneity' is 0.5 — distinct)."""
    if not a or not b:
        return False
    if a <= b or b <= a:
        return True
    return len(a & b) / len(a | b) >= 0.6


def _mode(values):
    """Most common non-empty value; ties broken by first-seen order (stable). Preserves the
    original raw form (casing/prefix) rather than the normalized key."""
    vals = [v for v in values if v not in (None, "", "—")]
    if not vals:
        return None
    counts = Counter(_norm(v) for v in vals)
    best = max(counts.values())
    for v in vals:                                   # first raw value at the winning count
        if counts[_norm(v)] == best:
            return v
    return vals[0]


def combine(model_deltas, n_sources):
    """model_deltas: one list of source-deltas per model (same order as the batch's sources).
    Returns (consensus, agreement): `consensus` is n_sources deltas; `agreement` the parallel
    per-source reports. Models whose array is short (a truncated response) simply don't vote on
    the missing tail — the combine never crashes on a miscounted model."""
    consensus, agreement = [], []
    for i in range(n_sources):
        deltas = [md[i] for md in model_deltas
                  if isinstance(md, list) and i < len(md) and isinstance(md[i], dict)]
        c, a = combine_one(deltas)
        consensus.append(c)
        agreement.append(a)
    return consensus, agreement


def combine_one(deltas):
    """Combine the several models' deltas for ONE source into (consensus_delta, agreement_report)."""
    n = len(deltas)
    if n == 0:
        rep = {"models": 0, "positionAgreement": 0.0, "flagged": True, "disagreedFields": []}
        return {"source": {"relevant": False, "offTopicReason": "no model produced a label",
                           "modelAgreement": rep}}, rep
    if n == 1:
        rep = {"models": 1, "positionAgreement": 1.0, "flagged": False, "disagreedFields": []}
        d = dict(deltas[0])
        d.setdefault("source", {})["modelAgreement"] = rep
        return d, rep

    srcs = [_src(d) for d in deltas]

    # relevance FIRST — a majority "off-topic" refuses the source
    rel_true = sum(1 for s in srcs if s.get("relevant", True) is not False)
    if rel_true < n / 2.0:
        reason = _mode([s.get("offTopicReason") for s in srcs if s.get("relevant") is False]) \
            or "not relevant to the question"
        rep = {"models": n, "positionAgreement": round(rel_true / n, 2), "flagged": False,
               "disagreedFields": ["relevant"] if rel_true else []}
        return {"source": {"relevant": False, "offTopicReason": reason, "modelAgreement": rep}}, rep

    # vote among the models that DID find it relevant
    rel = [(d, s) for d, s in zip(deltas, srcs) if s.get("relevant", True) is not False] \
        or list(zip(deltas, srcs))
    rd = [d for d, _s in rel]
    rs = [s for _d, s in rel]
    m = len(rd)

    # cluster proposals by STANCE, not raw label string, so 'NEW:Increases X', 'increases X', and
    # an existing 'pos_increases_x' id count as ONE vote (they're the same camp; the merge would
    # unify them anyway). Voting on raw strings falsely flagged agreement as disagreement.
    clusters = []                                    # each: {"tokens": set, "deltas": [], "label": raw}
    for d, s in zip(rd, rs):
        lab = s.get("position")
        if not lab:
            continue
        tk = _pos_key_tokens(lab)
        for c in clusters:
            if _same_stance(tk, c["tokens"]):
                c["deltas"].append(d)
                break
        else:
            clusters.append({"tokens": tk, "deltas": [d], "label": lab})
    disagreed, flagged = [], False
    if clusters:
        clusters.sort(key=lambda c: -len(c["deltas"]))
        top_n = len(clusters[0]["deltas"])
        if top_n > m / 2.0:                                      # real majority stance
            winner = max(clusters[0]["deltas"], key=_conf)
        else:                                                    # tie / plurality -> conf + FLAG
            flagged = True
            disagreed.append("position")
            winner = max(rd, key=_conf)
        pos_agree = top_n / m
        pos_vote = {c["label"]: len(c["deltas"]) for c in clusters}
        # per-stance PROPOSALS, for a human resolving the disagreement: each cluster's label,
        # vote count, and its best-confidence model's quote — the evidence behind each reading.
        proposals = []
        for c in clusters:
            best = max(c["deltas"], key=_conf)
            bprov = (_src(best).get("provenance") or {}).get("position") or {}
            proposals.append({"position": c["label"], "votes": len(c["deltas"]),
                              "quote": bprov.get("quote") or "", "confidence": _conf(best)})
    else:
        winner = max(rd, key=_conf)
        pos_agree = 0.0
        pos_vote = {}
        proposals = []
    wsrc = _src(winner)
    winner_i = next(i for i, d in enumerate(rd) if d is winner)

    out = dict(wsrc)                                             # keep winner's quote/positionShort
    out["relevant"] = True
    for field in ("evidence", "funding", "population", "confidence"):
        val = _mode([s.get(field) for s in rs])
        if val is not None:
            out[field] = val
        if len({_norm(s.get(field)) for s in rs if s.get(field)}) > 1:
            disagreed.append(field)

    # ESCALATE a tier split. Evidence TIER (primary makes evidence, secondary talks about it) is a
    # bigger nEff lever than the position itself — a source voted 'primary' mints an independent root
    # that the same source voted 'secondary' would not. So if the models straddle the primary/
    # secondary boundary, flag for human review even though the field-vote still picked a winner;
    # a wrong tier silently mints or denies a root (see engine/roots.tier_of, MECHANISM.md §8.1).
    ev_tiers = {_tier_of_label(s.get("evidence")) for s in rs if s.get("evidence")}
    if len(ev_tiers) > 1:
        flagged = True
        if "evidence" not in disagreed:
            disagreed.append("evidence")

    # restsOn: an evidentiary edge survives only on a STRICT MAJORITY vote (> m/2), so one model's
    # spurious dataset/citation edge is never kept (at m=2 an edge needs BOTH models, not one). Models
    # routinely name the same cohort differently, so edges are clustered by distinguishing-token
    # overlap BEFORE the vote (so "Przybylski2019 dataset" and "UK adolescent cohort" count as one
    # edge if both models meant the same study). src:-edges vote by exact normalized key. NOTE: the
    # old unconditional "if every model proposed <=1 dataset, merge them all" rule is removed — it
    # over-merged two genuinely different single datasets into false agreement. A dropped edge is now
    # safe: the source falls to the position's pool (A1), it can't inflate independence.
    src_count, src_form = Counter(), OrderedDict()
    ds_lists = []                                    # per model: [(norm, raw, tokens), ...]
    for model_i, s in enumerate(rs):
        seen_src, ds_row = set(), []
        for x in (s.get("restsOn") or []):
            ref = _edge_ref(x)
            if not ref:
                continue
            if ref.lower().startswith(("src:", "new-src:")):
                k = _norm(ref)
                if k not in seen_src:
                    seen_src.add(k)
                    src_count[k] += 1
                    src_form.setdefault(k, ref)
            else:
                # Keep the whole winning edge object as the representative form, so its specific
                # dependency quote survives the vote and can be verified by pipeline._carry_meta.
                ds_row.append((_norm(ref), x, _edge_tokens(ref)))
        ds_lists.append(ds_row)
    clusters = []                                    # {"tokens", "forms":[(model,norm,raw)], "votes"}
    for model_i, row in enumerate(ds_lists):
        for k, raw, tk in row:
            for c in clusters:
                if _same_edge(tk, c["tokens"]):
                    c["forms"].append((model_i, k, raw))
                    c["tokens"] |= tk
                    c["voters"].add(model_i)       # aliases repeated by ONE model are still one vote
                    break
            else:
                clusters.append({"tokens": set(tk), "forms": [(model_i, k, raw)],
                                 "voters": {model_i}})
    rests, edge_dropped = [], False
    for k, cnt in src_count.items():
        (rests.append(src_form[k]) if cnt > m / 2.0 else None)
        edge_dropped = edge_dropped or (0 < cnt <= m / 2.0)
    for c in clusters:
        if len(c["voters"]) > m / 2.0:
            # Representative form: the winning POSITION model's exact edge when it contributed.
            # If the majority edge came only from other models, keep their best-supported quote.
            # Tracking model identity avoids provider-order dependence when every ref string is the
            # same but quotes/confidences differ.
            representative = next((raw for mi, _k, raw in c["forms"] if mi == winner_i), None)
            if representative is None:
                representative = max(c["forms"], key=lambda form: _edge_conf(form[2]))[2]
            rests.append(representative)
        else:
            edge_dropped = True                       # a proposed edge failed to reach a majority
    out["restsOn"] = rests
    if edge_dropped and "restsOn" not in disagreed:
        disagreed.append("restsOn")                   # record edge-vote disagreement

    # factorWeights: models phrase the same crux differently ("Publication bias" vs
    # "publication-bias concerns"), so cluster proposals by label tokens BEFORE a STRICT-majority vote
    # (> m/2). Weight is the cluster's mode; the winning model's wording (and quote/rationale) wins.
    fclusters = []
    for d in rd:
        seen = set()
        for fw in (d.get("factorWeights") or []):
            lab = fw.get("factor") or fw.get("factorLabel")
            if not lab or _norm(lab) in seen:
                continue
            seen.add(_norm(lab))
            tk = _factor_tokens(lab)
            for c in fclusters:
                if _same_factor(tk, c["tokens"]):
                    c["items"].append((d is winner, fw))
                    c["tokens"] |= tk
                    c["votes"] += 1
                    break
            else:
                fclusters.append({"tokens": set(tk), "items": [(d is winner, fw)], "votes": 1})
    fws = []
    for c in fclusters:
        if c["votes"] > m / 2.0:
            rep = next((fw for is_w, fw in c["items"] if is_w), c["items"][0][1])
            base = dict(rep)
            base["weight"] = _mode([fw.get("weight") for _w, fw in c["items"]]) or base.get("weight")
            fws.append(base)

    rep = {"models": n, "positionAgreement": round(pos_agree, 2), "flagged": flagged,
           "tierSplit": len(ev_tiers) > 1,
           "disagreedFields": sorted(set(disagreed)),
           "positionVote": pos_vote, "proposals": proposals}
    out["modelAgreement"] = rep
    return {"source": out, "factorWeights": fws}, rep
