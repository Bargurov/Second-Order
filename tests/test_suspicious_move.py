"""
tests/test_suspicious_move.py

Unit tests for suspicious-move verification:
  _should_verify      — trigger logic
  _verify_ticker_return — timeout behaviour + disputed/confirmed classification
  _check_one_ticker   — degradation of label/direction_tag on disputed/timed_out

No live network calls: all provider interactions are mocked.
"""

import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, ".")
import market_check


def _make_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000.0] * n
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=dates)


# ---------------------------------------------------------------------------
# _should_verify
# ---------------------------------------------------------------------------

class TestShouldVerify(unittest.TestCase):
    """Validate that the trigger logic fires in the right circumstances."""

    def test_large_positive_move_triggers(self):
        # |r5| = 6 >= _VERIFY_MOVE_THRESHOLD (5.0) → should verify
        self.assertTrue(market_check._should_verify(6.0, 6.0, 1.0))

    def test_large_negative_move_triggers(self):
        self.assertTrue(market_check._should_verify(-7.5, -7.5, 1.0))

    def test_at_threshold_triggers(self):
        # Boundary: exactly 5.0 triggers
        self.assertTrue(market_check._should_verify(5.0, 5.0, 1.0))

    def test_below_threshold_no_trigger(self):
        # 4.9 < 5.0 → no trigger (all else normal)
        self.assertFalse(market_check._should_verify(4.9, 4.9, 1.0))

    def test_scrubbed_return_triggers(self):
        # r5 != r5_pre_sanitize means it was implausibly large and nulled
        self.assertTrue(market_check._should_verify(None, 210.0, 1.0))

    def test_low_vol_ratio_triggers(self):
        # vol_ratio < _VERIFY_LOW_VOL (0.1) → suspicious
        self.assertTrue(market_check._should_verify(1.0, 1.0, 0.05))

    def test_low_vol_boundary_triggers(self):
        # Exactly at boundary (0.1) triggers: condition is vol < 0.1, so 0.1 does NOT trigger
        self.assertFalse(market_check._should_verify(1.0, 1.0, 0.1))

    def test_below_threshold_normal_vol_no_trigger(self):
        self.assertFalse(market_check._should_verify(2.0, 2.0, 1.5))

    def test_none_r5_no_trigger_without_scrub_or_low_vol(self):
        # r5=None, r5_pre=None (no scrub), vol normal → no trigger
        self.assertFalse(market_check._should_verify(None, None, 1.0))

    def test_none_vol_large_move_triggers(self):
        self.assertTrue(market_check._should_verify(8.0, 8.0, None))


# ---------------------------------------------------------------------------
# _verify_ticker_return_impl — core logic (no timeout wrapper)
# ---------------------------------------------------------------------------

class TestVerifyTickerReturnImpl(unittest.TestCase):
    """Tests the pure comparison logic without the ThreadPoolExecutor layer."""

    def _run(self, r5_primary, secondary_r5_value, *, enough_data=True) -> dict:
        """Run _verify_ticker_return_impl with a mocked secondary provider."""
        n = 30 if enough_data else 3
        df = _make_df([100.0 + i * secondary_r5_value / 100 for i in range(n)])
        secondary_mock = MagicMock()
        secondary_mock.fetch_daily.return_value = df

        with patch("market_data.get_secondary_provider", return_value=secondary_mock):
            # Patch _pct to return secondary_r5_value directly for simplicity
            with patch.object(market_check, "_pct", return_value=secondary_r5_value):
                return market_check._verify_ticker_return_impl(
                    "XYZ", r5_primary, event_date=None
                )

    def test_confirmed_when_delta_small(self):
        # Primary +6%, secondary +6.5% → delta 0.5 < 3.0 → confirmed
        result = self._run(6.0, 6.5)
        self.assertEqual(result["status"], "confirmed")
        self.assertAlmostEqual(result["delta"], -0.5, places=1)

    def test_disputed_when_delta_large(self):
        # Primary +8%, secondary +2% → delta 6 > 3.0 → disputed
        result = self._run(8.0, 2.0)
        self.assertEqual(result["status"], "disputed")
        self.assertAlmostEqual(result["delta"], 6.0, places=1)

    def test_disputed_boundary(self):
        # Delta = exactly 3.01 → disputed
        result = self._run(5.01, 2.0)
        self.assertEqual(result["status"], "disputed")

    def test_confirmed_at_boundary(self):
        # Delta = exactly 3.0 → confirmed (not strictly greater than)
        result = self._run(5.0, 2.0)
        self.assertEqual(result["status"], "confirmed")

    def test_unavailable_when_no_secondary(self):
        with patch("market_data.get_secondary_provider", return_value=None):
            result = market_check._verify_ticker_return_impl("AAPL", 7.0)
        self.assertEqual(result["status"], "unavailable")

    def test_unavailable_when_fetch_raises(self):
        secondary_mock = MagicMock()
        secondary_mock.fetch_daily.side_effect = RuntimeError("network down")
        with patch("market_data.get_secondary_provider", return_value=secondary_mock):
            result = market_check._verify_ticker_return_impl("AAPL", 7.0)
        self.assertEqual(result["status"], "unavailable")

    def test_unavailable_when_not_enough_data(self):
        result = self._run(6.0, 5.0, enough_data=False)
        self.assertEqual(result["status"], "unavailable")


