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

    def test_tie_falls_to_highest_confidence_and_flags(self):
        c, rep = self._one([_d("NEW:Increases aggression", conf=0.6),
                            _d("NEW:No clear effect", conf=0.95)])
        self.assertEqual(c["source"]["position"], "NEW:No clear effect")   # higher confidence
        self.assertTrue(rep["flagged"])
        self.assertIn("position", rep["disagreedFields"])

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
