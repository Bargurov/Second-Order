"""Tests for ``scripts/benchmark_cache_backfill_write_smoke.py``.

Pin the write-safety contract:

* Default mode is ``dry-run`` — no writes, no temp copy, no provider
  call.
* Write mode requires ALL of ``--write --confirm --backup-path``;
  any missing flag → fail closed with no copy / no fetch / no write.
* ``--backup-path`` equal to ``--db-path`` is rejected — catastrophic
  config error.  ``--backup-path`` that does not exist is rejected.
* Provider unavailable → fail closed BEFORE copying.  No temp file
  is created on the unavailable path.
* Live events.db SHA-256 is byte-identical before/after every smoke
  run (real file, real hash).
* Input backup SHA-256 is byte-identical before/after every smoke
  run (real file, real hash).
* Output dict carries EXACTLY the 11 brief-mandated keys:
  ``ok, mode, backup_path, temp_copy_path, rows_planned,
  rows_written, live_db_unchanged, input_backup_unchanged,
  readiness_delta, errors, warnings`` — no additive fields.
* ``readiness_delta`` is a 6-key dict on the fully successful write
  path (``before/after_fully_ready``, ``fully_ready_delta``,
  ``before/after_missing_benchmark_proxy``,
  ``missing_benchmark_proxy_delta``) and ``None`` on every other
  path (dry-run, flag rejection, provider unavailable, zero planned,
  fetch failure, write failure, readiness report failure).
* ``rows_planned`` from the preflight seam (``estimated_rows_needed``)
  is an upper bound; ``rows_written`` is the actual count after the
  temp INSERT and may legitimately be lower (holidays, dedup).
* Default run does not import yfinance / market_check / market_data /
  price_cache / api / routes.* / fastapi.
* Three module-level seams are patchable: ``_run_preflight``,
  ``_check_provider_available``, ``_fetch_spy_rows``.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import benchmark_cache_backfill_write_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "mode",
    "backup_path",
    "temp_copy_path",
    "rows_planned",
    "rows_written",
    "live_db_unchanged",
    "input_backup_unchanged",
    "readiness_delta",
    "errors",
    "warnings",
)

_READINESS_DELTA_KEYS = (
    "before_fully_ready",
    "after_fully_ready",
    "fully_ready_delta",
    "before_missing_benchmark_proxy",
    "after_missing_benchmark_proxy",
    "missing_benchmark_proxy_delta",
)


# ---------------------------------------------------------------------------
# Real on-disk fixture: a tiny SQLite DB with the project's price_cache
# schema, plus a separate "backup" file.  Hand-rolled (no ``db.init_db``)
# so the fixture is decoupled from production migrations and pins the
# byte-level safety claim directly.
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

_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT
)
""".strip()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_temp_db(suffix: str = "smoke_db") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_PRICE_CACHE_DDL)
        conn.commit()
    finally:
        conn.close()
    return path


def _spy_row(date_iso: str, *, close: float = 100.0,
             volume: float = 5_000_000.0) -> dict:
    return {"date": date_iso, "close": close, "volume": volume}


def _preflight_payload(
    *, blocked: int = 0, start: str | None = None, end: str | None = None,
    rows_needed: int = 0, calls: int = 0, cache_max: str | None = None,
) -> dict:
    return {
        "benchmark_symbol":        "SPY",
        "blocked_event_count":     blocked,
        "required_start_date":     start,
        "required_end_date":       end,
        "current_cache_max_date":  cache_max,
        "estimated_rows_needed":   rows_needed,
        "provider_calls_required": calls,
        "recommended_next_action": "synthetic",
    }


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _patch_seams(
    *,
    plan: dict,
    provider_available: bool = True,
    fetch_rows: list[dict] | None = None,
    fetch_side_effect: Exception | None = None,
):
    fetch_rows = fetch_rows if fetch_rows is not None else []
    if fetch_side_effect is not None:
        fetch_patch = patch.object(cli, "_fetch_spy_rows",
                                   side_effect=fetch_side_effect)
    else:
        fetch_patch = patch.object(cli, "_fetch_spy_rows",
                                   return_value=fetch_rows)
    return (
        patch.object(cli, "_run_preflight", return_value=plan),
        patch.object(cli, "_check_provider_available",
                     return_value=provider_available),
        fetch_patch,
    )


