"""Tests for macro_calendar.get_macro_releases()."""
import unittest
from datetime import date

from macro_calendar import get_macro_releases


class TestGetMacroReleases(unittest.TestCase):

    def test_returns_list(self):
        result = get_macro_releases(today=date(2026, 4, 15))
        self.assertIsInstance(result, list)

    def test_all_five_indicators_present_in_wide_window(self):
        result = get_macro_releases(today=date(2026, 4, 15), days_before=30, days_after=30)
        names = {r["name"] for r in result}
        self.assertIn("CPI", names)
        self.assertIn("PPI", names)
        self.assertIn("NFP", names)
        self.assertIn("Unemployment", names)
        self.assertIn("PCE", names)

    def test_status_today(self):
        # CPI is scheduled 2026-04-10 — from that exact date it's "today"
        result = get_macro_releases(today=date(2026, 4, 10), days_before=0, days_after=30)
        cpi = [r for r in result if r["name"] == "CPI" and r["release_date"] == "2026-04-10"]
        self.assertEqual(len(cpi), 1)
        self.assertEqual(cpi[0]["status"], "today")
        self.assertEqual(cpi[0]["days_until"], 0)

    def test_status_upcoming(self):
        # NFP May 1 is 16 days ahead from Apr 15
        result = get_macro_releases(today=date(2026, 4, 15))
        nfp = [r for r in result if r["name"] == "NFP" and r["release_date"] == "2026-05-01"]
        self.assertEqual(len(nfp), 1)
        self.assertEqual(nfp[0]["status"], "upcoming")
        self.assertEqual(nfp[0]["days_until"], 16)

    def test_status_recent(self):
        # CPI Apr 10 is 5 days before Apr 15 — within days_before=5 window, status "past" (> 2 days)
        result = get_macro_releases(today=date(2026, 4, 15), days_before=5)
        cpi = [r for r in result if r["name"] == "CPI" and r["release_date"] == "2026-04-10"]
        self.assertEqual(len(cpi), 1)
        self.assertEqual(cpi[0]["days_until"], -5)
        self.assertEqual(cpi[0]["status"], "past")  # -5 days is "past" (beyond -2 threshold)

    def test_status_recent_within_two_days(self):
        # From Apr 12, CPI Apr 10 is 2 days ago → "recent"
        result = get_macro_releases(today=date(2026, 4, 12), days_before=3)
        cpi = [r for r in result if r["name"] == "CPI" and r["release_date"] == "2026-04-10"]
        self.assertEqual(len(cpi), 1)
        self.assertEqual(cpi[0]["status"], "recent")
        self.assertEqual(cpi[0]["days_until"], -2)

    def test_window_excludes_far_past(self):
        # NFP Apr 3 is 12 days before Apr 15; with days_before=5 it should NOT appear
        result = get_macro_releases(today=date(2026, 4, 15), days_before=5)
        nfp_apr3 = [r for r in result if r["name"] == "NFP" and r["release_date"] == "2026-04-03"]
        self.assertEqual(len(nfp_apr3), 0)

    def test_window_excludes_far_future(self):
        # With days_after=10, entries more than 10 days out should not appear
        result = get_macro_releases(today=date(2026, 4, 15), days_after=10)
        far_future = [r for r in result if r["release_date"] > "2026-04-25"]
        self.assertEqual(len(far_future), 0)

    def test_sorted_by_date(self):
        result = get_macro_releases(today=date(2026, 4, 15))
        dates = [r["release_date"] for r in result]
        self.assertEqual(dates, sorted(dates))

    def test_entry_has_required_fields(self):
        result = get_macro_releases(today=date(2026, 4, 15))
        for entry in result:
            self.assertIn("name", entry)
            self.assertIn("release_date", entry)
            self.assertIn("period", entry)
            self.assertIn("status", entry)
            self.assertIn("days_until", entry)

    def test_empty_window_returns_empty(self):
        # days_before=0, days_after=0 with no release on exactly that date
        result = get_macro_releases(today=date(2026, 4, 20), days_before=0, days_after=0)
        self.assertEqual(result, [])

    def test_nfp_and_unemployment_share_date(self):
        # NFP and Unemployment are the same BLS release — same date
        result = get_macro_releases(today=date(2026, 4, 15), days_before=20, days_after=20)
        nfp_dates = {r["release_date"] for r in result if r["name"] == "NFP"}
        urate_dates = {r["release_date"] for r in result if r["name"] == "Unemployment"}
        self.assertEqual(nfp_dates, urate_dates)


if __name__ == "__main__":
    unittest.main()
