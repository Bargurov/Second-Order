"""Tests for ``scripts/manual_ticker_repair_full_smoke.py``.

Pin the contract:

* Default mode is ``dry-run`` — no copy, no apply, no DB writes,
  no provider call, no readiness/contamination/clean-cohort
  imports.
* Write mode requires ALL of ``--write --confirm --backup-path
  --csv-path``; any missing flag → fail closed.
* Sequential write-mode order:
    1. Copy backup → temp
    2. Apply exclusions / retags (events table)
    3. Backfill price_cache for retag tickers
    4-6. Run readiness, contamination, clean-cohort reports
* Fail-closed precedence:
    - Empty CSV (no exclusions, no retags) → fail closed.
    - Exclusion-only CSV → apply runs, no provider check, OK.
    - Retag rows + provider unavailable → fail closed BEFORE copy.
    - Schema missing low_signal + exclusion rows → fail closed
      after copy, no apply.
* Live ``--db-path`` and input ``--backup-path`` are SHA-256
  byte-identical before/after every run, including every fail-
  closed path.
* Output dict carries EXACTLY the 18 brief-mandated keys (including
  the two ``mechanism_family_*`` summary fields).
* Three reports run after apply+backfill via local seams on this
  module; provider seams are also local for clean test patching.
"""
from __future__ import annotations

import csv as csv_module
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

from scripts import manual_ticker_repair_full_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "mode",
    "rows_read",
    "rows_excluded",
    "rows_retagged",
    "tickers_planned",
    "price_rows_written",
    "mechanism_family_updates",
    "mechanism_family_updated_event_ids",
    "before_clean_fully_ready",
    "after_clean_fully_ready",
    "clean_fully_ready_delta",
    "before_contaminated_fully_ready",
    "after_contaminated_fully_ready",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
    # Manual-aware clean-cohort metrics — same surface as the medium-
    # batch smoke.  The raw report's clean-cohort math doesn't know
    # about operator exclusions; the smoke layer surfaces an
    # operator-aware view alongside the raw counts so an operator can
    # see which events are eligible for the aggregate claim AFTER
    # exclusions / retags / mechanism-family decisions land — without
    # weakening the underlying contamination report.
    "operator_excluded_event_ids",
    "raw_after_clean_fully_ready",
    "adjusted_after_clean_fully_ready",
    "adjusted_clean_fully_ready_delta",
    "remaining_contamination_reasons",
)


# ---------------------------------------------------------------------------
# Fixtures
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


def _events_ddl(
    *, with_low_signal: bool = True, with_mechanism_family: bool = True,
) -> str:
    cols = [
        "id              INTEGER PRIMARY KEY AUTOINCREMENT",
        "headline        TEXT",
        "event_date      TEXT",
        "market_tickers  TEXT",
    ]
    if with_low_signal:
        cols.append("low_signal      INTEGER DEFAULT 0")
    if with_mechanism_family:
        cols.append("mechanism_family TEXT DEFAULT 'none'")
    return "CREATE TABLE events (\n  " + ",\n  ".join(cols) + "\n)"


def _make_temp_db(
    suffix: str = "full_smoke",
    *,
    with_low_signal: bool = True,
    with_mechanism_family: bool = True,
    seed_events: list[dict] | None = None,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_events_ddl(
            with_low_signal=with_low_signal,
            with_mechanism_family=with_mechanism_family,
        ))
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
                if with_mechanism_family:
                    cols.append("mechanism_family")
                    vals.append(e.get("mechanism_family", "none"))
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


def _write_csv(rows: list[dict], *, suffix: str = "full_csv") -> str:
    columns = (
        "event_id", "headline", "event_date", "current_primary_ticker",
        "flags", "reason", "manual_review_priority",
        "proposed_primary_ticker", "proposed_benchmark",
        "proposed_mechanism_family",
        "ticker_rationale", "exclude_reason",
    )
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in columns])
    return path


def _csv_row(
    *, event_id: int,
    proposed_primary_ticker: str = "",
    proposed_benchmark: str = "",
    proposed_mechanism_family: str = "",
    exclude_reason: str = "",
    event_date: str = "2026-04-06",
    headline: str = "h",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    "DRIV",
        "flags":                     "",
        "reason":                    "contaminated_fully_ready",
        "manual_review_priority":    "high",
        "proposed_primary_ticker":   proposed_primary_ticker,
        "proposed_benchmark":        proposed_benchmark,
        "proposed_mechanism_family": proposed_mechanism_family,
        "ticker_rationale":          "",
        "exclude_reason":            exclude_reason,
    }


