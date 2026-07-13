#!/usr/bin/env python3
"""One-off, human-reviewed migration of every non-exact stored excerpt.

Candidates are copied only from the freshly fetched document corpus.  Claims for which the fetched
source does not contain a defensible sentence lose the unsupported quote (or factor-provenance
claim) rather than receiving a paraphrase.  Run ``audit_quotes.py --write`` afterwards; this script
never grants verification status itself.
"""
import argparse
import difflib
import gzip
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.verify import _loose_norm, _segments, is_verified_exact  # noqa: E402


def _score(quote, sentence):
    a, b = _loose_norm(quote).split(), _loose_norm(sentence).split()
    aa, bb = set(a), set(b)
    coverage = len(aa & bb) / max(1, len(aa))
    jaccard = len(aa & bb) / max(1, len(aa | bb))
    sequence = difflib.SequenceMatcher(None, " ".join(a), " ".join(b), autojunk=False).ratio()
    return 0.5 * coverage + 0.2 * jaccard + 0.3 * sequence


# Exact sentences selected after reviewing the freshly fetched full text.
OVERRIDES = {
    ("covid.kb.json", "src_worobey_et_al_the_huanan_market_was_the_earl_2022", "position"):
        "While there is insufficient evidence to define upstream events, and exact circumstances remain obscure, our analyses indicate that the emergence of SARS-CoV-2 occurred via the live wildlife trade in China, and show that the Huanan market was the epicenter of the COVID-19 pandemic.",
    ("covid.kb.json", "src_worobey_et_al_the_huanan_market_was_the_earl_2022", "factor:f_epidemiological_proximity_of_the_earliest_ca"):
        "We show the earliest known COVID-19 cases from December 2019, including those without reported direct links, were geographically centered on this market.",
    ("51fb332b4e96.kb.json", "src_alcohol_cardiovascular_disease_and_industry__2021", "edge:0"):
        "We used Epistemonikos to identify systematic reviews.",
    ("51fb332b4e96.kb.json", "src_cardiovascular_disease_review_of_evidence_on_2025", "position"):
        "A subset of studies examined associations of moderate alcohol consumption—with the risk of MI, stroke, and CVD death—with particular care to include people who never consumed alcohol as the reference group.",
    ("51fb332b4e96.kb.json", "src_alcohol_consumption_and_risks_of_more_than_2_2023", "edge:0"):
        "We investigated the associations of alcohol consumption with 207 diseases in the 12-year China Kadoorie Biobank of >512,000 adults (41% men), including 168,050 genotyped for ALDH2 - rs671 and ADH1B - rs1229984 , with >1.1 million ICD-10 coded hospitalized events.",
    ("51fb332b4e96.kb.json", "src_risk_thresholds_for_total_and_beverage_speci_2021", "edge:0"):
        "Methods Using data from the UK Biobank, total and beverage-specific alcohol consumption was calculated as UK standard drinks (8 g alcohol) per week.",
    ("51fb332b4e96.kb.json", "src_urinary_tartaric_acid_as_a_biomarker_of_wine_2024", "edge:0"):
        "Methods A case-cohort nested study was designed within the PREDIMED trial with 1232 participants: 685 incident cases of CVD and a random subcohort of 625 participants (including 78 overlapping cases).",
    ("51fb332b4e96.kb.json", "src_exploring_causal_associations_of_alcohol_wit_2015", "position"):
        "Conclusion This study provides further evidence that the associations between alcohol consumption and increases in blood pressure and HDL cholesterol are causal.",
    ("51fb332b4e96.kb.json", "src_alcohol_consumption_and_cardiovascular_healt_2022", "position"):
        "However, higher risk for cardiovascular disease mortality was typically seen with heavier daily or weekly alcohol consumption across all types of beverages.",
    ("blackholes.kb.json", "src_lhc_safety_assessment_group_lsag_review_of_t_2008", "position"):
        "The stability of astronomical bodies constrains strongly the possible rate of accretion by any such microscopic black holes, so that they present no conceivable danger.",
    ("blackholes.kb.json", "src_cavagli_particle_accelerators_as_black_hole__2010", "position"):
        "By this process, the mini-black holes formed in particle accelerators would evaporate nearly as soon as they are created – typically, such black holes would only exist for a few tenth of a trillionth of a trillionth (10 -25 , in exponential notation ) seconds.",
    ("covid.kb.json", "src_who_china_joint_study_on_the_origins_of_sars_2021", "position"):
        "Assessment of likelihood In view of the above, a laboratory origin of the pandemic was considered to be extremely unlikely.",
    ("covid.kb.json", "src_garry_sars_cov_2_furin_cleavage_site_was_not_2022", "position"):
        "We also noted, correctly, that placing the insertion out of frame would be “an unusual and needlessly complex feat of genetic engineering.”",
    ("covid.kb.json", "src_harrison_sachs_a_call_for_an_independent_inq_2022", "position"):
        "However, we do assert that there has been no independent and transparent scientific scrutiny to date of the full scope of the US-based evidence.",
    ("covid.kb.json", "src_analysis_of_the_defuse_proposal_ecohealth_wi_2023", "position"):
        "While the language of the formal DEFUSE proposal called for the insertion of “human specific proteolytic cleavage sites” in a portion of the spike protein called the “S2′,” earlier drafts of DEFUSE were more explicit.",
    ("eggs.kb.json", "src_larsson_et_al_egg_consumption_and_risk_of_he_2015", "position"):
        "Consumption of eggs ≥1 time/d, but not less frequent consumption, was associated with an elevated risk of HF in men.",
    ("eggs.kb.json", "src_dehghan_et_al_egg_consumption_and_cvd_mortal_2020", "position"):
        "In 3 large international prospective studies including ∼177,000 individuals, 12,701 deaths, and 13,658 CVD events from 50 countries in 6 continents, we did not find significant associations between egg intake and blood lipids, mortality, or major CVD events.",
    ("eggs.kb.json", "src_blesso_fernandez_whole_egg_consumption_impro_2013", "position"):
        "Conclusions Incorporating daily whole egg intake into a moderately carbohydrate-restricted diet provides further improvements in the atherogenic lipoprotein profile and in insulin resistance in individuals with MetS.",
    ("eggs.kb.json", "src_spence_jenkins_davignon_egg_yolk_consumption_2010", "position"):
        "Interpretation Our findings suggest that regular consumption of egg yolk should be avoided by persons at risk of cardiovascular disease.",

    ("blackholes.kb.json", "src_giddings_mangano_astrophysical_implications__2008", "factor:f_reliability_of_the_cosmic_ray_safety_analogy"):
        "We argue that cases with such an effect at shorter times than the solar lifetime are ruled out, since in these scenarios black holes produced by cosmic rays impinging on much denser white dwarfs and neutron stars would then catalyze their decay on time scales incompatible with their known lifetimes.",
    ("blackholes.kb.json", "src_ord_hillerbrand_sandberg_probing_the_improba_2010", "factor:f_reliability_of_the_cosmic_ray_safety_analogy"):
        "If the probability estimate given by an argument is dwarfed by the chance that the argument itself is flawed, then the estimate is suspect.",
    ("covid.kb.json", "src_rootclaim_saar_wilf_bayesian_analysis_of_cov_2024", "factor:f_reliability_of_bayesian_priors_and_likelihoo"):
        "The mistakes were heavily skewed toward zoonosis, since our methodology involves steelmanning and maximizing the likelihoods of both hypotheses, while Miller used figures heavily biased toward zoonosis, in some cases using extreme estimates that are impossible to reach in a robust probabilistic analysis, as we explain below.",
    ("covid.kb.json", "src_weissman_an_inconvenient_probability_bayesia_2024", "factor:f_reliability_of_bayesian_priors_and_likelihoo"):
        "Methods The standard logical procedure to calculate the odds, P(LL)/P(ZW), is to combine some rough prior sense of the odds with judgments of how consistent new pieces of evidence are with the LL and ZW hypotheses.",
    ("covid.kb.json", "src_garry_sars_cov_2_furin_cleavage_site_was_not_2022", "factor:f_furin_cleavage_site_as_evidence_of_laborator"):
        "We also noted, correctly, that placing the insertion out of frame would be “an unusual and needlessly complex feat of genetic engineering.”",
    ("covid.kb.json", "src_analysis_of_the_defuse_proposal_ecohealth_wi_2023", "factor:f_prior_probability_of_a_research_related_acci"):
        "Specifically, the scientists sought to insert furin cleavage sites at the S1/S2 junction of the spike protein; to assemble synthetic viruses in six segments; to identify coronaviruses up to 25 percent different from SARS; and to select for receptor binding domains adept at infecting human receptors.",

    ("51fb332b4e96.kb.json", "src_association_of_habitual_alcohol_intake_with__2022", "factor:f_observational_study_bias_overestimation_conc"):
        "In linear mendelian randomization analyses, a 1-SD increase in genetically predicted alcohol consumption was associated with 1.3-fold (95% CI, 1.2-1.4) higher risk of hypertension (_P_< .001) and 1.4-fold (95% CI, 1.1-1.8) higher risk of coronary artery disease (_P_ = .006).",
    ("51fb332b4e96.kb.json", "src_cardiovascular_disease_review_of_evidence_on_2025", "factor:f_observational_study_bias_overestimation_conc"):
        "A subset of studies examined associations of moderate alcohol consumption—with the risk of MI, stroke, and CVD death—with particular care to include people who never consumed alcohol as the reference group.",
    ("51fb332b4e96.kb.json", "src_association_between_alcohol_and_cardiovascul_2014", "factor:f_mendelian_randomisation_genetic_confounding_"):
        "This suggests that reduction of alcohol consumption, even for light to moderate drinkers, is beneficial for cardiovascular health.",
    ("51fb332b4e96.kb.json", "src_alcohol_consumption_in_relation_to_cardiovas_2021", "factor:f_mendelian_randomisation_genetic_confounding_"):
        "Six out of the nine studies (67%) that assessed cardiovascular disease as outcome reported null associations.",
    ("51fb332b4e96.kb.json", "src_exploring_causal_associations_of_alcohol_wit_2015", "factor:f_mendelian_randomisation_genetic_confounding_"):
        "Conclusion This study provides further evidence that the associations between alcohol consumption and increases in blood pressure and HDL cholesterol are causal.",
    ("51fb332b4e96.kb.json", "src_a_mendelian_randomization_study_of_alcohol_u_2024", "factor:f_mendelian_randomisation_genetic_confounding_"):
        "Conclusions We replicate prior observational studies that show a U‐shaped association between alcohol consumption and cardiometabolic diseases, but MR findings show no causal association between these traits.",
    ("51fb332b4e96.kb.json", "src_moderate_alcohol_use_and_cardiovascular_dise_2013", "factor:f_mendelian_randomisation_genetic_confounding_"):
        "Larger studies are needed to confirm the null associations with IHD, CVD and fasting glucose.",
    ("51fb332b4e96.kb.json", "src_association_of_habitual_alcohol_intake_with__2022", "factor:f_mendelian_randomisation_genetic_confounding_"):
        "In linear mendelian randomization analyses, a 1-SD increase in genetically predicted alcohol consumption was associated with 1.3-fold (95% CI, 1.2-1.4) higher risk of hypertension (_P_< .001) and 1.4-fold (95% CI, 1.1-1.8) higher risk of coronary artery disease (_P_ = .006).",
    ("51fb332b4e96.kb.json", "src_alcohol_cardiovascular_disease_and_industry__2021", "factor:f_cardiovascular_disease_subtype_heterogeneity"):
        "Those with industry funding were more likely to study broader outcomes such as ‘cardiovascular disease’ or ‘coronary heart disease’ as opposed to specific CVD issues such as hypertension or stroke (93% [13/14] versus 41% [19/46]) (chi-squared 12.4, p < 0.001) and have more included studies (mean of 29 versus 20).",
    ("51fb332b4e96.kb.json", "src_reduced_stress_related_neural_network_activi_2023", "factor:f_hormetic_dose_response_drinking_pattern"):
        "Further, AC l/m associated with larger decreases in MACE risk among individuals with (vs without) prior anxiety (HR: 0.60 [95% CI: 0.50-0.72] vs 0.78 [95% CI: 0.73-0.80]; P interaction = 0.003).",
    ("covid.kb.json", "src_lytras_et_al_exploring_the_natural_origins_o_2022", "position"):
        "Coupled with the geographic ranges of their hosts and the sampling locations, across southern China, and into Southeast Asia, we confirm that horseshoe bats, Rhinolophus , are the likely reservoir species for the SARS-CoV-2 progenitor.",
    ("covid.kb.json", "src_bloom_recovery_of_deleted_deep_sequencing_da_2021", "position"):
        "Phylogenetic analysis of these sequences in the context of carefully annotated existing data further supports the idea that the Huanan Seafood Market sequences are not fully representative of the viruses in Wuhan early in the epidemic.",
}


