import unittest

from scanner.vix_regime import classify_vix_regime


class VixRegimeTests(unittest.TestCase):
    def test_classifies_baseline_teens_as_standard_long_vega(self):
        regime = classify_vix_regime(14.5)

        self.assertEqual(regime.name, "BASELINE")
        self.assertEqual(regime.structure_mode, "LONG_VEGA")
        self.assertTrue(regime.primary_alert_ok)

    def test_classifies_high_vix_as_negative_vega_hack(self):
        regime = classify_vix_regime(31.0)

        self.assertEqual(regime.name, "HIGH_VIX")
        self.assertEqual(regime.structure_mode, "NEGATIVE_VEGA")
        self.assertFalse(regime.primary_alert_ok)


if __name__ == "__main__":
    unittest.main()
