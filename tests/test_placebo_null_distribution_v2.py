"""Tests for ``scripts/placebo_null_distribution_v2.py``.

Pins the contract:

* ``detect_contiguous_block_for_index`` returns the maximal contiguous
  block of aligned dates (no internal calendar gap > 7 days).
* ``compute_eligible_fake_indices`` enforces:
  - estimation window inside the contiguous block (60+ pre-event bars),
  - h=1 inside the contiguous block (1+ post-event bar),
  - exclusion zone around the real event so the fake's estimation
    window or immediate horizon never overlaps the real event.
* ``_event_study_h1_p`` returns a finite p in [0, 1] on synthetic
  data, and None on insufficient estimation window.
* ``run_placebo_draws`` is deterministic given a seed and produces
  the expected fraction-based output schema.
* ``run_all`` returns ``ok=True`` against a synthetic fake-cache
  fixture and ``ok=False`` (with setup_errors) when a row has zero
  eligible fakes.

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
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.placebo_null_distribution_v2 import (  # noqa: E402
    _align_pair,
    _event_study_h1_p,
    build_per_row_state,
    compute_eligible_fake_indices,
    detect_contiguous_block_for_index,
    load_v2_cohort_rows,
    run_all,
    run_placebo_draws,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _business_dates(start: date, n: int) -> list[str]:
    out: list[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _make_fake_cache(bars_by_ticker):
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


def _drift_path(
    dates: list[str], *, start: float, drift: float, noise: float = 0.0,
) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = [(dates[0], start)]
    for i in range(1, len(dates)):
        prev = out[-1][1]
        sign = 1.0 if (i % 2 == 0) else -1.0
        d = drift + sign * noise
        out.append((dates[i], prev * (1.0 + d)))
    return out


# ---------------------------------------------------------------------------
# detect_contiguous_block_for_index
# ---------------------------------------------------------------------------


class TestContiguousBlockDetection(unittest.TestCase):
    def test_full_contiguous_range(self):
        dates = _business_dates(date(2020, 1, 1), 30)
        s, e = detect_contiguous_block_for_index(dates, target_idx=15)
        self.assertEqual(s, 0)
        self.assertEqual(e, 29)

    def test_breaks_at_large_gap(self):
        # 10 business days, then a 1-year gap, then 10 more
        early = _business_dates(date(2020, 1, 1), 10)
        late = _business_dates(date(2021, 1, 1), 10)
        dates = early + late
        s, e = detect_contiguous_block_for_index(dates, target_idx=4)
        self.assertEqual(s, 0)
        self.assertEqual(e, 9)  # block ends at the last pre-gap date
        s2, e2 = detect_contiguous_block_for_index(dates, target_idx=15)
        self.assertEqual(s2, 10)  # block starts at the first post-gap date
        self.assertEqual(e2, 19)

    def test_target_at_boundary(self):
        dates = _business_dates(date(2020, 1, 1), 5)
        s, e = detect_contiguous_block_for_index(dates, target_idx=0)
        self.assertEqual((s, e), (0, 4))
        s, e = detect_contiguous_block_for_index(dates, target_idx=4)
        self.assertEqual((s, e), (0, 4))


# ---------------------------------------------------------------------------
# compute_eligible_fake_indices
# ---------------------------------------------------------------------------


class TestEligibility(unittest.TestCase):
    def test_basic_eligibility_with_real_event_in_middle(self):
        # 180 business dates; real event in the middle. With 60 bars
        # estimation + 20 td exclusion after real event, eligible
        # indices should be in [60, real_idx - 60 - 1] U [real_idx + 21, 178].
        dates = _business_dates(date(2020, 1, 1), 180)
        real_event_idx = 100
        real_event_date = dates[real_event_idx]
        eligible = compute_eligible_fake_indices(dates, real_event_date)
        # Pre-real (F < R - 60 = 40): eligible if F >= 60 → empty (60 > 39)
        # Post-real (F > R + 20 = 120): eligible if F <= 178 → range(121, 179)
        self.assertEqual(eligible, list(range(121, 179)))

    def test_real_event_too_close_to_start_yields_post_real_only(self):
        dates = _business_dates(date(2020, 1, 1), 200)
        real_event_idx = 80  # 80 < 60 + 60, so no pre-real fakes
        real_event_date = dates[real_event_idx]
        eligible = compute_eligible_fake_indices(dates, real_event_date)
        # Pre-real requires F < R-60 = 20, but F must also be >= 60 → empty
        # Post-real requires F > R+20 = 100, F <= 198
        self.assertEqual(eligible, list(range(101, 199)))

    def test_no_eligible_when_real_event_at_start(self):
        dates = _business_dates(date(2020, 1, 1), 80)
        real_event_idx = 60  # exactly at minimum estimation cutoff
        real_event_date = dates[real_event_idx]
        eligible = compute_eligible_fake_indices(dates, real_event_date)
        # Pre-real: F < 0 → empty
        # Post-real: F > 80 → empty
        self.assertEqual(eligible, [])

    def test_real_event_missing_returns_empty(self):
        dates = _business_dates(date(2020, 1, 1), 80)
        eligible = compute_eligible_fake_indices(dates, "2030-01-01")
        self.assertEqual(eligible, [])

    def test_eligibility_constrained_to_contiguous_block(self):
        # 80 dates, then 2-year gap, then 80 more; real event in late block.
        early = _business_dates(date(2020, 1, 1), 80)
        late = _business_dates(date(2022, 1, 1), 80)
        dates = early + late
        # real event in late block, index 80+40=120
        real_event_idx = 120
        real_event_date = dates[real_event_idx]
        eligible = compute_eligible_fake_indices(dates, real_event_date)
        # late block is indices 80..159. Within that block:
        #   min_f = 80 + 60 = 140
        #   max_f = 158
        # Real event at 120 is WITHIN this block (well, actually 120 < 140
        # is below min_f anyway, but algorithmically real_idx is the anchor).
        # Pre-real fakes: F < 60 → none in [140..158]
        # Post-real fakes: F > 140 → [141..158]
        # So eligible should be [141..158]
        self.assertEqual(eligible, list(range(141, 159)))
        # Specifically, no fake from the early block should appear
        self.assertTrue(all(i >= 80 for i in eligible))


# ---------------------------------------------------------------------------
# _event_study_h1_p
# ---------------------------------------------------------------------------


class TestEventStudyH1P(unittest.TestCase):
    def _build_pair(self, n_bars: int, event_idx: int, event_shock: float):
        """Return aligned numpy arrays for asset+benchmark with a
        +event_shock multiplicative shock on the asset on event_idx.
        """
        import numpy as np
        dates = _business_dates(date(2020, 1, 1), n_bars)
        bars_a = _drift_path(dates, start=100.0, drift=0.0005, noise=0.001)
        bars_b = _drift_path(dates, start=50.0,  drift=0.0001, noise=0.0)
        # Inject shock at event_idx
        prev_a = bars_a[event_idx - 1][1]
        bars_a[event_idx] = (
            dates[event_idx],
            prev_a * (1.0 + 0.0005 + 0.001 * (1.0 if event_idx % 2 == 0 else -1.0)) * (1.0 + event_shock),
        )
        # Re-cascade from event_idx onward
        for i in range(event_idx + 1, n_bars):
            prev = bars_a[i - 1][1]
            sign = 1.0 if (i % 2 == 0) else -1.0
            bars_a[i] = (dates[i], prev * (1.0 + 0.0005 + 0.001 * sign))
        _, asset_arr, bench_arr = _align_pair(
            [d for d, _ in bars_a], [c for _, c in bars_a],
            [d for d, _ in bars_b], [c for _, c in bars_b],
        )
        return asset_arr, bench_arr

    def test_p_finite_and_in_unit_interval_with_real_shock(self):
        asset, bench = self._build_pair(n_bars=80, event_idx=65, event_shock=0.05)
        # production convention: pass first_trading_idx = 65;
        # event_index = 64; horizon 1 reads (asset[65], bench[65]).
        p = _event_study_h1_p(asset, bench, first_trading_idx=65)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLess(p, 1.0)
        self.assertTrue(math.isfinite(p))

    def test_returns_none_for_insufficient_estimation(self):
        asset, bench = self._build_pair(n_bars=80, event_idx=30, event_shock=0.05)
        # first_trading_idx=30 → event_index=29 < 60 → insufficient
        p = _event_study_h1_p(asset, bench, first_trading_idx=30)
        self.assertIsNone(p)

    def test_returns_none_for_horizon_overrun(self):
        asset, bench = self._build_pair(n_bars=80, event_idx=79, event_shock=0.05)
        # first_trading_idx=79 means horizon h=1 wants index 80, out of range
        # Actually production engine takes event_index = first_trading_idx - 1 = 78
        # h=1 wants index 79 which is the last index, valid. But first_trading_idx
        # of len(asset) (=80) would overflow.
        p = _event_study_h1_p(asset, bench, first_trading_idx=len(asset))
        self.assertIsNone(p)


# ---------------------------------------------------------------------------
# run_placebo_draws determinism + output schema
# ---------------------------------------------------------------------------


def _make_per_row_state(n_rows: int = 5, n_bars: int = 200):
    """Build per_row_state with synthetic paths suitable for the placebo
    runner. Each row has the same eligibility range (positions ~100..198)
    so we can verify determinism and output shapes without depending on
    the production cache reader.
    """
    import numpy as np
    state = []
    for i in range(n_rows):
        dates = _business_dates(date(2020, 1, 1), n_bars)
        bars_a = _drift_path(dates, start=100.0 + i, drift=0.0005, noise=0.001)
        bars_b = _drift_path(dates, start=50.0 + i,  drift=0.0001, noise=0.0)
        _, asset_arr, bench_arr = _align_pair(
            [d for d, _ in bars_a], [c for _, c in bars_a],
            [d for d, _ in bars_b], [c for _, c in bars_b],
        )
        # Eligibility: just use [60, n_bars-2] for simplicity
        eligible = list(range(60, n_bars - 1))
        state.append({
            "row": {
                "primary_ticker": f"P{i}",
                "benchmark_ticker": f"B{i}",
                "real_event_date": dates[100],
            },
            "aligned_dates": dates,
            "asset_aligned": asset_arr,
            "bench_aligned": bench_arr,
            "real_event_idx": 100,
            "aligned_total": n_bars,
            "eligible_fake_indices": eligible,
            "eligible_count": len(eligible),
        })
    return state


class TestRunPlaceboDraws(unittest.TestCase):
    def test_output_schema(self):
        state = _make_per_row_state()
        out = run_placebo_draws(state, n_draws=10, seed=0)
        self.assertTrue(out["ok"])
        for k in (
            "n_draws", "alpha", "row_count",
            "fraction_all_q_under_alpha", "fraction_at_least_4",
            "fraction_at_least_3", "median_discoveries_per_draw",
            "median_min_q_per_draw",
            "count_all_q_under_alpha", "count_at_least_4", "count_at_least_3",
        ):
            self.assertIn(k, out)
        self.assertEqual(out["n_draws"], 10)
        self.assertEqual(out["row_count"], 5)

    def test_seed_determinism(self):
        state_a = _make_per_row_state()
        state_b = _make_per_row_state()
        a = run_placebo_draws(state_a, n_draws=20, seed=42)
        b = run_placebo_draws(state_b, n_draws=20, seed=42)
        self.assertEqual(
            a["count_all_q_under_alpha"], b["count_all_q_under_alpha"],
        )
        self.assertEqual(a["count_at_least_4"], b["count_at_least_4"])
        self.assertAlmostEqual(
            a["fraction_all_q_under_alpha"],
            b["fraction_all_q_under_alpha"],
        )

    def test_different_seeds_can_differ(self):
        state = _make_per_row_state()
        a = run_placebo_draws(state, n_draws=50, seed=0)
        b = run_placebo_draws(state, n_draws=50, seed=999)
        # They MAY tie by coincidence but typically differ on at least one stat
        differ = (
            a["count_all_q_under_alpha"] != b["count_all_q_under_alpha"]
            or a["median_min_q_per_draw"] != b["median_min_q_per_draw"]
        )
        # Use a loose assertion: at minimum, the median_min_q numerics should
        # not be byte-identical when the seeds differ
        self.assertTrue(
            differ
            or a["median_min_q_per_draw"] is None,
            "different seeds produced bit-identical placebo output",
        )

    def test_fail_when_row_has_zero_eligible(self):
        state = _make_per_row_state()
        state[2]["eligible_fake_indices"] = []
        out = run_placebo_draws(state, n_draws=10, seed=0)
        self.assertFalse(out["ok"])
        self.assertIn("error", out)


# ---------------------------------------------------------------------------
# run_all end-to-end with a synthetic fake cache + temp artifact
# ---------------------------------------------------------------------------


class TestRunAll(unittest.TestCase):
    def _write_artifact_with_rows(self, rows):
        path = os.path.join(
            tempfile.gettempdir(),
            f"placebo_test_artifact_{uuid.uuid4().hex}.json",
        )
        artifact = {
            "candidates": [
                {
                    "primary_ticker":     r["primary"],
                    "benchmark_ticker":   r["bench"],
                    "first_trading_date": r["real_event"],
                }
                for r in rows
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(artifact, fh)
        return path

    def test_run_all_ok_against_synthetic(self):
        dates = _business_dates(date(2020, 1, 1), 200)
        # Build 5 distinct (ticker, benchmark) pairs with synthetic paths
        rows = []
        bars_by_ticker = {}
        for i in range(5):
            p_tkr, b_tkr = f"P{i}", f"B{i}"
            bars_a = _drift_path(dates, start=100.0 + i, drift=0.0005, noise=0.001)
            bars_b = _drift_path(dates, start=50.0 + i,  drift=0.0001, noise=0.0)
            bars_by_ticker[p_tkr] = bars_a
            bars_by_ticker[b_tkr] = bars_b
            rows.append({
                "primary":    p_tkr,
                "bench":      b_tkr,
                "real_event": dates[100],
            })
        reader = _make_fake_cache(bars_by_ticker)
        artifact_path = self._write_artifact_with_rows(rows)
        try:
            result = run_all(
                artifact_path, n_draws=20, seed=0, cache_reader=reader,
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(len(result["per_row_diagnostics"]), 5)
            self.assertEqual(result["results"]["n_draws"], 20)
            for d in result["per_row_diagnostics"]:
                self.assertGreater(d["eligible_count"], 0)
        finally:
            os.remove(artifact_path)

    def test_run_all_fails_on_cache_miss(self):
        rows = [{"primary": "MISSING", "bench": "ALSO_MISSING",
                 "real_event": "2020-01-15"}]
        reader = _make_fake_cache({})
        artifact_path = self._write_artifact_with_rows(rows)
        try:
            result = run_all(
                artifact_path, n_draws=5, seed=0, cache_reader=reader,
            )
            self.assertFalse(result["ok"])
            self.assertTrue(result.get("setup_errors"))
        finally:
            os.remove(artifact_path)

    def test_load_v2_cohort_rows_extracts_three_fields(self):
        rows = [{"primary": "AAA", "bench": "BBB", "real_event": "2020-01-15"}]
        path = self._write_artifact_with_rows(rows)
        try:
            extracted = load_v2_cohort_rows(path)
            self.assertEqual(len(extracted), 1)
            self.assertEqual(extracted[0]["primary_ticker"], "AAA")
            self.assertEqual(extracted[0]["benchmark_ticker"], "BBB")
            self.assertEqual(extracted[0]["real_event_date"], "2020-01-15")
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
