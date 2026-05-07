"""Tests for ``stats/event_study.py`` — the abnormal-return engine.

The engine consumes two aligned price arrays (asset + benchmark) plus
an ``event_index`` and returns four numbers per horizon:

  * ``raw_return``         — buy-and-hold return of the asset over h
                             days: ``(P[t+h] - P[t]) / P[t]``.
  * ``benchmark_return``   — same shape, on the benchmark.
  * ``abnormal_return``    — ``raw_return - benchmark_return``
                             (BHAR-style market-adjusted return).
  * ``sar``                — ``abnormal_return / (sigma_ar_daily *
                             sqrt(h))`` where ``sigma_ar_daily`` is
                             the sample stddev (ddof=1) of daily AR
                             over the estimation window.

These tests pin:

  * Hand-calculated raw / benchmark / AR / SAR for a tightly designed
    fixture (sigma is a known round number → SAR is exact).
  * ``ddof=1`` (sample std) — an explicit fixture where ``ddof=0``
    would give a visibly different answer.
  * sqrt(h) scaling: with constant daily AR the ratio of SAR(1) /
    SAR(4) equals ``2`` exactly.
  * Edge cases: sigma=0, insufficient forward data, insufficient
    estimation window, mismatched lengths, non-positive / NaN prices.
  * Default horizons (1, 5, 20); custom horizons honored.
  * Self-consistent payload: every requested horizon key is always
    present even when the value is None.
"""
from __future__ import annotations

import math
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stats import event_study  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _build_known_sigma_fixture() -> dict:
    """Construct asset + benchmark price arrays where every result is
    a hand-calculable round number.

    Estimation window: 5 daily returns.
      * benchmark daily returns: all 0       → sigma_benchmark = 0
      * asset daily returns: [+1%, -1%, +1%, -1%, 0%]
      * daily AR series == asset returns (since benchmark returns are 0)
      * mean(AR) = 0
      * sample variance (ddof=1) = sum(AR_i^2) / (n-1)
                                  = (4 * (0.01)^2) / 4 = 0.0001
      * sigma_ar_daily = 0.01

    Event close at index 5 (asset close = 99.980001..., bench = 100).
    Forward prices target:
      * h=1:  asset = event_close * 1.10  (raw=0.10), bench = 105 (0.05)
      * h=5:  asset = event_close * 1.20  (raw=0.20), bench = 110 (0.10)
      * h=20: asset = event_close * 1.40  (raw=0.40), bench = 130 (0.30)

    Intermediate forward prices are linearly interpolated; their
    values do not affect the engine because the engine only reads the
    event close + horizon endpoints.
    """
    asset_returns = [0.01, -0.01, 0.01, -0.01, 0.0]
    asset_prices = [100.0]
    for r in asset_returns:
        asset_prices.append(asset_prices[-1] * (1.0 + r))
    # asset_prices now has 6 entries; event_index = 5.
    event_close = asset_prices[-1]

    targets = {
        1:  event_close * 1.10,
        5:  event_close * 1.20,
        20: event_close * 1.40,
    }
    # Linear interpolation between known endpoints just to fill the
    # array; the engine never reads these intermediate values.
    asset_forward: list[float] = []
    last_idx, last_price = 0, event_close
    for h in (1, 5, 20):
        target = targets[h]
        for j in range(last_idx + 1, h + 1):
            frac = (j - last_idx) / (h - last_idx)
            asset_forward.append(last_price + frac * (target - last_price))
        last_idx, last_price = h, target
    asset_prices.extend(asset_forward)

    bench_prices = [100.0] * 6  # constant through estimation window
    bench_targets = {1: 105.0, 5: 110.0, 20: 130.0}
    bench_forward: list[float] = []
    last_idx, last_price = 0, 100.0
    for h in (1, 5, 20):
        target = bench_targets[h]
        for j in range(last_idx + 1, h + 1):
            frac = (j - last_idx) / (h - last_idx)
            bench_forward.append(last_price + frac * (target - last_price))
        last_idx, last_price = h, target
    bench_prices.extend(bench_forward)

    return {
        "asset_prices":     asset_prices,
        "benchmark_prices": bench_prices,
        "event_index":      5,
        "estimation_window": 5,
        "sigma_ar_daily":   0.01,
        "expected": {
            1:  {"raw_return": 0.10, "benchmark_return": 0.05,
                 "abnormal_return": 0.05,
                 "sar": 0.05 / (0.01 * math.sqrt(1))},
            5:  {"raw_return": 0.20, "benchmark_return": 0.10,
                 "abnormal_return": 0.10,
                 "sar": 0.10 / (0.01 * math.sqrt(5))},
            20: {"raw_return": 0.40, "benchmark_return": 0.30,
                 "abnormal_return": 0.10,
                 "sar": 0.10 / (0.01 * math.sqrt(20))},
        },
    }


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


