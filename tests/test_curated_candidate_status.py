"""Tests for ``scripts/curated_candidate_status.py``.

Pin the contract:

* Pure read of ``curated_candidates`` — never writes anywhere.
* Returns counts by status, mechanism family, primary ticker, and
  missing-field totals.  Same vocabulary as the
  ``GET /curated/candidates/status`` endpoint, mirrored intentionally
  so operators see the same picture from CLI and HTTP.
* Read-only against ``db.DB_FILE`` — no provider / yfinance / LLM
  calls; no FastAPI app surface; no paid actions.
* CLI emits parseable JSON under ``--json``.

Test isolation: ``tests/_db_isolation`` redirects ``db.DB_FILE`` to a
temp path before this module loads, so the script reads from the
isolated test DB.
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
from scripts import curated_candidate_status as cli  # noqa: E402


db.init_db()  # ensure curated_candidates exists


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _wipe() -> None:
    conn = sqlite3.connect(db.DB_FILE)
    try:
        conn.execute("DELETE FROM curated_candidates")
        conn.commit()
    finally:
        conn.close()


def _seed_row(
    *, source_event_id: int, source: str = "repaired_cohort",
    status: str = "needs_review",
    primary_ticker: str | None = "MS",
    mechanism_family: str | None = "bank_regulatory_capital_relief",
    validation_errors: list[str] | None = None,
) -> None:
    conn = sqlite3.connect(db.DB_FILE)
    try:
        conn.execute(
            """
            INSERT INTO curated_candidates (
                source_event_id, event_date, headline, source_url,
                primary_ticker, benchmark_ticker, mechanism_family,
                mechanism_description, predicted_direction,
                prediction_rationale, curator_notes,
                status, source, created_at, validation_errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_event_id, "2026-04-06", f"h{source_event_id}", None,
                primary_ticker, "SPY", mechanism_family,
                None, None, None, None,
                status, source, "2026-05-10T00:00:00",
                json.dumps(validation_errors or []),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


_REQUIRED_KEYS = (
    "total",
    "counts_by_status",
    "counts_by_mechanism_family",
    "counts_by_ticker",
    "missing_field_counts",
    "ok",
)


class TestStatusEnvelope(unittest.TestCase):
    def setUp(self) -> None:
        _wipe()

    def test_envelope_has_required_keys(self) -> None:
        report = cli.compute_status()
        for k in _REQUIRED_KEYS:
            self.assertIn(k, report, f"missing key: {k}")
        self.assertIs(report["ok"], True)

    def test_empty_table_yields_zero_counts(self) -> None:
        report = cli.compute_status()
        self.assertEqual(report["total"], 0)
        self.assertEqual(report["counts_by_status"], {})
        self.assertEqual(report["counts_by_mechanism_family"], {})
        self.assertEqual(report["counts_by_ticker"], {})
        # missing_field_counts is initialised to zero per required field.
        for v in report["missing_field_counts"].values():
            self.assertEqual(v, 0)


class TestStatusCounts(unittest.TestCase):
    def setUp(self) -> None:
        _wipe()

    def test_counts_by_status_family_ticker(self) -> None:
        # 2 needs_review + 1 draft.  Two sources cover the same event id
        # (legitimate via composite unique key).
        _seed_row(source_event_id=46, status="needs_review",
                  primary_ticker="MS",
                  mechanism_family="bank_regulatory_capital_relief")
        _seed_row(source_event_id=60, status="needs_review",
                  primary_ticker="XOM", mechanism_family="supply_shock")
        _seed_row(source_event_id=999, status="draft",
                  primary_ticker=None, mechanism_family=None,
                  validation_errors=["missing_primary_ticker",
                                     "missing_mechanism_family"])
        report = cli.compute_status()
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["counts_by_status"].get("needs_review"), 2)
        self.assertEqual(report["counts_by_status"].get("draft"),        1)
        self.assertEqual(
            report["counts_by_mechanism_family"].get("supply_shock"), 1,
        )
        self.assertEqual(report["counts_by_ticker"].get("MS"), 1)
        self.assertEqual(report["counts_by_ticker"].get("XOM"), 1)
        self.assertGreaterEqual(
            report["missing_field_counts"].get("primary_ticker", 0), 1,
        )
        self.assertGreaterEqual(
            report["missing_field_counts"].get("mechanism_family", 0), 1,
        )


class TestReadOnly(unittest.TestCase):
    def setUp(self) -> None:
        _wipe()

    def test_compute_status_does_not_mutate_db(self) -> None:
        _seed_row(source_event_id=46)
        before = _row_count()
        cli.compute_status()
        cli.compute_status()
        cli.compute_status()
        self.assertEqual(_row_count(), before)


def _row_count() -> int:
    conn = sqlite3.connect(db.DB_FILE)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM curated_candidates"
        ).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        _wipe()

    def test_cli_emits_parseable_json(self) -> None:
        _seed_row(source_event_id=46)
        out = io.StringIO()
        rc = cli.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["total"], 1)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    """The status report must avoid causal / proof language."""

    _FORBIDDEN = ("proof", "proves", "alpha", "guaranteed")

    def setUp(self) -> None:
        _wipe()

    def test_status_text_avoids_forbidden_terms(self) -> None:
        _seed_row(source_event_id=46)
        out = io.StringIO()
        cli.main([], out=out)  # text mode
        text = out.getvalue().lower()
        for term in self._FORBIDDEN:
            self.assertNotIn(
                term, text,
                f"forbidden term {term!r} in status text: {text[:300]!r}",
            )


if __name__ == "__main__":
    unittest.main()