# These exact claims were not present in the cited fetched source.  Factor entries are removed;
# position/edge quote fields are removed while the independently auditable classification remains.
DROP = {
    ("177f5ec738c9.kb.json", "src_technical_report_on_the_review_of_the_violen_2015", "position"),
    ("177f5ec738c9.kb.json", "src_much_ado_about_something_violent_video_game__2010", "position"),
    ("177f5ec738c9.kb.json", "src_violent_video_game_effects_on_aggression_emp_2010", "factor:f_researcher_expectancy_effects"),
    ("51fb332b4e96.kb.json", "src_alcohol_consumption_and_cardiovascular_healt_2022", "factor:f_cardiovascular_disease_subtype_heterogeneity"),
    ("51fb332b4e96.kb.json", "src_alcohol_consumption_and_cardiovascular_healt_2022", "factor:f_blood_pressure_as_mediator"),
    ("blackholes.kb.json", "src_blaizot_et_al_study_of_potentially_dangerous_2003", "position"),
    ("blackholes.kb.json", "src_plaga_on_the_potential_catastrophic_risk_fro_2008", "factor:f_whether_hawking_radiation_is_guaranteed_blac"),
    ("blackholes.kb.json", "src_johnson_the_black_hole_case_the_injunction_a_2009", "factor:f_independence_of_the_safety_review_from_the_i"),
    ("covid.kb.json", "src_rootclaim_saar_wilf_bayesian_analysis_of_cov_2024", "factor:f_ascertainment_reporting_bias_in_early_wuhan_"),
    ("covid.kb.json", "src_emergence_of_the_spike_furin_cleavage_site_i_2022", "factor:f_furin_cleavage_site_as_evidence_of_laborator"),
    ("covid.kb.json", "src_quay_bayesian_analysis_of_sars_cov_2_origin__2021", "factor:f_reliability_of_bayesian_priors_and_likelihoo"),
    ("eggs.kb.json", "src_fuller_et_al_diabegg_high_vs_low_egg_diet_in_2018", "factor:f_discount_for_industry_funding"),
    ("eggs.kb.json", "src_blesso_fernandez_whole_egg_consumption_impro_2013", "factor:f_discount_for_industry_funding"),
    ("eggs.kb.json", "src_alexander_et_al_meta_analysis_of_egg_consump_2016", "factor:f_discount_for_industry_funding"),
    ("eggs.kb.json", "src_tran_et_al_egg_consumption_and_cardiovascula_2014", "factor:f_discount_for_industry_funding"),
    ("51fb332b4e96.kb.json", "src_association_of_alcohol_consumption_with_sele_2011", "factor:f_observational_study_bias_overestimation_conc"),
    ("51fb332b4e96.kb.json", "src_alcohol_intake_and_risk_of_hypertension_a_sy_2024", "factor:f_observational_study_bias_overestimation_conc"),
    ("51fb332b4e96.kb.json", "src_association_of_alcohol_consumption_with_sele_2011", "factor:f_cardiovascular_disease_subtype_heterogeneity"),
    ("covid.kb.json", "src_us_odni_updated_assessment_on_covid_19_origi_2023", "position"),
    ("covid.kb.json", "src_us_odni_updated_assessment_on_covid_19_origi_2023", "factor:f_prior_probability_of_a_research_related_acci"),
    ("51fb332b4e96.kb.json", "src_urinary_tartaric_acid_as_a_biomarker_of_wine_2024", "factor:f_observational_study_bias_overestimation_conc"),
    ("51fb332b4e96.kb.json", "src_urinary_tartaric_acid_as_a_biomarker_of_wine_2024", "factor:f_cardiovascular_disease_subtype_heterogeneity"),
    ("51fb332b4e96.kb.json", "src_effect_of_alcohol_consumption_on_biological__2011", "factor:f_observational_study_bias_overestimation_conc"),
}