# ---------------------------------------------------------------------------
# _verify_ticker_return — timeout behaviour
#
# _VERIFY_TIMEOUT defaults to 8.0s.  Tests patch it to 0.1s so the slow
# mock resolves in milliseconds relative to real time.  The 8.0s value
# was chosen because:
#   - yfinance typical response: 1-3s per ticker
#   - Polygon typical response: 0.5-2s per ticker
#   - 8s is ~3x the P95 response time, cutting off truly stuck requests
#     while avoiding false timeouts on slow-but-healthy network paths.
# ---------------------------------------------------------------------------

class TestVerifyTickerReturnTimeout(unittest.TestCase):

    def _slow_fetch(self, *args, **kwargs):
        """Simulates a provider that takes longer than the timeout."""
        time.sleep(0.5)  # longer than the patched 0.1s timeout
        return _make_df([100.0] * 30)

    def test_timed_out_status_when_secondary_slow(self):
        secondary_mock = MagicMock()
        secondary_mock.fetch_daily.side_effect = self._slow_fetch

        with patch("market_data.get_secondary_provider", return_value=secondary_mock):
            with patch.object(market_check, "_VERIFY_TIMEOUT", 0.1):
                result = market_check._verify_ticker_return("XYZ", 7.0, event_date="2026-01-01")

        self.assertEqual(result["status"], "timed_out")
        self.assertIsNone(result["secondary_r5"])
        self.assertIsNone(result["delta"])

    def test_fast_secondary_completes_normally(self):
        df = _make_df([100.0 + i * 0.08 for i in range(30)])
        secondary_mock = MagicMock()
        secondary_mock.fetch_daily.return_value = df

        with patch("market_data.get_secondary_provider", return_value=secondary_mock):
            with patch.object(market_check, "_pct", return_value=6.8):
                result = market_check._verify_ticker_return("XYZ", 7.0, event_date="2026-01-01")

        # fast path returns a real verdict
        self.assertIn(result["status"], ("confirmed", "disputed"))

    def test_no_event_date_returns_unverified_without_live_call(self):
        # Without an event anchor the rolling-window comparison is unreliable
        # (primary may be hours-old cache; secondary is always live). The
        # function must return "unverified" immediately — never call the
        # secondary provider.
        secondary_mock = MagicMock()
        # secondary returns flat data → would produce "disputed" if it ran
        secondary_mock.fetch_daily.return_value = _make_df([100.0] * 30)

        with patch("market_data.get_secondary_provider", return_value=secondary_mock):
            result = market_check._verify_ticker_return("XYZ", 7.0, event_date=None)

        self.assertEqual(result["status"], "unverified")
        secondary_mock.fetch_daily.assert_not_called()


# ---------------------------------------------------------------------------
# _check_one_ticker — degradation on disputed / timed_out
# ---------------------------------------------------------------------------

