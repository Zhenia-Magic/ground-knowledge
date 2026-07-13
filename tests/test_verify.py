"""Tests for quote verification: engine/verify.py, its wiring into ingest/pipeline.py's
_carry_meta, engine/merge.py's textDepth/verifiedQuote passthrough, and engine/assess.py's
quote_audit. See SCHEMA.md (textDepth, provenance[field].verifiedQuote) and MECHANISM.md.
"""
import hashlib
import unittest
from unittest import mock

from engine.assess import quote_audit
from engine.merge import merge_delta
from engine.schema import empty_kb
from engine.verify import apply_quote_verification, ground_quote, is_verified_exact, match_quote
from ingest.pipeline import _carry_meta, _prompt_text, build_batch_extract_prompt

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
        # Case changes are alterations, not verbatim quotation.
        self.assertEqual(match_quote(EXACT_QUOTE.upper(), TEXT), "fuzzy")
        self.assertEqual(match_quote("  " + EXACT_QUOTE.replace("\n", "   "), TEXT), "exact")

    def test_near_verbatim_paraphrase_is_fuzzy(self):
        self.assertEqual(match_quote(FUZZY_QUOTE, TEXT), "fuzzy")

    def test_changed_dash_or_curly_quote_is_not_exact(self):
        text = "The interval was 0.14–0.29 and the authors called it “small but consistent.”"
        altered = 'The interval was 0.14-0.29 and the authors called it "small but consistent."'
        self.assertEqual(match_quote(altered, text), "fuzzy")

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

    def test_title_plus_abstract_join_is_never_exact(self):
        text = ("The Huanan market was the early epicenter of the COVID-19 pandemic\n\n"
                "Understanding how severe acute respiratory syndrome coronavirus 2 emerged in "
                "2019 is critical to preventing zoonotic outbreaks.")
        joined = ("The Huanan market was the early epicenter of the COVID-19 pandemic "
                  "Understanding how severe acute respiratory syndrome coronavirus 2 emerged in "
                  "2019 is critical to preventing zoonotic outbreaks.")
        self.assertEqual(ground_quote(joined, text,
                         source_title="The Huanan market was the early epicenter of the COVID-19 pandemic")
                         ["status"], "fuzzy")

    def test_exact_result_has_hashed_audit_and_canonical_sentence(self):
        result = ground_quote(EXACT_QUOTE, TEXT, text_depth="full")
        self.assertEqual(result["method"], "verbatim-sentence-v2")
        self.assertEqual(len(result["textSha256"]), 64)
        self.assertTrue(result["quote"].endswith("sick-quitter effect."))

    def test_editing_wording_after_verification_invalidates_exact_status(self):
        provenance = {"quote": EXACT_QUOTE}
        apply_quote_verification(provenance, TEXT, text_depth="full")
        self.assertTrue(is_verified_exact(provenance))
        provenance["quote"] += " altered"
        self.assertFalse(is_verified_exact(provenance))


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
        position = delta["source"]["provenance"]["position"]
        self.assertEqual(position["verifiedQuote"], "exact")
        self.assertTrue(is_verified_exact(position))
        self.assertEqual(delta["source"]["provenance"]["evidence"]["verifiedQuote"], "missing")

    def test_verifies_each_dependency_edge_against_doc_text(self):
        delta = {"source": {"title": "t", "restsOn": [
            {"ref": "D1", "provenance": {"quote": "We enrolled participants from the Nurses' Health Study."}},
            {"ref": "D2", "provenance": {"quote": FABRICATED_QUOTE}},
            "SRC:another-paper",
        ]}}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        edges = delta["source"]["restsOn"]
        self.assertEqual(edges[0]["provenance"]["verifiedQuote"], "exact")
        self.assertEqual(edges[1]["provenance"]["verifiedQuote"], "missing")

    def test_new_ingestion_does_not_revive_legacy_source_level_dependency_trust(self):
        delta = {"source": {"title": "t", "restsOn": ["D"], "provenance": {
            "restsOn": {"quote": "We enrolled participants from the Nurses' Health Study.",
                        "verifiedQuote": "exact"}}}}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        self.assertNotIn("verifiedQuote", delta["source"]["provenance"]["restsOn"])

    def test_per_edge_verification_survives_merge(self):
        kb = empty_kb("abc", "Does X cause Y?")
        delta = {"source": {"title": "A", "position": "NEW:Yes", "evidence": "Observational",
                            "funding": "Undisclosed", "population": "—", "restsOn": [
            {"ref": "NEW:Nurses Health Study", "provenance": {"quote":
             "We enrolled participants from the Nurses' Health Study."}}
        ]}}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        merge_delta(kb, delta)
        edge = kb["sources"][0]["restsOn"][0]
        self.assertIsInstance(edge, dict)
        self.assertEqual(edge["provenance"]["verifiedQuote"], "exact")

    def test_uploaded_document_path_verifies_edge_before_merge(self):
        import base64
        from ui.server import add_file_op
        delta = {"source": {"title": "Uploaded", "position": "NEW:Yes",
                            "evidence": "Observational", "restsOn": [{
            "ref": "NEW:Nurses Health Study", "provenance": {
                "quote": "We enrolled participants from the Nurses' Health Study."}}]}}
        with mock.patch("ui.server.extract_text", return_value={"kind": "full", "text": TEXT}), \
             mock.patch("ui.server._read", return_value=empty_kb("x", "q")), \
             mock.patch("ui.server.llm.complete", return_value=__import__("json").dumps(delta)), \
             mock.patch("ui.server._merge_list", return_value=[]) as merge:
            add_file_op("x", "paper.txt", base64.b64encode(b"x").decode(), True)
        carried = merge.call_args[0][1][0]
        self.assertEqual(carried["source"]["textDepth"], "full")
        self.assertEqual(carried["source"]["restsOn"][0]["provenance"]["verifiedQuote"], "exact")

    def test_verifies_factor_weight_quotes(self):
        delta = {"source": {"title": "t"}, "factorWeights": [{"factorLabel": "F", "weight": "high",
                                                                "quote": FABRICATED_QUOTE}]}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        self.assertEqual(delta["factorWeights"][0]["verifiedQuote"], "missing")

    def test_no_quote_leaves_verified_quote_unset(self):
        delta = {"source": {"title": "t", "provenance": {"position": {"quote": ""}}}}
        _carry_meta(delta, {"kind": "full", "text": TEXT})
        self.assertNotIn("verifiedQuote", delta["source"]["provenance"]["position"])

    def test_verifies_against_explicit_verify_text_not_full_doc_text(self):
        # Regression: a batch call may truncate what the model actually sees (max_text) well
        # below the full fetched doc. Verification must check the SAME truncated slice, not the
        # fuller doc text -- otherwise a quote the model never saw could "verify" by accident
        # against content sitting past the truncation point.
        doc = {"kind": "full", "text": TEXT}
        truncated = TEXT[:40]  # cuts off before EXACT_QUOTE appears
        delta = {"source": {"title": "t", "provenance": {
            "position": {"quote": EXACT_QUOTE},
        }}}
        _carry_meta(delta, doc, verify_text=truncated)
        self.assertEqual(delta["source"]["provenance"]["position"]["verifiedQuote"], "missing")
        # same quote, no truncation override -> verifies fine against the full doc text
        delta2 = {"source": {"title": "t", "provenance": {
            "position": {"quote": EXACT_QUOTE},
        }}}
        _carry_meta(delta2, doc)
        self.assertEqual(delta2["source"]["provenance"]["position"]["verifiedQuote"], "exact")