_REQUIRED_TOP_KEYS = (
    "available",
    "horizons",
    "estimation_window_used",
    "sigma_ar_daily",
    "warnings",
)

_REQUIRED_HORIZON_FIELDS = (
    "raw_return",
    "benchmark_return",
    "abnormal_return",
    "sar",
)


class TestPayloadShape(unittest.TestCase):
    def test_default_horizons_are_one_five_twenty(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        self.assertEqual(set(result["horizons"].keys()), {1, 5, 20})

    def test_top_level_keys_present(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        for key in _REQUIRED_TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_each_horizon_carries_required_fields(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        for h, entry in result["horizons"].items():
            for key in _REQUIRED_HORIZON_FIELDS:
                self.assertIn(key, entry, f"h={h} missing field: {key}")

    def test_custom_horizons_honored(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
            horizons=(1, 5),
        )
        self.assertEqual(set(result["horizons"].keys()), {1, 5})


# ---------------------------------------------------------------------------
# Numeric correctness — hand-calculated fixture
# ---------------------------------------------------------------------------


class TestNumericCorrectness(unittest.TestCase):
    def test_raw_benchmark_abnormal_returns_match_hand_calc(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        for h, expected in f["expected"].items():
            entry = result["horizons"][h]
            self.assertAlmostEqual(
                entry["raw_return"], expected["raw_return"], places=10,
                msg=f"h={h} raw_return",
            )
            self.assertAlmostEqual(
                entry["benchmark_return"], expected["benchmark_return"],
                places=10, msg=f"h={h} benchmark_return",
            )
            self.assertAlmostEqual(
                entry["abnormal_return"], expected["abnormal_return"],
                places=10, msg=f"h={h} abnormal_return",
            )
            self.assertAlmostEqual(
                entry["sar"], expected["sar"], places=10,
                msg=f"h={h} sar",
            )

    def test_sigma_matches_hand_calc(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        self.assertAlmostEqual(
            result["sigma_ar_daily"], f["sigma_ar_daily"], places=10,
        )

    def test_estimation_window_used_reports_actual_returns_count(
        self,
    ) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        # estimation_window=5 → 5 daily returns over 6 prices.
        self.assertEqual(result["estimation_window_used"], 5)


# ---------------------------------------------------------------------------
# ddof=1 vs ddof=0 — sample stddev, not population
# ---------------------------------------------------------------------------


class TestSigmaUsesSampleStd(unittest.TestCase):
    def test_sigma_uses_ddof_one_sample_std(self) -> None:
        # 5-element AR series gives n=5: ddof=0 divisor is 5, ddof=1 is 4.
        # The two sigmas differ by sqrt(5/4) = 1.1180...  Pin ddof=1.
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=f["asset_prices"],
            benchmark_prices=f["benchmark_prices"],
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        sigma = result["sigma_ar_daily"]
        # Hand-calc: sample variance = 4*(0.01)^2 / (5-1) = 0.0001
        # Population variance = 4*(0.01)^2 / 5 = 0.00008
        sigma_pop = math.sqrt(0.00008)
        self.assertAlmostEqual(sigma, 0.01,    places=10)
        self.assertNotAlmostEqual(sigma, sigma_pop, places=4)


# ---------------------------------------------------------------------------
# sqrt(h) scaling under constant daily AR
# ---------------------------------------------------------------------------


class TestSqrtHorizonScaling(unittest.TestCase):
    def test_sar_scales_inversely_with_sqrt_h(self) -> None:
        # Estimation window must have *varying* daily AR so sigma > 0;
        # event window must have *small constant* daily AR so BHAR
        # tracks the sum-of-daily AR closely (otherwise BHAR
        # compounding nudges the ratio away from the additive 0.5).
        n_estimation = 30
        n_forward    = 4
        asset_prices = [100.0]
        bench_prices = [100.0]
        # Alternating ±1% asset returns vs flat bench → daily AR
        # alternates ±1% → sigma_ar_daily ≈ 0.01017 (sample std).
        for i in range(n_estimation):
            r = 0.01 if i % 2 == 0 else -0.01
            asset_prices.append(asset_prices[-1] * (1.0 + r))
            bench_prices.append(bench_prices[-1])
        # 1bp/day constant daily AR over the event window — small
        # enough that BHAR(4) ≈ 4 × BHAR(1).
        daily_ar_event = 0.0001
        for _ in range(n_forward):
            asset_prices.append(asset_prices[-1] * (1.0 + daily_ar_event))
            bench_prices.append(bench_prices[-1])
        result = event_study.compute_event_study(
            asset_prices=asset_prices,
            benchmark_prices=bench_prices,
            event_index=n_estimation,
            estimation_window=n_estimation,
            horizons=(1, 4),
        )
        sar1 = result["horizons"][1]["sar"]
        sar4 = result["horizons"][4]["sar"]
        self.assertIsNotNone(sar1)
        self.assertIsNotNone(sar4)
        # Under exact additivity, SAR_h = (h × d_AR) / (sigma × √h) =
        # √h × d_AR / sigma, so SAR(1)/SAR(4) = 1/2.  BHAR
        # compounding nudges it ~5e-5 away at this scale; pin to 1e-3.
        self.assertAlmostEqual(sar1 / sar4, 0.5, delta=1e-3)


# ---------------------------------------------------------------------------
# Edge cases — sigma=0
# ---------------------------------------------------------------------------


class TestSigmaZeroCase(unittest.TestCase):
    def test_constant_returns_yield_sigma_zero_and_sar_none(self) -> None:
        # Estimation window where asset_returns == bench_returns each
        # day → daily AR series is all zeros → sigma=0.  AR over the
        # event window may be non-zero (if the event-window returns
        # diverge); SAR must be None for every horizon.
        n = 30
        asset_prices = [100.0]
        bench_prices = [100.0]
        for _ in range(n):
            asset_prices.append(asset_prices[-1] * 1.001)
            bench_prices.append(bench_prices[-1] * 1.001)  # same returns
        # Forward window: asset rallies, bench flat → AR ≠ 0.
        for _ in range(20):
            asset_prices.append(asset_prices[-1] * 1.01)
            bench_prices.append(bench_prices[-1] * 1.005)
        result = event_study.compute_event_study(
            asset_prices=asset_prices,
            benchmark_prices=bench_prices,
            event_index=n,
            estimation_window=n,
        )
        self.assertEqual(result["sigma_ar_daily"], 0.0)
        for h, entry in result["horizons"].items():
            self.assertIsNotNone(
                entry["abnormal_return"],
                f"AR must compute even when sigma=0 (h={h})",
            )
            self.assertIsNone(
                entry["sar"], f"SAR must be None when sigma=0 (h={h})",
            )
        # Surface the condition in warnings so consumers can branch.
        joined = " | ".join(result["warnings"])
        self.assertIn("sigma", joined.lower())


# ---------------------------------------------------------------------------
# Edge cases — insufficient data
# ---------------------------------------------------------------------------


class TestInsufficientData(unittest.TestCase):
    def test_event_index_below_estimation_window_marks_unavailable(
        self,
    ) -> None:
        # estimation_window=60 but event_index=10 → can't fit window.
        n = 100
        asset = [100.0 + i * 0.1 for i in range(n)]
        bench = [100.0 + i * 0.05 for i in range(n)]
        result = event_study.compute_event_study(
            asset_prices=asset,
            benchmark_prices=bench,
            event_index=10,
            estimation_window=60,
        )
        self.assertFalse(result["available"])
        for h in (1, 5, 20):
            entry = result["horizons"][h]
            for key in _REQUIRED_HORIZON_FIELDS:
                self.assertIsNone(entry[key], f"h={h} field {key}")
        # Warning explains the gap.
        self.assertTrue(any(
            "estimation" in w.lower() for w in result["warnings"]
        ), f"warnings: {result['warnings']}")

    def test_horizon_beyond_array_yields_none_for_that_horizon(
        self,
    ) -> None:
        # estimation_window fits but h=20 doesn't (only 5 forward bars).
        n_est = 30
        n_fwd = 5
        asset_prices = [100.0]
        bench_prices = [100.0]
        for _ in range(n_est + n_fwd):
            asset_prices.append(asset_prices[-1] * 1.01)
            bench_prices.append(bench_prices[-1] * 1.005)
        result = event_study.compute_event_study(
            asset_prices=asset_prices,
            benchmark_prices=bench_prices,
            event_index=n_est,
            estimation_window=n_est,
        )
        self.assertTrue(result["available"])
        # h=1, 5 fit; h=20 does not.
        for h in (1, 5):
            for key in _REQUIRED_HORIZON_FIELDS:
                if key == "sar":
                    continue  # sar may be None if sigma is small/zero
                self.assertIsNotNone(
                    result["horizons"][h][key],
                    f"h={h} field {key} should compute",
                )
        for key in _REQUIRED_HORIZON_FIELDS:
            self.assertIsNone(
                result["horizons"][20][key],
                f"h=20 field {key} must be None when horizon overflows",
            )
        # Warning surfaces the unavailable horizon.
        self.assertTrue(any(
            "horizon" in w.lower() and "20" in w
            for w in result["warnings"]
        ), f"warnings: {result['warnings']}")


# ---------------------------------------------------------------------------
# ValueError surface — caller bugs
# ---------------------------------------------------------------------------


class TestValueErrors(unittest.TestCase):
    def test_mismatched_lengths_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            event_study.compute_event_study(
                asset_prices=[100, 101, 102],
                benchmark_prices=[100, 101],
                event_index=1,
                estimation_window=1,
            )

    def test_non_positive_price_raises_value_error(self) -> None:
        prices = [100.0] * 10
        prices[3] = 0.0
        with self.assertRaises(ValueError):
            event_study.compute_event_study(
                asset_prices=prices,
                benchmark_prices=[100.0] * 10,
                event_index=5,
                estimation_window=3,
            )

    def test_negative_price_raises_value_error(self) -> None:
        prices = [100.0] * 10
        prices[3] = -5.0
        with self.assertRaises(ValueError):
            event_study.compute_event_study(
                asset_prices=prices,
                benchmark_prices=[100.0] * 10,
                event_index=5,
                estimation_window=3,
            )

    def test_nan_price_raises_value_error(self) -> None:
        prices = [100.0] * 10
        prices[3] = float("nan")
        with self.assertRaises(ValueError):
            event_study.compute_event_study(
                asset_prices=prices,
                benchmark_prices=[100.0] * 10,
                event_index=5,
                estimation_window=3,
            )

    def test_event_index_out_of_range_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            event_study.compute_event_study(
                asset_prices=[100.0] * 10,
                benchmark_prices=[100.0] * 10,
                event_index=20,
                estimation_window=3,
            )

    def test_horizon_non_positive_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            event_study.compute_event_study(
                asset_prices=[100.0] * 10,
                benchmark_prices=[100.0] * 10,
                event_index=5,
                estimation_window=3,
                horizons=(0,),
            )


# ---------------------------------------------------------------------------
# Input flexibility — accept list / tuple / ndarray / pandas Series
# ---------------------------------------------------------------------------


class TestInputFlexibility(unittest.TestCase):
    def test_accepts_pandas_series(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=pd.Series(f["asset_prices"]),
            benchmark_prices=pd.Series(f["benchmark_prices"]),
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        self.assertAlmostEqual(
            result["horizons"][1]["raw_return"], 0.10, places=10,
        )

    def test_accepts_numpy_array(self) -> None:
        f = _build_known_sigma_fixture()
        result = event_study.compute_event_study(
            asset_prices=np.asarray(f["asset_prices"]),
            benchmark_prices=np.asarray(f["benchmark_prices"]),
            event_index=f["event_index"],
            estimation_window=f["estimation_window"],
        )
        self.assertAlmostEqual(
            result["horizons"][1]["abnormal_return"], 0.05, places=10,
        )


# ---------------------------------------------------------------------------
# No DB / no provider — module import side-effects
# ---------------------------------------------------------------------------


class TestNoForbiddenSideEffects(unittest.TestCase):
    def test_module_imports_no_db_or_provider_modules(self) -> None:
        import inspect, ast
        source = inspect.getsource(event_study)
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        for forbidden in (
            "db", "price_cache", "market_check", "market_data",
            "yfinance", "analyze_event", "api",
        ):
            self.assertNotIn(
                forbidden, imports,
                f"event_study must not import {forbidden!r}",
            )

    def test_module_does_not_carry_app_or_router(self) -> None:
        self.assertFalse(hasattr(event_study, "app"))
        self.assertFalse(hasattr(event_study, "router"))


if __name__ == "__main__":
    unittest.main()
