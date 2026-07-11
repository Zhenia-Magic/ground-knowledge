"""Deterministic KB schema migration and lightweight integrity validation.

The JSON Schema in schema/kb-v2.schema.json is the portable contract for other tools. These stdlib-
only helpers keep local/portal loading dependency-free and check the cross-reference constraints JSON
Schema cannot express (source positions, dataset/source edges, and unique IDs).
"""
import copy

LATEST_SCHEMA_VERSION = 2


def migrate_kb(kb, copy_value=True):
    """Return ``(v2_kb, changes)`` without discarding unknown extension fields.

    A missing schemaVersion is the original v1 format. Migration is intentionally additive: fields
    whose truth cannot be reconstructed (quote verification, dataset confirmation, provenance weight)
    are never invented.
    """
    if not isinstance(kb, dict):
        raise ValueError("KB must be an object")
    out = copy.deepcopy(kb) if copy_value else kb
    meta = out.setdefault("meta", {})
    version = meta.get("schemaVersion", 1)
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise ValueError("meta.schemaVersion must be an integer")
    if version > LATEST_SCHEMA_VERSION:
        raise ValueError("KB schema v{} is newer than supported v{}".format(
            version, LATEST_SCHEMA_VERSION))

    changes = []
    if version < 2:
        for field in ("positions", "datasets", "factors", "sources", "log"):
            if field not in out:
                out[field] = []
                changes.append("added " + field)
        out.setdefault("pendingReview", [])
        out.setdefault("refused", [])
        vocab = out.setdefault("vocab", {})
        for field in ("evidence", "population", "funding"):
            vocab.setdefault(field, [])
        for d in out["datasets"]:
            d.setdefault("aliases", [])
        for f in out["factors"]:
            f.setdefault("weights", {})
            f.setdefault("rationale", "")
            f.setdefault("provenance", [])
        for s in out["sources"]:
            s.setdefault("authors", [])
            s.setdefault("venue", "")
            s.setdefault("citations", None)
            s.setdefault("retracted", False)
            s.setdefault("restsOn", [])
            s.setdefault("provenance", {})
            s.setdefault("textDepth", "unknown")
        changes.append("migrated schema v1 to v2")
    meta["schemaVersion"] = LATEST_SCHEMA_VERSION
    return out, changes


def validation_errors(kb):
    """Return deterministic human-readable structural/reference errors; empty means valid enough to run."""
    errors = []
    if not isinstance(kb, dict):
        return ["KB must be an object"]
    for field in ("meta", "positions", "datasets", "factors", "sources", "vocab", "log"):
        if field not in kb:
            errors.append("missing top-level field: " + field)
    if errors:
        return errors
    if kb.get("meta", {}).get("schemaVersion") != LATEST_SCHEMA_VERSION:
        errors.append("meta.schemaVersion must equal {}".format(LATEST_SCHEMA_VERSION))
    for field in ("positions", "datasets", "factors", "sources", "log"):
        if not isinstance(kb.get(field), list):
            errors.append(field + " must be an array")
    if errors:
        return errors

    def ids(field):
        vals = [x.get("id") for x in kb[field] if isinstance(x, dict)]
        if any(not x for x in vals):
            errors.append(field + " entries require non-empty id")
        if len(vals) != len(set(vals)):
            errors.append(field + " ids must be unique")
        return set(vals)

    pos_ids, ds_ids, src_ids = ids("positions"), ids("datasets"), ids("sources")
    ids("factors")
    for s in kb["sources"]:
        if not isinstance(s, dict):
            errors.append("sources entries must be objects")
            continue
        if s.get("position") not in pos_ids:
            errors.append("source {} references unknown position {}".format(
                s.get("id", "?"), s.get("position")))
        rests = s.get("restsOn", [])
        if not isinstance(rests, list):
            errors.append("source {} restsOn must be an array".format(s.get("id", "?")))
            continue
        for edge in rests:
            ref = _edge_ref(edge)
            if not ref:
                continue
            if ref.startswith("src:"):
                if ref[4:] not in src_ids:
                    errors.append("source {} references unknown source {}".format(s.get("id", "?"), ref[4:]))
            elif ref not in ds_ids:
                errors.append("source {} references unknown dataset {}".format(s.get("id", "?"), ref))
    return errors


def _edge_ref(edge):
    """The ref of a restsOn entry: the string itself, or the 'ref' field of an edge object
    {"ref": "...", "provenance": {...}} (see engine/roots._edges)."""
    if isinstance(edge, dict):
        return str(edge.get("ref") or "").strip()
    return str(edge).strip()


def load_migrated(value):
    """Migrate objects that look like KBs; leave deltas, benchmark fixtures, and other JSON alone."""
    if isinstance(value, dict) and "meta" in value and "sources" in value and "positions" in value:
        return migrate_kb(value)[0]
    return value
