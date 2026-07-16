import json
import os
import unittest

from app.web import viewer_html
from engine.assess import cruxes, distribution
from engine.verify import is_verified_exact

ROOT = os.path.dirname(os.path.dirname(__file__))


def _kb(case):
    with open(os.path.join(ROOT, "cases", case), encoding="utf-8") as handle:
        return json.load(handle)


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


class KeyIssuesCopyTests(unittest.TestCase):
    """The viewer template must carry the distinct badges and drop the copy that called every crux a
    'weigh very differently' disagreement (which was false for shared pivots)."""

    def test_template_has_distinct_badge_and_honest_tooltip(self):
        html = viewer_html("t", lambda _: {"id": "t", "question": "q", "version": 0,
                                           "kb": _kb("blackholes.kb.json")})
        self.assertIn("SHARED UNCERTAINTY", html)
        self.assertIn("KEY DISAGREEMENT", html)
        self.assertIn("pivotbadge", html)
        self.assertNotIn("weigh very differently — that is where the real disagreement", html)

    def test_public_navigation_uses_plain_language_and_keeps_position(self):
        with open(os.path.join(ROOT, "viewer", "template.html"), encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn('{id:"coverage",label:"Overview"}', template)
        self.assertIn('{id:"divergence",label:"Key issues"}', template)
        self.assertIn('{id:"independence",label:"Evidence reuse"}', template)
        self.assertIn("Positions", template)
        self.assertNotIn("Root coverage & bias", template)
        self.assertNotIn("Divergence matrix", template)

    def test_issue_badges_never_split_into_separate_pills(self):
        with open(os.path.join(ROOT, "viewer", "template.html"), encoding="utf-8") as handle:
            template = handle.read()
        crux_css = template.split(".cruxbadge{", 1)[1].split("}", 1)[0]
        pivot_css = template.split(".pivotbadge{", 1)[1].split("}", 1)[0]
        self.assertIn("display:inline-block", crux_css)
        self.assertIn("white-space:nowrap", crux_css)
        self.assertIn("white-space:nowrap", pivot_css)


class QuoteBadgeCopyTests(unittest.TestCase):
    def test_full_text_alone_never_creates_a_checkmark(self):
        with open(os.path.join(ROOT, "viewer", "template.html"), encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn('a.method==="verbatim-sentence-v2"', template)
        self.assertIn("a.textSha256&&a.quoteSha256", template)
        self.assertNotIn('textDepth==="full"?\'<span class="okicon"', template)
        self.assertIn("Stored summary — not verified verbatim", template)


class FactorEvidenceContractTests(unittest.TestCase):
    def test_every_shipped_factor_cell_has_an_exact_source_sentence(self):
        for case in ("177f5ec738c9.kb.json", "51fb332b4e96.kb.json", "blackholes.kb.json",
                     "covid.kb.json", "eggs.kb.json"):
            kb = _kb(case)
            for factor in kb.get("factors", []):
                for pos_id in factor.get("weights", {}):
                    claims = [p for p in factor.get("provenance", [])
                              if p.get("pos") == pos_id and is_verified_exact(p)]
                    self.assertTrue(claims, "{}: {} / {}".format(case, factor["label"], pos_id))

    def test_factor_only_context_source_does_not_inflate_egg_position_counts(self):
        kb = _kb("eggs.kb.json")
        self.assertEqual(len(kb.get("contextSources", [])), 1)
        self.assertEqual(sum(item["count"] for item in distribution(kb)), len(kb["sources"]))
        self.assertNotIn(kb["contextSources"][0]["id"], {s["id"] for s in kb["sources"]})


class CoverageSummaryTests(unittest.TestCase):
    def test_coverage_keeps_source_count_and_independence_separate(self):
        with open(os.path.join(ROOT, "viewer", "template.html"), encoding="utf-8") as handle:
            template = handle.read()
        self.assertIn("Source count versus underlying evidence", template)
        self.assertIn("Adjusted evidence-base count", template)
        self.assertIn('class="distrib"', template)
        self.assertIn('class="indeprows"', template)
        self.assertIn('class="indtrack"', template)
        self.assertNotIn('class="cmpraw"', template)
        self.assertNotIn('class="cmpbase"', template)
        self.assertNotIn("Two views of the same evidence", template)


if __name__ == "__main__":
    unittest.main()
