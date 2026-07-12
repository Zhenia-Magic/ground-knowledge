# Benchmark results — Ground Knowledge vs two deep-research baselines

Run `python eval/run_benchmark.py --require-live-baseline` to reproduce. Gold fixtures are in
`eval/gold.json`; independently captured ChatGPT Deep Research and Claude Code / Opus 4.8 reports,
prompts, provenance, and SHA-256 hashes are in `eval/baselines/`.

This is a **developer-authored diagnostic**, not a held-out evaluation or evidence that readers make
better decisions. The small gold is deliberately non-exhaustive; comparative scoring is a transparent
keyword-recall proxy with declared synonyms, and reports recall rather than precision. Hashes establish
capture integrity, not research quality. The value is that wins and losses are executable and visible.

## 1. Structure recall

| Case | Ground Knowledge positions | roots | cruxes |
|---|---:|---:|---:|
| COVID | 3/3 | 4/4 | 3/3 |
| Black holes | 2/2 | 4/4 | 3/3 |
| Eggs | 3/3 | 3/3 | 3/3 |

All expected crux concepts are present in the visible factor matrices. This structure-recall score
does not pretend every concept was promoted to a headline badge: the separate crux taxonomy
(`crossCampCrux`, `sharedPivot`, `oneSidedLoadBearing`, `missingCounterassessment`) remains selective.
For example, the eggs biomarkers and black-hole cosmic-ray concepts are modeled but remain below
the load-bearing promotion threshold; the executable output reports those type counts separately.

## 2. Collapse — the headline claim

Raw source count → confirmed independent bases:

- **COVID:** zoonotic 15 → **5.0**; laboratory-associated 8 → **3.5**; undetermined 5 → **2.0**.
- **Black holes:** no-risk 14 → **4.5**; residual concern 6 → **3.0**. The safe case now models
  production impossibility, Hawking evaporation, accretion timescale, the cosmic-ray/dense-star
  observation, and a half-strength review-only calculation as distinct layers.
- **Eggs:** increases-risk 5 → **5.0**; no-association 9 → **4.0**; context-dependent 6 → **5.0**.

The live baselines independently notice shared cohorts and recycled arguments. Ground Knowledge's
additional product is not that qualitative observation; it is the explicit, recomputable root graph,
quantitative collapse, and update diff.

## 3. Adversarial contract — executed on every case

| Attack | Required result |
|---|---|
| +12 ungrounded echo sources | increase ≤1.0; all twelve pool into one voice |
| +12 fabricated named roots through the unverified path | increase 0.0; roots remain proposed |
| one real dependency quote copied to a fabricated sibling | only the base actually named by the quote enters; sibling stays proposed |
| 12-source ungrounded citation ring | increase 0.0; loop is visible and flagged |
| new source using a known alias | increase 0.0; alias resolves to the existing root |
| generic fetched label (`Cohort`) | increase 0.0; ordinary methods prose cannot identify a root |
| two unknown lexical aliases named by one real sentence | at most one root enters; collision is flagged |

**All seven attacks pass on all three cases.** The benchmark traverses the ordinary merge,
verification, pending-reference, root-resolution, and assessment paths. Novel semantic aliases are
not claimed as automatically solved: lexical checks bound automatic admission, optional embeddings
suggest further candidates, and confirmation blocks a likely duplicate unless a curator records an override.

## 4. Comparative recall

| Case/system | positions | roots | cruxes |
|---|---:|---:|---:|
| COVID — Ground Knowledge | 3/3 | 4/4 | 3/3 |
| COVID — ChatGPT | 3/3 | 4/4 | 3/3 |
| COVID — Claude | 3/3 | 4/4 | 3/3 |
| Black holes — Ground Knowledge | 2/2 | 4/4 | 3/3 |
| Black holes — ChatGPT | 1/2 | 4/4 | 2/3 |
| Black holes — Claude | 2/2 | 4/4 | 3/3 |
| Eggs — Ground Knowledge | 3/3 | 3/3 | 3/3 |
| Eggs — ChatGPT | 3/3 | 3/3 | 3/3 |
| Eggs — Claude | 3/3 | 3/3 | 3/3 |

Near parity is the honest result. A good deep-research report already finds the main positions,
evidence layers, uncertainty, funding concerns, and cruxes. Ground Knowledge adds a structured,
portable artifact whose root count and adversarial properties can be rerun after every contribution.

## 5. What remains unproven

1. A wrong curator can still confirm a bad root; the actor/time/source record makes the decision
   auditable but cannot make it correct.
2. An omitted citation edge remains invisible because the system does not crawl and compare an
   external citation graph.
3. A genuinely novel semantic alias can evade automatic identity matching until review.
4. No blinded reader study yet shows better calibration or decision quality than deep-research prose.
   A ready-to-run protocol lives in `eval/reader_study/PROTOCOL.md`.
