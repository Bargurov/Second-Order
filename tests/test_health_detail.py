"""
tests/test_health_detail.py

Unit tests for the _derive_health_overall() helper used by GET /health/detail.
Pure function — no app, no I/O.
"""

import sys
import unittest

sys.path.insert(0, ".")
from api import _derive_health_overall


class TestDeriveHealthOverall(unittest.TestCase):

    def test_ok_when_status_ok_freshness_fresh(self):
        self.assertEqual("ok", _derive_health_overall({"status": "ok", "freshness": "fresh"}))

    def test_ok_when_empty_meta(self):
        self.assertEqual("ok", _derive_health_overall({}))

    def test_error_when_status_error(self):
        self.assertEqual("error", _derive_health_overall({"status": "error", "freshness": "stale"}))

    def test_error_takes_precedence_over_stale(self):
        self.assertEqual("error", _derive_health_overall({"status": "error", "freshness": "fresh"}))

    def test_degraded_when_status_degraded(self):
        self.assertEqual("degraded", _derive_health_overall({"status": "degraded", "freshness": "fresh"}))

    def test_degraded_when_freshness_stale(self):
        self.assertEqual("degraded", _derive_health_overall({"status": "ok", "freshness": "stale"}))

    def test_degraded_when_freshness_degraded(self):
        self.assertEqual("degraded", _derive_health_overall({"status": "ok", "freshness": "degraded"}))

    def test_ok_when_freshness_missing(self):
        self.assertEqual("ok", _derive_health_overall({"status": "ok"}))

    def test_degraded_when_status_missing_but_freshness_stale(self):
        self.assertEqual("degraded", _derive_health_overall({"freshness": "stale"}))


if __name__ == "__main__":
    unittest.main()