def _run(
    *,
    plan: dict | None = None,
    provider_available: bool = True,
    fetch_rows: list[dict] | None = None,
    fetch_side_effect: Exception | None = None,
    **kwargs,
) -> dict:
    plan = plan if plan is not None else _preflight_payload()
    p1, p2, p3 = _patch_seams(
        plan=plan,
        provider_available=provider_available,
        fetch_rows=fetch_rows,
        fetch_side_effect=fetch_side_effect,
    )
    with p1, p2, p3:
        return cli.smoke_backfill_write(**kwargs)


def _run_cli(
    argv: list[str],
    *,
    plan: dict | None = None,
    provider_available: bool = True,
    fetch_rows: list[dict] | None = None,
    fetch_side_effect: Exception | None = None,
) -> tuple[int, str]:
    plan = plan if plan is not None else _preflight_payload()
    out = StringIO()
    p1, p2, p3 = _patch_seams(
        plan=plan,
        provider_available=provider_available,
        fetch_rows=fetch_rows,
        fetch_side_effect=fetch_side_effect,
    )
    with p1, p2, p3:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Output contract — exactly 10 keys
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_returns_dict_with_exactly_11_keys(self) -> None:
        result = _run()
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))

    def test_no_additive_fields(self) -> None:
        # Run a few scenarios — none should introduce extra keys.
        scenarios = [
            {},  # default dry-run, no paths
            {"plan": _preflight_payload(rows_needed=21,
                                        start="2026-05-08",
                                        end="2026-06-05")},
        ]
        for kwargs in scenarios:
            result = _run(**kwargs)
            self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS),
                             f"unexpected keys for scenario {kwargs!r}")


# ---------------------------------------------------------------------------
# Default dry-run behavior
# ---------------------------------------------------------------------------


class TestDryRunDefault(unittest.TestCase):
    def test_default_mode_is_dry_run(self) -> None:
        result = _run()
        self.assertEqual(result["mode"], "dry-run")
        self.assertIs(result["ok"], True)

    def test_dry_run_creates_no_temp_copy(self) -> None:
        result = _run()
        self.assertIsNone(result["temp_copy_path"])

    def test_dry_run_rows_written_zero(self) -> None:
        result = _run(plan=_preflight_payload(
            rows_needed=21, start="2026-05-08", end="2026-06-05"))
        self.assertEqual(result["rows_written"], 0)

    def test_dry_run_rows_planned_from_preflight(self) -> None:
        result = _run(plan=_preflight_payload(
            rows_needed=42, start="2026-05-08", end="2026-06-05"))
        self.assertEqual(result["rows_planned"], 42)

    def test_dry_run_does_not_call_provider(self) -> None:
        with patch.object(cli, "_run_preflight",
                          return_value=_preflight_payload(rows_needed=21,
                                                          start="2026-05-08",
                                                          end="2026-06-05")):
            with patch.object(cli, "_fetch_spy_rows") as fetch:
                with patch.object(cli, "_check_provider_available",
                                  return_value=True) as check:
                    cli.smoke_backfill_write()
        self.assertFalse(
            fetch.called, "_fetch_spy_rows must not be invoked in dry-run")
        self.assertFalse(
            check.called,
            "_check_provider_available must not be invoked in dry-run",
        )


# ---------------------------------------------------------------------------
# Write-mode flag validation
# ---------------------------------------------------------------------------


