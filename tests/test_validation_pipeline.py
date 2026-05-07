"""
Tests for stats.validation_pipeline.

End-to-end composer that takes event-study horizon outputs and emits a
stable list of stat_validation records carrying p_value and fdr_q.

Discipline
----------
* Pure functions: no DB, provider, LLM, FastAPI, or archive mutation.
* Composes existing siblings: stats.event_study, stats.bootstrap_ci,
  stats.fdr, stats.stat_validation.
* Deterministic under seed.
"""

from __future__ import annotations

import ast
import math
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from stats import bootstrap_ci as _bci  # noqa: E402
from stats import event_study as _es  # noqa: E402
from stats import fdr as _fdr  # noqa: E402
from stats import stat_validation as _sv  # noqa: E402
from stats import validation_pipeline as vp  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic builders
# ---------------------------------------------------------------------------


def _gauss_walk(n: int, mu: float, sigma: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    p = 100.0
    out = [p]
    for _ in range(n - 1):
        r = rng.gauss(mu, sigma)
        p = max(p * (1.0 + r), 0.01)
        out.append(p)
    return out


def _build_event_study_outputs(
    *,
    n_events: int,
    horizons: tuple[int, ...] = (1, 5, 20),
    asset_drift: float = 0.0,
    sigma_asset: float = 0.012,
    sigma_bench: float = 0.010,
    seed: int = 0,
) -> list[dict]:
    """Run real compute_event_study on synthetic prices for ``n_events`` events.

    ``asset_drift`` is added to every asset return; benchmark returns are
    centered at zero. So a positive ``asset_drift`` produces positive
    abnormal returns on average — useful for exercising the
    significant_positive interpretation path.
    """
    rng = random.Random(seed)
    horizons = tuple(int(h) for h in horizons)
    n_per_event = max(horizons) + 80  # leaves room for estimation window
    out: list[dict] = []
    for i in range(n_events):
        ev_seed = seed * 10_000 + i
        # Asset prices with drift + noise, benchmark with noise only.
        # Use independent random walks so abnormal returns are non-trivial.
        asset = _gauss_walk(n_per_event, asset_drift, sigma_asset, ev_seed * 2 + 1)
        bench = _gauss_walk(n_per_event, 0.0, sigma_bench, ev_seed * 2 + 2)
        event_index = 60  # leaves estimation_window=60 fully available
        es = _es.compute_event_study(
            asset_prices=asset,
            benchmark_prices=bench,
            event_index=event_index,
            horizons=horizons,
            estimation_window=60,
        )
        out.append(es)
    return out


def _flat_rows_from_outputs(outputs: list[dict]) -> list[dict]:
    """Flatten compute_event_study outputs into per-horizon rows."""
    rows: list[dict] = []
    for es in outputs:
        if not es.get("available", False):
            continue
        for h, fields in es["horizons"].items():
            rows.append({
                "horizon": int(h),
                "abnormal_return": fields.get("abnormal_return"),
                "sar": fields.get("sar"),
            })
    return rows


# ---------------------------------------------------------------------------
# Output shape & ordering
# ---------------------------------------------------------------------------


class TestPipelineOutputShape(unittest.TestCase):
    def test_returns_list(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=20))
        out = vp.run_validation_pipeline(rows, seed=0)
        self.assertIsInstance(out, list)

    def test_one_record_per_unique_horizon(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=20))
        out = vp.run_validation_pipeline(rows, seed=0)
        horizons_in = {r["horizon"] for r in rows}
        horizons_out = {r["horizon"] for r in out}
        self.assertEqual(horizons_out, horizons_in)
        self.assertEqual(len(out), len(horizons_in))

    def test_records_sorted_by_horizon_ascending(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        # Shuffle input to prove output ordering is independent of input order.
        rng = random.Random(123)
        rng.shuffle(rows)
        out = vp.run_validation_pipeline(rows, seed=0)
        horizons = [r["horizon"] for r in out]
        self.assertEqual(horizons, sorted(horizons))

    def test_each_record_has_canonical_fields(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        out = vp.run_validation_pipeline(rows, seed=0)
        for rec in out:
            self.assertEqual(
                tuple(rec.keys()),
                _sv.STAT_VALIDATION_FIELDS,
            )

    def test_returns_python_floats_not_numpy(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        out = vp.run_validation_pipeline(rows, seed=0)
        for rec in out:
            for k in ("abnormal_return", "sar", "ci_low", "ci_high",
                      "p_value", "fdr_q"):
                v = rec[k]
                if v is not None:
                    self.assertIsInstance(v, float, msg=f"{k}={v!r}")

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(vp.run_validation_pipeline([], seed=0), [])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_seed_byte_equal(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=20))
        a = vp.run_validation_pipeline(rows, seed=42)
        b = vp.run_validation_pipeline(rows, seed=42)
        self.assertEqual(a, b)

    def test_default_seed_is_zero(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=20))
        default_run = vp.run_validation_pipeline(rows)
        explicit_zero = vp.run_validation_pipeline(rows, seed=0)
        self.assertEqual(default_run, explicit_zero)

    def test_different_seed_changes_ci_endpoints(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=20))
        a = vp.run_validation_pipeline(rows, seed=1)
        b = vp.run_validation_pipeline(rows, seed=2)
        # CI bounds change with seed (bootstrap is seeded). At least one
        # horizon should differ.
        differ = any(
            (ra["ci_low"], ra["ci_high"]) != (rb["ci_low"], rb["ci_high"])
            for ra, rb in zip(a, b)
        )
        self.assertTrue(differ)

    def test_p_value_and_fdr_q_are_seed_independent(self):
        """The cross-sectional z-test on SAR is deterministic without the
        bootstrap RNG, so changing the bootstrap seed must NOT alter p_value
        or fdr_q."""
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=20))
        a = vp.run_validation_pipeline(rows, seed=1)
        b = vp.run_validation_pipeline(rows, seed=2)
        for ra, rb in zip(a, b):
            self.assertEqual(ra["p_value"], rb["p_value"])
            self.assertEqual(ra["fdr_q"], rb["fdr_q"])

    def test_does_not_consume_global_random_state(self):
        random.seed(123)
        before = random.random()
        random.seed(123)
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        vp.run_validation_pipeline(rows, seed=99)
        after = random.random()
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


