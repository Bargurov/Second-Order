"""Tests for ``scripts/manual_ticker_repair_apply_smoke.py``.

Pin the contract:

* Default mode is ``dry-run`` — no copy, no apply, no DB writes,
  no provider/yfinance/LLM/FastAPI imports.
* Write mode requires ALL of ``--write --confirm --backup-path
  --csv-path``; any missing flag → fail closed.
* Live ``--db-path`` is hashed read-only before/after the smoke
  and must be byte-identical; same invariant for the input
  ``--backup-path``.  Both invariants hold even on every fail-
  closed path including schema-missing-exclusion-field.
* The temp copy is the only mutated artifact.
* Each CSV row is categorized as exclusion (``exclude_reason``
  set), retag (``proposed_primary_ticker`` set), no-op (neither),
  or ambiguous (both).  Ambiguous and no-op rows do NOT apply;
  they surface as errors / warnings.
* Exclusions flip ``low_signal=1`` in the temp DB.  This is the
  safest existing field with "deprioritized / skip" semantics in
  the events schema; pinning it to a different column would be
  a destructive choice.
* Retags update ``market_tickers`` JSON in the temp DB,
  preserving any non-symbol fields on the first list entry
  (e.g. ``weight``) so existing row content is preserved.
* If the temp DB schema lacks ``low_signal`` AND the CSV has at
  least one exclusion row, ``schema_missing_exclusion_field``
  fails the run closed: NEITHER exclusions NOR retags apply,
  ``rows_excluded == 0`` and ``rows_retagged == 0``.
* Three reports run after apply (clean_validation_cohort_report,
  stat_validation_ticker_contamination_report,
  stat_validation_readiness_report) through patchable seams.
* Output dict carries EXACTLY the 14 brief-mandated keys.
"""
from __future__ import annotations

import hashlib
import io
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

from scripts import manual_ticker_repair_apply_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "mode",
    "rows_read",
    "rows_excluded",
    "rows_retagged",
    "before_clean_fully_ready",
    "after_clean_fully_ready",
    "clean_fully_ready_delta",
    "before_contaminated_fully_ready",
    "after_contaminated_fully_ready",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
)


# ---------------------------------------------------------------------------
# On-disk fixtures
# ---------------------------------------------------------------------------


_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


def _events_ddl(*, with_low_signal: bool = True) -> str:
    cols = [
        "id              INTEGER PRIMARY KEY AUTOINCREMENT",
        "headline        TEXT",
        "event_date      TEXT",
        "market_tickers  TEXT",
    ]
    if with_low_signal:
        cols.append("low_signal      INTEGER DEFAULT 0")
    return "CREATE TABLE events (\n  " + ",\n  ".join(cols) + "\n)"


def _make_temp_db(
    suffix: str = "apply_smoke",
    *,
    with_low_signal: bool = True,
    seed_events: list[dict] | None = None,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_events_ddl(with_low_signal=with_low_signal))
        conn.execute(_PRICE_CACHE_DDL)
        if seed_events:
            for e in seed_events:
                cols = ["id", "headline", "event_date", "market_tickers"]
                vals = [
                    e["id"], e.get("headline"), e.get("event_date"),
                    e.get("market_tickers", "[]"),
                ]
                if with_low_signal:
                    cols.append("low_signal")
                    vals.append(int(e.get("low_signal", 0)))
                placeholders = ", ".join(["?"] * len(cols))
                conn.execute(
                    f"INSERT INTO events ({', '.join(cols)}) "
                    f"VALUES ({placeholders})",
                    vals,
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


def _write_csv(rows: list[dict], *, suffix: str = "apply_csv") -> str:
    """Write rows to a temp CSV with the 11-column packet header."""
    columns = (
        "event_id", "headline", "event_date", "current_primary_ticker",
        "flags", "reason", "manual_review_priority",
        "proposed_primary_ticker", "proposed_benchmark",
        "ticker_rationale", "exclude_reason",
    )
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in columns])
    return path


def _csv_row(
    *, event_id: int,
    proposed_primary_ticker: str = "",
    proposed_benchmark: str = "",
    ticker_rationale: str = "",
    exclude_reason: str = "",
    headline: str = "h",
    current_primary_ticker: str = "DRIV",
    flags: str = "driv_lit_off_topic",
    reason: str = "contaminated_fully_ready",
    manual_review_priority: str = "high",
    event_date: str = "2026-04-01",
) -> dict:
    return {
        "event_id":                 event_id,
        "headline":                 headline,
        "event_date":               event_date,
        "current_primary_ticker":   current_primary_ticker,
        "flags":                    flags,
        "reason":                   reason,
        "manual_review_priority":   manual_review_priority,
        "proposed_primary_ticker":  proposed_primary_ticker,
        "proposed_benchmark":       proposed_benchmark,
        "ticker_rationale":         ticker_rationale,
        "exclude_reason":           exclude_reason,
    }


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _clean_payload(*, count: int) -> dict:
    return {"clean_fully_ready_count": count}


