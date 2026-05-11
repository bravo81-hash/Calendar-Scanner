import unittest

from scanner.models import ScanSettings
from scanner.presets import apply_scoring_preset, scoring_preset_for_strategy


class ScoringPresetTests(unittest.TestCase):
    def test_buddy_preset_matches_existing_default_weights(self):
        self.assertEqual(
            scoring_preset_for_strategy("buddy_atm"),
            {
                "w_theta_debit": 50.0,
                "w_range_debit": 20.0,
                "w_days_to_target": 20.0,
                "w_vega_debit": 0.0,
                "w_spread_penalty": 10.0,
            },
        )

    def test_time_zone_preset_weights_liquidity_more_than_buddy(self):
        buddy = scoring_preset_for_strategy("buddy_atm")
        time_zone = scoring_preset_for_strategy("time_zone")

        self.assertGreater(time_zone["w_spread_penalty"], buddy["w_spread_penalty"])

    def test_apply_scoring_preset_returns_updated_settings(self):
        settings = ScanSettings(strategy="time_edge", w_theta_debit=1.0)

        updated = apply_scoring_preset(settings, "time_edge")

        self.assertEqual(updated.strategy, "time_edge")
        self.assertEqual(updated.w_theta_debit, scoring_preset_for_strategy("time_edge")["w_theta_debit"])


if __name__ == "__main__":
    unittest.main()