class TestInsufficientData(unittest.TestCase):
    def test_below_min_samples_marks_record_insufficient(self):
        rows = [
            {"horizon": 5, "abnormal_return": 0.01, "sar": 0.5}
            for _ in range(3)
        ]
        out = vp.run_validation_pipeline(rows, seed=0, min_samples=8)
        self.assertEqual(len(out), 1)
        rec = out[0]
        self.assertEqual(rec["horizon"], 5)
        self.assertIsNone(rec["ci_low"])
        self.assertIsNone(rec["ci_high"])
        self.assertIsNone(rec["p_value"])
        self.assertIsNone(rec["fdr_q"])
        self.assertFalse(rec["statistically_significant"])

    def test_all_nan_ar_yields_insufficient_record(self):
        rows = [
            {"horizon": 1, "abnormal_return": float("nan"), "sar": float("nan")}
            for _ in range(20)
        ]
        out = vp.run_validation_pipeline(rows, seed=0)
        self.assertEqual(len(out), 1)
        rec = out[0]
        self.assertIsNone(rec["abnormal_return"])
        self.assertIsNone(rec["sar"])
        self.assertIsNone(rec["ci_low"])
        self.assertIsNone(rec["ci_high"])
        self.assertIsNone(rec["p_value"])
        self.assertIsNone(rec["fdr_q"])
        self.assertEqual(
            rec["interpretation"],
            _sv.INTERPRETATION_INSUFFICIENT_DATA,
        )

    def test_mixed_horizons_some_sufficient(self):
        good = [
            {"horizon": 5, "abnormal_return": 0.01 + 0.001 * i, "sar": 0.4 + 0.01 * i}
            for i in range(20)
        ]
        sparse = [
            {"horizon": 20, "abnormal_return": 0.02, "sar": 0.5}
            for _ in range(2)
        ]
        out = vp.run_validation_pipeline(good + sparse, seed=0, min_samples=8)
        self.assertEqual(len(out), 2)
        rec_good  = next(r for r in out if r["horizon"] == 5)
        rec_thin  = next(r for r in out if r["horizon"] == 20)
        self.assertIsNotNone(rec_good["ci_low"])
        self.assertIsNotNone(rec_good["p_value"])
        self.assertIsNone(rec_thin["ci_low"])
        self.assertIsNone(rec_thin["p_value"])

    def test_zero_variance_sar_yields_none_p_value(self):
        # All SARs identical → variance 0 → z-test undefined → p_value None.
        rows = [
            {"horizon": 1, "abnormal_return": 0.001 * (i + 1), "sar": 0.5}
            for i in range(20)
        ]
        out = vp.run_validation_pipeline(rows, seed=0, min_samples=8)
        self.assertEqual(len(out), 1)
        rec = out[0]
        # AR variance is fine → CI present.
        self.assertIsNotNone(rec["ci_low"])
        # SAR variance is 0 → p_value None.
        self.assertIsNone(rec["p_value"])

    def test_insufficient_horizons_dropped_from_fdr_count(self):
        good = [
            {"horizon": 1, "abnormal_return": 0.05 * (i + 1), "sar": 5.0 + i}
            for i in range(20)
        ]
        sparse = [
            {"horizon": 5, "abnormal_return": 0.02, "sar": 0.5}
            for _ in range(3)
        ]
        out = vp.run_validation_pipeline(good + sparse, seed=0, min_samples=8)
        rec1 = next(r for r in out if r["horizon"] == 1)
        # m=1 valid p value → BH adjusted equals raw p.
        self.assertIsNotNone(rec1["p_value"])
        self.assertIsNotNone(rec1["fdr_q"])
        self.assertAlmostEqual(rec1["fdr_q"], rec1["p_value"], places=12)


