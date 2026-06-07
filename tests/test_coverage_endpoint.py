"""Contract + safety tests for ``GET /stats/coverage`` (R7A).

The endpoint exposes event-study readiness coverage COUNTS only — how many
archived analysis-stage events are event-study-ready (per-event AR / SAR /
CAR computable through the gated single-event validator) versus not — as ONE
independent eligibility gate.  It must:

  * return the documented counts-only shape (no per-event lists);
  * keep ``event_study_ready_count + unavailable_count == total_events`` so
    the denominator is internally consistent;
  * NEVER return or merge any Phase 1 / Phase 2 FDR pool data;
  * NOT imply a single linear funnel (it carries an explicit separateness
    note);
  * be read-only — no provider / yfinance / LLM seam, no DB mutation.

Hermetic: a temp DB per test (mirrors ``tests/test_backend_contract_smoke``).
No live network, no LLM, no yfinance.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402


# Tracked-evidence (Phase 1 / Phase 2 FDR) envelope keys — none of these may
# appear in the coverage response.  The two surfaces stay structurally
# separate: coverage is a per-event eligibility gate; the FDR pools are a
# closed cohort statistic with their own denominators.
_FDR_POOL_KEYS: frozenset[str] = frozenset({
    "phase1",
    "phase2",
    "phase1_count",
    "phase2_count",
    "phase2_pass_count",
    "phase2_fail_count",
    "fdr_scope_note",
    "q_value",
    "q_values",
    "passes_bh_at_005",
})


def _find_nan_paths(obj, path="root"):
    bad = []
    if isinstance(obj, float):
        if not math.isfinite(obj):
            bad.append(f"{path}={obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            bad.extend(_find_nan_paths(v, f"{path}.{k}"))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            bad.extend(_find_nan_paths(v, f"{path}[{i}]"))
    return bad


class CoverageEndpointBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp_db = os.path.join(
            os.path.dirname(__file__),
            f"test_coverage_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp_db
        db._db_ready = False
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp_db)
        except (OSError, PermissionError):
            pass

    # --- helpers ------------------------------------------------------------

    def _get(self, path):
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200, f"{path}: {r.text}")
        return r.json()

    def _seed_event(self):
        """Save one analysis-stage event with a primary ticker + event_date
        but no cached prices, so the gate resolves to ``unavailable``."""
        event_date = (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).date().isoformat()
        db.save_event({
            "headline":          "Coverage probe event",
            "stage":             "realized",
            "persistence":       "structural",
            "what_changed":      "synthetic",
            "mechanism_summary": "A -> B",
            "beneficiaries":     ["Alpha Corp"],
            "losers":            ["Beta Corp"],
            "assets_to_watch":   ["AAPL"],
            "confidence":        "medium",
            "market_note":       "synthetic",
            "market_tickers": [
                {
                    "symbol":     "AAPL",
                    "role":       "beneficiary",
                    "return_1d":  0.5,
                    "return_5d":  1.2,
                    "return_20d": 3.0,
                    "direction":  "supports thesis",
                },
            ],
            "event_date":        event_date,
            "model":             "claude-test",
            "low_signal":        0,
        })

    def _event_count(self):
        conn = sqlite3.connect(f"file:{self._tmp_db}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            conn.close()


class TestCoverageShape(CoverageEndpointBase):
    def test_returns_counts_only_shape(self):
        body = self._get("/stats/coverage")
        for key in (
            "ok",
            "section",
            "schema_version",
            "total_events",
            "event_study_ready_count",
            "unavailable_count",
            "curated_intake_excluded_count",
            "blocking_reasons",
            "not_a_funnel_note",
            "non_claims",
        ):
            self.assertIn(key, body, f"missing coverage key: {key}")
        self.assertEqual(body["section"], "event_study_coverage")
        self.assertIsInstance(body["total_events"], int)
        self.assertIsInstance(body["event_study_ready_count"], int)
        self.assertIsInstance(body["unavailable_count"], int)
        self.assertIsInstance(body["curated_intake_excluded_count"], int)
        self.assertIsInstance(body["blocking_reasons"], dict)
        self.assertIsInstance(body["not_a_funnel_note"], str)
        self.assertTrue(body["not_a_funnel_note"].strip())

    def test_counts_only_no_per_event_lists(self):
        """The viewer endpoint surfaces counts, never the per-event arrays
        the CLI report carries — so no headline / per-event payload leaks."""
        body = self._get("/stats/coverage")
        self.assertNotIn("available", body)
        self.assertNotIn("insufficient", body)

    def test_ready_plus_unavailable_equals_total(self):
        body = self._get("/stats/coverage")
        self.assertGreaterEqual(body["total_events"], 0)
        self.assertEqual(
            body["event_study_ready_count"] + body["unavailable_count"],
            body["total_events"],
            "ready + unavailable must equal the considered denominator",
        )

    def test_empty_archive_is_all_zero(self):
        body = self._get("/stats/coverage")
        self.assertEqual(body["total_events"], 0)
        self.assertEqual(body["event_study_ready_count"], 0)
        self.assertEqual(body["unavailable_count"], 0)

    def test_counts_reflect_seeded_archive(self):
        self._seed_event()
        body = self._get("/stats/coverage")
        self.assertEqual(body["total_events"], 1)
        # One analysis-stage event with a ticker + date but no cached prices
        # gates to unavailable (not ready).
        self.assertEqual(body["unavailable_count"], 1)
        self.assertEqual(body["event_study_ready_count"], 0)
        self.assertTrue(
            body["blocking_reasons"],
            "an unavailable event must surface at least one blocking reason",
        )

    def test_response_is_json_clean(self):
        self._seed_event()
        body = self._get("/stats/coverage")
        json.dumps(body)  # must not raise
        self.assertEqual(_find_nan_paths(body), [])


class TestCoverageStaysSeparateFromFdr(CoverageEndpointBase):
    def test_no_phase1_phase2_fdr_pool_fields(self):
        self._seed_event()
        body = self._get("/stats/coverage")
        leaked = sorted(k for k in body if k in _FDR_POOL_KEYS)
        self.assertEqual(
            leaked, [],
            f"FDR pool fields leaked into the coverage endpoint: {leaked}",
        )


class TestCoverageReadOnly(CoverageEndpointBase):
    def test_no_provider_or_paid_seam_invoked(self):
        """Hitting the endpoint must reach no provider / paid seam.  Each
        seam is patched to raise, so any call collapses the request — a 200
        is the proof the read-only gate path was taken."""
        self._seed_event()
        targets = (
            "yfinance.download",
            "yfinance.Ticker",
            "api.analyze_event",
            "api.market_check",
        )
        patchers = [
            mock.patch(t, side_effect=AssertionError(f"{t} called by coverage"))
            for t in targets
        ]
        for p in patchers:
            p.start()
        try:
            r = self.client.get("/stats/coverage")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(r.status_code, 200, r.text)

    def test_endpoint_does_not_mutate_db(self):
        self._seed_event()
        before = self._event_count()
        r = self.client.get("/stats/coverage")
        self.assertEqual(r.status_code, 200, r.text)
        after = self._event_count()
        self.assertEqual(before, after, "coverage endpoint mutated the archive")


if __name__ == "__main__":
    unittest.main()
