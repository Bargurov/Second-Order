"""
tests/test_critical_fixes.py

Regression tests for the Critical (Fix Now) items from ARCH_AUDIT.md:
  1. compute_stress_regime failure path
  2. NaN / non-finite direction-tag handling
  3. Punctuation tokenisation in _headline_words
"""

import math
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# 1. _is_finite, _pct, _pct_forward: NaN and non-finite guards
# ---------------------------------------------------------------------------

import market_check


class TestIsFinite(unittest.TestCase):
    """_is_finite must reject None, NaN, ±Inf and accept normal floats."""

    def test_normal_float(self):
        self.assertTrue(market_check._is_finite(1.5))
        self.assertTrue(market_check._is_finite(-0.0))
        self.assertTrue(market_check._is_finite(0))

    def test_nan(self):
        self.assertFalse(market_check._is_finite(float("nan")))

    def test_inf(self):
        self.assertFalse(market_check._is_finite(float("inf")))
        self.assertFalse(market_check._is_finite(float("-inf")))

    def test_none(self):
        self.assertFalse(market_check._is_finite(None))

    def test_string_rejects(self):
        self.assertFalse(market_check._is_finite("hello"))


class TestPctNanGuard(unittest.TestCase):
    """_pct and _pct_forward must return None when inputs contain NaN."""

    def _series(self, values):
        return pd.Series(values)

    def test_pct_normal(self):
        s = self._series([100.0, 110.0])
        self.assertAlmostEqual(market_check._pct(s, 1), 10.0)

    def test_pct_nan_in_last(self):
        s = self._series([100.0, float("nan")])
        self.assertIsNone(market_check._pct(s, 1))

    def test_pct_nan_in_first(self):
        s = self._series([float("nan"), 110.0])
        self.assertIsNone(market_check._pct(s, 1))

    def test_pct_inf(self):
        s = self._series([100.0, float("inf")])
        self.assertIsNone(market_check._pct(s, 1))

    def test_pct_zero_denominator(self):
        s = self._series([0.0, 110.0])
        self.assertIsNone(market_check._pct(s, 1))

    def test_pct_forward_normal(self):
        s = self._series([100.0, 105.0, 110.0])
        self.assertAlmostEqual(market_check._pct_forward(s, 2), 10.0)

    def test_pct_forward_nan(self):
        s = self._series([100.0, float("nan"), 110.0])
        # periods=1: compares iloc[0]=100 to iloc[1]=NaN -> None
        self.assertIsNone(market_check._pct_forward(s, 1))

    def test_pct_forward_zero_denom(self):
        s = self._series([0.0, 110.0])
        self.assertIsNone(market_check._pct_forward(s, 1))


# ---------------------------------------------------------------------------
# 2. _direction_tag: NaN must be treated as missing, not contradictory
# ---------------------------------------------------------------------------

class TestDirectionTagNan(unittest.TestCase):
    """NaN values must produce None (inconclusive), never a 'contradicts' tag."""

    def test_none_returns_none(self):
        self.assertIsNone(market_check._direction_tag(None, "beneficiary"))

    def test_nan_returns_none(self):
        self.assertIsNone(market_check._direction_tag(float("nan"), "beneficiary"))

    def test_inf_returns_none(self):
        self.assertIsNone(market_check._direction_tag(float("inf"), "loser"))

    def test_neg_inf_returns_none(self):
        self.assertIsNone(market_check._direction_tag(float("-inf"), "beneficiary"))

    def test_normal_beneficiary_supports(self):
        self.assertEqual(market_check._direction_tag(2.0, "beneficiary"), "supports ↑")

    def test_normal_beneficiary_contradicts(self):
        self.assertEqual(market_check._direction_tag(-2.0, "beneficiary"), "contradicts ↓")

    def test_normal_loser_supports(self):
        self.assertEqual(market_check._direction_tag(-2.0, "loser"), "supports ↓")

    def test_normal_loser_contradicts(self):
        self.assertEqual(market_check._direction_tag(2.0, "loser"), "contradicts ↑")

    def test_flat_zone(self):
        self.assertIsNone(market_check._direction_tag(0.3, "beneficiary"))


# ---------------------------------------------------------------------------
# 3. compute_stress_regime failure resilience
# ---------------------------------------------------------------------------

