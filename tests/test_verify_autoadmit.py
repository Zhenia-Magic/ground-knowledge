"""A verified exact dependency quote that names a real dataset should auto-admit that root on the
LOCAL verify path (the CLI's own fetch is trusted), without a separate curator step — while the
keyless/portal path (which does not record fetched depth) keeps the base proposed. Plus the
label-identity matcher must tolerate a parenthetical acronym without matching generic prose.
See engine/verify.py (verify_kb set_text_depth) and engine/roots.py (_quote_identifies_dataset).
"""
import copy
import unittest

from engine import roots
from engine.assess import independence
from engine.verify import verify_kb

TEXT = ("We analysed egg intake in the Framingham Heart Study cohort. "
        "Egg intake was not associated with coronary heart disease in the Framingham Heart Study.")


def _kb():
    return {
        "positions": [{"id": "p", "label": "No effect", "hue": "#332288"}],
        "datasets": [{"id": "ds_fram", "label": "Framingham Heart Study"}],
        "sources": [{
            "id": "s1", "title": "T", "url": "http://x", "position": "p",
            "evidence": "Observational", "textDepth": "unknown",
            "restsOn": [{"ref": "ds_fram", "provenance": {
                "quote": "We analysed egg intake in the Framingham Heart Study cohort."}}],
            "provenance": {"position": {
                "quote": "Egg intake was not associated with coronary heart disease in the "
                         "Framingham Heart Study."}},
        }],
        "factors": [],
    }


def _neff(kb):
    return {r["label"]: r["nEff"] for r in independence(kb)}


class LabelIdentityTests(unittest.TestCase):
    def _id(self, label, quote):
        return roots._quote_identifies_dataset({"datasets": [{"id": "d", "label": label}]}, "d", quote)

    def test_parenthetical_acronym_label_matches_full_name_in_quote(self):
        self.assertTrue(self._id("Japan Public Health Center-based prospective study (JPHC)",
                                 "followed under the Japan Public Health Center-based prospective study."))

    def test_parenthetical_acronym_matches_when_quote_uses_only_the_acronym(self):
        self.assertTrue(self._id("The Study (NHANES)", "data came from NHANES survey cycles."))

    def test_stripped_generic_fragment_does_not_match_prose(self):
        # "the cohort (study)" must not identify via the generic fragment "the cohort".
        self.assertFalse(self._id("the cohort (study)", "we used the cohort for analysis"))
        self.assertFalse(self._id("The Study (NHANES)", "in the study we then measured"))


class LocalAutoAdmitTests(unittest.TestCase):
    def test_local_verify_records_depth_and_auto_admits_named_root(self):
        kb = _kb()
        verify_kb(kb, lambda _u: {"text": TEXT, "kind": "abstract"}, set_text_depth=True)
        self.assertEqual(kb["sources"][0]["textDepth"], "abstract")
        self.assertEqual(_neff(kb)["No effect"], 1.0)

    def test_keyless_verify_leaves_depth_unknown_and_base_proposed(self):
        # The portal path passes a plain-text fetcher and the default set_text_depth=False, so a
        # keyless contribution's base stays proposed (worth zero) even though its quote is grounded.
        kb = _kb()
        verify_kb(kb, lambda _u: TEXT)
        self.assertEqual(kb["sources"][0]["textDepth"], "unknown")
        self.assertEqual(_neff(kb)["No effect"], 0.0)


if __name__ == "__main__":
    unittest.main()