class PromptTextTruncationTests(unittest.TestCase):
    def test_default_sends_full_text_untruncated(self):
        doc = {"text": TEXT}
        self.assertEqual(_prompt_text(doc), TEXT)
        self.assertEqual(_prompt_text(doc, None), TEXT)

    def test_explicit_max_text_truncates(self):
        doc = {"text": TEXT}
        self.assertEqual(_prompt_text(doc, 10), TEXT[:10])

    def test_batch_prompt_embeds_full_text_by_default(self):
        kb = empty_kb("abc", "Does X cause Y?")
        prompt = build_batch_extract_prompt(kb, [{"title": "t", "url": "u", "text": TEXT}])
        self.assertIn(TEXT.strip(), prompt)

    def test_batch_prompt_truncates_when_max_text_given(self):
        kb = empty_kb("abc", "Does X cause Y?")
        prompt = build_batch_extract_prompt(kb, [{"title": "t", "url": "u", "text": TEXT}],
                                            max_text=10)
        # unique to the doc text (not boilerplate elsewhere in the template), sits past char 10
        self.assertNotIn("R01-AA000000", prompt)

    def test_prompt_requests_per_edge_dependency_provenance(self):
        from ingest.pipeline import build_extract_prompt
        kb = empty_kb("abc", "Does X cause Y?")
        prompt = build_extract_prompt(kb, {"title": "t", "url": "u", "text": TEXT})
        self.assertIn('"restsOn":[{"ref":', prompt)
        self.assertNotIn('"restsOn":{"quote"', prompt)


