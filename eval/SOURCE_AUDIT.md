# Source relevance, correctness, and funding audit

Audit date: 2026-07-12  
Curator id recorded in the KB logs: `source-audit-2026-07`

> **Status:** this document is the historical 2026-07-12 audit pass, not the current inventory.
> Subsequent quote-enforcement and case curation changed the artifacts. The live count is generated
> from `cases/*.kb.json` in [`SOURCE_INVENTORY.md`](SOURCE_INVENTORY.md), and CI fails if that file
> drifts. Counts below describe what happened during this audit pass.

## Scope and rule

All 192 sources present at the start of this audit snapshot were read against the exact question, the position
under which they were filed, their quoted finding, and their dependency edges. A source was removed
only when its exposure, outcome, or subject did not answer the case question, when it was a duplicate,
or when the stored excerpt contained no case-specific finding. Method papers were retained when they
directly test a load-bearing bias in the case; their indirect status is called out below.

That audit snapshot resulted in 180 sources: 16 removed, four high-value anchors added, and three sources moved
to the position their actual conclusion supports. Every removal/move is a versioned `remove-source` or
`move-source` log record with the reason and curator id. The reusable operation is implemented in
`engine/curate.py`; it repairs citation edges, dataset confirmations, orphan datasets, and factor weights.

## Case-by-case results

### COVID origins — 28 → 29 sources

- Removed: none. The advocacy pieces and Bayesian reconstructions are intentionally retained because
  the competition case asks why analyses of substantially shared evidence reach incompatible answers;
  their `restsOn` edges prevent them from masquerading as new independent evidence.
- Corrected: Chan & Zhan's furin-cleavage-site paper was falsely glossed as a natural-evolution account.
  The paper says available sequences cannot distinguish natural emergence from experimental insertion,
  so it moved from **Zoonotic** to **Undetermined** and received the actual conclusion.
- Corrected: the Crits-Christoph market-wildlife record now points to the final 2024 *Cell* article
  (DOI `10.1016/j.cell.2024.08.010`) and uses its market-emergence/wildlife-DNA finding, not an
  unrelated SARS-CoV-1 sentence. The truncated Holmes *Cell* URL was also repaired.
- Added: WHO SAGO's 2025 independent assessment. It reviews evidence through June 2025, says the
  weight favors zoonotic spillover, but cannot rule out a laboratory origin because critical data were
  not available. It is therefore filed under **Undetermined / unresolved** and linked to the existing
  market, genomic, WHO-China, ODNI, and inquiry sources rather than counted as a fresh dataset.

### LHC microscopic black holes — 20 → 20 sources

- Removed: Martin Rees's generic precautionary book entry. The record linked to Wikipedia, contained
  no LHC microscopic-black-hole analysis, and had no verifiable case-specific finding.
- Added: Dimopoulos & Landsberg's 2001 *Physical Review Letters* paper, the canonical source for the
  conditional premise that TeV-scale gravity could produce microscopic black holes at the LHC and that
  they would decay promptly through Hawking radiation. It rests on the existing Hawking-evaporation
  base; it does not mint a second copy of that argument.
- Corrected: Kent's risk-assessment paper now points to the published *Risk Analysis* article and uses
  its actual expected-loss/risk-threshold conclusion instead of an arXiv navigation header.
- Retained as indirect but relevant: the RHIC/strangelet papers by Jaffe et al., Dar et al., Blaizot et
  al., and Kent. They do not study microscopic black holes directly, but they develop and challenge the
  cosmic-ray empirical-bound method that the LHC safety argument reuses. The case is explicitly about
  the reliability and dependency structure of that safety argument, so removing them would erase a
  load-bearing methodological dispute.

### Eggs and cardiovascular disease — 20 → 21 sources

- Removed: none after correction. The Barnard funding review is indirect evidence, retained because
  industry influence is an explicit crux; it is labelled Advocacy/Evidence-synthesis, not a clinical
  event study.
- Corrected three materially wrong records:
  - Godos et al. pointed to an unrelated radiotherapy paper and quoted its machine-learning methods.
    It now points to DOI `10.1007/s00394-020-02345-7`, contains the actual dose-response conclusion,
    and reuses the cohort/meta-analysis sources it synthesizes.
  - Spence et al.'s carotid-plaque paper is from 2012, not 2010, and now points to DOI
    `10.1016/j.atherosclerosis.2012.07.032`.
  - Barnard et al. pointed to an unrelated JAHA DOI. It now points to DOI
    `10.1177/1559827619892198` and records the authors' disclosed advocacy conflict.
