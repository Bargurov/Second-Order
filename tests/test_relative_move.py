"""Tests for relative_move.classify_relative_move — benchmark-aware validation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from relative_move import (
    classify_relative_move,
    _VALIDATION_QUALITY_LABELS,
    _SUPPORT_ROLLUP,
)


def _returns(r1=None, r5=None, r20=None) -> dict:
    return {"return_1d": r1, "return_5d": r5, "return_20d": r20}


# ---------------------------------------------------------------------------
# Alpha path — relative move in thesis direction
# ---------------------------------------------------------------------------

class TestAlphaSupport(unittest.TestCase):
    def test_beneficiary_outperforms_benchmark(self):
        """Ticker +3%, benchmark +1% → +2pp relative → alpha_support."""
        res = classify_relative_move(
            ticker_returns=_returns(r1=0.5, r5=3.0, r20=5.0),
            benchmark_returns=_returns(r1=0.2, r5=1.0, r20=2.0),
            role="beneficiary",
            benchmark_symbol="XLE",
        )
        self.assertEqual(res["validation_quality"], "alpha_support")
        self.assertEqual(res["thesis_support"], "supported")
        self.assertAlmostEqual(res["relative_return_5d"], 2.0, places=2)
        self.assertEqual(res["benchmark_symbol"], "XLE")

    def test_loser_underperforms_benchmark(self):
        """For a loser ticker, alpha = negative relative move."""
        res = classify_relative_move(
            ticker_returns=_returns(r5=-2.0),
            benchmark_returns=_returns(r5=+1.0),
            role="loser",
            benchmark_symbol="SMH",
        )
        self.assertEqual(res["validation_quality"], "alpha_support")
        self.assertEqual(res["thesis_support"], "supported")

    def test_alpha_support_just_clears_floor(self):
        """Relative of exactly +0.5pp clears the alpha floor for a beneficiary."""
        res = classify_relative_move(
            ticker_returns=_returns(r5=0.5),
            benchmark_returns=_returns(r5=0.0),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "alpha_support")


# ---------------------------------------------------------------------------
# Alpha contradicts — relative move AGAINST thesis
# ---------------------------------------------------------------------------

class TestAlphaContradicts(unittest.TestCase):
    def test_beneficiary_underperforms_against_thesis(self):
        """Ticker −1%, benchmark +1% → −2pp against thesis → alpha_contradicts."""
        res = classify_relative_move(
            ticker_returns=_returns(r5=-1.0),
            benchmark_returns=_returns(r5=+1.0),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "alpha_contradicts")
        self.assertEqual(res["thesis_support"], "contradicted")

    def test_loser_outperforms_against_thesis(self):
        """Loser ticker rallying more than benchmark → alpha_contradicts."""
        res = classify_relative_move(
            ticker_returns=_returns(r5=+3.0),
            benchmark_returns=_returns(r5=+1.0),
            role="loser",
        )
        self.assertEqual(res["validation_quality"], "alpha_contradicts")
        self.assertEqual(res["thesis_support"], "contradicted")


# ---------------------------------------------------------------------------
# Beta-aligned — the whole point of the upgrade
# ---------------------------------------------------------------------------

class TestBetaAligned(unittest.TestCase):
    def test_moved_with_market_no_alpha(self):
        """Beneficiary +1.2%, benchmark +1.0% → +0.2pp spread → beta_aligned.

        This is the case the task was written against: the thesis looks
        'supported' on absolute returns but alpha is effectively zero, so
        the validation should NOT count as clean support.
        """
        res = classify_relative_move(
            ticker_returns=_returns(r5=+1.2),
            benchmark_returns=_returns(r5=+1.0),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "beta_aligned")
        self.assertEqual(res["thesis_support"], "ambiguous_beta")

    def test_loser_moved_down_with_market_no_alpha(self):
        res = classify_relative_move(
            ticker_returns=_returns(r5=-1.1),
            benchmark_returns=_returns(r5=-0.9),
            role="loser",
        )
        self.assertEqual(res["validation_quality"], "beta_aligned")
        self.assertEqual(res["thesis_support"], "ambiguous_beta")


# ---------------------------------------------------------------------------
# Beta contradicts — moved with market in wrong direction
# ---------------------------------------------------------------------------

class TestBetaContradicts(unittest.TestCase):
    def test_beneficiary_down_with_tape(self):
        """Beneficiary −0.8%, benchmark −0.7% → moves wrong direction
        with the tape → beta_contradicts."""
        res = classify_relative_move(
            ticker_returns=_returns(r5=-0.8),
            benchmark_returns=_returns(r5=-0.7),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "beta_contradicts")
        self.assertEqual(res["thesis_support"], "contradicted")


# ---------------------------------------------------------------------------
# Drift — whole market moved, ticker is noise on top
# ---------------------------------------------------------------------------

class TestDrift(unittest.TestCase):
    def test_ticker_tracks_benchmark_almost_exactly(self):
        """Ticker +1.1%, SPY +1.2% → spread ~0.1pp, bench moved → drift."""
        res = classify_relative_move(
            ticker_returns=_returns(r5=+1.1),
            benchmark_returns=_returns(r5=+1.2),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "drift")
        self.assertEqual(res["thesis_support"], "ambiguous_beta")

    def test_large_bench_move_with_tiny_spread_reads_as_drift(self):
        """SPY +2%, ticker +2.05% → large bench move, spread ~flat → drift."""
        res = classify_relative_move(
            ticker_returns=_returns(r5=+2.05),
            benchmark_returns=_returns(r5=+2.0),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "drift")

    def test_ticker_fails_to_participate_in_rally_is_alpha_contradicts(self):
        """Beneficiary flat while SPY +1.2% → alpha_contradicts, not drift.

        Failing to participate in a market rally when the thesis said this
        name should lead is legitimate negative evidence — the alpha check
        fires because the spread (-1.1pp) is clearly against thesis.
        """
        res = classify_relative_move(
            ticker_returns=_returns(r5=+0.1),
            benchmark_returns=_returns(r5=+1.2),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "alpha_contradicts")
        self.assertEqual(res["thesis_support"], "contradicted")


# ---------------------------------------------------------------------------
# Flat + unavailable edge cases
# ---------------------------------------------------------------------------

class TestFlatAndUnavailable(unittest.TestCase):
    def test_flat_when_nothing_moved(self):
        res = classify_relative_move(
            ticker_returns=_returns(r5=+0.1),
            benchmark_returns=_returns(r5=-0.2),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "flat")
        self.assertEqual(res["thesis_support"], "flat")

    def test_unavailable_when_ticker_r5_missing(self):
        res = classify_relative_move(
            ticker_returns=_returns(r5=None),
            benchmark_returns=_returns(r5=1.0),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "unavailable")
        self.assertFalse(res["available"])
        self.assertEqual(res["thesis_support"], "unavailable")

    def test_unavailable_when_benchmark_missing(self):
        res = classify_relative_move(
            ticker_returns=_returns(r5=1.0),
            benchmark_returns=_returns(r5=None),
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "unavailable")

    def test_nan_inputs_sanitized(self):
        res = classify_relative_move(
            ticker_returns={"return_5d": float("nan")},
            benchmark_returns={"return_5d": 1.0},
            role="beneficiary",
        )
        self.assertEqual(res["validation_quality"], "unavailable")


# ---------------------------------------------------------------------------
# Shape guarantees
# ---------------------------------------------------------------------------

class TestShape(unittest.TestCase):
    def test_all_quality_labels_have_text(self):
        for q in _VALIDATION_QUALITY_LABELS:
            self.assertTrue(_VALIDATION_QUALITY_LABELS[q])
            self.assertIn(q, _SUPPORT_ROLLUP)

    def test_support_rollup_only_marks_alpha_as_supported(self):
        """Only alpha_support rolls up to 'supported' — the key invariant."""
        self.assertEqual(_SUPPORT_ROLLUP["alpha_support"], "supported")
        for q in ("beta_aligned", "drift"):
            self.assertEqual(_SUPPORT_ROLLUP[q], "ambiguous_beta")
        for q in ("alpha_contradicts", "beta_contradicts"):
            self.assertEqual(_SUPPORT_ROLLUP[q], "contradicted")

    def test_output_has_all_documented_fields(self):
        res = classify_relative_move(
            ticker_returns=_returns(r1=0.1, r5=2.0, r20=5.0),
            benchmark_returns=_returns(r1=0.05, r5=1.0, r20=3.0),
            role="beneficiary",
            benchmark_symbol="XLE",
        )
        expected_keys = {
            "relative_return_1d", "relative_return_5d", "relative_return_20d",
            "benchmark_symbol", "benchmark_return_5d",
            "validation_quality", "validation_quality_label",
            "thesis_support", "rationale", "available",
        }
        self.assertEqual(set(res.keys()), expected_keys)


# ---------------------------------------------------------------------------
# resolve_benchmark — sector map + SPY fallback
# ---------------------------------------------------------------------------

class TestResolveBenchmark(unittest.TestCase):
    def test_known_sector_ticker_resolves_to_sector_etf(self):
        from market_check import resolve_benchmark
        self.assertEqual(resolve_benchmark("CVX"), ("XLE", "energy"))
        self.assertEqual(resolve_benchmark("NVDA"), ("SMH", "semiconductors"))
        self.assertEqual(resolve_benchmark("LMT"), ("XAR", "defense"))

    def test_new_sector_tickers_resolve(self):
        from market_check import resolve_benchmark
        self.assertEqual(resolve_benchmark("JPM")[0], "XLF")
        self.assertEqual(resolve_benchmark("JNJ")[0], "XLV")
        self.assertEqual(resolve_benchmark("CAT")[0], "XLI")
        self.assertEqual(resolve_benchmark("TSLA")[0], "XLY")

    def test_unknown_ticker_falls_back_to_spy(self):
        from market_check import resolve_benchmark
        self.assertEqual(resolve_benchmark("XYZ_MADE_UP"), ("SPY", "market"))

    def test_case_insensitive(self):
        from market_check import resolve_benchmark
        self.assertEqual(resolve_benchmark("cvx"), ("XLE", "energy"))


if __name__ == "__main__":
    unittest.main()