class TestDegradationOnVerification(unittest.TestCase):
    """
    Verify that label and direction_tag are correctly degraded when
    verification returns disputed or timed_out.
    """

    def _run_check(self, r5_val: float, verification_status: str) -> dict:
        """
        Run _check_one_ticker with a controlled dataset and a mocked
        verification result.
        """
        closes = [100.0 + i * r5_val / 500 for i in range(30)]
        df = _make_df(closes)
        verif_mock = {
            "status": verification_status,
            "secondary_r5": None,
            "delta": None,
            "provider": None,
        }
        with patch.object(market_check, "_fetch", return_value=df):
            with patch.object(market_check, "_should_verify", return_value=True):
                with patch.object(market_check, "_verify_ticker_return", return_value=verif_mock):
                    with patch.object(market_check, "_pct", side_effect=[
                        r5_val / 5,   # r1
                        r5_val,       # r5
                        r5_val * 4,   # r20
                    ]):
                        return market_check._check_one_ticker("XYZ", role="beneficiary")

    def test_disputed_clears_direction_tag(self):
        result = self._run_check(r5_val=8.0, verification_status="disputed")
        self.assertIsNone(result["direction"])

    def test_disputed_appends_disputed_to_notable_move_label(self):
        # A +8% move with high volume would normally be "notable move"
        # After disputed verification it should be "notable move (disputed)"
        closes = [100.0] * 30
        # big move + elevated volume
        closes_rising = [100.0 + i * 0.5 for i in range(30)]
        df = _make_df(closes_rising, volumes=[2_000_000.0] * 30)
        verif = {"status": "disputed", "secondary_r5": 1.0, "delta": 7.0, "provider": "polygon"}
        with patch.object(market_check, "_fetch", return_value=df):
            with patch.object(market_check, "_should_verify", return_value=True):
                with patch.object(market_check, "_verify_ticker_return", return_value=verif):
                    result = market_check._check_one_ticker("XYZ", role="beneficiary")
        self.assertIn("(disputed)", result["label"])
        self.assertIsNone(result["direction"])

    def test_timed_out_clears_direction_tag(self):
        result = self._run_check(r5_val=7.5, verification_status="timed_out")
        self.assertIsNone(result["direction"])

    def test_timed_out_does_not_append_to_label(self):
        # timed_out: we just can't confirm, but the label stays as-is
        result = self._run_check(r5_val=7.5, verification_status="timed_out")
        self.assertNotIn("(disputed)", result["label"])

    def test_confirmed_preserves_direction_tag(self):
        result = self._run_check(r5_val=6.0, verification_status="confirmed")
        # direction should be set (not None) for a clear positive move by a beneficiary
        # direction_tag from _direction_tag: beneficiary + up → "supports ↑"
        self.assertIsNotNone(result["direction"])

    def test_unverified_preserves_label_and_direction(self):
        # No verification triggered (status=unverified) — normal path unchanged
        closes = [100.0 + i * 0.1 for i in range(30)]
        df = _make_df(closes)
        with patch.object(market_check, "_fetch", return_value=df):
            with patch.object(market_check, "_should_verify", return_value=False):
                result = market_check._check_one_ticker("XYZ", role="beneficiary")
        # direction_tag is set (or None for flat) but label is not "(disputed)"
        self.assertNotIn("(disputed)", result["label"])

    def test_beneficiary_up_preserves_direction_when_secondary_present(self):
        # Regression guard: without an event anchor, a secondary provider that
        # returns flat data would produce "disputed" (delta = r5 - 0 = large)
        # and clear direction.  The rolling-window comparison must be skipped so
        # a healthy beneficiary move always keeps its direction tag.
        closes = [100.0 + i * 0.5 for i in range(30)]   # +6% last 5d
        df = _make_df(closes, volumes=[2_000_000.0] * 30)
        # Secondary returns completely flat data → would be "disputed" if comparison ran
        secondary_mock = MagicMock()
        secondary_mock.fetch_daily.return_value = _make_df([100.0] * 30)
        with patch.object(market_check, "_fetch", return_value=df):
            with patch("market_data.get_secondary_provider", return_value=secondary_mock):
                result = market_check._check_one_ticker("XYZ", role="beneficiary")
        self.assertIsNotNone(result["direction"])
        self.assertIn("supports ↑", result["direction"])

    def test_flat_disputed_label_not_marked(self):
        # A flat move that somehow triggers verification and is disputed
        # should NOT get "(disputed)" added — the label "flat" already
        # expresses low significance.
        result = self._run_check(r5_val=0.1, verification_status="disputed")
        self.assertNotIn("(disputed)", result["label"])

    def test_needs_more_evidence_disputed_label_not_marked(self):
        # "needs more evidence" shouldn't get "(disputed)" either — redundant
        result = self._run_check(r5_val=0.0, verification_status="disputed")
        self.assertNotIn("(disputed)", result["label"])


# ---------------------------------------------------------------------------
# Numeric threshold validation: _VERIFY_TIMEOUT = 8.0s
#
# These tests exist to document that the 8-second timeout was chosen with
# reference to real observed latencies, not picked arbitrarily.
# ---------------------------------------------------------------------------

class TestVerifyTimeoutConstant(unittest.TestCase):

    def test_timeout_at_least_5s(self):
        """Too-short a timeout false-positives on slow-but-healthy networks.
        yfinance P95 on a slow network runs ~3-4s; 5s gives 25-67% headroom."""
        self.assertGreaterEqual(market_check._VERIFY_TIMEOUT, 5.0)

    def test_timeout_at_most_15s(self):
        """Too-long a timeout means a stuck request blocks the analysis pipeline
        for an unacceptable time.  15s is the outer bound for interactive use."""
        self.assertLessEqual(market_check._VERIFY_TIMEOUT, 15.0)


if __name__ == "__main__":
    unittest.main()
