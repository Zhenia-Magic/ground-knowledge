"""Gap analysis — the steering wheel for gap-driven deep search (see MECHANISM.md for the
independence model this reads from).

`find_gaps(kb)` reads the assessment and reports, deterministically, exactly WHERE a position's
support is thin: camps held up only by echo/secondary sources, evidence types or populations a
side never addresses, datasets named but never directly sourced, and factors only one side engages.
`gap_queries(kb, gaps)` turns each gap into a concrete search string, so the next discovery pass
aims at what's missing instead of pulling more of what we already have.

This is what makes "deep search" principled: we don't stop at a source count, we keep searching the
gaps until the gaps stop generating new angles — and we always report what is still open.
"""
from engine.assess import assess, _ds_label
from engine import roots as _roots

# a position with fewer than this many confirmed PRIMARY roots is "thin"
THIN_PRIMARY_BASES = 2


def _primary_bases(pos):
    """Count confirmed primary roots with non-zero coverage credit."""
    return sum(1 for b in pos.get("bases", [])
               if b["kind"] in ("dataset", "primary") and not b.get("secondaryOnly")
               and b.get("strength", 0) > 0)


def find_gaps(kb, a=None):
    """Return a severity-sorted list of gaps. Each: {kind, why, severity, ...targets}."""
    res = _roots.resolve(kb)
    a = a or assess(kb, res=res)
    gaps = []

    # 1. Positions held up by little or no INDEPENDENT primary evidence (mostly echo / secondary).
    for p in a["independence"]:
        if p["raw"] == 0:
            continue
        np = _primary_bases(p)
        if np < THIN_PRIMARY_BASES:
            gaps.append({
                "kind": "thin-position", "positionId": p["id"], "label": p["label"],
                "why": ("no confirmed primary root — support is ungrounded, unadmitted, or secondary"
                        if np == 0 else
                        "only {} confirmed primary root; rest is ungrounded or secondary".format(np)),
                "severity": 3 if np == 0 else 2})

    # 2. Blindspots: evidence types / populations a side never argues from.
    for b in a["blindspots"]:
        for ev in b.get("missingEvidence", []):
            gaps.append({"kind": "blindspot-evidence", "positionId": b["id"], "label": b["label"],
                         "target": ev, "why": "this side never argues from {} evidence".format(ev),
                         "severity": 1})
        for pop in b.get("missingPop", []):
            gaps.append({"kind": "blindspot-population", "positionId": b["id"], "label": b["label"],
                         "target": pop, "why": "this side doesn't address {}".format(pop),
                         "severity": 1})

    # 3. Datasets named but only cited THROUGH a review — the primary source itself is missing.
    for rk in sorted(res["secondary_only"]):
        did = rk[3:]
        gaps.append({"kind": "unsourced-dataset", "datasetId": did, "label": _ds_label(kb, did),
                     "why": "cited only via a review; the primary source resting on it is missing",
                     "severity": 2})

    # 4. Factors only one side engages — the other side's take is missing.
    for c in a["cruxes"]:
        if c.get("engaged") == 1:
            gaps.append({"kind": "one-sided-factor", "label": c["label"],
                         "why": "only one side weighs this factor — the rebuttal is missing",
                         "severity": 1})

    # 5. Funding blind spot: no interested (industry/advocacy) funding identified and a big chunk
    # undisclosed — the conflict-of-interest angle this tool exists to surface is unexplored.
    fs = a.get("fundingSkew") or {}
    total = len(kb["sources"])
    if total and fs.get("n", 0) == 0 and fs.get("undisclosed", 0) >= max(3, round(0.3 * total)):
        gaps.append({"kind": "funding-blindspot",
                     "why": "no industry/advocacy funding identified, {} of {} sources undisclosed — "
                            "the funding / conflict-of-interest angle is unexplored".format(
                                fs.get("undisclosed"), total),
                     "severity": 2})

    gaps.sort(key=lambda g: -g["severity"])
    return gaps


def gap_queries(kb, gaps):
    """Turn gaps into concrete search strings aimed at the missing evidence."""
    subj = (kb.get("meta", {}).get("question") or "").rstrip("? ").strip()
    pos = {p["id"]: p["label"] for p in kb["positions"]}
    out = []
    for g in gaps:
        k = g["kind"]
        if k == "thin-position":
            q = "{} {}".format(subj, pos.get(g["positionId"], g.get("label", "")))
        elif k == "blindspot-evidence":
            q = "{} {} {}".format(subj, pos.get(g["positionId"], ""), g["target"])
        elif k == "blindspot-population":
            q = "{} {} {}".format(subj, g["target"], pos.get(g["positionId"], ""))
        elif k == "unsourced-dataset":
            q = g["label"]                              # the dataset / cohort name itself
        elif k == "one-sided-factor":
            q = "{} {}".format(subj, g["label"])
        elif k == "funding-blindspot":
            q = "{} industry funding conflict of interest bias".format(subj)
        else:
            continue
        out.append({"gap": g, "query": " ".join(q.split())})
    return out
