"""
tests/test_short_headline_guard.py

Focused tests for the short-headline overlap guard that prevents
two- or three-word headlines sharing a single generic term from
over-matching in related events and historical analogs.

Three scenarios:
  1) Short false positives blocked
  2) Short true positives preserved
  3) Longer headline regression unchanged
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
    _RELATED_THRESHOLD,
    _SHORT_HEADLINE_THRESHOLD,
    _MIN_SHARED_TOKENS,
)


def _would_match_related(headline_a: str, headline_b: str) -> bool:
    """Simulate the find_related_events filter logic."""
    a = _headline_words(headline_a)
    b = _headline_words(headline_b)
    sim = _jaccard(a, b)
    return sim >= _RELATED_THRESHOLD and _short_headline_guard(a, b)


def _would_match_analog_headlines(headline_a: str, headline_b: str) -> bool:
    """Simulate the find_historical_analogs headline-only guard.

    Uses the lower analog threshold (0.15) but still applies the
    short-headline guard on headline-only words.
    """
    a = _headline_words(headline_a)
    b = _headline_words(headline_b)
    sim = _jaccard(a, b)
    return sim >= 0.15 and _short_headline_guard(a, b)


# ---------------------------------------------------------------------------
# 1) Short false positives blocked
# ---------------------------------------------------------------------------

class TestShortFalsePositivesBlocked(unittest.TestCase):
    """Short generic headlines sharing one token must NOT match."""

    def test_single_shared_generic_word(self):
        # "Oil rises" vs "Oil crashes" — 1 shared content word: oil
        self.assertFalse(_would_match_related("Oil rises", "Oil crashes"))

    def test_single_shared_with_stops(self):
        # After stop-word removal: {tariff} vs {tariff}
        # "New tariffs" → {tariff}; "Tariff report" → {tariff}
        self.assertFalse(
            _would_match_related("New tariffs on steel", "Tariff reports delayed")
        )

    def test_short_country_overlap(self):
        # "China exports" vs "China earthquake" — only "china" shared
        self.assertFalse(
            _would_match_analog_headlines("China exports boom", "China earthquake")
        )

    def test_two_word_identical_after_normalization(self):
        # "Fed rate" vs "Fed cut" — only "fed" shared (rate is 3 chars,
        # kept; but still just 1 shared token)
        self.assertFalse(
            _would_match_related("Fed rate", "Fed cut")
        )

    def test_guard_function_directly(self):
        """_short_headline_guard rejects 1-token overlap on short sets."""
        a = {"oil", "price"}
        b = {"oil", "supply"}
        self.assertFalse(_short_headline_guard(a, b))

    def test_guard_single_word_sets(self):
        """Single-word headline sets with 1 shared word blocked."""
        a = {"tariff"}
        b = {"tariff"}
        # Even perfect Jaccard = 1.0 should be blocked by the guard
        self.assertEqual(_jaccard(a, b), 1.0)
        self.assertFalse(_short_headline_guard(a, b))


# ---------------------------------------------------------------------------
# 2) Short true positives preserved
# ---------------------------------------------------------------------------

class TestShortTruePositivesPreserved(unittest.TestCase):
    """Short but specific macro/commodity headlines must still match."""

    def test_opec_cuts(self):
        # "OPEC output cut deepens" vs "OPEC production cut extended"
        # Shared after normalization: opec, cut (≥2 tokens)
        a = _headline_words("OPEC output cut deepens")
        b = _headline_words("OPEC production cut extended")
        shared = a & b
        self.assertGreaterEqual(len(shared), 2)
        self.assertTrue(_short_headline_guard(a, b))

    def test_fed_hikes_rates(self):
        # "Fed hikes rates" vs "Fed raises rates"
        # Shared: fed, rate (≥2)
        a = _headline_words("Fed hikes rates")
        b = _headline_words("Fed raises rates")
        shared = a & b
        self.assertGreaterEqual(len(shared), 2)
        self.assertTrue(_short_headline_guard(a, b))

    def test_china_tariffs(self):
        # "China tariffs escalate" vs "China tariff retaliation"
        # Shared: china, tariff (≥2)
        a = _headline_words("China tariffs escalate")
        b = _headline_words("China tariff retaliation")
        shared = a & b
        self.assertGreaterEqual(len(shared), 2)
        self.assertTrue(_short_headline_guard(a, b))

    def test_guard_with_two_shared(self):
        """_short_headline_guard accepts ≥2 shared tokens on short sets."""
        a = {"opec", "cut", "output"}
        b = {"opec", "cut", "production"}
        self.assertTrue(_short_headline_guard(a, b))

    def test_boj_yield_curve(self):
        # "BOJ adjusts yield curve" vs "BOJ yield curve control"
        # Shared: boj, yield, curve (≥2)
        a = _headline_words("BOJ adjusts yield curve")
        b = _headline_words("BOJ yield curve control")
        self.assertTrue(_short_headline_guard(a, b))


# ---------------------------------------------------------------------------
# 3) Longer headline regression unchanged
# ---------------------------------------------------------------------------

class TestLongerHeadlineRegression(unittest.TestCase):
    """Headlines with >4 content words should behave exactly as before."""

    def test_guard_always_passes_long_headlines(self):
        """When both sets have >_SHORT_HEADLINE_THRESHOLD words, guard passes."""
        a = {"federal", "reserve", "raise", "interest", "rate"}
        b = {"central", "bank", "monetary", "policy", "tightening"}
        self.assertGreater(min(len(a), len(b)), _SHORT_HEADLINE_THRESHOLD)
        # Even with 0 overlap, guard passes — Jaccard alone decides
        self.assertTrue(_short_headline_guard(a, b))

    def test_long_headline_low_jaccard_still_rejected(self):
        """Long headlines with low Jaccard still fail on the threshold."""
        a = "Federal Reserve unexpectedly raises rates by 50 basis points"
        b = "European Central Bank holds rates steady amid inflation fears"
        wa = _headline_words(a)
        wb = _headline_words(b)
        sim = _jaccard(wa, wb)
        # Low Jaccard — would be rejected by the threshold, not the guard
        self.assertLess(sim, _RELATED_THRESHOLD)
        # Guard itself passes for long headlines
        self.assertTrue(_short_headline_guard(wa, wb))

    def test_long_headline_genuine_match_preserved(self):
        """A real match between longer headlines is unaffected."""
        a = "US imposes sweeping tariffs on Chinese semiconductor exports"
        b = "US semiconductor tariffs on China take effect"
        wa = _headline_words(a)
        wb = _headline_words(b)
        sim = _jaccard(wa, wb)
        self.assertGreaterEqual(sim, 0.15)
        self.assertTrue(_short_headline_guard(wa, wb))

    def test_one_short_one_long(self):
        """Mixed lengths: short query vs long candidate. min() governs."""
        short = _headline_words("Oil surges")          # 2 words
        long_ = _headline_words(
            "Oil prices surge after OPEC announces surprise production cut"
        )                                               # ~6 words
        # min(2, 6) = 2 ≤ threshold → guard applies
        # shared: {oil, surge} → 2 ≥ _MIN_SHARED_TOKENS → passes
        shared = short & long_
        self.assertGreaterEqual(len(shared), _MIN_SHARED_TOKENS)
        self.assertTrue(_short_headline_guard(short, long_))

    def test_one_short_one_long_single_overlap(self):
        """Short query vs long candidate with only 1 shared word → blocked."""
        short = _headline_words("Oil drops")           # {oil, drop}
        long_ = _headline_words(
            "Gold and silver surge on safe haven demand as oil inventories build"
        )
        # shared: {oil} → 1 < _MIN_SHARED_TOKENS → blocked
        shared = short & long_
        self.assertLess(len(shared), _MIN_SHARED_TOKENS)
        self.assertFalse(_short_headline_guard(short, long_))


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

class TestGuardConstants(unittest.TestCase):
    def test_threshold_values(self):
        self.assertEqual(_MIN_SHARED_TOKENS, 2)
        self.assertEqual(_SHORT_HEADLINE_THRESHOLD, 4)


if __name__ == "__main__":
    unittest.main()
