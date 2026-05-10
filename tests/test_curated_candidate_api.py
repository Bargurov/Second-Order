"""Tests for the ``/curated/candidates/*`` API surface.

Pin the contract:

* ``GET  /curated/candidates/preview`` — read-only.  Returns the
  candidate rows that COULD be staged from existing local reports
  (repaired-cohort summary, expansion candidate, short-horizon
  packet).  No DB writes.
* ``POST /curated/candidates/stage`` — requires ``confirm=true``.
  Writes only to ``curated_candidates`` (never to ``events``).
  Idempotent by ``(source_event_id, source)`` — re-staging a row
  is a no-op.  Records missing required fields in
  ``validation_errors`` and chooses ``status`` from the closed
  vocabulary {``draft``, ``needs_review``}.
* ``GET  /curated/candidates/status`` — counts by ``status``,
  ``mechanism_family``, ``primary_ticker``, missing-field totals.

Conservative wording — nothing is called "validated" here.

Test DB isolation: ``tests/conftest.py`` + ``tests/_db_isolation.py``
redirects ``db.DB_FILE`` to a temp path before any test module loads.
A single ``TestClient`` triggers ``init_db()`` via the FastAPI lifespan,
which is what creates the ``curated_candidates`` table.  Tests reuse
that path; they NEVER hardcode a sqlite connection to the live
``events.db``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests import _db_isolation  # noqa: E402,F401  — fixes db.DB_FILE
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import db  # noqa: E402
from routes import curated as curated_routes  # noqa: E402


_client = TestClient(api.app)

# Force-create the curated_candidates table up front.  Lifespan only
# fires on the first request, but several tests poke the DB directly
# (counting events, asserting curated table is empty) BEFORE their
# first request — without this call those direct queries hit a
# missing-table error.  init_db is idempotent.
db.init_db()


# ---------------------------------------------------------------------------
# Synthetic upstream-report payloads.  The preview endpoint reads from
# three patchable seams in routes.curated; we feed each seam a small
# fixture so the test never invokes the real archive scripts.
# ---------------------------------------------------------------------------


def _summary_payload(events: list[dict]) -> dict:
    """Mirror the 8-key envelope from
    ``manual_repaired_cohort_validation_summary``.  Tests of the
    preview endpoint only inspect ``repaired_clean_event_ids`` and
    ``top_abs_sar``."""
    return {
        "repaired_clean_event_ids": [e["event_id"] for e in events],
        "events_evaluated":         len(events),
        "records_count":            len(events),
        "significant_count":        0,
        "top_abs_sar":              list(events),
        "by_event_verdict":         {str(e["event_id"]): "insufficient"
                                     for e in events},
        "limitations":              [],
        "recommended_next_action":  "n/a",
    }


def _expansion_payload(rows: list[dict]) -> dict:
    """Shape from ``repaired_cohort_expansion_candidate_report``."""
    return {
        "candidate_count": len(rows),
        "groups":          {},
        "top_candidates":  list(rows),
        "estimated_repair_yield": {
            "conservative_estimate": 0,
            "optimistic_estimate":   len(rows),
            "estimate_basis":        "test fixture",
        },
        "recommended_next_action": "manual review",
    }


def _short_horizon_payload(candidates: list[dict]) -> dict:
    """Shape from ``short_horizon_repair_packet``."""
    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   [],
        "reviewed_exclusion_set_count":  0,
        "excluded_reviewed_count":       0,
        "total_short_ready":             len(candidates),
        "delta_vs_full_ready":           0,
        "total_candidates_after_filter": len(candidates),
        "candidates":                    list(candidates),
        "recommended_next_action":       "manual review",
    }


def _patch_seams(
    *, summary: dict | None = None,
    expansion: dict | None = None,
    short_horizon: dict | None = None,
):
    return (
        patch.object(curated_routes, "_run_repaired_cohort_summary",
                     return_value=summary or _summary_payload([])),
        patch.object(curated_routes, "_run_expansion_report",
                     return_value=expansion or _expansion_payload([])),
        patch.object(curated_routes, "_run_short_horizon_packet",
                     return_value=short_horizon or _short_horizon_payload([])),
    )


def _clear_curated_table() -> None:
    """Drop every row of curated_candidates between tests so each
    test sees a clean slate.  The table itself is created by the
    lifespan-triggered init_db() and persists across tests."""
    conn = sqlite3.connect(db.DB_FILE)
    try:
        try:
            conn.execute("DELETE FROM curated_candidates")
            conn.commit()
        except sqlite3.OperationalError:
            # Table may not exist yet on the very first call before
            # any test triggers the lifespan; benign.
            pass
    finally:
        conn.close()


def _select_curated() -> list[dict]:
    conn = sqlite3.connect(db.DB_FILE)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM curated_candidates ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _live_event_count() -> int:
    """Confirm we never write to the events table.  Tolerates the
    case where init_db has not yet fired (no table) — that's
    indistinguishable from an empty events table for the assertion's
    purpose."""
    conn = sqlite3.connect(db.DB_FILE)
    try:
        try:
            return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DB schema
# ---------------------------------------------------------------------------


_REQUIRED_COLUMNS = (
    "id", "source_event_id", "event_date", "headline", "source_url",
    "primary_ticker", "benchmark_ticker", "mechanism_family",
    "mechanism_description", "predicted_direction",
    "prediction_rationale", "curator_notes",
    "status", "source", "created_at", "validation_errors",
)


class TestSchema(unittest.TestCase):
    def test_curated_candidates_table_has_required_columns(self) -> None:
        # Lifespan-triggered init_db must have created the table.
        with TestClient(api.app):
            pass
        conn = sqlite3.connect(db.DB_FILE)
        try:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(curated_candidates)"
            ).fetchall()]
        finally:
            conn.close()
        for c in _REQUIRED_COLUMNS:
            self.assertIn(c, cols, f"missing column: {c}")

    def test_unique_constraint_on_source_event_id_and_source(self) -> None:
        # Composite unique key — same archive event may surface from
        # multiple sources (repaired_cohort + short_horizon_candidate)
        # and each source gets its own row.  Re-inserting the same
        # (source_event_id, source) pair must be rejected.
        with TestClient(api.app):
            pass
        conn = sqlite3.connect(db.DB_FILE)
        try:
            conn.execute(
                "INSERT INTO curated_candidates (source_event_id, source, "
                "status, created_at) VALUES (?, ?, ?, ?)",
                (9999, "repaired_cohort", "draft", "2026-05-10T00:00:00"),
            )
            conn.commit()
            # Same (source_event_id, source) — must fail.
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO curated_candidates (source_event_id, "
                    "source, status, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (9999, "repaired_cohort", "draft",
                     "2026-05-10T00:00:00"),
                )
                conn.commit()
            # Different source — allowed.
            conn.execute(
                "INSERT INTO curated_candidates (source_event_id, source, "
                "status, created_at) VALUES (?, ?, ?, ?)",
                (9999, "short_horizon_candidate", "draft",
                 "2026-05-10T00:00:00"),
            )
            conn.commit()
        finally:
            try:
                conn.execute(
                    "DELETE FROM curated_candidates WHERE source_event_id "
                    "= 9999"
                )
                conn.commit()
            except sqlite3.Error:
                pass
            conn.close()


# ---------------------------------------------------------------------------
# /curated/candidates/preview
# ---------------------------------------------------------------------------


class TestPreviewReadOnly(unittest.TestCase):
    def setUp(self) -> None:
        _clear_curated_table()

    def test_preview_returns_candidates_from_all_three_sources(self) -> None:
        summary = _summary_payload([
            {"event_id": 30, "ticker": "XOM", "benchmark": "SPY",
             "mechanism_family": "supply_shock",
             "headline": "h30", "event_date": "2026-04-05"},
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
        ])
        expansion = _expansion_payload([
            {"event_id": 200, "headline": "h200",
             "group": "ticker_repair_needed", "reason": "need ticker"},
        ])
        short_h = _short_horizon_payload([
            {"event_id": 300, "headline": "h300",
             "event_date": "2026-04-10",
             "current_primary_ticker": "AAPL",
             "flags": [], "repair_type": "needs_review",
             "repair_priority": "medium"},
        ])
        before = _live_event_count()
        with _patch_seams(summary=summary, expansion=expansion,
                          short_horizon=short_h)[0], \
             _patch_seams(summary=summary, expansion=expansion,
                          short_horizon=short_h)[1], \
             _patch_seams(summary=summary, expansion=expansion,
                          short_horizon=short_h)[2]:
            r = _client.get("/curated/candidates/preview")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("candidates", body)
        self.assertIn("preview_count", body)
        self.assertEqual(body["preview_count"], len(body["candidates"]))
        sources = {c["source"] for c in body["candidates"]}
        self.assertEqual(
            sources,
            {"repaired_cohort", "archive_candidate",
             "short_horizon_candidate"},
        )
        # No DB writes — events count unchanged, curated_candidates empty.
        self.assertEqual(_live_event_count(), before)
        self.assertEqual(_select_curated(), [])

    def test_preview_records_missing_fields_in_validation_errors(self) -> None:
        # Event surfaced with no ticker / family — validation_errors
        # must list those gaps so the operator sees them BEFORE
        # staging.  Auto-fill is forbidden when fields are absent.
        summary = _summary_payload([
            {"event_id": 12345, "headline": "missing fields",
             "event_date": "2026-04-06"},
        ])
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            body = _client.get("/curated/candidates/preview").json()
        cand = next(c for c in body["candidates"]
                    if c["source_event_id"] == 12345)
        self.assertIn("validation_errors", cand)
        self.assertTrue(any("primary_ticker" in e
                            for e in cand["validation_errors"]))
        self.assertTrue(any("mechanism_family" in e
                            for e in cand["validation_errors"]))


# ---------------------------------------------------------------------------
# /curated/candidates/stage
# ---------------------------------------------------------------------------


class TestStageRequiresConfirm(unittest.TestCase):
    def setUp(self) -> None:
        _clear_curated_table()

    def test_stage_without_confirm_returns_400(self) -> None:
        summary = _summary_payload([
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
        ])
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            r = _client.post("/curated/candidates/stage")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(_select_curated(), [])

    def test_stage_with_confirm_writes_only_to_curated(self) -> None:
        summary = _summary_payload([
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
        ])
        before_events = _live_event_count()
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            r = _client.post(
                "/curated/candidates/stage", params={"confirm": "true"},
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertGreaterEqual(body["staged_count"], 1)
        rows = _select_curated()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_event_id"], 46)
        self.assertEqual(rows[0]["source"], "repaired_cohort")
        self.assertIn(rows[0]["status"], ("draft", "needs_review"))
        # NEVER mutate the events table.
        self.assertEqual(_live_event_count(), before_events)


class TestStageIdempotent(unittest.TestCase):
    def setUp(self) -> None:
        _clear_curated_table()

    def test_re_staging_same_event_is_a_no_op(self) -> None:
        summary = _summary_payload([
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
        ])
        for _ in range(3):
            with _patch_seams(summary=summary)[0], \
                 _patch_seams(summary=summary)[1], \
                 _patch_seams(summary=summary)[2]:
                r = _client.post(
                    "/curated/candidates/stage",
                    params={"confirm": "true"},
                )
            self.assertEqual(r.status_code, 200, r.text)
        rows = _select_curated()
        self.assertEqual(len(rows), 1,
                         f"expected idempotency, got {len(rows)} rows")


class TestStageStatusVocabulary(unittest.TestCase):
    """Stage chooses status from the closed vocabulary
    {``draft``, ``needs_review``}.  The other two values
    (``ready_for_validation``, ``excluded``) are operator-set out of
    band; the API itself never sets them on stage."""

    _ALLOWED_AT_STAGE = {"draft", "needs_review"}

    def setUp(self) -> None:
        _clear_curated_table()

    def test_complete_event_stages_as_needs_review(self) -> None:
        summary = _summary_payload([
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
        ])
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            _client.post("/curated/candidates/stage",
                         params={"confirm": "true"})
        rows = _select_curated()
        self.assertEqual(rows[0]["status"], "needs_review")

    def test_incomplete_event_stages_as_draft(self) -> None:
        summary = _summary_payload([
            {"event_id": 999, "headline": "missing fields",
             "event_date": "2026-04-06"},
        ])
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            _client.post("/curated/candidates/stage",
                         params={"confirm": "true"})
        rows = _select_curated()
        self.assertEqual(rows[0]["status"], "draft")
        self.assertNotEqual((rows[0]["validation_errors"] or "").strip(),
                            "")

    def test_status_values_are_in_allowed_set(self) -> None:
        summary = _summary_payload([
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
            {"event_id": 999, "headline": "missing fields",
             "event_date": "2026-04-06"},
        ])
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            _client.post("/curated/candidates/stage",
                         params={"confirm": "true"})
        rows = _select_curated()
        for r in rows:
            self.assertIn(r["status"], self._ALLOWED_AT_STAGE)


# ---------------------------------------------------------------------------
# /curated/candidates/status
# ---------------------------------------------------------------------------


class TestStatusEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        _clear_curated_table()

    def test_status_counts_by_status_family_ticker_and_missing(self) -> None:
        # Stage two events: one complete, one missing fields.
        summary = _summary_payload([
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
            {"event_id": 60, "ticker": "XOM", "benchmark": "SPY",
             "mechanism_family": "supply_shock",
             "headline": "h60", "event_date": "2026-04-08"},
            {"event_id": 999, "headline": "h999 missing",
             "event_date": "2026-04-09"},
        ])
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            _client.post("/curated/candidates/stage",
                         params={"confirm": "true"})
        r = _client.get("/curated/candidates/status")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("counts_by_status",           body)
        self.assertIn("counts_by_mechanism_family", body)
        self.assertIn("counts_by_ticker",           body)
        self.assertIn("missing_field_counts",       body)
        self.assertIn("total",                      body)
        self.assertEqual(body["total"], 3)
        # Status mix: 2 needs_review + 1 draft.
        self.assertEqual(body["counts_by_status"].get("needs_review"), 2)
        self.assertEqual(body["counts_by_status"].get("draft"),        1)
        # Mechanism family + ticker totals only count complete rows.
        self.assertEqual(
            body["counts_by_mechanism_family"].get("supply_shock"), 1,
        )
        self.assertEqual(body["counts_by_ticker"].get("XOM"), 1)
        # Missing-field totals reflect the draft row.
        self.assertGreaterEqual(
            body["missing_field_counts"].get("primary_ticker", 0), 1,
        )


# ---------------------------------------------------------------------------
# Live archive does not appear from preview/stage when seams are stubbed
# ---------------------------------------------------------------------------


class TestNoLiveArchiveLeak(unittest.TestCase):
    """Sanity check: when the seams return empty payloads, the preview
    candidate list is empty.  This guards against a future regression
    where the route bypasses its seams and reads from the archive
    directly."""

    def setUp(self) -> None:
        _clear_curated_table()

    def test_empty_seams_yield_empty_preview(self) -> None:
        with _patch_seams()[0], _patch_seams()[1], _patch_seams()[2]:
            body = _client.get("/curated/candidates/preview").json()
        self.assertEqual(body["candidates"], [])
        self.assertEqual(body["preview_count"], 0)


# ---------------------------------------------------------------------------
# Conservative wording — nothing is called "validated" here
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def setUp(self) -> None:
        _clear_curated_table()

    def test_preview_response_avoids_validated_terms(self) -> None:
        # Forbidden tokens must NOT appear in the preview body keys
        # OR in the candidate status values.  ``ready_for_validation``
        # is the only legitimate use of the substring "validation"
        # and that's a status the API never *sets*.
        summary = _summary_payload([
            {"event_id": 46, "ticker": "MS", "benchmark": "SPY",
             "mechanism_family": "bank_regulatory_capital_relief",
             "headline": "h46", "event_date": "2026-04-06"},
        ])
        with _patch_seams(summary=summary)[0], \
             _patch_seams(summary=summary)[1], \
             _patch_seams(summary=summary)[2]:
            body = _client.get("/curated/candidates/preview").json()
        text = json.dumps(body).lower()
        for term in ("proof", "proves", "validated", "alpha",
                     "guaranteed"):
            self.assertNotIn(
                term, text,
                f"forbidden term {term!r} in preview body: {text[:300]!r}",
            )


if __name__ == "__main__":
    unittest.main()
