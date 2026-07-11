# Benchmark results — Ground Knowledge vs. a deep-research baseline

*Run `python eval/run_benchmark.py` to reproduce. Gold fixtures: `eval/gold.json`. Baselines:
`eval/baselines/`.*

The rubric's first instruction to judges is to anchor against off-the-shelf deep research. This is
that comparison, made runnable. The claim is **not** "a better paragraph" — a good deep-research tool
writes an excellent paragraph. The claim is a **structured, recomputable artifact whose numbers move
only for legitimate reasons**, which a prose answer cannot be.

## 1. Structure recall (does the tool surface the right map?)

Against small hand-specified gold fixtures per case:

| Case | positions | key roots | cruxes |
|---|---|---|---|
| COVID | 3/3 | 4/4 | 1/3 |
| Black holes | 2/2 | 2/2 | 0/3 |
| Eggs | 3/3 | 3/3 | 1/3 |

Positions and evidentiary roots are recalled fully. **Crux recall is honestly partial** — and that is
a *finding*, not a bug: a crux only emerges when ≥2 camps weigh the *same* factor with a ≥2-level
spread, so cruxes a single camp raises (or a settled 2-camp case like black holes) don't register.
This is the sparse-factor-grid limitation named in `SPEC.md` §8, surfaced quantitatively.

## 2. Collapse (the headline claim, quantified)

Raw source count → distinct independent evidence bases, per position:

- **COVID** — Zoonotic 15 → **5.0**, Laboratory 8 → **3.5** (the six Bayesian re-analyses rest on the
  same evidence; they are re-analysis, not six independent looks).
- **Black holes** — No risk 14 → **2.5** (the settled consensus rests on ~2–3 arguments), Residual 6 → 3.0.
- **Eggs** — No association 9 → **4.0** (6 of the 9 share the Nurses' Health / HPFS cohort).

The live Deep Research reports do better than a naive literature summary: they independently notice
shared cohorts and recycled arguments. They do **not** turn that observation into a recomputable
root graph or the quantitative 9 → 4 collapse. That inspectable number is the product distinction.

## 3. Adversarial robustness (the robustness contract, executed)

For each case, flood the strongest position and recompute:

| Attack | Result | Contract |
|---|---|---|
| +12 ungrounded echo | nEff + **≤1.0** | 12 rehashes collapse to one pooled voice |
| +12 fabricated named datasets (unverified path) | confirmed nEff + **0.0** | proposed roots remain visible but are quarantined until confirmed |

**PASS on all three cases.** Echo is pooled. Fabricated roots remain visible for review but contribute
zero to confirmed nEff until a fetched dependency quote verifies them or a curator confirms them. The remaining risk is false
confirmation: the arithmetic cannot itself tell whether a fetched source really entails the proposed
edge. A prose baseline has no analogue of this executable property —
adding twelve fabricated citations to a deep-research prompt simply makes the paragraph more confident.

## What the live baseline gives, and doesn't

Two independent baseline sets were captured on 2026-07-11 from the same prompts with no repository,
case source list, or Ground Knowledge framework supplied: ChatGPT Deep Research and Claude Code web
research. Raw outputs, operator-confirmed prompts, timestamps, and SHA-256 hashes live in the two
baseline manifests. The original authored COVID stand-in is retained separately for audit history.

This is a strong baseline. All three reports identify the main positions, load-bearing evidence,
uncertainty, source-quality issues, and important cruxes. They also notice evidence dependence:

| Capability | ChatGPT Deep Research | Claude Code | Ground Knowledge |
|---|---|---|---|
| Main positions, load-bearing evidence, cruxes | yes | yes | yes, structured |
| Reused/overlapping evidence noticed qualitatively | yes | yes, in dedicated sections | encoded as root edges |
| Funding/source-quality concerns | yes | yes | structured fields + warnings |
| Portable URLs in captured Markdown | no (internal citation tokens) | yes | yes |
| Explicit root graph and deterministic collapse count | no | no | yes |
| Versioned update diff / contributor artifact | no | no | yes |
| Executable flooding/fabrication contract | no | no | yes |

The Claude reports are particularly demanding comparators. The eggs report independently reduces the
literature to roughly four genuinely distinct strands; the COVID report identifies the shared Chinese
market dataset, overlapping author group, and recycled advocacy document set; the black-hole report
separates production, Hawking evaporation, accretion, and dense-star survival into different failure
layers. That last report exposes a real ontology limitation here: Ground Knowledge's 2.5-base safe
count captures the encoded empirical/dependency roots but does not fully represent every independent
theoretical safety argument. The number must not be presented as an exhaustive count of all arguments.

The honest advantage is therefore narrower than “Deep Research misses correlation.” It does not.
What Ground Knowledge adds is:

- a **recomputable** independence number (re-run the engine, get the same answer);
- the **collapse** of six Bayesian re-analyses to their shared evidence;
- an **adversarial-robustness contract** you can execute;
- a **diffable artifact** another team extends, rather than a one-time paragraph.

## Honest limitations this benchmark surfaces

1. **Crux recall is partial** (sparse factor grid).
2. **Fabrication is quarantined, not semantically disproved** — a bad confirmation can still admit it.
3. **Portable citation limitation:** ChatGPT's Markdown export preserved internal citation tokens
   (`turn…view…`) but not their URLs. The original chats/share links or PDF exports should accompany
   the submission so judges can open the cited sources. Claude Code's captures do preserve URLs.
4. **Non-empirical root ontology remains incomplete:** the black-hole Claude baseline distinguishes
   more theoretical failure layers than the current KB encodes as roots.
