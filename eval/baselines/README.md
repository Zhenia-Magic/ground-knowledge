# Deep-research baselines

To keep the comparison honest and live, drop a **real** deep-research / Claude transcript for each
sub-question here as `<case>.md`, answering the matched sub-question in `eval/gold.json`. The files
checked in now are **authored stand-ins** (clearly labelled) so the benchmark reads end-to-end
without an API call — replace them with real output to make the comparison live.

The point of the comparison is in `eval/RESULTS.md`: a prose answer is fluent and useful, but it is
not a recomputable artifact, it does not compute the collapse of correlated evidence, and it offers
no adversarial-invariance guarantee. The benchmark quantifies the difference.
