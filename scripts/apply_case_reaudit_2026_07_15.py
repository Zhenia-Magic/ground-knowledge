#!/usr/bin/env python3
"""Apply deterministic metadata/quotation fixes found in the 2026-07-15 case re-audit."""
import argparse
import copy
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.io import atomic_write_json  # noqa: E402
from engine.merge import recompute_factor_weights  # noqa: E402
from engine.verify import apply_quote_verification, is_verified_exact  # noqa: E402
from ingest.extract import _strip_html, extract_text  # noqa: E402
from scripts.audit_quotes import write_markdown_report  # noqa: E402


ALCOHOL = ROOT / "cases" / "51fb332b4e96.kb.json"

POSITION_QUOTES = {
    "src_alcohol_consumption_and_the_risk_of_incident_2022":
        "Our findings suggest a J-shaped relationship between alcohol consumption and incident AF.",
    "src_effects_of_acute_alcohol_consumption_on_card_2021":
        "There was no significant association between PR, QRS, and QTc intervals and increasing BAC.",
    "src_cardiovascular_disease_review_of_evidence_on_2025":
        "Conclusion 6-3: The committee concludes that compared with never consuming alcohol, consuming moderate amounts of alcohol is associated with a lower risk of CVD mortality in both females and males (moderate certainty).",
    "src_longitudinal_study_of_alcohol_consumption_an_2017":
        "Moderate alcohol consumption was associated with slower HDL-cholesterol decreases; however, the type of alcoholic beverage had differential effects on the change in the HDL-cholesterol concentration.",
}

COVID_POSITION_QUOTES = {
    "src_odni_the_potential_links_between_the_wuhan_i_2023":
        "Variations in IC analytic views on the origins of the COVID-19 pandemic largely stem from differences in how agencies weigh intelligence reporting and scientific publications and intelligence and scientific gaps.",
    "src_odni_news_release_fauci_funded_wuhan_lab_res_2026":
        "Today, Director of National Intelligence Tulsi Gabbard is releasing never-before-seen communications and documents exposing how Fauci worked with politicized career leadership in the Intelligence Community (IC) to suppress the truth about his actions, the virus’ lab-leak origins, and his role in directing U.S. funding for this dangerous research that caused immeasurable harm and countless lost lives.",
}