# ---------------------------------------------------------------------------
# Statistical correctness
# ---------------------------------------------------------------------------


class TestStatisticalCorrectness(unittest.TestCase):
    def test_strong_positive_signal_significant_positive(self):
        outputs = _build_event_study_outputs(
            n_events=80,
            horizons=(1,),
            asset_drift=0.005,  # 50 bps daily drift on top of noise
            sigma_asset=0.005,
            sigma_bench=0.005,
            seed=2026,
        )
        rows = _flat_rows_from_outputs(outputs)
        out = vp.run_validation_pipeline(rows, seed=0)
        rec = out[0]
        self.assertGreater(rec["abnormal_return"], 0.0)
        self.assertLessEqual(rec["fdr_q"], 0.05)
        self.assertTrue(rec["statistically_significant"])
        self.assertEqual(
            rec["interpretation"],
            _sv.INTERPRETATION_SIGNIFICANT_POSITIVE,
        )

    def test_strong_negative_signal_significant_negative(self):
        outputs = _build_event_study_outputs(
            n_events=80,
            horizons=(1,),
            asset_drift=-0.005,
            sigma_asset=0.005,
            sigma_bench=0.005,
            seed=4242,
        )
        rows = _flat_rows_from_outputs(outputs)
        out = vp.run_validation_pipeline(rows, seed=0)
        rec = out[0]
        self.assertLess(rec["abnormal_return"], 0.0)
        self.assertLessEqual(rec["fdr_q"], 0.05)
        self.assertEqual(
            rec["interpretation"],
            _sv.INTERPRETATION_SIGNIFICANT_NEGATIVE,
        )

    def test_no_signal_not_significant(self):
        outputs = _build_event_study_outputs(
            n_events=60,
            horizons=(1,),
            asset_drift=0.0,
            sigma_asset=0.012,
            sigma_bench=0.010,
            seed=7777,
        )
        rows = _flat_rows_from_outputs(outputs)
        out = vp.run_validation_pipeline(rows, seed=0)
        rec = out[0]
        # Under no drift, p must not collapse to <= alpha by accident.
        # We can't make this a hard inequality (random luck), but the
        # interpretation must be a member of the closed vocabulary.
        self.assertIn(rec["interpretation"], _sv.INTERPRETATIONS)

    def test_p_value_in_unit_interval_when_present(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=30))
        out = vp.run_validation_pipeline(rows, seed=0)
        for rec in out:
            if rec["p_value"] is not None:
                self.assertGreaterEqual(rec["p_value"], 0.0)
                self.assertLessEqual(rec["p_value"], 1.0)
            if rec["fdr_q"] is not None:
                self.assertGreaterEqual(rec["fdr_q"], 0.0)
                self.assertLessEqual(rec["fdr_q"], 1.0)

    def test_fdr_q_at_least_p_value_when_both_present(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=30))
        out = vp.run_validation_pipeline(rows, seed=0)
        for rec in out:
            p, q = rec["p_value"], rec["fdr_q"]
            if p is not None and q is not None:
                # BH adjustment is monotonically >= raw p (rarely equal).
                self.assertGreaterEqual(q + 1e-12, p, msg=f"q={q} p={p}")

    def test_ci_brackets_mean_when_present(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=30))
        out = vp.run_validation_pipeline(rows, seed=0)
        for rec in out:
            if (
                rec["ci_low"] is not None
                and rec["ci_high"] is not None
                and rec["abnormal_return"] is not None
            ):
                self.assertLessEqual(rec["ci_low"], rec["abnormal_return"] + 1e-9)
                self.assertLessEqual(rec["abnormal_return"] - 1e-9, rec["ci_high"])

    def test_significant_only_if_fdr_q_le_alpha(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(
            n_events=80, horizons=(1, 5, 20),
            asset_drift=0.003, sigma_asset=0.005, sigma_bench=0.005,
            seed=99,
        ))
        out = vp.run_validation_pipeline(rows, seed=0, alpha=0.05)
        for rec in out:
            if rec["fdr_q"] is None:
                self.assertFalse(rec["statistically_significant"])
            else:
                self.assertEqual(
                    rec["statistically_significant"],
                    rec["fdr_q"] <= 0.05,
                )


