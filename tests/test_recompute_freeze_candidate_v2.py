"""Tests for ``scripts/recompute_freeze_candidate_v2.py``.

Pins the contract:

* ``recompute_row`` raises ``RuntimeError`` on cache miss, insufficient
  estimation window, or unaligned ``first_trading_date``.
* ``recompute_row`` reproduces a known-good BHAR from a synthetic
  fixed-drift price path.
* ``compare_to_artifact`` reports per-row pass/fail with tight
  tolerances; mismatches in AR, SAR, p, or q are surfaced.
* ``run_invariant_checks`` enforces the v2.1 structural rules
  (method, CENX date, demo_wiring_note, all q < 0.05).
* End-to-end orchestration: ``recompute_cohort`` + ``compare_to_artifact``
  pass against a synthetic 1-row fixture built to be self-consistent.

All tests use synthetic fixtures + a fake cache reader. None touch
the live ``events.db`` or ``price_cache``.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.recompute_freeze_candidate_v2 import (  # noqa: E402
    _align_pair,
    _is_close,
    _window_bounds,
    compare_to_artifact,
    recompute_cohort,
    recompute_row,
    run_invariant_checks,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


def _business_dates(start: date, n: int) -> list[str]:
    """Return ``n`` consecutive business-day ISO date strings."""
    out: list[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _make_fake_cache(bars_by_ticker: dict[str, list[tuple[str, float]]]):
    """Return a callable that mimics the production cache reader.

    The callable filters by ``[start, end]`` (inclusive). Returns
    ``None`` on empty-slice / unknown-ticker so the recompute code's
    cache-miss branch is exercised.
    """
    def reader(ticker: str, start: str, end: str):
        bars = bars_by_ticker.get(ticker)
        if not bars:
            return None
        dates: list[str] = []
        closes: list[float] = []
        for d, c in bars:
            if start <= d <= end:
                dates.append(d)
                closes.append(c)
        if not dates:
            return None
        return dates, closes
    return reader


def _build_drift_path_with_event_jump(
    dates: list[str],
    *,
    start_price: float,
    daily_drift: float,
    event_idx: int | None,
    event_extra: float,
    noise: float = 0.0,
) -> list[tuple[str, float]]:
    """Geometric path: each day multiplies by ``(1 + daily_drift +/- noise)``.

    ``noise`` alternates sign by day index so the daily-return series is
    NOT constant — this is required for ``compute_event_study``'s
    sigma_ar_daily to be > 0 (otherwise SAR is None and tests that
    assert finite SAR fail vacuously).

    On ``event_idx`` (when not ``None``) the price additionally
    multiplies by ``(1 + event_extra)`` — used to inject a known AR
    shock for the test.
    """
    out: list[tuple[str, float]] = [(dates[0], start_price)]
    for i in range(1, len(dates)):
        prev = out[-1][1]
        sign = 1.0 if (i % 2 == 0) else -1.0
        d = daily_drift + sign * noise
        mult = 1.0 + d
        if event_idx is not None and i == event_idx:
            mult *= (1.0 + event_extra)
        out.append((dates[i], prev * mult))
    return out


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


class TestIsClose(unittest.TestCase):
    def test_abs_match(self):
        self.assertTrue(_is_close(1.0, 1.0, abs_tol=0.0))
        self.assertTrue(_is_close(1.0, 1.0001, abs_tol=1e-3))
        self.assertFalse(_is_close(1.0, 1.01, abs_tol=1e-3))

    def test_rel_match_for_small_values(self):
        self.assertTrue(_is_close(1.0e-6, 1.001e-6, abs_tol=0.0, rel_tol=1e-2))
        self.assertFalse(_is_close(1.0e-6, 2.0e-6, abs_tol=0.0, rel_tol=1e-2))

    def test_none_propagates_to_false(self):
        self.assertFalse(_is_close(None, 1.0, abs_tol=1.0))
        self.assertFalse(_is_close(1.0, None, abs_tol=1.0))

    def test_combined_abs_and_rel(self):
        # abs_tol used when expected is small; rel_tol used when expected is large.
        self.assertTrue(_is_close(0.0, 1e-12, abs_tol=1e-9, rel_tol=1e-3))
        self.assertTrue(_is_close(1000.0, 1000.5, abs_tol=1e-9, rel_tol=1e-3))


class TestWindowBounds(unittest.TestCase):
    def test_basic_window(self):
        s, e = _window_bounds("2020-01-15")
        # 2020-01-15 minus 200 calendar days
        self.assertEqual(s, (date(2020, 1, 15) - timedelta(days=200)).isoformat())
        # plus 60 calendar days
        self.assertEqual(e, (date(2020, 1, 15) + timedelta(days=60)).isoformat())

    def test_accepts_iso_with_timestamp(self):
        s, e = _window_bounds("2020-01-15T00:00:00")
        self.assertEqual(s, (date(2020, 1, 15) - timedelta(days=200)).isoformat())
        self.assertEqual(e, (date(2020, 1, 15) + timedelta(days=60)).isoformat())


class TestAlignPair(unittest.TestCase):
    def test_intersection_keeps_only_common(self):
        a_d = ["2020-01-01", "2020-01-02", "2020-01-03"]
        a_c = [10.0, 11.0, 12.0]
        b_d = ["2020-01-02", "2020-01-03", "2020-01-06"]
        b_c = [100.0, 110.0, 120.0]
        common, a_aligned, b_aligned = _align_pair(a_d, a_c, b_d, b_c)
        self.assertEqual(common, ["2020-01-02", "2020-01-03"])
        # asset closes for the two common dates (a_c[1], a_c[2])
        self.assertEqual(list(a_aligned), [11.0, 12.0])
        # benchmark closes for the same two common dates (b_c[0], b_c[1])
        self.assertEqual(list(b_aligned), [100.0, 110.0])

    def test_empty_intersection_returns_empty(self):
        common, a, b = _align_pair(["2020-01-01"], [1.0], ["2020-01-02"], [2.0])
        self.assertEqual(common, [])
        self.assertEqual(list(a), [])
        self.assertEqual(list(b), [])


# ---------------------------------------------------------------------------
# recompute_row tests against fake cache
# ---------------------------------------------------------------------------


class TestRecomputeRow(unittest.TestCase):
    def test_known_positive_ar_reproduces_within_tolerance(self):
        """Synthetic: asset drifts +0.05%/day with alternating ±0.1%
        noise; benchmark drifts +0.01%/day flat. On the first_trading
        day, asset gets an extra +5% jump. The h=1 AR (BHAR) must
        match a closed-form derived from the path's actual last two
        prices, and SAR/p must be finite (sigma_ar_daily > 0 because
        of the noise alternation).
        """
        dates = _business_dates(date(2020, 1, 1), 80)
        first_trading_idx = 65  # leaves 64 prior bars, > 60 estimation window
        first_trading = dates[first_trading_idx]
        bars_a = _build_drift_path_with_event_jump(
            dates, start_price=100.0, daily_drift=0.0005, noise=0.001,
            event_idx=first_trading_idx, event_extra=0.05,
        )
        bars_b = _build_drift_path_with_event_jump(
            dates, start_price=50.0, daily_drift=0.0001, noise=0.0,
            event_idx=None, event_extra=0.0,
        )
        reader = _make_fake_cache({"AAA": bars_a, "BBB": bars_b})

        row = recompute_row(
            primary_ticker="AAA", benchmark_ticker="BBB",
            first_trading_iso=first_trading, cache_reader=reader,
        )

        # Closed-form expected AR derived from the actual path's last
        # two prices (robust to whatever noise pattern the builder used)
        p_a_pre = bars_a[first_trading_idx - 1][1]
        p_a_evt = bars_a[first_trading_idx][1]
        p_b_pre = bars_b[first_trading_idx - 1][1]
        p_b_evt = bars_b[first_trading_idx][1]
        expected_ar_pct = (
            (p_a_evt / p_a_pre - 1.0) - (p_b_evt / p_b_pre - 1.0)
        ) * 100.0
        self.assertAlmostEqual(row["h1_AR_pct"], expected_ar_pct, places=9)

        # SAR / p sanity: SAR > 0 (positive AR + positive sigma), p finite.
        # p may underflow to exactly 0.0 when SAR is extremely large
        # (Phi(50) saturates to 1.0 in float64) — allow p >= 0.
        self.assertIsNotNone(row["h1_SAR"])
        self.assertGreater(row["h1_SAR"], 0.0)
        self.assertTrue(math.isfinite(row["h1_SAR"]))
        self.assertIsNotNone(row["h1_p"])
        self.assertGreaterEqual(row["h1_p"], 0.0)
        self.assertLess(row["h1_p"], 1.0)

    def test_raises_on_primary_cache_miss(self):
        reader = _make_fake_cache({})  # empty
        with self.assertRaisesRegex(RuntimeError, r"cache miss for primary"):
            recompute_row(
                primary_ticker="ZZZ", benchmark_ticker="QQQ",
                first_trading_iso="2020-01-15", cache_reader=reader,
            )

    def test_raises_on_benchmark_cache_miss(self):
        dates = _business_dates(date(2020, 1, 1), 5)
        bars = [(d, 100.0) for d in dates]
        reader = _make_fake_cache({"AAA": bars})  # no benchmark
        with self.assertRaisesRegex(RuntimeError, r"cache miss for benchmark"):
            recompute_row(
                primary_ticker="AAA", benchmark_ticker="QQQ",
                first_trading_iso=dates[2], cache_reader=reader,
            )

    def test_raises_on_first_trading_not_aligned(self):
        # 80 business days starting 2020-01-01: cache contains weekdays
        # but no weekends. Pick a Saturday inside the cache's date span
        # so the cache reader returns the surrounding weekday bars (the
        # window filter is purely date-string range), but Saturday is
        # not in the aligned date list — exercising the "not in aligned
        # dates" branch.
        dates = _business_dates(date(2020, 1, 1), 80)
        bars = [(d, 100.0 + i) for i, d in enumerate(dates)]
        reader = _make_fake_cache({"AAA": bars, "BBB": bars})
        sat_in_range = "2020-01-04"  # Saturday inside the bar range
        self.assertNotIn(sat_in_range, dates,
                         "fixture sanity: Saturday must not be in the bar list")
        with self.assertRaisesRegex(RuntimeError, r"not in aligned dates"):
            recompute_row(
                primary_ticker="AAA", benchmark_ticker="BBB",
                first_trading_iso=sat_in_range, cache_reader=reader,
            )

    def test_raises_on_insufficient_estimation_window(self):
        dates = _business_dates(date(2020, 1, 1), 30)  # only 30 bars
        bars = [(d, 100.0 + i) for i, d in enumerate(dates)]
        reader = _make_fake_cache({"AAA": bars, "BBB": bars})
        with self.assertRaisesRegex(RuntimeError, r"insufficient estimation window"):
            recompute_row(
                primary_ticker="AAA", benchmark_ticker="BBB",
                # first_trading near start → only ~10 pre-event bars
                first_trading_iso=dates[10], cache_reader=reader,
            )


# ---------------------------------------------------------------------------
# compare_to_artifact tests
# ---------------------------------------------------------------------------


class TestCompareToArtifact(unittest.TestCase):
    def _artifact_row(self, **overrides):
        base = {
            "primary_ticker": "AAA",
            "h1_AR_pct": 1.5, "h1_SAR": 2.0,
            "h1_p": 0.01, "h1_q_bh": 0.05,
        }
        base.update(overrides)
        return base

    def _rec_row(self, **overrides):
        base = {
            "primary_ticker": "AAA",
            "h1_AR_pct": 1.5, "h1_SAR": 2.0, "h1_p": 0.01,
        }
        base.update(overrides)
        return base

    def test_exact_match_passes(self):
        res = compare_to_artifact(
            artifact_candidates=[self._artifact_row()],
            recomputed_rows=[self._rec_row()],
            recomputed_qs=[0.05],
        )
        self.assertTrue(res["all_pass"])
        self.assertTrue(res["rows"][0]["ok"])

    def test_within_tolerance_passes(self):
        # AR drifts by 1e-4 (< 5e-4 abs tol); SAR by 1e-4; p by 1e-6 rel;
        # q by 1e-6 rel.
        res = compare_to_artifact(
            artifact_candidates=[self._artifact_row()],
            recomputed_rows=[self._rec_row(
                h1_AR_pct=1.5001, h1_SAR=2.0001, h1_p=0.0100001,
            )],
            recomputed_qs=[0.0500001],
        )
        self.assertTrue(res["all_pass"])

    def test_ar_mismatch_flagged(self):
        res = compare_to_artifact(
            artifact_candidates=[self._artifact_row()],
            recomputed_rows=[self._rec_row(h1_AR_pct=3.0)],
            recomputed_qs=[0.05],
        )
        self.assertFalse(res["all_pass"])
        self.assertFalse(res["rows"][0]["h1_AR_pct"]["match"])
        self.assertTrue(res["rows"][0]["h1_SAR"]["match"])

    def test_sar_mismatch_flagged(self):
        res = compare_to_artifact(
            artifact_candidates=[self._artifact_row()],
            recomputed_rows=[self._rec_row(h1_SAR=10.0)],
            recomputed_qs=[0.05],
        )
        self.assertFalse(res["all_pass"])
        self.assertFalse(res["rows"][0]["h1_SAR"]["match"])

    def test_p_mismatch_flagged_under_rel_tol(self):
        # 50% drift in p must be flagged (rel_tol is 1e-3 == 0.1%)
        res = compare_to_artifact(
            artifact_candidates=[self._artifact_row(h1_p=1e-6)],
            recomputed_rows=[self._rec_row(h1_p=1.5e-6)],
            recomputed_qs=[0.05],
        )
        self.assertFalse(res["all_pass"])
        self.assertFalse(res["rows"][0]["h1_p"]["match"])

    def test_q_mismatch_flagged(self):
        res = compare_to_artifact(
            artifact_candidates=[self._artifact_row()],
            recomputed_rows=[self._rec_row()],
            recomputed_qs=[0.99],
        )
        self.assertFalse(res["all_pass"])
        self.assertFalse(res["rows"][0]["h1_q_bh"]["match"])

    def test_missing_recomputed_row_flagged(self):
        res = compare_to_artifact(
            artifact_candidates=[self._artifact_row()],
            recomputed_rows=[],
            recomputed_qs=[],
        )
        self.assertFalse(res["all_pass"])
        self.assertEqual(res["rows"][0]["error"], "no recomputed row")


# ---------------------------------------------------------------------------
# Invariant tests
# ---------------------------------------------------------------------------


_EXPECTED_DEMO = (
    "Section C Demo v1 is unchanged; this artifact is not wired to demo."
)


def _make_artifact(*,
                   methods="production_bhar",
                   cenx_first="2018-04-09",
                   demo_note=_EXPECTED_DEMO,
                   q_values=None,
                   ticker_list=("WHR", "CENX", "FSLR", "TXT", "RIO")):
    return {
        "demo_wiring_note": demo_note,
        "candidates": [
            {
                "primary_ticker": t,
                "method": methods,
                "first_trading_date":
                    (cenx_first if t == "CENX" else "2020-01-01"),
            }
            for t in ticker_list
        ],
        "cohort_statistics": {
            "q_values_summary": q_values or {
                "WHR": 0.01, "CENX": 0.001, "FSLR": 1e-6,
                "TXT": 0.01, "RIO": 0.04,
            },
        },
    }


class TestInvariants(unittest.TestCase):
    def test_well_formed_passes(self):
        res = run_invariant_checks(_make_artifact())
        self.assertTrue(res["ok"])
        self.assertTrue(res["all_method_production_bhar"])
        self.assertTrue(res["cenx_first_trading_is_apr9"])
        self.assertTrue(res["demo_wiring_note_preserved"])
        self.assertTrue(res["all_artifact_q_below_005"])

    def test_method_violation_flagged(self):
        art = _make_artifact()
        art["candidates"][0]["method"] = "market_model_ols"
        res = run_invariant_checks(art)
        self.assertFalse(res["ok"])
        self.assertFalse(res["all_method_production_bhar"])

    def test_cenx_wrong_date_flagged(self):
        res = run_invariant_checks(_make_artifact(cenx_first="2018-04-06"))
        self.assertFalse(res["ok"])
        self.assertFalse(res["cenx_first_trading_is_apr9"])

    def test_demo_note_altered_flagged(self):
        res = run_invariant_checks(_make_artifact(
            demo_note="wired to demo now",
        ))
        self.assertFalse(res["ok"])
        self.assertFalse(res["demo_wiring_note_preserved"])

    def test_q_above_005_flagged(self):
        res = run_invariant_checks(_make_artifact(q_values={
            "WHR": 0.06, "CENX": 0.001, "FSLR": 1e-6,
            "TXT": 0.01, "RIO": 0.04,
        }))
        self.assertFalse(res["ok"])
        self.assertFalse(res["all_artifact_q_below_005"])

    def test_wrong_candidate_count_flags_method_check(self):
        # Only 3 candidates instead of the expected 5
        res = run_invariant_checks(_make_artifact(
            ticker_list=("WHR", "CENX", "FSLR"),
        ))
        self.assertFalse(res["ok"])
        self.assertFalse(res["all_method_production_bhar"])


# ---------------------------------------------------------------------------
# End-to-end: recompute_cohort + compare_to_artifact against a fake cache
# ---------------------------------------------------------------------------


class TestEndToEndAgainstFakeCache(unittest.TestCase):
    def test_recompute_cohort_matches_self_consistent_synthetic_artifact(self):
        """Build a synthetic 1-row 'cohort' against a fake cache, then
        construct an artifact that records exactly what recompute_row
        produces. The orchestrator's compare step should pass.

        Demonstrates that recompute_cohort + compare_to_artifact agree
        when the data is internally consistent — i.e., the pipeline is
        not introducing spurious drift.
        """
        dates = _business_dates(date(2019, 1, 1), 80)
        first_trading_idx = 65
        first_trading = dates[first_trading_idx]
        bars_a = _build_drift_path_with_event_jump(
            dates, start_price=100.0, daily_drift=0.0005, noise=0.001,
            event_idx=first_trading_idx, event_extra=0.05,
        )
        bars_b = _build_drift_path_with_event_jump(
            dates, start_price=50.0, daily_drift=0.0001, noise=0.0,
            event_idx=None, event_extra=0.0,
        )
        reader = _make_fake_cache({"AAA": bars_a, "BBB": bars_b})

        # First compute what the engine will produce
        rec_row = recompute_row(
            primary_ticker="AAA", benchmark_ticker="BBB",
            first_trading_iso=first_trading, cache_reader=reader,
        )
        from stats.fdr import bh_adjust
        bh = bh_adjust([rec_row["h1_p"]], alpha=0.05)
        q = bh["adjusted"][0]

        # Build an artifact whose recorded values exactly match
        artifact = {
            "demo_wiring_note": _EXPECTED_DEMO,
            "candidates": [{
                "primary_ticker": "AAA",
                "benchmark_ticker": "BBB",
                "method": "production_bhar",
                "first_trading_date": first_trading,
                "h1_AR_pct": rec_row["h1_AR_pct"],
                "h1_SAR": rec_row["h1_SAR"],
                "h1_p": rec_row["h1_p"],
                "h1_q_bh": q,
            }],
            "cohort_statistics": {
                "q_values_summary": {"AAA": q},
            },
        }

        # Run the orchestrator's recompute step + compare
        rows, qs = recompute_cohort(artifact, cache_reader=reader)
        cmp_ = compare_to_artifact(
            artifact_candidates=artifact["candidates"],
            recomputed_rows=rows,
            recomputed_qs=qs,
        )
        self.assertTrue(cmp_["all_pass"], f"got: {cmp_}")

    def test_recompute_cohort_flags_artifact_drift(self):
        """Same setup, but the artifact records a wrong AR. The
        comparison must surface the mismatch."""
        dates = _business_dates(date(2019, 1, 1), 80)
        first_trading_idx = 65
        first_trading = dates[first_trading_idx]
        bars_a = _build_drift_path_with_event_jump(
            dates, start_price=100.0, daily_drift=0.0005, noise=0.001,
            event_idx=first_trading_idx, event_extra=0.05,
        )
        bars_b = _build_drift_path_with_event_jump(
            dates, start_price=50.0, daily_drift=0.0001, noise=0.0,
            event_idx=None, event_extra=0.0,
        )
        reader = _make_fake_cache({"AAA": bars_a, "BBB": bars_b})

        artifact = {
            "demo_wiring_note": _EXPECTED_DEMO,
            "candidates": [{
                "primary_ticker": "AAA",
                "benchmark_ticker": "BBB",
                "method": "production_bhar",
                "first_trading_date": first_trading,
                # Deliberately wrong values:
                "h1_AR_pct": 99.0, "h1_SAR": 99.0,
                "h1_p": 0.5, "h1_q_bh": 0.5,
            }],
            "cohort_statistics": {"q_values_summary": {"AAA": 0.5}},
        }

        rows, qs = recompute_cohort(artifact, cache_reader=reader)
        cmp_ = compare_to_artifact(
            artifact_candidates=artifact["candidates"],
            recomputed_rows=rows,
            recomputed_qs=qs,
        )
        self.assertFalse(cmp_["all_pass"])
        self.assertFalse(cmp_["rows"][0]["h1_AR_pct"]["match"])


if __name__ == "__main__":
    unittest.main()