class TestWriteFlagValidation(unittest.TestCase):
    def test_write_without_confirm_rejected(self) -> None:
        result = _run(write=True, confirm=False, backup_path="/tmp/x.db")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["mode"], "write")
        self.assertEqual(result["rows_written"], 0)
        self.assertIsNone(result["temp_copy_path"])
        self.assertTrue(any("--confirm" in e for e in result["errors"]))

    def test_write_without_backup_path_rejected(self) -> None:
        result = _run(write=True, confirm=True, backup_path=None)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("--backup-path" in e for e in result["errors"]))

    def test_backup_path_equals_db_path_rejected(self) -> None:
        live = _make_temp_db("smoke_live")
        try:
            result = _run(
                write=True, confirm=True,
                db_path=live, backup_path=live,
            )
            self.assertIs(result["ok"], False)
            self.assertTrue(
                any("differ" in e.lower() or "same" in e.lower()
                    for e in result["errors"]),
                f"errors don't mention path equality: {result['errors']!r}",
            )
            self.assertIsNone(result["temp_copy_path"])
        finally:
            os.unlink(live)

    def test_backup_path_nonexistent_rejected(self) -> None:
        bogus = os.path.join(tempfile.gettempdir(),
                             f"nonexistent_{uuid.uuid4().hex}.db")
        result = _run(
            write=True, confirm=True, backup_path=bogus,
        )
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("does not exist" in e.lower() for e in result["errors"]),
            f"errors don't mention missing backup: {result['errors']!r}",
        )


# ---------------------------------------------------------------------------
# Provider fail-closed
# ---------------------------------------------------------------------------