class TestStressRegimeFailurePath(unittest.TestCase):
    """When individual signal fetches raise, the regime should degrade
    gracefully per-signal instead of silently returning all-calm."""

    def _make_fetch_that_fails_for(self, failing_tickers: set[str]):
        """Return a _fetch replacement that raises for specific tickers."""
        def _fake_fetch(ticker):
            if ticker in failing_tickers:
                raise ConnectionError(f"Simulated network failure for {ticker}")
            # Return a minimal valid DataFrame for everything else
            dates = pd.date_range("2026-01-01", periods=25, freq="B")
            closes = [100.0 + i * 0.1 for i in range(25)]
            volumes = [1_000_000] * 25
            return pd.DataFrame({"Close": closes, "Volume": volumes}, index=dates)
        return _fake_fetch

    def test_single_signal_failure_does_not_crash(self):
        """If VIX fetch fails, the function should still return a valid regime."""
        fake = self._make_fetch_that_fails_for({"^VIX"})
        with patch.object(market_check, "_fetch", side_effect=fake):
            result = market_check.compute_stress_regime()
        self.assertIn("regime", result)
        self.assertIn("signals", result)
        self.assertIn("detail", result)
        # The volatility detail should indicate error
        vol = result["detail"].get("volatility", {})
        self.assertIn("error", vol.get("explanation", "").lower())

    def test_all_signals_fail_returns_degraded_state(self):
        """If every fetch raises, we must still get a valid structure — not crash."""
        all_tickers = {"^VIX", "^VIX3M", "HYG", "SHY", "GLD", "DX-Y.NYB", "TLT", "RSP", "SPY"}
        fake = self._make_fetch_that_fails_for(all_tickers)
        with patch.object(market_check, "_fetch", side_effect=fake):
            result = market_check.compute_stress_regime()
        self.assertIn("regime", result)
        self.assertIn("signals", result)
        self.assertIn("detail", result)
        # All signals should remain at their defaults (False)
        for v in result["signals"].values():
            self.assertFalse(v)
        # Every detail section should exist
        for key in ("volatility", "term_structure", "credit", "safe_haven", "breadth"):
            self.assertIn(key, result["detail"])

    def test_healthy_signals_survive_partial_failure(self):
        """Credit signal fails, but VIX/term/haven/breadth should still compute."""
        fake = self._make_fetch_that_fails_for({"HYG", "SHY"})
        with patch.object(market_check, "_fetch", side_effect=fake):
            result = market_check.compute_stress_regime()
        # Volatility should have computed successfully (non-error explanation)
        vol = result["detail"].get("volatility", {})
        self.assertNotIn("error", vol.get("explanation", "").lower())
        # Credit should show error
        credit = result["detail"].get("credit", {})
        self.assertIn("error", credit.get("explanation", "").lower())


# ---------------------------------------------------------------------------
# 4. _headline_words: punctuation stripping
# ---------------------------------------------------------------------------

import db


class TestHeadlineWordsPunctuation(unittest.TestCase):
    """_headline_words must strip leading/trailing punctuation so that
    'oil:' and 'oil' produce the same token."""

    def test_trailing_colon(self):
        words = db._headline_words("Oil: OPEC decision")
        self.assertIn("oil", words)
        self.assertNotIn("oil:", words)

    def test_trailing_comma(self):
        words = db._headline_words("tariffs, steel, sanctions")
        self.assertIn("tariffs", words)
        self.assertNotIn("tariffs,", words)
        self.assertIn("steel", words)
        self.assertNotIn("steel,", words)

    def test_trailing_period(self):
        words = db._headline_words("Markets rally.")
        self.assertIn("rally", words)
        self.assertNotIn("rally.", words)

    def test_possessive_kept(self):
        # "opec's" is a valid token — internal apostrophe preserved
        words = db._headline_words("OPEC's production cut")
        self.assertIn("opec's", words)

    def test_hyphenated_word_kept(self):
        words = db._headline_words("multi-year trade deal")
        self.assertIn("multi-year", words)

    def test_quoted_word(self):
        words = db._headline_words('"sanctions" imposed')
        self.assertIn("sanctions", words)
        self.assertNotIn('"sanctions"', words)

    def test_stop_words_still_removed(self):
        words = db._headline_words("The quick, brown fox.")
        self.assertNotIn("the", words)
        self.assertIn("quick", words)
        self.assertIn("brown", words)
        self.assertIn("fox", words)

    def test_punctuated_vs_clean_match(self):
        """Two headlines differing only in punctuation should now overlap."""
        a = db._headline_words("Oil: OPEC's decision, markets rally.")
        b = db._headline_words("Oil OPEC's decision markets rally")
        self.assertEqual(a, b)


class TestNewsSourcesHeadlineWords(unittest.TestCase):
    """news_sources._headline_words should strip punctuation identically."""

    def test_trailing_colon(self):
        from news_sources import _headline_words
        words = _headline_words("Oil: OPEC decision")
        self.assertIn("oil", words)
        self.assertNotIn("oil:", words)

    def test_punctuated_vs_clean(self):
        from news_sources import _headline_words
        a = _headline_words("Tariffs, steel sanctions.")
        b = _headline_words("Tariffs steel sanctions")
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# 5. classify_decay: NaN guard
# ---------------------------------------------------------------------------

class TestClassifyDecayNan(unittest.TestCase):
    """classify_decay must handle None and NaN gracefully."""

    def test_both_none(self):
        result = market_check.classify_decay(None, None)
        self.assertEqual(result["label"], "Unknown")

    def test_r5_none(self):
        result = market_check.classify_decay(None, 5.0)
        self.assertEqual(result["label"], "Unknown")

    def test_normal_holding(self):
        result = market_check.classify_decay(3.0, 5.0)
        self.assertEqual(result["label"], "Holding")


if __name__ == "__main__":
    unittest.main()
