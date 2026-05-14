import unittest

from scanner.trade_management import evaluate_position_management, transformer_plan


class TradeManagementTests(unittest.TestCase):
    def test_flags_profit_target_time_stop_and_strike_touch(self):
        result = evaluate_position_management(
            entry_debit=10.0,
            current_value=7.5,
            front_dte=2,
            underlying_price=5900.0,
            put_short_strike=5700.0,
            call_short_strike=5900.0,
        )

        self.assertTrue(result.profit_target_hit)
        self.assertTrue(result.time_stop_hit)
        self.assertTrue(result.stop_loss_hit)
        self.assertIn("profit", " ".join(result.alerts).lower())

    def test_transformer_plan_builds_front_month_wings_from_calendar_profit(self):
        plan = transformer_plan(
            put_short_strike=5700.0,
            call_short_strike=5900.0,
            put_wing_strike=5650.0,
            call_wing_strike=5950.0,
            back_put_long_bid=14.0,
            back_call_long_bid=15.0,
            front_put_wing_ask=3.0,
            front_call_wing_ask=3.5,
            quantity=2,
        )

        self.assertGreater(plan.net_credit, 0)
        self.assertTrue(plan.risk_funded)
        self.assertEqual(len(plan.legs), 4)
        self.assertEqual(plan.legs[0]["action"], "SELL_TO_CLOSE")


if __name__ == "__main__":
    unittest.main()