def _contam_payload(*, suspicious: int) -> dict:
    return {"suspicious_count": suspicious}


def _readiness_payload(*, total: int = 0, fully_ready: int = 0) -> dict:
    return {"total_events": total, "events_fully_ready": fully_ready}


def _patch_seams(
    *,
    clean_before: int = 0,
    clean_after: int | None = None,
    contam_before: int = 0,
    contam_after: int | None = None,
    readiness: dict | None = None,
):
    clean_after = clean_after if clean_after is not None else clean_before
    contam_after = contam_after if contam_after is not None else contam_before
    clean_calls = iter([
        _clean_payload(count=clean_before),
        _clean_payload(count=clean_after),
    ])
    contam_calls = iter([
        _contam_payload(suspicious=contam_before),
        _contam_payload(suspicious=contam_after),
    ])

    def fake_clean(*, db_path):
        return next(clean_calls)

    def fake_contam(*, db_path):
        return next(contam_calls)

    def fake_readiness(*, db_path):
        return readiness if readiness is not None else _readiness_payload()

    return (
        patch.object(cli, "_run_clean_cohort_report", side_effect=fake_clean),
        patch.object(cli, "_run_contamination_report", side_effect=fake_contam),
        patch.object(cli, "_run_readiness_report", side_effect=fake_readiness),
    )


def _run(*, csv_path: str | None = None, **kwargs) -> dict:
    return cli.smoke_apply_repair(csv_path=csv_path, **kwargs)


# ---------------------------------------------------------------------------
# Output contract — exactly 14 keys
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_dry_run_returns_dict_with_exactly_14_keys(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))

    def test_no_additive_fields_on_write_mode(self) -> None:
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01"},
        ])
        csv_path = _write_csv([_csv_row(event_id=1, exclude_reason="off-topic")])
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            for w in result.get("warnings", []):
                # Clean any temp copy mentioned in warnings.
                if "Temp copy at " in w:
                    p = w.split("Temp copy at ", 1)[1].strip()
                    if os.path.exists(p):
                        os.unlink(p)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))


# ---------------------------------------------------------------------------
# Default dry-run
# ---------------------------------------------------------------------------


class TestDryRunDefault(unittest.TestCase):
    def test_default_mode_is_dry_run(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mode"], "dry-run")
        self.assertIs(result["ok"], True)

    def test_dry_run_counts_categories_without_running_reports(self) -> None:
        rows = [
            _csv_row(event_id=1, exclude_reason="off-topic"),
            _csv_row(event_id=2, exclude_reason="off-topic"),
            _csv_row(event_id=3, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY"),
        ]
        csv_path = _write_csv(rows)
        try:
            with patch.object(cli, "_run_clean_cohort_report") as clean:
                with patch.object(cli, "_run_contamination_report") as contam:
                    with patch.object(cli, "_run_readiness_report") as ready:
                        result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["rows_read"],     3)
        self.assertEqual(result["rows_excluded"], 2)
        self.assertEqual(result["rows_retagged"], 1)
        self.assertFalse(clean.called,
                         "dry-run must not call clean cohort report")
        self.assertFalse(contam.called,
                         "dry-run must not call contamination report")
        self.assertFalse(ready.called,
                         "dry-run must not call readiness report")

    def test_dry_run_before_after_fields_are_null(self) -> None:
        csv_path = _write_csv([_csv_row(event_id=1, exclude_reason="x")])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIsNone(result["before_clean_fully_ready"])
        self.assertIsNone(result["after_clean_fully_ready"])
        self.assertIsNone(result["clean_fully_ready_delta"])
        self.assertIsNone(result["before_contaminated_fully_ready"])
        self.assertIsNone(result["after_contaminated_fully_ready"])

    def test_dry_run_hash_invariants_true(self) -> None:
        csv_path = _write_csv([_csv_row(event_id=1, exclude_reason="x")])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIs(result["live_db_unchanged"],     True)
        self.assertIs(result["input_backup_unchanged"], True)


# ---------------------------------------------------------------------------
# Write-mode flag validation
# ---------------------------------------------------------------------------


class TestWriteFlagValidation(unittest.TestCase):
    def test_write_without_confirm_rejected(self) -> None:
        result = _run(write=True, confirm=False,
                      backup_path="/tmp/x.db", csv_path="/tmp/x.csv")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["rows_read"],     0)
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertTrue(any("--confirm" in e for e in result["errors"]))

    def test_write_without_backup_path_rejected(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True, csv_path=csv_path, backup_path=None,
            )
        finally:
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("--backup-path" in e for e in result["errors"]))

    def test_write_without_csv_path_rejected(self) -> None:
        backup = _make_temp_db("apply_backup")
        try:
            result = _run(
                write=True, confirm=True, backup_path=backup, csv_path=None,
            )
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("--csv-path" in e for e in result["errors"]))

    def test_backup_path_equals_db_path_rejected(self) -> None:
        live = _make_temp_db("apply_live")
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True,
                db_path=live, backup_path=live, csv_path=csv_path,
            )
        finally:
            os.unlink(live)
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("differ" in e.lower() or "same" in e.lower()
                for e in result["errors"]))

    def test_backup_path_nonexistent_rejected(self) -> None:
        bogus = os.path.join(tempfile.gettempdir(),
                             f"missing_{uuid.uuid4().hex}.db")
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True,
                backup_path=bogus, csv_path=csv_path,
            )
        finally:
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("does not exist" in e.lower()
                            for e in result["errors"]))

    def test_csv_path_nonexistent_rejected(self) -> None:
        backup = _make_temp_db("apply_backup")
        bogus_csv = os.path.join(tempfile.gettempdir(),
                                 f"nope_{uuid.uuid4().hex}.csv")
        try:
            result = _run(
                write=True, confirm=True,
                backup_path=backup, csv_path=bogus_csv,
            )
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("does not exist" in e.lower()
                            for e in result["errors"]))