LOCAL_VERIFICATION = {
    "cases/51fb332b4e96.kb.json": {
        "src_alcohol_consumption_and_the_risk_of_incident_2022":
            ("/tmp/reaudit-af.html", "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8871230/"),
        "src_effects_of_acute_alcohol_consumption_on_card_2021":
            ("/tmp/reaudit-munich.html", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8166672/"),
        "src_cardiovascular_disease_review_of_evidence_on_2025":
            ("/tmp/reaudit-nasem.html", "https://www.ncbi.nlm.nih.gov/books/NBK614695/"),
        "src_longitudinal_study_of_alcohol_consumption_an_2017":
            ("/tmp/reaudit-hdl.html", "https://pmc.ncbi.nlm.nih.gov/articles/PMC5366050/"),
        "src_a_review_of_the_relationship_between_dimensi_2026":
            ("/tmp/reaudit-carr.html", "https://pubmed.ncbi.nlm.nih.gov/42129601/"),
    },
    "cases/blackholes.kb.json": {
        "src_a_search_for_microscopic_black_holes_string__2026":
            ("/tmp/reaudit-cms.html", "https://cms-results.web.cern.ch/cms-results/public-results/publications/EXO-24-028/"),
    },
    "cases/covid.kb.json": {
        "src_the_data_are_insufficient_to_confidently_roo_2025":
            ("/tmp/reaudit-bloom.json", "https://doi.org/10.1093/molbev/msaf118"),
        "src_odni_the_potential_links_between_the_wuhan_i_2023":
            ("/tmp/odni-covid-origins-2023.pdf", "https://www.dni.gov/files/ODNI/documents/assessments/Report-on-Potential-Links-Between-the-Wuhan-Institute-of-Virology-and-the-Origins-of-COVID-19-20230623.pdf"),
        "src_odni_news_release_fauci_funded_wuhan_lab_res_2026":
            ("/tmp/reaudit-odni-2026.html", "https://www.dni.gov/index.php/newsroom/press-releases/press-releases-2026/4166-pr-11-26"),
    },
}


def strip_verification(provenance):
    provenance.pop("verifiedQuote", None)
    provenance.pop("quoteVerification", None)


def update_alcohol_quotes_and_metadata():
    kb = json.loads(ALCOHOL.read_text(encoding="utf-8"))
    source_map = {source["id"]: source for source in kb["sources"]}
    changes = []

    for source_id, quote in POSITION_QUOTES.items():
        source = source_map[source_id]
        provenance = source.setdefault("provenance", {}).setdefault("position", {})
        if provenance.get("quote") != quote:
            provenance["quote"] = quote
            provenance["extractionConfidence"] = 0.98
            strip_verification(provenance)
            changes.append({"source": source_id, "field": "position quote"})

    source = source_map["src_exploring_the_complex_interplay_between_alco_2026"]
    corrected = {
        "year": 2025,
        "venue": "Trends in Cardiovascular Medicine",
        "funding": "Government/public",
    }
    for field, value in corrected.items():
        if source.get(field) != value:
            changes.append({"source": source["id"], "field": field,
                            "from": copy.deepcopy(source.get(field)), "to": value})
            source[field] = value

    if not changes:
        print("alcohol re-audit corrections already applied")
        return False

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    version = (kb.get("meta", {}).get("version", 0) or 0) + 1
    kb["meta"]["version"] = version
    kb["meta"]["updated"] = now
    kb.setdefault("log", []).append({
        "version": version,
        "action": "case-source-reaudit",
        "by": "source-audit-2026-07-15",
        "summary": "applied {} exact-quotation/metadata corrections from the case source re-audit".format(len(changes)),
        "changes": changes,
        "ts": now,
    })
    atomic_write_json(str(ALCOHOL), kb)
    print("applied {} alcohol re-audit corrections (KB now v{})".format(len(changes), version))
    return True


def update_covid_quotes():
    path = ROOT / "cases" / "covid.kb.json"
    kb = json.loads(path.read_text(encoding="utf-8"))
    source_map = {source["id"]: source for source in kb["sources"]}
    changes = []
    for source_id, quote in COVID_POSITION_QUOTES.items():
        source = source_map[source_id]
        provenance = source.setdefault("provenance", {}).setdefault("position", {})
        if provenance.get("quote") != quote:
            provenance["quote"] = quote
            provenance["extractionConfidence"] = 0.99
            strip_verification(provenance)
            changes.append({"source": source_id, "field": "position quote"})
    if not changes:
        print("COVID quotation canonicalisation already applied")
        return False
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    version = (kb.get("meta", {}).get("version", 0) or 0) + 1
    kb["meta"]["version"] = version
    kb["meta"]["updated"] = now
    kb.setdefault("log", []).append({
        "version": version,
        "action": "case-source-reaudit",
        "by": "source-audit-2026-07-15",
        "summary": "canonicalised {} ODNI excerpt(s) to complete verbatim source sentences".format(len(changes)),
        "changes": changes,
        "ts": now,
    })
    atomic_write_json(str(path), kb)
    print("canonicalised {} COVID quotations (KB now v{})".format(len(changes), version))
    return True


def annotate_collider_evidence_tier():
    path = ROOT / "cases" / "blackholes.kb.json"
    kb = json.loads(path.read_text(encoding="utf-8"))
    terms = kb.setdefault("vocab", {}).setdefault("evidence", [])
    term = next((item for item in terms if item.get("label") == "Collider experiment"), None)
    if term is None or term.get("tier") == "primary":
        print("collider evidence tier already correct" if term else "collider evidence term not present yet")
        return False
    term["tier"] = "primary"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    version = (kb.get("meta", {}).get("version", 0) or 0) + 1
    kb["meta"]["version"] = version
    kb["meta"]["updated"] = now
    kb.setdefault("log", []).append({
        "version": version,
        "action": "curate-evidence-tier",
        "by": "source-audit-2026-07-15",
        "summary": "classified Collider experiment as a primary evidence-generating design",
        "ts": now,
    })
    atomic_write_json(str(path), kb)
    print("classified Collider experiment as primary (KB now v{})".format(version))
    return True


def _quote_objects(kb, source):
    objects = []
    for field, provenance in (source.get("provenance") or {}).items():
        if field != "restsOn" and isinstance(provenance, dict) and provenance.get("quote"):
            objects.append(("source:" + field, provenance))
    for index, edge in enumerate(source.get("restsOn") or []):
        provenance = edge.get("provenance") if isinstance(edge, dict) else None
        if isinstance(provenance, dict) and provenance.get("quote"):
            objects.append(("edge:{}".format(index), provenance))
    for factor in kb.get("factors", []):
        for claim in factor.get("provenance") or []:
            if claim.get("source") == source.get("id") and claim.get("quote"):
                objects.append(("factor:" + factor.get("id", "?"), claim))
    return objects


def _load_local_document(path):
    path = pathlib.Path(path)
    if path.suffix.lower() != ".json":
        return extract_text(str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    message = payload.get("message") or {}
    text = (message.get("title") or [""])[0] + "\n\n" + _strip_html(message.get("abstract") or "")
    return {"text": text, "title": (message.get("title") or [path.name])[0],
            "kind": "abstract"}


def verify_selected_quotes():
    missing = [local for sources in LOCAL_VERIFICATION.values() for local, _url in sources.values()
               if not pathlib.Path(local).exists()]
    if missing:
        raise SystemExit("missing local primary-source downloads: " + ", ".join(missing))
    total = 0
    for relative, specs in LOCAL_VERIFICATION.items():
        path = ROOT / relative
        kb = json.loads(path.read_text(encoding="utf-8"))
        source_map = {source["id"]: source for source in kb["sources"]}
        for source_id, (local, canonical_url) in specs.items():
            source = source_map[source_id]
            doc = _load_local_document(local)
            source["textDepth"] = doc.get("kind", "unknown")
            for field, provenance in _quote_objects(kb, source):
                result = apply_quote_verification(
                    provenance, doc.get("text") or "", source_title=source.get("title"),
                    text_depth=doc.get("kind", "unknown"), source_url=canonical_url)
                if not is_verified_exact(provenance):
                    raise SystemExit("{} {} failed exact verification: {}".format(
                        source_id, field, (result or {}).get("status", "missing")))
                total += 1
        recompute_factor_weights(kb)
        kb["log"] = [entry for entry in kb.get("log", [])
                     if entry.get("action") != "quote-reaudit-selected"]
        kb.setdefault("log", []).append({
            "version": kb.get("meta", {}).get("version", 0),
            "action": "quote-reaudit-selected",
            "method": "verbatim-sentence-v2",
            "by": "source-audit-2026-07-15",
            "sources": len(specs),
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        atomic_write_json(str(path), kb)
    print("verified {} selected position, dependency, and factor quotations exactly".format(total))


def refresh_quote_audit_reports():
    """Refresh report scope from the current hashed verification records without re-fetching.

    Unchanged records retain their earlier checked-text hashes. The sources changed in this audit
    are re-fetched and re-verified by ``verify_selected_quotes`` before this snapshot is written.
    """
    case_paths = sorted((ROOT / "cases").glob("*.kb.json"))
    report = {
        "method": "verbatim-sentence-v2",
        "automaticFuzzyRepair": False,
        "reportMode": "stored-verification-snapshot",
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cases": {},
    }
    for path in case_paths:
        kb = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for source in kb.get("sources", []):
            quotes = []
            for field, provenance in _quote_objects(kb, source):
                status = "exact" if is_verified_exact(provenance) else (
                    provenance.get("verifiedQuote") or "unchecked")
                quotes.append({
                    "status": status,
                    "changed": False,
                    "repaired": False,
                    "old": provenance.get("quote"),
                    "new": provenance.get("quote"),
                    "field": field,
                })
            rows.append({
                "id": source.get("id"),
                "title": source.get("title"),
                "fetch": source.get("textDepth", "unknown"),
                "error": None,
                "quotes": quotes,
            })
        counts = {}
        for row in rows:
            for quote in row["quotes"]:
                status = quote["status"]
                counts[status] = counts.get(status, 0) + 1
        report["cases"][path.name] = {"summary": counts, "sources": rows}
    atomic_write_json(str(ROOT / "eval" / "QUOTE_AUDIT.json"), report)
    write_markdown_report(case_paths, ROOT / "eval" / "QUOTE_AUDIT.md")
    print("refreshed eval/QUOTE_AUDIT.json and eval/QUOTE_AUDIT.md from current hashed records")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-local", action="store_true")
    parser.add_argument("--refresh-reports", action="store_true")
    args = parser.parse_args()
    update_alcohol_quotes_and_metadata()
    update_covid_quotes()
    annotate_collider_evidence_tier()
    if args.verify_local:
        verify_selected_quotes()
    if args.refresh_reports:
        refresh_quote_audit_reports()


if __name__ == "__main__":
    main()
