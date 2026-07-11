import json
import os
import unittest

from engine.migrate import migrate_kb, validation_errors
from engine.schema import empty_kb


class SchemaMigrationTests(unittest.TestCase):
    def test_v1_migrates_additively_without_inventing_trust(self):
        old = {"meta": {"id": "x", "question": "q", "version": 1},
               "positions": [{"id": "p", "label": "Yes", "hue": "#000"}],
               "datasets": [{"id": "d", "label": "Cohort"}],
               "factors": [],
               "sources": [{"id": "s", "title": "Paper", "position": "p", "evidence": "Observational",
                            "funding": "Undisclosed", "population": "Adults", "restsOn": ["d"]}],
               "vocab": {"evidence": [], "population": [], "funding": []}, "log": []}
        kb, changes = migrate_kb(old)
        self.assertEqual(kb["meta"]["schemaVersion"], 2)
        self.assertEqual(kb["sources"][0]["textDepth"], "unknown")
        self.assertNotIn("confirmed", kb["datasets"][0])
        self.assertTrue(changes)
        self.assertEqual(validation_errors(kb), [])
        self.assertNotIn("schemaVersion", old["meta"])        # copy by default

    def test_cross_reference_validation(self):
        kb = empty_kb("x", "q")
        kb["sources"] = [{"id": "s", "title": "t", "position": "missing", "evidence": "Observational",
                          "funding": "Undisclosed", "population": "Adults", "restsOn": ["missing-ds"],
                          "provenance": {}, "textDepth": "unknown"}]
        errors = validation_errors(kb)
        self.assertTrue(any("unknown position" in e for e in errors))
        self.assertTrue(any("unknown dataset" in e for e in errors))

    def test_machine_schema_is_valid_json_and_targets_v2(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema", "kb-v2.schema.json")
        with open(path, encoding="utf-8") as f:
            schema = json.load(f)
        self.assertEqual(schema["properties"]["meta"]["properties"]["schemaVersion"]["const"], 2)
        self.assertIn("sources", schema["required"])


if __name__ == "__main__":
    unittest.main()
