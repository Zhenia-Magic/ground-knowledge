"""Tests for quote verification: engine/verify.py, its wiring into ingest/pipeline.py's
_carry_meta, engine/merge.py's textDepth/verifiedQuote passthrough, and engine/assess.py's
quote_audit. See SCHEMA.md (textDepth, provenance[field].verifiedQuote) and MECHANISM.md.
"""
import unittest

from engine.assess import quote_audit
from engine.merge import merge_delta
from engine.schema import empty_kb
from engine.verify import match_quote
from ingest.pipeline import _carry_meta

TEXT = """Title of Paper

Abstract: This cohort study of 12,000 adults found that moderate alcohol consumption was
associated with a 20% lower risk of cardiovascular events after adjustment for age and sex.

--- full text ---
Methods: We enrolled participants from the Nurses' Health Study.
Results: Moderate drinkers had a hazard ratio of 0.80 (95% CI 0.72-0.89) for coronary heart
disease compared to abstainers, an association that weakened after adjusting for the
sick-quitter effect.
Funding / disclosures: This work was supported by NIH grant R01-AA000000.
"""

EXACT_QUOTE = ("Moderate drinkers had a hazard ratio of 0.80 (95% CI 0.72-0.89) for coronary "
               "heart\ndisease compared to abstainers")
FUZZY_QUOTE = ("drinkers had a hazard ratio near 0.80 (CI 0.72 to 0.89) for coronary heart "
               "disease vs abstainers")
FABRICATED_QUOTE = "the study found that heavy drinking triples the risk of stroke in young women"


class MatchQuoteTests(unittest.TestCase):
    def test_exact_substring_after_normalization(self):
        self.assertEqual(match_quote(EXACT_QUOTE, TEXT), "exact")
        self.assertEqual(match_quote(EXACT_QUOTE.upper(), TEXT), "exact")
        self.assertEqual(match_quote("  " + EXACT_QUOTE.replace("\n", "   "), TEXT), "exact")

    def test_near_verbatim_paraphrase_is_fuzzy(self):
        self.assertEqual(match_quote(FUZZY_QUOTE, TEXT), "fuzzy")

    def test_fabricated_quote_is_missing(self):
        self.assertEqual(match_quote(FABRICATED_QUOTE, TEXT), "missing")

    def test_unrelated_short_quote_not_falsely_matched(self):
        # regression: unfiltered small matching blocks between an unrelated quote and a large
        # repetitive-vocabulary text can spuriously sum to a high ratio.
        repetitive = " ".join(["the study cohort participants were followed for a decade"] * 200)
        self.assertEqual(match_quote(FABRICATED_QUOTE, repetitive), "missing")

    def test_too_short_quote_is_missing_even_if_present(self):
        self.assertEqual(match_quote("risk", TEXT), "missing")

    def test_empty_quote_or_text_is_missing(self):
        self.assertEqual(match_quote("", TEXT), "missing")
        self.assertEqual(match_quote(EXACT_QUOTE, ""), "missing")


class CarryMetaVerificationTests(unittest.TestCase):
    def test_sets_text_depth_from_doc_kind(self):
        delta = {"source": {"title": "t"}}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        self.assertEqual(delta["source"]["textDepth"], "full")

    def test_defaults_text_depth_unknown_when_doc_has_no_kind(self):
        delta = {"source": {"title": "t"}}
        _carry_meta(delta, {"text": TEXT})
        self.assertEqual(delta["source"]["textDepth"], "unknown")

    def test_verifies_source_provenance_quotes_against_doc_text(self):
        delta = {"source": {"title": "t", "provenance": {
            "position": {"quote": EXACT_QUOTE, "extractionConfidence": "high"},
            "evidence": {"quote": FABRICATED_QUOTE, "extractionConfidence": "high"},
        }}}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        self.assertEqual(delta["source"]["provenance"]["position"]["verifiedQuote"], "exact")
        self.assertEqual(delta["source"]["provenance"]["evidence"]["verifiedQuote"], "missing")

    def test_verifies_factor_weight_quotes(self):
        delta = {"source": {"title": "t"}, "factorWeights": [{"factorLabel": "F", "weight": "high",
                                                                "quote": FABRICATED_QUOTE}]}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        self.assertEqual(delta["factorWeights"][0]["verifiedQuote"], "missing")

    def test_no_quote_leaves_verified_quote_unset(self):
        delta = {"source": {"title": "t", "provenance": {"position": {"quote": ""}}}}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        self.assertNotIn("verifiedQuote", delta["source"]["provenance"]["position"])


class MergeCarriesVerificationTests(unittest.TestCase):
    def test_text_depth_and_verified_quote_survive_merge(self):
        kb = empty_kb("abc", "Does X cause Y?")
        merge_delta(kb, {"source": {
            "title": "A paper", "position": "NEW:Yes", "evidence": "Observational",
            "funding": "Undisclosed", "population": "—", "textDepth": "full",
            "provenance": {"position": {"quote": EXACT_QUOTE, "verifiedQuote": "exact"}},
        }, "factorWeights": [{"factorLabel": "F", "weight": "high",
                               "quote": FABRICATED_QUOTE, "verifiedQuote": "missing"}]})
        src = kb["sources"][0]
        self.assertEqual(src["textDepth"], "full")
        self.assertEqual(src["provenance"]["position"]["verifiedQuote"], "exact")
        self.assertEqual(kb["factors"][0]["provenance"][0]["verifiedQuote"], "missing")

    def test_missing_text_depth_defaults_unknown(self):
        kb = empty_kb("abc", "Does X cause Y?")
        merge_delta(kb, {"source": {
            "title": "A paper", "position": "NEW:Yes", "evidence": "Observational",
            "funding": "Undisclosed", "population": "—",
        }, "factorWeights": []})
        self.assertEqual(kb["sources"][0]["textDepth"], "unknown")


class QuoteAuditTests(unittest.TestCase):
    def _kb_with(self, sources):
        return {"positions": [{"id": "X", "label": "X", "hue": "#111"}],
                "datasets": [], "factors": [], "sources": sources,
                "vocab": {"evidence": []}}

    def _src(self, sid, depth, verified=None):
        prov = {"position": {"quote": "q", "verifiedQuote": verified}} if verified else {}
        return {"id": sid, "position": "X", "title": sid, "textDepth": depth, "provenance": prov}

    def test_unverified_quote_on_full_text_source_is_flagged(self):
        kb = self._kb_with([self._src("s1", "full", "missing")])
        qa = quote_audit(kb)
        pos = qa["positions"][0]
        self.assertEqual(pos["full"], 1)
        self.assertEqual(pos["unverifiedFull"], 1)
        self.assertEqual(len(qa["flagged"]), 1)
        self.assertEqual(qa["flagged"][0]["id"], "s1")

    def test_missing_quote_on_abstract_source_is_not_flagged(self):
        kb = self._kb_with([self._src("s1", "abstract", "missing")])
        qa = quote_audit(kb)
        pos = qa["positions"][0]
        self.assertEqual(pos["full"], 0)
        self.assertEqual(pos["unverifiedFull"], 0)
        self.assertEqual(qa["flagged"], [])

    def test_unknown_depth_excluded_from_depth_known_count(self):
        kb = self._kb_with([self._src("s1", "unknown"), self._src("s2", "full", "exact")])
        qa = quote_audit(kb)
        pos = qa["positions"][0]
        self.assertEqual(pos["raw"], 2)
        self.assertEqual(pos["depthKnown"], 1)
        self.assertEqual(pos["full"], 1)
        self.assertEqual(pos["unverifiedFull"], 0)


if __name__ == "__main__":
    unittest.main()
