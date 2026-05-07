"""Tests for ``stats.p_values.p_value_from_sar``.

Pure stdlib computations against ``math.erfc`` reference values.  The
suite pins:

  * Two-sided p-values at canonical critical points (1.96, 2.576).
  * Symmetry under ``z → -z`` for the two-sided alternative.
  * Complement identity ``p_greater(z) + p_less(z) == 1`` for finite z.
  * Boundary behavior at the six ``±inf × {two-sided, greater, less}``
    combinations.
  * Sentinel propagation: ``None`` and ``NaN`` map to ``None``; the
    function never returns 0.0 / 1.0 for missing input.
  * Strict alternative-string validation (no case folding, no aliases).
"""
from __future__ import annotations

import math
import unittest

from stats.p_values import p_value_from_sar


class TestTwoSidedKnownValues(unittest.TestCase):
    """Pin two-sided p at canonical critical z's."""

    def test_z_at_1p96_two_sided_is_close_to_0p05(self) -> None:
        p = p_value_from_sar(1.96)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p, 0.05, places=3)

    def test_z_at_2p576_two_sided_is_close_to_0p01(self) -> None:
        p = p_value_from_sar(2.576)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p, 0.01, places=3)

    def test_z_at_zero_two_sided_is_exactly_one(self) -> None:
        self.assertEqual(p_value_from_sar(0.0), 1.0)
        self.assertEqual(p_value_from_sar(0), 1.0)

    def test_two_sided_is_symmetric_in_sign(self) -> None:
        for z in (0.5, 1.0, 1.96, 2.5, 3.0, 5.0):
            with self.subTest(z=z):
                self.assertAlmostEqual(
                    p_value_from_sar(z),
                    p_value_from_sar(-z),
                    places=15,
                )

    def test_two_sided_in_unit_interval(self) -> None:
        for z in (-10.0, -3.0, -1.0, 0.0, 1.0, 3.0, 10.0):
            with self.subTest(z=z):
                p = p_value_from_sar(z)
                self.assertIsNotNone(p)
                self.assertGreaterEqual(p, 0.0)
                self.assertLessEqual(p, 1.0)


class TestOneSidedKnownValues(unittest.TestCase):

    def test_z_zero_one_sided_is_one_half(self) -> None:
        self.assertEqual(
            p_value_from_sar(0.0, alternative="greater"), 0.5,
        )
        self.assertEqual(
            p_value_from_sar(0.0, alternative="less"),    0.5,
        )

    def test_greater_decreases_in_z(self) -> None:
        ladder = [-3.0, -1.0, 0.0, 1.0, 3.0]
        ps = [p_value_from_sar(z, alternative="greater") for z in ladder]
        for a, b in zip(ps, ps[1:]):
            self.assertGreater(a, b)

    def test_less_increases_in_z(self) -> None:
        ladder = [-3.0, -1.0, 0.0, 1.0, 3.0]
        ps = [p_value_from_sar(z, alternative="less") for z in ladder]
        for a, b in zip(ps, ps[1:]):
            self.assertLess(a, b)

    def test_greater_and_less_complement_to_one(self) -> None:
        for z in (-3.0, -1.5, -0.25, 0.0, 0.25, 1.5, 3.0):
            with self.subTest(z=z):
                pg = p_value_from_sar(z, alternative="greater")
                pl = p_value_from_sar(z, alternative="less")
                self.assertAlmostEqual(pg + pl, 1.0, places=12)

    def test_greater_at_1p645_is_close_to_0p05(self) -> None:
        p = p_value_from_sar(1.645, alternative="greater")
        self.assertAlmostEqual(p, 0.05, places=3)

    def test_less_at_neg_1p645_is_close_to_0p05(self) -> None:
        p = p_value_from_sar(-1.645, alternative="less")
        self.assertAlmostEqual(p, 0.05, places=3)


