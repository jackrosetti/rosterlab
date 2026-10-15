import unittest

from rosterlab.distributions import paired_deltas, probability_negative, probability_positive, summarize


class DistributionTests(unittest.TestCase):
    def test_summary_exposes_quantiles_and_tail_means(self):
        summary = summarize(range(1, 101))
        self.assertEqual(summary.count, 100)
        self.assertAlmostEqual(summary.mean, 50.5)
        self.assertAlmostEqual(summary.p50, 50.5)
        self.assertAlmostEqual(summary.cvar10, 5.5)
        self.assertAlmostEqual(summary.cvar90, 95.5)

    def test_paired_counterfactual_preserves_world_alignment(self):
        deltas = paired_deltas((10.0, 40.0, 5.0), (12.0, 35.0, 5.0))
        self.assertEqual(deltas, (2.0, -5.0, 0.0))
        self.assertAlmostEqual(probability_positive(deltas), 1 / 3)
        self.assertAlmostEqual(probability_negative(deltas), 1 / 3)


if __name__ == "__main__":
    unittest.main()
