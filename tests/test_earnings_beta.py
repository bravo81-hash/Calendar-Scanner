import unittest

from scanner.earnings_beta import calculate_earnings_edge


class EarningsBetaTests(unittest.TestCase):
    def test_calculates_overpriced_premium_edge(self):
        result = calculate_earnings_edge(market_implied_move=12.5, historical_average_move=8.0)

        self.assertAlmostEqual(result.edge, 4.5)
        self.assertAlmostEqual(result.overpriced_pct, 36.0)
        self.assertEqual(result.classification, "HEAVILY_OVERPRICED")

    def test_adjusts_historical_move_for_iv_crush_factor(self):
        result = calculate_earnings_edge(
            market_implied_move=10.0,
            historical_average_move=8.0,
            iv_crush_factor_pct=25.0,
        )

        self.assertAlmostEqual(result.adjusted_historical_move, 6.0)
        self.assertAlmostEqual(result.overpriced_pct, 40.0)


if __name__ == "__main__":
    unittest.main()