def _spy_row(date_iso: str, *, close: float = 100.0,
             volume: float = 1.0e6) -> dict:
    return {"date": date_iso, "close": close, "volume": volume}


def _patch_seams(
    *,
    clean_before: int = 0,
    clean_after: int | None = None,
    after_payload: dict | None = None,
    before_payload: dict | None = None,
    contam_before: int = 0,
    contam_after: int | None = None,
    provider_available: bool = True,
    fetch_rows: list[dict] | None = None,
    fetch_side_effect: Exception | None = None,
):
    """Patch the three report seams + provider seams.

    Two clean-cohort fake-payload styles are supported:

      * Bare scalar form (``clean_before`` / ``clean_after``) — returns
        ``{"clean_fully_ready_count": N}`` only.  Backward-compatible
        for tests that don't pin the manual-aware adjustment fields.
      * Rich payload form (``before_payload`` / ``after_payload``) —
        returns the full dict the smoke needs to compute the
        ``adjusted_*`` and ``remaining_contamination_reasons`` fields.
        When supplied, the rich payload wins.
    """
    if before_payload is None:
        before_payload = {"clean_fully_ready_count": clean_before}
    if after_payload is None:
        eff_after = clean_after if clean_after is not None else clean_before
        after_payload = {"clean_fully_ready_count": eff_after}
    contam_after = contam_after if contam_after is not None else contam_before
    clean_calls = iter([before_payload, after_payload])
    contam_calls = iter([
        {"suspicious_count": contam_before},
        {"suspicious_count": contam_after},
    ])

    def fake_clean(*, db_path):
        return next(clean_calls)

    def fake_contam(*, db_path):
        return next(contam_calls)

    def fake_readiness(*, db_path):
        return {"total_events": 0, "events_fully_ready": 0}

    if fetch_side_effect is not None:
        fetch_patch = patch.object(
            cli, "_fetch_ticker_rows", side_effect=fetch_side_effect)
    else:
        rows = fetch_rows if fetch_rows is not None else []

        def fake_fetch(*, ticker, start, end):
            return rows
        fetch_patch = patch.object(
            cli, "_fetch_ticker_rows", side_effect=fake_fetch)

    return (
        patch.object(cli, "_run_clean_cohort_report",  side_effect=fake_clean),
        patch.object(cli, "_run_contamination_report", side_effect=fake_contam),
        patch.object(cli, "_run_readiness_report",     side_effect=fake_readiness),
        patch.object(cli, "_check_provider_available", return_value=provider_available),
        fetch_patch,
    )


def _run(*, csv_path: str | None = None, **kwargs) -> dict:
    return cli.smoke_full_repair(csv_path=csv_path, **kwargs)


def _cleanup_temp_copy(result: dict) -> None:
    for w in result.get("warnings", []):
        if "Temp copy at " in w:
            p = w.split("Temp copy at ", 1)[1].strip()
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_dry_run_returns_dict_with_exactly_18_keys(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))

    def test_no_additive_fields_on_write_mode(self) -> None:
        backup = _make_temp_db("full_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-01"),
        ])
        try:
            patches = _patch_seams(
                fetch_rows=[_spy_row("2026-03-01"), _spy_row("2026-04-10")])
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
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

    def test_dry_run_does_not_call_seams(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS"),
            _csv_row(event_id=2, exclude_reason="off-topic"),
        ])
        try:
            with patch.object(cli, "_check_provider_available") as check:
                with patch.object(cli, "_fetch_ticker_rows") as fetch:
                    with patch.object(cli, "_run_clean_cohort_report") as clean:
                        with patch.object(cli, "_run_contamination_report") as contam:
                            with patch.object(cli, "_run_readiness_report") as ready:
                                _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertFalse(check.called)
        self.assertFalse(fetch.called)
        self.assertFalse(clean.called)
        self.assertFalse(contam.called)
        self.assertFalse(ready.called)

    def test_dry_run_counts_categories_and_tickers(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS"),
            _csv_row(event_id=2, proposed_primary_ticker="MS"),
            _csv_row(event_id=3, proposed_primary_ticker="JPM"),
            _csv_row(event_id=4, exclude_reason="off-topic"),
            _csv_row(event_id=5, exclude_reason="off-topic"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["rows_read"],       5)
        self.assertEqual(result["rows_excluded"],   2)
        self.assertEqual(result["rows_retagged"],   3)
        self.assertEqual(result["tickers_planned"], 2)  # MS + JPM
        self.assertEqual(result["price_rows_written"], 0)

    def test_dry_run_before_after_are_null(self) -> None:
        csv_path = _write_csv([_csv_row(event_id=1,
                                        proposed_primary_ticker="MS")])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIsNone(result["before_clean_fully_ready"])
        self.assertIsNone(result["after_clean_fully_ready"])
        self.assertIsNone(result["clean_fully_ready_delta"])
        self.assertIsNone(result["before_contaminated_fully_ready"])
        self.assertIsNone(result["after_contaminated_fully_ready"])


# ---------------------------------------------------------------------------
# Write-mode flag validation
# ---------------------------------------------------------------------------


class TestWriteFlagValidation(unittest.TestCase):
    def test_write_without_confirm_rejected(self) -> None:
        result = _run(write=True, confirm=False,
                      backup_path="/tmp/x.db", csv_path="/tmp/x.csv")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["price_rows_written"], 0)

    def test_write_without_backup_path_rejected(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True, csv_path=csv_path, backup_path=None)
        finally:
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)

    def test_write_without_csv_path_rejected(self) -> None:
        backup = _make_temp_db("full_backup")
        try:
            result = _run(
                write=True, confirm=True, backup_path=backup, csv_path=None)
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)

    def test_backup_equals_db_path_rejected(self) -> None:
        live = _make_temp_db("full_live")
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True,
                db_path=live, backup_path=live, csv_path=csv_path)
        finally:
            os.unlink(live)
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)