class TestInfBoundaries(unittest.TestCase):
    """All six ``±inf × {two-sided, greater, less}`` combinations."""

    def test_pos_inf_two_sided_is_zero(self) -> None:
        self.assertEqual(p_value_from_sar(math.inf), 0.0)

    def test_neg_inf_two_sided_is_zero(self) -> None:
        self.assertEqual(p_value_from_sar(-math.inf), 0.0)

    def test_pos_inf_greater_is_zero(self) -> None:
        self.assertEqual(
            p_value_from_sar(math.inf, alternative="greater"), 0.0,
        )

    def test_neg_inf_greater_is_one(self) -> None:
        self.assertEqual(
            p_value_from_sar(-math.inf, alternative="greater"), 1.0,
        )

    def test_pos_inf_less_is_one(self) -> None:
        self.assertEqual(
            p_value_from_sar(math.inf, alternative="less"), 1.0,
        )

    def test_neg_inf_less_is_zero(self) -> None:
        self.assertEqual(
            p_value_from_sar(-math.inf, alternative="less"), 0.0,
        )


class TestMissingInputs(unittest.TestCase):

    def test_none_returns_none_two_sided(self) -> None:
        self.assertIsNone(p_value_from_sar(None))

    def test_none_returns_none_greater(self) -> None:
        self.assertIsNone(p_value_from_sar(None, alternative="greater"))

    def test_none_returns_none_less(self) -> None:
        self.assertIsNone(p_value_from_sar(None, alternative="less"))

    def test_nan_returns_none(self) -> None:
        self.assertIsNone(p_value_from_sar(float("nan")))
        self.assertIsNone(
            p_value_from_sar(float("nan"), alternative="greater"),
        )
        self.assertIsNone(
            p_value_from_sar(float("nan"), alternative="less"),
        )

    def test_nan_does_not_collapse_to_zero_or_one(self) -> None:
        # Regression guard: ``erfc(nan)`` is NaN; we must not silently
        # produce a numeric p-value for missing input.
        self.assertIsNone(p_value_from_sar(float("nan")))


class TestInvalidAlternative(unittest.TestCase):

    def test_unknown_alternative_raises(self) -> None:
        with self.assertRaises(ValueError):
            p_value_from_sar(1.0, alternative="not-a-thing")

    def test_capitalized_two_sided_raises(self) -> None:
        with self.assertRaises(ValueError):
            p_value_from_sar(1.0, alternative="Two-sided")

    def test_uppercase_greater_raises(self) -> None:
        with self.assertRaises(ValueError):
            p_value_from_sar(1.0, alternative="GREATER")

    def test_alias_two_dot_sided_raises(self) -> None:
        # ``"two.sided"`` is R's spelling — explicitly NOT supported.
        with self.assertRaises(ValueError):
            p_value_from_sar(1.0, alternative="two.sided")

    def test_empty_alternative_raises(self) -> None:
        with self.assertRaises(ValueError):
            p_value_from_sar(1.0, alternative="")

    def test_none_alternative_raises(self) -> None:
        with self.assertRaises((ValueError, TypeError)):
            p_value_from_sar(1.0, alternative=None)  # type: ignore[arg-type]

    def test_invalid_alternative_with_none_input_still_raises(self) -> None:
        # Validate the alternative even when sar is missing — surfacing
        # caller bugs is more useful than silently returning ``None``.
        with self.assertRaises(ValueError):
            p_value_from_sar(None, alternative="bogus")


class TestNumericInputCoercion(unittest.TestCase):

    def test_int_input_works(self) -> None:
        self.assertEqual(p_value_from_sar(0), 1.0)
        self.assertAlmostEqual(
            p_value_from_sar(2), p_value_from_sar(2.0), places=15,
        )

    def test_bool_true_treated_as_one(self) -> None:
        self.assertAlmostEqual(
            p_value_from_sar(True),
            p_value_from_sar(1.0),
            places=15,
        )

    def test_bool_false_treated_as_zero(self) -> None:
        self.assertEqual(p_value_from_sar(False), 1.0)


class TestExtremeFiniteInputs(unittest.TestCase):
    """Large but finite ``z`` should underflow to 0.0, not raise."""

    def test_very_large_positive_two_sided(self) -> None:
        p = p_value_from_sar(50.0)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLess(p, 1e-100)

    def test_very_large_positive_greater(self) -> None:
        p = p_value_from_sar(50.0, alternative="greater")
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLess(p, 1e-100)

    def test_very_large_negative_less(self) -> None:
        p = p_value_from_sar(-50.0, alternative="less")
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.0)
        self.assertLess(p, 1e-100)


if __name__ == "__main__":
    unittest.main()
