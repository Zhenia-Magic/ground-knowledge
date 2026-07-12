# Blinded reader study — preregistration-ready protocol

## Automated web variant (fast pilot)

A self-serve, auto-scored version runs in the portal so you can **just share one link**:

- **Participants open** `https://groundknowledge.org/study` — anonymous (a random token, never a name).
- **Assignment:** each participant is given **ONE ~10-minute case** and one condition (a
  between-subjects design), assigned automatically (`eval/reader_study/study.assign`, driven by the
  submission count). The 3 cases × 2 conditions form 6 cells that rotate evenly, so cases and
  conditions stay balanced. This keeps the ask short and spreads recruitment; the rigorous
  WITHIN-participant crossover (`randomize.assignments`) is the manual follow-up below.
- **Blinded:** participants see only their materials (the deep-research report; and, in the `DR+GK`
  condition, the Ground Knowledge evidence map) — never the condition label.
- **Objective items auto-score instantly** (`eval/reader_study/gold_questions.json`): the flood trap,
  an "independent evidence bases" estimate, and a crux multiple-choice. Free-text answers are captured
  for optional later human scoring, never auto-scored.
- **Results:** `https://groundknowledge.org/study/results` shows DR vs DR+GK mean objective score and
  per-item accuracy. This is a **between-observations** read — an honest fast signal; the paired,
  human-scored analysis below is the rigorous follow-up. Report it as **exploratory** below the 24
  minimum.

The manual, fully human-scored protocol follows.

## Question

Does adding Ground Knowledge's structured evidence-root audit to a strong deep-research report help
a thoughtful reader reason better than the deep-research report alone?

This is the missing evaluation for the rubric's **epistemic uplift** criterion. It tests incremental
reader benefit, not writing style or whether one system happened to retrieve a better paper.

## Design

- **Participants:** target 36; minimum 24 after exclusions. Recruit analytically experienced readers
  who were not involved in building the cases. Record domain familiarity before exposure.
- **Cases:** COVID origins, LHC black-hole safety, eggs and cardiovascular risk.
- **Conditions:**
  - `DR`: the captured Claude Code / Opus 4.8 deep-research report.
  - `DR+GK`: the same report plus the corresponding Ground Knowledge viewer/export.
- **Assignment:** within-participant crossover. Each participant sees all three cases, with condition
  and order assigned by the Latin-square generator `randomize.py`. Tool labels are neutralized;
  participants are not told which condition is the submission.
- **Time:** maximum 18 minutes per case. Capture completion time automatically or with a stopwatch.
- **No coaching:** participants receive the task sheet below and may open cited sources, but receive
  no explanation of roots, cruxes, or expected answers beyond the normal product copy.

## Primary outcome

Before inspecting responses, two judges independently score each case using the frozen rubric below.
Disagreements are reconciled without seeing condition labels.

1. **Dependency recognition (0–4):** correctly identifies how many apparently separate sources reuse
   the same underlying dataset/argument; names the principal shared root(s).
2. **Load-bearing evidence (0–4):** identifies the evidence whose failure would most change the answer.
3. **Crux recognition (0–4):** identifies the predeclared gold cruxes and separates active
   disagreement from an unanswered/one-sided assumption.
4. **Calibrated conclusion (0–4):** conclusion preserves material uncertainty and does not infer
   confidence from raw source count.

Primary endpoint: mean of the four scores (0–4), compared within participant between `DR` and
`DR+GK`. Report paired mean difference, bootstrap 95% CI, and every anonymized response.

## Secondary outcomes

- Time to completion.
- Raw-source-count trap: after adding twelve derivative sources, does the participant correctly say
  that independent support is unchanged? (`yes/no` plus explanation.)
- Confidence calibration: confidence (0–100) on four adjudicated factual/dependency questions per
  case; report Brier score where answers are binary and calibration plots descriptively.
- Usability: “I can tell what evidence is doing the work” and “I can inspect why the conclusion
  changed,” each 1–7.
- Error taxonomy: missed dependency, invented dependency, missed minority view, false certainty,
  quality/independence conflation.

## Participant task sheet

For each case:

1. State the main plausible answers and your calibrated current conclusion.
2. Name the three most load-bearing pieces of evidence or argument.
3. Identify any sources that are not independent of one another and explain why.
4. Name the most important crux or unanswered assumption.
5. Suppose twelve additional articles repeat the strongest camp's existing evidence without adding
   new data or argument. Should your confidence change? Why?
6. Rate confidence in your conclusion from 0–100.

## Frozen analysis rules

- Exclude only participants who leave two or more cases blank or report having built/reviewed this
  repository. Report exclusions and reasons.
- Do not change the gold or scoring rubric after condition labels are revealed.
- Primary analysis is paired and intention-to-treat for every completed case.
- Report results even if null or negative; attach de-identified raw data and the scoring sheet.
- Treat this as a small exploratory study unless the minimum sample is reached.

## Files to publish with results

- `assignments.csv` generated before recruitment.
- Completed `responses.csv` using `responses-template.csv`.
- Frozen case materials and their SHA-256 hashes.
- Two blinded scorer files, reconciliation notes, analysis notebook/script, and all exclusions.

