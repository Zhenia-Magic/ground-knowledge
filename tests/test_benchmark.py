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

    def test_comparative_recall_scores_baselines_and_reports_losses(self):
        gold = run_benchmark._load("eval/gold.json")
        comp = run_benchmark.comparative_recall(gold)
        self.assertEqual(set(comp), {"covid", "blackholes", "eggs"})
        covid = comp["covid"]["systems"]
        self.assertIn("chatgpt-deep-research", covid)
        # GK surfaces all covid positions in its structured output
        self.assertEqual(covid["Ground Knowledge"]["positions"],
                         set(comp["covid"]["gold"]["positions"]))
        # the honest signal is the LOSS: a baseline surfaces a crux GK's detector misses (biomarkers)
        eggs = comp["eggs"]["systems"]
        baseline_cruxes = eggs["claude-code"]["cruxes"] | eggs["chatgpt-deep-research"]["cruxes"]
        self.assertIn("biomarkers", baseline_cruxes - eggs["Ground Knowledge"]["cruxes"])


if __name__ == "__main__":
    unittest.main()
