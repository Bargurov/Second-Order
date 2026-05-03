"""
tests/test_spark_normalize.py

Focused tests for consistent-length sparkline normalization.

  1) Short history gets left-padded to SPARK_LENGTH.
  2) Long history gets trimmed (oldest bars dropped) to SPARK_LENGTH.
  3) Normal (exact-length) history renders in the same order.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_check import normalize_spark, SPARK_LENGTH


class TestNormalizeSparkShort(unittest.TestCase):
    """Short spark arrays are left-padded to SPARK_LENGTH."""

    def test_short_array_padded_to_length(self):
        short = [0.1, 0.5, 0.9]
        result = normalize_spark(short)
        self.assertEqual(len(result), SPARK_LENGTH)

    def test_short_array_left_padded_with_first_value(self):
        short = [0.2, 0.5, 0.8]
        result = normalize_spark(short)
        pad_count = SPARK_LENGTH - len(short)
        self.assertEqual(result[:pad_count], [0.2] * pad_count)
        self.assertEqual(result[pad_count:], short)

    def test_single_element_padded(self):
        result = normalize_spark([0.7])
        self.assertEqual(len(result), SPARK_LENGTH)
        self.assertEqual(result[-1], 0.7)
        self.assertTrue(all(v == 0.7 for v in result[:-1]))

    def test_empty_array_padded_with_zeros(self):
        result = normalize_spark([])
        self.assertEqual(len(result), SPARK_LENGTH)
        self.assertTrue(all(v == 0.0 for v in result))


class TestNormalizeSparkLong(unittest.TestCase):
    """Long spark arrays are trimmed from the left to SPARK_LENGTH."""

    def test_long_array_trimmed_to_length(self):
        long = list(range(30))
        result = normalize_spark(long)
        self.assertEqual(len(result), SPARK_LENGTH)

    def test_long_array_keeps_most_recent(self):
        long = list(range(30))
        result = normalize_spark(long)
        # Should be the last SPARK_LENGTH elements.
        self.assertEqual(result, long[-SPARK_LENGTH:])

    def test_one_over_trimmed(self):
        over = list(range(SPARK_LENGTH + 1))
        result = normalize_spark(over)
        self.assertEqual(len(result), SPARK_LENGTH)
        self.assertEqual(result, over[1:])


class TestNormalizeSparkExact(unittest.TestCase):
    """Exact-length spark arrays pass through in the same order."""

    def test_exact_length_unchanged(self):
        exact = [round(i * 0.05, 3) for i in range(SPARK_LENGTH)]
        result = normalize_spark(exact)
        self.assertEqual(result, exact)

    def test_exact_length_is_fresh_copy(self):
        exact = [0.5] * SPARK_LENGTH
        result = normalize_spark(exact)
        self.assertEqual(result, exact)
        # Must be a new list, not the same object.
        self.assertIsNot(result, exact)

    def test_order_preserved(self):
        exact = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9,
                 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
        result = normalize_spark(exact)
        self.assertEqual(result, exact)


class TestNormalizeSparkCustomLength(unittest.TestCase):
    """The length parameter overrides SPARK_LENGTH."""

    def test_custom_length_short(self):
        result = normalize_spark([0.5, 0.6], length=5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result, [0.5, 0.5, 0.5, 0.5, 0.6])

    def test_custom_length_long(self):
        result = normalize_spark([1, 2, 3, 4, 5], length=3)
        self.assertEqual(result, [3, 4, 5])


if __name__ == "__main__":
    unittest.main()