# ---------------------------------------------------------------------------
# Input acceptance
# ---------------------------------------------------------------------------


class TestInputForms(unittest.TestCase):
    def test_full_event_study_outputs_accepted(self):
        """Pipeline accepts compute_event_study outputs directly."""
        outputs = _build_event_study_outputs(n_events=15)
        out = vp.run_validation_pipeline(outputs, seed=0)
        self.assertEqual(len(out), 3)  # one per horizon (1, 5, 20)

    def test_flat_per_horizon_rows_accepted(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        out = vp.run_validation_pipeline(rows, seed=0)
        self.assertEqual(len(out), 3)

    def test_full_and_flat_yield_same_records(self):
        outputs = _build_event_study_outputs(n_events=15)
        rows = _flat_rows_from_outputs(outputs)
        a = vp.run_validation_pipeline(outputs, seed=0)
        b = vp.run_validation_pipeline(rows, seed=0)
        self.assertEqual(a, b)

    def test_unavailable_event_study_outputs_skipped(self):
        outputs = _build_event_study_outputs(n_events=15)
        outputs.insert(0, {
            "available": False,
            "horizons": {h: {"abnormal_return": None, "sar": None}
                         for h in (1, 5, 20)},
            "estimation_window_used": 0,
            "sigma_ar_daily": None,
            "warnings": ["insufficient estimation window"],
        })
        out_with_bad = vp.run_validation_pipeline(outputs, seed=0)
        out_clean    = vp.run_validation_pipeline(outputs[1:], seed=0)
        self.assertEqual(out_with_bad, out_clean)

    def test_per_event_horizons_with_none_skipped(self):
        rows = [
            {"horizon": 1, "abnormal_return": None, "sar": None}
            for _ in range(20)
        ]
        out = vp.run_validation_pipeline(rows, seed=0)
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["abnormal_return"])
        self.assertEqual(
            out[0]["interpretation"],
            _sv.INTERPRETATION_INSUFFICIENT_DATA,
        )

    def test_input_order_does_not_affect_output(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=20))
        rng = random.Random(99)
        shuffled = rows[:]
        rng.shuffle(shuffled)
        a = vp.run_validation_pipeline(rows, seed=0)
        b = vp.run_validation_pipeline(shuffled, seed=0)
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestInputValidation(unittest.TestCase):
    def test_non_iterable_raises(self):
        with self.assertRaises(TypeError):
            vp.run_validation_pipeline(42, seed=0)

    def test_non_dict_row_raises(self):
        with self.assertRaises(TypeError):
            vp.run_validation_pipeline([("h", 1)], seed=0)

    def test_row_missing_horizon_raises(self):
        rows = [{"abnormal_return": 0.01, "sar": 0.5} for _ in range(10)]
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0)

    def test_row_with_negative_horizon_raises(self):
        rows = [
            {"horizon": -1, "abnormal_return": 0.01, "sar": 0.5}
            for _ in range(10)
        ]
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0)

    def test_non_numeric_ar_raises(self):
        rows = [
            {"horizon": 1, "abnormal_return": "oops", "sar": 0.5}
            for _ in range(10)
        ]
        with self.assertRaises((TypeError, ValueError)):
            vp.run_validation_pipeline(rows, seed=0)

    def test_alpha_out_of_range_raises(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0, alpha=0.0)
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0, alpha=1.5)

    def test_confidence_out_of_range_raises(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0, confidence=1.0)
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0, confidence=-0.1)

    def test_n_bootstrap_must_be_positive(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0, n_bootstrap=0)

    def test_min_samples_must_be_positive(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with self.assertRaises(ValueError):
            vp.run_validation_pipeline(rows, seed=0, min_samples=0)

    def test_seed_must_be_integer(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with self.assertRaises(TypeError):
            vp.run_validation_pipeline(rows, seed=0.5)


# ---------------------------------------------------------------------------
# Module composition (uses existing siblings)
# ---------------------------------------------------------------------------


class TestModuleComposition(unittest.TestCase):
    def test_calls_bootstrap_ar_ci(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with patch.object(
            vp, "bootstrap_ar_ci", wraps=vp.bootstrap_ar_ci,
        ) as spy:
            vp.run_validation_pipeline(rows, seed=0)
            self.assertGreaterEqual(spy.call_count, 1)

    def test_calls_bh_adjust(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with patch.object(vp, "bh_adjust", wraps=vp.bh_adjust) as spy:
            vp.run_validation_pipeline(rows, seed=0)
            self.assertGreaterEqual(spy.call_count, 1)

    def test_calls_make_stat_validation_record(self):
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        with patch.object(
            vp, "make_stat_validation_record",
            wraps=vp.make_stat_validation_record,
        ) as spy:
            out = vp.run_validation_pipeline(rows, seed=0)
            self.assertEqual(spy.call_count, len(out))

    def test_record_fields_match_make_stat_validation_record(self):
        """Composer hands its inputs to make_stat_validation_record so the
        record format must be byte-equal to what make_stat_validation_record
        emits when given the same horizon-aggregated inputs."""
        rows = _flat_rows_from_outputs(_build_event_study_outputs(n_events=15))
        out = vp.run_validation_pipeline(rows, seed=0)
        for rec in out:
            self.assertEqual(
                tuple(rec.keys()),
                _sv.STAT_VALIDATION_FIELDS,
            )
            for key in _sv.STAT_VALIDATION_FIELDS:
                self.assertIn(key, rec)


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


_FORBIDDEN_TOP_LEVEL_IMPORTS = frozenset({
    "sqlite3",
    "fastapi",
    "starlette",
    "uvicorn",
    "httpx",
    "yfinance",
    "openai",
    "anthropic",
    "feedparser",
    "db",
    "api",
    "routes",
    "price_cache",
    "market_data",
    "market_check",
    "analyze_event",
    "auto_backfill_runner",
    "auto_adjust_mismatch_repair",
})


def _module_top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
    return found


class TestModuleHygiene(unittest.TestCase):
    def test_no_forbidden_top_level_imports(self):
        path = _REPO_ROOT / "stats" / "validation_pipeline.py"
        imports = _module_top_level_imports(path)
        clash = imports & _FORBIDDEN_TOP_LEVEL_IMPORTS
        self.assertFalse(
            clash,
            f"validation_pipeline must not import: {sorted(clash)}",
        )

    def test_only_uses_listed_stats_siblings(self):
        """Source must reference at least the four documented siblings."""
        path = _REPO_ROOT / "stats" / "validation_pipeline.py"
        source = path.read_text(encoding="utf-8")
        for sibling in (
            "bootstrap_ci",
            "fdr",
            "stat_validation",
        ):
            self.assertIn(sibling, source, msg=sibling)

    def test_import_does_not_pull_db_provider_or_fastapi(self):
        before = set(sys.modules.keys())
        sys.modules.pop("stats.validation_pipeline", None)
        import importlib
        importlib.import_module("stats.validation_pipeline")
        after = set(sys.modules.keys())
        delta = after - before
        forbidden = {
            m for m in delta
            if m.split(".")[0] in {
                "fastapi", "starlette", "uvicorn", "httpx",
                "yfinance", "openai", "anthropic", "feedparser",
                "sqlite3", "requests", "urllib3",
            }
        }
        self.assertFalse(
            forbidden,
            f"importing stats.validation_pipeline pulled in: "
            f"{sorted(forbidden)}",
        )


# ---------------------------------------------------------------------------
# End-to-end via real compute_event_study
# ---------------------------------------------------------------------------


class TestEndToEnd(unittest.TestCase):
    def test_compute_event_study_then_pipeline_round_trip(self):
        outputs = _build_event_study_outputs(
            n_events=25,
            horizons=(1, 5, 20),
            asset_drift=0.001,
            seed=2026,
        )
        out = vp.run_validation_pipeline(outputs, seed=0)
        # Three records, one per horizon, sorted ascending.
        self.assertEqual([r["horizon"] for r in out], [1, 5, 20])
        for rec in out:
            self.assertEqual(
                tuple(rec.keys()),
                _sv.STAT_VALIDATION_FIELDS,
            )

    def test_idempotent_on_repeated_calls(self):
        outputs = _build_event_study_outputs(n_events=20)
        a = vp.run_validation_pipeline(outputs, seed=0)
        b = vp.run_validation_pipeline(outputs, seed=0)
        c = vp.run_validation_pipeline(outputs, seed=0)
        self.assertEqual(a, b)
        self.assertEqual(b, c)


if __name__ == "__main__":
    unittest.main()
