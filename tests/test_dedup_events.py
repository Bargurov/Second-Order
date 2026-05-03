"""Tests for db.dedup_events() and _event_dates_close()."""

import unittest
from db import dedup_events, _event_dates_close


def _ev(
    event_id: int,
    headline: str,
    event_date: str | None = "2025-01-15",
    timestamp: str = "2025-01-15T10:00:00",
) -> dict:
    return {
        "id": event_id,
        "headline": headline,
        "event_date": event_date,
        "timestamp": timestamp,
    }


class TestEventDatesClose(unittest.TestCase):
    def test_same_date(self):
        self.assertTrue(_event_dates_close("2025-01-15", "2025-01-15"))

    def test_within_window(self):
        self.assertTrue(_event_dates_close("2025-01-15", "2025-01-17"))

    def test_outside_window(self):
        self.assertFalse(_event_dates_close("2025-01-15", "2025-01-20"))

    def test_both_none_close_timestamps(self):
        self.assertTrue(_event_dates_close(None, None, "2025-01-15T10:00:00", "2025-01-16T08:00:00"))

    def test_both_none_distant_timestamps(self):
        self.assertFalse(_event_dates_close(None, None, "2024-06-01T10:00:00", "2025-01-15T10:00:00"))

    def test_one_none_one_date(self):
        self.assertFalse(_event_dates_close("2025-01-15", None))
        self.assertFalse(_event_dates_close(None, "2025-01-15"))


class TestDedupEventsPassthrough(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(dedup_events([]), [])

    def test_single_event(self):
        ev = _ev(1, "OPEC cuts oil output")
        self.assertEqual(dedup_events([ev]), [ev])

    def test_no_duplicates_returned_unchanged(self):
        evs = [
            _ev(3, "China imposes tariffs on US tech exports", "2025-01-15"),
            _ev(2, "Federal Reserve raises interest rates 25bp", "2025-01-14"),
            _ev(1, "OPEC cuts oil production sharply", "2025-01-13"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 3)
        self.assertEqual([e["id"] for e in result], [3, 2, 1])


class TestDedupEventsCollapse(unittest.TestCase):
    def test_high_similarity_same_date_collapsed(self):
        """Two headlines with same core words + same date → keep newest."""
        evs = [
            _ev(10, "OPEC cuts oil production output barrel", "2025-01-15"),
            _ev(5,  "OPEC cuts oil production output target", "2025-01-15"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 10)  # newest kept

    def test_high_similarity_different_date_not_collapsed(self):
        """Same headline words but different event dates → kept separate."""
        evs = [
            _ev(10, "OPEC cuts oil production output barrel", "2025-01-15"),
            _ev(5,  "OPEC cuts oil production output target", "2025-01-01"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 2)

    def test_low_similarity_same_date_not_collapsed(self):
        """Unrelated headlines on the same date → kept separate."""
        evs = [
            _ev(10, "OPEC cuts oil production output barrel", "2025-01-15"),
            _ev(5,  "Federal Reserve raises interest rate decision", "2025-01-15"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 2)

    def test_three_way_group_all_collapsed(self):
        """Three near-identical headlines → only the newest survives."""
        evs = [
            _ev(30, "OPEC cuts oil production output target barrel supply", "2025-01-15"),
            _ev(20, "OPEC cuts oil production output target barrel quota",  "2025-01-15"),
            _ev(10, "OPEC cuts oil production output target barrel reduce", "2025-01-15"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 30)

    def test_mixed_some_collapse_some_distinct(self):
        """Duplicate pair + unrelated event → one canonical + unrelated."""
        evs = [
            _ev(30, "OPEC cuts oil production output target barrel supply",  "2025-01-15"),
            _ev(20, "OPEC cuts oil production output target barrel quota",   "2025-01-15"),
            _ev(10, "Federal Reserve raises interest rate decision meeting", "2025-01-15"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 2)
        ids = {e["id"] for e in result}
        self.assertIn(30, ids)
        self.assertNotIn(20, ids)
        self.assertIn(10, ids)

    def test_oldest_suppressed_not_canonical(self):
        """Input is newest-first; older duplicate should always be suppressed."""
        evs = [
            _ev(100, "OPEC cuts oil output production barrel supply",  "2025-01-15"),
            _ev(1,   "OPEC cuts oil output production barrel target",  "2025-01-15"),
        ]
        result = dedup_events(evs)
        self.assertEqual(result[0]["id"], 100)

    def test_within_date_window_collapsed(self):
        """Events within 2-day window are dedup candidates."""
        evs = [
            _ev(10, "OPEC cuts oil production output barrel supply", "2025-01-15"),
            _ev(5,  "OPEC cuts oil production output barrel target", "2025-01-17"),  # 2 days = edge of window
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 1)

    def test_just_outside_date_window_kept(self):
        """3 days apart exceeds the 2-day window → kept separate."""
        evs = [
            _ev(10, "OPEC cuts oil production output barrel supply", "2025-01-15"),
            _ev(5,  "OPEC cuts oil production output barrel target", "2025-01-18"),  # 3 days
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 2)

    def test_no_event_date_close_timestamps_collapsed(self):
        """Legacy rows without event_date: collapse when timestamps are close."""
        evs = [
            _ev(10, "OPEC cuts oil production output barrel supply", None, "2025-01-15T10:00:00"),
            _ev(5,  "OPEC cuts oil production output barrel target", None, "2025-01-16T08:00:00"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 10)

    def test_no_event_date_distant_timestamps_kept(self):
        """Legacy rows without event_date: don't collapse when timestamps are months apart."""
        evs = [
            _ev(10, "OPEC cuts oil production output barrel supply", None, "2025-01-15T10:00:00"),
            _ev(5,  "OPEC cuts oil production output barrel target", None, "2024-10-01T08:00:00"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 2)

    def test_empty_headline_not_collapsed(self):
        """Events with empty headline word sets are never collapsed."""
        evs = [
            _ev(10, "", "2025-01-15"),
            _ev(5,  "", "2025-01-15"),
        ]
        result = dedup_events(evs)
        self.assertEqual(len(result), 2)

    def test_order_preserved(self):
        """Output preserves the input (newest-first) order of kept events."""
        evs = [
            _ev(50, "China tariff tech export imposition sanction trade",  "2025-01-10"),
            _ev(40, "OPEC cuts oil production output barrel supply target", "2025-01-15"),
            _ev(30, "OPEC cuts oil production output barrel supply quota",  "2025-01-15"),
            _ev(10, "Federal Reserve rate decision hike interest policy",   "2025-01-12"),
        ]
        result = dedup_events(evs)
        # 30 is a duplicate of 40; 50 and 10 are distinct
        ids = [e["id"] for e in result]
        self.assertNotIn(30, ids)
        self.assertEqual(ids.index(50), 0)
        self.assertLess(ids.index(40), ids.index(10))


if __name__ == "__main__":
    unittest.main()
