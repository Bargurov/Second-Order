"""
tests/test_benchmark_quarantine.py

Contract tests for the benchmark-print quarantine layer.

Covers:
  1. Registry sanity — every entry has the required threshold fields
     and the inclusion set covers the macro composers' inputs.
  2. Primitive ``compute_benchmark_quarantine`` — healthy / warn /
     quarantined paths for each reason code, unit-aware thresholds.
  3. ``channel_quality_block`` roll-up — ok / warn / quarantined status
     propagates correctly when multiple channels are scored.
  4. Shock-decomposition integration — a corrupt 10Y print is
     quarantined, the nominal_yield channel's move is zeroed, the
     top-level ``channel_quality`` surfaces the reason.
  5. Cross-asset-coherence integration — a corrupt VIX print is
     dropped from the scorer and surfaced on the output.
  6. Healthy-path regression — a normal macro tape round-trips
     unchanged (status=ok, every channel's observed value preserved).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from benchmark_quarantine import (
    BENCHMARK_REGISTRY,
    DATA_QUALITY_IDS,
    QUARANTINE_REASON_IDS,
    benchmark_thresholds,
    channel_quality_block,
    compute_benchmark_quarantine,
    is_benchmark,
)
from shock_decomposition import compute_shock_decomposition
from cross_asset_coherence import compute_cross_asset_coherence


# ---------------------------------------------------------------------------
# 1. Registry sanity
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):

    def test_every_registry_entry_has_required_fields(self):
        required = {
            "unit", "sigma_5d", "outlier_sigma", "hard_cap",
            "price_floor", "price_ceiling", "stale_minutes",
        }
        for market, pack in BENCHMARK_REGISTRY.items():
            self.assertTrue(
                required <= set(pack.keys()),
                f"{market} missing fields: {required - set(pack.keys())}",
            )

    def test_units_are_constrained_to_pp_or_pct(self):
        for market, pack in BENCHMARK_REGISTRY.items():
            self.assertIn(pack["unit"], {"pp", "pct"},
                          f"{market} has non-standard unit {pack['unit']!r}")

    def test_hard_cap_exceeds_sigma_multiplied(self):
        """Hard cap must live above the sigma outlier threshold —
        otherwise a stat_outlier would never fire before hard_bound."""
        for market, pack in BENCHMARK_REGISTRY.items():
            sigma_cap = pack["sigma_5d"] * pack["outlier_sigma"]
            self.assertGreater(
                pack["hard_cap"], sigma_cap,
                f"{market} hard_cap ({pack['hard_cap']}) must exceed "
                f"sigma_cap ({sigma_cap}) or stat_outlier is unreachable",
            )

    def test_core_macro_tickers_are_registered(self):
        """Inclusion rule: the macro composers must find their
        canonical benchmark tickers in the registry."""
        for market in ("10Y", "DXY", "VIX", "SPY", "TIP", "HYG", "CL", "GLD"):
            self.assertTrue(is_benchmark(market),
                            f"{market} must be in BENCHMARK_REGISTRY")

    def test_is_benchmark_is_case_insensitive(self):
        self.assertTrue(is_benchmark("10y"))
        self.assertTrue(is_benchmark("  DxY  "))
        self.assertFalse(is_benchmark("AAPL"))
        self.assertFalse(is_benchmark(None))

    def test_benchmark_thresholds_returns_safe_copy(self):
        t = benchmark_thresholds("10Y")
        t["hard_cap"] = 999.0
        fresh = benchmark_thresholds("10Y")
        self.assertNotEqual(fresh["hard_cap"], 999.0)

    def test_unknown_market_thresholds_is_none(self):
        self.assertIsNone(benchmark_thresholds("NOT_A_MARKET"))


# ---------------------------------------------------------------------------
# 2. Primitive sanitizer — healthy / warn / quarantined
# ---------------------------------------------------------------------------

class TestQuarantineHealthyPath(unittest.TestCase):
    """A normal print must round-trip unchanged with no reason flags."""

    def test_normal_5d_move_is_ok(self):
        v = compute_benchmark_quarantine("10Y",
                                          move_5d=0.15,  # ~0.75 sigma
                                          last_price=4.25)
        self.assertEqual(v["data_quality"], "ok")
        self.assertEqual(v["reasons"], [])
        self.assertEqual(v["observed_safe"], 0.15)

    def test_normal_dxy_move_is_ok(self):
        v = compute_benchmark_quarantine("DXY",
                                          move_5d=0.40,  # ~0.6 sigma
                                          last_price=104.0)
        self.assertEqual(v["data_quality"], "ok")
        self.assertEqual(v["observed_safe"], 0.40)


class TestQuarantineHardFail(unittest.TestCase):
    """Hard-fail reasons must zero observed_safe and emit quarantined."""

    def test_hard_bound_violation_is_quarantined(self):
        # 10Y hard cap is 2.50pp — a 5pp move is outright corrupt.
        v = compute_benchmark_quarantine("10Y", move_5d=5.0)
        self.assertEqual(v["data_quality"], "quarantined")
        self.assertIn("hard_bound_violation", v["reasons"])
        self.assertIsNone(v["observed_safe"])

    def test_price_floor_violation_is_quarantined(self):
        # VIX floor is 5 — a price of 2 is physically implausible.
        v = compute_benchmark_quarantine("VIX",
                                          move_5d=10.0,
                                          last_price=2.0)
        self.assertEqual(v["data_quality"], "quarantined")
        self.assertIn("price_floor_violation", v["reasons"])

    def test_price_ceiling_violation_is_quarantined(self):
        # 10Y ceiling is 25 — a yield of 50 is corrupt (stub row).
        v = compute_benchmark_quarantine("10Y",
                                          move_5d=0.1,
                                          last_price=50.0)
        self.assertEqual(v["data_quality"], "quarantined")
        self.assertIn("price_floor_violation", v["reasons"])

    def test_dual_source_mismatch_is_quarantined(self):
        v = compute_benchmark_quarantine(
            "10Y",
            move_5d=0.2,
            verification={"status": "disputed",
                           "secondary_r5": 0.05, "delta": 0.15},
        )
        self.assertEqual(v["data_quality"], "quarantined")
        self.assertIn("dual_source_mismatch", v["reasons"])
        self.assertIsNone(v["observed_safe"])

    def test_no_quote_is_quarantined(self):
        v = compute_benchmark_quarantine("10Y",
                                          move_5d=None, move_1d=None,
                                          last_price=None)
        self.assertEqual(v["data_quality"], "quarantined")
        self.assertIn("no_quote", v["reasons"])


class TestQuarantineWarn(unittest.TestCase):
    """Soft-warn reasons preserve observed_safe but emit warn."""

    def test_stat_outlier_is_warn(self):
        # 10Y sigma is 0.20pp × 4.0 = 0.80pp threshold; hard_cap is
        # 2.50pp — a 1.0pp move is a stat outlier, not a hard bound.
        v = compute_benchmark_quarantine("10Y", move_5d=1.0)
        self.assertEqual(v["data_quality"], "warn")
        self.assertIn("stat_outlier", v["reasons"])
        self.assertEqual(v["observed_safe"], 1.0)

    def test_volume_anomaly_is_warn(self):
        v = compute_benchmark_quarantine("10Y",
                                          move_5d=0.1,
                                          volume_ratio=0.05)
        self.assertEqual(v["data_quality"], "warn")
        self.assertIn("volume_anomaly", v["reasons"])

    def test_stale_quote_is_warn(self):
        v = compute_benchmark_quarantine("DXY",
                                          move_5d=0.1,
                                          quote_age_minutes=4000.0)
        self.assertEqual(v["data_quality"], "warn")
        self.assertIn("stale_quote", v["reasons"])

    def test_unverified_is_warn(self):
        v = compute_benchmark_quarantine(
            "10Y",
            move_5d=0.1,
            verification={"status": "unavailable"},
        )
        self.assertEqual(v["data_quality"], "warn")
        self.assertIn("unverified", v["reasons"])

    def test_multiple_warn_reasons_accumulate(self):
        v = compute_benchmark_quarantine("10Y",
                                          move_5d=1.0,
                                          volume_ratio=0.05,
                                          quote_age_minutes=4000.0)
        self.assertEqual(v["data_quality"], "warn")
        for reason in ("stat_outlier", "volume_anomaly", "stale_quote"):
            self.assertIn(reason, v["reasons"])


class TestQuarantineElevation(unittest.TestCase):
    """Any hard-fail reason elevates even if warn reasons also fire."""

    def test_hard_bound_beats_stat_outlier(self):
        v = compute_benchmark_quarantine("10Y", move_5d=5.0,
                                          volume_ratio=0.05)
        self.assertEqual(v["data_quality"], "quarantined")
        self.assertIn("hard_bound_violation", v["reasons"])


class TestNonBenchmarkPassthrough(unittest.TestCase):
    """Non-benchmark tickers pass through with is_benchmark=False."""

    def test_unknown_market_returns_is_benchmark_false(self):
        v = compute_benchmark_quarantine("AAPL", move_5d=4.0)
        self.assertFalse(v["is_benchmark"])
        self.assertEqual(v["data_quality"], "ok")
        self.assertEqual(v["reasons"], [])
        # Non-benchmark observed value passes through unaltered.
        self.assertEqual(v["observed_safe"], 4.0)


class TestReasonCodeDiscipline(unittest.TestCase):
    """data_quality == 'ok' iff reasons == []."""

    def test_ok_has_empty_reasons(self):
        v = compute_benchmark_quarantine("10Y", move_5d=0.1)
        self.assertEqual(v["data_quality"], "ok")
        self.assertEqual(v["reasons"], [])

    def test_all_reasons_in_controlled_vocabulary(self):
        # Exercise many paths and confirm reasons come from the enum.
        samples = [
            compute_benchmark_quarantine("10Y", move_5d=10.0),
            compute_benchmark_quarantine("10Y", move_5d=1.0),
            compute_benchmark_quarantine("10Y", move_5d=0.1,
                                          volume_ratio=0.01),
            compute_benchmark_quarantine("VIX", move_5d=0.1,
                                          last_price=2.0),
            compute_benchmark_quarantine(
                "10Y", move_5d=0.1,
                verification={"status": "disputed"},
            ),
        ]
        for v in samples:
            for r in v["reasons"]:
                self.assertIn(r, QUARANTINE_REASON_IDS,
                              f"unknown reason {r!r} in {v}")


# ---------------------------------------------------------------------------
# 3. channel_quality_block roll-up
# ---------------------------------------------------------------------------

class TestChannelQualityBlock(unittest.TestCase):

    def test_all_ok_rolls_up_to_ok(self):
        block = channel_quality_block([
            {"channel": "rates", "data_quality": "ok", "reasons": []},
            {"channel": "fx",    "data_quality": "ok", "reasons": []},
        ])
        self.assertEqual(block["status"], "ok")
        self.assertEqual(block["quarantined"], [])
        self.assertEqual(block["warn"], [])

    def test_any_warn_rolls_up_to_warn(self):
        block = channel_quality_block([
            {"channel": "rates", "data_quality": "ok",   "reasons": []},
            {"channel": "fx",    "data_quality": "warn", "reasons": ["stat_outlier"]},
        ])
        self.assertEqual(block["status"], "warn")
        self.assertIn("fx", block["warn"])

    def test_any_quarantined_rolls_up_to_quarantined(self):
        block = channel_quality_block([
            {"channel": "rates", "data_quality": "warn",        "reasons": ["stat_outlier"]},
            {"channel": "vol",   "data_quality": "quarantined", "reasons": ["hard_bound_violation"]},
        ])
        self.assertEqual(block["status"], "quarantined")
        self.assertIn("vol", block["quarantined"])
        # Warn list still carries the warn-grade channels for telemetry
        self.assertIn("rates", block["warn"])

    def test_empty_input_returns_ok(self):
        block = channel_quality_block([])
        self.assertEqual(block["status"], "ok")
        self.assertEqual(block["channels"], {})


# ---------------------------------------------------------------------------
# 4. shock_decomposition integration
# ---------------------------------------------------------------------------

class TestShockDecompositionQuarantine(unittest.TestCase):

    def _snapshots(self, dxy_change: float = 0.5,
                    cl_change: float = 1.0) -> list[dict]:
        return [
            {"market": "DXY", "value": 104.0, "change_5d": dxy_change},
            {"market": "CL",  "value": 80.0,  "change_5d": cl_change},
        ]

    def test_corrupt_nominal_print_is_hard_failed(self):
        """A ^TNX move of +10pp is clearly corrupt — the quarantine
        layer must zero the nominal_yield channel and surface the
        reason via channel_quality."""
        rates_context = {
            "nominal":        {"change_5d": 10.0},  # absurd — hard_cap violated
            "real_proxy":     {"change_5d": -0.3},
            "breakeven_proxy": {"change_5d": 0.1},
        }
        block = compute_shock_decomposition(
            rates_context, None, self._snapshots(),
        )
        self.assertIn("channel_quality", block)
        cq = block["channel_quality"]
        self.assertEqual(cq["status"], "quarantined")
        self.assertIn("nominal_yield", cq["quarantined"])
        # The nominal_yield channel must have move_5d nulled so
        # ranking / primary selection doesn't read the corrupt print.
        self.assertFalse(block["channels"]["nominal_yield"]["available"])
        self.assertIsNone(block["channels"]["nominal_yield"]["move_5d"])
        self.assertEqual(
            block["channels"]["nominal_yield"]["data_quality"],
            "quarantined",
        )

    def test_healthy_macro_tape_is_unchanged(self):
        """Healthy-path: every channel's 5d move is preserved and
        channel_quality status is 'ok'."""
        rates_context = {
            "nominal":        {"change_5d": 0.05},
            "real_proxy":     {"change_5d": -0.03},
            "breakeven_proxy": {"change_5d": 0.02},
        }
        block = compute_shock_decomposition(
            rates_context, None, self._snapshots(),
        )
        self.assertEqual(block["channel_quality"]["status"], "ok")
        self.assertEqual(block["channel_quality"]["quarantined"], [])
        # Original nominal move must be visible in the payload.
        self.assertEqual(
            block["channels"]["nominal_yield"]["move_5d"], 0.05,
        )
        # Per-channel metadata present but flagged ok.
        for cid in ("nominal_yield", "real_yield", "fx", "commodity"):
            self.assertEqual(
                block["channels"][cid]["data_quality"], "ok",
                f"{cid} should be ok on the healthy path",
            )


# ---------------------------------------------------------------------------
# 5. cross_asset_coherence integration
# ---------------------------------------------------------------------------

class TestCrossAssetCoherenceQuarantine(unittest.TestCase):

    def test_corrupt_vix_print_is_dropped_from_scorer(self):
        # VIX hard_cap is 200 points over 5d — a move of 500 is corrupt.
        snapshots = [
            {"market": "DXY", "value": 104.0, "change_5d": 0.5},
            {"market": "SPY", "value": 450.0, "change_5d": 0.5},
        ]
        stress = {"raw": {"vix_change_5d": 500.0}}  # hard-cap violation
        rates_context = {"nominal": {"change_5d": 0.05}}
        block = compute_cross_asset_coherence(
            "rate_pressure_up", rates_context, stress, snapshots,
        )
        self.assertIn("channel_quality", block)
        self.assertEqual(block["channel_quality"]["status"], "quarantined")
        self.assertIn("vol", block["channel_quality"]["quarantined"])
        # The vol channel must read as unavailable / silent now.
        self.assertIsNone(block["channels"]["vol"]["observed"])

    def test_healthy_tape_preserves_all_channels(self):
        snapshots = [
            {"market": "DXY", "value": 104.0, "change_5d": 0.3},
            {"market": "SPY", "value": 450.0, "change_5d": 0.4},
            {"market": "CL",  "value": 80.0,  "change_5d": 1.0},
        ]
        stress = {"raw": {"vix_change_5d": 0.5, "credit_spread_5d": 0.05}}
        rates_context = {"nominal": {"change_5d": 0.05}}
        block = compute_cross_asset_coherence(
            "rate_pressure_up", rates_context, stress, snapshots,
        )
        self.assertEqual(block["channel_quality"]["status"], "ok")
        for cid in ("rates", "fx", "vol", "equities"):
            self.assertEqual(
                block["channels"][cid]["data_quality"], "ok",
                f"{cid} should be ok on the healthy path",
            )


# ---------------------------------------------------------------------------
# 6. Input-type robustness
# ---------------------------------------------------------------------------

class TestInputRobustness(unittest.TestCase):

    def test_nan_move_is_treated_as_missing(self):
        # NaN and inf are numeric but degenerate — must not produce
        # false quarantines, nor pass through as "ok".
        v = compute_benchmark_quarantine("10Y", move_5d=float("nan"))
        # With no other inputs, NaN coerces to None and the print
        # collapses to no_quote → quarantined.
        self.assertEqual(v["data_quality"], "quarantined")
        self.assertIn("no_quote", v["reasons"])

    def test_string_move_coerces_to_none_and_quarantines(self):
        v = compute_benchmark_quarantine("10Y", move_5d="not-a-number")
        self.assertEqual(v["data_quality"], "quarantined")

    def test_data_quality_id_is_controlled(self):
        v = compute_benchmark_quarantine("10Y", move_5d=0.1)
        self.assertIn(v["data_quality"], DATA_QUALITY_IDS)


if __name__ == "__main__":
    unittest.main()
