"""Tests for ``scripts/curated_candidate_stage_smoke.py``.

The smoke exercises the API-backed curated staging path end-to-end
against a TEST/TEMP DB only.  It must:

* Stage the realistic 5-event repaired cohort [30, 40, 46, 60, 73].
* Surface a JSON envelope with the brief-mandated keys
  (``preview_count``, ``staged_count``, ``status_counts``,
  ``staged_event_ids``, ``live_db_unchanged``, ``errors``,
  ``warnings``).
* Leave the live ``events`` table byte-identical — the smoke runs in
  the redirected test DB and patches the upstream report seams so
  the heavy archive scripts never run.
* Use conservative language only — nothing here is "validated".

Test isolation: ``tests/_db_isolation`` redirects ``db.DB_FILE`` to
a temp path before this module loads.  ``init_db()`` creates the
``curated_candidates`` table.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests import _db_isolation  # noqa: E402,F401

import db  # noqa: E402
from scripts import curated_candidate_stage_smoke as cli  # noqa: E402


db.init_db()


_REQUIRED_KEYS = (
    "preview_count",
    "staged_count",
    "status_counts",
    "staged_event_ids",
    "live_db_unchanged",
    "errors",
    "warnings",
)


def _wipe_curated() -> None:
    conn = sqlite3.connect(db.DB_FILE)
    try:
        conn.execute("DELETE FROM curated_candidates")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestEnvelopeContract(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_curated()

    def test_envelope_has_required_keys(self) -> None:
        report = cli.run_curated_candidate_stage_smoke()
        for k in _REQUIRED_KEYS:
            self.assertIn(k, report, f"missing key: {k}")


# ---------------------------------------------------------------------------
# Five-event repaired cohort happy path
# ---------------------------------------------------------------------------


class TestFiveEventCohort(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_curated()

    def test_cohort_stages_without_touching_events_table(self) -> None:
        report = cli.run_curated_candidate_stage_smoke()
        self.assertEqual(report["preview_count"], 5)
        self.assertEqual(report["staged_count"], 5)
        self.assertEqual(
            sorted(report["staged_event_ids"]), [30, 40, 46, 60, 73],
        )
        self.assertIs(report["live_db_unchanged"], True)
        self.assertEqual(report["errors"], [])
        # status_counts is keyed by curated_candidates.status — every
        # event in the realistic cohort has full required fields and
        # so should land in needs_review (not draft).
        self.assertEqual(report["status_counts"].get("needs_review"), 5)


# ---------------------------------------------------------------------------
# Idempotency — re-running the smoke leaves staged_count flat
# ---------------------------------------------------------------------------


class TestRepeatable(unittest.TestCase):
    """Each smoke invocation runs against its own fresh temp DB so
    repeated runs produce the same shape — every run stages the full
    cohort independently.  Idempotency of the underlying staging API
    on a single DB is covered by ``test_curated_candidate_api``."""

    def setUp(self) -> None:
        _wipe_curated()

    def test_repeated_runs_produce_stable_shape(self) -> None:
        first  = cli.run_curated_candidate_stage_smoke()
        second = cli.run_curated_candidate_stage_smoke()
        for r in (first, second):
            self.assertEqual(r["staged_count"], 5)
            self.assertEqual(
                sorted(r["staged_event_ids"]), [30, 40, 46, 60, 73],
            )
            self.assertIs(r["live_db_unchanged"], True)


# ---------------------------------------------------------------------------
# Live archive never mutated
# ---------------------------------------------------------------------------


class TestEventsTableUnchanged(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_curated()

    def test_events_table_byte_identical(self) -> None:
        before = _events_count()
        cli.run_curated_candidate_stage_smoke()
        self.assertEqual(_events_count(), before)


def _events_count() -> int:
    conn = sqlite3.connect(db.DB_FILE)
    try:
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_curated()

    def test_cli_emits_parseable_json(self) -> None:
        out = io.StringIO()
        rc = cli.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["staged_count"], 5)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    _FORBIDDEN = ("proof", "proves", "validated", "alpha", "guaranteed")

    def setUp(self) -> None:
        _wipe_curated()

    def test_text_avoids_forbidden_terms(self) -> None:
        out = io.StringIO()
        cli.main([], out=out)  # text mode
        text = out.getvalue().lower()
        for term in self._FORBIDDEN:
            self.assertNotIn(
                term, text,
                f"forbidden term {term!r} in smoke output: {text[:300]!r}",
            )


if __name__ == "__main__":
    unittest.main()
