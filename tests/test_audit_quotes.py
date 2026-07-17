import json
import pathlib
import tempfile
import unittest

from engine.verify import apply_quote_verification, is_verified_exact
from scripts.audit_quotes import audit_case, write_markdown_report


class AlternateQuoteSourceAuditTests(unittest.TestCase):
    def test_factor_quote_reaudits_against_recorded_full_text_url(self):
        landing_url = "https://example.test/abstract"
        full_url = "https://example.test/full-text"
        landing_text = "The landing page contains only this position sentence."
        factor_text = "The full paper says this factor changes the conclusion materially."
        position = {"quote": landing_text}
        factor_claim = {
            "source": "s1", "pos": "p1", "weight": "high", "quote": factor_text
        }
        apply_quote_verification(
            position, landing_text, source_title="Paper", text_depth="abstract",
            source_url=landing_url)
        apply_quote_verification(
            factor_claim, factor_text, source_title="Paper", text_depth="full",
            source_url=full_url)
        kb = {
            "meta": {"version": 1},
            "positions": [{"id": "p1", "label": "P1"}],
            "datasets": [],
            "factors": [{"id": "f1", "label": "F1", "weights": {"p1": "high"},
                         "provenance": [factor_claim]}],
            "sources": [{"id": "s1", "title": "Paper", "url": landing_url,
                         "position": "p1", "provenance": {"position": position}}],
            "log": [],
        }
        fetched = {
            landing_url: {"ok": True, "doc": {"text": landing_text, "kind": "abstract",
                                                  "url": landing_url}},
            full_url: {"ok": True, "doc": {"text": factor_text, "kind": "full",
                                               "url": full_url}},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "case.json"
            path.write_text(json.dumps(kb), encoding="utf-8")
            audited, rows = audit_case(path, fetched, None)

        claim = audited["factors"][0]["provenance"][0]
        self.assertTrue(is_verified_exact(claim))
        self.assertEqual(claim["quoteVerification"]["sourceUrl"], full_url)
        factor_row = next(q for q in rows[0]["quotes"] if q["field"] == "factor:f1")
        self.assertEqual(factor_row["status"], "exact")

    def test_markdown_all_excerpt_total_includes_context_sources(self):
        position_quote = {"quote": "The outcome source reports the finding exactly."}
        context_quote = {"quote": "The context source reports a bias finding exactly."}
        apply_quote_verification(position_quote, position_quote["quote"], text_depth="full")
        apply_quote_verification(context_quote, context_quote["quote"], text_depth="full")
        kb = {
            "meta": {"version": 1},
            "positions": [{"id": "p1", "label": "P1"}],
            "datasets": [],
            "factors": [],
            "sources": [{"id": "s1", "title": "Outcome", "position": "p1",
                         "provenance": {"position": position_quote}}],
            "contextSources": [{"id": "c1", "title": "Context",
                                "provenance": {"position": context_quote}}],
            "log": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            case_path = pathlib.Path(directory) / "case.json"
            report_path = pathlib.Path(directory) / "report.md"
            case_path.write_text(json.dumps(kb), encoding="utf-8")
            write_markdown_report([case_path], report_path)
            report = report_path.read_text(encoding="utf-8")
        self.assertIn("Position excerpts: **1 exact of 1**", report)
        self.assertIn("All stored excerpts (position, dependency, and factor): **2 exact of 2**", report)


if __name__ == "__main__":
    unittest.main()
