"""
tests/test_finance_stopwords.py

Focused tests for the finance-domain stopword expansion that reduces false-positive
related-event and historical-analog matches between unrelated headlines.

Three scenarios:
  1) False positives reduced — generic finance tokens no longer cause cross-topic match
  2) Real macro matches preserved — topic-specific tokens survive; pairs still link
  3) Clean existing matches unchanged — pairs without new stops are unaffected
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import (
    _headline_words,
    _jaccard,
    _short_headline_guard,
    _STOP_WORDS,
    _RELATED_THRESHOLD,
)

# New domain stops that were added — used to verify they are filtered
_NEW_DOMAIN_STOPS = {
    "data", "growth", "record", "level",
    "show", "warn", "signal", "plan", "expect",
    "year", "month", "week", "quarter",
}


def _would_match_related(headline_a: str, headline_b: str) -> bool:
    """Simulate find_related_events filter logic."""
    a = _headline_words(headline_a)
    b = _headline_words(headline_b)
    return _jaccard(a, b) >= _RELATED_THRESHOLD and _short_headline_guard(a, b)


def _would_match_analog(headline_a: str, headline_b: str) -> bool:
    """Simulate find_historical_analogs headline-only guard (0.15 threshold)."""
    a = _headline_words(headline_a)
    b = _headline_words(headline_b)
    return _jaccard(a, b) >= 0.15 and _short_headline_guard(a, b)


# ---------------------------------------------------------------------------
# 1) False positives reduced
# ---------------------------------------------------------------------------

class TestFalsePositivesReduced(unittest.TestCase):
    """Headlines sharing only generic finance tokens must NOT match."""

    def test_opposite_economic_direction_headlines(self):
        # Before this change: shared {show, growth, data} → Jaccard 0.43 → match
        # After: all three are stops → no shared content tokens → no match
        self.assertFalse(
            _would_match_related(
                "US growth data shows weakness",
                "China growth data shows strength",
            )
        )

    def test_generic_tokens_stripped_from_word_sets(self):
        """New domain stops must not appear in _headline_words output."""
        for hl in [
            "US growth data shows weakness",
            "Fed signals rate plan this year",
            "Banks warn of record level losses this quarter",
        ]:
            words = _headline_words(hl)
            leaked = words & _NEW_DOMAIN_STOPS
            self.assertEqual(
                leaked, set(),
                f"New stops leaked into word set for {hl!r}: {leaked}",
            )

    def test_generic_institution_signals_headlines(self):
        # Before: shared {signal, plan, year} → Jaccard 0.50 → match
        # After: all three are stops; fed≠ecb, rate≠growth → no match
        self.assertFalse(
            _would_match_related(
                "Fed signals rate plan this year",
                "ECB signals growth plan this year",
            )
        )

    def test_record_data_quarter_stops_cross_sector_fp(self):
        # Before: "record", "data", "quarter" inflate cross-topic Jaccard
        # After: stripped → match relies on sector-specific tokens only
        a = _headline_words("US banks post record quarterly data beat")
        b = _headline_words("US energy sector record quarterly data miss")
        # After stripping "record", "data", "quarter": {u, bank, post, beat} vs {u, energi, sector, miss}
        shared = a & b
        self.assertNotIn("record", shared)
        self.assertNotIn("data", shared)
        self.assertNotIn("quarter", shared)

    def test_warn_level_year_do_not_inflate_sim(self):
        # "warn" and "year" alone shouldn't link unrelated events
        self.assertFalse(
            _would_match_related(
                "Fed warns of inflation risk this year",
                "IMF warns of geopolitical risk this year",
            )
        )

    def test_plan_show_stops_cross_institution_fp(self):
        # Two institutions announcing different plans → should not link
        self.assertFalse(
            _would_match_related(
                "BOJ shows plan to widen yield curve band",
                "ECB shows plan to cut balance sheet this year",
            )
        )


# ---------------------------------------------------------------------------
# 2) Real macro matches preserved
# ---------------------------------------------------------------------------

class TestRealMacroMatchesPreserved(unittest.TestCase):
    """Pairs sharing topic-specific tokens still link even with new stops applied."""

    def test_iran_nuclear_sanctions(self):
        # New stops "expected" and "plan" appear but 4 specific topic tokens remain
        # shared: {iran, nuclear, deal, sanction} → Jaccard ≈ 0.57
        self.assertTrue(
            _would_match_related(
                "Iran nuclear deal sanctions expected to ease",
                "Iran nuclear sanctions deal plan finalized",
            )
        )

    def test_us_china_tariff_war_escalation(self):
        # New stops "signal", "year", "expect" removed; 4 shared topic tokens remain
        # shared: {us, china, tariff, war} → Jaccard = 0.50
        self.assertTrue(
            _would_match_related(
                "US China tariff war signals escalation this year",
                "China US tariff war escalates as expected",
            )
        )

    def test_oil_sanctions_analog(self):
        # No new stops present; topic tokens (russia, oil, sanction) drive match
        self.assertTrue(
            _would_match_analog(
                "Russia oil sanctions tighten amid Ukraine war",
                "Oil sanctions on Russia extended by EU",
            )
        )

    def test_fed_rate_hike_preserved(self):
        # "rate" and "cut" are NOT new stops — they survive and drive Fed event matches.
        # Uses a pair with enough overlapping topic tokens to clear the related threshold.
        a = _headline_words("Fed cuts rates to emergency low")
        b = _headline_words("Federal Reserve emergency rate cut")
        # Core topic tokens must be intact
        for tok in ("rate", "cut", "emergency"):
            self.assertIn(tok, a, f"{tok!r} unexpectedly missing from a")
            self.assertIn(tok, b, f"{tok!r} unexpectedly missing from b")
        # Still links as a related event
        self.assertTrue(_would_match_related(
            "Fed cuts rates to emergency low",
            "Federal Reserve emergency rate cut",
        ))

    def test_boj_yield_curve_preserved(self):
        # No new stops; topic tokens (boj, yield, curve) intact
        a = _headline_words("BOJ adjusts yield curve control band")
        b = _headline_words("BOJ yield curve policy shift accelerates")
        shared = a & b
        self.assertGreaterEqual(len(shared), 2)
        self.assertTrue(_short_headline_guard(a, b))

    def test_opec_cut_topic_tokens_intact(self):
        # "cut" and "opec" must survive — key commodity-supply discriminators
        a = _headline_words("OPEC output cut deepens")
        b = _headline_words("OPEC production cut extended")
        self.assertIn("opec", a)
        self.assertIn("cut", a)
        self.assertIn("opec", b)
        self.assertIn("cut", b)
        shared = a & b
        self.assertGreaterEqual(len(shared), 2)
        self.assertTrue(_short_headline_guard(a, b))


# ---------------------------------------------------------------------------
# 3) Clean existing matches unchanged
# ---------------------------------------------------------------------------

class TestExistingMatchesUnchanged(unittest.TestCase):
    """Pairs with none of the new stops are unaffected by this change."""

    def test_china_tariff_retaliation(self):
        # Contains no new stops — behavior identical to before.
        # sim=0.20 — matches as historical analog (≥0.15), not as related event (≥0.35).
        self.assertTrue(
            _would_match_analog(
                "China tariffs escalate into full trade war",
                "China tariff retaliation hits US agriculture",
            )
        )

    def test_oil_sanctions_exact_tokens(self):
        # Token sets for oil-sanction headlines are unchanged
        a = _headline_words("Russia oil sanctions extended")
        b = _headline_words("Oil sanctions tighten on Russia")
        for tok in ("russia", "oil", "sanction"):
            self.assertIn(tok, a | b)

    def test_short_headline_guard_unchanged_for_new_stops(self):
        # Short genuine macro pair still passes the guard after new stops
        a = _headline_words("OPEC output cut deepens")
        b = _headline_words("OPEC production cut extended")
        self.assertTrue(_short_headline_guard(a, b))

    def test_long_genuine_analog_unchanged(self):
        # Longer tariff headline pair; none of the new stops appear
        self.assertTrue(
            _would_match_analog(
                "US imposes sweeping tariffs on Chinese semiconductor exports",
                "US semiconductor tariffs on China take effect",
            )
        )

    def test_new_stops_are_subset_of_full_stopword_set(self):
        """All new domain stops must be present in _STOP_WORDS after the change."""
        for word in _NEW_DOMAIN_STOPS:
            self.assertIn(
                word, _STOP_WORDS,
                f"Expected {word!r} in _STOP_WORDS but it is missing",
            )


if __name__ == "__main__":
    unittest.main()
