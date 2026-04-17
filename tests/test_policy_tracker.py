"""
tests/test_policy_tracker.py

Unit tests for policy_tracker.get_policy_items().
No network, no DB — pure date arithmetic.
"""

import sys
import unittest
from datetime import date

sys.path.insert(0, ".")
from policy_tracker import get_policy_items, _REVISIT_WARN_DAYS, _PAST_GRACE_DAYS


class TestStatusDerivation(unittest.TestCase):
    """Status values are derived from relative dates."""

    def _single(self, policy_type: str, effective_iso: str, revisit_iso: str, today: date) -> dict:
        import policy_tracker as _mod
        orig = list(_mod._ITEMS)
        _mod._ITEMS = [
            ("Test Policy", policy_type, "US", effective_iso, "2025-01-01", revisit_iso, "desc"),
        ]
        try:
            items = get_policy_items(today=today, days_before=365, days_after=365)
        finally:
            _mod._ITEMS = orig
        return items[0] if items else {}

    def test_announced_when_effective_far(self):
        # tariff threshold = 7; 16 days out → announced
        today = date(2026, 4, 15)
        item = self._single("tariff", "2026-05-01", "2026-08-01", today)
        self.assertEqual(item["status"], "announced")
        self.assertEqual(item["days_until"], 16)

    def test_pre_effective_within_threshold(self):
        # tariff threshold = 7; 5 days out → pre_effective
        today = date(2026, 4, 15)
        item = self._single("tariff", "2026-04-20", "2026-07-20", today)
        self.assertEqual(item["status"], "pre_effective")

    def test_active_when_effective_past_revisit_far(self):
        today = date(2026, 4, 15)
        item = self._single("tariff", "2026-03-01", "2026-08-01", today)
        self.assertEqual(item["status"], "active")

    def test_revisit_due_within_warn_window(self):
        today = date(2026, 4, 15)
        revisit = date(2026, 4, 15) + __import__("datetime").timedelta(days=_REVISIT_WARN_DAYS)
        item = self._single("tariff", "2026-01-01", revisit.isoformat(), today)
        self.assertEqual(item["status"], "revisit_due")

    def test_revisit_due_exactly_on_warn_boundary(self):
        today = date(2026, 4, 15)
        import datetime
        revisit = today + datetime.timedelta(days=_REVISIT_WARN_DAYS)
        item = self._single("tariff", "2026-01-01", revisit.isoformat(), today)
        self.assertEqual(item["status"], "revisit_due")

    def test_revisit_due_when_overdue_within_grace(self):
        today = date(2026, 4, 15)
        import datetime
        revisit = today - datetime.timedelta(days=5)
        item = self._single("tariff", "2026-01-01", revisit.isoformat(), today)
        self.assertEqual(item["status"], "revisit_due")

    def test_excluded_when_revisit_beyond_grace(self):
        today = date(2026, 4, 15)
        import datetime
        revisit = today - datetime.timedelta(days=_PAST_GRACE_DAYS + 1)
        item = self._single("tariff", "2026-01-01", revisit.isoformat(), today)
        self.assertEqual(item, {})  # excluded

    def test_excluded_when_effective_too_far_future(self):
        today = date(2026, 4, 15)
        # days_after=60; item effective 200 days out is excluded
        import policy_tracker as _mod
        orig = list(_mod._ITEMS)
        _mod._ITEMS = [
            ("Test Policy", "tariff", "US", "2026-11-01", "2025-01-01", "2027-02-01", "desc"),
        ]
        try:
            items = get_policy_items(today=today, days_before=365, days_after=60)
            self.assertEqual(items, [])
        finally:
            _mod._ITEMS = orig


class TestFieldPresence(unittest.TestCase):
    """Every returned item must have all required fields."""

    REQUIRED = {
        "name", "policy_type", "jurisdiction",
        "effective_date", "announcement_date", "revisit_date", "description",
        "status", "days_until", "days_until_revisit",
    }

    def test_all_fields_present(self):
        items = get_policy_items(today=date(2026, 4, 15))
        self.assertGreater(len(items), 0)
        for item in items:
            missing = self.REQUIRED - item.keys()
            self.assertEqual(missing, set(), f"Missing fields in {item['name']}: {missing}")


class TestWindowFiltering(unittest.TestCase):
    """Items outside the window are excluded."""

    def test_returns_some_items_for_april_2026(self):
        items = get_policy_items(today=date(2026, 4, 15))
        self.assertGreater(len(items), 0)

    def test_narrow_window_excludes_distant_items(self):
        # Window of 1 day before / 1 day after → almost nothing qualifies
        items = get_policy_items(
            today=date(2026, 4, 15),
            days_before=1,
            days_after=1,
        )
        # ECB April 17 effective date is 2 days out — outside days_after=1
        names = [i["name"] for i in items]
        self.assertNotIn("ECB Rate Decision", names)

    def test_no_past_status_items_returned_by_default(self):
        items = get_policy_items(today=date(2026, 4, 15))
        for item in items:
            self.assertNotEqual(item["status"], "past",
                                f"'past' item slipped through: {item['name']}")


