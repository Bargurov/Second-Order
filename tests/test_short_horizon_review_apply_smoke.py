"""Tests for ``scripts/short_horizon_review_apply_smoke.py``.

Pin the contract:

* Read-only against the live archive — every run hashes the live DB
  before and after and surfaces ``live_db_unchanged``.
* The smoke copies the live DB to a fresh temp file via the
  ``_copy_live_db_to_temp`` patchable seam and stages accepted
  worksheet rows into the temp DB's ``curated_candidates`` table
  via the ``_stage_curated_candidates`` patchable seam.
* Never invokes a validation runner; never imports FastAPI, a
  provider, ``yfinance``, or an LLM.
* Output dict carries EXACTLY these 11 keys::

    ok, worksheet_path, temp_db_path, accepted_count, staged_count,
    staged_event_ids, excluded_count, pending_count,
    live_db_unchanged, errors, warnings

* Canonical worksheet gate column: ``include_in_short_horizon_
  validation``.  Vocabulary (case- and whitespace-insensitive):
  ``yes`` → accepted bucket, ``no`` → excluded bucket, blank →
  pending bucket.  Unknown values fall back to pending with a
  warning.
* Yes rows missing a required ``proposed_*`` field (or carrying
  an invalid ``predicted_direction`` / ``event_date``) are counted
  as accepted but NOT staged — ``accepted_count`` may exceed
  ``staged_count``.
* No rows must carry a non-blank ``exclude_reason`` or they land in
  ``errors`` (NOT in ``excluded_count``).
* Conservative wording — banned tokens (``proof``, ``proven``,
  ``automatically``, ``alpha generated``, ``correct ticker``,
  ``validated``) absent from any text the smoke emits.
"""
from __future__ import annotations

import csv as csv_module
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_apply_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "worksheet_path",
    "temp_db_path",
    "accepted_count",
    "staged_count",
    "staged_event_ids",
    "excluded_count",
    "pending_count",
    "live_db_unchanged",
    "errors",
    "warnings",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "automatically",
    "alpha generated",
    "correct ticker",
    "validated",
)


