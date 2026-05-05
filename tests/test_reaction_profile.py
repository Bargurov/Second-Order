"""Tests for reaction_profile.compute_reaction_profile.

Synthetic fixtures only — no DB, no provider calls, no clock dependence.
Mirrors the test plan in docs/reaction_profile_design.md §7.
"""

from __future__ import annotations

import unittest
from typing import Sequence

from reaction_profile import (
    FADE_OR_HOLD_LABELS,
    REACTION_PROFILE_BASES,
    _FADE_HOLD_THRESHOLD,
    _NOISE_5D_PCT,
    _NOISE_20D_PCT,
    _NOISE_60D_PCT,
    compute_reaction_profile,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

ANCHOR: float = 100.0


def _from_returns(returns_pct: Sequence[float]) -> list[float]:
    """Build a closes series from per-bar pct moves *relative to anchor*.

    ``returns_pct[i]`` is the cumulative-from-anchor pct return at bar
    ``i+1``.  Returns ``[ANCHOR, ANCHOR*(1+r0/100), ...]``.
    """
    return [ANCHOR] + [ANCHOR * (1.0 + r / 100.0) for r in returns_pct]


def _flat_series(n_bars: int) -> list[float]:
    """Anchor + n_bars identical bars (zero return each session)."""
    return [ANCHOR] * (n_bars + 1)


# Stable key set the composer must always emit.
EXPECTED_KEYS: frozenset = frozenset({
    "return_1d", "return_5d", "return_20d", "return_60d",
    "benchmark_relative_return_1d",
    "benchmark_relative_return_5d",
    "benchmark_relative_return_20d",
    "benchmark_relative_return_60d",
    "peak_move_5d", "peak_move_20d", "peak_move_60d",
    "time_to_peak_5d", "time_to_peak_20d", "time_to_peak_60d",
    "fade_or_hold_label_5d",
    "fade_or_hold_label_20d",
    "fade_or_hold_label_60d",
    "reaction_profile_basis",
})


# ---------------------------------------------------------------------------
# Stable shape — design §7.1
# ---------------------------------------------------------------------------

class StableShape(unittest.TestCase):
    def _assert_keys(self, result):
        self.assertEqual(set(result.keys()), set(EXPECTED_KEYS))

    def test_none_input_full_keys(self):
        self._assert_keys(compute_reaction_profile(None))

    def test_empty_list_full_keys(self):
        self._assert_keys(compute_reaction_profile([]))

    def test_full_series_full_keys(self):
        self._assert_keys(compute_reaction_profile(_flat_series(60)))

    def test_basis_in_vocabulary(self):
        for inp in (None, [], _flat_series(0), _flat_series(60)):
            with self.subTest(inp=inp):
                r = compute_reaction_profile(inp)
                self.assertIn(
                    r["reaction_profile_basis"], REACTION_PROFILE_BASES,
                )

    def test_fade_labels_in_vocabulary(self):
        r = compute_reaction_profile(_flat_series(60))
        for h in ("5d", "20d", "60d"):
            with self.subTest(horizon=h):
                self.assertIn(
                    r[f"fade_or_hold_label_{h}"], FADE_OR_HOLD_LABELS,
                )


# ---------------------------------------------------------------------------
# Returns — design §7.1
# ---------------------------------------------------------------------------

class BasicReturns(unittest.TestCase):
    def test_return_1d_5d_20d_60d_happy_path(self):
        # Construct a series with specific bars: 1=+1%, 5=+3%, 20=+5%, 60=+8%.
        rets = [0.0] * 60
        rets[0]  = 1.0    # bar 1
        rets[4]  = 3.0    # bar 5
        rets[19] = 5.0    # bar 20
        rets[59] = 8.0    # bar 60
        r = compute_reaction_profile(_from_returns(rets))
        self.assertEqual(r["reaction_profile_basis"], "forward_anchored")
        self.assertAlmostEqual(r["return_1d"],  1.0, places=2)
        self.assertAlmostEqual(r["return_5d"],  3.0, places=2)
        self.assertAlmostEqual(r["return_20d"], 5.0, places=2)
        self.assertAlmostEqual(r["return_60d"], 8.0, places=2)

    def test_negative_return_sign_preserved(self):
        r = compute_reaction_profile(_from_returns([-2.0]))
        self.assertAlmostEqual(r["return_1d"], -2.0, places=2)

    def test_short_series_nulls_longer_horizons(self):
        # 5 forward bars → 1d/5d valid, 20d/60d null.
        r = compute_reaction_profile(_from_returns([1.0, 1.0, 1.0, 1.0, 2.0]))
        self.assertAlmostEqual(r["return_1d"], 1.0, places=2)
        self.assertAlmostEqual(r["return_5d"], 2.0, places=2)
        self.assertIsNone(r["return_20d"])
        self.assertIsNone(r["return_60d"])

    def test_round_to_2dp(self):
        # Anchor 100 → bar 1 = 101.234 → return 1.234% rounds to 1.23.
        r = compute_reaction_profile([100.0, 101.234])
        self.assertAlmostEqual(r["return_1d"], 1.23, places=2)


# ---------------------------------------------------------------------------
# Peak / time-to-peak — design §7.2
# ---------------------------------------------------------------------------

class PeakAndTime(unittest.TestCase):
    def test_peak_at_first_bar(self):
        rets = [5.0, 0.5, 0.5, 0.5, 0.5]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], 5.0, places=2)
        self.assertEqual(r["time_to_peak_5d"], 1)

    def test_peak_at_last_bar(self):
        rets = [0.5, 0.5, 0.5, 0.5, 5.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], 5.0, places=2)
        self.assertEqual(r["time_to_peak_5d"], 5)

    def test_tie_picks_earliest(self):
        # Bars 2 and 4 both at +3%; earliest wins → bar 2.
        rets = [0.0, 3.0, 0.0, 3.0, 0.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], 3.0, places=2)
        self.assertEqual(r["time_to_peak_5d"], 2)

    def test_whipsaw_peak_then_settle(self):
        # +4% at bar 2, settles to 0% by bar 5.
        rets = [0.0, 4.0, 2.0, 1.0, 0.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], 4.0, places=2)
        self.assertEqual(r["time_to_peak_5d"], 2)
        self.assertAlmostEqual(r["return_5d"], 0.0, places=2)
        self.assertEqual(r["fade_or_hold_label_5d"], "fade")

    def test_negative_peak_preserves_sign(self):
        rets = [0.0, -1.0, -5.0, -2.0, -1.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], -5.0, places=2)
        self.assertEqual(r["time_to_peak_5d"], 3)

    def test_peak_60d_independent_of_5d_window(self):
        # 60 forward bars; +10% peak at bar 30.  5d / 20d windows are flat.
        rets = [0.0] * 60
        rets[29] = 10.0
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_60d"], 10.0, places=2)
        self.assertEqual(r["time_to_peak_60d"], 30)
        # Bar 30 sits outside both the 5d and 20d windows.
        self.assertAlmostEqual(r["peak_move_5d"], 0.0, places=2)
        self.assertAlmostEqual(r["peak_move_20d"], 0.0, places=2)


