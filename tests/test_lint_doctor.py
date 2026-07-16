"""Tests for the bring-your-own-agent guardrails: `cli.py lint`, `cli.py doctor`, and the
clean (non-raising) rejection an agent sees when `add` gets a malformed delta."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli
from engine.schema import empty_kb


def _run(fn, **kwargs):
    """Call a cli command with a namespace, capture stdout, return (output, exit_code).

    exit_code is 0 when the command returns normally, or the SystemExit code otherwise."""
    buf = io.StringIO()
    code = 0
    with redirect_stdout(buf):
        try:
            fn(SimpleNamespace(**kwargs))
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return buf.getvalue(), code


GOOD_DELTA = {
    "source": {
        "title": "Sydney Diet-Heart re-analysis", "relevant": True, "evidence": "RCT",
        "funding": "Government/public", "population": "human", "position": "increases-risk",
        "provenance": {"increases-risk": {
            "quote": "substituting linoleic acid increased mortality",
            "verifiedQuote": "exact", "extractionConfidence": 0.9}},
        "restsOn": [{"ref": "NEW:Sydney Diet-Heart", "datasetKind": "dataset",
                     "provenance": {"quote": "the Sydney Diet-Heart Study",
                                    "extractionConfidence": 0.8}}],
    }
}

BAD_DELTA = {
    "source": {
        "title": "x", "evidence": "RCT", "funding": "Government/public",
        "population": "human", "position": "p",
        "restsOn": [{"ref": "ds:a", "datasetKind": "spreadsheet",
                     "admission": {"status": "confirmed"}}],
    }
}


def _healthy_kb():
    kb = empty_kb("t", "Does saturated fat increase cardiovascular risk?")
    kb["positions"] = [{"id": "pos_up", "label": "Increases risk", "hue": "#2E8B6F"},
                       {"id": "pos_none", "label": "No clear effect", "hue": "#B4656F"}]
    kb["datasets"] = [{"id": "ds_sydney", "label": "Sydney Diet-Heart",
                       "confirmation": {"status": "confirmed", "method": "curator",
                                        "by": "Evgeniia", "ts": "2026-01-01T00:00:00Z"}}]
    kb["sources"] = [
        {"id": "s1", "title": "Sydney trial", "evidence": "RCT", "funding": "Government/public",
         "population": "human", "position": "pos_up",
         "restsOn": [{"ref": "ds_sydney"}]},
        {"id": "s2", "title": "Null cohort", "evidence": "Observational",
         "funding": "Academic/institutional", "population": "human", "position": "pos_none",
         "restsOn": []},
    ]
    return kb


class LintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _path(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def test_a_well_formed_delta_passes_and_flags_ignored_trust_fields(self):
        out, code = _run(cli.cmd_lint, path=self._path("good.json", GOOD_DELTA))
        self.assertEqual(code, 0)
        self.assertIn("well-formed", out)
        # verifiedQuote is not an error, but lint must warn it will be dropped.
        self.assertIn("note:", out)
        self.assertIn("verifiedQuote", out)

    def test_a_malformed_delta_fails_with_numbered_errors(self):
        out, code = _run(cli.cmd_lint, path=self._path("bad.json", BAD_DELTA))
        self.assertEqual(code, 1)
        self.assertIn("datasetKind", out)
        self.assertIn("admission", out)
        self.assertIn("1.", out)  # numbered

    def test_a_batch_with_one_bad_delta_fails(self):
        out, code = _run(cli.cmd_lint, path=self._path("batch.json", [GOOD_DELTA, BAD_DELTA]))
        self.assertEqual(code, 1)
        self.assertIn("delta[1]", out)

    def test_lint_routes_a_kb_to_the_schema_validator(self):
        out, code = _run(cli.cmd_lint, path=self._path("kb.json", _healthy_kb()))
        self.assertEqual(code, 0)
        self.assertIn("valid KB", out)

    def test_lint_fails_on_a_kb_with_a_broken_cross_reference(self):
        kb = _healthy_kb()
        kb["sources"][0]["position"] = "pos_does_not_exist"
        out, code = _run(cli.cmd_lint, path=self._path("brokenkb.json", kb))
        self.assertEqual(code, 1)
        self.assertIn("unknown position", out)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _path(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def test_healthy_kb_reports_healthy_and_exits_zero(self):
        out, code = _run(cli.cmd_doctor, kb=self._path("kb.json", _healthy_kb()))
        self.assertEqual(code, 0)
        self.assertIn("HEALTHY", out)

    def test_proposed_base_and_empty_position_warn_but_do_not_fail(self):
        kb = _healthy_kb()
        kb["positions"].append({"id": "pos_empty", "label": "It depends", "hue": "#7A6FB4"})  # no source
        kb["datasets"].append({"id": "ds_prop", "label": "Unconfirmed cohort"})  # no confirmation
        kb["sources"][1]["restsOn"] = [{"ref": "ds_prop"}]  # used, so not also an orphan
        out, code = _run(cli.cmd_doctor, kb=self._path("kb.json", kb))
        self.assertEqual(code, 0)  # warnings never hard-fail
        self.assertIn("still proposed", out)
        self.assertIn("no source yet", out)
        self.assertIn("warning", out)

    def test_broken_structure_reports_unhealthy_and_exits_one(self):
        kb = _healthy_kb()
        kb["sources"][0]["position"] = "pos_does_not_exist"
        out, code = _run(cli.cmd_doctor, kb=self._path("kb.json", kb))
        self.assertEqual(code, 1)
        self.assertIn("UNHEALTHY", out)


class AddRejectionTests(unittest.TestCase):
    def test_add_rejects_a_malformed_delta_cleanly_without_mutating_the_kb(self):
        tmp = tempfile.mkdtemp()
        kb_path = os.path.join(tmp, "kb.json")
        with open(kb_path, "w", encoding="utf-8") as f:
            json.dump(empty_kb("t", "Does X cause Y?"), f)
        delta_path = os.path.join(tmp, "bad.json")
        with open(delta_path, "w", encoding="utf-8") as f:
            json.dump(BAD_DELTA, f)
        # cmd_add must NOT raise a traceback; it prints a clean rejection.
        out, code = _run(cli.cmd_add, kb=kb_path, delta=delta_path, build=False)
        self.assertEqual(code, 0)
        self.assertIn("rejected", out.lower())
        with open(kb_path, encoding="utf-8") as f:
            after = json.load(f)
        self.assertEqual(after["meta"]["version"], 0)  # unchanged
        self.assertEqual(after["sources"], [])


if __name__ == "__main__":
    unittest.main()
