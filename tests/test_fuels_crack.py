import unittest
from datetime import date
from fractions import Fraction as F

from second_order.fuels_crack import (ENGINE_VERSION, barrel, basket_value, crack, crack_history, exact_text,
                                      shown, sign_of)


def days(values):
    return {date.fromisoformat(day): (None if value is None else F(value)) for day, value in values.items()}


class FuelsCrackTests(unittest.TestCase):
    def test_the_synthetic_unit_example(self):  # spec 6.2: not market data
        self.assertEqual(basket_value(F("2.50"), F("3.00")), F(112))
        self.assertEqual(crack(F("2.50"), F("3.00"), F(80)), F(32))

    def test_zero_and_negative_cracks_are_signed(self):
        self.assertEqual(sign_of(crack(F("2.50"), F("3.00"), F(112))), "zero")
        self.assertEqual(sign_of(crack(F("2.50"), F("3.00"), F(115))), "negative")
        self.assertEqual(sign_of(F(1)), "positive")
        self.assertEqual(shown(crack(F("2.50"), F("3.00"), F(115)), 2), "-3.00")

    def test_exact_text(self):
        self.assertEqual([exact_text(F(112)), exact_text(F("112.042")), exact_text(F(-3)), exact_text(F("0.014")),
                          exact_text(F("-0.5"))],
                         ["112", "112.042", "-3", "0.014", "-0.5"])
        with self.assertRaises(ValueError):
            exact_text(F(1, 3))

    def test_the_latest_and_previous_common_dates(self):
        # Diesel has no value on 3 Nov, so the barrel uses 2 Nov and the change compares it with 30 Oct.
        b = barrel({"brent": days({"2026-10-30": "79", "2026-11-02": "80", "2026-11-03": "81"}),
                    "gasoline": days({"2026-10-30": "2.5", "2026-11-02": "2.5", "2026-11-03": "2.6"}),
                    "diesel": days({"2026-10-30": "3", "2026-11-02": "3", "2026-11-03": None})})
        self.assertEqual((b["state"], b["date"], b["previous_date"]), ("computed", "2026-11-02", "2026-10-30"))
        self.assertEqual(b["change"]["brent"]["value"], "1")
        self.assertEqual(b["engine_version"], ENGINE_VERSION)
        self.assertEqual(b["crack"]["sign"], "positive")

    def test_one_common_date_has_no_change(self):
        b = barrel({"brent": days({"2026-11-02": "80"}), "gasoline": days({"2026-11-02": "2.5"}),
                    "diesel": days({"2026-11-02": "3"})})
        self.assertEqual(b["state"], "computed")
        self.assertIsNone(b["change"]); self.assertIsNone(b["previous"]); self.assertIsNone(b["previous_date"])
        self.assertEqual(b["crack"]["shown"], "32.00")

    def test_no_common_date_withholds_everything(self):
        b = barrel({"brent": days({"2026-11-02": "80"}), "gasoline": days({"2026-11-03": "2.5"}),
                    "diesel": days({"2026-11-03": "3"})})
        self.assertEqual(b["state"], "withheld")
        self.assertIsNone(b["basket"]); self.assertIsNone(b["crack"]); self.assertIsNone(b["inputs"])
        self.assertIn("all have a value", b["problem"])

    def test_a_missing_series_withholds_and_is_named(self):
        b = barrel({"brent": days({"2026-11-02": "80"}), "gasoline": None, "diesel": days({"2026-11-02": "3"})})
        self.assertEqual(b["state"], "withheld"); self.assertIn("gasoline", b["problem"])

    def test_rounded_values_never_feed_the_change(self):
        # Basket 112.042 (shown 112.04), then 112.056 (shown 112.06). The exact change 0.014 shows 0.01, not 0.02.
        b = barrel({"brent": days({"2026-11-02": "79.04", "2026-11-03": "80.00"}),
                    "gasoline": days({"2026-11-02": "2.501", "2026-11-03": "2.501"}),
                    "diesel": days({"2026-11-02": "3.001", "2026-11-03": "3.002"})})
        self.assertEqual((b["basket"]["shown"], b["previous"]["brent"]["shown"]), ("112.06", "79.04"))
        self.assertEqual((b["change"]["basket"]["value"], b["change"]["basket"]["shown"]), ("0.014", "0.01"))
        self.assertEqual(b["change"]["brent"]["shown"], "0.96")

    def test_crack_history_uses_common_dates_only(self):
        inputs = {"brent": days({"2026-11-02": "80", "2026-11-03": "81", "2026-11-04": "82"}),
                  "gasoline": days({"2026-11-02": "2.5", "2026-11-03": "2.6", "2026-11-04": "2.5"}),
                  "diesel": days({"2026-11-02": "3", "2026-11-03": None, "2026-11-04": "3.1"})}
        self.assertEqual(crack_history(inputs, date(2026, 11, 1)),
                         [["2026-11-02", exact_text(crack(F("2.5"), F("3"), F(80)))],
                          ["2026-11-04", exact_text(crack(F("2.5"), F("3.1"), F(82)))]])
        self.assertEqual(crack_history(inputs, date(2026, 11, 3)),
                         [["2026-11-04", exact_text(crack(F("2.5"), F("3.1"), F(82)))]])


if __name__ == "__main__":
    unittest.main()
