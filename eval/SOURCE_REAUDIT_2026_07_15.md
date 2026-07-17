# Case source re-audit — 2026-07-15

## Scope and method

All five live case files were reviewed for source identity, relevance to the stated question,
position fit, publication metadata, dependency/root identity, and whether the stored excerpt states
the source's actual finding rather than background or methods. The search was refreshed through
2026-07-15 using primary publication pages, scholarly catalogues, and relevant official reports.

Every new or changed excerpt was re-fetched from its primary source and passed the deterministic
`verbatim-sentence-v2` verifier. Unchanged excerpts retain their earlier checked-text hashes; the
audit date is not a claim that every unchanged URL was downloaded again on this date.

## Changes made

### Alcohol and cardiovascular disease

- Added Carr et al. (2026), a current synthesis of 56 cohort meta-analyses and 20 Mendelian-
  randomisation studies. It is filed under the mixed/outcome-dependent position because it reports
  J-shaped associations for IHD and ischaemic stroke, mostly monotonic harm for other outcomes, and
  largely null or harmful MR results. [Primary record](https://pubmed.ncbi.nlm.nih.gov/42129601/)
- Renamed the middle position to **Mixed / outcome- and pattern-dependent cardiovascular effects**;
  the prior label was restricted to immediate effects although the sources also cover chronic and
  endpoint-specific findings.
- Moved the 2025 AHA scientific statement and the 2012 Roerecke meta-analysis into the mixed
  position. Their own conclusions are conditional or heterogeneous, not categorically protective
  or categorically no-benefit.
- Replaced four exact-but-nonprobative background/method snippets with exact finding sentences:
  incident AF, MunichBREW, the National Academies CVD review, and the longitudinal HDL study.
- Corrected Lee, Kim & Kang's review from 2026 to its catalogue publication year, **2025**, and
  corrected its venue and public/academic funding classification.

### LHC black-hole safety

- Removed a duplicate record for the same 2008 LSAG safety review and repointed every dependency,
  factor claim, and confirmation to the retained journal-version record.
- Added the CMS Collaboration's 2026 Run 2 search using 13 TeV collision data (138 fb⁻¹), which
  excludes modelled semiclassical-black-hole masses below 8.4–11.4 TeV at 95% confidence. This
  directly updates the empirical production-search layer; it constrains a necessary premise but is
  not, by itself, the full astrophysical safety argument. [CMS publication page](https://cms-results.web.cern.ch/cms-results/public-results/publications/EXO-24-028/)
- Classified the new source as a primary collider experiment and admitted its specifically named
  Run 2 evidence base with a curator record.

### SARS-CoV-2 origins

- Renamed the zoonotic position to **Zoonotic spillover**. The previous wording implied that every
  natural-origin source establishes the Huanan market as the first spillover site, which is stronger
  than several sources conclude.
- Added Bloom (2025), which shows bias in the earliest available sequences and concludes that the
  phylogenetic root cannot be resolved confidently with current data. It is filed as unresolved and
  linked to the existing early-sequence evidence base. [Primary article](https://doi.org/10.1093/molbev/msaf118)
- Restored the 2023 ODNI assessment under unresolved: it documents divergent agency conclusions and
  the scientific/intelligence gaps behind them. [Official assessment](https://www.dni.gov/files/ODNI/documents/assessments/Report-on-Potential-Links-Between-the-Wuhan-Institute-of-Virology-and-the-Origins-of-COVID-19-20230623.pdf)
- Added ODNI's June 2026 lab-origin news release as an **institutional statement**, not a scientific
  study and not an independent empirical root. This captures the current official claim without
  giving a press release the evidentiary status of primary research. [Official release](https://www.dni.gov/index.php/newsroom/press-releases/press-releases-2026/4166-pr-11-26)
- Merged duplicate population vocabulary for early viral sequences and for the two U.S. intelligence
  assessments, preventing artificial coverage/blind-spot differences caused only by wording.

### Violent video games and aggression

- Removed *Violent Video Games and Hostile Expectations* (2002) from the position evidence. Its
  experiment measures hostile expectations, aggressive thoughts, and anger—not aggressive
  behaviour—so treating it as direct evidence that exposure increases aggression overstated the
  measured outcome.
- No new source was added: the case already contains the most decision-relevant recent longitudinal
  evidence (2024) and reanalysis (2025), and the newer search results did not improve on that fit.

### Eggs and cardiovascular disease

- No source or position change was needed. The case already includes the 2025 updated umbrella
  review alongside the major cohort, meta-analytic, biomarker, and subgroup evidence. The separate
  industry-funding review remains correctly isolated as a context source rather than outcome
  evidence.

## Final integrity results

| Check | Result |
|---|---:|
| Live sources | 166 |
| Position excerpts exactly verified | 166 / 166 |
| All stored excerpts exactly verified | 319 / 319 |
| Named evidence-base records | 78 |
| Confirmed evidence-base identities | 78 / 78 |
| Unadmitted support links | 0 |
| Schema validations | 5 / 5 passed |
| Automated tests | 312 / 312 passed |
| Adversarial benchmark contracts | 9 / 9 passed in all benchmark cases |

The refreshed machine-readable audit is in `eval/QUOTE_AUDIT.json`; current per-case counts are in
`eval/SOURCE_INVENTORY.md`.
