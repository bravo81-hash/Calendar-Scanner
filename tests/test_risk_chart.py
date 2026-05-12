import unittest

from scanner.mock_data import build_mock_chain
from scanner.models import ScanSettings
from scanner.risk_chart import (
    bs_greeks,
    bs_price,
    candidate_risk_frame,
    implied_vol_from_price,
)
from strategies.time_edge import build_main as build_te


class RiskChartTests(unittest.TestCase):
    def test_bs_call_put_parity_rough(self):
        # Call - Put ~ S * e^(-qT) - K * e^(-rT)  for European; check sign behaviour
        S, K, T, sigma = 100.0, 100.0, 0.25, 0.20
        c = bs_price(S, K, T, sigma, "C")
        p = bs_price(S, K, T, sigma, "P")
        # Both prices positive
        self.assertGreater(c, 0)
        self.assertGreater(p, 0)
        # ATM-ish: call ≈ put for r=q (we use r=0.045, q=0.013 so slight asymmetry expected)
        self.assertAlmostEqual(c - p, 100 * (1 - 1.0) + 0, delta=2.5)

    def test_bs_greeks_put_delta_negative(self):
        greeks = bs_greeks(100.0, 100.0, 0.25, 0.20, "P")
        self.assertLess(greeks["delta"], 0.0)
        # Theta negative for both calls and puts (long option)
        self.assertLess(greeks["theta"], 0.0)
        # Vega and gamma positive
        self.assertGreater(greeks["vega"], 0.0)
        self.assertGreater(greeks["gamma"], 0.0)

    def test_iv_bisection_recovers(self):
        S, K, T, sigma = 100.0, 95.0, 0.30, 0.25
        target_price = bs_price(S, K, T, sigma, "P")
        recovered = implied_vol_from_price(S, K, T, target_price, "P")
        self.assertAlmostEqual(recovered, sigma, places=3)

    def test_candidate_risk_frame_renders(self):
        quotes_by_expiry, dte_by_expiry, spot = build_mock_chain("SPX", 5800.0)
        settings = ScanSettings(symbol="SPX")
        candidates, _ = build_te("SPX", quotes_by_expiry, dte_by_expiry, settings, None, spot)
        self.assertEqual(len(candidates), 1)
        frame = candidate_risk_frame(candidates[0], spot_price=spot, price_points=31, projection_count=3)
        self.assertFalse(frame.empty)
        self.assertIn("pnl", frame.columns)
        self.assertIn("delta", frame.columns)
        # At entry (T+0) at spot, pnl should be ~ 0 by construction (mark = entry mark)
        atm_row = frame[(frame["projection_day"] == 0)].iloc[(len(frame[(frame["projection_day"] == 0)]) // 2)]
        self.assertAlmostEqual(atm_row["pnl"], 0.0, delta=20.0)


if __name__ == "__main__":
    unittest.main()