# ---------------------------------------------------------------------------
# Fail-closed precedence
# ---------------------------------------------------------------------------


class TestFailClosedEmptyCSV(unittest.TestCase):
    def test_empty_csv_fails_closed_no_temp_copy(self) -> None:
        backup = _make_temp_db("full_backup")
        csv_path = _write_csv([])
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["rows_excluded"],     0)
        self.assertEqual(result["rows_retagged"],     0)
        self.assertEqual(result["price_rows_written"], 0)
        self.assertFalse(
            any("Temp copy at " in w for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )


class TestExclusionOnlyDoesNotNeedProvider(unittest.TestCase):
    def test_exclusion_only_csv_runs_apply_no_provider_check(self) -> None:
        backup = _make_temp_db("full_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01"},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
        ])
        try:
            with patch.object(cli, "_check_provider_available") as check:
                with patch.object(cli, "_fetch_ticker_rows") as fetch:
                    with patch.object(cli, "_run_clean_cohort_report",
                                      return_value={"clean_fully_ready_count": 0}):
                        with patch.object(cli, "_run_contamination_report",
                                          return_value={"suspicious_count": 0}):
                            with patch.object(cli, "_run_readiness_report",
                                              return_value={}):
                                result = _run(
                                    csv_path=csv_path, backup_path=backup,
                                    write=True, confirm=True,
                                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["rows_excluded"], 1)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertEqual(result["tickers_planned"], 0)
        self.assertEqual(result["price_rows_written"], 0)
        # Provider must NOT be probed when there are no retag rows.
        self.assertFalse(
            check.called,
            "provider must not be probed for exclusion-only CSV",
        )
        self.assertFalse(
            fetch.called,
            "fetch must not be called for exclusion-only CSV",
        )


class TestRetagRowsWithProviderUnavailableFailsClosed(unittest.TestCase):
    def test_retag_with_provider_unavailable_fails_before_copy(self) -> None:
        backup = _make_temp_db("full_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-01"),
        ])
        try:
            patches = _patch_seams(provider_available=False)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        # Apply must NOT have run — neither exclusions nor retags.
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertEqual(result["price_rows_written"], 0)
        # tickers_planned IS surfaced even on this fail-closed path.
        self.assertEqual(result["tickers_planned"], 1)
        self.assertTrue(
            any("provider" in e.lower() for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        # No temp copy created on this path.
        self.assertFalse(
            any("Temp copy at " in w for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )

    def test_mixed_csv_with_provider_unavailable_fails_closed(self) -> None:
        """Even when CSV mixes exclusions + retags, retag-with-no-provider
        fails the whole run closed.  Apply does NOT run for the
        exclusion rows."""
        backup = _make_temp_db("full_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01"},
            {"id": 2, "event_date": "2026-04-02",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
            _csv_row(event_id=2, proposed_primary_ticker="MS",
                     event_date="2026-04-02"),
        ])
        try:
            patches = _patch_seams(provider_available=False)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)


class TestSchemaMissingFailsClosed(unittest.TestCase):
    def test_schema_missing_with_exclusions_fails_closed(self) -> None:
        backup = _make_temp_db("full_backup_no_ls",
                               with_low_signal=False,
                               seed_events=[
                                   {"id": 1, "event_date": "2026-04-01"},
                               ])
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
        ])
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_exclusion_field" in e for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        self.assertEqual(result["rows_excluded"], 0)


