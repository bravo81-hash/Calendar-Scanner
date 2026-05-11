import unittest

from scanner.mock_data import build_mock_chain
from scanner.models import ScanSettings, RegimeSnapshot
from scanner.scoring import rank_candidates
from scanner.regime import apply_regime
from strategies.buddy_atm import build as build_buddy
from strategies.triple_calendar import build as build_triple
from strategies.time_edge import build_main as build_te
from strategies.time_edge import build_no_touch as build_te_nt
from strategies.time_zone import build as build_tz


class StrategyMockTests(unittest.TestCase):
    def setUp(self):
        self.quotes_by_expiry, self.dte_by_expiry, self.spot = build_mock_chain("SPX", 5800.0)
        self.settings = ScanSettings(symbol="SPX")

    def test_buddy_builds_candidates(self):
        candidates, extras = build_buddy("SPX", self.quotes_by_expiry, self.dte_by_expiry, self.settings, None, self.spot)
        self.assertGreater(len(candidates), 0, "buddy_atm should produce candidates with mock chain")
        for c in candidates:
            self.assertEqual(c.strategy, "buddy_atm")
            self.assertEqual(len(c.legs), 2)
            self.assertGreater(c.net_debit, 0)

    def test_buddy_ranking_uses_normalization(self):
        candidates, _ = build_buddy("SPX", self.quotes_by_expiry, self.dte_by_expiry, self.settings, None, self.spot)
        ranked = rank_candidates(candidates, self.settings)
        # All candidates should have a non-negative custom_score and unique rank
        ranks = [c.rank for c in ranked]
        self.assertEqual(sorted(ranks), list(range(1, len(ranks) + 1)))
        for c in ranked:
            self.assertGreaterEqual(c.custom_score, 0.0)

    def test_triple_builds_one_candidate(self):
        candidates, _ = build_triple("SPX", self.quotes_by_expiry, self.dte_by_expiry, self.settings, None, self.spot)
        # Triple needs an expiry near 21 DTE (we have 22) and 28 (we have 28); tolerance 2
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.strategy, "triple_calendar")
        self.assertEqual(len(c.legs), 6)
        self.assertIn("expected_move", c.extras)
        self.assertGreater(c.extras["expected_move"], 0)

    def test_time_edge_main(self):
        candidates, extras = build_te("SPX", self.quotes_by_expiry, self.dte_by_expiry, self.settings, None, self.spot)
        # Mock has 15 and 22 DTE; that's exactly TE main targets
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.strategy, "time_edge")
        self.assertEqual(len(c.legs), 2)

    def test_time_edge_no_touch_requires_calls(self):
        # No-touch needs both rights; remove calls to verify the rejection path.
        puts_only = {
            expiry: [quote for quote in quotes if quote.right == "P"]
            for expiry, quotes in self.quotes_by_expiry.items()
        }
        candidates, _ = build_te_nt("SPX", puts_only, self.dte_by_expiry, self.settings, None, self.spot)
        # Without calls, should reject due to no_call_short
        self.assertEqual(len(candidates), 0)

    def test_time_zone_pcs_plus_cal(self):
        # We're using mock SPX puts; TimeZone is RUT in production but the
        # structure logic is symbol-agnostic.
        settings = ScanSettings(symbol="SPX", tz_pcs_min_credit=0.0, require_positive_credit_pcs=False)
        candidates, _ = build_tz("SPX", self.quotes_by_expiry, self.dte_by_expiry, settings, None, self.spot)
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.strategy, "time_zone")
        self.assertEqual(len(c.legs), 4)
        self.assertIn("pcs_credit", c.extras)

    def test_time_zone_flags_delta_flat_rule_failures(self):
        # Force the long calendar leg delta to dominate so the structure is not
        # acceptably flat relative to theta.
        back_expiry = next(exp for exp, dte in self.dte_by_expiry.items() if dte == 43)
        for quote in self.quotes_by_expiry[back_expiry]:
            quote.delta = -100.0

        settings = ScanSettings(symbol="SPX", tz_pcs_min_credit=0.0, require_positive_credit_pcs=False)
        candidates, extras = build_tz("SPX", self.quotes_by_expiry, self.dte_by_expiry, settings, None, self.spot)

        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0].extras["delta_flat_pass"])
        self.assertGreater(candidates[0].extras["delta_flat_ratio"], 0.10)
        self.assertTrue(any("Delta-flat rule failed" in warning for warning in extras["warnings"]))

    def test_regime_hard_skip_te_backwardation(self):
        candidates, _ = build_te("SPX", self.quotes_by_expiry, self.dte_by_expiry, self.settings, None, self.spot)
        regime = RegimeSnapshot(term_state="BACKWARDATION")
        apply_regime(candidates, regime)
        self.assertEqual(candidates[0].regime_score, 0.0)
        self.assertTrue(candidates[0].regime_skip)

    def test_regime_soft_demote_low_iv_rank(self):
        candidates, _ = build_te("SPX", self.quotes_by_expiry, self.dte_by_expiry, self.settings, None, self.spot)
        regime = RegimeSnapshot(iv_rank=20, stfs_score_time_edge=50)
        apply_regime(candidates, regime)
        # 0.6 (iv too low) * 1.0 (neutral stfs midpoint = 1.0) = 0.6
        self.assertAlmostEqual(candidates[0].regime_score, 0.6, places=2)
        self.assertIn("VERTICAL", candidates[0].regime_flags[0])

    def test_regime_neutral_when_no_snapshot(self):
        candidates, _ = build_te("SPX", self.quotes_by_expiry, self.dte_by_expiry, self.settings, None, self.spot)
        apply_regime(candidates, None)
        self.assertEqual(candidates[0].regime_score, 1.0)


if __name__ == "__main__":
    unittest.main()
