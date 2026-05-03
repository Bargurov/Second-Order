"""
tests/test_headline_cleaning.py

Tests for source-prefix dedup normalization and calendar headline filtering.
"""

import sys
import unittest

sys.path.insert(0, ".")
from news_fetch import _dedup_key, normalize_headline, normalize_source
from news_relevance import _is_calendar_headline, is_relevant


class TestDedupNormalization(unittest.TestCase):
    """Dedup key must collapse source-prefixed and bare variants."""

    def _key(self, source: str, title: str) -> tuple[str, str]:
        return (normalize_source(source), _dedup_key(normalize_headline(title)))

    def test_source_prefix_collapses_to_same_key(self):
        """'Reuters: Fed raises rates' and 'Fed raises rates' from Reuters → same key."""
        k1 = self._key("Reuters", "Reuters: Fed raises rates")
        k2 = self._key("Reuters", "Fed raises rates")
        self.assertEqual(k1, k2)

    def test_bloomberg_prefix_collapses(self):
        k1 = self._key("Bloomberg", "Bloomberg: Oil prices surge on OPEC cut")
        k2 = self._key("Bloomberg", "Oil prices surge on OPEC cut")
        self.assertEqual(k1, k2)

    def test_cross_source_produces_different_keys(self):
        """Same normalized title but different sources → different keys (corroboration)."""
        k1 = self._key("Reuters", "Oil prices surge")
        k2 = self._key("Bloomberg", "Oil prices surge")
        self.assertNotEqual(k1, k2)

    def test_genuinely_different_titles_different_keys(self):
        k1 = self._key("Reuters", "Fed raises rates")
        k2 = self._key("Reuters", "Fed holds rates steady")
        self.assertNotEqual(k1, k2)

    def test_source_alias_normalized(self):
        """'BBC Business' and 'BBC World' normalize to same source."""
        k1 = self._key("BBC Business", "UK inflation falls to 2%")
        k2 = self._key("BBC World", "UK inflation falls to 2%")
        self.assertEqual(k1, k2)


class TestCalendarHeadlineGuard(unittest.TestCase):

    def test_diary_prefix_rejected(self):
        self.assertTrue(_is_calendar_headline("DIARY: Reuters schedule of upcoming events"))

    def test_diary_lowercase_rejected(self):
        self.assertTrue(_is_calendar_headline("diary: key events this week"))

    def test_scheduled_rejected(self):
        self.assertTrue(_is_calendar_headline("SCHEDULED: Fed press conference at 2:30pm ET"))

    def test_calendar_rejected(self):
        self.assertTrue(_is_calendar_headline("CALENDAR: Economic releases due this week"))

    def test_advisory_rejected(self):
        self.assertTrue(_is_calendar_headline("ADVISORY: Press briefing at noon"))

    def test_week_ahead_rejected(self):
        self.assertTrue(_is_calendar_headline("WEEK AHEAD: Fed, ECB and NFP on tap"))

    def test_table_rejected(self):
        self.assertTrue(_is_calendar_headline("TABLE: Central bank rate decisions 2026"))

    def test_preview_not_rejected(self):
        """PREVIEW may carry editorial analysis — should not be blocked."""
        self.assertFalse(_is_calendar_headline("PREVIEW: What the Fed's next move means for markets"))

    def test_normal_headline_not_rejected(self):
        self.assertFalse(_is_calendar_headline("Fed raises interest rates by 25 basis points"))

    def test_contains_diary_but_not_prefix(self):
        """'diary' mid-sentence should not trigger the guard."""
        self.assertFalse(_is_calendar_headline("Trader's diary: navigating volatile oil markets"))

    def test_is_relevant_rejects_calendar(self):
        """is_relevant() must return False for calendar-style headlines."""
        self.assertFalse(is_relevant("DIARY: Reuters schedule of upcoming events"))
        self.assertFalse(is_relevant("SCHEDULED: Fed meeting at 2pm"))
        self.assertFalse(is_relevant("WEEK AHEAD: Fed, ECB and NFP"))

    def test_is_relevant_keeps_normal_economic_headline(self):
        self.assertTrue(is_relevant("Fed raises interest rates by 25 basis points"))


if __name__ == "__main__":
    unittest.main()
