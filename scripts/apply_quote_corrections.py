#!/usr/bin/env python3
"""Apply human-reviewed source/position corrections discovered during the quote audit.

The script never writes verification flags. Run ``scripts/audit_quotes.py`` afterwards so only
wording actually found in fetched text can regain an exact checkmark.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / "cases" / name
    return path, json.loads(path.read_text(encoding="utf-8"))


def save(path, kb):
    path.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def remove_source(kb, source_id, reason):
    source = next((s for s in kb.get("sources", []) if s.get("id") == source_id), None)
    if not source:
        return
    kb["sources"] = [s for s in kb["sources"] if s.get("id") != source_id]
    for other in kb["sources"]:
        other["restsOn"] = [edge for edge in other.get("restsOn") or []
                            if str(edge.get("ref") if isinstance(edge, dict) else edge).lower()
                            != ("src:" + source_id).lower()]
    for factor in kb.get("factors", []):
        factor["provenance"] = [p for p in factor.get("provenance") or []
                                if p.get("source") != source_id]
    kb.setdefault("refused", []).append({"title": source.get("title"), "url": source.get("url"),
                                          "reason": reason, "sourceId": source_id})


def repair_dataset_references(kb):
    source_ids = {s.get("id") for s in kb.get("sources", [])}
    users = {}
    for item in kb.get("sources", []):
        for edge in item.get("restsOn") or []:
            ref = edge.get("ref") if isinstance(edge, dict) else edge
            if ref and not str(ref).lower().startswith("src:"):
                users.setdefault(ref, []).append(item.get("id"))
    kb["datasets"] = [dataset for dataset in kb.get("datasets", []) if dataset.get("id") in users]
    for dataset in kb["datasets"]:
        confirmation = dataset.get("confirmation")
        if isinstance(confirmation, dict) and confirmation.get("source") not in source_ids:
            confirmation["source"] = users[dataset["id"]][0]


def source(kb, source_id):
    return next(s for s in kb["sources"] if s.get("id") == source_id)


def clear_quote_trust(provenance):
    if isinstance(provenance, dict):
        provenance.pop("verifiedQuote", None)
        provenance.pop("quoteVerification", None)


def set_position_quotes(kb, replacements):
    for source_id, quote in replacements.items():
        matches = [s for s in kb.get("sources", []) if s.get("id") == source_id]
        if not matches:
            continue
        provenance = matches[0].setdefault("provenance", {}).setdefault("position", {})
        provenance["quote"] = quote
        clear_quote_trust(provenance)


def apply_eggs():
    path, kb = load("eggs.kb.json")
    for position in kb["positions"]:
        if position["id"] == "pos_no_association":
            position["label"] = "No increased risk / possibly lower risk"
            position["shortLabel"] = "No increased risk"
    remove_source(kb, "src_barnard_et_al_industry_funding_and_cholester_2020",
                  "Funding-bias review does not itself estimate whether eggs change CVD risk; retained findings belong in methodological discussion, not a position tally.")
    tran = source(kb, "src_tran_et_al_egg_consumption_and_cardiovascula_2014")
    tran["url"] = "https://pubmed.ncbi.nlm.nih.gov/24711708/"
    tran["position"] = "pos_context_dependent_depends_on_the_person"
    tran["provenance"]["position"]["quote"] = (
        "Four of the six studies that investigated CVD in diabetic patients found a statistically significant association between egg consumption and CVD.")
    clear_quote_trust(tran["provenance"]["position"])
    djousse = source(kb, "src_djouss_gaziano_egg_consumption_and_risk_of_h_2008")
    djousse["url"] = "https://doi.org/10.1161/CIRCULATIONAHA.107.734210"
    egg_urls = {
        "src_zhong_et_al_associations_of_dietary_choleste_2019": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6439941/",
        "src_dehghan_et_al_egg_consumption_and_cvd_mortal_2020": "https://pubmed.ncbi.nlm.nih.gov/31965140/",
        "src_hu_et_al_a_prospective_study_of_egg_consumpt_1999": "https://doi.org/10.1001/jama.281.15.1387",
        "src_fuller_et_al_diabegg_high_vs_low_egg_diet_in_2018": "https://pubmed.ncbi.nlm.nih.gov/29741558/",
        "src_virtanen_et_al_egg_consumption_and_risk_of_c_2016": "https://pubmed.ncbi.nlm.nih.gov/26864369/",
        "src_berger_et_al_dietary_cholesterol_and_cardiov_2015": "https://pubmed.ncbi.nlm.nih.gov/26109578/",
        "src_shin_et_al_egg_consumption_in_relation_to_ca_2013": "https://pmc.ncbi.nlm.nih.gov/articles/PMC3683816/",
        "src_larsson_et_al_egg_consumption_and_risk_of_he_2015": "https://ajcn.nutrition.org/article/S0002-9165(23)13738-5/fulltext",
    }
    for sid, url in egg_urls.items():
        source(kb, sid)["url"] = url
    set_position_quotes(kb, {
        "src_zhong_et_al_associations_of_dietary_choleste_2019": "Among US adults, higher consumption of dietary cholesterol or eggs was significantly associated with higher risk of incident CVD and all-cause mortality in a dose-response manner.",
        "src_zhuang_et_al_egg_cholesterol_consumption_and_2021": "In this study, intakes of eggs and cholesterol were associated with higher all-cause, CVD, and cancer mortality.",
        "src_drouin_chartier_et_al_egg_consumption_and_ri_2020": "The results from our cohort study and updated meta-analysis show that moderate egg consumption (up to one egg per day) is not associated with cardiovascular disease risk overall.",
        "src_dehghan_et_al_egg_consumption_and_cvd_mortal_2020": "In 3 large international prospective studies including ∼177,000 individuals, 12,701 deaths, and 13,658 CVD events from 50 countries in 6 continents, we did not find significant associations between egg intake and blood lipids, mortality, or major CVD events.",
        "src_qin_et_al_egg_consumption_and_cardiovascular_2018": "Compared with non-consumers, daily egg consumption was associated with lower risk of CVD (HR 0.89, 95% CI 0.87 to 0.92).",
        "src_hu_et_al_a_prospective_study_of_egg_consumpt_1999": "These findings suggest that consumption of up to 1 egg per day is unlikely to have substantial overall impact on the risk of CHD or stroke among healthy men and women.",
        "src_rong_et_al_egg_consumption_and_risk_of_chd_a_2013": "Higher consumption of eggs (up to one egg per day) is not associated with increased risk of coronary heart disease or stroke.",
        "src_fuller_et_al_diabegg_high_vs_low_egg_diet_in_2018": "People with prediabetes or T2D who consumed a 3-mo high-egg weight-loss diet with a 6-mo follow-up exhibited no adverse changes in cardiometabolic markers compared with those who consumed a low-egg weight-loss diet.",
        "src_blesso_fernandez_whole_egg_consumption_impro_2013": "Incorporating daily whole egg intake into a moderately carbohydrate-restricted diet provides further improvements in the atherogenic lipoprotein profile and in insulin resistance in individuals with MetS.",
        "src_carson_et_al_dietary_cholesterol_and_cardiov_2020": "Dietary guidance should focus on healthy dietary patterns (eg, Mediterranean-style and DASH [Dietary Approaches to Stop Hypertension]-style diets) that are inherently relatively low in cholesterol with typical levels similar to the current US intake.",
        "src_djouss_gaziano_egg_consumption_and_risk_of_h_2008": "Egg consumption of ≥1 per day is related to an increased risk of HF among US male physicians.",
        "src_spence_jenkins_davignon_egg_yolk_consumption_2010": "Our findings suggest that regular consumption of egg yolk should be avoided by persons at risk of cardiovascular disease.",
        "src_alexander_et_al_meta_analysis_of_egg_consump_2016": "Based on the results of this meta-analysis, consumption of up to one egg daily may contribute to a decreased risk of total stroke, and daily egg intake does not appear to be associated with risk of CHD.",
        "src_virtanen_et_al_egg_consumption_and_risk_of_c_2016": "Egg or cholesterol intakes were not associated with increased CAD risk, even in ApoE4 carriers (i.e., in highly susceptible individuals).",
        "src_berger_et_al_dietary_cholesterol_and_cardiov_2015": "Dietary cholesterol was not statistically significantly associated with any coronary artery disease, ischemic stroke, or hemorrhagic stroke.",
        "src_shin_et_al_egg_consumption_in_relation_to_ca_2013": "However, egg consumption may be associated with an increased incidence of type 2 diabetes among the general population and CVD comorbidity among diabetic patients.",
        "src_larsson_et_al_egg_consumption_and_risk_of_he_2015": "Consumption of eggs ≥1 time/d, but not less frequent consumption, was associated with an elevated risk of HF in men.",
        "src_godos_et_al_egg_consumption_and_cardiovascul_2021": "There is no conclusive evidence on the role of egg in CVD risk, despite the fact that higher quality studies are warranted to obtain stronger evidence for a possible protection of CVD associated with moderate weekly egg consumption compared to no intake; equally, future studies may strengthen the evidence for increased heart failure risk associated with high regular egg consumption.",
    })
    set_position_quotes(kb, {
        "src_djouss_gaziano_egg_consumption_and_risk_of_h_2008": "However, egg consumption of > or = 1 per day is related to an increased risk of HF among US male physicians.",
        "src_tran_et_al_egg_consumption_and_cardiovascula_2014": "Four of the six studies that examined CVD and mortality and egg consumption among diabetics found a statistically significant association.",
    })
    repair_dataset_references(kb)
    save(path, kb)


def apply_alcohol():
    path, kb = load("51fb332b4e96.kb.json")
    complex_pos = "pos_alcohol_has_complex_bidirectional_immediate_"
    decreases = "pos_moderate_alcohol_decreases_cardiovascular_ri"
    no_reduction = "pos_moderate_alcohol_does_not_reduce_cardiovascu"
    moves = {
        "src_a_burden_of_proof_study_on_alcohol_consumpti_2024": complex_pos,
        "src_alcohol_consumption_and_its_association_with_2024": complex_pos,
        "src_alcohol_consumption_and_cardiovascular_disea_2022": complex_pos,
        "src_cardiovascular_disease_review_of_evidence_on_2025": decreases,
        "src_the_cardioprotective_association_of_average__2012": no_reduction,
        "src_exploring_causal_associations_of_alcohol_wit_2015": complex_pos,
        "src_alcohol_consumption_and_cardiovascular_healt_2022": complex_pos,
    }
    for sid, position in moves.items():
        matches = [s for s in kb["sources"] if s.get("id") == sid]
        if matches:
            matches[0]["position"] = position
            clear_quote_trust((matches[0].get("provenance") or {}).get("position"))
    remove_source(kb, "src_the_moderate_alcohol_and_cardiovascular_heal_2020",
                  "MACH15 is a design paper for a trial terminated before outcomes; it cannot support a cardiovascular-benefit position.")
    set_position_quotes(kb, {
        "src_moderate_alcohol_intake_and_lower_risk_of_co_1999": "Alcohol intake is causally related to lower risk of coronary heart disease through changes in lipids and haemostatic factors.",
        "src_alcohol_and_immediate_risk_of_cardiovascular_2016": "There appears to be a consistent finding of an immediately higher cardiovascular risk following any alcohol consumption but by 24 hours, only heavy alcohol intake conferred continued risk.",
        "src_j_curve_revisited_cardiovascular_benefits_of_2013": "The evidence for a J-shaped relationship between alcohol consumption and cardiovascular outcomes is extensive.",
        "src_alcohol_consumption_and_cardiovascular_disea_2024": "Moderate drinking—defined as one to two drinks per day—has been linked to a lower risk of ischemic heart disease and stroke, indicating some protective effects.",
        "src_association_between_alcohol_and_cardiovascul_2014": "This suggests that reduction of alcohol consumption, even for light to moderate drinkers, is beneficial for cardiovascular health.",
        "src_alcohol_consumption_and_cardiovascular_disea_2020_2": "This study provides evidence of a causal relationship between higher alcohol consumption and increased risk of stroke and peripheral artery disease.",
        "src_alcohol_consumption_in_relation_to_cardiovas_2021": "Six out of the nine studies (67%) that assessed cardiovascular disease as outcome reported null associations.",
        "src_do_moderate_drinkers_have_reduced_mortality__2016": "Meta-analyses adjusting for these factors find that low-volume alcohol consumption has no net mortality benefit compared with lifetime abstention or occasional drinking.",
        "src_moderate_alcohol_use_and_reduced_mortality_r_2007": "Our meta-analytic results indicate that the few studies without this error (i.e., those that did not contaminate the abstainer category with occasional or former drinkers) show abstainers and \"light\" or \"moderate\" drinkers to be at equal risk for all-cause and CHD mortality.",
        "src_a_mendelian_randomization_study_of_alcohol_u_2024": "We replicate prior observational studies that show a U‐shaped association between alcohol consumption and cardiometabolic diseases, but MR findings show no causal association between these traits.",
        "src_moderate_alcohol_use_and_cardiovascular_dise_2013": "Larger studies are needed to confirm the null associations with IHD, CVD and fasting glucose.",
        "src_alcohol_consumption_and_its_association_with_2024": "These studies mostly showed non-significant associations between CHD and genetically predicted alcohol consumption when adjusted to smoking.",
        "src_examining_the_causal_association_between_mod_2024": "Although alcohol drinking is beneficial to a few cardiovascular risk factors, it is detrimental to many others.",
        "src_alcohol_and_cardiovascular_disease_a_critica_2024": "In summary, studies with stronger research designs find no evidence of protective effects of low to moderate alcohol use in relation to CVD incidence or mortality.",
        "src_association_of_habitual_alcohol_intake_with__2022": "Genetic epidemiology suggested that alcohol consumption of all amounts was associated with increased cardiovascular risk, but marked risk differences exist across levels of intake, including those accepted by current national guidelines.",
        "src_alcohol_intake_and_risk_of_hypertension_a_sy_2024": "Overall, our results lend support to a causal association between alcohol consumption and risk of hypertension, especially above an alcohol intake of 12 g/d, and are consistent with recommendations to avoid or limit alcohol intake.",
        "src_alcohol_consumption_and_risks_of_more_than_2_2023": "Among Chinese men, alcohol consumption increased multiple disease risks, highlighting the need to strengthen preventive measures to reduce alcohol intake.",
        "src_reduced_stress_related_neural_network_activi_2023": "AC l/m associates with reduced MACE risk, in part, by lowering activity of a stress-related brain network known for its association with cardiovascular disease.",
        "src_urinary_tartaric_acid_as_a_biomarker_of_wine_2024": "Light-to-moderate wine consumption, measured through an objective biomarker (tartaric acid), was prospectively associated with lower CVD rate in a Mediterranean population at high cardiovascular risk.",
    })
    repair_dataset_references(kb)
    save(path, kb)


def apply_covid_blackholes():
    path, kb = load("covid.kb.json")
    source(kb, "src_latham_wilson_the_mojiang_miners_passage_hyp_2020")["url"] = (
        "https://jonathanlatham.net/a-proposed-origin-for-sars-cov-2-and-the-covid-19-pandemic/")
    source(kb, "src_analysis_of_the_defuse_proposal_ecohealth_wi_2023")["url"] = (
        "https://usrtk.org/wp-content/uploads/2023/01/defuse-proposal.pdf")
    url_updates = {
        "src_holmes_et_al_the_origins_of_sars_cov_2_a_cri_2021": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8373617/",
        "src_who_china_joint_study_on_the_origins_of_sars_2021": "https://www.who.int/docs/default-source/coronaviruse/final-joint-report_origins-studies-6-april-201.pdf?sfvrsn=4f5e5196_1&download=true",
        "src_lytras_et_al_exploring_the_natural_origins_o_2022": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8882382/",
        "src_garry_sars_cov_2_furin_cleavage_site_was_not_2022": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9546612/",
        "src_bloom_recovery_of_deleted_deep_sequencing_da_2021": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8436388/",
        "src_harrison_sachs_a_call_for_an_independent_inq_2022": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9173817/",
        "src_relman_to_stop_the_next_pandemic_we_need_to__2020": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7703598/",
        "src_who_sago_independent_assessment_of_the_origi_2025": "https://cdn.who.int/media/docs/default-source/documents/epp/sago/independent-assessment-of-the-origins-of-sars-cov-2-by-sago.pdf?sfvrsn=b0f90ad4_6&download=true",
    }
    for sid, url in url_updates.items():
        source(kb, sid)["url"] = url
    source(kb, "src_liu_gao_et_al_surveillance_of_sars_cov_2_at__2023")["position"] = "pos_undetermined_unresolved"
    remove_source(kb, "src_courtier_orgogozo_de_ribera_sars_cov_2_infec_2022",
                  "The HAL identifier/title could not be resolved to a stable manuscript, so its claim cannot be checked.")
    set_position_quotes(kb, {
        "src_worobey_et_al_the_huanan_market_was_the_earl_2022": "Although there is insufficient evidence to define upstream events, and exact circumstances remain obscure, our analyses indicate that the emergence of SARS-CoV-2 occurred through the live wildlife trade in China and show that the Huanan market was the epicenter of the COVID-19 pandemic.",
        "src_andersen_rambaut_lipkin_holmes_garry_the_pro_2020": "However, since we observed all notable SARS-CoV-2 features, including the optimized RBD and polybasic cleavage site, in related coronaviruses in nature, we do not believe that any type of laboratory-based scenario is plausible.",
        "src_crits_christoph_et_al_genetic_tracing_of_mar_2024": "We demonstrate that market-linked severe acute respiratory syndrome coronavirus 2 (SARS-CoV-2) genetic diversity is consistent with market emergence and find increased SARS-CoV-2 positivity near and within a wildlife stall.",
        "src_emergence_of_the_spike_furin_cleavage_site_i_2022": "We review what is known about the SARS-CoV-2 FCS in the context of its pathogenesis, origin, and how future wildlife coronavirus sampling may alter the interpretation of existing data.",
        "src_segreto_deigin_the_genetic_structure_of_sars_2021": "Both cleavage site and specific RBD could result from site-directed mutagenesis, a procedure that does not leave a trace.",
        "src_rootclaim_saar_wilf_bayesian_analysis_of_cov_2024": "Without resorting to sore losing and given the importance of this issue, regardless of the debate, we would like to explain why we still believe the lab leak hypothesis is the most likely explanation for the origin of COVID-19 and, as our new and updated analysis shows, its likelihood only increased following the deeper analysis we did for the debate.",
        "src_weissman_an_inconvenient_probability_bayesia_2024": "Despite prior probabilities favoring zoonosis we have seen that after evidence-based updating the odds strongly favor a lab leak origin.",
        "src_peter_miller_the_case_for_zoonosis_covid_ori_2024": "The primary basis for my decision was the relative epidemiological proximity of the earliest indicators of covid to a plausible animal source, rather than a potential laboratory source.",
        "src_us_odni_updated_assessment_on_covid_19_origi_2023": "After examining all available intelligence reporting and other information, though, the IC remains divided on the most likely origin of COVID-19.",
        "src_wade_the_origin_of_covid_did_people_or_natur_2021": "But it seems to me that proponents of lab escape can explain all the available facts about SARS2 considerably more easily than can those who favor natural emergence.",
        "src_response_to_segreto_deigin_there_is_still_no_2021": "We also explain why existing genetic data, viral diversity and past human history suggest that a natural origin of the virus is the most likely scenario.",
        "src_scott_alexander_i_watched_15_hours_of_covid__2024": "Both judges decided in favor of Peter.",
        "src_zhou_et_al_a_pneumonia_outbreak_associated_w_2020": "Furthermore, we show that 2019-nCoV is 96% identical at the whole-genome level to a bat coronavirus.",
        "src_temmam_et_al_bat_coronaviruses_related_to_sa_2022": "Our findings therefore indicate that bat-borne SARS-CoV-2-like viruses that are potentially infectious for humans circulate in Rhinolophus spp. in the Indochinese peninsula.",
        "src_boni_et_al_evolutionary_origins_of_the_sars__2020": "SARS-CoV-2 itself is not a recombinant of any sarbecoviruses detected to date, and its receptor-binding motif, important for specificity to human ACE2 receptors, appears to be an ancestral trait shared with bat viruses and not one acquired recently via recombination.",
        "src_quay_bayesian_analysis_of_sars_cov_2_origin__2021": "A Bayesian analysis concludes beyond a reasonable doubt that SARS-CoV-2 is not a natural zoonosis but instead is laboratory derived.",
        "src_holmes_et_al_the_origins_of_sars_cov_2_a_cri_2021": "There is currently no evidence that SARS-CoV-2 has a laboratory origin.",
        "src_lytras_et_al_exploring_the_natural_origins_o_2022": "Coupled with the geographic ranges of their hosts and the sampling locations, across southern China, and into Southeast Asia, we confirm that horseshoe bats, Rhinolophus , are the likely reservoir species for the SARS-CoV-2 progenitor.",
        "src_garry_sars_cov_2_furin_cleavage_site_was_not_2022": "We also noted, correctly, that placing the insertion out of frame would be \"an unusual and needlessly complex feat of genetic engineering.\"",
        "src_liu_gao_et_al_surveillance_of_sars_cov_2_at__2023": "Using quantitative real-time polymerase chain reaction (RT-qPCR) and high-throughput sequencing (Bowtie2 analysis), SARS-CoV-2 was detected in 74 (70 RT-qPCR and 4 Bowtie2) environmental samples, but none of the animal samples.",
        "src_bloom_recovery_of_deleted_deep_sequencing_da_2021": "First, they provide further evidence that the Huanan Seafood Market sequences that were the focus of the joint WHO-China report ( WHO 2021 ) are not representative of all SARS-CoV-2 in Wuhan early in the epidemic.",
        "src_harrison_sachs_a_call_for_an_independent_inq_2022": "The investigation into the origin of the virus has been made difficult by the lack of key evidence from the earliest days of the outbreak-there's no doubt that greater transparency on the part of Chinese authorities would be enormously helpful.",
        "src_relman_to_stop_the_next_pandemic_we_need_to__2020": "Even though a definitive answer may not be forthcoming, and even though an objective analysis requires addressing some uncomfortable possibilities, it is crucial that we pursue this question.",
        "src_latham_wilson_the_mojiang_miners_passage_hyp_2020": "The origin of SARS-CoV-2 that we propose below is based on the case histories of these miners and their hospital treatment.",
        "src_who_sago_independent_assessment_of_the_origi_2025": "Much of the information needed to assess hypothesis #2, of an accidental laboratory related event, either during field investigations or a breach in laboratory biosafety or biosecurity , has not been made available to WHO or SAGO.",
    })
    repair_dataset_references(kb)
    save(path, kb)

    path, kb = load("blackholes.kb.json")
    source(kb, "src_cavagli_particle_accelerators_as_black_hole__2010")["url"] = (
        "https://www.einstein-online.info/en/spotlight/accelerators_bh/")
    cern = source(kb, "src_cern_the_safety_of_the_lhc_public_statement_2008")
    cern["url"] = "https://home.cern/cern-reiterates-safety-of-lhc-on-eve-of-first-beam/"
    cern["provenance"]["position"]["quote"] = (
        "A report published today in the peer reviewed Journal of Physics G: Nuclear and Particle Physics provides comprehensive evidence that safety fears about the Large Hadron Collider (LHC) are unfounded.")
    clear_quote_trust(cern["provenance"]["position"])
    blackhole_urls = {
        "src_lhc_safety_assessment_group_lsag_review_of_t_2008": "https://arxiv.org/pdf/0806.3414",
        "src_calogero_might_a_laboratory_experiment_destr_2000": "https://doi.org/10.1179/030801800679224",
        "src_blaizot_et_al_study_of_potentially_dangerous_2003": "https://cds.cern.ch/record/613175/files/CERN-2003-001.pdf",
    }
    for sid, url in blackhole_urls.items():
        source(kb, sid)["url"] = url
    remove_source(kb, "src_jaffe_busza_sandweiss_wilczek_review_of_spec_2000",
                  "RHIC strangelet analysis, not evidence about LHC-created black holes.")
    remove_source(kb, "src_dar_de_r_jula_heinz_will_relativistic_heavy__1999",
                  "RHIC strangelet analysis, not evidence about LHC-created black holes.")
    remove_source(kb, "src_dimopoulos_landsberg_black_holes_at_the_larg_2001",
                  "Collider-production/detection paper with no safety conclusion; Hawking evaporation is already represented by its direct theoretical source.")
    set_position_quotes(kb, {
        "src_giddings_mangano_astrophysical_implications__2008": "In short, this study finds no basis for concerns that TeV-scale black holes from the LHC could pose a risk to Earth on time scales shorter than the Earth's natural lifetime.",
        "src_ellis_giudice_mangano_tkachev_wiedemann_revi_2008": "The stability of astronomical bodies constrains strongly the possible rate of accretion by any such microscopic black holes, so that they present no conceivable danger.",
        "src_hawking_particle_creation_by_black_holes_1975": "This thermal emission leads to a slow decrease in the mass of the black hole and to its eventual disappearance: any primordial black hole of mass less than about 10 15 g would have evaporated by now.",
        "src_koch_bleicher_st_cker_exclusion_of_black_hol_2009": "In this paper we summarize the most straight forward arguments that are necessary to rule out such doomsday scenarios.",
        "src_ord_hillerbrand_sandberg_probing_the_improba_2010": "Using the risk estimates from the Large Hadron Collider as a test case, we show how serious the problem can be when it comes to catastrophic risks and how best to address it.",
        "src_johnson_the_black_hole_case_the_injunction_a_2009": "Next, the article explores the daunting challenges the case presents to equity, evidence, and law-and-economics analysis.",
        "src_hut_rees_how_stable_is_our_vacuum_cosmic_ray_1983": "We show here that this chance, fortunately, is completely negligible since the region inside our past light cone has already survived some 10 5 cosmic ray collisions at centre of mass energies of 10 11 GeV and higher.",
        "src_tegmark_bostrom_is_a_doomsday_catastrophe_li_2005": "Here we derive a new upper bound of one per billion years (99.9% confidence level) for the exogenous terminal-catastrophe rate that is free of such selection bias, using calculations based on the relatively late formation time of Earth.",
        "src_casadio_fabi_harms_on_the_catastrophic_black_2010": "Based on this analysis, we argue against the possibility of catastrophic black hole growth at the LHC.",
        "src_giddings_mangano_comments_on_claimed_risk_fr_2008": "We comment on inconsistency of this proposed scenario.",
        "src_kent_a_critical_look_at_risk_assessments_for_2004": "Future policy on catastrophe risks would be more rational, and more deserving of public trust, if acceptable risk bounds were generally agreed upon ahead of time and if serious research on whether those bounds could indeed be guaranteed was carried out well in advance of any hypothetically risky experiment, with the relevant debates involving experts with no stake in the experiments under consideration.",
    })
    repair_dataset_references(kb)
    save(path, kb)


def apply_video():
    path, kb = load("177f5ec738c9.kb.json")
    source(kb, "src_restoring_the_spirit_of_fair_play_in_the_deb_2013")["position"] = "pos_increases_aggression"
    remove_source(kb, "src_violent_video_games_and_real_world_violence__2014",
                  "The study tests violent-crime trends, not the case question's aggression outcome; its text concedes a possible link with minor aggression.")
    remove_source(kb, "src_longitudinal_effects_of_media_violence_on_ag_2010",
                  "Combined film, television, and game exposure cannot isolate the video-game exposure asked by this case.")
    remove_source(kb, "src_the_public_health_risks_of_media_violence_a__2009",
                  "Mixed-media meta-analysis does not provide a game-specific estimate for this case.")
    remove_source(kb, "src_selling_violent_video_game_solutions_a_look__2017",
                  "Institutional-policy history and court treatment, not evidence of a causal aggression effect.")
    remove_source(kb, "src_possible_biases_of_researchers_attitudes_tow_2016",
                  "Bibliometric researcher-attitudes study with no aggression outcome; belongs in methodological context rather than an effect position.")

    position_quotes = {
        "src_nailing_the_coffin_shut_on_doubts_that_viole_2010":
            "The meta-analysis by Anderson et al. (2010) is the best yet in proving beyond a reasonable doubt that exposure to video game violence increases the risk that the observer will behave more aggressively and violently in the future.",
        "src_technical_report_on_the_review_of_the_violen_2015":
            "The research demonstrates a consistent relation between violent video game use and increases in aggressive behavior, aggressive cognitions, and aggressive affect and decreases in prosocial behavior, empathy, and sensitivity to aggression.",
        "src_does_playing_violent_video_games_cause_aggre_2019":
            "Since at least ten significant effects would be expected purely by chance, we conclude that there were no detrimental effects of violent video gameplay.",
        "src_the_contagious_impact_of_playing_violent_vid_2019":
            "Mediation analyses showed that friends’ aggression at Time 1 accounted for the impact of friends’ amount of violent video game play at Time 1 on the participant's aggression at Time 2.",
        "src_violent_video_games_and_aggression_2008":
            "Although males were more aggressive than females, neither randomized exposure to violent-video-game conditions nor previous real-life exposure to violent video games caused any differences in aggression.",
        "src_metaanalysis_of_the_relationship_between_vio_2018":
            "On the basis of this metaanalysis, we conclude that playing violent video games is associated with greater levels of overt physical aggression over time, after accounting for prior aggression.",
        "src_evidence_for_publication_bias_in_video_game__2007":
            "Publication bias issues emerge for both experimental and non-experimental studies of aggressive behaviors.",
        "src_lacko_machackova_smahel_does_violence_in_vid_2024":
            "All desensitization effects were statistically insignificant.",
    }
    for sid, quote in position_quotes.items():
        matches = [s for s in kb["sources"] if s.get("id") == sid]
        if matches:
            provenance = matches[0].setdefault("provenance", {}).setdefault("position", {})
            provenance["quote"] = quote
            clear_quote_trust(provenance)

    # Use the exact PMC transcription for Huesmann and fetch the Prescott conclusion from the
    # article body rather than an abstract-only publisher record.
    set_position_quotes(kb, {"src_nailing_the_coffin_shut_on_doubts_that_viole_2010":
        "The current meta-analysis by Anderson and his colleagues is the best yet in proving beyond a reasonable doubt that exposure to video game violence increases the risk that the observer will behave more aggressively and violently in the future."})
    source(kb, "src_metaanalysis_of_the_relationship_between_vio_2018")["url"] = (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC6176643/")

    przybylski = source(kb, "src_violent_video_game_engagement_is_not_associa_2019")
    if przybylski.get("restsOn") and isinstance(przybylski["restsOn"][0], dict):
        provenance = przybylski["restsOn"][0].setdefault("provenance", {})
        provenance["quote"] = ("A large sample of British adolescent participants (n = 1004) aged 14 and 15 years and an equal number of their carers were interviewed.")
        clear_quote_trust(provenance)
    apa = source(kb, "src_technical_report_on_the_review_of_the_violen_2015")
    if apa.get("restsOn") and isinstance(apa["restsOn"][0], dict):
        apa["restsOn"][0]["provenance"]["quote"] = (
            "All four meta-analyses reported an adverse effect of violent video game use on aggressive outcomes, with an effect size greater than zero and a narrow range of unadjusted effect sizes (.14–.29).")
        clear_quote_trust(apa["restsOn"][0]["provenance"])
    # Remove two chronologically impossible review->future-review dependencies.
    for sid in ("src_effects_of_violent_video_games_on_aggressive_2001",
                "src_evidence_for_publication_bias_in_video_game__2007"):
        item = source(kb, sid)
        item["restsOn"] = [edge for edge in item.get("restsOn") or []
                           if not str(edge.get("ref") if isinstance(edge, dict) else edge).lower().startswith("src:")]
    # Elson/Ferguson (2013) is the analysis to which the two commentaries respond, not vice versa.
    core_id = "src_twenty_five_years_of_research_on_violence_in_2013"
    core = source(kb, core_id)
    core["restsOn"] = [edge for edge in core.get("restsOn") or []
                       if str(edge.get("ref") if isinstance(edge, dict) else edge).lower() not in {
                           "src:src_restoring_the_spirit_of_fair_play_in_the_deb_2013",
                           "src:src_apples_oranges_and_the_burden_of_proof_putti_2013"}]
    for sid in ("src_restoring_the_spirit_of_fair_play_in_the_deb_2013",
                "src_apples_oranges_and_the_burden_of_proof_putti_2013"):
        item = source(kb, sid)
        ref = "src:" + core_id
        if ref not in [e.get("ref") if isinstance(e, dict) else e for e in item.get("restsOn") or []]:
            item.setdefault("restsOn", []).append(ref)
    repair_dataset_references(kb)
    save(path, kb)


if __name__ == "__main__":
    apply_eggs()
    apply_alcohol()
    apply_covid_blackholes()
    apply_video()
    print("Applied reviewed source, URL, position, and dependency corrections.")
