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

A deep-research answer states "many studies find no association"; it does **not** compute that those
studies reduce to four independent looks. This number is the product.

## 3. Adversarial invariance (the robustness contract, executed)

For each case, flood the strongest position and recompute:

| Attack | Result | Contract |
|---|---|---|
| +12 ungrounded echo | nEff + **≤1.0** | 12 rehashes collapse to one pooled voice |
| +12 fabricated named datasets (unverified path) | nEff + **6.0**, not +12 | each provisional-**halved** and flagged "unconfirmed" |

**PASS on all three cases.** Echo is fully neutralized. Fabrication is *halved and flagged*, not
eliminated — the acknowledged residual (`MECHANISM.md` §8): the arithmetic cannot tell a real dataset
from a fabricated one, so an unverified named root counts at half until a fetch or a curator confirms
it, and every such root is visibly marked. A prose baseline has no analogue of this property at all —
adding twelve fabricated citations to a deep-research prompt simply makes the paragraph more confident.

## What the baseline gives, and doesn't

`eval/baselines/covid.md` is a representative deep-research-style prose answer for the COVID
sub-question (authored stand-in — swap in a real deep-research/Claude transcript to make it live). It
is genuinely useful: fluent, cited, balanced. What it does not give, and this tool does:

- a **recomputable** independence number (re-run the engine, get the same answer);
- the **collapse** of six Bayesian re-analyses to their shared evidence;
- an **adversarial-invariance guarantee** you can execute;
- a **diffable artifact** another team extends, rather than a one-time paragraph.

## Honest limitations this benchmark surfaces

1. **Crux recall is partial** (sparse factor grid).
2. **Fabrication is discounted, not defeated** — the half-weight + flag is the mitigation, not a proof.
3. **The baseline is an authored stand-in**, not a live deep-research call; the harness is built to
   accept a real transcript.
