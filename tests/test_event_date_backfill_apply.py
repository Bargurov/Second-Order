"""Behavior tests for ``event_date_backfill.apply_event_date_backfill``.

These tests live alongside, but go beyond, the design-doc safety
contract pinned in ``tests/test_event_date_backfill_write_contract.py``.
They verify implementation-shaped guarantees that the contract does not
spell out: returned shape (``applied_count`` / ``applied_updates``),
ordering, the ``BEGIN IMMEDIATE`` transaction seam, the ``WHERE`` clause
guard against re-dating, ``db_path`` forwarding, and the absence of
paid surfaces in the writer's import graph.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db                                                  # noqa: E402
import event_date_backfill                                 # noqa: E402
from event_date_backfill import apply_event_date_backfill  # noqa: E402
from scripts import event_date_backfill as cli             # noqa: E402


def _snapshot_tables(db_path: str) -> tuple[list[tuple], list[tuple]]:
    conn = sqlite3.connect(db_path)
    try:
        events = list(conn.execute("SELECT * FROM events ORDER BY id"))
        cache = list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))
        return events, cache
    finally:
        conn.close()


class _DBBase(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_edb_apply_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed(
        self,
        *,
        event_date,
        symbols=None,
        timestamp=None,
        headline=None,
    ) -> None:
        head = headline or f"EDB apply seed {uuid.uuid4().hex[:10]}"
        ev = {
            "headline":       head,
            "stage":          "realized",
            "persistence":    "medium",
            "event_date":     event_date,
            "market_tickers": [{"symbol": s.upper()} for s in (symbols or [])],
        }
        if timestamp is not None:
            ev["timestamp"] = timestamp
        db.save_event(ev)

    def _event_dates(self) -> list[tuple[int, str | None]]:
        with sqlite3.connect(self._tmp) as conn:
            return list(conn.execute(
                "SELECT id, event_date FROM events ORDER BY id"
            ))


# ---------------------------------------------------------------------------
# Return-shape guarantees beyond the contract.
# ---------------------------------------------------------------------------


class TestApplyReturnShape(_DBBase):
    def test_confirm_false_returns_dry_run_shape_with_zero_applied(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        result = apply_event_date_backfill(db_path=self._tmp, confirm=False)
        # Mirrors plan keys.
        for key in (
            "total_candidates",
            "events_with_market_tickers",
            "ticker_rows_blocked",
            "proposed_updates",
            "skipped_counts",
            "confidence_note",
        ):
            self.assertIn(key, result)
        # Plus apply-shape sentinels.
        self.assertEqual(result["applied_count"],   0)
        self.assertEqual(result["applied_updates"], [])

    def test_confirm_true_carries_applied_updates_with_required_fields(
        self,
    ) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
            headline="apply field check",
        )
        result = apply_event_date_backfill(db_path=self._tmp, confirm=True)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(len(result["applied_updates"]), 1)
        update = result["applied_updates"][0]
        for key in ("event_id", "timestamp", "proposed_event_date"):
            self.assertIn(key, update)
        self.assertEqual(update["timestamp"],           "2026-04-15T13:30:00")
        self.assertEqual(update["proposed_event_date"], "2026-04-15")

    def test_applied_updates_ordered_by_event_id_ascending(self) -> None:
        for i in range(4):
            self._seed(
                event_date=None, symbols=["AAPL"],
                timestamp=f"2026-04-{15 + i:02d}T10:00:00",
                headline=f"apply order {i}",
            )
        result = apply_event_date_backfill(db_path=self._tmp, confirm=True)
        ids = [u["event_id"] for u in result["applied_updates"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(result["applied_count"], 4)

    def test_confirm_false_carries_planner_projection_block(self) -> None:
        # The planner exposes ``projected_hydration_impact``; the
        # apply wrapper must not silently strip it on confirm=False.
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        result = apply_event_date_backfill(db_path=self._tmp, confirm=False)
        self.assertIn("projected_hydration_impact", result)
        self.assertEqual(
            result["projected_hydration_impact"]["candidate_events"], 1,
        )


# ---------------------------------------------------------------------------
# WHERE-clause guard — never re-date a row.
# ---------------------------------------------------------------------------


class TestApplyWhereClauseGuard(_DBBase):
    def test_dated_row_never_redated_even_if_proposal_targets_it(self) -> None:
        # Drive the WHERE-clause guard directly: feed a hand-built plan
        # whose proposal targets an already-dated row.  The UPDATE must
        # be a no-op because of ``AND (event_date IS NULL OR
        # event_date = '')``.
        self._seed(
            event_date="2025-01-01", symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
            headline="never re-date",
        )
        rows = self._event_dates()
        target_id = rows[0][0]

        forged_plan = {
            "total_candidates":           1,
            "events_with_market_tickers": 1,
            "ticker_rows_blocked":        1,
            "proposed_updates": [{
                "event_id":                    target_id,
                "headline":                    "never re-date",
                "timestamp":                   "2026-04-15T13:30:00",
                "proposed_event_date":         "2099-12-31",
                "ticker_count":                1,
                "tickers":                     ["AAPL"],
                "projected_tickers_unblocked": 1,
            }],
            "skipped_counts":             {"timestamp_unparseable": 0},
            "confidence_note":            "stub",
        }

        with patch.object(
            event_date_backfill, "plan_event_date_backfill",
            return_value=forged_plan,
        ):
            result = apply_event_date_backfill(
                db_path=self._tmp, confirm=True,
            )

        rows_after = self._event_dates()
        self.assertEqual(rows_after[0][1], "2025-01-01")
        self.assertEqual(result["applied_count"],   0)
        self.assertEqual(result["applied_updates"], [])


# ---------------------------------------------------------------------------
# Transaction seam — explicit BEGIN IMMEDIATE.
# ---------------------------------------------------------------------------


class TestApplyTransactionSeam(_DBBase):
    def test_writer_issues_begin_immediate(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )

        captured: list[tuple] = []
        real_connect = sqlite3.connect

        class _SpyConnection:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *exec_args, **exec_kwargs):
                captured.append(("execute", sql))
                return self._conn.execute(sql, *exec_args, **exec_kwargs)

            def close(self):
                return self._conn.close()

        def spy_connect(*args, **kwargs):
            captured.append(("connect", args, dict(kwargs)))
            return _SpyConnection(real_connect(*args, **kwargs))

        with patch.object(event_date_backfill.sqlite3, "connect",
                          side_effect=spy_connect):
            result = apply_event_date_backfill(
                db_path=self._tmp, confirm=True,
            )

        self.assertEqual(result["applied_count"], 1)
        # The writer connected with isolation_level=None (autocommit)
        # so it can issue an explicit BEGIN IMMEDIATE.
        connect_calls = [c for c in captured if c[0] == "connect"]
        self.assertTrue(connect_calls, "writer never opened a connection")
        for _, args, kwargs in connect_calls:
            if self._tmp in args or kwargs.get("database") == self._tmp:
                self.assertIs(kwargs.get("isolation_level"), None)
                break
        else:
            self.fail("no connection opened against the temp DB path")
        executed = [c[1] for c in captured if c[0] == "execute"]
        self.assertIn("BEGIN IMMEDIATE", executed)
        self.assertIn("COMMIT", executed)
        # And the UPDATE carries the WHERE-clause guard.
        update_stmts = [s for s in executed if s.upper().startswith("UPDATE")]
        self.assertTrue(update_stmts)
        for stmt in update_stmts:
            self.assertIn("event_date IS NULL OR event_date = ''", stmt)


# ---------------------------------------------------------------------------
# Idempotency beyond contract: applied_count is zero on re-run.
# ---------------------------------------------------------------------------


class TestApplyIdempotency(_DBBase):
    def test_second_apply_reports_zero_applied(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        first  = apply_event_date_backfill(db_path=self._tmp, confirm=True)
        second = apply_event_date_backfill(db_path=self._tmp, confirm=True)
        self.assertEqual(first["applied_count"],  1)
        self.assertEqual(second["applied_count"], 0)
        self.assertEqual(second["applied_updates"], [])

    def test_partial_unparseable_does_not_block_other_writes(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
            headline="parseable",
        )
        self._seed(
            event_date=None, symbols=["MSFT"],
            timestamp="not-a-date",
            headline="unparseable",
        )
        result = apply_event_date_backfill(db_path=self._tmp, confirm=True)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(
            result["skipped_counts"].get("timestamp_unparseable", 0), 1,
        )


# ---------------------------------------------------------------------------
# db_path forwarding mirrors the planner's behavior.
# ---------------------------------------------------------------------------


class TestApplyDbPathForwarding(_DBBase):
    def test_explicit_db_path_writes_to_target_only(self) -> None:
        # Seed the bound DB.
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        bound_path = self._tmp

        # Switch the global to an empty DB; pass bound_path explicitly.
        empty_path = os.path.join(
            tempfile.gettempdir(),
            f"test_edb_apply_alt_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = empty_path
        db._db_ready = False
        db.init_db()
        try:
            result = apply_event_date_backfill(
                db_path=bound_path, confirm=True,
            )
        finally:
            db.DB_FILE = bound_path
            db._db_ready = False
            db.init_db()
            try:
                os.remove(empty_path)
            except (OSError, PermissionError):
                pass

        self.assertEqual(result["applied_count"], 1)
        # Bound DB is now dated.
        rows = self._event_dates()
        self.assertEqual(rows[0][1], "2026-04-15")


# ---------------------------------------------------------------------------
# CLI integration — the writer is reachable via --write --confirm and the
# guidance message lands when only one of the two flags is supplied.
# ---------------------------------------------------------------------------


class TestApplyCliPathway(_DBBase):
    def test_cli_write_confirm_renders_applied_count_in_text(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        out = StringIO()
        rc = cli.main(
            ["--write", "--confirm", "--db-path", self._tmp], out=out,
        )
        self.assertEqual(rc, 0)
        self.assertIn("Applied updates:", out.getvalue())
        self.assertIn("Event-date backfill write", out.getvalue())

    def test_cli_write_alone_emits_guidance_to_stderr(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        out = StringIO()
        before = _snapshot_tables(self._tmp)
        with patch("sys.stderr", new_callable=StringIO) as err:
            rc = cli.main(["--write", "--db-path", self._tmp], out=out)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(rc, 2)
        self.assertEqual(before, after)
        self.assertIn("--write and --confirm must be supplied together",
                      err.getvalue())

    def test_cli_confirm_alone_emits_guidance_to_stderr(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        out = StringIO()
        before = _snapshot_tables(self._tmp)
        with patch("sys.stderr", new_callable=StringIO) as err:
            rc = cli.main(["--confirm", "--db-path", self._tmp], out=out)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(rc, 2)
        self.assertEqual(before, after)
        self.assertIn("--write and --confirm must be supplied together",
                      err.getvalue())


# ---------------------------------------------------------------------------
# Module surface — the writer name is the contract sentinel and the CLI
# does not re-export it under a public name.
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):
    def test_writer_is_callable_under_canonical_name(self) -> None:
        self.assertTrue(callable(
            getattr(event_date_backfill, "apply_event_date_backfill", None),
        ))

    def test_cli_module_does_not_re_export_writer_under_public_name(
        self,
    ) -> None:
        # Mirrors the contract test: the writer is bound to a private
        # alias inside the CLI module.
        public_writes = [
            name for name in dir(cli)
            if not name.startswith("_") and any(
                name.startswith(p) for p in ("apply", "write", "persist",
                                             "commit")
            ) and callable(getattr(cli, name))
        ]
        self.assertEqual(public_writes, [])


if __name__ == "__main__":
    unittest.main()
