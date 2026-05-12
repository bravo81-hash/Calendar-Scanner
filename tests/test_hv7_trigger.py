import unittest

from scanner.hv7_trigger import apply_hv7_trigger_to_settings, detect_hv7_trigger
from scanner.models import ScanSettings


class Hv7TriggerTests(unittest.TestCase):
    def test_trigger_true_when_index_down_two_percent_and_vix_above_threshold(self):
        snapshot = detect_hv7_trigger(
            underlying_price=3920.0,
            underlying_prior_close=4000.0,
            vix_price=27.5,
        )

        self.assertTrue(snapshot.available)
        self.assertTrue(snapshot.triggered)
        self.assertAlmostEqual(snapshot.underlying_change_pct, -2.0)

    def test_trigger_false_when_vix_below_threshold(self):
        snapshot = detect_hv7_trigger(
            underlying_price=3900.0,
            underlying_prior_close=4000.0,
            vix_price=26.9,
        )

        self.assertTrue(snapshot.available)
        self.assertFalse(snapshot.triggered)
        self.assertIn("VIX", snapshot.reason)

    def test_trigger_unavailable_when_prior_close_missing(self):
        snapshot = detect_hv7_trigger(
            underlying_price=3900.0,
            underlying_prior_close=None,
            vix_price=28.0,
        )

        self.assertFalse(snapshot.available)
        self.assertFalse(snapshot.triggered)
        self.assertIn("missing", snapshot.reason.lower())

    def test_apply_available_snapshot_updates_settings(self):
        settings = ScanSettings(strategy="hv7_bwb", hv7_trigger_confirmed=False)
        snapshot = detect_hv7_trigger(3920.0, 4000.0, 28.0)

        updated = apply_hv7_trigger_to_settings(settings, snapshot)

        self.assertTrue(updated.hv7_trigger_confirmed)
        self.assertEqual(updated.hv7_trigger_source, "auto")
        self.assertAlmostEqual(updated.hv7_underlying_change_pct, -2.0)
        self.assertEqual(updated.hv7_vix_price, 28.0)

    def test_unavailable_snapshot_keeps_manual_setting(self):
        settings = ScanSettings(strategy="hv7_bwb", hv7_trigger_confirmed=True)
        snapshot = detect_hv7_trigger(None, 4000.0, 28.0)

        updated = apply_hv7_trigger_to_settings(settings, snapshot)

        self.assertTrue(updated.hv7_trigger_confirmed)
        self.assertEqual(updated.hv7_trigger_source, "manual_fallback")


if __name__ == "__main__":
    unittest.main()
