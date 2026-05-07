"""Tests for ``stats/fdr.py``.

Pin the contract:

* Pure deterministic — repeated calls produce identical output;
  the input list is never mutated.
* Output shape: dict with ``adjusted``, ``discoveries``,
  ``num_discoveries``, ``m``, ``alpha``.  ``adjusted`` and
  ``discoveries`` have the same length as the input and preserve
  input order.
* Algorithm: matches R's ``p.adjust(p, method = "BH")`` reference,
  including the running-min monotonicity step and the ``[0, 1]``
  clamp.
* Empty / one-value / ties / invalid p-values are all handled
  without raising; invalid entries carry ``None`` / ``False`` and
  do not contribute to ``m``.
* ``alpha`` must be a finite number in ``(0, 1]``; otherwise
  ``ValueError``.
* No DB / provider / LLM / FastAPI seam is touched.
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stats.fdr import bh_adjust  # noqa: E402


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


_TOP_KEYS = ("adjusted", "discoveries", "num_discoveries", "m", "alpha")


class TestShape(unittest.TestCase):
    def test_returns_dict_with_expected_keys(self) -> None:
        result = bh_adjust([0.1, 0.2, 0.3])
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_adjusted_and_discoveries_match_input_length(self) -> None:
        for n in (0, 1, 2, 5, 17):
            with self.subTest(n=n):
                result = bh_adjust([0.5] * n)
                self.assertEqual(len(result["adjusted"]),    n)
                self.assertEqual(len(result["discoveries"]), n)

    def test_alpha_is_echoed_as_float(self) -> None:
        result = bh_adjust([0.1], alpha=0.01)
        self.assertEqual(result["alpha"], 0.01)
        self.assertIsInstance(result["alpha"], float)

    def test_default_alpha_is_zero_point_zero_five(self) -> None:
        # Sentinel: a p-value of exactly 0.05 must be a discovery
        # under the default alpha (== 0.05) and not under alpha=0.01.
        self.assertTrue(bh_adjust([0.05])["discoveries"][0])
        self.assertFalse(bh_adjust([0.05], alpha=0.01)["discoveries"][0])


# ---------------------------------------------------------------------------
# Empty / single-value
# ---------------------------------------------------------------------------


class TestEmptyAndSingle(unittest.TestCase):
    def test_empty_input_yields_empty_outputs(self) -> None:
        result = bh_adjust([])
        self.assertEqual(result["adjusted"],        [])
        self.assertEqual(result["discoveries"],     [])
        self.assertEqual(result["num_discoveries"], 0)
        self.assertEqual(result["m"],               0)

    def test_single_valid_below_alpha_is_discovery(self) -> None:
        result = bh_adjust([0.01])
        # m=1 → adjusted == p clamped to [0, 1] == 0.01
        self.assertEqual(result["adjusted"],        [0.01])
        self.assertEqual(result["discoveries"],     [True])
        self.assertEqual(result["num_discoveries"], 1)
        self.assertEqual(result["m"],               1)

    def test_single_valid_above_alpha_is_not_discovery(self) -> None:
        result = bh_adjust([0.5])
        self.assertEqual(result["adjusted"],        [0.5])
        self.assertEqual(result["discoveries"],     [False])
        self.assertEqual(result["num_discoveries"], 0)
        self.assertEqual(result["m"],               1)

    def test_single_invalid_yields_none_and_false(self) -> None:
        result = bh_adjust([float("nan")])
        self.assertEqual(result["adjusted"],        [None])
        self.assertEqual(result["discoveries"],     [False])
        self.assertEqual(result["num_discoveries"], 0)
        self.assertEqual(result["m"],               0)


# ---------------------------------------------------------------------------
# Reference vector — R's ``p.adjust(p, method = "BH")``
# ---------------------------------------------------------------------------


_REFERENCE_INPUT = [0.01, 0.04, 0.03, 0.20, 0.50]
# Computed by hand and cross-checked against R:
#   sorted: 0.01, 0.03, 0.04, 0.20, 0.50  (m=5)
#   raw_q at each rank (5/k * p_(k)):
#     k=1: 5/1*0.01 = 0.05
#     k=2: 5/2*0.03 = 0.075
#     k=3: 5/3*0.04 = 0.0666...
#     k=4: 5/4*0.20 = 0.25
#     k=5: 5/5*0.50 = 0.50
#   running min from the right:
#     k=5: 0.50
#     k=4: 0.25
#     k=3: 0.0666...
#     k=2: 0.0666...     (raw 0.075 is larger, so the rank-3 min wins)
#     k=1: 0.05          (raw 0.05 is smaller than 0.0666...)
#   restore to input order [0.01, 0.04, 0.03, 0.20, 0.50]:
#     0.01 -> rank 1 -> 0.05
#     0.04 -> rank 3 -> 0.0666...
#     0.03 -> rank 2 -> 0.0666...
#     0.20 -> rank 4 -> 0.25
#     0.50 -> rank 5 -> 0.50
_REFERENCE_EXPECTED = [0.05, 1.0 / 15.0, 1.0 / 15.0, 0.25, 0.50]


class TestKnownReference(unittest.TestCase):
    def test_matches_r_p_adjust_bh_method(self) -> None:
        result = bh_adjust(_REFERENCE_INPUT)
        self.assertEqual(result["m"], 5)
        for got, exp in zip(result["adjusted"], _REFERENCE_EXPECTED):
            self.assertIsNotNone(got)
            self.assertAlmostEqual(got, exp, places=12)

    def test_reference_alpha_05_yields_one_discovery(self) -> None:
        # Only the smallest adjusted p-value (0.05) is at-or-below
        # alpha=0.05.  num_discoveries must be 1 and the discovery
        # mask must mark only the input ``0.01`` position.
        result = bh_adjust(_REFERENCE_INPUT, alpha=0.05)
        self.assertEqual(result["num_discoveries"], 1)
        self.assertEqual(result["discoveries"], [True, False, False, False, False])

    def test_reference_alpha_07_lifts_extra_discoveries(self) -> None:
        # Adjusted p-values at ranks 1, 2, 3 are 0.05 and 0.0666...
        # Both are <= 0.07, so three discoveries appear.
        result = bh_adjust(_REFERENCE_INPUT, alpha=0.07)
        self.assertEqual(result["num_discoveries"], 3)
        # Original input was [0.01, 0.04, 0.03, 0.20, 0.50]; the
        # first three are the small p-values at ranks 1, 3, 2.
        self.assertEqual(result["discoveries"], [True, True, True, False, False])


# ---------------------------------------------------------------------------
# Ties
# ---------------------------------------------------------------------------


class TestTies(unittest.TestCase):
    def test_tied_pvalues_receive_equal_adjusted_values(self) -> None:
        # sorted: [0.01, 0.04, 0.04, 0.10] (m=4)
        #   k=1: 4*0.01 = 0.04
        #   k=2: 2*0.04 = 0.08
        #   k=3: 4/3*0.04 = 0.0533...
        #   k=4: 0.10
        # cummin from right -> [0.04, 0.0533..., 0.0533..., 0.10]
        # restore order [0.04, 0.01, 0.10, 0.04]:
        #   0.04 -> tie at rank 2 or 3 -> 0.0533...
        #   0.01 -> rank 1 -> 0.04
        #   0.10 -> rank 4 -> 0.10
        #   0.04 -> tie at rank 2 or 3 -> 0.0533...
        result = bh_adjust([0.04, 0.01, 0.10, 0.04])
        adj = result["adjusted"]
        self.assertAlmostEqual(adj[0], 4.0 / 75.0, places=12)
        self.assertAlmostEqual(adj[1], 0.04,        places=12)
        self.assertAlmostEqual(adj[2], 0.10,        places=12)
        self.assertAlmostEqual(adj[3], 4.0 / 75.0, places=12)
        # Confirm the two tied positions get the SAME value
        # (tie-invariance — no inversion).
        self.assertEqual(adj[0], adj[3])

    def test_all_zero_pvalues_yield_all_zero_adjusted(self) -> None:
        result = bh_adjust([0.0, 0.0, 0.0])
        self.assertEqual(result["adjusted"], [0.0, 0.0, 0.0])
        self.assertEqual(result["discoveries"], [True, True, True])

    def test_all_one_pvalues_yield_all_one_adjusted(self) -> None:
        result = bh_adjust([1.0, 1.0, 1.0, 1.0])
        for adj in result["adjusted"]:
            self.assertAlmostEqual(adj, 1.0, places=12)
        # alpha=0.05 default -> none below threshold.
        self.assertEqual(result["discoveries"], [False] * 4)


# ---------------------------------------------------------------------------
# Monotonicity & clamp
# ---------------------------------------------------------------------------


class TestMonotonicityAndClamp(unittest.TestCase):
    def test_adjusted_is_monotone_in_sorted_rank_order(self) -> None:
        # The adjusted series is non-decreasing in original-rank order.
        # Random-ish input, deterministic seed-free.
        ps = [0.001, 0.5, 0.04, 0.27, 0.13, 0.05, 0.99, 0.0001, 0.07]
        result = bh_adjust(ps)
        # Pair each input with its adjusted, sort by input, walk.
        pairs = sorted(zip(ps, result["adjusted"]), key=lambda x: x[0])
        prev = -math.inf
        for p, q in pairs:
            self.assertIsNotNone(q)
            self.assertGreaterEqual(q, prev,
                                    f"q={q} broke monotonicity after {prev}")
            prev = q

    def test_adjusted_is_clamped_to_unit_interval(self) -> None:
        # Large p-values produce raw_q > 1; the clamp must keep
        # adjusted in [0, 1].  Use a single p of 0.9 with m=1 first
        # (no clamp triggered), then m=3 with all p>=0.5 to trigger.
        single = bh_adjust([0.9])
        self.assertEqual(single["adjusted"], [0.9])

        many = bh_adjust([0.6, 0.7, 0.8, 0.9, 1.0])
        for adj in many["adjusted"]:
            self.assertIsNotNone(adj)
            self.assertGreaterEqual(adj, 0.0)
            self.assertLessEqual(adj,    1.0)
        # All five adjusted values collapse to 1.0 because the
        # rank-5 raw is 1.0 and earlier ranks have raw_q > 1
        # (capped to 1 by the running min once it hits the rank-5
        # value).  R returns the same.
        for adj in many["adjusted"]:
            self.assertAlmostEqual(adj, 1.0, places=12)


# ---------------------------------------------------------------------------
# Order preservation
# ---------------------------------------------------------------------------


class TestOrderPreservation(unittest.TestCase):
    def test_input_order_preserved_in_outputs(self) -> None:
        # Reverse the reference input — adjusted must reverse to match.
        forward = bh_adjust(_REFERENCE_INPUT)["adjusted"]
        backward = bh_adjust(list(reversed(_REFERENCE_INPUT)))["adjusted"]
        self.assertEqual(forward, list(reversed(backward)))


# ---------------------------------------------------------------------------
# Invalid p-values
# ---------------------------------------------------------------------------


_INVALID_VALUES = [
    None,
    "0.05",
    [0.05],
    {"p": 0.05},
    object(),
    True,
    False,
    float("nan"),
    float("inf"),
    -float("inf"),
    -0.0001,
    1.0001,
    -1.0,
    2.0,
]


class TestInvalidPValues(unittest.TestCase):
    def test_each_invalid_value_carries_none_and_false(self) -> None:
        for bad in _INVALID_VALUES:
            with self.subTest(value=repr(bad)):
                result = bh_adjust([bad])
                self.assertEqual(result["adjusted"],        [None],
                                 f"unexpected adjusted for {bad!r}")
                self.assertEqual(result["discoveries"],     [False],
                                 f"unexpected discovery for {bad!r}")
                self.assertEqual(result["m"],               0)
                self.assertEqual(result["num_discoveries"], 0)

    def test_invalid_entries_do_not_change_m_for_valid_neighbours(self) -> None:
        # Same valid p-values, but one run has an extra invalid.
        # m must be the count of valids, identical across both runs;
        # the adjusted values for the valids must also be identical.
        valids = [0.01, 0.04, 0.03, 0.20, 0.50]
        plain = bh_adjust(valids)
        with_garbage = bh_adjust(
            [valids[0], None, valids[1], float("nan"), valids[2],
             "string", valids[3], -1.0, valids[4], float("inf")],
        )
        self.assertEqual(plain["m"],               5)
        self.assertEqual(with_garbage["m"],        5)
        # Pull the non-None entries out of the garbage run; they must
        # match the plain run in order.
        valid_q = [q for q in with_garbage["adjusted"] if q is not None]
        self.assertEqual(len(valid_q), 5)
        for got, exp in zip(valid_q, plain["adjusted"]):
            self.assertAlmostEqual(got, exp, places=12)

    def test_all_invalid_yields_all_none_and_false(self) -> None:
        result = bh_adjust([float("nan"), None, "x", -1.0, 2.0])
        self.assertEqual(result["adjusted"],        [None] * 5)
        self.assertEqual(result["discoveries"],     [False] * 5)
        self.assertEqual(result["m"],               0)
        self.assertEqual(result["num_discoveries"], 0)

    def test_pvalue_at_boundaries_zero_and_one_is_valid(self) -> None:
        # 0.0 and 1.0 are inclusive bounds — both must pass validation.
        result = bh_adjust([0.0, 1.0])
        self.assertEqual(result["m"], 2)
        # Sorted: [0.0, 1.0]; raw_q: [0.0, 1.0]; cummin: [0.0, 1.0].
        # adjusted preserves input order [0.0, 1.0].
        self.assertEqual(result["adjusted"],    [0.0, 1.0])
        self.assertEqual(result["discoveries"], [True, False])


# ---------------------------------------------------------------------------
# alpha validation
# ---------------------------------------------------------------------------


class TestAlphaValidation(unittest.TestCase):
    def test_alpha_one_admits_every_valid_pvalue(self) -> None:
        result = bh_adjust([0.001, 0.5, 0.99], alpha=1.0)
        self.assertEqual(result["discoveries"], [True, True, True])
        self.assertEqual(result["num_discoveries"], 3)

    def test_alpha_below_smallest_adjusted_yields_no_discoveries(self) -> None:
        result = bh_adjust([0.5, 0.6, 0.7], alpha=0.0001)
        self.assertEqual(result["discoveries"], [False, False, False])
        self.assertEqual(result["num_discoveries"], 0)

    def test_zero_alpha_raises(self) -> None:
        with self.assertRaises(ValueError):
            bh_adjust([0.1], alpha=0.0)

    def test_negative_alpha_raises(self) -> None:
        with self.assertRaises(ValueError):
            bh_adjust([0.1], alpha=-0.01)

    def test_alpha_above_one_raises(self) -> None:
        with self.assertRaises(ValueError):
            bh_adjust([0.1], alpha=1.0001)

    def test_nan_or_inf_alpha_raises(self) -> None:
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=repr(bad)):
                with self.assertRaises(ValueError):
                    bh_adjust([0.1], alpha=bad)

    def test_non_numeric_alpha_raises(self) -> None:
        for bad in ("0.05", None, [0.05], {"a": 1}, object()):
            with self.subTest(value=repr(bad)):
                with self.assertRaises(ValueError):
                    bh_adjust([0.1], alpha=bad)

    def test_bool_alpha_raises(self) -> None:
        # True coerces to 1.0 silently in plain arithmetic; reject
        # so accidental ``alpha=True`` doesn't lift every test to
        # discovery without warning.
        with self.assertRaises(ValueError):
            bh_adjust([0.1], alpha=True)
        with self.assertRaises(ValueError):
            bh_adjust([0.1], alpha=False)


# ---------------------------------------------------------------------------
# Determinism & no input mutation
# ---------------------------------------------------------------------------


class TestDeterminismAndNoMutation(unittest.TestCase):
    def test_repeated_calls_return_identical_payload(self) -> None:
        ps = [0.01, 0.04, 0.03, 0.20, 0.50, float("nan"), 0.07]
        first = bh_adjust(ps, alpha=0.05)
        for _ in range(5):
            again = bh_adjust(ps, alpha=0.05)
            self.assertEqual(first, again)

    def test_input_list_is_not_mutated(self) -> None:
        ps = [0.04, 0.01, 0.10, 0.04, float("nan"), None]
        snapshot = list(ps)
        bh_adjust(ps)
        self.assertEqual(ps, snapshot,
                         "bh_adjust must not mutate its input list")

    def test_accepts_arbitrary_iterable_not_just_list(self) -> None:
        # tuple, generator, range — all iterables should work.
        list_result   = bh_adjust([0.01, 0.04, 0.03, 0.20, 0.50])
        tuple_result  = bh_adjust((0.01, 0.04, 0.03, 0.20, 0.50))
        gen_result    = bh_adjust(p for p in [0.01, 0.04, 0.03, 0.20, 0.50])
        self.assertEqual(list_result, tuple_result)
        self.assertEqual(list_result, gen_result)


# ---------------------------------------------------------------------------
# BH step-up equivalence — the reference algorithmic property
# ---------------------------------------------------------------------------


def _bh_stepup_rejections(p_values: list[float], alpha: float) -> list[bool]:
    """Reference BH step-up procedure.

    For sorted p-values ``p_(1) <= ... <= p_(m)``, find the largest
    ``k`` such that ``p_(k) <= (k/m) * alpha``; reject hypotheses
    1 through ``k``.  Returns a bool mask in input order.

    This is the original Benjamini-Hochberg (1995) decision rule.
    The adjusted-p-value formulation reproduces the same rejection
    set when compared at threshold ``alpha`` — that property is what
    this test cross-checks against.
    """
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(range(n), key=lambda i: p_values[i])
    m = n
    k_star = -1
    for k_zero, idx in enumerate(indexed):
        rank = k_zero + 1
        if p_values[idx] <= (rank / m) * alpha:
            k_star = k_zero
    rejected = [False] * n
    if k_star >= 0:
        for k_zero in range(k_star + 1):
            rejected[indexed[k_zero]] = True
    return rejected


class TestStepUpEquivalence(unittest.TestCase):
    def test_discoveries_match_step_up_procedure(self) -> None:
        cases = [
            ([0.01, 0.04, 0.03, 0.20, 0.50],                0.05),
            ([0.01, 0.04, 0.03, 0.20, 0.50],                0.07),
            ([0.001, 0.002, 0.04, 0.05],                    0.05),
            ([0.5, 0.6, 0.7, 0.8],                          0.05),
            ([0.0001, 0.0002, 0.0003],                      0.001),
            ([0.04, 0.01, 0.10, 0.04],                      0.05),
            ([0.5],                                         0.5),
            ([0.05],                                        0.05),
        ]
        for ps, alpha in cases:
            with self.subTest(p_values=ps, alpha=alpha):
                got = bh_adjust(ps, alpha=alpha)["discoveries"]
                expected = _bh_stepup_rejections(ps, alpha)
                self.assertEqual(
                    got, expected,
                    f"discovery mismatch: bh_adjust={got} stepup={expected} "
                    f"for p={ps}, alpha={alpha}",
                )


# ---------------------------------------------------------------------------
# No external seam — module imports nothing project-specific
# ---------------------------------------------------------------------------


class TestNoExternalSeam(unittest.TestCase):
    def test_module_imports_only_stdlib(self) -> None:
        # The module's public surface must not pull in anything
        # project-specific or networked.  Walk the AST of fdr.py and
        # collect every top-level import; assert each is stdlib.
        import ast

        from stats import fdr as _fdr

        with open(_fdr.__file__, "r", encoding="utf-8") as fp:
            tree = ast.parse(fp.read(), filename=_fdr.__file__)

        # Standard-library modules the implementation may legitimately
        # pull in.  ``__future__`` is stdlib syntax; ``typing`` is
        # stdlib.  Anything else is a contract violation.
        allowed = {"__future__", "math", "typing"}

        observed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    observed.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    observed.add(node.module.split(".", 1)[0])

        unexpected = observed - allowed
        self.assertEqual(
            unexpected, set(),
            f"stats.fdr must not import non-stdlib modules; got "
            f"{sorted(unexpected)}",
        )

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        from stats import fdr as _fdr
        self.assertFalse(hasattr(_fdr, "app"))
        self.assertFalse(hasattr(_fdr, "router"))

    def test_running_does_not_import_db_provider_llm(self) -> None:
        # Order-independent guard: instrument ``builtins.__import__``
        # so any actual import statement targeting a project-specific
        # module is recorded — even when an earlier suite has already
        # cached the target in ``sys.modules``.
        import builtins
        from unittest.mock import patch

        forbidden_roots = (
            "db", "api", "routes",
            "market_check", "market_data", "price_cache",
            "yfinance", "openai", "anthropic",
        )

        def _is_forbidden(name: str) -> bool:
            head = name.split(".", 1)[0]
            return head in forbidden_roots

        forbidden_imports: list[str] = []
        real_import = builtins.__import__

        def tracing_import(
            name, globals=None, locals=None, fromlist=(), level=0,
        ):
            if _is_forbidden(name):
                forbidden_imports.append(name)
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=tracing_import):
            bh_adjust([0.01, 0.04, 0.03, 0.20, 0.50], alpha=0.05)

        self.assertEqual(
            forbidden_imports, [],
            f"forbidden imports during bh_adjust: {forbidden_imports}",
        )


if __name__ == "__main__":
    unittest.main()
