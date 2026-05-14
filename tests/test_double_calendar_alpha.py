import unittest
from datetime import date, timedelta

from scanner.mock_data import build_mock_chain
from scanner.models import ScanSettings
from scanner.vix_regime import classify_vix_regime
from strategies.double_calendar_alpha import build


class DoubleCalendarAlphaTests(unittest.TestCase):
    def test_builds_standard_double_calendar_with_7_day_gap(self):
        quotes_by_expiry, dte_by_expiry, spot = build_mock_chain("SPX", 5800.0)
        settings = ScanSettings(symbol="SPX", strategy="double_calendar_alpha")
        settings.double_cal_strike_offset = 100.0

        candidates, extras = build("SPX", quotes_by_expiry, dte_by_expiry, settings, None, spot)

        self.assertEqual(extras["mode"], "LONG_VEGA")
        self.assertGreater(len(candidates), 0)
        candidate = candidates[0]
        self.assertEqual(candidate.strategy, "double_calendar_alpha")
        self.assertEqual(len(candidate.legs), 4)
        self.assertEqual(candidate.back_dte - candidate.front_dte, 7)
        self.assertEqual(candidate.extras["put_strike"], 5700.0)
        self.assertEqual(candidate.extras["call_strike"], 5900.0)

    def test_high_vix_mode_selects_wednesday_friday_same_week(self):
        today = date.today()
        days_to_wed = (2 - today.weekday()) % 7
        if days_to_wed == 0:
            days_to_wed = 7
        wed_dte = days_to_wed
        fri_dte = wed_dte + 2
        quotes_by_expiry, _, spot = build_mock_chain("SPX", 5800.0)
        dte_by_expiry = {}
        selected_quotes = {}
        for dte in (wed_dte, fri_dte):
            expiry = (today + timedelta(days=dte)).strftime("%Y%m%d")
            source_expiry = next(iter(quotes_by_expiry))
            selected_quotes[expiry] = [
                type(q)(
                    q.symbol, expiry, q.strike, q.right, q.bid, q.ask, q.mid,
                    q.delta, q.theta, q.vega, q.gamma, q.implied_vol,
                )
                for q in quotes_by_expiry[source_expiry]
            ]
            dte_by_expiry[expiry] = dte

        settings = ScanSettings(symbol="SPX", strategy="double_calendar_alpha")
        settings.vix_price = 31.0

        candidates, extras = build("SPX", selected_quotes, dte_by_expiry, settings, None, spot)

        self.assertEqual(classify_vix_regime(settings.vix_price).structure_mode, "NEGATIVE_VEGA")
        self.assertEqual(extras["mode"], "NEGATIVE_VEGA")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].back_dte - candidates[0].front_dte, 2)


if __name__ == "__main__":
    unittest.main()
