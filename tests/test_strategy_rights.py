import unittest

from scanner.models import ScanSettings
from strategies.registry import rights_for


class StrategyRightsTests(unittest.TestCase):
    def test_time_edge_main_requests_puts_only(self):
        settings = ScanSettings(strategy="time_edge")

        self.assertEqual(rights_for("time_edge", settings), ("P",))

    def test_time_edge_no_touch_requests_puts_and_calls(self):
        settings = ScanSettings(strategy="time_edge_no_touch")

        self.assertEqual(rights_for("time_edge_no_touch", settings), ("P", "C"))

    def test_triple_calendar_can_require_full_straddle_rights(self):
        settings = ScanSettings(strategy="triple_calendar", triple_require_full_straddle=True)

        self.assertEqual(rights_for("triple_calendar", settings), ("P", "C"))


if __name__ == "__main__":
    unittest.main()
