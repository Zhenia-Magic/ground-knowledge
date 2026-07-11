"""Tests for the multi-model labelling ensemble (ingest/ensemble.combine) and the rate gate /
model-list parsing in ingest/llm."""
import os
import time
import unittest

from ingest import ensemble, llm


def _d(position, evidence="Observational", funding="Academic/institutional",
       population="Adults", rests=None, conf=0.8, relevant=True, factors=None, offtopic=None):
    src = {"title": "t", "position": position, "evidence": evidence, "funding": funding,
           "population": population, "restsOn": rests or [], "relevant": relevant,
           "provenance": {"position": {"quote": "q for " + str(position),
                                       "extractionConfidence": conf}}}
    if offtopic:
        src["offTopicReason"] = offtopic
    return {"source": src, "factorWeights": factors or []}


class CombineOneTests(unittest.TestCase):
    def _one(self, deltas):
        c, rep = ensemble.combine_one(deltas)
        return c, rep

    def test_majority_position_wins_and_is_not_flagged(self):
        c, rep = self._one([_d("NEW:Increases aggression"), _d("NEW:Increases aggression"),
                            _d("NEW:No clear effect")])
        self.assertEqual(c["source"]["position"], "NEW:Increases aggression")
        self.assertFalse(rep["flagged"])
        self.assertAlmostEqual(rep["positionAgreement"], 2 / 3, places=2)

    def test_same_stance_different_wording_is_agreement_not_disagreement(self):
        # the real-world false-flag: models agree on stance but phrase the NEW label differently
        c, rep = self._one([_d("NEW:Violent video games increase aggression", conf=0.8),
                            _d("increases aggression", conf=0.7)])
        self.assertFalse(rep["flagged"])
        self.assertAlmostEqual(rep["positionAgreement"], 1.0, places=2)

    def test_new_prefix_matches_bare_label(self):
        c, rep = self._one([_d("NEW:No clear effect"), _d("no clear effect"), _d("pos_no_clear_effect")])
        self.assertFalse(rep["flagged"])

    def test_formatting_variants_are_the_same_stance(self):
        # spaced vs camelCase vs snake_case vs plural — all one camp, must not flag
        for a, b in [("NEW:Increases aggression", "NEW:IncreaseAggression"),
                     ("NEW:No clear effect", "NEW:NoClearEffect"),
                     ("NEW:Increases aggression", "NEW:increase_aggression")]:
            _, rep = self._one([_d(a), _d(b)])
            self.assertFalse(rep["flagged"], (a, b))

    def test_genuine_opposite_stance_still_flags(self):
        c, rep = self._one([_d("NEW:No clear effect", conf=0.7),
                            _d("NEW:Violent video games increase aggression", conf=0.9)])
        self.assertTrue(rep["flagged"])
        self.assertEqual(c["source"]["position"], "NEW:Violent video games increase aggression")

    def test_tie_falls_to_highest_confidence_and_flags(self):
        c, rep = self._one([_d("NEW:Increases aggression", conf=0.6),
                            _d("NEW:No clear effect", conf=0.95)])
        self.assertEqual(c["source"]["position"], "NEW:No clear effect")   # higher confidence
        self.assertTrue(rep["flagged"])
        self.assertIn("position", rep["disagreedFields"])

    def test_tier_split_escalates_even_when_position_agrees(self):
        # models agree on the POSITION but split on evidence TIER (primary vs secondary): the bigger
        # nEff lever, so escalate to human review though the field-vote still picks a winner.
        c, rep = self._one([_d("NEW:Increases aggression", evidence="Observational"),
                            _d("NEW:Increases aggression", evidence="Narrative/Commentary")])
        self.assertTrue(rep["tierSplit"])
        self.assertTrue(rep["flagged"])
        self.assertIn("evidence", rep["disagreedFields"])

    def test_same_tier_evidence_variation_is_not_a_tier_split(self):
        # review vs meta-analysis differ, but both are SECONDARY -> not a tier split, no escalation
        c, rep = self._one([_d("NEW:Increases aggression", evidence="Systematic review"),
                            _d("NEW:Increases aggression", evidence="Meta-analysis")])
        self.assertFalse(rep["tierSplit"])
        self.assertFalse(rep["flagged"])

    def test_winning_models_quote_is_carried(self):
        c, _ = self._one([_d("NEW:Increases aggression", conf=0.6),
                          _d("NEW:Increases aggression", conf=0.9),
                          _d("NEW:No clear effect", conf=0.99)])
        # majority is "Increases"; among those the 0.9 model wins -> its quote
        self.assertIn("Increases aggression", c["source"]["provenance"]["position"]["quote"])

    def test_categorical_fields_take_the_mode(self):
        c, _ = self._one([_d("NEW:X", evidence="Meta-analysis", funding="Industry"),
                          _d("NEW:X", evidence="Meta-analysis", funding="Undisclosed"),
                          _d("NEW:X", evidence="Observational", funding="Industry")])
        self.assertEqual(c["source"]["evidence"], "Meta-analysis")
        self.assertEqual(c["source"]["funding"], "Industry")

    def test_restsOn_kept_only_if_half_propose_it(self):
        c, _ = self._one([_d("NEW:X", rests=["ds_a", "ds_b"]),
                          _d("NEW:X", rests=["ds_a"]),
                          _d("NEW:X", rests=["ds_c"])])
        # ds_a in 2/3 (kept); ds_b, ds_c each 1/3 (dropped)
        self.assertEqual(c["source"]["restsOn"], ["ds_a"])

    def test_factor_kept_only_if_half_propose_with_mode_weight(self):
        f = lambda lab, w: {"factor": lab, "weight": w, "quote": "q", "rationale": "r"}
        c, _ = self._one([_d("NEW:X", factors=[f("Publication bias", "high")]),
                          _d("NEW:X", factors=[f("Publication bias", "high"), f("Lab proxies", "low")]),
                          _d("NEW:X", factors=[f("Publication bias", "med")])])
        labels = [fw["factor"] for fw in c["factorWeights"]]
        self.assertIn("Publication bias", labels)          # 3/3
        self.assertNotIn("Lab proxies", labels)            # 1/3, dropped
        pb = next(fw for fw in c["factorWeights"] if fw["factor"] == "Publication bias")
        self.assertEqual(pb["weight"], "high")             # mode of high/high/med

    def test_majority_offtopic_refuses_source(self):
        c, rep = self._one([_d("NEW:X", relevant=False, offtopic="different outcome"),
                            _d("NEW:X", relevant=False, offtopic="different outcome"),
                            _d("NEW:X", relevant=True)])
        self.assertIs(c["source"]["relevant"], False)
        self.assertEqual(c["source"]["offTopicReason"], "different outcome")

    def test_offtopic_minority_does_not_vote_on_position(self):
        c, rep = self._one([_d("NEW:Increases", relevant=True, conf=0.9),
                            _d("NEW:Increases", relevant=True, conf=0.8),
                            _d("NEW:X", relevant=False, offtopic="x")])
        self.assertTrue(c["source"]["relevant"])
        self.assertEqual(c["source"]["position"], "NEW:Increases")

    def test_agreement_report_attached_to_source(self):
        c, rep = self._one([_d("NEW:X"), _d("NEW:X")])
        self.assertEqual(c["source"]["modelAgreement"]["models"], 2)
        self.assertEqual(c["source"]["modelAgreement"], rep)

    def test_empty_and_single(self):
        c0, r0 = self._one([])
        self.assertIs(c0["source"]["relevant"], False)
        self.assertTrue(r0["flagged"])
        c1, r1 = self._one([_d("NEW:X")])
        self.assertEqual(r1["models"], 1)
        self.assertFalse(r1["flagged"])


