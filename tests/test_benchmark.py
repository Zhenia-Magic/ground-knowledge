import json
import os
import unittest

from eval import run_benchmark


ROOT = os.path.dirname(os.path.dirname(__file__))


class BenchmarkContractTests(unittest.TestCase):
    def test_fabricated_unverified_roots_add_zero_confirmed_neff(self):
        with open(os.path.join(ROOT, "cases", "eggs.kb.json"), encoding="utf-8") as f:
            kb = json.load(f)
        adv = run_benchmark.adversarial_invariance(kb)
        self.assertEqual(adv["fabricated"], adv["before"])
        self.assertEqual(adv["cycle"], adv["before"])
        self.assertTrue(adv["cycleFlagged"])
        self.assertEqual(adv["edgeBound"], adv["before"] + 1)
        self.assertGreaterEqual(adv["edgeProvisional"], 1)
        self.assertEqual(adv["knownAlias"], adv["before"])
        self.assertEqual(adv["genericLabel"], adv["before"])
        self.assertEqual(adv["unknownAliasSplit"], adv["before"] + 1)
        self.assertTrue(adv["aliasSplitFlagged"])
        self.assertEqual(adv["verdict"], "PASS")

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
        # Structure recall means visible in the matrix, not promoted to a headline badge.
        eggs = comp["eggs"]["systems"]
        self.assertEqual(eggs["Ground Knowledge"]["cruxes"], set(comp["eggs"]["gold"]["cruxes"]))
        # Wins/losses are still item-level and honest: ChatGPT misses this modeled black-hole factor.
        bh = comp["blackholes"]["systems"]
        self.assertIn("safety argument itself",
                      bh["Ground Knowledge"]["cruxes"] - bh["chatgpt-deep-research"]["cruxes"])


if __name__ == "__main__":
    unittest.main()
