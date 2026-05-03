"""
tests/test_market_holiday_clamp.py

Focused tests for US market holiday handling in _clamp_to_market_date.

  1) Weekend clamp unchanged (existing behavior preserved).
  2) US market holiday clamps forward to next trading day.
  3) Normal trading day unchanged.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_check
from market_check import _clamp_to_market_date, is_market_holiday


# Freeze "today" to a known date so tests don't depend on the real calendar.
_FAKE_TODAY = date(2026, 4, 15)  # Wednesday


def _clamp(date_str: str) -> str:
    """Call _clamp_to_market_date with a frozen today."""
    with patch.object(market_check, "_date_type") as mock_date:
        mock_date.fromisoformat = date.fromisoformat
        mock_date.today.return_value = _FAKE_TODAY
        return _clamp_to_market_date(date_str)


# ---------------------------------------------------------------------------
# 1) Weekend clamp unchanged
# ---------------------------------------------------------------------------

class TestWeekendClampUnchanged(unittest.TestCase):

    def test_saturday_rolls_to_friday(self):
        self.assertEqual(_clamp("2026-03-14"), "2026-03-13")  # Sat → Fri

    def test_sunday_rolls_to_friday(self):
        self.assertEqual(_clamp("2026-03-15"), "2026-03-13")  # Sun → Fri

    def test_friday_unchanged(self):
        self.assertEqual(_clamp("2026-03-13"), "2026-03-13")

    def test_monday_unchanged(self):
        self.assertEqual(_clamp("2026-03-16"), "2026-03-16")

    def test_weekend_result_is_weekday(self):
        for d in ["2026-03-14", "2026-03-15", "2026-04-11", "2026-04-12"]:
            result = _clamp(d)
            wd = date.fromisoformat(result).weekday()
            self.assertLess(wd, 5, f"{d} → {result} is weekday {wd}")


# ---------------------------------------------------------------------------
# 2) US market holiday clamps forward correctly
# ---------------------------------------------------------------------------

class TestHolidayClampForward(unittest.TestCase):

    def test_mlk_day_2026_monday_rolls_to_tuesday(self):
        """2026-01-19 is MLK Day (Monday) → 2026-01-20 (Tuesday)."""
        self.assertTrue(is_market_holiday(date(2026, 1, 19)))
        self.assertEqual(_clamp("2026-01-19"), "2026-01-20")

    def test_presidents_day_2026(self):
        """2026-02-16 is Presidents' Day (Monday) → 2026-02-17 (Tuesday)."""
        self.assertTrue(is_market_holiday(date(2026, 2, 16)))
        self.assertEqual(_clamp("2026-02-16"), "2026-02-17")

    def test_good_friday_2026(self):
        """2026-04-03 is Good Friday → 2026-04-06 (Monday)."""
        self.assertTrue(is_market_holiday(date(2026, 4, 3)))
        self.assertEqual(_clamp("2026-04-03"), "2026-04-06")

    def test_independence_day_2026_observed_friday(self):
        """2026-07-03 is observed Independence Day (Friday).
        Rolls to 2026-07-06 (Monday)."""
        self.assertTrue(is_market_holiday(date(2026, 7, 3)))
        # Need today to be after July 6 for this to work
        with patch.object(market_check, "_date_type") as mock_date:
            mock_date.fromisoformat = date.fromisoformat
            mock_date.today.return_value = date(2026, 7, 10)
            result = _clamp_to_market_date("2026-07-03")
        self.assertEqual(result, "2026-07-06")

    def test_christmas_2026_friday(self):
        """2026-12-25 is Christmas (Friday) → 2026-12-28 (Monday)."""
        self.assertTrue(is_market_holiday(date(2026, 12, 25)))
        with patch.object(market_check, "_date_type") as mock_date:
            mock_date.fromisoformat = date.fromisoformat
            mock_date.today.return_value = date(2026, 12, 31)
            result = _clamp_to_market_date("2026-12-25")
        self.assertEqual(result, "2026-12-28")

    def test_new_years_2026_thursday(self):
        """2026-01-01 is New Year's Day (Thursday) → 2026-01-02 (Friday)."""
        self.assertTrue(is_market_holiday(date(2026, 1, 1)))
        self.assertEqual(_clamp("2026-01-01"), "2026-01-02")

    def test_thanksgiving_2026(self):
        """2026-11-26 is Thanksgiving (Thursday) → 2026-11-27 (Friday)."""
        self.assertTrue(is_market_holiday(date(2026, 11, 26)))
        with patch.object(market_check, "_date_type") as mock_date:
            mock_date.fromisoformat = date.fromisoformat
            mock_date.today.return_value = date(2026, 11, 30)
            result = _clamp_to_market_date("2026-11-26")
        self.assertEqual(result, "2026-11-27")

    def test_saturday_before_holiday_monday_skips_both(self):
        """Saturday 2026-01-17 → Friday 2026-01-16 (not MLK Mon 01-19).
        Weekend rolls back, and that Friday is not a holiday, so it stays."""
        result = _clamp("2026-01-17")
        self.assertEqual(result, "2026-01-16")

    def test_sunday_before_holiday_monday_rolls_to_friday(self):
        """Sunday 2026-01-18 → Friday 2026-01-16."""
        result = _clamp("2026-01-18")
        self.assertEqual(result, "2026-01-16")

    def test_memorial_day_2026(self):
        """2026-05-25 is Memorial Day (Monday) → 2026-05-26 (Tuesday)."""
        self.assertTrue(is_market_holiday(date(2026, 5, 25)))
        with patch.object(market_check, "_date_type") as mock_date:
            mock_date.fromisoformat = date.fromisoformat
            mock_date.today.return_value = date(2026, 5, 30)
            result = _clamp_to_market_date("2026-05-25")
        self.assertEqual(result, "2026-05-26")