class MergeCarriesVerificationTests(unittest.TestCase):
    def test_text_depth_and_verified_quote_survive_merge(self):
        kb = empty_kb("abc", "Does X cause Y?")
        merge_delta(kb, {"source": {
            "title": "A paper", "position": "NEW:Yes", "evidence": "Observational",
            "funding": "Undisclosed", "population": "—", "textDepth": "full",
            "provenance": {"position": {"quote": EXACT_QUOTE, "verifiedQuote": "exact",
                "quoteVerification": {"method": "verbatim-sentence-v2", "status": "exact",
                                      "textSha256": "a" * 64,
                                      "quoteSha256": hashlib.sha256(
                                          " ".join(EXACT_QUOTE.split()).encode()).hexdigest()}}},
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
        if verified == "exact":
            prov["position"]["quoteVerification"] = {
                "method": "verbatim-sentence-v2", "status": "exact", "textSha256": "a" * 64,
                "quoteSha256": hashlib.sha256(b"q").hexdigest()}
        return {"id": sid, "position": "X", "title": sid, "textDepth": depth, "provenance": prov}

    def test_unverified_quote_on_full_text_source_is_flagged(self):
        kb = self._kb_with([self._src("s1", "full", "missing")])
        qa = quote_audit(kb)
        pos = qa["positions"][0]
        self.assertEqual(pos["full"], 1)
        self.assertEqual(pos["unverifiedFull"], 1)
        self.assertEqual(len(qa["flagged"]), 1)
        self.assertEqual(qa["flagged"][0]["id"], "s1")

    def test_missing_quote_on_abstract_source_is_still_flagged_as_not_a_quote(self):
        kb = self._kb_with([self._src("s1", "abstract", "missing")])
        qa = quote_audit(kb)
        pos = qa["positions"][0]
        self.assertEqual(pos["full"], 0)
        self.assertEqual(pos["unverifiedFull"], 0)
        self.assertEqual(len(qa["flagged"]), 1)

    def test_unknown_depth_excluded_from_depth_known_count(self):
        kb = self._kb_with([self._src("s1", "unknown"), self._src("s2", "full", "exact")])
        qa = quote_audit(kb)
        pos = qa["positions"][0]
        self.assertEqual(pos["raw"], 2)
        self.assertEqual(pos["depthKnown"], 1)
        self.assertEqual(pos["full"], 1)
        self.assertEqual(pos["unverifiedFull"], 0)


class ConfidenceAuditTests(unittest.TestCase):
    """confidence_audit is the OTHER quote-quality axis: quote_audit asks 'is this quote real
    (present in the fetched text)'; confidence_audit asks 'is a real quote actually a confident
    basis for the position it's filed under' (prompts/ingest.md's quote-RELEVANCE rule)."""

    def _kb_with(self, sources):
        return {"positions": [{"id": "X", "label": "X", "hue": "#111"}],
                "datasets": [], "factors": [], "sources": sources,
                "vocab": {"evidence": []}}

    def _src(self, sid, conf):
        prov = {"position": {"quote": "q", "extractionConfidence": conf}} if conf is not None else {}
        return {"id": sid, "position": "X", "title": sid, "provenance": prov}

    def test_low_confidence_source_is_counted_and_flagged(self):
        from engine.assess import confidence_audit
        kb = self._kb_with([self._src("s1", 0.3)])
        ca = confidence_audit(kb)
        pos = ca["positions"][0]
        self.assertEqual(pos["classed"], 1)
        self.assertEqual(pos["low"], 1)
        self.assertEqual(ca["flagged"][0]["id"], "s1")

    def test_high_confidence_source_is_not_flagged(self):
        from engine.assess import confidence_audit
        kb = self._kb_with([self._src("s1", 0.9)])
        ca = confidence_audit(kb)
        pos = ca["positions"][0]
        self.assertEqual(pos["classed"], 1)
        self.assertEqual(pos["low"], 0)
        self.assertEqual(ca["flagged"], [])

    def test_missing_confidence_excluded_from_denominator_not_guessed(self):
        from engine.assess import confidence_audit
        kb = self._kb_with([self._src("s1", None), self._src("s2", 0.9)])
        ca = confidence_audit(kb)
        pos = ca["positions"][0]
        self.assertEqual(pos["raw"], 2)
        self.assertEqual(pos["classed"], 1)
        self.assertEqual(pos["low"], 0)

    def test_weak_flag_requires_a_real_count_not_just_share(self):
        from engine.assess import confidence_audit
        # one low-confidence source out of one classed is 100% share, but too small a sample
        # to warrant a case-wide warning -- matches method_audit's "count first" discipline.
        kb = self._kb_with([self._src("s1", 0.2)])
        ca = confidence_audit(kb)
        self.assertFalse(ca["positions"][0]["weak"])

    def test_weak_flag_fires_with_enough_low_confidence_sources(self):
        from engine.assess import confidence_audit
        kb = self._kb_with([self._src("s%d" % i, 0.2) for i in range(3)])
        ca = confidence_audit(kb)
        self.assertTrue(ca["positions"][0]["weak"])


if __name__ == "__main__":
    unittest.main()
