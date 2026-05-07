"""
Tests for stats.bootstrap_ci.

Pure deterministic bootstrap mean confidence interval utility.
No DB, no provider, no LLM, no FastAPI, no network.

Public surface under test:
    - bootstrap_mean_ci(samples, *, confidence, n_bootstrap, seed, min_samples)
    - bootstrap_ar_ci(abnormal_returns, **kwargs)
    - bootstrap_sar_ci(sar_values, **kwargs)
"""

from __future__ import annotations

import ast
import math
import os
import sys
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from stats import bootstrap_ci as bci  # noqa: E402


# ---------------------------------------------------------------------------
# Test data builders
# ---------------------------------------------------------------------------

def _ar_like(n: int = 32, seed: int = 1) -> list[float]:
    """Synthetic abnormal-return-like sample with mean ~0.003."""
    import random as _r
    rng = _r.Random(seed)
    return [rng.gauss(0.003, 0.012) for _ in range(n)]


def _sar_like(n: int = 32, seed: int = 7) -> list[float]:
    """Synthetic standardized abnormal-return-like sample with mean ~0.4, stdev ~1.0."""
    import random as _r
    rng = _r.Random(seed)
    return [rng.gauss(0.4, 1.0) for _ in range(n)]


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

class TestOutputShape(unittest.TestCase):
    def test_happy_path_keys_are_stable(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=0)
        expected_keys = {
            "ok",
            "n",
            "n_input",
            "mean",
            "lower",
            "upper",
            "confidence",
            "n_bootstrap",
            "seed",
            "min_samples",
            "insufficient_data",
            "reason",
            "kind",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_insufficient_data_keys_match_happy_path(self):
        good = bci.bootstrap_mean_ci(_ar_like(), seed=0)
        bad = bci.bootstrap_mean_ci([0.1, 0.2], seed=0, min_samples=8)
        self.assertEqual(set(good.keys()), set(bad.keys()))

    def test_kind_is_mean_for_default(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=0)
        self.assertEqual(result["kind"], "mean")

    def test_kind_is_ar_for_ar_wrapper(self):
        result = bci.bootstrap_ar_ci(_ar_like(), seed=0)
        self.assertEqual(result["kind"], "ar")

    def test_kind_is_sar_for_sar_wrapper(self):
        result = bci.bootstrap_sar_ci(_sar_like(), seed=0)
        self.assertEqual(result["kind"], "sar")

    def test_returns_python_floats_not_numpy(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=0)
        for k in ("mean", "lower", "upper"):
            self.assertIsInstance(result[k], float, msg=k)
        # Confidence is also a float, not numpy.
        self.assertIsInstance(result["confidence"], float)

    def test_insufficient_data_floats_are_none(self):
        result = bci.bootstrap_mean_ci([0.1, 0.2], seed=0, min_samples=8)
        self.assertIsNone(result["mean"])
        self.assertIsNone(result["lower"])
        self.assertIsNone(result["upper"])
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])
        self.assertIsInstance(result["reason"], str)


# ---------------------------------------------------------------------------
# Determinism / reproducibility
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_inputs_same_output(self):
        sample = _ar_like()
        a = bci.bootstrap_mean_ci(sample, seed=42)
        b = bci.bootstrap_mean_ci(sample, seed=42)
        self.assertEqual(a, b)

    def test_different_seed_changes_ci_endpoints(self):
        sample = _ar_like()
        a = bci.bootstrap_mean_ci(sample, seed=1)
        b = bci.bootstrap_mean_ci(sample, seed=2)
        # Endpoints almost surely differ across seeds for a non-degenerate sample.
        self.assertNotEqual((a["lower"], a["upper"]), (b["lower"], b["upper"]))

    def test_default_seed_is_zero(self):
        sample = _ar_like()
        default_seeded = bci.bootstrap_mean_ci(sample)
        explicit_zero = bci.bootstrap_mean_ci(sample, seed=0)
        self.assertEqual(default_seeded, explicit_zero)

    def test_does_not_consume_global_random_state(self):
        import random as _r
        _r.seed(123)
        before = _r.random()
        _r.seed(123)
        bci.bootstrap_mean_ci(_ar_like(), seed=99)
        after = _r.random()
        # Calling our utility must not perturb the global RNG.
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Insufficient data / safety
# ---------------------------------------------------------------------------

