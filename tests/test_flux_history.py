import tempfile
import unittest

from scanner.flux_history import load_flux_history, save_flux_snapshot


class FluxHistoryTests(unittest.TestCase):
    def test_saves_and_loads_recent_flux_ratio_snapshots(self):
        with tempfile.NamedTemporaryFile() as tmp:
            save_flux_snapshot(
                symbol="SPX",
                front_expiry="20260601",
                back_expiry="20260608",
                front_dte=10,
                back_dte=17,
                front_iv=0.19,
                back_iv=0.16,
                iv_ratio=1.1875,
                db_path=tmp.name,
            )

            rows = load_flux_history("SPX", "20260601", "20260608", db_path=tmp.name)

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["iv_ratio"], 1.1875)
        self.assertEqual(rows[0]["front_dte"], 10)


if __name__ == "__main__":
    unittest.main()