# Canonical short-horizon review worksheet columns, in the order
# emitted by ``scripts.short_horizon_review_worksheet``.  The gate
# column is ``include_in_short_horizon_validation``; the operator
# fills the ``proposed_*`` columns for ``yes`` rows.
_WORKSHEET_COLUMNS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT,
    low_signal      INTEGER DEFAULT 0,
    mechanism_family TEXT DEFAULT 'none'
)
""".strip()


_CURATED_CANDIDATES_DDL = """
CREATE TABLE curated_candidates (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id       INTEGER NOT NULL,
    event_date            TEXT,
    headline              TEXT,
    source_url            TEXT,
    primary_ticker        TEXT,
    benchmark_ticker      TEXT,
    mechanism_family      TEXT,
    mechanism_description TEXT,
    predicted_direction   TEXT,
    prediction_rationale  TEXT,
    curator_notes         TEXT,
    status                TEXT NOT NULL DEFAULT 'draft',
    source                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    validation_errors     TEXT NOT NULL DEFAULT '[]',
    UNIQUE(source_event_id, source)
)
""".strip()


def _make_live_db(
    *, with_curated_table: bool = False,
    seed_event_ids: list[int] | None = None,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"sh_review_apply_live_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_DDL)
        if with_curated_table:
            conn.execute(_CURATED_CANDIDATES_DDL)
        for ev_id in (seed_event_ids or []):
            conn.execute(
                "INSERT INTO events (id, headline, event_date) "
                "VALUES (?, ?, ?)",
                (ev_id, f"headline {ev_id}", "2026-04-06"),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _row(**fields: Any) -> dict[str, Any]:
    return {c: fields.get(c, "") for c in _WORKSHEET_COLUMNS}


def _accepted_row(
    *, event_id: int,
    headline: str = "h",
    event_date: str = "2026-04-15",
    proposed_primary_ticker: str = "XOM",
    proposed_benchmark_ticker: str = "SPY",
    proposed_mechanism_family: str = "supply_shock",
    predicted_direction: str = "up",
    operator_notes: str = "",
) -> dict[str, Any]:
    return _row(
        event_id=event_id,
        include_in_short_horizon_validation="yes",
        headline=headline, event_date=event_date,
        proposed_primary_ticker=proposed_primary_ticker,
        proposed_benchmark_ticker=proposed_benchmark_ticker,
        proposed_mechanism_family=proposed_mechanism_family,
        predicted_direction=predicted_direction,
        operator_notes=operator_notes,
    )


def _excluded_row(
    *, event_id: int, exclude_reason: str = "off-topic",
) -> dict[str, Any]:
    return _row(
        event_id=event_id,
        include_in_short_horizon_validation="no",
        exclude_reason=exclude_reason,
    )


def _pending_row(*, event_id: int) -> dict[str, Any]:
    return _row(
        event_id=event_id,
        include_in_short_horizon_validation="",
    )


def _write_worksheet(rows: list[dict[str, Any]]) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"sh_review_ws_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv_module.writer(fh, lineterminator="\n")
        w.writerow(_WORKSHEET_COLUMNS)
        for r in rows:
            w.writerow([str(r.get(c, "")) for c in _WORKSHEET_COLUMNS])
    return path


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_has_exactly_eleven_keys_no_args(self) -> None:
        report = cli.smoke_short_horizon_review_apply()
        self.assertEqual(
            set(report.keys()), set(_REQUIRED_KEYS),
            f"unexpected keys: {sorted(report.keys())}",
        )

    def test_no_args_fails_closed_with_worksheet_error(self) -> None:
        report = cli.smoke_short_horizon_review_apply()
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "--worksheet" in e for e in report["errors"]
        ))
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["staged_count"], 0)
        self.assertEqual(report["staged_event_ids"], [])
        self.assertIsNone(report["temp_db_path"])


# ---------------------------------------------------------------------------
# Worksheet parsing
# ---------------------------------------------------------------------------


class TestWorksheetParsing(unittest.TestCase):
    def test_missing_worksheet_file_fails_closed(self) -> None:
        report = cli.smoke_short_horizon_review_apply(
            worksheet_path="/nonexistent/path/to/worksheet.csv",
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "does not exist" in e for e in report["errors"]
        ))

    def test_worksheet_missing_required_columns_fails_closed(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"sh_review_bad_{uuid.uuid4().hex}.csv",
        )
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv_module.writer(fh, lineterminator="\n")
            # Missing canonical gate column.
            w.writerow(["event_id", "headline"])
            w.writerow(["1", "h"])
        report = cli.smoke_short_horizon_review_apply(
            worksheet_path=path,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "include_in_short_horizon_validation" in e
            for e in report["errors"]
        ))


# ---------------------------------------------------------------------------
# Decision categorization
# ---------------------------------------------------------------------------


class TestDecisionCategorization(unittest.TestCase):
    def test_counts_yes_no_blank(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _accepted_row(event_id=80),
                _accepted_row(event_id=81,
                              proposed_primary_ticker="BA",
                              proposed_mechanism_family="supply_shock"),
                _excluded_row(event_id=82),
                _excluded_row(event_id=83),
                _pending_row(event_id=84),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertEqual(report["accepted_count"], 2)
            self.assertEqual(report["excluded_count"], 2)
            self.assertEqual(report["pending_count"], 1)
        finally:
            os.unlink(live)

    def test_blank_gate_falls_back_to_pending_without_warning(self) -> None:
        # Blank is the legitimate pending_review state — no warning.
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _row(event_id=90, include_in_short_horizon_validation=""),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertEqual(report["pending_count"], 1)
            for w in report["warnings"]:
                self.assertNotIn(
                    "unknown include_in_short_horizon_validation", w,
                    f"blank gate must not surface as unknown: {w!r}",
                )
        finally:
            os.unlink(live)

    def test_unknown_gate_value_falls_back_to_pending_with_warning(
        self,
    ) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _row(
                    event_id=91,
                    include_in_short_horizon_validation="maybe",
                ),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertEqual(report["pending_count"], 1)
            self.assertTrue(any(
                "include_in_short_horizon_validation" in w
                for w in report["warnings"]
            ))
        finally:
            os.unlink(live)

    def test_gate_value_is_case_and_whitespace_insensitive(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _accepted_row(event_id=92,
                              proposed_primary_ticker="XOM"),
                _excluded_row(event_id=93),
                # "  YES  " and " No " must dispatch identically to
                # plain "yes"/"no".
                _accepted_row(event_id=94,
                              proposed_primary_ticker="XOM"),
            ])
            # Rewrite gate cells to mixed-case / padded variants.
            with open(ws, "r", encoding="utf-8") as fh:
                text = fh.read()
            text = text.replace(
                ",yes,", ",  YES  ,", 1,
            ).replace(
                ",no,", ", No ,", 1,
            )
            with open(ws, "w", encoding="utf-8") as fh:
                fh.write(text)
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertEqual(report["accepted_count"], 2,
                             report.get("errors"))
            self.assertEqual(report["excluded_count"], 1)
        finally:
            os.unlink(live)

    def test_no_row_without_exclude_reason_is_error(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _excluded_row(event_id=95, exclude_reason=""),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["excluded_count"], 0)
            self.assertTrue(any(
                "exclude_reason" in e for e in report["errors"]
            ))
        finally:
            os.unlink(live)

    def test_non_integer_event_id_lands_in_errors(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([_row(
                event_id="bogus",
                include_in_short_horizon_validation="yes",
                headline="h", event_date="2026-04-15",
                proposed_primary_ticker="XOM",
                proposed_benchmark_ticker="SPY",
                proposed_mechanism_family="supply_shock",
                predicted_direction="up",
            )])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "event_id" in e for e in report["errors"]
            ))
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Accepted-row field validation
# ---------------------------------------------------------------------------


class TestAcceptedRowFieldValidation(unittest.TestCase):
    def test_yes_row_missing_proposed_mechanism_family_is_not_staged(
        self,
    ) -> None:
        live = _make_live_db()
        try:
            # Strip proposed_mechanism_family from this yes row.
            row = _accepted_row(event_id=100,
                                proposed_mechanism_family="")
            ws = _write_worksheet([row])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertFalse(report["ok"])
            # Accepted_count reflects operator intent — staged_count
            # reflects what actually landed.
            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["staged_count"], 0)
            self.assertEqual(report["staged_event_ids"], [])
            self.assertTrue(any(
                "proposed_mechanism_family" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(live)

    def test_yes_row_missing_proposed_benchmark_ticker_is_not_staged(
        self,
    ) -> None:
        live = _make_live_db()
        try:
            row = _accepted_row(event_id=101,
                                proposed_benchmark_ticker="")
            ws = _write_worksheet([row])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["staged_count"], 0)
            self.assertTrue(any(
                "proposed_benchmark_ticker" in e
                for e in report["errors"]
            ))
        finally:
            os.unlink(live)

    def test_yes_row_with_invalid_direction_is_not_staged(self) -> None:
        live = _make_live_db()
        try:
            row = _accepted_row(event_id=102,
                                predicted_direction="sideways")
            ws = _write_worksheet([row])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["staged_count"], 0)
            self.assertTrue(any(
                "predicted_direction" in e for e in report["errors"]
            ))
        finally:
            os.unlink(live)

    def test_flat_direction_is_rejected_alignment_with_validator(
        self,
    ) -> None:
        # The validator vocabulary is {up, down, neutral}; ``flat``
        # is the curated-event vocabulary and must be rejected here
        # too so the validator / apply pair agree.
        live = _make_live_db()
        try:
            row = _accepted_row(event_id=103, predicted_direction="flat")
            ws = _write_worksheet([row])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "predicted_direction" in e for e in report["errors"]
            ))
        finally:
            os.unlink(live)

    def test_neutral_direction_is_accepted(self) -> None:
        live = _make_live_db()
        try:
            row = _accepted_row(event_id=104,
                                predicted_direction="neutral")
            ws = _write_worksheet([row])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["staged_count"], 1)
        finally:
            os.unlink(live)

    def test_yes_row_with_invalid_event_date_is_not_staged(self) -> None:
        live = _make_live_db()
        try:
            row = _accepted_row(event_id=105, event_date="2026/04/15")
            ws = _write_worksheet([row])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["staged_count"], 0)
            self.assertTrue(any(
                "event_date" in e for e in report["errors"]
            ))
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Staging into temp DB
# ---------------------------------------------------------------------------


class TestStagingIntoTempDB(unittest.TestCase):
    def test_accepted_rows_land_in_curated_candidates_table(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _accepted_row(event_id=200),
                _accepted_row(event_id=201,
                              proposed_primary_ticker="BA",
                              proposed_mechanism_family="supply_shock"),
                _excluded_row(event_id=202),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["staged_count"], 2)
            self.assertEqual(report["staged_event_ids"], [200, 201])
            self.assertEqual(report["excluded_count"], 1)
            # Verify the temp DB actually contains the rows with the
            # worksheet's ``proposed_*`` values mapped to DB columns.
            temp = report["temp_db_path"]
            self.assertIsNotNone(temp)
            conn = sqlite3.connect(temp)
            try:
                rows = conn.execute(
                    "SELECT source_event_id, status, source, "
                    "primary_ticker, benchmark_ticker, mechanism_family "
                    "FROM curated_candidates "
                    "ORDER BY source_event_id"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual([r[0] for r in rows], [200, 201])
            for _id, status, source, *_rest in rows:
                self.assertEqual(status, "needs_review")
                self.assertEqual(source, "short_horizon_review_apply_smoke")
            # Row 201 used overrides — confirm the proposed_* values
            # arrived at the DB columns.
            self.assertEqual(rows[1][3], "BA")        # primary_ticker
            self.assertEqual(rows[1][4], "SPY")       # benchmark_ticker
            self.assertEqual(rows[1][5], "supply_shock")
        finally:
            os.unlink(live)

    def test_temp_db_creates_curated_candidates_table_if_missing(
        self,
    ) -> None:
        # Live DB does NOT have curated_candidates — the smoke must
        # create the table in the temp copy.
        live = _make_live_db(with_curated_table=False)
        try:
            ws = _write_worksheet([_accepted_row(event_id=300)])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["staged_count"], 1)
        finally:
            os.unlink(live)

    def test_unique_constraint_dedupes_repeat_event_ids_in_worksheet(
        self,
    ) -> None:
        live = _make_live_db()
        try:
            # Two rows with the same event_id — only one stages.
            ws = _write_worksheet([
                _accepted_row(event_id=400),
                _accepted_row(event_id=400, headline="duplicate"),
            ])
            # ``unique_constraint`` is enforced by the temp DB's
            # ``UNIQUE(source_event_id, source)``.
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertEqual(report["accepted_count"], 2)
            self.assertEqual(report["staged_count"], 1)
            self.assertEqual(report["staged_event_ids"], [400])
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Live DB byte-identity
# ---------------------------------------------------------------------------


class TestLiveDBByteIdentity(unittest.TestCase):
    def test_live_db_bytes_unchanged_after_full_run(self) -> None:
        live = _make_live_db(seed_event_ids=[80, 81])
        try:
            before = _sha256(live)
            ws = _write_worksheet([
                _accepted_row(event_id=500),
                _accepted_row(event_id=501),
                _excluded_row(event_id=502),
                _pending_row(event_id=503),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertTrue(report["ok"], report.get("errors"))
            after = _sha256(live)
            self.assertEqual(
                before, after,
                "live DB bytes mutated by smoke",
            )
            self.assertTrue(report["live_db_unchanged"])
        finally:
            os.unlink(live)

    def test_live_db_bytes_unchanged_when_worksheet_invalid(self) -> None:
        live = _make_live_db(seed_event_ids=[80])
        try:
            before = _sha256(live)
            # Worksheet path missing → no copy happens, live DB
            # bytes still unchanged.
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path="/nonexistent.csv", db_path=live,
            )
            self.assertFalse(report["ok"])
            after = _sha256(live)
            self.assertEqual(before, after)
            self.assertTrue(report["live_db_unchanged"])
        finally:
            os.unlink(live)

    def test_missing_live_db_fails_closed(self) -> None:
        ws = _write_worksheet([_accepted_row(event_id=600)])
        report = cli.smoke_short_horizon_review_apply(
            worksheet_path=ws,
            db_path="/nonexistent/path/to/events.db",
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "live DB does not exist" in e for e in report["errors"]
        ))
        self.assertEqual(report["staged_count"], 0)
        self.assertIsNone(report["temp_db_path"])
        # Bailing before any copy is "unchanged" — we left the
        # nonexistent file the way we found it.
        self.assertTrue(report["live_db_unchanged"])


# ---------------------------------------------------------------------------
# Empty / no-op worksheets
# ---------------------------------------------------------------------------


class TestEmptyWorksheet(unittest.TestCase):
    def test_header_only_worksheet_is_a_clean_no_op(self) -> None:
        live = _make_live_db(seed_event_ids=[80])
        try:
            before = _sha256(live)
            ws = _write_worksheet([])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["accepted_count"], 0)
            self.assertEqual(report["staged_count"], 0)
            self.assertEqual(report["staged_event_ids"], [])
            self.assertEqual(report["excluded_count"], 0)
            self.assertEqual(report["pending_count"], 0)
            self.assertTrue(report["live_db_unchanged"])
            self.assertIsNone(report["temp_db_path"])
            self.assertEqual(_sha256(live), before)
        finally:
            os.unlink(live)

    def test_only_excluded_and_pending_rows_is_a_clean_no_op(self) -> None:
        live = _make_live_db(seed_event_ids=[80])
        try:
            before = _sha256(live)
            ws = _write_worksheet([
                _excluded_row(event_id=900),
                _excluded_row(event_id=901),
                _pending_row(event_id=902),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["accepted_count"], 0)
            self.assertEqual(report["staged_count"], 0)
            self.assertEqual(report["excluded_count"], 2)
            self.assertEqual(report["pending_count"], 1)
            self.assertTrue(report["live_db_unchanged"])
            self.assertIsNone(report["temp_db_path"])
            self.assertEqual(_sha256(live), before)
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


class TestPatchableSeams(unittest.TestCase):
    def test_copy_live_db_to_temp_seam_is_patchable(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([_accepted_row(event_id=700)])
            sentinel_temp = _make_live_db(with_curated_table=True)
            try:
                with patch.object(
                    cli, "_copy_live_db_to_temp",
                    return_value=sentinel_temp,
                ) as copy_seam:
                    report = cli.smoke_short_horizon_review_apply(
                        worksheet_path=ws, db_path=live,
                    )
                self.assertEqual(copy_seam.call_count, 1)
                self.assertEqual(report["temp_db_path"], sentinel_temp)
                self.assertEqual(report["staged_count"], 1)
            finally:
                if os.path.exists(sentinel_temp):
                    os.unlink(sentinel_temp)
        finally:
            os.unlink(live)

    def test_stage_curated_candidates_seam_is_patchable(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _accepted_row(event_id=800),
                _accepted_row(event_id=801),
            ])
            with patch.object(
                cli, "_stage_curated_candidates",
                return_value=(2, [800, 801]),
            ) as stage_seam:
                report = cli.smoke_short_horizon_review_apply(
                    worksheet_path=ws, db_path=live,
                )
            self.assertEqual(stage_seam.call_count, 1)
            self.assertEqual(report["staged_count"], 2)
            self.assertEqual(report["staged_event_ids"], [800, 801])
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_text_render(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _accepted_row(event_id=900),
                _excluded_row(event_id=901),
                _pending_row(event_id=902),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            text = cli._render_text(report)
            lowered = text.lower()
            for token in _BANNED_WORDS:
                self.assertNotIn(
                    token, lowered,
                    f"banned token {token!r} in render: {text}",
                )
        finally:
            os.unlink(live)

    def test_no_banned_tokens_in_report_json(self) -> None:
        # The JSON envelope is what an operator most often sees.
        # Banned tokens must not surface there either.
        live = _make_live_db()
        try:
            ws = _write_worksheet([
                _accepted_row(event_id=910),
                _excluded_row(event_id=911),
            ])
            report = cli.smoke_short_horizon_review_apply(
                worksheet_path=ws, db_path=live,
            )
            blob = cli._render_json(report).lower()
            for token in _BANNED_WORDS:
                self.assertNotIn(
                    token, blob,
                    f"banned token {token!r} in JSON render",
                )
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLIEntryPoint(unittest.TestCase):
    def test_main_json_prints_valid_json(self) -> None:
        live = _make_live_db()
        try:
            ws = _write_worksheet([_accepted_row(event_id=1000)])
            buf = StringIO()
            rc = cli.main(
                ["--worksheet", ws, "--db-path", live, "--json"],
                out=buf,
            )
            payload = json.loads(buf.getvalue())
            self.assertEqual(set(payload.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
        finally:
            os.unlink(live)

    def test_main_returns_nonzero_on_failure(self) -> None:
        buf = StringIO()
        rc = cli.main(
            ["--worksheet", "/nonexistent.csv", "--json"],
            out=buf,
        )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