SOURCE_UPDATES = {
    ("blackholes.kb.json", "src_blaizot_et_al_study_of_potentially_dangerous_2003"): {
        "url": "https://cds.cern.ch/record/613175/files",
    },
    ("covid.kb.json", "src_worobey_et_al_the_huanan_market_was_the_earl_2022"): {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9348750/",
    },
    ("covid.kb.json", "src_garry_sars_cov_2_furin_cleavage_site_was_not_2022"): {
        "url": "https://pdfs.semanticscholar.org/bf02/ddc9442b96c045c4359635f7ce77fd6b130b.pdf",
    },
    ("covid.kb.json", "src_analysis_of_the_defuse_proposal_ecohealth_wi_2023"): {
        "title": "US Right to Know — analysis of DEFUSE proposal drafts",
        "url": "https://usrtk.org/covid-19-origins/scientists-proposed-making-viruses-with-unique-features-of-sars-cov-2-in-wuhan/",
    },
}


def _clear(provenance):
    provenance.pop("verifiedQuote", None)
    provenance.pop("quoteVerification", None)


def _doc(cache, url):
    path = cache / (hashlib.sha256(url.encode()).hexdigest() + ".json.gz")
    try:
        result = json.load(gzip.open(path, "rt", encoding="utf-8"))
        return result.get("doc") if result.get("ok") else None
    except (OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True, type=pathlib.Path)
    args = parser.parse_args()
    counts = {"replaced": 0, "dropped": 0, "unresolved": 0}
    for path in sorted((ROOT / "cases").glob("*.kb.json")):
        kb = json.loads(path.read_text(encoding="utf-8"))
        source_map = {source["id"]: source for source in kb.get("sources", [])}
        for source_id, source in source_map.items():
            source.update(SOURCE_UPDATES.get((path.name, source_id), {}))
        refs = []
        for source in kb.get("sources", []):
            for field, provenance in (source.get("provenance") or {}).items():
                if isinstance(provenance, dict) and provenance.get("quote"):
                    refs.append((source, field, provenance, None))
            for index, edge in enumerate(source.get("restsOn") or []):
                provenance = edge.get("provenance") if isinstance(edge, dict) else None
                if isinstance(provenance, dict) and provenance.get("quote"):
                    refs.append((source, "edge:" + str(index), provenance, None))
        for factor in kb.get("factors", []):
            for provenance in list(factor.get("provenance") or []):
                source = source_map.get(provenance.get("source"))
                if source and provenance.get("quote"):
                    refs.append((source, "factor:" + factor["id"], provenance, factor))

        for source, field, provenance, factor in refs:
            key = (path.name, source["id"], field)
            if key in DROP:
                if factor is not None:
                    factor["provenance"] = [p for p in factor.get("provenance") or []
                                              if p is not provenance]
                else:
                    provenance.pop("quote", None)
                    _clear(provenance)
                counts["dropped"] += 1
                continue
            if (key in OVERRIDES and
                    _loose_norm(OVERRIDES[key]) not in _loose_norm(provenance.get("quote"))):
                provenance["quote"] = OVERRIDES[key]
                _clear(provenance)
                counts["replaced"] += 1
                continue
            if is_verified_exact(provenance):
                continue
            replacement = OVERRIDES.get(key)
            if replacement is None:
                doc = _doc(args.cache, source.get("url", ""))
                candidates = [] if not doc else [
                    (_score(provenance["quote"], sentence), sentence)
                    for sentence in _segments(doc.get("text", ""))
                    if 7 <= len(sentence.split()) and len(sentence) < 1500
                ]
                if candidates:
                    score, replacement = max(candidates, key=lambda item: item[0])
                    if score < 0.42:
                        replacement = None
            if replacement:
                provenance["quote"] = replacement
                _clear(provenance)
                counts["replaced"] += 1
            else:
                # No defensible sentence: remove the unsupported excerpt/claim instead of leaving
                # prose that looks like source language.
                if factor is not None:
                    factor["provenance"] = [p for p in factor.get("provenance") or []
                                              if p is not provenance]
                else:
                    provenance.pop("quote", None)
                    _clear(provenance)
                counts["dropped"] += 1

        path.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
