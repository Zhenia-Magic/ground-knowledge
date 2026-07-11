import json
import os
import unittest

from eval import run_benchmark


ROOT = os.path.dirname(os.path.dirname(__file__))


class BenchmarkContractTests(unittest.TestCase):
    def test_fabricated_unverified_roots_add_zero_confirmed_neff(self):
        with open(os.path.join(ROOT, "cases", "eggs.kb.json"), encoding="utf-8") as f:
            kb = json.load(f)
        _, before, _, after_fabricated, verdict = run_benchmark.adversarial_invariance(kb)
        self.assertEqual(after_fabricated, before)
        self.assertEqual(verdict, "PASS")

    def test_live_baseline_files_and_hashes_are_complete(self):
        manifests, issues = run_benchmark.baseline_status()
        self.assertEqual(issues, [])
        self.assertEqual(set(manifests), {"chatgpt-deep-research", "claude-code"})


if __name__ == "__main__":
    unittest.main()