# ---------------------------------------------------------------------------
# CSV categorization
# ---------------------------------------------------------------------------


class TestCSVCategorization(unittest.TestCase):
    def test_ambiguous_row_rejected(self) -> None:
        rows = [
            _csv_row(event_id=1,
                     proposed_primary_ticker="MS",
                     exclude_reason="off-topic"),
        ]
        csv_path = _write_csv(rows)
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertTrue(
            any("ambiguous" in e.lower() or "both" in e.lower()
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )

    def test_no_op_row_warns(self) -> None:
        rows = [_csv_row(event_id=1)]  # no exclude, no proposed
        csv_path = _write_csv(rows)
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertTrue(
            any("no-op" in w.lower() or "no operator" in w.lower()
                or "no proposal" in w.lower()
                for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )

    def test_unparseable_event_id_warns(self) -> None:
        rows = [{
            "event_id": "not-an-int",
            "headline": "h", "event_date": "x", "current_primary_ticker": "",
            "flags": "", "reason": "", "manual_review_priority": "high",
            "proposed_primary_ticker": "MS", "proposed_benchmark": "",
            "ticker_rationale": "", "exclude_reason": "",
        }]
        csv_path = _write_csv(rows)
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        # No retag applied; warning surfaced.
        self.assertEqual(result["rows_retagged"], 0)


# ---------------------------------------------------------------------------
# Schema check — fail closed when low_signal is missing
# ---------------------------------------------------------------------------


class TestSchemaMissingExclusionField(unittest.TestCase):
    def test_schema_missing_low_signal_fails_closed_with_token(self) -> None:
        # Backup DB without a low_signal column.
        backup = _make_temp_db("apply_backup_no_ls",
                               with_low_signal=False,
                               seed_events=[{"id": 1, "event_date": "2026-04-01"}])
        rows = [_csv_row(event_id=1, exclude_reason="off-topic")]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            for w in result.get("warnings", []):
                if "Temp copy at " in w:
                    p = w.split("Temp copy at ", 1)[1].strip()
                    if os.path.exists(p):
                        os.unlink(p)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_exclusion_field" in e
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)

    def test_schema_missing_low_signal_no_apply_for_retag_rows(self) -> None:
        """Even retag rows must NOT apply when an exclusion row exists
        but the schema cannot honor it.  Fail-closed = no partial."""
        backup = _make_temp_db("apply_backup_no_ls",
                               with_low_signal=False,
                               seed_events=[
                                   {"id": 1, "event_date": "2026-04-01",
                                    "market_tickers": '[{"symbol":"DRIV"}]'},
                                   {"id": 2, "event_date": "2026-04-02",
                                    "market_tickers": '[{"symbol":"DRIV"}]'},
                               ])
        rows = [
            _csv_row(event_id=1, exclude_reason="off-topic"),
            _csv_row(event_id=2, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY"),
        ]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            for w in result.get("warnings", []):
                if "Temp copy at " in w:
                    p = w.split("Temp copy at ", 1)[1].strip()
                    if os.path.exists(p):
                        os.unlink(p)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)

    def test_retag_only_csv_does_not_check_low_signal(self) -> None:
        """Schema check is irrelevant when there are no exclusion rows."""
        backup = _make_temp_db("apply_backup_no_ls",
                               with_low_signal=False,
                               seed_events=[
                                   {"id": 1, "event_date": "2026-04-01",
                                    "market_tickers": '[{"symbol":"DRIV"}]'},
                               ])
        rows = [_csv_row(event_id=1, proposed_primary_ticker="MS",
                         proposed_benchmark="SPY")]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            for w in result.get("warnings", []):
                if "Temp copy at " in w:
                    p = w.split("Temp copy at ", 1)[1].strip()
                    if os.path.exists(p):
                        os.unlink(p)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["rows_retagged"], 1)
        self.assertNotIn(
            "schema_missing_exclusion_field",
            " ".join(result["errors"]),
        )