- Added: Formisano et al.'s 2025 updated umbrella review (DOI
  `10.1016/j.numecd.2025.103849`). It found no high-vs-low association across cardiovascular
  outcomes, while rating the underlying review evidence critically low. It reported no external
  funding and is linked to the reviews/cohorts it synthesizes.

### Moderate alcohol and cardiovascular risk — 79 → 68 sources

Removed 11 records:

1. *Alcohol and Health: Praise of the J Curves* — all-cause mortality commentary, not a CVD endpoint.
2. *Alcohol consumption and mortality in patients with cardiovascular disease* — mortality in people
   with established CVD, not incident cardiovascular risk.
3. *Detrimental Effects of Alcohol on the Heart* — heavy exposure/cardiomyopathy, not moderate intake.
4. Whitehall II trajectories — all-cause mortality in established CVD.
5. Two copies of the GBD high-alcohol-use burden analysis — duplicate and wrong dose range.
6. Korean health-change/cessation study — predictors of cessation, not alcohol's cardiovascular effect.
7. WHO “No level is safe” item — overall-health/cancer trade-off, no CVD-specific moderate-dose result.
8. Alpha Omega post-MI cohort — mortality after infarction, not incident CVD risk.
9. Chronic coronary disease guideline — stored excerpt was only generic search methodology and made no
   alcohol-specific claim.
10. Alcoholic-cardiomyopathy GBD analysis — chronic excessive exposure, outside the question.

Two sources were refiled under **Complex/bidirectional**: the 2026 ACC overview (which says outcome
benefit remains uncertain) and the UK Biobank atrial-fibrillation threshold study (a J-shaped,
endpoint-specific result). The no-benefit position lost the misleading “(MR evidence)” suffix because it
also contains trials, cohorts, reviews, and advisories. Two spellings of the same Fillmore/Stockwell
mortality-bias evidence base and two typo-duplicate bias factors were merged.

Retained as indirect but relevant: all-cause-mortality papers only when their purpose is to test the
“sick quitter”/abstainer-reference bias used to infer cardioprotection. These are methodological checks,
not treated as CVD event datasets.

### Violent video games and aggression — 45 → 42 sources

Removed four records:

1. Duplicate Markey, Markey & French record under a second Semantic Scholar URL.
2. *Violent Video Games and Violent Crime* — outcome is crime rates, not aggressive behavior.
3. Risk-glorifying/racing-games longitudinal study — exposure and outcome are broad behavioral
   deviance, not violent-game exposure and aggression.
4. eLife GTA-V neuroimaging study — outcome is empathy/emotional reactivity, not aggression.

Added Lacko, Machackova & Smahel's 2024 four-wave study of 3,010 Czech adolescents (DOI
`10.1016/j.chb.2024.108341`). It directly measures physical/verbal aggression, separates within-person
from between-person effects, reports no significant desensitization effect, has open data, and records
European Union support. Its newly named panel is admitted through a source-specific verified edge.

Retained as indirect but relevant: APA-task-force critiques, publication-bias analyses, and the
meta-analysis dispute. They bear on the case's two explicit cruxes—effect-size magnitude and
researcher expectancy—and collapse into shared secondary/meta-analytic roots rather than being counted
as independent aggressive-behavior experiments.

## Metadata and funding completion

- At the audit snapshot, author and venue fields were populated for all 180 retained/added sources.
- 97 retained sources received a catalogue/full-text metadata audit record; four additions arrived
  complete. Named funding details are now stored on 37 sources and are visible in the source cards.
- The Berger dietary-cholesterol review is now marked **Industry** because Crossref records USDA plus
  American Egg Board/Egg Nutrition Center support. The PREDIMED wine-biomarker paper is marked
  **Industry** because it names the Spanish wine interprofessional body alongside public grants. The
  alcohol cardiovascular review with Novartis/Gilead support is also conservatively marked Industry.
- 53 sources remain **Undisclosed** (25 alcohol, 25 video-game, two COVID commentary pieces, one legal
  analysis). Crossref/OpenAlex and the accessible publication pages did not provide a named funder;
  these were deliberately left Undisclosed rather than guessed as independent.

## Reproducibility

- `scripts/audit_source_metadata.py` fetches non-mutating OpenAlex/Crossref candidates with title-match
  scores and checkpoint/resume support.
- `scripts/apply_source_metadata.py` applies only high-confidence or explicitly approved matches,
  preserves a metadata audit record, and contains the manually verified corrections above.
- `eval/source_audit_additions/` contains the four hand-auditable source deltas.
- The KB logs contain every removal, move, metadata audit, entity merge, and addition with versions.
