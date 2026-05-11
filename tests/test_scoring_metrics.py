import math
import unittest

from scanner.scoring import (
    days_to_target_pct,
    expected_move_from_straddle,
    normalize_high_is_good,
    normalize_low_is_good,
    range_debit_ratio,
    theta_debit_ratio,
    vega_debit_ratio,
)


class MetricsTests(unittest.TestCase):
    def test_theta_debit_ratio_basic(self):
        self.assertAlmostEqual(theta_debit_ratio(0.10, 2.00), 0.05)
        self.assertEqual(theta_debit_ratio(0.10, 0), 0.0)
        self.assertEqual(theta_debit_ratio(0.10, -1.0), 0.0)

    def test_days_to_target_pct(self):
        # $2 debit, $0.10/day theta, 10% target => 2 * 0.10 / 0.10 = 2 days
        self.assertAlmostEqual(days_to_target_pct(2.00, 0.10, 0.10), 2.0)
        # zero theta -> infinity
        self.assertTrue(math.isinf(days_to_target_pct(2.0, 0.0, 0.10)))

    def test_range_and_vega(self):
        self.assertAlmostEqual(range_debit_ratio(8.0, 2.0), 4.0)
        self.assertAlmostEqual(vega_debit_ratio(0.20, 2.0), 0.10)

    def test_expected_move_from_straddle(self):
        self.assertAlmostEqual(expected_move_from_straddle(15.0, 12.0), 27.0)
        self.assertAlmostEqual(expected_move_from_straddle(0.0, 0.0), 0.0)

    def test_normalize_high_is_good(self):
        self.assertEqual(normalize_high_is_good([1, 2, 3]), [0.0, 0.5, 1.0])
        # constant column
        self.assertEqual(normalize_high_is_good([5, 5, 5]), [1.0, 1.0, 1.0])
        # empty
        self.assertEqual(normalize_high_is_good([]), [])
        # NaN handling
        result = normalize_high_is_good([float("nan"), 1.0, 2.0])
        self.assertEqual(result[0], 0.0)
        self.assertAlmostEqual(result[1], 0.0)
        self.assertAlmostEqual(result[2], 1.0)

    def test_normalize_low_is_good(self):
        self.assertEqual(normalize_low_is_good([1, 2, 3]), [1.0, 0.5, 0.0])


if __name__ == "__main__":
    unittest.main()
