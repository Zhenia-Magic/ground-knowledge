"""Tests for the human-in-the-loop review queue (engine/review.py): ensemble position
disagreements are queued — not merged with a tie-break — until a person picks a position
or drops the paper."""
import unittest

from engine import review
from engine.merge import merge_delta
from engine.schema import empty_kb


def _flagged_delta(title="Contested paper", url="https://ex.org/contested"):
    return {
        "reviewText": "ABSTRACT: violent games were associated with ...",
        "source": {
            "title": title, "year": 2020, "url": url,
            "position": "NEW:Increases aggression", "evidence": "Observational", "restsOn": [],
            "modelAgreement": {
                "models": 2, "flagged": True, "disagreedFields": ["position"],
                "positionVote": {"NEW:Increases aggression": 1, "NEW:No clear effect": 1},
                "proposals": [
                    {"position": "NEW:Increases aggression", "votes": 1,
                     "quote": "aggression increased", "confidence": 0.8},
                    {"position": "NEW:No clear effect", "votes": 1,
                     "quote": "no association found", "confidence": 0.7}]}},
        "factorWeights": [{"factor": "Publication bias", "weight": "high"}],
    }


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.kb = empty_kb("t", "q")

    def test_flagged_delta_is_detected(self):
        self.assertTrue(review.needs_review(_flagged_delta()))
        self.assertFalse(review.needs_review({"source": {"title": "x"}}))

    def test_queue_holds_entry_with_abstract_and_proposals(self):
        e = review.queue_for_review(self.kb, _flagged_delta())
        self.assertEqual(len(self.kb["pendingReview"]), 1)
        self.assertIn("ABSTRACT", e["abstract"])
        self.assertEqual(len(e["proposals"]), 2)
        self.assertEqual(len(self.kb["sources"]), 0)       # NOT merged
        self.assertNotIn("reviewText", e["delta"])          # abstract not duplicated in the delta

    def test_requeue_of_same_source_is_a_noop(self):
        review.queue_for_review(self.kb, _flagged_delta())
        self.assertIsNone(review.queue_for_review(self.kb, _flagged_delta()))
        self.assertEqual(len(self.kb["pendingReview"]), 1)

    def test_already_merged_source_is_not_queued(self):
        merge_delta(self.kb, {"source": {"title": "Contested paper", "year": 2020,
                                         "url": "https://ex.org/contested",
                                         "position": "NEW:Increases aggression",
                                         "evidence": "Observational", "restsOn": []}})
        self.assertIsNone(review.queue_for_review(self.kb, _flagged_delta()))


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.kb = empty_kb("t", "q")
        self.entry = review.queue_for_review(self.kb, _flagged_delta())

    def test_resolve_to_proposed_position_merges(self):
        rep = review.resolve_review(self.kb, self.entry["id"], "position", "NEW:No clear effect")
        self.assertTrue(rep.get("addedSource"))
        self.assertEqual(self.kb["pendingReview"], [])
        s = self.kb["sources"][0]
        self.assertEqual(self.kb["positions"][0]["label"], "No clear effect")
        self.assertFalse(s["modelAgreement"]["flagged"])           # human decision clears the flag
        self.assertEqual(s["modelAgreement"]["resolvedBy"], "human")

    def test_resolve_to_existing_position_by_label_and_id(self):
        merge_delta(self.kb, {"source": {"title": "seed", "year": 2019, "url": "https://ex.org/s",
                                         "position": "NEW:No clear effect",
                                         "evidence": "Observational", "restsOn": []}})
        pid = self.kb["positions"][0]["id"]
        rep = review.resolve_review(self.kb, self.entry["id"], "position", "no clear effect")
        self.assertTrue(rep.get("addedSource"))
        self.assertEqual(len(self.kb["positions"]), 1)             # resolved onto the existing camp
        self.assertEqual(self.kb["sources"][-1]["position"], pid)

    def test_drop_discards_and_logs(self):
        rep = review.resolve_review(self.kb, self.entry["id"], "drop")
        self.assertTrue(rep["dropped"])
        self.assertEqual(self.kb["pendingReview"], [])
        self.assertEqual(self.kb["sources"], [])
        self.assertEqual(self.kb["log"][-1]["action"], "review-drop")

    def test_unknown_id_and_missing_position_raise(self):
        with self.assertRaises(ValueError):
            review.resolve_review(self.kb, "pr_nope", "drop")
        with self.assertRaises(ValueError):
            review.resolve_review(self.kb, self.entry["id"], "position", "")

    def test_pending_entries_do_not_affect_metrics(self):
        from engine.assess import assess
        a = assess(self.kb)
        self.assertEqual(a["distribution"], [])                    # no positions, no sources


class FlaggedSourceReReviewTests(unittest.TestCase):
    """Already-MERGED sources that carry a disagreement flag (legacy / paste-back path) must show
    up in the same review surface and be re-decidable in place."""

    def setUp(self):
        self.kb = empty_kb("t", "q")
        merge_delta(self.kb, {"source": {
            "title": "Merged but contested", "year": 2021, "url": "https://ex.org/m",
            "position": "NEW:Increases risk", "evidence": "Observational", "restsOn": [],
            "modelAgreement": {"models": 2, "flagged": True,
                               "positionVote": {"pos_increases_risk": 1, "NEW:No clear effect": 1}}}})
        self.sid = self.kb["sources"][0]["id"]

    def test_flagged_source_appears_in_review_items_and_count(self):
        items = review.review_items(self.kb)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "flagged")
        self.assertEqual(items[0]["id"], self.sid)
        self.assertEqual(len(items[0]["proposals"]), 2)     # reconstructed from the vote
        self.assertEqual(review.review_count(self.kb), 1)

    def test_reposition_in_place_clears_flag_and_switches_camp(self):
        rep = review.resolve_flagged_source(self.kb, self.sid, "position", "NEW:No clear effect")
        self.assertTrue(rep.get("resolved"))
        s = self.kb["sources"][0]
        self.assertEqual(self.kb["positions"][-1]["label"], "No clear effect")
        self.assertEqual(s["position"], self.kb["positions"][-1]["id"])
        self.assertFalse(s["modelAgreement"]["flagged"])
        self.assertEqual(review.review_count(self.kb), 0)

    def test_accept_keeps_label_and_clears_flag(self):
        pos_before = self.kb["sources"][0]["position"]
        rep = review.resolve_flagged_source(self.kb, self.sid, "accept")
        self.assertTrue(rep.get("kept"))
        s = self.kb["sources"][0]
        self.assertEqual(s["position"], pos_before)          # unchanged
        self.assertFalse(s["modelAgreement"]["flagged"])
        self.assertEqual(review.review_count(self.kb), 0)

    def test_drop_removes_the_merged_source_and_prunes_provenance(self):
        self.kb.setdefault("factors", []).append(
            {"id": "f_x", "label": "X", "weights": {}, "provenance": [{"source": self.sid, "quote": "q"}]})
        rep = review.resolve_flagged_source(self.kb, self.sid, "drop")
        self.assertTrue(rep["dropped"])
        self.assertEqual(self.kb["sources"], [])
        self.assertEqual(self.kb["factors"][0]["provenance"], [])

    def test_unknown_source_id_raises(self):
        with self.assertRaises(ValueError):
            review.resolve_flagged_source(self.kb, "nope", "drop")
