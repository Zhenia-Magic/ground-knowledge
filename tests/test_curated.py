"""Tests for the 'curated & maintained' stewardship badge and its paired computed signal.

The badge is a trusted, admin-only label; the paired percentages are earned by the evidence state.
Both must be unforgeable through the public contribute path."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.schema import empty_kb
from engine import curate
from engine.assess import curation_summary
from engine.migrate import validation_errors
from engine.verify import strip_untrusted_verification
from engine.merge import merge_delta


def _kb_with_bases():
    kb = empty_kb("t", "Does X cause Y?")
    kb["positions"] = [{"id": "pos_up", "label": "Increases", "hue": "#2E8B6F"},
                       {"id": "pos_none", "label": "No effect", "hue": "#B4656F"}]
    kb["datasets"] = [
        {"id": "ds_a", "label": "Cohort A",
         "confirmation": {"status": "confirmed", "method": "curator", "by": "E", "ts": "2026-01-01T00:00:00Z"}},
        {"id": "ds_b", "label": "Cohort B"},  # proposed
    ]
    kb["sources"] = [
        {"id": "s1", "title": "A", "evidence": "RCT", "funding": "Government/public",
         "population": "human", "position": "pos_up", "restsOn": [{"ref": "ds_a"}],
         "provenance": {"position": {"quote": "a finding sentence.", "verifiedQuote": "exact"}}},
        {"id": "s2", "title": "B", "evidence": "Observational", "funding": "Academic/institutional",
         "population": "human", "position": "pos_none", "restsOn": [{"ref": "ds_b"}],
         "provenance": {"position": {"quote": "another sentence.", "verifiedQuote": None}}},
    ]
    return kb


class SetCuratedTests(unittest.TestCase):
    def test_marking_writes_an_audit_record_and_bumps_version(self):
        kb = _kb_with_bases()
        v0 = kb["meta"]["version"]
        curate.set_curated(kb, by="Evgeniia", note="flagship")
        rec = kb["meta"]["curated"]
        self.assertEqual(rec["by"], "Evgeniia")
        self.assertEqual(rec["note"], "flagship")
        self.assertTrue(rec["since"])
        self.assertGreater(kb["meta"]["version"], v0)

    def test_marking_requires_a_by_identity(self):
        kb = _kb_with_bases()
        with self.assertRaises(ValueError):
            curate.set_curated(kb, by="  ")

    def test_unmarking_removes_the_record(self):
        kb = _kb_with_bases()
        curate.set_curated(kb, by="E")
        curate.set_curated(kb, curated=False)
        self.assertNotIn("curated", kb["meta"])


class CurationSummaryTests(unittest.TestCase):
    def test_paired_percentages_are_computed_from_evidence_state(self):
        kb = _kb_with_bases()
        cur = curation_summary(kb)
        self.assertEqual(cur["totalBases"], 2)
        self.assertEqual(cur["confirmedBases"], 1)   # ds_a confirmed, ds_b proposed
        self.assertEqual(cur["basesPct"], 50)
        self.assertEqual(cur["totalQuotes"], 2)
        self.assertEqual(cur["verifiedQuotes"], 1)   # only s1's quote is verified
        self.assertEqual(cur["quotesPct"], 50)
        self.assertIsNone(cur["curated"])            # not marked yet

    def test_curated_record_is_echoed_in_the_summary(self):
        kb = _kb_with_bases()
        curate.set_curated(kb, by="E")
        self.assertEqual(curation_summary(kb)["curated"]["by"], "E")

    def test_empty_kb_does_not_divide_by_zero(self):
        cur = curation_summary(empty_kb("t", "q"))
        self.assertEqual(cur["basesPct"], 0)
        self.assertEqual(cur["quotesPct"], 0)

    def test_assess_resolves_the_graph_only_once(self):
        # curation_summary must thread the shared resolve, not trigger a second one — assess()
        # promises "one assess() is one resolve()".
        import engine.assess as A
        with mock.patch("engine.assess._roots.resolve", wraps=A._roots.resolve) as resolve:
            A.assess(_kb_with_bases())
        self.assertEqual(resolve.call_count, 1)


class ValidationTests(unittest.TestCase):
    def test_a_well_formed_curated_record_validates(self):
        kb = _kb_with_bases()
        curate.set_curated(kb, by="E")
        self.assertEqual(validation_errors(kb), [])

    def test_a_malformed_curated_record_is_rejected(self):
        for bad in ({"since": "2026"}, {"by": "  ", "since": "2026"}, {"by": "E"}, "notanobject"):
            kb = _kb_with_bases()
            kb["meta"]["curated"] = bad
            self.assertTrue(validation_errors(kb), "should reject curated={!r}".format(bad))


class ForgeResistanceTests(unittest.TestCase):
    def test_a_delta_carrying_meta_curated_cannot_set_it_through_merge(self):
        kb = empty_kb("t", "Does X cause Y?")
        delta = {"meta": {"curated": {"by": "attacker", "since": "2020"}},
                 "source": {"title": "s", "relevant": True, "evidence": "Observational",
                            "funding": "Undisclosed", "population": "human", "position": "NEW:p",
                            "provenance": {"position": {"quote": "a real sentence.",
                                                        "extractionConfidence": 0.5}}}}
        merge_delta(kb, strip_untrusted_verification(delta))
        self.assertIsNone(kb["meta"].get("curated"))

    def test_strip_drops_client_supplied_meta(self):
        delta = {"meta": {"curated": {"by": "x", "since": "2020"}}, "source": {"title": "s"}}
        strip_untrusted_verification(delta)
        self.assertNotIn("meta", delta)

    def test_strip_untrusted_kb_removes_every_trust_record_a_keyless_push_cannot_assert(self):
        from engine.verify import strip_untrusted_kb
        kb = _kb_with_bases()
        curate.set_curated(kb, by="attacker")
        # forge an edge admission + a verified quote too
        kb["sources"][0]["restsOn"][0] = {"ref": "ds_a", "admission": {
            "status": "confirmed", "method": "curator", "by": "attacker", "ts": "2020"}}
        kb["sources"][0]["provenance"]["position"]["verifiedQuote"] = "exact"
        strip_untrusted_kb(kb)
        self.assertNotIn("curated", kb["meta"])                          # stewardship gone
        self.assertNotIn("confirmation", kb["datasets"][0])              # curator confirm gone
        self.assertNotIn("admission", kb["sources"][0]["restsOn"][0])    # edge admission gone
        self.assertNotIn("verifiedQuote", kb["sources"][0]["provenance"]["position"])
        # and the derived coverage now reflects the honest (proposed) state
        self.assertEqual(curation_summary(kb)["confirmedBases"], 0)


class MarkCuratedCliTests(unittest.TestCase):
    def test_cli_marks_and_reports_the_paired_signal(self):
        import tempfile, json as _json, cli
        tmp = tempfile.mkdtemp()
        kb_path = os.path.join(tmp, "kb.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            _json.dump(_kb_with_bases(), f)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.cmd_mark_curated(SimpleNamespace(kb=kb_path, by="Evgeniia", note=None, off=False))
        out = buf.getvalue()
        self.assertIn("curated & maintained by Evgeniia", out)
        self.assertIn("50% confirmed", out)          # paired computed signal
        with open(kb_path, encoding="utf-8") as f:
            self.assertEqual(_json.load(f)["meta"]["curated"]["by"], "Evgeniia")


if __name__ == "__main__":
    unittest.main()