# ---------------------------------------------------------------------------
# Happy path — combined apply + backfill demonstrates joint effect
# ---------------------------------------------------------------------------


class TestHappyPathCombined(unittest.TestCase):
    def test_combined_run_applies_then_backfills_into_same_temp(self) -> None:
        """End-to-end wiring: retag DRIV→MS in events table AND insert
        MS rows into price_cache, all in the same temp DB.  Both
        mutations land before the after-reports run."""
        backup = _make_temp_db("full_backup", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV","weight":1.0}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY", event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(
                clean_before=0, clean_after=1,
                contam_before=11, contam_after=10,
                fetch_rows=[
                    _spy_row("2026-03-01"), _spy_row("2026-04-10"),
                ],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            # Both mutations landed in the same temp DB.
            conn = sqlite3.connect(tcp)
            try:
                ev_row = conn.execute(
                    "SELECT market_tickers FROM events WHERE id = 46"
                ).fetchone()
                ms_rows = conn.execute(
                    "SELECT date FROM price_cache WHERE ticker = 'MS' "
                    "ORDER BY date"
                ).fetchall()
            finally:
                conn.close()
            parsed = json.loads(ev_row[0])
            self.assertEqual(parsed[0]["symbol"], "MS")
            self.assertEqual(parsed[0]["weight"], 1.0)  # extras preserved
            self.assertEqual([r[0] for r in ms_rows],
                             ["2026-03-01", "2026-04-10"])
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(result["rows_retagged"],          1)
        self.assertEqual(result["tickers_planned"],        1)
        self.assertEqual(result["price_rows_written"],     2)
        self.assertEqual(result["before_clean_fully_ready"],         0)
        self.assertEqual(result["after_clean_fully_ready"],          1)
        self.assertEqual(result["clean_fully_ready_delta"],          1)
        self.assertEqual(result["before_contaminated_fully_ready"], 11)
        self.assertEqual(result["after_contaminated_fully_ready"],  10)


# ---------------------------------------------------------------------------
# Hash invariants on every fail path
# ---------------------------------------------------------------------------


class TestHashInvariantsAllPaths(unittest.TestCase):
    def test_empty_csv_keeps_hashes(self) -> None:
        live = _make_temp_db("full_live")
        backup = _make_temp_db("full_backup")
        csv_path = _write_csv([])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)

    def test_retag_with_provider_unavailable_keeps_hashes(self) -> None:
        live = _make_temp_db("full_live")
        backup = _make_temp_db("full_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-01"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(provider_available=False)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)

    def test_schema_missing_keeps_hashes(self) -> None:
        live = _make_temp_db("full_live")
        backup = _make_temp_db("full_backup_no_ls",
                               with_low_signal=False,
                               seed_events=[
                                   {"id": 1, "event_date": "2026-04-01"},
                               ])
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)

    def test_success_path_keeps_hashes(self) -> None:
        live = _make_temp_db("full_live")
        backup = _make_temp_db("full_backup", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)


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

    def test_check_provider_available_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_check_provider_available")))

    def test_fetch_ticker_rows_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_ticker_rows")))


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
            cli.smoke_full_repair(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mechanism-family decision support
# ---------------------------------------------------------------------------


class TestMechanismFamilyDecisionParsing(unittest.TestCase):
    def test_parse_single_decision(self) -> None:
        out, errs = cli._parse_mechanism_family_decisions(
            ["46=bank_regulatory_capital_relief"])
        self.assertEqual(out, {46: "bank_regulatory_capital_relief"})
        self.assertEqual(errs, [])

    def test_parse_multiple_decisions(self) -> None:
        out, errs = cli._parse_mechanism_family_decisions([
            "46=bank_regulatory_capital_relief",
            "12=tariff",
        ])
        self.assertEqual(out, {
            46: "bank_regulatory_capital_relief",
            12: "tariff",
        })
        self.assertEqual(errs, [])

    def test_parse_rejects_missing_equals(self) -> None:
        out, errs = cli._parse_mechanism_family_decisions(["46-bank"])
        self.assertEqual(out, {})
        self.assertTrue(errs)

    def test_parse_rejects_non_int_event_id(self) -> None:
        out, errs = cli._parse_mechanism_family_decisions(["abc=bank"])
        self.assertEqual(out, {})
        self.assertTrue(errs)

    def test_parse_rejects_empty_family(self) -> None:
        out, errs = cli._parse_mechanism_family_decisions(["46="])
        self.assertEqual(out, {})
        self.assertTrue(errs)


class TestMechanismFamilyApplyHelper(unittest.TestCase):
    def test_helper_updates_only_matching_rows(self) -> None:
        backup = _make_temp_db("mf_apply", seed_events=[
            {"id": 46, "event_date": "2026-04-06", "mechanism_family": "none"},
            {"id": 47, "event_date": "2026-04-06", "mechanism_family": "none"},
        ])
        warnings: list[str] = []
        try:
            applied, applied_ids = cli._apply_mechanism_family_decisions(
                backup,
                {46: "bank_regulatory_capital_relief"},
                warnings,
            )
            self.assertEqual(applied, 1)
            self.assertEqual(applied_ids, [46])
            conn = sqlite3.connect(backup)
            try:
                row46 = conn.execute(
                    "SELECT mechanism_family FROM events WHERE id = 46"
                ).fetchone()
                row47 = conn.execute(
                    "SELECT mechanism_family FROM events WHERE id = 47"
                ).fetchone()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
        self.assertEqual(row46[0], "bank_regulatory_capital_relief")
        self.assertEqual(row47[0], "none")

    def test_helper_skips_missing_event_id(self) -> None:
        backup = _make_temp_db("mf_apply_miss", seed_events=[
            {"id": 1, "event_date": "2026-04-01", "mechanism_family": "none"},
        ])
        warnings: list[str] = []
        try:
            applied, applied_ids = cli._apply_mechanism_family_decisions(
                backup, {99: "bank_regulatory_capital_relief"}, warnings)
        finally:
            os.unlink(backup)
        self.assertEqual(applied, 0)
        self.assertEqual(applied_ids, [])
        self.assertTrue(
            any("99" in w for w in warnings),
            f"warnings: {warnings!r}",
        )


class TestMechanismFamilyWriteMode(unittest.TestCase):
    def test_decision_applied_in_write_mode(self) -> None:
        backup = _make_temp_db("mf_write", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]',
             "mechanism_family": "none"},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY", event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(
                clean_before=0, clean_after=1,
                contam_before=11, contam_after=10,
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = cli.smoke_full_repair(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                    mechanism_family_decisions=[
                        "46=bank_regulatory_capital_relief",
                    ],
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            # Mechanism family landed on the temp DB; backup unchanged.
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT mechanism_family, market_tickers "
                    "FROM events WHERE id = 46"
                ).fetchone()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(row[0], "bank_regulatory_capital_relief")
        # Retag still happened — preserve existing behavior.
        parsed = json.loads(row[1])
        self.assertEqual(parsed[0]["symbol"], "MS")
        # Clean delta is +1 (mocked); operator-visible signal that
        # event 46 entered the clean cohort.
        self.assertEqual(result["clean_fully_ready_delta"], 1)
        # Decision application surfaced as a warning.
        self.assertTrue(
            any("mechanism family" in w.lower() and "46" in w
                for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )


class TestMechanismFamilySchemaMissingFailsClosed(unittest.TestCase):
    def test_decision_against_missing_column_fails_closed(self) -> None:
        backup = _make_temp_db("mf_no_col",
                               with_mechanism_family=False,
                               seed_events=[
                                   {"id": 46, "event_date": "2026-04-06",
                                    "market_tickers":
                                        '[{"symbol":"DRIV"}]'},
                               ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY", event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(fetch_rows=[_spy_row("2026-04-01")])
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = cli.smoke_full_repair(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                    mechanism_family_decisions=[
                        "46=bank_regulatory_capital_relief",
                    ],
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_mechanism_family_field" in e
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        # Fail-closed precedence: NEITHER apply nor backfill ran.
        self.assertEqual(result["rows_excluded"],     0)
        self.assertEqual(result["rows_retagged"],     0)
        self.assertEqual(result["price_rows_written"], 0)


class TestMechanismFamilyDryRun(unittest.TestCase):
    def test_dry_run_does_not_touch_db_or_seams(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            with patch.object(cli, "_check_provider_available") as check:
                with patch.object(cli, "_fetch_ticker_rows") as fetch:
                    with patch.object(cli, "_run_clean_cohort_report") as clean:
                        with patch.object(cli, "_run_contamination_report") as contam:
                            with patch.object(cli, "_run_readiness_report") as ready:
                                result = cli.smoke_full_repair(
                                    csv_path=csv_path,
                                    mechanism_family_decisions=[
                                        "46=bank_regulatory_capital_relief",
                                    ],
                                )
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mode"], "dry-run")
        self.assertFalse(check.called)
        self.assertFalse(fetch.called)
        self.assertFalse(clean.called)
        self.assertFalse(contam.called)
        self.assertFalse(ready.called)


class TestCSVMechanismFamilyExtraction(unittest.TestCase):
    """The smoke must read ``proposed_mechanism_family`` from each CSV
    row and surface non-blank values as auto-applied mechanism-family
    decisions, additive to the existing ``--mechanism-family-decision``
    CLI flag."""

    def test_extracts_non_blank_proposed_mechanism_family(self) -> None:
        rows = [
            _csv_row(event_id=46,
                     proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief"),
        ]
        out = cli._extract_csv_mechanism_family_decisions(rows)
        self.assertEqual(out, {46: "bank_regulatory_capital_relief"})

    def test_skips_blank_proposed_mechanism_family(self) -> None:
        rows = [
            _csv_row(event_id=4, exclude_reason="off-topic"),
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_mechanism_family="   "),
        ]
        out = cli._extract_csv_mechanism_family_decisions(rows)
        self.assertEqual(out, {})

    def test_skips_missing_column(self) -> None:
        rows = [{
            "event_id": "46", "event_date": "2026-04-06",
            "proposed_primary_ticker": "MS", "proposed_benchmark": "SPY",
            "exclude_reason": "",
        }]
        out = cli._extract_csv_mechanism_family_decisions(rows)
        self.assertEqual(out, {})

    def test_skips_unparseable_event_id(self) -> None:
        rows = [{
            "event_id": "abc", "event_date": "2026-04-06",
            "proposed_primary_ticker": "MS", "proposed_benchmark": "SPY",
            "proposed_mechanism_family": "bank_regulatory_capital_relief",
            "exclude_reason": "",
        }]
        out = cli._extract_csv_mechanism_family_decisions(rows)
        self.assertEqual(out, {})


class TestCSVDrivenMechanismFamilyApply(unittest.TestCase):
    """Write-mode behavior of CSV-driven mechanism_family decisions."""

    def test_csv_decision_applied_in_write_mode(self) -> None:
        backup = _make_temp_db("mf_csv_write", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]',
             "mechanism_family": "none"},
        ])
        csv_path = _write_csv([
            _csv_row(
                event_id=46, proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
                proposed_mechanism_family="bank_regulatory_capital_relief",
                event_date="2026-04-06",
            ),
        ])
        try:
            patches = _patch_seams(
                clean_before=0, clean_after=1,
                contam_before=11, contam_after=10,
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = cli.smoke_full_repair(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT mechanism_family FROM events WHERE id = 46"
                ).fetchone()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(row[0], "bank_regulatory_capital_relief")
        self.assertEqual(result["mechanism_family_updates"], 1)
        self.assertEqual(result["mechanism_family_updated_event_ids"], [46])
        self.assertIs(result["ok"], True)

    def test_cli_overrides_csv_for_same_event_id(self) -> None:
        backup = _make_temp_db("mf_override", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]',
             "mechanism_family": "none"},
        ])
        csv_path = _write_csv([
            _csv_row(
                event_id=46, proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
                proposed_mechanism_family="csv_family_token",
                event_date="2026-04-06",
            ),
        ])
        try:
            patches = _patch_seams(
                clean_before=0, clean_after=1,
                contam_before=11, contam_after=10,
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = cli.smoke_full_repair(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                    mechanism_family_decisions=["46=cli_family_token"],
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT mechanism_family FROM events WHERE id = 46"
                ).fetchone()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(row[0], "cli_family_token")
        self.assertEqual(result["mechanism_family_updates"], 1)
        self.assertEqual(result["mechanism_family_updated_event_ids"], [46])

    def test_csv_and_cli_merge_for_different_event_ids(self) -> None:
        backup = _make_temp_db("mf_merge", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]',
             "mechanism_family": "none"},
            {"id": 47, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]',
             "mechanism_family": "none"},
        ])
        csv_path = _write_csv([
            _csv_row(
                event_id=46, proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
                proposed_mechanism_family="csv_family_token",
                event_date="2026-04-06",
            ),
            _csv_row(
                event_id=47, exclude_reason="",
                event_date="2026-04-06",
                proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
            ),
        ])
        try:
            patches = _patch_seams(
                fetch_rows=[_spy_row("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = cli.smoke_full_repair(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                    mechanism_family_decisions=["47=cli_only_token"],
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            conn = sqlite3.connect(tcp)
            try:
                rows = conn.execute(
                    "SELECT id, mechanism_family FROM events ORDER BY id"
                ).fetchall()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        as_dict = {r[0]: r[1] for r in rows}
        self.assertEqual(as_dict[46], "csv_family_token")
        self.assertEqual(as_dict[47], "cli_only_token")
        self.assertEqual(result["mechanism_family_updates"], 2)
        self.assertEqual(
            sorted(result["mechanism_family_updated_event_ids"]), [46, 47],
        )

    def test_blank_csv_value_does_not_overwrite(self) -> None:
        backup = _make_temp_db("mf_blank", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]',
             "mechanism_family": "none"},
        ])
        csv_path = _write_csv([
            _csv_row(
                event_id=46, proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
                proposed_mechanism_family="",
                event_date="2026-04-06",
            ),
        ])
        try:
            patches = _patch_seams(fetch_rows=[_spy_row("2026-04-01")])
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = cli.smoke_full_repair(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT mechanism_family FROM events WHERE id = 46"
                ).fetchone()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(row[0], "none")
        self.assertEqual(result["mechanism_family_updates"], 0)
        self.assertEqual(result["mechanism_family_updated_event_ids"], [])


