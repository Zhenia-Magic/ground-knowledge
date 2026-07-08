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


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s if s is not None else "").lower()).strip()


def _src(d):
    return (d or {}).get("source") or {}


def _conf(d):
    prov = (_src(d).get("provenance") or {}).get("position") or {}
    try:
        return float(prov.get("extractionConfidence"))
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
    else:
        winner = max(rd, key=_conf)
        pos_agree = 0.0
        pos_vote = {}
    wsrc = _src(winner)

    out = dict(wsrc)                                             # keep winner's quote/positionShort
    out["relevant"] = True
    for field in ("evidence", "funding", "population", "confidence"):
        val = _mode([s.get(field) for s in rs])
        if val is not None:
            out[field] = val
        if len({_norm(s.get(field)) for s in rs if s.get(field)}) > 1:
            disagreed.append(field)

    # restsOn: keep an edge >= half the models proposed (normalized), preserve a raw form
    edge_count, raw_form = Counter(), OrderedDict()
    for s in rs:
        for e in dict.fromkeys(_norm(x) for x in (s.get("restsOn") or []) if x):
            edge_count[e] += 1
        for x in (s.get("restsOn") or []):
            if x:
                raw_form.setdefault(_norm(x), x)
    out["restsOn"] = [raw_form[e] for e, cnt in edge_count.items() if cnt >= m / 2.0]

    # factorWeights: keep a factor >= half propose; weight = mode
    fw_by = OrderedDict()
    for d in rd:
        for fw in (d.get("factorWeights") or []):
            lab = fw.get("factor") or fw.get("factorLabel")
            if lab:
                fw_by.setdefault(_norm(lab), []).append(fw)
    fws = []
    for _key, items in fw_by.items():
        if len(items) >= m / 2.0:
            base = dict(items[0])
            base["weight"] = _mode([it.get("weight") for it in items]) or base.get("weight")
            fws.append(base)

    rep = {"models": n, "positionAgreement": round(pos_agree, 2), "flagged": flagged,
           "disagreedFields": sorted(set(disagreed)),
           "positionVote": pos_vote}
    out["modelAgreement"] = rep
    return {"source": out, "factorWeights": fws}, rep