# ---------------------------------------------------------------------------
# fade_or_hold_label decision table — design §7.3
# ---------------------------------------------------------------------------

class FadeOrHoldDecision(unittest.TestCase):
    def test_insufficient_when_horizon_underfilled(self):
        # 4 forward bars only → return_5d is None → label is "insufficient".
        r = compute_reaction_profile(_from_returns([1.0, 1.0, 1.0, 1.0]))
        self.assertEqual(r["fade_or_hold_label_5d"], "insufficient")
        self.assertIsNone(r["peak_move_5d"])

    def test_flat_when_peak_below_noise(self):
        # All bars within ±0.5%, below the 1.0% 5d noise floor.
        rets = [0.5, -0.5, 0.3, -0.4, 0.2]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertEqual(r["fade_or_hold_label_5d"], "flat")

    def test_reverse_when_signs_flip(self):
        # +3% at bar 2, then -3% at bar 5.
        rets = [0.0, 3.0, 0.0, -1.5, -3.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], 3.0, places=2)
        self.assertAlmostEqual(r["return_5d"], -3.0, places=2)
        self.assertEqual(r["fade_or_hold_label_5d"], "reverse")

    def test_hold_at_threshold_inclusive(self):
        # peak +5%, final +3.5% → ratio 0.7 → "hold" (boundary inclusive).
        rets = [0.0, 5.0, 4.5, 4.0, 3.5]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], 5.0, places=2)
        self.assertAlmostEqual(r["return_5d"], 3.5, places=2)
        self.assertEqual(r["fade_or_hold_label_5d"], "hold")

    def test_fade_just_below_threshold(self):
        # peak +5%, final +3.0% → ratio 0.6 < 0.7 → "fade".
        rets = [0.0, 5.0, 4.0, 3.5, 3.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["peak_move_5d"], 5.0, places=2)
        self.assertAlmostEqual(r["return_5d"], 3.0, places=2)
        self.assertEqual(r["fade_or_hold_label_5d"], "fade")

    def test_final_zero_is_fade_not_reverse(self):
        # Peak +4%, final 0% — gave back 100% but never crossed zero → fade.
        rets = [0.0, 4.0, 2.0, 1.0, 0.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertAlmostEqual(r["return_5d"], 0.0, places=2)
        self.assertEqual(r["fade_or_hold_label_5d"], "fade")

    def test_threshold_constant_pinned(self):
        self.assertEqual(_FADE_HOLD_THRESHOLD, 0.7)

    def test_noise_constants_pinned(self):
        self.assertEqual(_NOISE_5D_PCT,  1.0)
        self.assertEqual(_NOISE_20D_PCT, 2.0)
        self.assertEqual(_NOISE_60D_PCT, 3.0)


# ---------------------------------------------------------------------------
# Benchmark relative return — design §7.1 / §7.4
# ---------------------------------------------------------------------------

class BenchmarkRelative(unittest.TestCase):
    def test_happy_path(self):
        # Ticker +5% at 5d, benchmark +2% at 5d → relative +3%.
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        bench  = _from_returns([0.5, 1.0, 1.5, 1.7, 2.0])
        r = compute_reaction_profile(closes, benchmark_closes=bench)
        self.assertAlmostEqual(r["return_5d"], 5.0, places=2)
        self.assertAlmostEqual(r["benchmark_relative_return_5d"], 3.0, places=2)

    def test_missing_benchmark_nulls_relative(self):
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        r = compute_reaction_profile(closes, benchmark_closes=None)
        for h in ("1d", "5d", "20d", "60d"):
            with self.subTest(horizon=h):
                self.assertIsNone(r[f"benchmark_relative_return_{h}"])

    def test_short_benchmark_nulls_only_unreached_horizons(self):
        # Ticker has 60 bars; benchmark has only 5 → 1d/5d valid, 20d/60d null.
        closes = _from_returns([1.0] * 60)
        bench  = _from_returns([0.5] * 5)
        r = compute_reaction_profile(closes, benchmark_closes=bench)
        self.assertIsNotNone(r["benchmark_relative_return_1d"])
        self.assertIsNotNone(r["benchmark_relative_return_5d"])
        self.assertIsNone(r["benchmark_relative_return_20d"])
        self.assertIsNone(r["benchmark_relative_return_60d"])

    def test_quarantined_horizon_nulls_relative(self):
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        bench  = _from_returns([0.5, 1.0, 1.5, 1.7, 2.0])
        r = compute_reaction_profile(
            closes, benchmark_closes=bench,
            benchmark_quarantined_horizons={"5d"},
        )
        self.assertIsNone(r["benchmark_relative_return_5d"])
        # Other horizons unaffected.
        self.assertAlmostEqual(
            r["benchmark_relative_return_1d"], 0.5, places=2,
        )

    def test_quarantined_set_does_not_mutate_input(self):
        # Composer must not mutate the caller's set — paranoid guard.
        q = {"20d"}
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        compute_reaction_profile(closes, benchmark_quarantined_horizons=q)
        self.assertEqual(q, {"20d"})


# ---------------------------------------------------------------------------
# Basis states — design §7.4
# ---------------------------------------------------------------------------

class BasisStates(unittest.TestCase):
    def test_unscorable_for_none(self):
        r = compute_reaction_profile(None)
        self.assertEqual(r["reaction_profile_basis"], "unscorable")
        self.assertIsNone(r["return_1d"])

    def test_unscorable_for_empty_list(self):
        r = compute_reaction_profile([])
        self.assertEqual(r["reaction_profile_basis"], "unscorable")

    def test_unscorable_for_anchor_only(self):
        r = compute_reaction_profile([100.0])
        self.assertEqual(r["reaction_profile_basis"], "unscorable")
        self.assertIsNone(r["return_1d"])

    def test_stale_nulls_forward_fields(self):
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        r = compute_reaction_profile(closes, stale=True)
        self.assertEqual(r["reaction_profile_basis"], "stale")
        for h in ("1d", "5d", "20d", "60d"):
            with self.subTest(horizon=h):
                self.assertIsNone(r[f"return_{h}"])
                self.assertIsNone(r[f"benchmark_relative_return_{h}"])
        for h in ("5d", "20d", "60d"):
            with self.subTest(horizon=h):
                self.assertIsNone(r[f"peak_move_{h}"])
                self.assertIsNone(r[f"time_to_peak_{h}"])
                self.assertEqual(
                    r[f"fade_or_hold_label_{h}"], "insufficient",
                )

    def test_same_day_fallback_only_r1(self):
        # Anchor = prior close, closes[1] = event-day close; +2% same-day move.
        closes = [100.0, 102.0]
        r = compute_reaction_profile(closes, same_day_fallback=True)
        self.assertEqual(r["reaction_profile_basis"], "same_day_fallback")
        self.assertAlmostEqual(r["return_1d"], 2.0, places=2)
        self.assertIsNone(r["return_5d"])
        self.assertIsNone(r["return_20d"])
        self.assertIsNone(r["return_60d"])
        self.assertIsNone(r["peak_move_5d"])
        self.assertIsNone(r["time_to_peak_5d"])
        self.assertEqual(r["fade_or_hold_label_5d"], "insufficient")

    def test_same_day_fallback_with_benchmark(self):
        # Ticker +2.0%, benchmark +1.0% → relative_1d = +1.0%.
        r = compute_reaction_profile(
            [100.0, 102.0],
            benchmark_closes=[50.0, 50.5],
            same_day_fallback=True,
        )
        self.assertAlmostEqual(
            r["benchmark_relative_return_1d"], 1.0, places=2,
        )
        self.assertIsNone(r["benchmark_relative_return_5d"])

    def test_forward_anchored_default(self):
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        r = compute_reaction_profile(closes)
        self.assertEqual(r["reaction_profile_basis"], "forward_anchored")


# ---------------------------------------------------------------------------
# Edge cases from the task brief
# ---------------------------------------------------------------------------

class EdgeCases(unittest.TestCase):
    def test_no_prices(self):
        for inp in (None, [], [100.0]):
            with self.subTest(inp=inp):
                r = compute_reaction_profile(inp)
                self.assertEqual(r["reaction_profile_basis"], "unscorable")

    def test_event_too_young_uses_same_day_fallback(self):
        r = compute_reaction_profile([100.0, 101.5], same_day_fallback=True)
        self.assertEqual(r["reaction_profile_basis"], "same_day_fallback")
        self.assertAlmostEqual(r["return_1d"], 1.5, places=2)
        self.assertIsNone(r["return_5d"])

    def test_missing_benchmark(self):
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        r = compute_reaction_profile(closes, benchmark_closes=None)
        for h in ("1d", "5d", "20d", "60d"):
            with self.subTest(horizon=h):
                self.assertIsNone(r[f"benchmark_relative_return_{h}"])

    def test_sign_flip_reverse(self):
        rets = [0.0, 3.0, 0.0, -1.0, -3.0]
        r = compute_reaction_profile(_from_returns(rets))
        self.assertEqual(r["fade_or_hold_label_5d"], "reverse")

    def test_hold_vs_fade_threshold_boundary(self):
        # At threshold (ratio = 0.7) → hold.
        r_hold = compute_reaction_profile(
            _from_returns([0.0, 5.0, 4.5, 4.0, 3.5]),
        )
        self.assertEqual(r_hold["fade_or_hold_label_5d"], "hold")
        # Below threshold (ratio = 0.6) → fade.
        r_fade = compute_reaction_profile(
            _from_returns([0.0, 5.0, 4.0, 3.5, 3.0]),
        )
        self.assertEqual(r_fade["fade_or_hold_label_5d"], "fade")

    def test_contradictory_ticker_directions_compute_independently(self):
        # The composer is per-ticker — opposing-direction tickers each get
        # an independent profile.  No cross-ticker contamination possible.
        closes_up = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        closes_dn = _from_returns([-1.0, -2.0, -3.0, -4.0, -5.0])
        r_up = compute_reaction_profile(closes_up)
        r_dn = compute_reaction_profile(closes_dn)
        self.assertAlmostEqual(r_up["return_5d"],  5.0, places=2)
        self.assertAlmostEqual(r_dn["return_5d"], -5.0, places=2)
        self.assertAlmostEqual(r_up["peak_move_5d"],  5.0, places=2)
        self.assertAlmostEqual(r_dn["peak_move_5d"], -5.0, places=2)
        self.assertEqual(r_up["fade_or_hold_label_5d"], "hold")
        self.assertEqual(r_dn["fade_or_hold_label_5d"], "hold")

    def test_invalid_anchor_zero(self):
        # Anchor 0 → divide-by-zero protection; everything null.
        r = compute_reaction_profile([0.0, 1.0, 2.0])
        self.assertIsNone(r["return_1d"])
        self.assertIsNone(r["return_5d"])

    def test_nan_in_series_is_skipped(self):
        # NaN bars are unscorable for that horizon's target but earlier
        # bars still contribute to the peak scan.
        nan = float("nan")
        closes = [100.0, 102.0, nan, 103.0, 104.0, 105.0]
        r = compute_reaction_profile(closes)
        # return_5d targets bar 5 (105.0) → +5%.
        self.assertAlmostEqual(r["return_5d"], 5.0, places=2)
        # NaN at bar 2 is skipped; peak still found at bar 5.
        self.assertAlmostEqual(r["peak_move_5d"], 5.0, places=2)


# ---------------------------------------------------------------------------
# Determinism + purity — design §7.5 / §7.6
# ---------------------------------------------------------------------------

class Determinism(unittest.TestCase):
    def test_repeated_calls_identical(self):
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        bench  = _from_returns([0.5, 1.0, 1.5, 1.7, 2.0])
        a = compute_reaction_profile(closes, benchmark_closes=bench)
        b = compute_reaction_profile(closes, benchmark_closes=bench)
        self.assertEqual(a, b)

    def test_byte_equal_across_kwarg_orderings(self):
        closes = _from_returns([1.0, 2.0, 3.0, 4.0, 5.0])
        a = compute_reaction_profile(
            closes, benchmark_closes=None, stale=False,
        )
        b = compute_reaction_profile(
            closes, stale=False, benchmark_closes=None,
        )
        self.assertEqual(a, b)


class PureContract(unittest.TestCase):
    """Structural guards against accidental I/O imports."""

    def test_no_io_or_provider_imports_in_source(self):
        import inspect
        import reaction_profile as rp
        src = inspect.getsource(rp)
        forbidden = (
            "import datetime", "from datetime",
            "import time\n", "from time ",
            "import sqlite3", "from sqlite3",
            "import requests", "from requests",
            "import urllib", "from urllib",
            "import yfinance", "from yfinance",
            "import market_check", "from market_check",
            "import market_data",  "from market_data",
            "import price_cache",  "from price_cache",
            "import db",           "from db",
            "anthropic", "openai",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()