class TestInsufficientData(unittest.TestCase):
    def test_empty_sample_flagged_insufficient(self):
        result = bci.bootstrap_mean_ci([], seed=0)
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["n"], 0)

    def test_single_element_flagged_insufficient(self):
        result = bci.bootstrap_mean_ci([0.5], seed=0)
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["n"], 1)

    def test_below_min_samples_flagged_insufficient(self):
        result = bci.bootstrap_mean_ci([0.1] * 5, seed=0, min_samples=8)
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["n"], 5)

    def test_at_min_samples_threshold_is_sufficient(self):
        result = bci.bootstrap_mean_ci([0.1] * 8, seed=0, min_samples=8)
        self.assertFalse(result["insufficient_data"])
        self.assertTrue(result["ok"])

    def test_min_samples_one_with_two_elements_is_sufficient(self):
        result = bci.bootstrap_mean_ci([0.1, 0.2], seed=0, min_samples=1)
        self.assertFalse(result["insufficient_data"])
        self.assertTrue(result["ok"])

    def test_all_nan_flagged_insufficient(self):
        result = bci.bootstrap_mean_ci([float("nan")] * 12, seed=0)
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["n"], 0)
        self.assertEqual(result["n_input"], 12)

    def test_all_inf_flagged_insufficient(self):
        result = bci.bootstrap_mean_ci(
            [float("inf"), float("-inf")] * 6,
            seed=0,
        )
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])

    def test_mixed_finite_and_nan_uses_finite_count(self):
        sample = [0.1] * 10 + [float("nan")] * 5
        result = bci.bootstrap_mean_ci(sample, seed=0, min_samples=8)
        self.assertEqual(result["n_input"], 15)
        self.assertEqual(result["n"], 10)
        self.assertFalse(result["insufficient_data"])

    def test_reason_string_is_informative_when_insufficient(self):
        result = bci.bootstrap_mean_ci([0.1] * 3, seed=0, min_samples=8)
        self.assertIsInstance(result["reason"], str)
        # Reason must mention insufficient data and identify the n / threshold.
        self.assertIn("insufficient_data", result["reason"])
        self.assertIn("3", result["reason"])
        self.assertIn("8", result["reason"])

    def test_reason_is_none_on_success(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=0)
        self.assertIsNone(result["reason"])


# ---------------------------------------------------------------------------
# CI correctness
# ---------------------------------------------------------------------------

