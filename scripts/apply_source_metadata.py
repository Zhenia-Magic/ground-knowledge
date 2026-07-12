#!/usr/bin/env python3
"""Apply only curator-approved/high-confidence catalogue metadata to the case KBs.

The fetch report is deliberately separate (audit_source_metadata.py).  This script refuses noisy
matches, preserves stronger existing conflict labels, records named funders, and leaves one versioned
case log entry.  A few source corrections found by manual full-text checking are explicit below.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.merge import now_iso


AUDITOR = "source-audit-2026-07"

# Title annotations make these genuine Crossref matches score below the automatic threshold.  Each
# was manually compared with the stored title and publication page before inclusion.
APPROVED = {
    "src_zhong_et_al_associations_of_dietary_choleste_2019",
    "src_zhuang_et_al_egg_cholesterol_consumption_and_2021",
    "src_drouin_chartier_et_al_egg_consumption_and_ri_2020",
    "src_hu_et_al_a_prospective_study_of_egg_consumpt_1999",
    "src_blesso_fernandez_whole_egg_consumption_impro_2013",
    "src_carson_et_al_dietary_cholesterol_and_cardiov_2020",
    "src_alexander_et_al_meta_analysis_of_egg_consump_2016",
    "src_tran_et_al_egg_consumption_and_cardiovascula_2014",
    "src_shin_et_al_egg_consumption_in_relation_to_ca_2013",
    "src_larsson_et_al_egg_consumption_and_risk_of_he_2015",
    "src_worobey_et_al_the_huanan_market_was_the_earl_2022",
    "src_response_to_segreto_deigin_there_is_still_no_2021",
    "src_boni_et_al_evolutionary_origins_of_the_sars__2020",
    "src_lytras_et_al_exploring_the_natural_origins_o_2022",
    "src_bloom_recovery_of_deleted_deep_sequencing_da_2021",
    "src_latham_wilson_the_mojiang_miners_passage_hyp_2020",
}


def classify_funders(names):
    text = " ".join(names).lower()
    industry = ("novartis", "gilead", "egg board", "egg nutrition", "interprofesional del vino",
                "oive", "pharmaceutical company", "brewing", "winery", "wine industry",
                "alcohol industry")
    government = ("national institute", "national science", "department of", "research council",
                  "minister", "ministry", "european union", "european commission", "government",
                  "instituto de salud", "nih", "nsf", "usda", "cicyt", "feder", "aei")
    nonprofit = ("foundation", "trust", "association", "heart fund", "charitable", "sloan")
    academic = ("university", "universität", "universidad", "institute", "academy")
    if any(term in text for term in industry):
        return "Industry"
    if any(term in text for term in government):
        return "Government/public"
    if any(term in text for term in nonprofit):
        return "Nonprofit/charity"
    if any(term in text for term in academic):
        return "Academic/institutional"
    return None


def manual_corrections(source):
    sid = source.get("id")
    if sid == "src_godos_et_al_egg_consumption_and_cardiovascul_2021":
        source.update({
            "title": "Godos et al. — Egg consumption and cardiovascular risk: a dose-response meta-analysis of prospective cohort studies",
            "year": 2021,
            "url": "https://doi.org/10.1007/s00394-020-02345-7",
            "authors": ["Justyna Godos", "Agnieszka Micek", "Tomasz Brzostek", "Estefania Toledo",
                        "Licia Iacoviello", "Arne Astrup", "Oscar H. Franco", "Fabio Galvano",
                        "Miguel A. Martinez-Gonzalez", "Giuseppe Grosso"],
            "venue": "European Journal of Nutrition",
            "funding": "Government/public",
            "fundingDetails": ["Italian Ministry of Health", "University of Catania"],
            "restsOn": [
                "src:src_drouin_chartier_et_al_egg_consumption_and_ri_2020",
                "src:src_rong_et_al_egg_consumption_and_risk_of_chd_a_2013",
                "src:src_shin_et_al_egg_consumption_in_relation_to_ca_2013",
                "src:src_larsson_et_al_egg_consumption_and_risk_of_he_2015",
            ],
            "provenance": {"position": {
                "quote": "There is no conclusive evidence on the role of egg in CVD risk; possible protection at moderate intake and increased heart-failure risk at high intake both require stronger evidence.",
                "extractionConfidence": 0.97, "verifiedQuote": "fuzzy"}},
            "textDepth": "full",
        })
        return "corrected unrelated PubMed link/quote and restored the actual Godos meta-analysis"
    if sid == "src_spence_jenkins_davignon_egg_yolk_consumption_2010":
        source.update({
            "year": 2012,
            "url": "https://doi.org/10.1016/j.atherosclerosis.2012.07.032",
            "authors": ["J. David Spence", "David J. A. Jenkins", "Jean Davignon"],
            "venue": "Atherosclerosis",
            "funding": "Nonprofit/charity",
            "fundingDetails": ["Heart and Stroke Foundation of Ontario"],
        })
        return "corrected publication year and PubMed link for the carotid-plaque paper"
    if sid == "src_barnard_et_al_industry_funding_and_cholester_2020":
        source.update({
            "title": "Barnard et al. — Industry Funding and Cholesterol Research: A Systematic Review",
            "year": 2019,
            "url": "https://doi.org/10.1177/1559827619892198",
            "authors": ["Neal D. Barnard", "M. Blaire Long", "Jennifer M. Ferguson", "Rosendo Flores", "Hana Kahleova"],
            "venue": "American Journal of Lifestyle Medicine",
            "funding": "Advocacy",
            "fundingDetails": ["Conflict disclosed: lead author was uncompensated president of the Physicians Committee for Responsible Medicine, which advocates plant-based diets"],
        })
        return "replaced an unrelated JAHA DOI with the actual funding-review publication"
    if sid == "src_holmes_et_al_the_origins_of_sars_cov_2_a_cri_2021":
        source.update({
            "url": "https://doi.org/10.1016/j.cell.2021.08.017",
            "venue": "Cell",
            "funding": "Government/public",
            "fundingDetails": ["Public/nonprofit grants including BBSRC, MRC, NIH, NSF, ERC, Wellcome Trust, CEPI and the Gates Foundation"],
        })
        return "repaired truncated Cell URL and added the article funding statement"
    if sid == "src_crits_christoph_et_al_genetic_tracing_of_mar_2024":
        source.update({
            "url": "https://doi.org/10.1016/j.cell.2024.08.010", "venue": "Cell",
            "provenance": {"position": {
                "quote": "Market-linked SARS-CoV-2 genetic diversity is consistent with market emergence, and wildlife DNA was identified in SARS-CoV-2-positive samples from a wildlife stall.",
                "extractionConfidence": 0.97, "verifiedQuote": "fuzzy"}},
        })
        return "replaced a preprint PubMed link and an irrelevant SARS-CoV-1 excerpt with the 2024 Cell article and finding"
    if sid == "src_emergence_of_the_spike_furin_cleavage_site_i_2022":
        source.update({
            "title": "Chan & Zhan — The Emergence of the Spike Furin Cleavage Site in SARS-CoV-2",
            "authors": ["Yujia Alina Chan", "Shing Hei Zhan"],
            "venue": "Molecular Biology and Evolution",
            "url": "https://doi.org/10.1093/molbev/msab327",
            "provenance": {"position": {
                "quote": "Without access to the full set of viral sequences available before the emergence of SARS-CoV-2, it is difficult to know what novel cleavage sites were characterized and how they were introduced.",
                "extractionConfidence": 0.96, "verifiedQuote": "fuzzy"}},
            "textDepth": "full",
        })
        return "removed the false 'natural-evolution account' gloss and restored the paper's genuinely unresolved conclusion"
    if sid == "src_kent_a_critical_look_at_risk_assessments_for_2004":
        source.update({
            "url": "https://doi.org/10.1111/j.0272-4332.2004.00419.x",
            "authors": ["Adrian Kent"], "venue": "Risk Analysis", "textDepth": "abstract",
            "provenance": {"position": {
                "quote": "The costs of small risks of catastrophe have been significantly underestimated; acceptable risk bounds should be agreed before hypothetically risky experiments.",
                "extractionConfidence": 0.96, "verifiedQuote": "fuzzy"}},
        })
        return "replaced an arXiv page-header excerpt with the published abstract finding"
    if sid == "src_alcohol_consumption_and_cardiovascular_disea_2024":
        # Crossref identifies only university support; the prior Industry label had no named basis.
        source["funding"] = "Academic/institutional"
        source["fundingDetails"] = ["University of Medicine and Pharmacy of Craiova, Romania"]
        return "corrected an unsupported Industry label to the named university funder"

    manual_meta = {
        "src_analysis_of_the_defuse_proposal_ecohealth_wi_2023": (["U.S. Right to Know"], "U.S. Right to Know"),
        "src_rootclaim_saar_wilf_bayesian_analysis_of_cov_2024": (["Saar Wilf"], "Rootclaim"),
        "src_weissman_an_inconvenient_probability_bayesia_2024": (["Michael Weissman"], "Substack"),
        "src_peter_miller_the_case_for_zoonosis_covid_ori_2024": (["Peter Miller"], "COVID Origins Debate"),
        "src_who_china_joint_study_on_the_origins_of_sars_2021": (["WHO-convened global study team"], "World Health Organization"),
        "src_us_odni_updated_assessment_on_covid_19_origi_2023": (["Office of the Director of National Intelligence"], "U.S. ODNI"),
        "src_wade_the_origin_of_covid_did_people_or_natur_2021": (["Nicholas Wade"], "Bulletin of the Atomic Scientists"),
        "src_scott_alexander_i_watched_15_hours_of_covid__2024": (["Scott Alexander"], "Astral Codex Ten"),
        "src_boni_et_al_evolutionary_origins_of_the_sars__2020": (source.get("authors") or ["Maciej F. Boni et al."], "Nature Microbiology"),
        "src_lytras_et_al_exploring_the_natural_origins_o_2022": (source.get("authors") or ["Spyros Lytras et al."], "Genome Biology and Evolution"),
        "src_quay_bayesian_analysis_of_sars_cov_2_origin__2021": (["Steven Quay"], "Zenodo"),
        "src_courtier_orgogozo_de_ribera_sars_cov_2_infec_2022": (["Virginie Courtier-Orgogozo", "Francisco A. de Ribera"], "HAL open archive"),
        "src_ellis_giudice_mangano_tkachev_wiedemann_revi_2008": (["John Ellis", "Gian Giudice", "Michelangelo Mangano", "Igor Tkachev", "Urs Wiedemann"], "Journal of Physics G"),
        "src_calogero_might_a_laboratory_experiment_destr_2000": (["Francesco Calogero"], "Interdisciplinary Science Reviews"),
        "src_johnson_the_black_hole_case_the_injunction_a_2009": (["Eric E. Johnson"], "Legal analysis / arXiv"),
        "src_cern_the_safety_of_the_lhc_public_statement_2008": (["CERN"], "CERN"),
        "src_hut_rees_how_stable_is_our_vacuum_cosmic_ray_1983": (["Piet Hut", "Martin Rees"], "Nature"),
        "src_blaizot_et_al_study_of_potentially_dangerous_2003": (["J.-P. Blaizot", "J. Iliopoulos", "J. Madsen", "G. G. Ross", "P. Sonderegger", "H.-J. Specht"], "CERN Yellow Reports"),
        "src_casadio_fabi_harms_on_the_catastrophic_black_2010": (["Roberto Casadio", "Sergio Fabi", "Benjamin Harms"], "arXiv"),
        "src_cavagli_particle_accelerators_as_black_hole__2010": (["Marco Cavaglià"], "arXiv"),
        "src_plaga_on_the_potential_catastrophic_risk_fro_2008": (["Rainer Plaga"], "arXiv"),
        "src_giddings_mangano_comments_on_claimed_risk_fr_2008": (["Steven B. Giddings", "Michelangelo L. Mangano"], "arXiv"),
        "src_dehghan_et_al_egg_consumption_and_cvd_mortal_2020": (["Mahshid Dehghan", "Andrew Mente", "Sumathy Rangarajan", "Viswanathan Mohan", "et al."], "The American Journal of Clinical Nutrition"),
        "src_qin_et_al_egg_consumption_and_cardiovascular_2018": (["Canqing Yu", "Ling Yang", "Yiping Chen", "Zheng Bian", "et al."], "Heart"),
        "src_rong_et_al_egg_consumption_and_risk_of_chd_a_2013": (["Ying Rong", "Li Chen", "Tingting Zhu", "et al."], "BMJ"),
        "src_fuller_et_al_diabegg_high_vs_low_egg_diet_in_2018": (["Nicholas R. Fuller", "Amanda Sainsbury", "Ian D. Caterson", "et al."], "The American Journal of Clinical Nutrition"),
        "src_djouss_gaziano_egg_consumption_and_risk_of_h_2008": (["Luc Djoussé", "J. Michael Gaziano"], "Circulation"),
        "src_virtanen_et_al_egg_consumption_and_risk_of_c_2016": (["Jyrki K. Virtanen", "Jaakko Mursu", "Hassan E. K. Virtanen", "et al."], "The American Journal of Clinical Nutrition"),
        "src_nih_to_end_funding_for_moderate_alcohol_and__2018": (["National Institutes of Health"], source.get("venue") or "NIH News Release"),
        "src_prioritizing_health_uncorking_the_evidence_t_2026": (["American College of Cardiology"], source.get("venue") or "ACC Cardiology Magazine"),
    }
    if sid in manual_meta:
        authors, venue = manual_meta[sid]
        source["authors"] = authors
        source["venue"] = venue
        return "filled author and venue metadata from the publication page"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--report", required=True)
    ap.add_argument("--min-match", type=float, default=0.8)
    args = ap.parse_args(argv)
    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    by_id = {}
    for rows in report.get("cases", {}).values():
        for row in rows:
            by_id[row.get("id")] = row.get("candidate") or {}

    for path in args.files:
        with open(path, encoding="utf-8") as f:
            kb = json.load(f)
        changes = []
        for source in kb.get("sources", []):
            before = json.dumps(source, sort_keys=True, ensure_ascii=False)
            manual = manual_corrections(source)
            candidate = by_id.get(source.get("id"), {})
            accepted = candidate.get("match", 0) >= args.min_match or source.get("id") in APPROVED
            if accepted:
                if not source.get("authors") and candidate.get("authors"):
                    source["authors"] = candidate["authors"]
                if not source.get("venue") and candidate.get("venue"):
                    source["venue"] = candidate["venue"]
                funders = list(dict.fromkeys(candidate.get("funders") or []))
                if funders:
                    source["fundingDetails"] = funders
                    category = classify_funders(funders)
                    if category and source.get("funding") not in {"Industry", "Advocacy"}:
                        source["funding"] = category
            if json.dumps(source, sort_keys=True, ensure_ascii=False) != before:
                source["metadataAudit"] = {"by": AUDITOR, "ts": now_iso(),
                                           "method": "catalogue+manual-full-text"}
                changes.append({"source": source.get("id"), "manual": manual,
                                "catalogueMatch": candidate.get("match") if accepted else None})
        if changes:
            version = (kb.get("meta", {}).get("version") or 0) + 1
            kb["meta"]["version"] = version
            kb["meta"]["updated"] = now_iso()
            kb.setdefault("log", []).append({
                "version": version, "action": "source-metadata-audit", "by": AUDITOR,
                "summary": "corrected/enriched metadata for {} source(s)".format(len(changes)),
                "changes": changes, "ts": kb["meta"]["updated"],
            })
            with open(path, "w", encoding="utf-8") as f:
                json.dump(kb, f, indent=2, ensure_ascii=False)
                f.write("\n")
        print("{}: {} source metadata record(s) changed".format(path, len(changes)))


if __name__ == "__main__":
    main()
