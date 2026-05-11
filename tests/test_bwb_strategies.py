import unittest

from scanner.mock_data import build_mock_chain
from scanner.models import ScanSettings
from strategies.registry import REGISTRY, build_for, rights_for, target_pct_for


class BwbStrategyTests(unittest.TestCase):
    def setUp(self):
        self.quotes_by_expiry, self.dte_by_expiry, self.spot = build_mock_chain("SPX", 5800.0)

    def test_new_reference_strategies_are_registered(self):
        self.assertIn("a14_bwb", REGISTRY)
        self.assertIn("hv7_bwb", REGISTRY)
        self.assertIn("fly_diagonal", REGISTRY)
        self.assertEqual(target_pct_for("a14_bwb"), 0.05)
        self.assertEqual(target_pct_for("hv7_bwb"), 0.05)
        self.assertEqual(target_pct_for("fly_diagonal"), 0.10)

    def test_bwb_strategy_rights(self):
        self.assertEqual(rights_for("a14_bwb", ScanSettings(strategy="a14_bwb")), ("P",))
        self.assertEqual(rights_for("hv7_bwb", ScanSettings(strategy="hv7_bwb")), ("P",))
        self.assertEqual(rights_for("fly_diagonal", ScanSettings(strategy="fly_diagonal")), ("P", "C"))

    def test_a14_builds_put_bwb_candidate(self):
        settings = ScanSettings(strategy="a14_bwb", symbol="SPX")
        candidates, extras = build_for("a14_bwb")(
            "SPX", self.quotes_by_expiry, self.dte_by_expiry, settings, None, self.spot
        )

        self.assertEqual(extras["rejection_reasons"], {})
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.strategy, "a14_bwb")
        self.assertEqual([leg.action for leg in candidate.legs], ["BUY", "SELL", "BUY"])
        self.assertEqual([leg.quantity for leg in candidate.legs], [1, 2, 1])
        self.assertTrue(all(leg.quote.right == "P" for leg in candidate.legs))
        self.assertIn("bwb_width_upper", candidate.extras)

    def test_hv7_builds_put_bwb_candidate_with_trigger_warning(self):
        settings = ScanSettings(strategy="hv7_bwb", symbol="SPX", hv7_trigger_confirmed=False)
        candidates, extras = build_for("hv7_bwb")(
            "SPX", self.quotes_by_expiry, self.dte_by_expiry, settings, None, self.spot
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].strategy, "hv7_bwb")
        self.assertTrue(any("HV7 trigger" in warning for warning in extras["warnings"]))
        self.assertEqual(candidates[0].extras["trigger_confirmed"], False)

    def test_fly_diagonal_builds_iron_fly_plus_two_time_spreads(self):
        settings = ScanSettings(strategy="fly_diagonal", symbol="SPX")
        candidates, extras = build_for("fly_diagonal")(
            "SPX", self.quotes_by_expiry, self.dte_by_expiry, settings, None, self.spot
        )

        self.assertEqual(extras["rejection_reasons"], {})
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.strategy, "fly_diagonal")
        self.assertEqual(len(candidate.legs), 8)
        self.assertEqual(
            [(leg.action, leg.quantity, leg.quote.right) for leg in candidate.legs],
            [
                ("BUY", 1, "P"),
                ("SELL", 1, "P"),
                ("SELL", 1, "C"),
                ("BUY", 1, "C"),
                ("SELL", 1, "P"),
                ("BUY", 1, "P"),
                ("SELL", 1, "C"),
                ("BUY", 1, "C"),
            ],
        )
        self.assertEqual(candidate.extras["structure"], "atm_iron_fly_plus_put_call_time_spreads")
        self.assertEqual(candidate.extras["iron_fly_width"], settings.fly_iron_fly_width)
        self.assertGreaterEqual(candidate.position_theta, 0.0)


if __name__ == "__main__":
    unittest.main()