class TestConfidenceIntervalProperties(unittest.TestCase):
    def test_ci_brackets_sample_mean(self):
        sample = _ar_like(n=64)
        result = bci.bootstrap_mean_ci(sample, seed=0)
        self.assertTrue(result["ok"])
        self.assertLessEqual(result["lower"], result["mean"])
        self.assertLessEqual(result["mean"], result["upper"])

    def test_ci_lower_le_upper(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=0)
        self.assertLessEqual(result["lower"], result["upper"])

    def test_constant_sample_collapses_to_point(self):
        result = bci.bootstrap_mean_ci([0.42] * 16, seed=0)
        self.assertAlmostEqual(result["mean"], 0.42, places=12)
        self.assertAlmostEqual(result["lower"], 0.42, places=12)
        self.assertAlmostEqual(result["upper"], 0.42, places=12)

    def test_higher_confidence_is_wider_or_equal(self):
        sample = _ar_like(n=64)
        narrow = bci.bootstrap_mean_ci(sample, seed=0, confidence=0.80)
        wide = bci.bootstrap_mean_ci(sample, seed=0, confidence=0.99)
        narrow_w = narrow["upper"] - narrow["lower"]
        wide_w = wide["upper"] - wide["lower"]
        self.assertLessEqual(narrow_w, wide_w + 1e-12)

    def test_mean_matches_sample_mean(self):
        sample = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        result = bci.bootstrap_mean_ci(sample, seed=0)
        self.assertAlmostEqual(result["mean"], sum(sample) / len(sample), places=12)

    def test_negative_values_handled(self):
        sample = [-x for x in _ar_like(n=32)]
        result = bci.bootstrap_mean_ci(sample, seed=0)
        self.assertTrue(result["ok"])
        # Lower bound for a negative-mean sample is itself negative-ish.
        self.assertLessEqual(result["lower"], result["upper"])

    def test_ci_contains_true_mean_for_known_distribution_seeded(self):
        """Coverage sanity: with a tight known-mean sample and a seeded RNG,
        the bootstrap mean CI should bracket the population mean used to
        generate the sample. Determinism makes this a hard equality check."""
        import random as _r
        rng = _r.Random(2026)
        true_mean = 0.0
        sample = [rng.gauss(true_mean, 1.0) for _ in range(200)]
        result = bci.bootstrap_mean_ci(sample, seed=0, confidence=0.95)
        self.assertLessEqual(result["lower"], true_mean)
        self.assertGreaterEqual(result["upper"], true_mean)

    def test_n_bootstrap_propagates_to_payload(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=0, n_bootstrap=500)
        self.assertEqual(result["n_bootstrap"], 500)

    def test_seed_propagates_to_payload(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=17)
        self.assertEqual(result["seed"], 17)

    def test_confidence_propagates_to_payload(self):
        result = bci.bootstrap_mean_ci(_ar_like(), seed=0, confidence=0.90)
        self.assertAlmostEqual(result["confidence"], 0.90)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestInputValidation(unittest.TestCase):
    def test_confidence_at_or_below_zero_raises(self):
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), confidence=0.0)
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), confidence=-0.5)

    def test_confidence_at_or_above_one_raises(self):
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), confidence=1.0)
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), confidence=1.5)

    def test_n_bootstrap_must_be_positive(self):
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), n_bootstrap=0)
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), n_bootstrap=-10)

    def test_min_samples_must_be_positive(self):
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), min_samples=0)
        with self.assertRaises(ValueError):
            bci.bootstrap_mean_ci(_ar_like(), min_samples=-1)

    def test_seed_must_be_integer(self):
        with self.assertRaises(TypeError):
            bci.bootstrap_mean_ci(_ar_like(), seed=0.5)
        with self.assertRaises(TypeError):
            bci.bootstrap_mean_ci(_ar_like(), seed="0")

    def test_string_element_raises_typeerror(self):
        with self.assertRaises(TypeError):
            bci.bootstrap_mean_ci(["a", "b", "c"], seed=0)

    def test_dict_element_raises_typeerror(self):
        with self.assertRaises(TypeError):
            bci.bootstrap_mean_ci([{"x": 1}], seed=0)

    def test_none_element_raises_typeerror(self):
        with self.assertRaises(TypeError):
            bci.bootstrap_mean_ci([0.1, None, 0.2], seed=0)

    def test_non_iterable_raises(self):
        with self.assertRaises(TypeError):
            bci.bootstrap_mean_ci(42, seed=0)

    def test_tuple_input_accepted(self):
        result = bci.bootstrap_mean_ci(tuple([0.1] * 12), seed=0)
        self.assertTrue(result["ok"])

    def test_generator_input_consumed(self):
        gen = (x * 0.01 for x in range(20))
        result = bci.bootstrap_mean_ci(gen, seed=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["n"], 20)


# ---------------------------------------------------------------------------
# Wrappers
# ---------------------------------------------------------------------------

