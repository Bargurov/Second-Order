"""
tests/test_pre_event_drift.py

Validates the pre-event drift helper and its effect on the empirical
"already priced" classification in surprise_vs_anticipation.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd  # noqa: E402

from surprise_vs_anticipation import (  # noqa: E402
    compute_surprise_vs_anticipation,
    _aligned_pre_drift,
    _already_priced_classification,
    _PRE_DRIFT_STRONG_PP,
    _PRE_DRIFT_WEAK_PP,
    _PRE_DRIFT_FLAT_PP,
)


# ---------------------------------------------------------------------------
# _aligned_pre_drift — sign alignment contract
# ---------------------------------------------------------------------------

class TestAlignedPreDrift(unittest.TestCase):

    def test_beneficiary_positive_stays_positive(self):
        tickers = [{"symbol": "AAA", "role": "beneficiary"}]
        drift = _aligned_pre_drift(tickers, {"AAA": 2.0})
        self.assertAlmostEqual(drift, 2.0)

    def test_loser_negative_flips_to_positive(self):
        # Loser down -2% pre-event IS in the thesis direction — flip sign.
        tickers = [{"symbol": "BBB", "role": "loser"}]
        drift = _aligned_pre_drift(tickers, {"BBB": -2.0})
        self.assertAlmostEqual(drift, 2.0)

    def test_averages_across_tickers(self):
        tickers = [
            {"symbol": "AAA", "role": "beneficiary"},
            {"symbol": "BBB", "role": "loser"},
        ]
        drift = _aligned_pre_drift(tickers, {"AAA": 1.5, "BBB": -1.0})
        # aligned = (1.5, 1.0) average = 1.25
        self.assertAlmostEqual(drift, 1.25)

    def test_none_when_no_data(self):
        self.assertIsNone(_aligned_pre_drift([{"symbol": "AAA"}], None))
        self.assertIsNone(_aligned_pre_drift([{"symbol": "AAA"}], {}))
        self.assertIsNone(_aligned_pre_drift([], {"AAA": 1.0}))


# ---------------------------------------------------------------------------
# _already_priced_classification — label boundaries
# ---------------------------------------------------------------------------

class TestAlreadyPricedLabels(unittest.TestCase):

    def test_strong_positive_is_already_priced(self):
        self.assertEqual(
            _already_priced_classification(_PRE_DRIFT_STRONG_PP + 0.1),
            "already_priced",
        )

    def test_weak_positive_is_partially_priced(self):
        mid = (_PRE_DRIFT_STRONG_PP + _PRE_DRIFT_WEAK_PP) / 2
        self.assertEqual(
            _already_priced_classification(mid),
            "partially_priced",
        )

    def test_strong_negative_is_reversal(self):
        self.assertEqual(
            _already_priced_classification(-_PRE_DRIFT_STRONG_PP - 0.1),
            "reversal_on_catalyst",
        )

    def test_weak_negative_is_reversal(self):
        # Anything between -STRONG and -WEAK counts as reversal signal.
        mid = -(_PRE_DRIFT_STRONG_PP + _PRE_DRIFT_WEAK_PP) / 2
        self.assertEqual(
            _already_priced_classification(mid),
            "reversal_on_catalyst",
        )

    def test_flat_tape_near_zero(self):
        self.assertEqual(
            _already_priced_classification(_PRE_DRIFT_FLAT_PP - 0.01),
            "flat_tape",
        )
        self.assertEqual(
            _already_priced_classification(-(_PRE_DRIFT_FLAT_PP - 0.01)),
            "flat_tape",
        )

    def test_unknown_when_none(self):
        self.assertEqual(_already_priced_classification(None), "unknown")


# ---------------------------------------------------------------------------
# compute_surprise_vs_anticipation — empirical already-priced
# ---------------------------------------------------------------------------

def _stress(vix_change_5d=0.0, regime="Mixed"):
    return {
        "regime": regime,
        "raw": {"vix": 17.0, "vix_change_5d": vix_change_5d},
        "signals": {
            "vix_elevated": False, "term_inversion": False,
            "safe_haven_bid": False, "credit_widening": False,
            "breadth_deterioration": False,
        },
    }


class TestSurpriseWithPreDrift(unittest.TestCase):

    def test_strong_pre_drift_forces_already_priced(self):
        # Post-event returns below intraday-share noise floor (|r5|<0.3),
        # so the regime is driven by the pre-event drift signal alone.
        tickers = [{"symbol": "AAA", "role": "beneficiary",
                    "return_1d": 0.1, "return_5d": 0.1}]
        result = compute_surprise_vs_anticipation(
            "realized", tickers=tickers, stress_regime=_stress(),
            pre_event_drift={"AAA": 3.5},
        )
        self.assertEqual(result["already_priced"], "already_priced")
        self.assertEqual(result["pre_event_drift_pct"], 3.5)
        self.assertEqual(result["regime"], "anticipated_confirmation")

    def test_reversal_on_catalyst_surfaces_as_surprise(self):
        tickers = [{"symbol": "AAA", "role": "beneficiary",
                    "return_1d": 2.0, "return_5d": 2.3}]
        result = compute_surprise_vs_anticipation(
            "realized", tickers=tickers, stress_regime=_stress(),
            pre_event_drift={"AAA": -2.5},
        )
        self.assertEqual(result["already_priced"], "reversal_on_catalyst")
        # Should lean toward surprise_shock
        self.assertEqual(result["regime"], "surprise_shock")

    def test_flat_tape_leaves_no_drift_bias(self):
        tickers = [{"symbol": "AAA", "role": "beneficiary",
                    "return_1d": 2.0, "return_5d": 2.2}]
        result = compute_surprise_vs_anticipation(
            "realized", tickers=tickers, stress_regime=_stress(),
            pre_event_drift={"AAA": 0.1},
        )
        self.assertEqual(result["already_priced"], "flat_tape")

    def test_priced_before_string_uses_drift(self):
        tickers = [{"symbol": "AAA", "role": "beneficiary",
                    "return_1d": 0.5, "return_5d": 0.5}]
        result = compute_surprise_vs_anticipation(
            "realized", tickers=tickers, stress_regime=_stress(),
            pre_event_drift={"AAA": 3.2},
        )
        self.assertIn("3.2%", result["priced_before"])

    def test_backward_compat_without_pre_drift_kwarg(self):
        tickers = [{"symbol": "AAA", "role": "beneficiary",
                    "return_1d": 2.0, "return_5d": 2.2}]
        # Old signature path — no pre_event_drift arg.
        result = compute_surprise_vs_anticipation(
            "realized", tickers=tickers, stress_regime=_stress(),
        )
        self.assertIn("regime", result)
        self.assertEqual(result["already_priced"], "unknown")
        self.assertIsNone(result["pre_event_drift_pct"])


# ---------------------------------------------------------------------------
# compute_pre_event_drift — fetch / slicing
# ---------------------------------------------------------------------------

class TestComputePreEventDrift(unittest.TestCase):

    def _build_fake_df(self, closes: list[float], dates: list[str]) -> pd.DataFrame:
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
        return pd.DataFrame({"Close": closes, "Volume": [1e6] * len(closes)}, index=idx)

    def test_drift_computed_from_last_5_bars_when_no_date(self):
        import market_check
        # 6 bars: 100 → 100 → 100 → 100 → 100 → 102 (last 5 is +2%)
        df = self._build_fake_df(
            [100.0, 100.5, 100.2, 100.8, 100.3, 102.0],
            ["2026-04-10", "2026-04-11", "2026-04-12",
             "2026-04-14", "2026-04-15", "2026-04-16"],
        )
        with patch.object(market_check, "_fetch", return_value=df):
            out = market_check.compute_pre_event_drift(["AAA"], event_date=None)
        self.assertIn("AAA", out)
        # (102/100 - 1)*100 = 2.0
        self.assertAlmostEqual(out["AAA"], 2.0, places=1)

    def test_drift_sliced_to_event_date_when_supplied(self):
        import market_check
        df = self._build_fake_df(
            [100.0, 101.0, 101.5, 102.0, 103.0, 104.0, 105.0, 110.0],
            ["2026-04-08", "2026-04-09", "2026-04-10",
             "2026-04-11", "2026-04-14", "2026-04-15",
             "2026-04-16", "2026-04-17"],
        )
        with patch.object(market_check, "_fetch", return_value=df):
            # Cut off at 2026-04-15 — last 5 bars are 100, 101, 101.5, 102, 103, 104
            # Pre_event 5d return = (104 / 100 - 1)*100 = 4.0
            out = market_check.compute_pre_event_drift(["AAA"], event_date="2026-04-15")
        self.assertAlmostEqual(out["AAA"], 4.0, places=1)

    def test_missing_symbol_returns_empty_dict(self):
        import market_check
        with patch.object(market_check, "_fetch", return_value=None):
            out = market_check.compute_pre_event_drift(["AAA"])
        self.assertEqual(out, {})

    def test_empty_input_returns_empty_dict(self):
        import market_check
        self.assertEqual(market_check.compute_pre_event_drift([]), {})
        self.assertEqual(market_check.compute_pre_event_drift(None), {})


# ---------------------------------------------------------------------------
# compute_pre_event_drift — fail closed on invalid pre-event dates (K1A)
#
# The value is labelled *pre-event* drift, so when event_date cannot be
# parsed / normalised / sliced safely the symbol must be SKIPPED, never
# computed from the unsliced (post-event-inclusive) series.  K0 confirmed
# the old `except Exception: pass` slicing path leaked the unsliced drift.
# ---------------------------------------------------------------------------

class TestPreEventDriftFailsClosed(unittest.TestCase):

    # 8 daily bars 2026-04-08 .. 2026-04-17.  Unsliced 5d drift = 8.37%
    # (last 6 closes 101.5 -> 110); sliced at 2026-04-15 = 4.0% (100 -> 104).
    _CLOSES = [100.0, 101.0, 101.5, 102.0, 103.0, 104.0, 105.0, 110.0]
    _DATES = ["2026-04-08", "2026-04-09", "2026-04-10", "2026-04-11",
              "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"]
    _UNSLICED_LEAK_PCT = 8.37   # the post-event value the pre-fix bug leaked
    _PRE_EVENT_PCT = 4.0        # correct value sliced at 2026-04-15

    def _naive_df(self) -> pd.DataFrame:
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in self._DATES])
        return pd.DataFrame(
            {"Close": self._CLOSES, "Volume": [1e6] * len(self._CLOSES)},
            index=idx,
        )

    def _tz_aware_df(self) -> pd.DataFrame:
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in self._DATES], tz="UTC")
        return pd.DataFrame(
            {"Close": self._CLOSES, "Volume": [1e6] * len(self._CLOSES)},
            index=idx,
        )

    def test_valid_iso_date_uses_only_pre_event_bars(self):
        import market_check
        with patch.object(market_check, "_fetch", return_value=self._naive_df()):
            out = market_check.compute_pre_event_drift(["AAA"], event_date="2026-04-15")
        self.assertIn("AAA", out)
        self.assertAlmostEqual(out["AAA"], self._PRE_EVENT_PCT, places=2)
        # Explicitly the sliced value, not the unsliced post-event drift.
        self.assertNotAlmostEqual(out["AAA"], self._UNSLICED_LEAK_PCT, places=1)

    def test_malformed_event_date_skips_symbol(self):
        import market_check
        with patch.object(market_check, "_fetch", return_value=self._naive_df()):
            out = market_check.compute_pre_event_drift(["AAA"], event_date="not-a-date")
        # Fail closed: an unparseable date must not leak the unsliced series.
        self.assertNotIn("AAA", out)
        self.assertEqual(out, {})

    def test_tz_suffixed_iso_datetime_no_post_event_leak(self):
        import market_check
        with patch.object(market_check, "_fetch", return_value=self._naive_df()):
            out = market_check.compute_pre_event_drift(
                ["AAA"], event_date="2026-04-15T14:30:00Z")
        # Normalised safely to the same pre-event window — never the leak.
        self.assertIn("AAA", out)
        self.assertAlmostEqual(out["AAA"], self._PRE_EVENT_PCT, places=2)

    def test_tz_aware_input_never_falls_through_to_unsliced(self):
        import market_check
        with patch.object(market_check, "_fetch", return_value=self._naive_df()):
            out = market_check.compute_pre_event_drift(
                ["AAA"], event_date="2026-04-15T14:30:00Z")
        # Whether the fix normalises or skips, the result must never equal
        # the unsliced post-event drift.
        self.assertNotAlmostEqual(
            out.get("AAA", 0.0), self._UNSLICED_LEAK_PCT, places=1)

    def test_date_before_window_is_honest_skip(self):
        import market_check
        with patch.object(market_check, "_fetch", return_value=self._naive_df()):
            out = market_check.compute_pre_event_drift(["AAA"], event_date="2020-01-01")
        # No usable pre-event bars -> honest empty, not a leak.
        self.assertEqual(out, {})

    def test_slice_failure_skips_symbol_not_unsliced(self):
        # A tz-aware price index vs a naive cutoff makes the ``<=`` compare
        # raise; the fix must fail closed (skip), not swallow-and-continue
        # with the unsliced series.
        import market_check
        with patch.object(market_check, "_fetch", return_value=self._tz_aware_df()):
            out = market_check.compute_pre_event_drift(["AAA"], event_date="2026-04-15")
        self.assertNotIn("AAA", out)
        self.assertEqual(out, {})

    def test_no_silent_except_pass_in_drift_slicing(self):
        import inspect
        import re
        import market_check
        src = inspect.getsource(market_check.compute_pre_event_drift)
        self.assertIsNone(
            re.search(r"except[^\n]*:\s*\n\s*pass\b", src),
            "compute_pre_event_drift must not swallow parse/slice failures "
            "with `except ...: pass` (that leaks post-event bars into a "
            "value labelled pre-event)",
        )


if __name__ == "__main__":
    unittest.main()