class TestCSVDrivenSchemaMissingFailsClosed(unittest.TestCase):
    """When the CSV provides a non-blank ``proposed_mechanism_family``
    but the temp DB lacks the ``mechanism_family`` column, the run
    must fail closed BEFORE applying retags or backfilling."""

    def test_csv_decision_against_missing_column_fails_closed(self) -> None:
        backup = _make_temp_db("mf_csv_no_col",
                               with_mechanism_family=False,
                               seed_events=[
                                   {"id": 46, "event_date": "2026-04-06",
                                    "market_tickers":
                                        '[{"symbol":"DRIV"}]'},
                               ])
        csv_path = _write_csv([
            _csv_row(
                event_id=46, proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
                proposed_mechanism_family="bank_regulatory_capital_relief",
                event_date="2026-04-06",
            ),
        ])
        try:
            patches = _patch_seams(fetch_rows=[_spy_row("2026-04-01")])
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = cli.smoke_full_repair(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_mechanism_family_field" in e
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertEqual(result["mechanism_family_updates"], 0)
        self.assertEqual(result["mechanism_family_updated_event_ids"], [])
        self.assertEqual(result["price_rows_written"], 0)


class TestMechanismFamilyDryRunReporting(unittest.TestCase):
    """Dry-run mirrors ``rows_retagged`` semantics — surface what
    *would* be applied (merged CSV + CLI) without touching any DB."""

    def test_dry_run_reports_merged_planned_updates(self) -> None:
        csv_path = _write_csv([
            _csv_row(
                event_id=46, proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
                proposed_mechanism_family="csv_family_token",
                event_date="2026-04-06",
            ),
        ])
        try:
            result = cli.smoke_full_repair(
                csv_path=csv_path,
                mechanism_family_decisions=["47=cli_only_token"],
            )
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["mechanism_family_updates"], 2)
        self.assertEqual(
            sorted(result["mechanism_family_updated_event_ids"]),
            [46, 47],
        )

    def test_dry_run_cli_overrides_csv_in_planned_updates(self) -> None:
        csv_path = _write_csv([
            _csv_row(
                event_id=46, proposed_primary_ticker="MS",
                proposed_benchmark="SPY",
                proposed_mechanism_family="csv_family_token",
                event_date="2026-04-06",
            ),
        ])
        try:
            result = cli.smoke_full_repair(
                csv_path=csv_path,
                mechanism_family_decisions=["46=cli_family_token"],
            )
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mechanism_family_updates"], 1)
        self.assertEqual(result["mechanism_family_updated_event_ids"], [46])


