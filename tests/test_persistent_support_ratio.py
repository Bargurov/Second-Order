"""
tests/test_persistent_support_ratio.py

Focused tests for persistent mover support_ratio correctness.

  1) Implausible ticker scrub must not leak into support_ratio — a ticker
     with a 1348% return is scrubbed to None, so it must not count as
     "supporting" in the agreement computation.
  2) Duplicate ticker suppression must not distort support_ratio — a
     cross-contaminated row that is suppressed must not inflate the
     denominator.
  3) Healthy regression — event with clean tickers produces the same
     support_ratio as before.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from api import _persistent_summary, _compute_support_ratio
from market_check import (
    _scrub_implausible_ticker_returns,
    _suppress_duplicate_tickers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ticker(
    symbol: str,
    return_5d: float | None,
    *,
    direction_tag: str | None = "supports thesis",
    role: str = "beneficiary",
    return_1d: float | None = 0.5,
    return_20d: float | None = None,
    spark: list | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "role": role,
        "label": "in motion",
        "return_1d": return_1d,
        "return_5d": return_5d,
        "return_20d": return_20d,
        "direction_tag": direction_tag,
        "volume_ratio": 1.1,
        "vs_xle_5d": None,
        "spark": spark or [round(0.1 * i, 2) for i in range(20)],
        "anchor_date": None,
    }


def _event(tickers: list[dict], *, days_old: int = 10) -> dict:
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    return {
        "id": 1,
        "headline": "Persistent mover test",
        "stage": "realized",
        "persistence": "structural",
        "event_date": (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d"),
        "timestamp": ts,
        "what_changed": "Something changed",
        "mechanism_summary": "Mechanism",
        "beneficiaries": [],
        "losers": [],
        "assets_to_watch": [],
        "confidence": "medium",
        "market_note": "note",
        "market_tickers": tickers,
        "transmission_chain": [],
        "if_persists": {},
    }


def _clean(tickers: list[dict]) -> list[dict]:
    """Same clean pipeline as _compute_persistent_slice."""
    return _suppress_duplicate_tickers(
        _scrub_implausible_ticker_returns(tickers)
    )


def _with_return(tickers: list[dict]) -> list[dict]:
    return [t for t in tickers if t.get("return_5d") is not None]


# ---------------------------------------------------------------------------
# 1) Implausible ticker scrub must not leak into support_ratio
# ---------------------------------------------------------------------------

class TestImplausibleScrubNotInRatio(unittest.TestCase):
    """A ticker with an absurd return (e.g. +1348%) is scrubbed to None
    by _scrub_implausible_ticker_returns.  After scrubbing, it has no
    return_5d and must not count toward support_ratio."""

    def test_scrubbed_ticker_excluded_from_ratio(self):
        tickers = [
            # Healthy supporting ticker
            _ticker("XOM", 3.5, direction_tag="supports thesis"),
            # Implausible — will be scrubbed to return_5d=None
            _ticker("XLE", 1348.0, direction_tag="supports thesis"),
            # Healthy opposing ticker
            _ticker("DAL", -2.0, direction_tag="contradicts thesis", role="loser"),
        ]
        ev = _event(tickers)

        cleaned = _clean(tickers)
        qualified = _with_return(cleaned)

        # The implausible ticker should be gone from qualified.
        qualified_symbols = {t["symbol"] for t in qualified}
        self.assertNotIn("XLE", qualified_symbols,
                         "Implausible XLE should be scrubbed out")

        # Now test that _persistent_summary uses this same clean list.
        now_dt = datetime.now()
        summary = _persistent_summary(ev, qualified, now_dt)

        # With only XOM (supports) and DAL (contradicts) in the cleaned
        # set, support_ratio should be 1/2 = 0.5, NOT 2/3 ≈ 0.67.
        self.assertAlmostEqual(summary["support_ratio"], 0.5, places=2)

    def test_all_implausible_yields_zero_ratio(self):
        tickers = [
            _ticker("XLE", 1500.0, direction_tag="supports thesis"),
            _ticker("XOM", 2000.0, direction_tag="supports thesis"),
        ]
        ev = _event(tickers)

        cleaned = _clean(tickers)
        qualified = _with_return(cleaned)

        # All tickers scrubbed — no qualified tickers.
        self.assertEqual(len(qualified), 0)


# ---------------------------------------------------------------------------
# 2) Duplicate ticker suppression must not distort support_ratio
# ---------------------------------------------------------------------------

class TestDuplicateSuppressionNotInRatio(unittest.TestCase):
    """Cross-contaminated duplicate rows are suppressed by
    _suppress_duplicate_tickers.  They must not inflate the agreement
    denominator."""

    def test_duplicate_suppressed_ticker_excluded(self):
        # Two tickers with identical (return_5d, spark) → cross-contaminated.
        # _suppress_duplicate_tickers nulls both their return_5d and
        # direction_tag, so after _with_return filtering only the
        # non-duplicate DAL survives.
        shared_spark = [0.1, 0.2, 0.3, 0.4, 0.5] * 4
        tickers = [
            _ticker("XOM", 3.5, direction_tag="supports thesis",
                    spark=shared_spark),
            _ticker("CVX", 3.5, direction_tag="supports thesis",
                    spark=shared_spark),
            _ticker("DAL", -2.0, direction_tag="contradicts thesis",
                    role="loser", spark=[0.9, 0.8, 0.7, 0.6, 0.5] * 4),
        ]
        ev = _event(tickers)

        cleaned = _clean(tickers)
        qualified = _with_return(cleaned)

        # Both XOM and CVX are suppressed (return_5d → None); only DAL survives.
        self.assertEqual(len(qualified), 1,
                         "Both duplicates should have been suppressed")
        self.assertEqual(qualified[0]["symbol"], "DAL")

        now_dt = datetime.now()
        summary = _persistent_summary(ev, qualified, now_dt)

        # Only DAL (contradicts) remains → 0/1 = 0.0.
        # The key invariant: the ratio is computed from the same cleaned
        # list, not from the raw 3-ticker list where it would be 2/3.
        self.assertAlmostEqual(summary["support_ratio"], 0.0, places=2)


# ---------------------------------------------------------------------------
# 3) Healthy regression — clean tickers produce correct support_ratio
# ---------------------------------------------------------------------------

class TestHealthyRegression(unittest.TestCase):
    """Events with normal tickers produce the same support_ratio as always."""

    def test_all_supporting(self):
        tickers = [
            _ticker("XOM", 3.5, direction_tag="supports thesis"),
            _ticker("CVX", 2.1, direction_tag="supports thesis"),
        ]
        ev = _event(tickers)
        cleaned = _clean(tickers)
        qualified = _with_return(cleaned)

        summary = _persistent_summary(ev, qualified, datetime.now())
        self.assertAlmostEqual(summary["support_ratio"], 1.0, places=2)

    def test_mixed_support(self):
        tickers = [
            _ticker("XOM", 3.5, direction_tag="supports thesis"),
            _ticker("DAL", -2.0, direction_tag="contradicts thesis",
                    role="loser"),
        ]
        ev = _event(tickers)
        cleaned = _clean(tickers)
        qualified = _with_return(cleaned)

        summary = _persistent_summary(ev, qualified, datetime.now())
        self.assertAlmostEqual(summary["support_ratio"], 0.5, places=2)

    def test_no_direction_tags_yields_zero(self):
        tickers = [
            _ticker("XOM", 3.5, direction_tag=None),
            _ticker("CVX", 2.1, direction_tag=None),
        ]
        ev = _event(tickers)
        cleaned = _clean(tickers)
        qualified = _with_return(cleaned)

        summary = _persistent_summary(ev, qualified, datetime.now())
        self.assertAlmostEqual(summary["support_ratio"], 0.0, places=2)

    def test_ratio_matches_compute_support_ratio(self):
        """_persistent_summary must agree with _compute_support_ratio
        given the same cleaned list."""
        tickers = [
            _ticker("XOM", 3.5, direction_tag="supports thesis"),
            _ticker("CVX", 2.1, direction_tag="supports thesis"),
            _ticker("DAL", -2.0, direction_tag="contradicts thesis",
                    role="loser"),
        ]
        ev = _event(tickers)
        cleaned = _clean(tickers)
        qualified = _with_return(cleaned)

        expected = _compute_support_ratio(qualified)
        summary = _persistent_summary(ev, qualified, datetime.now())
        self.assertAlmostEqual(summary["support_ratio"], round(expected, 2))


if __name__ == "__main__":
    unittest.main()