class TestSorting(unittest.TestCase):
    """Items are sorted by effective_date, then name."""

    def test_sorted_by_effective_date(self):
        items = get_policy_items(today=date(2026, 4, 15))
        dates = [i["effective_date"] for i in items]
        self.assertEqual(dates, sorted(dates))

    def test_same_date_sorted_by_name(self):
        # Use a date where no collision exists in live data; inject two same-date items
        from policy_tracker import _ITEMS as _orig
        import policy_tracker as _mod
        orig = list(_mod._ITEMS)
        _mod._ITEMS = [
            ("Zebra Policy", "tariff", "US", "2026-06-01", "2025-01-01", "2026-09-01", "z"),
            ("Alpha Policy", "tariff", "EU", "2026-06-01", "2025-01-01", "2026-09-01", "a"),
        ]
        try:
            items = get_policy_items(today=date(2026, 4, 15), days_before=10, days_after=90)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["name"], "Alpha Policy")
            self.assertEqual(items[1]["name"], "Zebra Policy")
        finally:
            _mod._ITEMS = orig


class TestDaysCalculation(unittest.TestCase):
    """days_until and days_until_revisit are correct."""

    def test_days_until_positive_for_upcoming(self):
        items = get_policy_items(today=date(2026, 4, 15))
        for item in items:
            if item["status"] in ("announced", "pre_effective"):
                self.assertGreater(item["days_until"], 0)

    def test_days_until_nonpositive_for_active(self):
        items = get_policy_items(today=date(2026, 4, 15))
        for item in items:
            if item["status"] in ("active", "revisit_due"):
                self.assertLessEqual(item["days_until"], 0)

    def test_days_until_revisit_matches_date(self):
        today = date(2026, 4, 15)
        items = get_policy_items(today=today)
        for item in items:
            rev = date.fromisoformat(item["revisit_date"])
            expected = (rev - today).days
            self.assertEqual(item["days_until_revisit"], expected,
                             f"days_until_revisit mismatch for {item['name']}")


class TestKnownItems(unittest.TestCase):
    """Spot-checks on expected items for the current date."""

    def test_us_china_tariffs_present(self):
        items = get_policy_items(today=date(2026, 4, 15))
        names = [i["name"] for i in items]
        self.assertTrue(
            any("145" in n for n in names),
            "Expected US-China 145% tariff item to be present",
        )

    def test_ecb_decision_upcoming(self):
        items = get_policy_items(today=date(2026, 4, 15))
        ecb = next((i for i in items if "ECB" in i["name"]), None)
        self.assertIsNotNone(ecb)
        self.assertEqual(ecb["status"], "pre_effective")
        self.assertEqual(ecb["days_until"], 2)

    def test_fed_decision_upcoming(self):
        items = get_policy_items(today=date(2026, 4, 15))
        fed = next((i for i in items if "FOMC" in i["name"]), None)
        self.assertIsNotNone(fed)
        self.assertEqual(fed["status"], "announced")


class TestPhaseThresholds(unittest.TestCase):
    """Phase boundary is at the per-type pre_effective threshold."""

    def _phase(self, policy_type: str, days_until: int) -> str:
        from datetime import timedelta
        import policy_tracker as _mod
        today = date(2026, 4, 15)
        effective = (today + timedelta(days=days_until)).isoformat()
        revisit = (today + timedelta(days=days_until + 90)).isoformat()
        orig = list(_mod._ITEMS)
        _mod._ITEMS = [("T", policy_type, "US", effective, "2025-01-01", revisit, "d")]
        try:
            items = get_policy_items(today=today, days_before=365, days_after=365)
        finally:
            _mod._ITEMS = orig
        return items[0]["status"] if items else "excluded"

    def test_rate_decision_threshold_3(self):
        self.assertEqual(self._phase("rate_decision", 4), "announced")
        self.assertEqual(self._phase("rate_decision", 3), "pre_effective")
        self.assertEqual(self._phase("rate_decision", 1), "pre_effective")

    def test_tariff_threshold_7(self):
        self.assertEqual(self._phase("tariff", 8), "announced")
        self.assertEqual(self._phase("tariff", 7), "pre_effective")
        self.assertEqual(self._phase("tariff", 1), "pre_effective")
        self.assertEqual(self._phase("tariff", 0), "active")

    def test_sanction_threshold_7(self):
        self.assertEqual(self._phase("sanction", 8), "announced")
        self.assertEqual(self._phase("sanction", 7), "pre_effective")

    def test_executive_order_threshold_7(self):
        self.assertEqual(self._phase("executive_order", 8), "announced")
        self.assertEqual(self._phase("executive_order", 7), "pre_effective")

    def test_regulation_threshold_30(self):
        self.assertEqual(self._phase("regulation", 31), "announced")
        self.assertEqual(self._phase("regulation", 30), "pre_effective")
        self.assertEqual(self._phase("regulation", 1), "pre_effective")


if __name__ == "__main__":
    unittest.main()