class CombineAlignmentTests(unittest.TestCase):
    def test_short_model_array_does_not_crash_or_misalign(self):
        # model B returned only 1 delta for a 2-source batch (truncation) -> source 2 uses A only
        a = [_d("NEW:Increases"), _d("NEW:No effect")]
        b = [_d("NEW:Increases")]
        consensus, agree = ensemble.combine([a, b], 2)
        self.assertEqual(len(consensus), 2)
        self.assertEqual(consensus[0]["source"]["position"], "NEW:Increases")
        self.assertEqual(consensus[1]["source"]["position"], "NEW:No effect")   # only A voted
        self.assertEqual(agree[1]["models"], 1)


class RateAndModelListTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("EPISTEMIC_LABEL_MODELS")
        os.environ.pop("EPISTEMIC_LABEL_MODELS", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("EPISTEMIC_LABEL_MODELS", None)
        else:
            os.environ["EPISTEMIC_LABEL_MODELS"] = self._saved

    def test_label_models_needs_two(self):
        self.assertEqual(llm.label_models(), [])
        os.environ["EPISTEMIC_LABEL_MODELS"] = "only-one"
        self.assertEqual(llm.label_models(), [])          # a single model is not an ensemble
        os.environ["EPISTEMIC_LABEL_MODELS"] = "a, b , c"
        self.assertEqual(llm.label_models(), ["a", "b", "c"])

    def test_rate_gate_disabled_is_a_noop(self):
        saved = llm._RATE_LIMIT_RPM
        try:
            llm._RATE_LIMIT_RPM = 0
            t0 = time.time()
            for _ in range(100):
                llm._rate_gate()
            self.assertLess(time.time() - t0, 0.5)        # no sleeping when disabled
        finally:
            llm._RATE_LIMIT_RPM = saved

    def test_rate_gate_records_calls_within_window(self):
        saved = llm._RATE_LIMIT_RPM
        saved_calls = list(llm._rate_calls)
        try:
            llm._RATE_LIMIT_RPM = 1000            # high enough to never sleep in the test
            llm._rate_calls.clear()
            for _ in range(5):
                llm._rate_gate()
            self.assertEqual(len(llm._rate_calls), 5)
        finally:
            llm._RATE_LIMIT_RPM = saved
            llm._rate_calls[:] = saved_calls


class PostTimeoutRetryTests(unittest.TestCase):
    """A read timeout (socket.timeout) must be RETRIED, not crash the run as it did before."""

    class _FakeResp:
        def __init__(self, payload):
            self._payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return self._payload

    def _patch(self, sequence):
        """sequence: list of exceptions-to-raise or payloads-to-return, consumed per call."""
        import urllib.request
        calls = {"n": 0}
        seq = list(sequence)

        def fake_urlopen(req, timeout=None):
            i = calls["n"]; calls["n"] += 1
            item = seq[i]
            if isinstance(item, BaseException):
                raise item
            return self._FakeResp(item)
        self._orig = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        self._sleep = time.sleep
        time.sleep = lambda *_a, **_k: None      # don't actually back off in the test
        return calls

    def tearDown(self):
        import urllib.request
        if hasattr(self, "_orig"):
            urllib.request.urlopen = self._orig
        if hasattr(self, "_sleep"):
            time.sleep = self._sleep

    def test_timeout_then_success_is_retried(self):
        import socket
        calls = self._patch([socket.timeout("The read operation timed out"),
                             b'{"ok": true}'])
        out = llm._post("http://x", {}, {"a": 1}, tries=4)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(calls["n"], 2)          # failed once, retried, succeeded

    def test_persistent_timeout_raises_clean_systemexit(self):
        import socket
        self._patch([socket.timeout()] * 4)
        with self.assertRaises(SystemExit) as cm:
            llm._post("http://x", {}, {"a": 1}, tries=4)
        self.assertIn("timed out", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class EdgeClusteringTests(unittest.TestCase):
    """restsOn vote must cluster two models' names for the SAME cohort — the alias-twin bug that
    double-counted one study's data as two independent roots (10/40 sources on the real case)."""

    def _one(self, deltas):
        return ensemble.combine_one(deltas)

    def test_token_overlapping_twin_names_are_never_double_counted(self):
        # twin names for one study must never become TWO independent roots: they either cluster into
        # one edge (majority) or drop to the pool on non-majority -- but never inflate to two.
        c, _ = self._one([_d("NEW:X", rests=["NEW:GTA V vs Sims 3 longitudinal intervention cohort"]),
                          _d("NEW:X", rests=["NEW:GTA V longitudinal intervention 2018"])])
        self.assertLessEqual(len(c["source"]["restsOn"]), 1)

    def test_disjoint_single_proposals_are_not_force_merged(self):
        # the removed all_single rule used to force-merge two DIFFERENT single datasets into false
        # agreement. Now they don't cluster and neither reaches a majority -> both drop (pool, safe),
        # and the disagreement is recorded rather than laundered into a fabricated shared root.
        c, rep = self._one([_d("NEW:X", rests=["NEW:UK adolescent VVG and aggression cohort (N=1004)"]),
                            _d("NEW:X", rests=["NEW:Przybylski2019 adolescent dataset"])])
        self.assertEqual(c["source"]["restsOn"], [])
        self.assertIn("restsOn", rep["disagreedFields"])

    def test_winner_wording_is_preferred_when_an_edge_survives(self):
        # both models name the SAME cohort (share the distinguishing token) -> majority -> the
        # higher-confidence model's wording is the representative form.
        c, _ = self._one([_d("NEW:X", conf=0.9, rests=["NEW:Greitemeyer 2019 aggression cohort"]),
                          _d("NEW:X", conf=0.5, rests=["NEW:Greitemeyer 2019 aggression longitudinal"])])
        self.assertEqual(c["source"]["restsOn"], ["NEW:Greitemeyer 2019 aggression cohort"])

    def test_two_genuinely_distinct_datasets_survive(self):
        # both models list the same TWO cohorts (one under a name variant) -> exactly two edges
        c, _ = self._one([_d("NEW:X", rests=["NEW:Nurses Health Study", "NEW:UK Biobank"]),
                          _d("NEW:X", rests=["NEW:Nurses' Health Study cohort", "NEW:UK Biobank"])])
        self.assertEqual(len(c["source"]["restsOn"]), 2)

    def test_src_edge_needs_a_strict_majority(self):
        # a src: edge proposed by only 1 of 2 models does NOT survive (strict > m/2); the unanimous
        # Cohort Q does. So one model's spurious citation edge can never mint a derivation link.
        c, rep = self._one([_d("NEW:X", rests=["SRC:src_a_2010", "NEW:Cohort Q"]),
                            _d("NEW:X", rests=["NEW:Cohort Q"])])
        self.assertNotIn("SRC:src_a_2010", c["source"]["restsOn"])
        self.assertEqual(len(c["source"]["restsOn"]), 1)
        self.assertIn("restsOn", rep["disagreedFields"])


class MergeGuardTests(unittest.TestCase):
    def setUp(self):
        from engine.schema import empty_kb
        from engine.merge import merge_delta
        self.merge_delta = merge_delta
        self.kb = empty_kb("t", "q")
        self.merge_delta(self.kb, {"source": {
            "title": "Violent Video Game Effects on Aggression Empathy and Prosocial Behavior",
            "year": 2010, "url": "https://ex.org/anderson2010", "position": "NEW:Increases",
            "evidence": "Meta-analysis", "restsOn": []}})
        self.anderson_id = self.kb["sources"][0]["id"]

    def test_unprefixed_source_id_becomes_src_edge_not_dataset(self):
        self.merge_delta(self.kb, {"source": {
            "title": "A reanalysis", "year": 2017, "url": "https://ex.org/re",
            "position": "NEW:No effect", "evidence": "Meta-analysis",
            "restsOn": ["NEW:" + self.anderson_id]}})       # raw src_... id without SRC: prefix
        s = self.kb["sources"][1]
        self.assertEqual(s["restsOn"], ["src:" + self.anderson_id])
        self.assertFalse(any(d["id"].startswith("ds_src_") for d in self.kb["datasets"]))

    def test_source_title_as_dataset_becomes_src_edge(self):
        self.merge_delta(self.kb, {"source": {
            "title": "A commentary", "year": 2011, "url": "https://ex.org/c",
            "position": "NEW:Increases", "evidence": "Narrative/Commentary",
            "restsOn": ["NEW:Violent Video Game Effects on Aggression Empathy and Prosocial Behavior"]}})
        self.assertEqual(self.kb["sources"][1]["restsOn"], ["src:" + self.anderson_id])

    def test_real_cohort_names_still_make_datasets(self):
        self.merge_delta(self.kb, {"source": {
            "title": "A cohort study", "year": 2019, "url": "https://ex.org/coh",
            "position": "NEW:No effect", "evidence": "Observational",
            "restsOn": ["NEW:UK adolescent cohort"]}})
        self.assertTrue(self.kb["sources"][1]["restsOn"][0].startswith("ds_"))

    def test_title_prefix_duplicate_refused(self):
        # same paper: publisher link with full title vs mirror with truncated title, same year
        rep = self.merge_delta(self.kb, {"source": {
            "title": "Violent Video Game Effects on Aggression Empathy and Prosocial",
            "year": 2010, "url": "https://mirror.org/pmc123", "position": "NEW:Increases",
            "evidence": "Meta-analysis", "restsOn": []}})
        self.assertTrue(rep["duplicate"])

    def test_different_year_same_prefix_not_refused(self):
        rep = self.merge_delta(self.kb, {"source": {
            "title": "Violent Video Game Effects on Aggression Empathy and Prosocial",
            "year": 2015, "url": "https://ex.org/other", "position": "NEW:Increases",
            "evidence": "Meta-analysis", "restsOn": []}})
        self.assertFalse(rep["duplicate"])

    def test_weights_snap_to_vocabulary(self):
        self.merge_delta(self.kb, {"source": {
            "title": "Weighted", "year": 2020, "url": "https://ex.org/w",
            "position": "NEW:Increases", "evidence": "Observational", "restsOn": []},
            "factorWeights": [
                {"factor": "Publication bias", "weight": "medium"},
                {"factor": "Methodological quality", "weight": "High"},
                {"factor": "Cultural context", "weight": "Moderate"}]})
        w = {f["label"]: list(f["weights"].values())[0] for f in self.kb["factors"]}
        self.assertEqual(w["Publication bias"], "med")
        self.assertEqual(w["Methodological quality"], "high")
        self.assertEqual(w["Cultural context"], "med")

    def test_exact_title_one_year_apart_is_a_duplicate(self):
        # print-vs-online mirror drift: Nature 2018 vs PMC listing 2019
        rep = self.merge_delta(self.kb, {"source": {
            "title": "Violent Video Game Effects on Aggression Empathy and Prosocial Behavior",
            "year": 2011, "url": "https://mirror.org/pmcXY", "position": "NEW:Increases",
            "evidence": "Meta-analysis", "restsOn": []}})
        self.assertTrue(rep["duplicate"])          # KB copy is 2010; exact title, 1 year apart

    def test_exact_title_two_years_apart_is_not_a_duplicate(self):
        rep = self.merge_delta(self.kb, {"source": {
            "title": "Violent Video Game Effects on Aggression Empathy and Prosocial Behavior",
            "year": 2013, "url": "https://ex.org/later", "position": "NEW:Increases",
            "evidence": "Meta-analysis", "restsOn": []}})
        self.assertFalse(rep["duplicate"])


class FactorClusteringTests(unittest.TestCase):
    """Factor votes must cluster paraphrased labels — exact-label voting silently discarded most
    factors (a 46-source run kept only 2)."""

    def _one(self, deltas):
        return ensemble.combine_one(deltas)

    def _f(self, lab, w="high"):
        return {"factor": lab, "weight": w, "quote": "q " + lab, "rationale": "r"}

    def test_paraphrased_factor_labels_cluster_and_survive(self):
        c, _ = self._one([_d("NEW:X", factors=[self._f("Publication bias")]),
                          _d("NEW:X", factors=[self._f("publication-bias concerns", "med")])])
        self.assertEqual(len(c["factorWeights"]), 1)
        self.assertEqual(c["factorWeights"][0]["weight"], "high")   # mode ties -> first-seen

    def test_camelcase_and_plural_variants_cluster(self):
        c, _ = self._one([_d("NEW:X", factors=[self._f("Researcher expectancy effects")]),
                          _d("NEW:X", factors=[self._f("ResearcherExpectancyEffect")])])
        self.assertEqual(len(c["factorWeights"]), 1)

    def test_distinct_axes_sharing_words_stay_distinct(self):
        # Jaccard 0.5 — below the 0.6 factor bar, and neither is a subset
        c, _ = self._one([_d("NEW:X", factors=[self._f("Effect size magnitude"),
                                               self._f("Effect size heterogeneity")]),
                          _d("NEW:X", factors=[self._f("Effect size magnitude"),
                                               self._f("Effect size heterogeneity")])])
        self.assertEqual(len(c["factorWeights"]), 2)

    def test_winner_wording_preferred_for_factor_label(self):
        c, _ = self._one([_d("NEW:X", conf=0.9, factors=[self._f("Publication bias")]),
                          _d("NEW:X", conf=0.5, factors=[self._f("Publication bias in meta-analyses")])])
        self.assertEqual(c["factorWeights"][0]["factor"], "Publication bias")


class FactorMergeGuardTests(unittest.TestCase):
    def test_factor_paraphrase_folds_into_existing(self):
        from engine.schema import empty_kb
        from engine.merge import merge_delta
        kb = empty_kb("t", "q")
        d = lambda t, fl: {"source": {"title": t, "year": 2020, "url": "https://ex.org/" + t,
                                      "position": "NEW:Increases", "evidence": "Observational",
                                      "restsOn": []},
                           "factorWeights": [{"factor": fl, "weight": "high"}]}
        merge_delta(kb, d("a", "Publication bias"))
        merge_delta(kb, d("b", "Publication bias concerns"))
        merge_delta(kb, d("c", "Effect size magnitude"))
        self.assertEqual(len(kb["factors"]), 2)
        self.assertEqual(kb["factors"][0]["label"], "Publication bias")
