"""Total, dependency-free validation for ingestion deltas.

The labeller and public API are both untrusted inputs.  Validation therefore happens before any
merge mutates a knowledge base, and every failure is returned as data rather than surfacing as a
``KeyError``/``TypeError`` halfway through a write.
"""

_VERIFIED = {"exact", "fuzzy", "missing"}
_DEPTHS = {"full", "abstract", "partial", "unknown"}
_KINDS = {"dataset", "document", "argument", "model"}
_WEIGHTS = {"high", "med", "medium", "moderate", "low", "n/a", "na", "none",
            "not applicable"}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _string(errors, value, path, required=False, maximum=5000):
    if value is None:
        if required:
            errors.append(path + " is required")
        return
    if not isinstance(value, str):
        errors.append(path + " must be a string")
        return
    if required and not value.strip():
        errors.append(path + " is required")
    if len(value) > maximum:
        errors.append("{} is too long (max {} chars)".format(path, maximum))


def _string_list(errors, value, path, maximum=100, item_max=500):
    if value is None:
        return
    if not isinstance(value, list):
        errors.append(path + " must be an array")
        return
    if len(value) > maximum:
        errors.append("{} has too many entries (max {})".format(path, maximum))
    for i, item in enumerate(value[:maximum + 1]):
        _string(errors, item, "{}[{}]".format(path, i), maximum=item_max)


def _provenance(errors, value, path):
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(path + " must be an object")
        return
    _string(errors, value.get("quote"), path + ".quote", maximum=5000)
    if "verifiedQuote" in value and value.get("verifiedQuote") not in _VERIFIED:
        errors.append(path + ".verifiedQuote must be exact, fuzzy, or missing")
    confidence = value.get("extractionConfidence")
    if confidence is not None and (not _is_number(confidence) or not 0 <= confidence <= 1):
        errors.append(path + ".extractionConfidence must be a number from 0 to 1")
    qv = value.get("quoteVerification")
    if qv is not None and not isinstance(qv, dict):
        errors.append(path + ".quoteVerification must be an object")