class TestArSarWrappers(unittest.TestCase):
    def test_ar_wrapper_matches_core_with_kind_override(self):
        sample = _ar_like()
        core = bci.bootstrap_mean_ci(sample, seed=11, confidence=0.90)
        ar = bci.bootstrap_ar_ci(sample, seed=11, confidence=0.90)
        for k in ("mean", "lower", "upper", "n", "n_bootstrap", "seed", "confidence"):
            self.assertEqual(ar[k], core[k], msg=k)
        self.assertEqual(ar["kind"], "ar")
        self.assertEqual(core["kind"], "mean")

    def test_sar_wrapper_matches_core_with_kind_override(self):
        sample = _sar_like()
        core = bci.bootstrap_mean_ci(sample, seed=11, confidence=0.90)
        sar = bci.bootstrap_sar_ci(sample, seed=11, confidence=0.90)
        for k in ("mean", "lower", "upper", "n", "n_bootstrap", "seed", "confidence"):
            self.assertEqual(sar[k], core[k], msg=k)
        self.assertEqual(sar["kind"], "sar")

    def test_ar_wrapper_handles_insufficient_data(self):
        result = bci.bootstrap_ar_ci([0.1, 0.2], seed=0, min_samples=8)
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "ar")

    def test_sar_wrapper_handles_insufficient_data(self):
        result = bci.bootstrap_sar_ci([], seed=0)
        self.assertTrue(result["insufficient_data"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "sar")


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
    "pandas",
    "requests",
    "urllib3",
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
        path = _REPO_ROOT / "stats" / "bootstrap_ci.py"
        imports = _module_top_level_imports(path)
        clash = imports & _FORBIDDEN_TOP_LEVEL_IMPORTS
        self.assertFalse(
            clash,
            f"bootstrap_ci must not import: {sorted(clash)}",
        )

    def test_no_db_or_provider_runtime_calls(self):
        """Importing the module must not pull in DB / FastAPI / provider modules."""
        before = set(sys.modules.keys())
        # Force a fresh import.
        sys.modules.pop("stats.bootstrap_ci", None)
        import importlib
        importlib.import_module("stats.bootstrap_ci")
        after = set(sys.modules.keys())
        delta = after - before
        forbidden_present = {
            m for m in delta
            if m.split(".")[0] in {
                "fastapi", "starlette", "uvicorn", "httpx", "yfinance",
                "openai", "anthropic", "pandas", "requests", "urllib3",
                "feedparser",
            }
        }
        self.assertFalse(
            forbidden_present,
            f"importing stats.bootstrap_ci pulled in: {sorted(forbidden_present)}",
        )

    def test_module_has_public_callables(self):
        for name in ("bootstrap_mean_ci", "bootstrap_ar_ci", "bootstrap_sar_ci"):
            self.assertTrue(callable(getattr(bci, name)), msg=name)


# ---------------------------------------------------------------------------
# Stress / edge sanity
# ---------------------------------------------------------------------------

class TestEdgeStress(unittest.TestCase):
    def test_two_element_sample_min_one_works(self):
        result = bci.bootstrap_mean_ci([1.0, 3.0], seed=0, min_samples=1)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["mean"], 2.0)
        self.assertGreaterEqual(result["lower"], 1.0 - 1e-9)
        self.assertLessEqual(result["upper"], 3.0 + 1e-9)

    def test_large_sample_runs_under_short_time(self):
        sample = _ar_like(n=500)
        # Just ensure it returns and is valid; performance is bounded by n_bootstrap.
        result = bci.bootstrap_mean_ci(sample, seed=0, n_bootstrap=200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["n"], 500)

    def test_int_inputs_treated_as_floats(self):
        result = bci.bootstrap_mean_ci([1, 2, 3, 4, 5, 6, 7, 8], seed=0)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["mean"], 4.5)
        self.assertIsInstance(result["mean"], float)


if __name__ == "__main__":
    unittest.main()