class TestCLI(unittest.TestCase):
    def _cli(self, argv: list[str], **patch_kwargs) -> tuple[int, str]:
        out = StringIO()
        patches = _patch_seams(**patch_kwargs)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            try:
                rc = cli.main(argv, out=out)
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue()

    def test_dry_run_default_emits_parseable_json(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS"),
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

    def test_mechanism_family_decision_flag_parses(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            rc, output = self._cli([
                "--dry-run", "--json", "--csv-path", csv_path,
                "--mechanism-family-decision",
                "46=bank_regulatory_capital_relief",
            ])
        finally:
            os.unlink(csv_path)
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_malformed_decision_flag_surfaces_error(self) -> None:
        csv_path = _write_csv([])
        try:
            rc, output = self._cli([
                "--dry-run", "--json", "--csv-path", csv_path,
                "--mechanism-family-decision", "no-equals-sign",
            ])
        finally:
            os.unlink(csv_path)
        parsed = json.loads(output)
        self.assertIs(parsed["ok"], False)


# ---------------------------------------------------------------------------
# Manual-aware clean-cohort adjustment — mirror of the medium-batch
# smoke surface.  The full smoke runs the joint apply + backfill +
# reports and must surface the same operator-aware view so an operator
# reading the full smoke gets identical adjusted_after_clean_fully_ready
# / remaining_contamination_reasons fields.
# ---------------------------------------------------------------------------


def _excluded_example(
    *, event_id: int, flags: list[str],
    primary_ticker: str = "XOM", event_date: str = "2026-04-08",
    headline: str = "h", mechanism_family: str | None = "supply_shock",
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "flags":            list(flags),
    }


class TestOperatorExcludedEventIdsFull(unittest.TestCase):
    def test_dry_run_populates_operator_excluded_event_ids(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=20, exclude_reason="off-topic"),
            _csv_row(event_id=5,  exclude_reason="off-topic"),
            _csv_row(event_id=12, proposed_primary_ticker="XOM"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["operator_excluded_event_ids"], [5, 20])


class TestAdjustedCleanCohortFull(unittest.TestCase):
    def _build(
        self, csv_rows: list[dict], after_payload: dict,
    ) -> dict:
        backup = _make_temp_db("full_adj", seed_events=[
            {"id": int(r["event_id"]), "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'}
            for r in csv_rows
        ])
        csv_path = _write_csv(csv_rows)
        try:
            patches = _patch_seams(
                after_payload=after_payload,
                fetch_rows=[_spy_row("2026-03-01"), _spy_row("2026-04-10")],
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        return result

    def test_duplicate_only_flag_enters_adjusted_clean(self) -> None:
        result = self._build(
            csv_rows=[
                _csv_row(event_id=60, proposed_primary_ticker="XOM"),
                _csv_row(event_id=153, exclude_reason="off-topic"),
            ],
            after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(event_id=60,
                                      flags=["duplicate_date_ticker"]),
                ],
            },
        )
        self.assertEqual(result["raw_after_clean_fully_ready"], 0)
        self.assertEqual(result["adjusted_after_clean_fully_ready"], 1)
        self.assertEqual(result["adjusted_clean_fully_ready_delta"], 1)
        self.assertEqual(result["remaining_contamination_reasons"], {})

    def test_multi_flag_stays_in_remaining(self) -> None:
        result = self._build(
            csv_rows=[
                _csv_row(event_id=60, proposed_primary_ticker="XOM"),
            ],
            after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(
                        event_id=60,
                        flags=["duplicate_date_ticker", "mechanism_family_none"],
                    ),
                ],
            },
        )
        self.assertEqual(result["adjusted_after_clean_fully_ready"], 0)
        self.assertEqual(
            result["remaining_contamination_reasons"],
            {"60": ["duplicate_date_ticker", "mechanism_family_none"]},
        )

    def test_dry_run_count_fields_null_remaining_empty_dict(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=60, proposed_primary_ticker="XOM"),
            _csv_row(event_id=153, exclude_reason="off-topic"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIsNone(result["raw_after_clean_fully_ready"])
        self.assertIsNone(result["adjusted_after_clean_fully_ready"])
        self.assertIsNone(result["adjusted_clean_fully_ready_delta"])
        self.assertEqual(result["remaining_contamination_reasons"], {})
        self.assertEqual(result["operator_excluded_event_ids"], [153])


if __name__ == "__main__":
    unittest.main()
