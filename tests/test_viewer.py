import json
import os
import unittest

from app.web import viewer_html
from engine.assess import cruxes

ROOT = os.path.dirname(os.path.dirname(__file__))


def _kb(case):
    return json.load(open(os.path.join(ROOT, "cases", case), encoding="utf-8"))


def _cruxes(case):
    return {c["label"]: c for c in cruxes(_kb(case))}


class DivergenceTaxonomyTests(unittest.TestCase):
    """A SHARED PIVOT (both camps rate it decisive; spread 0) is a distinct thing from a DISAGREEMENT
    crux (camps weigh it very differently). The divergence matrix must not conflate them."""

    def test_black_hole_hawking_is_a_shared_pivot_not_a_disagreement(self):
        hawking = next(c for l, c in _cruxes("blackholes.kb.json").items() if "Hawking" in l)
        self.assertTrue(hawking["sharedPivot"])       # both camps rate it high
        self.assertFalse(hawking["crossCampCrux"])    # they do NOT weigh it differently
        self.assertTrue(hawking["isCrux"])            # still a crux — just the shared kind

    def test_black_hole_case_has_no_cross_camp_disagreement_crux(self):
        cx = _cruxes("blackholes.kb.json")
        self.assertEqual(sum(1 for c in cx.values() if c["crossCampCrux"]), 0)

    def test_covid_has_a_cross_camp_disagreement_crux(self):
        cx = _cruxes("covid.kb.json")
        self.assertGreaterEqual(sum(1 for c in cx.values() if c["crossCampCrux"]), 1)


class DivergenceCopyTests(unittest.TestCase):
    """The viewer template must carry the distinct badges and drop the copy that called every crux a
    'weigh very differently' disagreement (which was false for shared pivots)."""

    def test_template_has_distinct_badge_and_honest_tooltip(self):
        html = viewer_html("t", lambda _: {"id": "t", "question": "q", "version": 0,
                                           "kb": _kb("blackholes.kb.json")})
        self.assertIn("SHARED PIVOT", html)
        self.assertIn("pivotbadge", html)
        self.assertNotIn("weigh very differently — that is where the real disagreement", html)


if __name__ == "__main__":
    unittest.main()
