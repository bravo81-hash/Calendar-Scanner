import unittest

from scanner.flux_metrics import average_iv, classify_flux_signal, iv_ratio
from scanner.models import OptionQuote


class FluxMetricsTests(unittest.TestCase):
    def test_iv_ratio_uses_front_divided_by_back(self):
        front = [
            OptionQuote("SPX", "20260601", 5800, "P", 1, 2, 1.5, -30, implied_vol=0.18),
            OptionQuote("SPX", "20260601", 5900, "C", 1, 2, 1.5, 30, implied_vol=0.20),
        ]
        back = [
            OptionQuote("SPX", "20260608", 5800, "P", 2, 3, 2.5, -30, implied_vol=0.16),
            OptionQuote("SPX", "20260608", 5900, "C", 2, 3, 2.5, 30, implied_vol=0.17),
        ]

        self.assertAlmostEqual(average_iv(front), 0.19)
        self.assertAlmostEqual(iv_ratio(front, back), 0.19 / 0.165)

    def test_classify_flux_signal_flags_ratio_spike(self):
        signal = classify_flux_signal(current_ratio=1.16, previous_ratio=1.10, spike_threshold=0.03)

        self.assertEqual(signal.status, "ENTRY_SIGNAL")
        self.assertGreater(signal.change_pct, 0.03)
        self.assertIn("spike", signal.reason.lower())

    def test_classify_flux_signal_waits_when_ratio_is_flat(self):
        signal = classify_flux_signal(current_ratio=1.11, previous_ratio=1.10, spike_threshold=0.03)

        self.assertEqual(signal.status, "WAIT")


if __name__ == "__main__":
    unittest.main()