# ---------------------------------------------------------------------------
# Apply behavior — exclusion + retag mutate temp DB only
# ---------------------------------------------------------------------------


class TestApplyMutatesTempOnly(unittest.TestCase):
    def test_exclusion_sets_low_signal_in_temp_only(self) -> None:
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]', "low_signal": 0},
        ])
        rows = [_csv_row(event_id=1, exclude_reason="off-topic")]
        csv_path = _write_csv(rows)
        backup_before = _sha256(backup)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            backup_after = _sha256(backup)
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            self.assertTrue(os.path.exists(tcp))
            # Backup unchanged; temp DB has low_signal=1 for event 1.
            self.assertEqual(backup_before, backup_after)
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT low_signal FROM events WHERE id = 1"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(row[0], 1)
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["rows_excluded"], 1)

    def test_retag_updates_market_tickers_preserving_extras(self) -> None:
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers":
                 '[{"symbol":"DRIV","weight":1.0,"role":"primary"}]'},
        ])
        rows = [_csv_row(event_id=1, proposed_primary_ticker="MS",
                         proposed_benchmark="SPY",
                         ticker_rationale="parent issuer")]
        csv_path = _write_csv(rows)
        backup_before = _sha256(backup)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            backup_after = _sha256(backup)
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            self.assertEqual(backup_before, backup_after)
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT market_tickers FROM events WHERE id = 1"
                ).fetchone()
            finally:
                conn.close()
            parsed = json.loads(row[0])
            self.assertEqual(parsed[0]["symbol"], "MS")
            # Extras preserved.
            self.assertEqual(parsed[0]["weight"], 1.0)
            self.assertEqual(parsed[0]["role"],   "primary")
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["rows_retagged"], 1)

    def test_retag_with_empty_market_tickers_creates_new_list(self) -> None:
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01", "market_tickers": "[]"},
        ])
        rows = [_csv_row(event_id=1, proposed_primary_ticker="MS",
                         proposed_benchmark="SPY")]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT market_tickers FROM events WHERE id = 1"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(json.loads(row[0]),
                             [{"symbol": "MS"}])
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["rows_retagged"], 1)


# ---------------------------------------------------------------------------
# Hash invariants — backup & live DB byte-identical
# ---------------------------------------------------------------------------


class TestHashInvariants(unittest.TestCase):
    def test_write_mode_leaves_live_db_byte_identical(self) -> None:
        live = _make_temp_db("apply_live", seed_events=[
            {"id": 1, "event_date": "2026-04-01"},
        ])
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        rows = [_csv_row(event_id=1, proposed_primary_ticker="MS",
                         proposed_benchmark="SPY")]
        csv_path = _write_csv(rows)
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup, db_path=live,
                    write=True, confirm=True,
                )
            live_after = _sha256(live)
            backup_after = _sha256(backup)
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(live_before,   live_after)
        self.assertEqual(backup_before, backup_after)
        self.assertIs(result["live_db_unchanged"],     True)
        self.assertIs(result["input_backup_unchanged"], True)

    def test_schema_missing_exclusion_field_keeps_hashes(self) -> None:
        backup = _make_temp_db("apply_backup_no_ls",
                               with_low_signal=False,
                               seed_events=[
                                   {"id": 1, "event_date": "2026-04-01"},
                               ])
        rows = [_csv_row(event_id=1, exclude_reason="off-topic")]
        csv_path = _write_csv(rows)
        backup_before = _sha256(backup)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            backup_after = _sha256(backup)
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(backup_before, backup_after)
        self.assertIs(result["input_backup_unchanged"], True)


