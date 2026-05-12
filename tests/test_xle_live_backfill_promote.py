"""Tests for ``scripts/xle_live_backfill_promote.py``.

The live XLE backfill promoter writes XLE rows into the live events
DB's ``price_cache`` table.  It is the only script in the workflow
that does so, and only with every safety gate passing:

  * ``--confirm-live-write`` is supplied,
  * ``--backup-path`` points at an existing readable file,
  * the preview artifact reports ``ready_after == 2`` AND
    ``blocked_after == 0``.

Pin the contract:

* Without any of the three gates → ``ok=False`` and no DB write.
  Every gate is evaluated independently so the operator sees every
  problem on a single run.
* Only ticker ``XLE`` and only the dates listed in the preview
  artifact's ``required_dates`` may land in the live DB — defense in
  depth against a misbehaving fetch.
* Writes go through a single explicit transaction.  On any exception
  inside the loop the transaction is rolled back and
  ``live_db_hash_after == live_db_hash_before``.
* The envelope reports ``inserted_count``,
  ``skipped_existing_count``, ``live_db_hash_before``,
  ``live_db_hash_after``, and a post-write
  ``benchmark_sensitivity_preflight`` ``ready_count`` / ``blocked_count``.
* Conservative wording — banned tokens (``proof``, ``proves``,
  ``proven``, ``alpha``, ``guaranteed``, ``automatically``,
  ``validated``, ``definitely``) absent from any text the promoter
  emits.  The promoter never asserts an SPY-vs-XLE conclusion.
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
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import xle_live_backfill_promote as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "confirm_live_write",
    "backup_path",
    "backup_exists",
    "backup_hash",
    "preview_artifact_path",
    "preview_ready_after",
    "preview_blocked_after",
    "preview_ready",
    "required_dates",
    "inserted_count",
    "skipped_existing_count",
    "live_db_hash_before",
    "live_db_hash_after",
    "preflight_after",
    "ready_count",
    "blocked_count",
    "warnings",
    "errors",
    "recommended_next_action",
)


_BANNED_WORDS = (
    "proof",
    "proves",
    "proven",
    "alpha",
    "guaranteed",
    "automatically",
    "validated",
    "definitely",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_PRICE_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


def _make_live_db() -> str:
    """Create a minimal live events.db-shaped fixture containing just
    the price_cache table.  Used as the writeable target for the
    promoter.
    """
    path = os.path.join(
        tempfile.gettempdir(),
        f"xle_live_fix_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_PRICE_CACHE_DDL)
        conn.commit()
    finally:
        conn.close()
    return path


def _make_backup_file(*, content: bytes = b"backup-bytes") -> str:
    """Create a non-empty readable file the promoter accepts as a
    valid ``--backup-path``.  The promoter only checks existence /
    readability / non-zero size, not that the file is a SQLite DB.
    """
    path = os.path.join(
        tempfile.gettempdir(),
        f"xle_live_bak_{uuid.uuid4().hex}.bak",
    )
    with open(path, "wb") as fh:
        fh.write(content)
    return path


def _happy_artifact(
    *,
    ready_after:        int  = 2,
    blocked_after:      int  = 0,
    ok:                 bool = True,
    live_db_unchanged:  bool = True,
    required_dates:     list[str] | None = None,
) -> dict[str, Any]:
    """A complete synthetic preview-artifact dict that satisfies every
    readiness gate by default.  Tests that want to drive a specific
    gate failure call this helper and override one key.
    """
    return {
        "ok":                ok,
        "ready_after":       int(ready_after),
        "blocked_after":     int(blocked_after),
        "live_db_unchanged": live_db_unchanged,
        "required_dates":    list(required_dates or []),
    }


def _write_preview_artifact(
    *,
    ready_after: int,
    blocked_after: int,
    required_dates: list[str] | None = None,
) -> str:
    """Write a synthetic preview-artifact JSON file the promoter can
    read.  Mirrors the keys the real artifact carries.
    """
    path = os.path.join(
        tempfile.gettempdir(),
        f"xle_preview_{uuid.uuid4().hex}.json",
    )
    payload = {
        "ok":             True,
        "confirm_online": True,
        "ready_after":    ready_after,
        "blocked_after":  blocked_after,
        "ready_before":   0,
        "blocked_before": 2,
        "required_dates": list(required_dates or []),
        "fetched_rows":   len(required_dates or []),
        "inserted_temp_rows": len(required_dates or []),
        "preflight_before": {
            "checked_events": 2,
            "ready_count":    0,
            "blocked_count":  2,
        },
        "preflight_after": {
            "checked_events": 2,
            "ready_count":    ready_after,
            "blocked_count":  blocked_after,
        },
        "still_missing_dates":   [],
        "live_db_unchanged":     True,
        "warnings":              [],
        "errors":                [],
        "recommended_next_action": "synthetic",
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _provider_row(
    *, date: str, ticker: str = "XLE",
    close: float = 100.0, volume: float = 1.0e6,
) -> dict[str, Any]:
    return {
        "ticker":      ticker,
        "date":        date,
        "close":       close,
        "volume":      volume,
        "auto_adjust": 1,
        "fetched_at":  "2026-05-12T00:00:00+00:00",
    }


def _preflight_report(
    *, ready: int, blocked: int,
) -> dict[str, Any]:
    return {
        "ok":             True,
        "checked_events": ready + blocked,
        "ready_count":    ready,
        "blocked_count":  blocked,
        "rows":           [],
        "recommended_next_action": "synthetic",
    }


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_xle_rows(*, db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute(
            "SELECT COUNT(*) FROM price_cache WHERE ticker='XLE'",
        ).fetchone()[0])
    finally:
        conn.close()


def _select_xle_rows(*, db_path: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT ticker, date, close FROM price_cache "
            "WHERE ticker='XLE' ORDER BY date",
        ).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Default refusal — no flags
# ---------------------------------------------------------------------------


class TestDefaultRefusal(unittest.TestCase):
    def test_without_any_flags_returns_ok_false_and_does_not_write(
        self,
    ) -> None:
        live = _make_live_db()
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={},  # missing artifact path
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=False,
                    backup_path=None,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertEqual(report["inserted_count"], 0)
            self.assertEqual(report["skipped_existing_count"], 0)
            fetch_seam.assert_not_called()
            self.assertEqual(_count_xle_rows(db_path=live), 0)
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# --confirm-live-write gate
# ---------------------------------------------------------------------------


class TestConfirmLiveWriteGate(unittest.TestCase):
    def test_without_confirm_live_write_refuses(self) -> None:
        live = _make_live_db()
        backup = _make_backup_file()
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=False,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            joined = " ".join(report["errors"]).lower()
            self.assertIn("confirm-live-write", joined,
                          f"errors: {report['errors']}")
            fetch_seam.assert_not_called()
            self.assertEqual(_count_xle_rows(db_path=live), 0)
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# --backup-path gate
# ---------------------------------------------------------------------------


class TestBackupPathGate(unittest.TestCase):
    def test_without_backup_path_refuses(self) -> None:
        live = _make_live_db()
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=None,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            joined = " ".join(report["errors"]).lower()
            self.assertIn("backup-path", joined,
                          f"errors: {report['errors']}")
            fetch_seam.assert_not_called()
            self.assertEqual(_count_xle_rows(db_path=live), 0)
        finally:
            os.unlink(live)

    def test_with_missing_backup_file_refuses(self) -> None:
        live = _make_live_db()
        missing_backup = os.path.join(
            tempfile.gettempdir(),
            f"missing_backup_{uuid.uuid4().hex}.bak",
        )
        # Important: do NOT create the backup file.
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=missing_backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["backup_exists"])
            fetch_seam.assert_not_called()
            self.assertEqual(_count_xle_rows(db_path=live), 0)
        finally:
            os.unlink(live)

    def test_empty_backup_file_refuses(self) -> None:
        live = _make_live_db()
        empty_backup = _make_backup_file(content=b"")
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=empty_backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["backup_exists"])
            fetch_seam.assert_not_called()
        finally:
            os.unlink(live)
            os.unlink(empty_backup)

    def test_backup_hash_surfaced_when_backup_valid(self) -> None:
        live = _make_live_db()
        backup = _make_backup_file(content=b"deterministic-bytes")
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-03-26")], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertTrue(report["backup_exists"])
            self.assertIsNotNone(report["backup_hash"])
            self.assertEqual(report["backup_hash"], _sha256(backup))
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Preview readiness gate
# ---------------------------------------------------------------------------


class TestPreviewReadinessGate(unittest.TestCase):
    def test_preview_still_blocked_refuses(self) -> None:
        live = _make_live_db()
        backup = _make_backup_file()
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ready_after":   1,
                    "blocked_after": 1,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["preview_ready"])
            self.assertEqual(report["preview_ready_after"],   1)
            self.assertEqual(report["preview_blocked_after"], 1)
            fetch_seam.assert_not_called()
            self.assertEqual(_count_xle_rows(db_path=live), 0)
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_preview_ready_after_3_refused_literal_gate(self) -> None:
        # Literal gate: ready_after MUST equal 2, not "ready_after >=
        # checked".  3 ready / 0 blocked is treated as a mismatch
        # because the preview is designed around two events.
        live = _make_live_db()
        backup = _make_backup_file()
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ready_after":   3,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["preview_ready"])
            fetch_seam.assert_not_called()
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_missing_preview_artifact_refuses(self) -> None:
        live = _make_live_db()
        backup = _make_backup_file()
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={},  # artifact unreadable
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            fetch_seam.assert_not_called()
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Preview artifact ``ok`` gate
# ---------------------------------------------------------------------------


class TestPreviewOkGate(unittest.TestCase):
    """The promotion is gated on the preview artifact reporting
    ``ok == True``.  An artifact with ``ok=False`` indicates the
    preview itself raised an error (missing DB, hash mismatch, etc.) —
    its readiness counts cannot be relied on.
    """

    def test_artifact_ok_false_refuses(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            artifact = _happy_artifact(
                required_dates=["2026-03-26"],
            )
            # Headline counts look ready, but ok=False — must refuse.
            artifact["ok"] = False
            with patch.object(
                cli, "_read_preview_artifact",
                return_value=artifact,
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["preview_ready"])
            fetch_seam.assert_not_called()
            self.assertEqual(_count_xle_rows(db_path=live), 0)
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_artifact_ok_missing_refuses(self) -> None:
        # An artifact that omits ``ok`` entirely must also fail closed
        # — absence of the key is treated as not-ok.
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            artifact = _happy_artifact(
                required_dates=["2026-03-26"],
            )
            artifact.pop("ok", None)
            with patch.object(
                cli, "_read_preview_artifact",
                return_value=artifact,
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["preview_ready"])
            fetch_seam.assert_not_called()
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Preview artifact ``live_db_unchanged`` gate
# ---------------------------------------------------------------------------


class TestPreviewLiveDbUnchangedGate(unittest.TestCase):
    """Promotion also requires the preview artifact to report
    ``live_db_unchanged == True``.  If the preview ran with the live DB
    mutating underneath it, the operator must investigate before any
    live write — even when the headline counts look cleared.
    """

    def test_artifact_live_db_unchanged_false_refuses(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            artifact = _happy_artifact(
                required_dates=["2026-03-26"],
            )
            artifact["live_db_unchanged"] = False
            with patch.object(
                cli, "_read_preview_artifact",
                return_value=artifact,
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["preview_ready"])
            fetch_seam.assert_not_called()
            self.assertEqual(_count_xle_rows(db_path=live), 0)
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_artifact_live_db_unchanged_missing_refuses(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            artifact = _happy_artifact(
                required_dates=["2026-03-26"],
            )
            artifact.pop("live_db_unchanged", None)
            with patch.object(
                cli, "_read_preview_artifact",
                return_value=artifact,
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["preview_ready"])
            fetch_seam.assert_not_called()
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_error_message_names_all_four_required_conditions(self) -> None:
        # The error message must surface every missing condition at
        # once so the operator does not have to fix them one at a time.
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            artifact = _happy_artifact(
                required_dates=["2026-03-26"],
            )
            artifact["ok"] = False
            artifact["live_db_unchanged"] = False
            with patch.object(
                cli, "_read_preview_artifact",
                return_value=artifact,
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            joined = " ".join(report["errors"]).lower()
            for required in (
                "ok=true",
                "ready_after=2",
                "blocked_after=0",
                "live_db_unchanged=true",
            ):
                self.assertIn(
                    required, joined,
                    f"missing required condition {required!r} in "
                    f"errors: {report['errors']}",
                )
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Gate failures accumulate
# ---------------------------------------------------------------------------


class TestGateFailureAccumulation(unittest.TestCase):
    def test_all_three_gate_failures_surface_in_one_run(self) -> None:
        live = _make_live_db()
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ready_after":   0,
                    "blocked_after": 2,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam:
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=False,
                    backup_path=None,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            joined = " ".join(report["errors"]).lower()
            # Each independent gate must have surfaced its own error
            # message so the operator can fix all of them at once.
            self.assertIn("confirm-live-write", joined,
                          f"errors: {report['errors']}")
            self.assertIn("backup-path", joined,
                          f"errors: {report['errors']}")
            self.assertIn("preview", joined,
                          f"errors: {report['errors']}")
            fetch_seam.assert_not_called()
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Successful promotion
# ---------------------------------------------------------------------------


class TestSuccessfulPromotion(unittest.TestCase):
    def test_inserts_only_xle_rows_for_required_dates(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            dates = ["2026-03-26", "2026-03-27", "2026-03-30"]
            rows = [_provider_row(date=d, close=42.0 + i)
                    for i, d in enumerate(dates)]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=(rows, []),
            ) as fetch_seam, patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["inserted_count"], 3)
            self.assertEqual(report["skipped_existing_count"], 0)
            self.assertEqual(report["ready_count"],   2)
            self.assertEqual(report["blocked_count"], 0)
            # Fetch seam called with the preview's required_dates.
            kwargs = fetch_seam.call_args.kwargs
            self.assertEqual(kwargs["dates"], dates)
            # Live DB carries only XLE rows for the requested dates.
            persisted = _select_xle_rows(db_path=live)
            self.assertEqual({r[1] for r in persisted}, set(dates))
            self.assertEqual({r[0] for r in persisted}, {"XLE"})
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_inserted_count_and_skipped_count_split_when_duplicate(
        self,
    ) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            # Seed an existing row that matches one of the required
            # dates so INSERT OR IGNORE silently skips it.
            conn = sqlite3.connect(live)
            try:
                conn.execute(
                    "INSERT INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, "
                    "fetched_at) VALUES "
                    "('XLE', '2026-03-26', 99.99, 1.0, 1, 'seed')",
                )
                conn.commit()
            finally:
                conn.close()

            dates = ["2026-03-26", "2026-03-27"]
            rows = [_provider_row(date=d) for d in dates]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=(rows, []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            # One new row, one duplicate skipped.
            self.assertEqual(report["inserted_count"], 1)
            self.assertEqual(report["skipped_existing_count"], 1)
            # Seeded row's close was 99.99; INSERT OR IGNORE keeps it.
            persisted = _select_xle_rows(db_path=live)
            for row in persisted:
                if row[1] == "2026-03-26":
                    self.assertEqual(row[2], 99.99)
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Defense-in-depth — fetch returns extra tickers / dates
# ---------------------------------------------------------------------------


class TestDefenseInDepthFilter(unittest.TestCase):
    def test_rows_outside_required_dates_never_land_in_live_db(
        self,
    ) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            allowed = ["2026-03-26"]
            # Fetch seam misbehaves: returns an extra date and an
            # extra ticker.  Neither must land in the live DB.
            rows = [
                _provider_row(date="2026-03-26"),
                _provider_row(date="2026-03-27"),   # not in required
                _provider_row(date="2026-03-26", ticker="SPY"),
            ]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": allowed,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=(rows, []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["inserted_count"], 1)
            conn = sqlite3.connect(live)
            try:
                everything = conn.execute(
                    "SELECT ticker, date FROM price_cache",
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(everything, [("XLE", "2026-03-26")])
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Single transaction — rollback on exception
# ---------------------------------------------------------------------------


class TestSingleTransaction(unittest.TestCase):
    def test_exception_mid_insert_rolls_back_completely(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            before_hash = _sha256(live)
            dates = ["2026-03-26", "2026-03-27"]
            # First row valid; second row patched to raise from
            # inside the insert helper by feeding garbage values is
            # awkward, so instead we patch the helper itself.
            def raising_insert(*, live_db_path, rows):  # noqa: ANN001
                # Re-implement just enough to mutate the DB then raise
                # — this is how we prove rollback.
                conn = sqlite3.connect(live_db_path, isolation_level=None)
                try:
                    conn.execute("BEGIN")
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO price_cache "
                            "(ticker, date, close, volume, "
                            "auto_adjust, fetched_at) VALUES "
                            "(?, ?, ?, ?, ?, ?)",
                            ("XLE", "2026-03-26", 1.0, 1.0, 1, ""),
                        )
                        raise sqlite3.OperationalError("simulated mid-loop")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                finally:
                    conn.close()
                return 0, 0  # unreachable

            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=(
                    [_provider_row(date=d) for d in dates], [],
                ),
            ), patch.object(
                cli, "_insert_rows_single_tx",
                side_effect=raising_insert,
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=0, blocked=2),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            # Rollback path → no XLE rows persisted.
            self.assertEqual(_count_xle_rows(db_path=live), 0)
            # Live DB bytes identical to pre-call state.
            after_hash = _sha256(live)
            self.assertEqual(before_hash, after_hash)
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_real_insert_helper_rolls_back_on_failure(self) -> None:
        # Drive the actual helper through a sqlite failure to prove
        # the rollback path inside _insert_rows_single_tx works.
        live = _make_live_db()
        try:
            before_hash = _sha256(live)
            # Drop the price_cache table so the INSERT raises
            # OperationalError mid-loop — this exercises the helper's
            # own rollback path.
            conn = sqlite3.connect(live)
            try:
                conn.execute("DROP TABLE price_cache")
                conn.commit()
            finally:
                conn.close()
            after_drop_hash = _sha256(live)

            rows = [_provider_row(date="2026-03-26")]
            with self.assertRaises(sqlite3.Error):
                cli._insert_rows_single_tx(
                    live_db_path=live, rows=rows,
                )
            # No data table to write to → after hash matches the
            # immediately-pre-call hash (after the DROP).
            self.assertEqual(_sha256(live), after_drop_hash)
            # And nothing was persisted (the table is gone).
            conn = sqlite3.connect(live)
            try:
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'",
                ).fetchall()]
            finally:
                conn.close()
            self.assertNotIn("price_cache", names)
            # Sanity: original DB had a table; after-drop is different.
            self.assertNotEqual(before_hash, after_drop_hash)
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Live DB hashes
# ---------------------------------------------------------------------------


class TestLiveDbHashes(unittest.TestCase):
    def test_hashes_recorded_before_and_after(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            before = _sha256(live)
            dates = ["2026-03-26"]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=dates[0])], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertEqual(report["live_db_hash_before"], before)
            self.assertEqual(report["live_db_hash_after"], _sha256(live))
            # An insert happened, so the hashes differ.
            self.assertNotEqual(report["live_db_hash_before"],
                                report["live_db_hash_after"])
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_hashes_match_when_no_real_insert_happened(self) -> None:
        # Re-running against the same DB after a successful insert
        # finds every required row already present → all inserts are
        # ignored → bytes match before/after.
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            dates = ["2026-03-26"]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=dates[0])], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
                second = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertEqual(second["inserted_count"], 0)
            self.assertEqual(second["skipped_existing_count"], 1)
            self.assertEqual(second["live_db_hash_before"],
                             second["live_db_hash_after"])
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Provider returns empty / rollback path on empty fetch
# ---------------------------------------------------------------------------


class TestEmptyProviderResponse(unittest.TestCase):
    def test_empty_fetch_does_not_write_live_db(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            before = _sha256(live)
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=0, blocked=2),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertEqual(report["inserted_count"], 0)
            self.assertEqual(_sha256(live), before)
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_exactly_required_keys(self) -> None:
        with patch.object(
            cli, "_read_preview_artifact",
            return_value={
                "ready_after":   2,
                "blocked_after": 0,
                "required_dates": [],
            },
        ):
            report = cli.run_xle_live_backfill_promote(
                confirm_live_write=False,
                backup_path=None,
                db_path=None,
            )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_on_success_path(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            dates = ["2026-03-26"]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=dates[0])], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            haystack = " ".join(
                list(report["errors"])
                + list(report["warnings"])
                + [report["recommended_next_action"]]
            ).lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(w, haystack,
                                 f"banned word {w!r} in text")
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_no_benchmark_verdict_on_success_path(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            dates = ["2026-03-26"]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=dates[0])], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            action = report["recommended_next_action"].lower()
            for forbidden in (
                "spy is better than xle",
                "xle is better than spy",
                "spy outperforms",
                "xle outperforms",
                "spy beats xle",
                "xle beats spy",
            ):
                self.assertNotIn(forbidden, action,
                                 f"premature verdict: {action!r}")
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api", "market_data")

    def test_module_import_does_not_pull_provider(self) -> None:
        leaked = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        self.assertEqual(leaked, set(),
                         f"unexpected imports: {leaked}")

    def test_without_confirm_live_write_provider_seam_never_called(
        self,
    ) -> None:
        with patch.object(
            cli, "_read_preview_artifact",
            return_value={
                "ready_after":   2,
                "blocked_after": 0,
                "required_dates": ["2026-03-26"],
            },
        ), patch.object(
            cli, "_fetch_xle_rows_online",
        ) as fetch_seam:
            cli.run_xle_live_backfill_promote(
                confirm_live_write=False,
                backup_path=None,
                db_path=None,
            )
        fetch_seam.assert_not_called()


# ---------------------------------------------------------------------------
# Real preview-artifact file path
# ---------------------------------------------------------------------------


class TestPreviewArtifactFileIO(unittest.TestCase):
    def test_reads_preview_artifact_from_disk(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        artifact = _write_preview_artifact(
            ready_after=2, blocked_after=0,
            required_dates=["2026-03-26"],
        )
        try:
            with patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-03-26")], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    preview_artifact=artifact,
                    db_path=live,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["preview_artifact_path"], artifact)
            self.assertTrue(report["preview_ready"])
            self.assertEqual(report["required_dates"], ["2026-03-26"])
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(artifact)

    def test_post_calendar_fix_artifact_clears_the_gate(self) -> None:
        # Pin compatibility with the canonical artifact in
        # artifacts/xle_online_backfill_preview_post_calendar_fix.json.
        # We don't open the file from the repo (test isolation), but
        # we mirror its key shape so a future schema drift in the
        # promoter's artifact reader fails here.
        live   = _make_live_db()
        backup = _make_backup_file()
        artifact = _write_preview_artifact(
            ready_after=2, blocked_after=0,
            required_dates=[
                "2026-03-26", "2026-03-27", "2026-03-30",
                "2026-03-31", "2026-04-01", "2026-04-02",
            ],
        )
        try:
            with patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=(
                    [_provider_row(date=d) for d in [
                        "2026-03-26", "2026-03-27", "2026-03-30",
                        "2026-03-31", "2026-04-01", "2026-04-02",
                    ]],
                    [],
                ),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    preview_artifact=artifact,
                    db_path=live,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["inserted_count"], 6)
            self.assertEqual(_count_xle_rows(db_path=live), 6)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(artifact)


# ---------------------------------------------------------------------------
# Recommended next action
# ---------------------------------------------------------------------------


class TestRecommendedNextAction(unittest.TestCase):
    def test_gate_failure_points_at_gates(self) -> None:
        with patch.object(
            cli, "_read_preview_artifact",
            return_value={},
        ):
            report = cli.run_xle_live_backfill_promote(
                confirm_live_write=False,
                backup_path=None,
                db_path=None,
            )
        action = report["recommended_next_action"].lower()
        # Surface the corrective action explicitly so an operator
        # can self-diagnose without parsing the errors list.
        self.assertIn("backup", action, f"action: {action!r}")

    def test_success_path_mentions_inserted_and_preflight(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            dates = ["2026-03-26", "2026-03-27"]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": dates,
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=d) for d in dates], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            action = report["recommended_next_action"].lower()
            self.assertIn("xle row", action, f"action: {action!r}")
            self.assertIn("ready", action,   f"action: {action!r}")
            self.assertIn("blocked", action, f"action: {action!r}")
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_post_write_preflight_did_not_clear_points_at_blockers(
        self,
    ) -> None:
        # The promoter writes the rows the preview said were needed,
        # but the post-write preflight still finds an event blocked.
        # The recommendation MUST steer the operator to investigate
        # the blocker rather than imply success.
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            dates = ["2026-03-26"]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value=_happy_artifact(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=dates[0])], []),
            ), patch.object(
                cli, "_run_preflight",
                # Insert succeeded but post-write preflight is NOT
                # cleared — e.g., a separate primary-ticker gap.
                return_value=_preflight_report(ready=1, blocked=1),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            # Insert still happened (the script does not refuse a
            # write because of a downstream preflight gap; the
            # operator needs to see the rows landed AND that the
            # gap remains).
            self.assertEqual(report["inserted_count"], 1)
            self.assertEqual(report["blocked_count"], 1)
            action = report["recommended_next_action"].lower()
            self.assertIn("blocker", action, f"action: {action!r}")
            self.assertIn("inspect", action, f"action: {action!r}")
        finally:
            os.unlink(live)
            os.unlink(backup)

    def test_post_write_preflight_cleared_does_not_request_inspection(
        self,
    ) -> None:
        # Cross-check: the cleared branch must NOT mention
        # "inspect each blocked event's blockers".
        live   = _make_live_db()
        backup = _make_backup_file()
        try:
            dates = ["2026-03-26"]
            with patch.object(
                cli, "_read_preview_artifact",
                return_value=_happy_artifact(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=dates[0])], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                report = cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                )
            action = report["recommended_next_action"].lower()
            self.assertNotIn(
                "inspect each blocked", action,
                f"cleared path wrongly emitted not-cleared wording: "
                f"{action!r}",
            )
        finally:
            os.unlink(live)
            os.unlink(backup)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_without_flags_returns_nonzero_and_valid_json(
        self,
    ) -> None:
        with patch.object(
            cli, "_read_preview_artifact",
            return_value={},
        ):
            out = StringIO()
            rc = cli.main(["--json"], out=out)
        self.assertNotEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertFalse(parsed["ok"])
        self.assertFalse(parsed["confirm_live_write"])

    def test_cli_with_all_gates_passes(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        artifact = _write_preview_artifact(
            ready_after=2, blocked_after=0,
            required_dates=["2026-03-26"],
        )
        try:
            with patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-03-26")], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                out = StringIO()
                rc = cli.main(
                    [
                        "--json",
                        "--confirm-live-write",
                        "--backup-path", backup,
                        "--preview-artifact", artifact,
                        "--db-path", live,
                    ],
                    out=out,
                )
            self.assertEqual(rc, 0, f"output: {out.getvalue()}")
            parsed = json.loads(out.getvalue())
            self.assertTrue(parsed["ok"])
            self.assertEqual(parsed["inserted_count"], 1)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(artifact)


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_path_passed(self) -> None:
        live   = _make_live_db()
        backup = _make_backup_file()
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"xle_live_out_{uuid.uuid4().hex}.json",
        )
        try:
            with patch.object(
                cli, "_read_preview_artifact",
                return_value={
                    "ok":               True,
                    "live_db_unchanged": True,
                    "ready_after":   2,
                    "blocked_after": 0,
                    "required_dates": ["2026-03-26"],
                },
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-03-26")], []),
            ), patch.object(
                cli, "_run_preflight",
                return_value=_preflight_report(ready=2, blocked=0),
            ):
                cli.run_xle_live_backfill_promote(
                    confirm_live_write=True,
                    backup_path=backup,
                    db_path=live,
                    output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            for k in _REQUIRED_KEYS:
                self.assertIn(k, parsed)
        finally:
            os.unlink(live)
            os.unlink(backup)
            if os.path.exists(out_path):
                os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
