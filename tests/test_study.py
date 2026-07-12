import os
import tempfile
import unittest

from eval.reader_study import study


class AssignmentTests(unittest.TestCase):
    def test_each_participant_gets_all_three_cases_deterministically(self):
        a = study.assign(0)
        self.assertEqual(sorted(r["case"] for r in a), ["blackholes", "covid", "eggs"])
        self.assertEqual(study.assign(0), a)                       # deterministic
        for r in a:
            self.assertIn(r["condition"], ("DR", "DR+GK"))

    def test_conditions_balance_across_participants(self):
        counts = {"DR": 0, "DR+GK": 0}
        for i in range(24):
            for r in study.assign(i):
                counts[r["condition"]] += 1
        self.assertLessEqual(abs(counts["DR"] - counts["DR+GK"]), 4)  # roughly balanced


class ScoringTests(unittest.TestCase):
    def _answers(self, case, correct=True):
        gold = study.load_gold()
        spec = gold["cases"][case]
        ans = {"flood": gold["flood_gold"] if correct else "Increase"}
        for q in spec["questions"]:
            g = q["gold"][0] if isinstance(q["gold"], list) else q["gold"]
            ans[q["id"]] = g if correct else "definitely wrong"
        return ans

    def test_all_correct_scores_full_and_all_wrong_scores_zero(self):
        full = study.score_case("covid", self._answers("covid", True))
        self.assertEqual(full["objective"], 1.0)
        none = study.score_case("covid", self._answers("covid", False))
        self.assertEqual(none["objective"], 0.0)

    def test_crux_accepts_any_listed_gold_answer(self):
        # covid crux gold is a list; either the ascertainment or furin answer is correct
        a = {"flood": "Stay the same", "bases": "about 5",
             "crux": "Furin cleavage site as evidence of laboratory engineering"}
        self.assertTrue(study.score_case("covid", a)["items"]["crux"])

    def test_free_text_is_captured_not_scored(self):
        resp = {"participant": "p", "cases": [
            {"case": "eggs", "condition": "DR", "answers": self._answers("eggs", True),
             "free": {"crux_open": "confounding"}}]}
        scored = study.score_response(resp)
        self.assertEqual(scored[0]["free"], {"crux_open": "confounding"})
        self.assertEqual(scored[0]["score"]["objective"], 1.0)

    def test_aggregate_reports_uplift_between_conditions(self):
        obs = [
            {"condition": "DR", "score": {"objective": 0.4, "items": {"flood": False}}},
            {"condition": "DR+GK", "score": {"objective": 0.9, "items": {"flood": True}}},
        ]
        agg = study.aggregate(obs)
        self.assertAlmostEqual(agg["DR"]["meanObjective"], 0.4)
        self.assertAlmostEqual(agg["DR+GK"]["meanObjective"], 0.9)
        self.assertAlmostEqual(agg["upliftDRplusGK"], 0.5)


class StoreRoundTripTests(unittest.TestCase):
    def test_save_list_count(self):
        from app import store
        with tempfile.TemporaryDirectory() as d:
            old = store._SQLITE_PATH
            store._SQLITE_PATH = os.path.join(d, "t.db")
            try:
                store.init_db()
                self.assertEqual(store.count_study_participants(), 0)
                store.save_study_response("p1", {"cases": []}, [{"case": "covid", "condition": "DR"}])
                self.assertEqual(store.count_study_participants(), 1)
                rows = store.list_study_responses()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["participant"], "p1")
                self.assertEqual(rows[0]["scored"][0]["case"], "covid")
            finally:
                store._SQLITE_PATH = old


class WebRenderTests(unittest.TestCase):
    def test_form_renders_with_consent_and_all_cases(self):
        from app.study_web import study_form_html
        html = study_form_html(0, "abc123")
        self.assertIn("anonymous", html)
        self.assertIn("Submit my answers", html)
        for title in ("SARS-CoV-2", "black hole", "eggs"):
            self.assertIn(title, html)

    def test_report_renders_markdown_and_strips_preamble(self):
        from app.study_web import study_report_html
        self.assertIsNone(study_report_html("nope"))
        html = study_report_html("covid")
        # research-session narration is stripped; report starts at its real title
        self.assertNotIn("loading the web tools", html)
        self.assertIn("The Origin of SARS-CoV-2", html)
        # markdown is actually rendered, not shown raw
        self.assertIn("<em>", html)                 # italics
        self.assertIn("<hr>", html)                 # horizontal rules
        self.assertIn("<li>", html)                 # lists
        self.assertNotIn("<p>---</p>", html)        # no raw horizontal rule
        self.assertNotIn("<p>- ", html)             # no raw bullet

    def test_results_page_renders_empty(self):
        from app.study_web import study_results_html
        self.assertIn("DR vs DR+GK", study_results_html([]))


if __name__ == "__main__":
    unittest.main()