# ---------------------------------------------------------------------------
# 3) Normal trading day unchanged
# ---------------------------------------------------------------------------

class TestNormalTradingDayUnchanged(unittest.TestCase):

    def test_plain_monday(self):
        self.assertEqual(_clamp("2026-03-16"), "2026-03-16")

    def test_plain_wednesday(self):
        self.assertEqual(_clamp("2026-03-18"), "2026-03-18")

    def test_plain_friday(self):
        self.assertEqual(_clamp("2026-03-20"), "2026-03-20")

    def test_day_after_holiday_unchanged(self):
        """2026-01-20 (Tuesday after MLK Day) is a normal trading day."""
        self.assertFalse(is_market_holiday(date(2026, 1, 20)))
        self.assertEqual(_clamp("2026-01-20"), "2026-01-20")

    def test_day_before_holiday_unchanged(self):
        """2026-01-16 (Friday before MLK Monday) is a normal trading day."""
        self.assertFalse(is_market_holiday(date(2026, 1, 16)))
        self.assertEqual(_clamp("2026-01-16"), "2026-01-16")

    def test_non_holiday_weekday_not_in_table(self):
        """A 2029 weekday (no holidays table) passes through unchanged."""
        with patch.object(market_check, "_date_type") as mock_date:
            mock_date.fromisoformat = date.fromisoformat
            mock_date.today.return_value = date(2029, 6, 15)
            result = _clamp_to_market_date("2029-06-11")  # Monday
        self.assertEqual(result, "2029-06-11")


# ---------------------------------------------------------------------------
# is_market_holiday helper
# ---------------------------------------------------------------------------

class TestIsMarketHoliday(unittest.TestCase):

    def test_known_holidays(self):
        self.assertTrue(is_market_holiday(date(2025, 12, 25)))
        self.assertTrue(is_market_holiday(date(2026, 7, 3)))
        self.assertTrue(is_market_holiday(date(2027, 7, 5)))

    def test_normal_day_not_holiday(self):
        self.assertFalse(is_market_holiday(date(2026, 3, 18)))

    def test_weekend_not_in_holiday_set(self):
        """Weekends are handled by the weekend logic, not the holiday set."""
        self.assertFalse(is_market_holiday(date(2026, 3, 14)))  # Saturday


if __name__ == "__main__":
    unittest.main()