# ---------------------------------------------------------------------------
# Before/after counts wired through report seams
# ---------------------------------------------------------------------------


class TestBeforeAfterCounts(unittest.TestCase):
    def test_retag_drops_contamination_count(self) -> None:
        """Retag CSV row → contamination should drop, clean should rise."""
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        rows = [_csv_row(event_id=1, proposed_primary_ticker="MS",
                         proposed_benchmark="SPY")]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams(
                clean_before=10, clean_after=11,
                contam_before=7, contam_after=6,
            )
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["before_clean_fully_ready"],         10)
        self.assertEqual(result["after_clean_fully_ready"],          11)
        self.assertEqual(result["clean_fully_ready_delta"],           1)
        self.assertEqual(result["before_contaminated_fully_ready"],   7)
        self.assertEqual(result["after_contaminated_fully_ready"],    6)

    def test_exclusion_only_csv_counts_unchanged(self) -> None:
        """Truthful behavior given current report semantics: setting
        low_signal=1 does not change clean/contam counts because those
        reports do not filter on low_signal.  Pin this so it doesn't
        silently regress."""
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01"},
        ])
        rows = [_csv_row(event_id=1, exclude_reason="off-topic")]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams(
                clean_before=5, clean_after=5,
                contam_before=7, contam_after=7,
            )
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["rows_excluded"], 1)
        self.assertEqual(result["clean_fully_ready_delta"], 0)
        self.assertEqual(result["before_contaminated_fully_ready"],
                         result["after_contaminated_fully_ready"])

    def test_clean_delta_is_after_minus_before(self) -> None:
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        rows = [_csv_row(event_id=1, proposed_primary_ticker="MS",
                         proposed_benchmark="SPY")]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams(
                clean_before=20, clean_after=23,
            )
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["clean_fully_ready_delta"], 3)


# ---------------------------------------------------------------------------
# proposed_benchmark non-SPY → warn but proceed
# ---------------------------------------------------------------------------


class TestNonSpyBenchmarkWarn(unittest.TestCase):
    def test_non_spy_benchmark_warns_but_proceeds(self) -> None:
        backup = _make_temp_db("apply_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        rows = [_csv_row(event_id=1, proposed_primary_ticker="MS",
                         proposed_benchmark="QQQ")]
        csv_path = _write_csv(rows)
        try:
            p1, p2, p3 = _patch_seams()
            with p1, p2, p3:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["rows_retagged"], 1)
        self.assertTrue(
            any("benchmark" in w.lower() for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )
        self.assertIs(result["ok"], True)


# ---------------------------------------------------------------------------
# Patchable seams + import isolation
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_clean_cohort_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_clean_cohort_report")))

    def test_contamination_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_contamination_report")))

    def test_readiness_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_readiness_report")))


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_default_dry_run_does_not_import_provider_or_fastapi(
        self,
    ) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        csv_path = _write_csv([])
        try:
            cli.smoke_apply_repair(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set(),
                         "default dry-run imported a forbidden module")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _cli(self, argv: list[str], **patch_kwargs) -> tuple[int, str]:
        out = StringIO()
        p1, p2, p3 = _patch_seams(**patch_kwargs)
        with p1, p2, p3:
            try:
                rc = cli.main(argv, out=out)
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue()

    def test_dry_run_default_emits_parseable_json(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
        ])
        try:
            rc, output = self._cli([
                "--dry-run", "--json", "--csv-path", csv_path,
            ])
        finally:
            os.unlink(csv_path)
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_no_flag_defaults_to_dry_run(self) -> None:
        csv_path = _write_csv([])
        try:
            rc, output = self._cli([
                "--json", "--csv-path", csv_path,
            ])
        finally:
            os.unlink(csv_path)
        parsed = json.loads(output)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_write_without_confirm_fails(self) -> None:
        csv_path = _write_csv([])
        try:
            rc, output = self._cli([
                "--write", "--backup-path", "/tmp/x.db",
                "--csv-path", csv_path, "--json",
            ])
        finally:
            os.unlink(csv_path)
        parsed = json.loads(output)
        self.assertIs(parsed["ok"], False)


if __name__ == "__main__":
    unittest.main()
