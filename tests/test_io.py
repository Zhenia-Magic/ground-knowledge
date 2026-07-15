import json
import os
import stat
import tempfile
import unittest

from engine.io import atomic_write_json, atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def test_text_replaces_complete_file_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "artifact.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("old trailing content")
            os.chmod(path, 0o640)
            atomic_write_text(path, "new")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "new")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)

    def test_json_write_is_complete_and_has_final_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "nested", "artifact.json")
            atomic_write_json(path, {"title": "Evidence ✓"})
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(json.loads(text), {"title": "Evidence ✓"})


if __name__ == "__main__":
    unittest.main()
