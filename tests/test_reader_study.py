import unittest

from eval.reader_study.randomize import assignments


class ReaderStudyRandomizationTests(unittest.TestCase):
    def test_assignment_is_deterministic_and_balanced(self):
        a = assignments(36)
        self.assertEqual(a, assignments(36))
        self.assertEqual(len(a), 108)
        by_case = {}
        by_case_sequence = {}
        for row in a:
            by_case.setdefault(row["case"], {"DR": 0, "DR+GK": 0})[row["condition"]] += 1
            key = (row["case"], row["sequence"])
            by_case_sequence.setdefault(key, {"DR": 0, "DR+GK": 0})[row["condition"]] += 1
        for counts in by_case.values():
            self.assertLessEqual(abs(counts["DR"] - counts["DR+GK"]), 1)
        for counts in by_case_sequence.values():
            self.assertLessEqual(abs(counts["DR"] - counts["DR+GK"]), 1)