class TestProviderFailClosed(unittest.TestCase):
    def test_provider_unavailable_no_temp_no_write(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            result = _run(
                provider_available=False,
                plan=_preflight_payload(rows_needed=21,
                                        start="2026-05-08",
                                        end="2026-06-05"),
                write=True, confirm=True, backup_path=backup,
            )
            self.assertIs(result["ok"], False)
            self.assertEqual(result["rows_written"], 0)
            self.assertIsNone(
                result["temp_copy_path"],
                "temp copy must not be created when provider unavailable",
            )
            self.assertTrue(
                any("provider" in e.lower() for e in result["errors"]),
                f"no provider error: {result['errors']!r}",
            )
        finally:
            os.unlink(backup)

    def test_provider_fetch_raises_no_partial_write(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            result = _run(
                provider_available=True,
                fetch_side_effect=RuntimeError("synthetic network error"),
                plan=_preflight_payload(rows_needed=21,
                                        start="2026-05-08",
                                        end="2026-06-05"),
                write=True, confirm=True, backup_path=backup,
            )
            self.assertIs(result["ok"], False)
            self.assertEqual(result["rows_written"], 0)
            self.assertTrue(
                any("synthetic network error" in e for e in result["errors"]),
                f"errors: {result['errors']!r}",
            )
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Hash invariants — real files, real SHA-256
# ---------------------------------------------------------------------------


class TestHashInvariantsRealFile(unittest.TestCase):
    def test_dry_run_leaves_live_db_byte_identical(self) -> None:
        live = _make_temp_db("smoke_live")
        before = _sha256(live)
        try:
            result = _run(db_path=live)
            after = _sha256(live)
        finally:
            os.unlink(live)
        self.assertEqual(before, after,
                         "live DB bytes changed during dry-run smoke")
        self.assertIs(result["live_db_unchanged"], True)

    def test_dry_run_leaves_input_backup_byte_identical(self) -> None:
        backup = _make_temp_db("smoke_backup")
        before = _sha256(backup)
        try:
            result = _run(backup_path=backup)
            after = _sha256(backup)
        finally:
            os.unlink(backup)
        self.assertEqual(before, after,
                         "input backup bytes changed during dry-run smoke")
        self.assertIs(result["input_backup_unchanged"], True)

    def test_write_mode_leaves_live_db_byte_identical(self) -> None:
        live = _make_temp_db("smoke_live")
        backup = _make_temp_db("smoke_backup")
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            result = _run(
                plan=_preflight_payload(rows_needed=2,
                                        start="2026-05-08",
                                        end="2026-05-11"),
                fetch_rows=[
                    _spy_row("2026-05-08"),
                    _spy_row("2026-05-11"),
                ],
                db_path=live, backup_path=backup,
                write=True, confirm=True,
            )
            live_after = _sha256(live)
            backup_after = _sha256(backup)
        finally:
            os.unlink(live)
            os.unlink(backup)
            tcp = result.get("temp_copy_path")
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        # Safety claim: NEITHER the live DB NOR the input backup bytes
        # change during a write-mode smoke.  The temp copy is the only
        # file that gains rows.
        self.assertEqual(live_before, live_after,
                         "LIVE DB BYTES CHANGED — safety claim broken")
        self.assertEqual(backup_before, backup_after,
                         "INPUT BACKUP BYTES CHANGED — safety claim broken")
        self.assertIs(result["live_db_unchanged"],     True)
        self.assertIs(result["input_backup_unchanged"], True)
        self.assertEqual(result["rows_written"], 2)
        self.assertIs(result["ok"], True)


# ---------------------------------------------------------------------------
# Temp copy actually carries the new SPY rows
# ---------------------------------------------------------------------------


class TestTempCopyCarriesRows(unittest.TestCase):
    def test_temp_copy_has_inserted_spy_rows(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            result = _run(
                plan=_preflight_payload(rows_needed=2,
                                        start="2026-05-08",
                                        end="2026-05-11"),
                fetch_rows=[
                    _spy_row("2026-05-08"),
                    _spy_row("2026-05-11"),
                ],
                backup_path=backup, write=True, confirm=True,
            )
            self.assertIs(result["ok"], True)
            self.assertEqual(result["rows_written"], 2)
            tcp = result["temp_copy_path"]
            self.assertIsNotNone(tcp)
            self.assertTrue(os.path.exists(tcp))
            try:
                conn = sqlite3.connect(tcp)
                rows = conn.execute(
                    "SELECT date FROM price_cache WHERE ticker = 'SPY' "
                    "ORDER BY date"
                ).fetchall()
                conn.close()
                self.assertEqual([r[0] for r in rows],
                                 ["2026-05-08", "2026-05-11"])
            finally:
                if os.path.exists(tcp):
                    os.unlink(tcp)
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# rows_planned == 0 short-circuits
# ---------------------------------------------------------------------------


class TestZeroPlannedShortCircuit(unittest.TestCase):
    def test_zero_planned_skips_provider_call(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            with patch.object(cli, "_run_preflight",
                              return_value=_preflight_payload(rows_needed=0)):
                with patch.object(cli, "_check_provider_available",
                                  return_value=True) as check:
                    with patch.object(cli, "_fetch_spy_rows") as fetch:
                        result = cli.smoke_backfill_write(
                            backup_path=backup, write=True, confirm=True,
                        )
            self.assertIs(result["ok"], True)
            self.assertEqual(result["rows_planned"],  0)
            self.assertEqual(result["rows_written"],  0)
            self.assertFalse(fetch.called,
                             "must not call provider when rows_planned == 0")
            # check_provider_available may or may not be called before
            # the short-circuit — both are acceptable; the key rule is
            # that no fetch / no copy happens.
            del check
            self.assertIsNone(
                result["temp_copy_path"],
                "no temp copy when there is nothing to write",
            )
        finally:
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Preflight wiring
# ---------------------------------------------------------------------------


class TestPreflightWiring(unittest.TestCase):
    def test_preflight_called_with_backup_path_in_write_mode(self) -> None:
        backup = _make_temp_db("smoke_backup")
        captured: dict = {}

        def fake_preflight(*, db_path):
            captured["db_path"] = db_path
            return _preflight_payload(rows_needed=0)

        try:
            with patch.object(cli, "_run_preflight",
                              side_effect=fake_preflight):
                with patch.object(cli, "_check_provider_available",
                                  return_value=True):
                    cli.smoke_backfill_write(
                        backup_path=backup, write=True, confirm=True,
                    )
        finally:
            os.unlink(backup)
        # Plan source = write source — preflight reads the backup, not
        # the live DB.
        self.assertEqual(captured.get("db_path"), backup)


# ---------------------------------------------------------------------------
# Provider isolation — default run must not touch yfinance / FastAPI
# ---------------------------------------------------------------------------


class TestProviderImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance",
        "market_check",
        "market_data",
        "price_cache",
        "api",
        "fastapi",
    )

    def test_default_dry_run_does_not_import_provider_or_fastapi(
        self,
    ) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        # Run un-patched dry-run against an empty temp DB.
        live = _make_temp_db("smoke_live_iso")
        try:
            cli.smoke_backfill_write(db_path=live)
        finally:
            os.unlink(live)
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(
            after - before, set(),
            "default dry-run imported a forbidden module",
        )


# ---------------------------------------------------------------------------
# Seam patchability — sanity check that all four seams exist as
# module attributes and can be replaced via patch.object.
# ---------------------------------------------------------------------------


class TestSeamPatchability(unittest.TestCase):
    def test_run_preflight_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_preflight")))

    def test_check_provider_available_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_check_provider_available")))

    def test_fetch_spy_rows_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_spy_rows")))

    def test_run_readiness_report_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_readiness_report")))


# ---------------------------------------------------------------------------
# Readiness delta — present on success, None on every other path
# ---------------------------------------------------------------------------


class TestReadinessDeltaNullPaths(unittest.TestCase):
    """Every path that does NOT complete a write must surface
    ``readiness_delta=None`` — dry-run, flag rejection, provider
    unavailable, zero planned, fetch failure, write failure.
    """

    def test_dry_run_readiness_delta_is_null(self) -> None:
        result = _run()
        self.assertIn("readiness_delta", result)
        self.assertIsNone(result["readiness_delta"])

    def test_dry_run_does_not_call_readiness_report(self) -> None:
        with patch.object(cli, "_run_readiness_report") as readiness:
            with patch.object(cli, "_run_preflight",
                              return_value=_preflight_payload(
                                  rows_needed=21,
                                  start="2026-05-08", end="2026-06-05")):
                cli.smoke_backfill_write()
        self.assertFalse(
            readiness.called,
            "_run_readiness_report must not be invoked in dry-run",
        )

    def test_write_without_confirm_readiness_delta_is_null(self) -> None:
        result = _run(write=True, confirm=False, backup_path="/tmp/x.db")
        self.assertIsNone(result["readiness_delta"])

    def test_write_without_backup_path_readiness_delta_is_null(self) -> None:
        result = _run(write=True, confirm=True, backup_path=None)
        self.assertIsNone(result["readiness_delta"])

    def test_provider_unavailable_readiness_delta_is_null(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            result = _run(
                provider_available=False,
                plan=_preflight_payload(rows_needed=21,
                                        start="2026-05-08",
                                        end="2026-06-05"),
                write=True, confirm=True, backup_path=backup,
            )
        finally:
            os.unlink(backup)
        self.assertIsNone(result["readiness_delta"])

    def test_zero_planned_readiness_delta_is_null(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            with patch.object(cli, "_run_preflight",
                              return_value=_preflight_payload(rows_needed=0)):
                with patch.object(cli, "_check_provider_available",
                                  return_value=True):
                    with patch.object(cli, "_fetch_spy_rows"):
                        result = cli.smoke_backfill_write(
                            backup_path=backup,
                            write=True, confirm=True,
                        )
        finally:
            os.unlink(backup)
        self.assertIsNone(result["readiness_delta"])

    def test_fetch_failure_readiness_delta_is_null(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            result = _run(
                fetch_side_effect=RuntimeError("synthetic fetch failure"),
                plan=_preflight_payload(rows_needed=2,
                                        start="2026-05-08",
                                        end="2026-05-11"),
                write=True, confirm=True, backup_path=backup,
            )
        finally:
            os.unlink(backup)
            tcp = result.get("temp_copy_path")
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertIsNone(result["readiness_delta"])


class TestReadinessDeltaSuccess(unittest.TestCase):
    """The fully successful write path must surface a 6-key
    ``readiness_delta`` dict measuring fully_ready and missing
    benchmark proxy counts before vs after the temp-copy write.
    """

    def test_success_path_readiness_delta_is_six_key_dict(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            result = _run(
                plan=_preflight_payload(rows_needed=2,
                                        start="2026-05-08",
                                        end="2026-05-11"),
                fetch_rows=[
                    _spy_row("2026-05-08"),
                    _spy_row("2026-05-11"),
                ],
                backup_path=backup, write=True, confirm=True,
            )
        finally:
            os.unlink(backup)
            tcp = result.get("temp_copy_path")
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertIs(result["ok"], True)
        self.assertIsInstance(result["readiness_delta"], dict)
        self.assertEqual(set(result["readiness_delta"].keys()),
                         set(_READINESS_DELTA_KEYS))
        # Every value must be an int (not a numpy/None scalar).
        for k in _READINESS_DELTA_KEYS:
            self.assertIsInstance(result["readiness_delta"][k], int,
                                  f"{k} must be int")

    def test_readiness_delta_called_with_backup_then_temp(self) -> None:
        """Pin the source-of-truth: ``before`` reads the input backup,
        ``after`` reads the temp copy.  Order matters — temp is the
        post-write file.
        """
        backup = _make_temp_db("smoke_backup")
        captured: list[str] = []

        def fake_readiness(*, db_path):
            captured.append(db_path)
            # Return distinct counts so we can verify ordering.
            if db_path == backup:
                return {"events_fully_ready": 3,
                        "events_missing_benchmark_proxy": 7}
            return {"events_fully_ready": 5,
                    "events_missing_benchmark_proxy": 4}

        try:
            with patch.object(cli, "_run_preflight",
                              return_value=_preflight_payload(
                                  rows_needed=1,
                                  start="2026-05-08", end="2026-05-08")):
                with patch.object(cli, "_check_provider_available",
                                  return_value=True):
                    with patch.object(cli, "_fetch_spy_rows",
                                      return_value=[_spy_row("2026-05-08")]):
                        with patch.object(cli, "_run_readiness_report",
                                          side_effect=fake_readiness):
                            result = cli.smoke_backfill_write(
                                backup_path=backup,
                                write=True, confirm=True,
                            )
        finally:
            os.unlink(backup)
            tcp = result.get("temp_copy_path")
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        # First call must be the backup, second call must be the temp.
        self.assertEqual(len(captured), 2,
                         f"expected 2 readiness calls, got {captured!r}")
        self.assertEqual(captured[0], backup)
        self.assertEqual(captured[1], result["temp_copy_path"])
        delta = result["readiness_delta"]
        self.assertEqual(delta["before_fully_ready"],             3)
        self.assertEqual(delta["after_fully_ready"],              5)
        self.assertEqual(delta["fully_ready_delta"],              2)
        self.assertEqual(delta["before_missing_benchmark_proxy"], 7)
        self.assertEqual(delta["after_missing_benchmark_proxy"],  4)
        self.assertEqual(delta["missing_benchmark_proxy_delta"], -3)

    def test_readiness_delta_reflects_real_spy_writes(self) -> None:
        """End-to-end: write SPY rows that complete coverage for an
        event lacking only the SPY benchmark, run real readiness
        against backup vs temp, observe the delta.
        """
        backup = _make_temp_db("smoke_backup")
        # Seed an event whose primary ticker has full coverage but the
        # SPY benchmark is missing — backfilling SPY should flip its
        # benchmark_proxy_available to True.
        conn = sqlite3.connect(backup)
        try:
            conn.execute(
                "INSERT INTO events (id, headline, event_date, market_tickers) "
                "VALUES (?, ?, ?, ?)",
                (1, "h", "2026-04-01",
                 '[{"symbol": "AAPL"}]'),
            )
            # 70 distinct dates strictly before event_date for AAPL
            # plus a 20-business-day-forward row.
            from datetime import date as _date, timedelta as _td
            base = _date(2025, 12, 1)
            now_iso = "2026-01-01T00:00:00+00:00"
            for i in range(70):
                d = (base + _td(days=i)).isoformat()
                conn.execute(
                    "INSERT OR IGNORE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("AAPL", d, 100.0, 1.0, 1, now_iso),
                )
            # forward 1d / 5d / 20d rows for AAPL after 2026-04-01
            for d in ["2026-04-02", "2026-04-08", "2026-04-30"]:
                conn.execute(
                    "INSERT OR IGNORE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("AAPL", d, 100.0, 1.0, 1, now_iso),
                )
            conn.commit()
        finally:
            conn.close()
        try:
            result = _run(
                plan=_preflight_payload(rows_needed=1,
                                        start="2026-04-30",
                                        end="2026-04-30"),
                fetch_rows=[_spy_row("2026-04-30")],
                backup_path=backup, write=True, confirm=True,
            )
        finally:
            os.unlink(backup)
            tcp = result.get("temp_copy_path")
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertIs(result["ok"], True)
        delta = result["readiness_delta"]
        # Before the SPY write the benchmark proxy was missing for
        # the seeded event; after the write it should be present, so
        # missing count drops by 1 and fully_ready rises by 1.
        self.assertEqual(delta["before_missing_benchmark_proxy"], 1)
        self.assertEqual(delta["after_missing_benchmark_proxy"],  0)
        self.assertEqual(delta["missing_benchmark_proxy_delta"], -1)
        self.assertEqual(delta["before_fully_ready"], 0)
        self.assertEqual(delta["after_fully_ready"],  1)
        self.assertEqual(delta["fully_ready_delta"],  1)


class TestReadinessFailureFailsClosed(unittest.TestCase):
    """If readiness raises, the run must fail closed (ok=False, error
    surfaced, readiness_delta=None) — but the live DB and input backup
    safety claim (byte-identical) must STILL be verified by hash.
    """

    def test_readiness_failure_logs_error_and_nulls_delta(self) -> None:
        backup = _make_temp_db("smoke_backup")
        try:
            with patch.object(cli, "_run_preflight",
                              return_value=_preflight_payload(
                                  rows_needed=1,
                                  start="2026-05-08", end="2026-05-08")):
                with patch.object(cli, "_check_provider_available",
                                  return_value=True):
                    with patch.object(cli, "_fetch_spy_rows",
                                      return_value=[_spy_row("2026-05-08")]):
                        with patch.object(
                            cli, "_run_readiness_report",
                            side_effect=RuntimeError(
                                "synthetic readiness failure"),
                        ):
                            result = cli.smoke_backfill_write(
                                backup_path=backup,
                                write=True, confirm=True,
                            )
        finally:
            os.unlink(backup)
            tcp = result.get("temp_copy_path")
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertIs(result["ok"], False)
        self.assertIsNone(result["readiness_delta"])
        self.assertTrue(
            any("readiness" in e.lower() for e in result["errors"]),
            f"errors don't mention readiness: {result['errors']!r}",
        )

    def test_readiness_failure_still_verifies_safety_hashes(self) -> None:
        live = _make_temp_db("smoke_live")
        backup = _make_temp_db("smoke_backup")
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            with patch.object(cli, "_run_preflight",
                              return_value=_preflight_payload(
                                  rows_needed=1,
                                  start="2026-05-08", end="2026-05-08")):
                with patch.object(cli, "_check_provider_available",
                                  return_value=True):
                    with patch.object(cli, "_fetch_spy_rows",
                                      return_value=[_spy_row("2026-05-08")]):
                        with patch.object(
                            cli, "_run_readiness_report",
                            side_effect=RuntimeError(
                                "synthetic readiness failure"),
                        ):
                            result = cli.smoke_backfill_write(
                                db_path=live, backup_path=backup,
                                write=True, confirm=True,
                            )
            live_after = _sha256(live)
            backup_after = _sha256(backup)
        finally:
            os.unlink(live)
            os.unlink(backup)
            tcp = result.get("temp_copy_path")
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        # Safety claim survives readiness failure.
        self.assertEqual(live_before, live_after,
                         "LIVE DB BYTES CHANGED while readiness failed")
        self.assertEqual(backup_before, backup_after,
                         "INPUT BACKUP BYTES CHANGED while readiness failed")
        self.assertIs(result["live_db_unchanged"],     True)
        self.assertIs(result["input_backup_unchanged"], True)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_dry_run_default_emits_parseable_json(self) -> None:
        rc, output = _run_cli(["--dry-run", "--json", "--limit", "50"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_no_flag_defaults_to_dry_run(self) -> None:
        rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_write_without_confirm_fails(self) -> None:
        rc, output = _run_cli([
            "--write", "--backup-path", "/tmp/some.db", "--json",
        ])
        # CLI should still exit 0 (well-formed report); ok=False inside.
        parsed = json.loads(output)
        self.assertEqual(parsed["mode"], "write")
        self.assertIs(parsed["ok"], False)

    def test_write_confirm_without_backup_path_fails(self) -> None:
        rc, output = _run_cli([
            "--write", "--confirm", "--json",
        ])
        parsed = json.loads(output)
        self.assertIs(parsed["ok"], False)

    def test_limit_arg_accepted(self) -> None:
        rc, _ = _run_cli(["--dry-run", "--json", "--limit", "50"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
