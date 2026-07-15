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
    if "meta" not in out:
        out["meta"] = {}
    if not isinstance(out.get("meta"), dict):
        raise ValueError("meta must be an object")
    meta = out["meta"]
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
        if not isinstance(vocab, dict):
            raise ValueError("vocab must be an object")
        for field in ("evidence", "population", "funding"):
            vocab.setdefault(field, [])
        for d in out["datasets"]:
            if isinstance(d, dict):
                d.setdefault("aliases", [])
        for f in out["factors"]:
            if isinstance(f, dict):
                f.setdefault("weights", {})
                f.setdefault("rationale", "")
                f.setdefault("provenance", [])
        for s in out["sources"]:
            if isinstance(s, dict):
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

    def string_list(value, path):
        if not isinstance(value, list):
            errors.append(path + " must be an array")
            return
        if any(not isinstance(item, str) for item in value):
            errors.append(path + " entries must be strings")

    def provenance_record(value, path):
        if not isinstance(value, dict):
            errors.append(path + " must be an object")
            return
        if "quote" in value and value.get("quote") is not None and not isinstance(value.get("quote"), str):
            errors.append(path + ".quote must be a string")
        verified = value.get("verifiedQuote")
        if verified not in (None, "exact", "fuzzy", "missing"):
            errors.append(path + ".verifiedQuote is invalid")
        if verified in ("exact", "fuzzy") and not str(value.get("quote") or "").strip():
            errors.append(path + ".verifiedQuote requires quote")
        if value.get("quoteVerification") is not None and not isinstance(
                value.get("quoteVerification"), dict):
            errors.append(path + ".quoteVerification must be an object")
    if not isinstance(kb.get("meta"), dict):
        errors.append("meta must be an object")
    if not isinstance(kb.get("vocab"), dict):
        errors.append("vocab must be an object")
    if errors:
        return errors
    if kb["meta"].get("schemaVersion") != LATEST_SCHEMA_VERSION:
        errors.append("meta.schemaVersion must equal {}".format(LATEST_SCHEMA_VERSION))
    for field in ("id", "question"):
        if not isinstance(kb["meta"].get(field), str) or not kb["meta"].get(field).strip():
            errors.append("meta.{} must be a non-empty string".format(field))
    if not isinstance(kb["meta"].get("version", 0), int) or isinstance(
            kb["meta"].get("version", 0), bool):
        errors.append("meta.version must be an integer")
    for field in ("positions", "datasets", "factors", "sources", "log"):
        if not isinstance(kb.get(field), list):
            errors.append(field + " must be an array")
    for field in ("evidence", "population", "funding"):
        if not isinstance(kb["vocab"].get(field), list):
            errors.append("vocab." + field + " must be an array")
    for field in ("pendingReview", "refused"):
        if field in kb and not isinstance(kb.get(field), list):
            errors.append(field + " must be an array")
    if "contextSources" in kb and not isinstance(kb.get("contextSources"), list):
        errors.append("contextSources must be an array")
    if errors:
        return errors

    def ids(field):
        vals = []
        for i, item in enumerate(kb[field]):
            if not isinstance(item, dict):
                errors.append("{}[{}] must be an object".format(field, i))
                continue
            ident = item.get("id")
            if not isinstance(ident, str) or not ident.strip():
                errors.append(field + " entries require non-empty id")
                continue
            vals.append(ident)
        if len(vals) != len(set(vals)):
            errors.append(field + " ids must be unique")
        return set(vals)

    pos_ids, ds_ids, src_ids = ids("positions"), ids("datasets"), ids("sources")
    ids("factors")
    context_ids = set()
    for i, source in enumerate(kb.get("contextSources", [])):
        if not isinstance(source, dict):
            errors.append("contextSources[{}] must be an object".format(i))
            continue
        ident = source.get("id")
        if not isinstance(ident, str) or not ident.strip():
            errors.append("contextSources entries require non-empty id")
        elif ident in context_ids or ident in src_ids:
            errors.append("contextSources ids must be unique across all sources")
        else:
            context_ids.add(ident)
    for field in ("positions", "datasets", "factors"):
        for item in kb[field]:
            if isinstance(item, dict) and (not isinstance(item.get("label"), str)
                                           or not item.get("label").strip()):
                errors.append("{} {} requires non-empty label".format(field[:-1], item.get("id", "?")))
    for d in kb["datasets"]:
        if not isinstance(d, dict):
            errors.append("datasets entries must be objects")
            continue
        c = d.get("confirmation")
        string_list(d.get("aliases", []), "dataset {} aliases".format(d.get("id", "?")))
        if d.get("kind") not in (None, "dataset", "experiment", "observation", "document",
                                  "argument", "model"):
            errors.append("dataset {} has invalid kind".format(d.get("id", "?")))
        if c is not None and not isinstance(c, dict):
            errors.append("dataset {} confirmation must be an object".format(d.get("id", "?")))
            continue
        if isinstance(c, dict) and c.get("status") not in (None, "confirmed", "provisional", "disputed"):
            errors.append("dataset {} has invalid confirmation status".format(d.get("id", "?")))
        if not isinstance(c, dict) or c.get("status") != "confirmed":
            continue
        method = c.get("method")
        if method not in ("curator", "verified-edge"):
            errors.append("dataset {} confirmed record requires method curator or verified-edge".format(d.get("id", "?")))
        if not (c.get("ts") or c.get("timestamp")):
            errors.append("dataset {} confirmed record requires ts".format(d.get("id", "?")))
        if method == "curator" and not (c.get("by") or c.get("curator")):
            errors.append("dataset {} curator confirmation requires by".format(d.get("id", "?")))
        if method == "verified-edge" and not c.get("source"):
            errors.append("dataset {} verified-edge confirmation requires source".format(d.get("id", "?")))
    for s in kb["sources"]:
        if not isinstance(s, dict):
            errors.append("sources entries must be objects")
            continue
        for field in ("title", "evidence", "funding", "population"):
            if not isinstance(s.get(field), str) or not s.get(field).strip():
                errors.append("source {} requires non-empty {}".format(s.get("id", "?"), field))
        string_list(s.get("authors", []), "source {} authors".format(s.get("id", "?")))
        if "year" in s and s.get("year") is not None and not isinstance(s.get("year"), (str, int)):
            errors.append("source {} year must be a string, integer, or null".format(s.get("id", "?")))
        if "citations" in s and s.get("citations") is not None and (
                not isinstance(s.get("citations"), int) or isinstance(s.get("citations"), bool)
                or s.get("citations") < 0):
            errors.append("source {} citations must be a non-negative integer".format(s.get("id", "?")))
        if "retracted" in s and not isinstance(s.get("retracted"), bool):
            errors.append("source {} retracted must be true or false".format(s.get("id", "?")))
        if s.get("textDepth", "unknown") not in ("full", "abstract", "partial", "unknown"):
            errors.append("source {} has invalid textDepth".format(s.get("id", "?")))
        source_provenance = s.get("provenance", {})
        if not isinstance(source_provenance, dict):
            errors.append("source {} provenance must be an object".format(s.get("id", "?")))
        else:
            for name, record in source_provenance.items():
                provenance_record(record, "source {} provenance.{}".format(s.get("id", "?"), name))
        if s.get("modelAgreement") is not None and not isinstance(s.get("modelAgreement"), dict):
            errors.append("source {} modelAgreement must be an object".format(s.get("id", "?")))
        if s.get("position") not in pos_ids:
            errors.append("source {} references unknown position {}".format(
                s.get("id", "?"), s.get("position")))
        rests = s.get("restsOn", [])
        if not isinstance(rests, list):
            errors.append("source {} restsOn must be an array".format(s.get("id", "?")))
            continue
        for edge in rests:
            if not isinstance(edge, (str, dict)):
                errors.append("source {} edges must be strings or objects".format(s.get("id", "?")))
                continue
            ref = _edge_ref(edge)
            if not ref:
                errors.append("source {} has an edge without ref".format(s.get("id", "?")))
                continue
            if isinstance(edge, dict):
                prov = edge.get("provenance")
                if prov is not None and not isinstance(prov, dict):
                    errors.append("source {} edge {} provenance must be an object".format(
                        s.get("id", "?"), ref or "?"))
                elif isinstance(prov, dict):
                    provenance_record(prov, "source {} edge {} provenance".format(
                        s.get("id", "?"), ref))
                admission = edge.get("admission")
                if admission is not None:
                    if not isinstance(admission, dict):
                        errors.append("source {} edge {} admission must be an object".format(
                            s.get("id", "?"), ref or "?"))
                    elif admission.get("status") != "confirmed" or admission.get("method") not in \
                            ("curator", "legacy-migration") \
                            or not admission.get("by") or not admission.get("ts"):
                        errors.append("source {} edge {} has invalid curator admission".format(
                            s.get("id", "?"), ref or "?"))
            if not ref:
                continue
            if ref.startswith("src:"):
                if ref[4:] not in src_ids:
                    errors.append("source {} references unknown source {}".format(s.get("id", "?"), ref[4:]))
            elif ref not in ds_ids:
                errors.append("source {} references unknown dataset {}".format(s.get("id", "?"), ref))
    for d in kb["datasets"]:
        c = d.get("confirmation") if isinstance(d, dict) else None
        if isinstance(c, dict) and c.get("source") and c["source"] not in src_ids:
            errors.append("dataset {} confirmation references unknown source {}".format(
                d.get("id", "?"), c["source"]))
    for f in kb["factors"]:
        if not isinstance(f, dict):
            continue
        if not isinstance(f.get("weights", {}), dict):
            errors.append("factor {} weights must be an object".format(f.get("id", "?")))
        else:
            for pid, weight in f.get("weights", {}).items():
                if pid not in pos_ids:
                    errors.append("factor {} weight references unknown position {}".format(
                        f.get("id", "?"), pid))
                if weight not in ("high", "med", "low", "n/a"):
                    errors.append("factor {} has invalid weight {}".format(f.get("id", "?"), weight))
        provenance = f.get("provenance", [])
        if not isinstance(provenance, list):
            errors.append("factor {} provenance must be an array".format(f.get("id", "?")))
            continue
        for claim in provenance:
            if not isinstance(claim, dict):
                errors.append("factor {} provenance entries must be objects".format(f.get("id", "?")))
                continue
            if claim.get("source") not in src_ids | context_ids:
                errors.append("factor {} claim references unknown source {}".format(
                    f.get("id", "?"), claim.get("source")))
            if claim.get("pos") not in pos_ids:
                errors.append("factor {} claim references unknown position {}".format(
                    f.get("id", "?"), claim.get("pos")))
            if claim.get("weight") is not None and claim.get("weight") not in (
                    "high", "med", "low", "n/a"):
                errors.append("factor {} claim has invalid weight".format(f.get("id", "?")))
            provenance_record(claim, "factor {} claim".format(f.get("id", "?")))
    for kind in ("evidence", "population", "funding"):
        labels = []
        for i, term in enumerate(kb["vocab"].get(kind, [])):
            if not isinstance(term, dict):
                errors.append("vocab.{}[{}] must be an object".format(kind, i))
                continue
            label = term.get("label")
            if not isinstance(label, str) or not label.strip():
                errors.append("vocab.{} entries require non-empty label".format(kind))
            else:
                labels.append(label)
            string_list(term.get("aliases", []),
                        "vocab.{} term {} aliases".format(kind, label or "?"))
        if len(labels) != len(set(labels)):
            errors.append("vocab.{} labels must be unique".format(kind))
    from engine.validate import delta_validation_errors
    for i, item in enumerate(kb.get("pendingReview", [])):
        if not isinstance(item, dict):
            errors.append("pendingReview[{}] must be an object".format(i))
            continue
        if not isinstance(item.get("id"), str) or not item.get("id"):
            errors.append("pendingReview[{}] requires id".format(i))
        delta_errors = delta_validation_errors(item.get("delta"))
        errors.extend("pendingReview[{}].{}".format(i, error) for error in delta_errors)
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