def delta_validation_errors(delta, max_roots=40, max_factors=40):
    """Return every structural error in an ingestion delta; never raise on malformed input."""
    errors = []
    if not isinstance(delta, dict):
        return ["delta must be an object"]
    if "sourceId" in delta:
        _string(errors, delta.get("sourceId"), "delta.sourceId", required=True, maximum=80)
    src = delta.get("source")
    if not isinstance(src, dict):
        errors.append("delta.source must be an object")
        return errors

    if "relevant" in src and not isinstance(src.get("relevant"), bool):
        errors.append("delta.source.relevant must be true or false")
    _string(errors, src.get("title"), "delta.source.title",
            required=src.get("relevant") is not False, maximum=500)
    _string(errors, src.get("position"), "delta.source.position",
            required=src.get("relevant") is not False, maximum=300)
    _string(errors, src.get("positionShort"), "delta.source.positionShort", maximum=80)
    _string(errors, src.get("offTopicReason"), "delta.source.offTopicReason", maximum=1000)
    _string(errors, src.get("url"), "delta.source.url", maximum=2048)
    for field in ("venue", "evidence", "funding", "population", "confidence"):
        _string(errors, src.get(field), "delta.source." + field, maximum=500)
    _string_list(errors, src.get("authors"), "delta.source.authors", maximum=100, item_max=500)
    _string_list(errors, src.get("fundingDetails"), "delta.source.fundingDetails",
                 maximum=100, item_max=1000)
    year = src.get("year")
    if year is not None and not isinstance(year, (int, str)):
        errors.append("delta.source.year must be an integer, string, or null")
    elif isinstance(year, str) and len(year) > 20:
        errors.append("delta.source.year is too long (max 20 chars)")
    citations = src.get("citations")
    if citations is not None and (not isinstance(citations, int) or isinstance(citations, bool)
                                  or citations < 0):
        errors.append("delta.source.citations must be a non-negative integer or null")
    if "retracted" in src and not isinstance(src.get("retracted"), bool):
        errors.append("delta.source.retracted must be true or false")
    if src.get("textDepth") is not None and src.get("textDepth") not in _DEPTHS:
        errors.append("delta.source.textDepth must be full, abstract, partial, or unknown")
    agreement = src.get("modelAgreement")
    if agreement is not None:
        if not isinstance(agreement, dict):
            errors.append("delta.source.modelAgreement must be an object")
        else:
            if "flagged" in agreement and not isinstance(agreement.get("flagged"), bool):
                errors.append("delta.source.modelAgreement.flagged must be true or false")
            models = agreement.get("models")
            if models is not None and (not isinstance(models, int) or isinstance(models, bool)
                                       or models < 0):
                errors.append("delta.source.modelAgreement.models must be a non-negative integer")
            _string_list(errors, agreement.get("disagreedFields"),
                         "delta.source.modelAgreement.disagreedFields", maximum=100, item_max=100)
            proposals = agreement.get("proposals")
            if proposals is not None:
                if not isinstance(proposals, list):
                    errors.append("delta.source.modelAgreement.proposals must be an array")
                else:
                    if len(proposals) > 20:
                        errors.append("delta.source.modelAgreement.proposals has too many entries (max 20)")
                    for i, proposal in enumerate(proposals[:21]):
                        path = "delta.source.modelAgreement.proposals[{}]".format(i)
                        if not isinstance(proposal, dict):
                            errors.append(path + " must be an object")
                            continue
                        _string(errors, proposal.get("position"), path + ".position",
                                required=True, maximum=300)
                        _string(errors, proposal.get("quote"), path + ".quote", maximum=5000)
            vote = agreement.get("positionVote")
            if vote is not None and not isinstance(vote, dict):
                errors.append("delta.source.modelAgreement.positionVote must be an object")

    provenance = src.get("provenance")
    if provenance is not None and not isinstance(provenance, dict):
        errors.append("delta.source.provenance must be an object")
    elif isinstance(provenance, dict):
        if len(provenance) > 50:
            errors.append("delta.source.provenance has too many fields (max 50)")
        for field, value in provenance.items():
            if not isinstance(field, str):
                errors.append("delta.source.provenance keys must be strings")
            else:
                _provenance(errors, value, "delta.source.provenance." + field)

    rests = src.get("restsOn", [])
    if not isinstance(rests, list):
        errors.append("delta.source.restsOn must be an array")
    else:
        if len(rests) > max_roots:
            errors.append("delta.source.restsOn has too many entries (max {})".format(max_roots))
        for i, edge in enumerate(rests[:max_roots + 1]):
            path = "delta.source.restsOn[{}]".format(i)
            if isinstance(edge, str):
                _string(errors, edge, path, required=True, maximum=300)
                continue
            if not isinstance(edge, dict):
                errors.append(path + " must be a string or {ref, provenance} object")
                continue
            _string(errors, edge.get("ref"), path + ".ref", required=True, maximum=300)
            _provenance(errors, edge.get("provenance"), path + ".provenance")
            kind = edge.get("datasetKind", edge.get("kind"))
            if kind is not None and str(kind).strip().lower() not in _KINDS:
                errors.append(path + ".datasetKind must be dataset, document, argument, or model")
            if "admission" in edge:
                errors.append(path + ".admission is curator-controlled and is not accepted in deltas")

    factors = delta.get("factorWeights", [])
    if not isinstance(factors, list):
        errors.append("delta.factorWeights must be an array")
    else:
        if len(factors) > max_factors:
            errors.append("delta.factorWeights has too many entries (max {})".format(max_factors))
        for i, claim in enumerate(factors[:max_factors + 1]):
            path = "delta.factorWeights[{}]".format(i)
            if not isinstance(claim, dict):
                errors.append(path + " must be an object")
                continue
            label = claim.get("factorLabel", claim.get("factor"))
            _string(errors, label, path + ".factorLabel", required=True, maximum=300)
            weight = claim.get("weight")
            if not isinstance(weight, str) or weight.strip().lower() not in _WEIGHTS:
                errors.append(path + ".weight must be high, med, low, or n/a")
            _string(errors, claim.get("rationale"), path + ".rationale", maximum=3000)
            _string(errors, claim.get("quote"), path + ".quote", maximum=5000)
            if claim.get("verifiedQuote") is not None and claim.get("verifiedQuote") not in _VERIFIED:
                errors.append(path + ".verifiedQuote must be exact, fuzzy, or missing")
            if claim.get("quoteVerification") is not None and not isinstance(
                    claim.get("quoteVerification"), dict):
                errors.append(path + ".quoteVerification must be an object")
    return errors


def require_valid_delta(delta):
    """Raise one concise ``ValueError`` if a delta is not safe to merge."""
    errors = delta_validation_errors(delta)
    if errors:
        raise ValueError("; ".join(errors))
    return delta
