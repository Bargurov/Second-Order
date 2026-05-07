"""Contract tests for ``event_date_backfill`` write mode.

Status — write mode is live
---------------------------
The dry-run planner (``plan_event_date_backfill``), the writer
(``apply_event_date_backfill``), and the CLI's ``--write --confirm``
gate ship.  This file pins the safety contract from
``docs/event_date_backfill_write_design.md``.

What this file pins
-------------------
* ``TestWriteModeAbsent`` — invariants that must hold even now that
  write mode is implemented: ``--apply`` is rejected as a typo guard,
  the CLI module exposes no public write helper (the apply function
  is bound under a leading-underscore alias).
* ``TestWriteContract``   — full safety contract.  Each test maps to
  a numbered rule in the design doc.

History
-------
Earlier revisions of this file carried four ``CURRENT-STATE GUARD``
tests pinning the absence of write mode (no apply on the module, the
CLI rejecting ``--write`` / ``--confirm`` / ``--write --confirm``).
Those guards were flipped in the same patch that landed write mode;
their future-behavior replacements live in ``TestWriteContract``
(``test_cli_write_alone_is_refused``,
``test_cli_confirm_alone_is_refused``,
``test_cli_write_confirm_runs_apply``) and the apply-shape test in
``tests/test_event_date_backfill_apply.py``.
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

import db                                                 # noqa: E402
import event_date_backfill                                # noqa: E402
from scripts import event_date_backfill as cli            # noqa: E402


# ---------------------------------------------------------------------------
# Sentinel — does write mode exist yet?
# ---------------------------------------------------------------------------

_APPLY_FN_NAME = "apply_event_date_backfill"
_APPLY_FN = getattr(event_date_backfill, _APPLY_FN_NAME, None)
_HAS_WRITE_MODE = callable(_APPLY_FN)
_SKIP_REASON = (
    "Write mode not implemented yet; see "
    "docs/event_date_backfill_write_design.md.  Add "
    f"event_date_backfill.{_APPLY_FN_NAME} to activate this contract."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Isolated SQLite DB per test.  Mirrors the pattern in
    ``tests/test_event_date_backfill.py`` so seed/snapshot semantics
    line up with the dry-run planner tests."""

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_edb_write_{uuid.uuid4().hex}.db",
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
        head = headline or f"EDB write seed {uuid.uuid4().hex[:10]}"
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
# Current-state guards — assert write mode is absent or refused.
# ---------------------------------------------------------------------------


_WRITE_FN_PREFIXES = ("apply", "write", "persist", "commit")


def _public_write_callables(module) -> list[str]:
    return [
        name for name in dir(module)
        if not name.startswith("_")
        and any(name.startswith(p) for p in _WRITE_FN_PREFIXES)
        and callable(getattr(module, name))
    ]


class TestWriteModeAbsent(unittest.TestCase):
    """Pin the invariants that must hold even now that write mode is
    live: ``--apply`` is rejected as a typo guard, and the CLI module
    exposes no public write callable (the apply function is bound under
    a leading-underscore alias)."""

    def test_cli_module_exposes_no_write_helper(self) -> None:
        write_attrs = _public_write_callables(cli)
        self.assertEqual(
            write_attrs, [],
            "CLI module must not expose a public write helper; "
            "the apply function must be imported under a leading-"
            f"underscore alias.  Found: {write_attrs}",
        )

    def _expect_argparse_exit(self, argv: list[str]) -> None:
        out = StringIO()
        with patch("sys.stderr", new_callable=StringIO):
            with self.assertRaises(SystemExit) as cm:
                cli.main(argv, out=out)
        self.assertEqual(cm.exception.code, 2)

    def test_cli_rejects_apply_flag(self) -> None:
        # ``--apply`` is a permanent rejection.  The contract picks
        # ``--write --confirm``; ``--apply`` is reserved as a typo
        # guard so a future operator cannot accidentally trigger
        # writes by typing the wrong flag.
        self._expect_argparse_exit(["--apply"])


# ---------------------------------------------------------------------------
# Future-behavior contract — auto-activated when write mode lands.
# Each test maps to a numbered rule in
# docs/event_date_backfill_write_design.md.
# ---------------------------------------------------------------------------


@unittest.skipUnless(_HAS_WRITE_MODE, _SKIP_REASON)
class TestWriteContract(_DBBase):

    # Rule 1 — both --write and --confirm required ----------------------

    def test_apply_without_confirm_writes_nothing(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        before = _snapshot_tables(self._tmp)
        result = _APPLY_FN(db_path=self._tmp, confirm=False)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "apply(confirm=False) must not write — see Rule 1",
        )
        self.assertEqual(result.get("applied_count", 0), 0)

    def test_cli_write_alone_is_refused(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        before = _snapshot_tables(self._tmp)
        out = StringIO()
        try:
            rc = cli.main(["--write", "--db-path", self._tmp], out=out)
        except SystemExit as exc:
            rc = exc.code
        after = _snapshot_tables(self._tmp)
        self.assertNotEqual(rc, 0, "plain --write must exit non-zero")
        self.assertEqual(before, after, "plain --write must not write")

    def test_cli_confirm_alone_is_refused(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        before = _snapshot_tables(self._tmp)
        out = StringIO()
        try:
            rc = cli.main(["--confirm", "--db-path", self._tmp], out=out)
        except SystemExit as exc:
            rc = exc.code
        after = _snapshot_tables(self._tmp)
        self.assertNotEqual(rc, 0, "plain --confirm must exit non-zero")
        self.assertEqual(before, after, "plain --confirm must not write")

    # Rules 3, 4 — only NULL/empty rows touched; value = timestamp[:10] -

    def test_apply_with_confirm_sets_event_date_from_timestamp_prefix(
        self,
    ) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
            headline="ts-prefix one",
        )
        self._seed(
            event_date="", symbols=["MSFT"],
            timestamp="2026-04-16T09:00:00",
            headline="ts-prefix two",
        )
        result = _APPLY_FN(db_path=self._tmp, confirm=True)
        rows = self._event_dates()
        dates = {r[1] for r in rows}
        self.assertEqual(
            dates, {"2026-04-15", "2026-04-16"},
            "Rule 4 — event_date must equal timestamp[:10]",
        )
        self.assertEqual(result.get("applied_count", 0), 2)

    def test_apply_only_touches_null_or_empty_event_date_rows(self) -> None:
        self._seed(
            event_date="2025-01-01", symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
            headline="already dated",
        )
        self._seed(
            event_date=None, symbols=["MSFT"],
            timestamp="2026-04-16T09:00:00",
            headline="needs date",
        )
        _APPLY_FN(db_path=self._tmp, confirm=True)
        rows = self._event_dates()
        dates = {r[1] for r in rows}
        self.assertIn(
            "2025-01-01", dates,
            "Rule 3 — pre-dated row must keep its event_date verbatim",
        )
        self.assertIn(
            "2026-04-16", dates,
            "Rule 4 — undated row must be backfilled from timestamp[:10]",
        )

    # Rule 5 — malformed timestamps are skipped, not coerced -----------

    def test_apply_skips_malformed_timestamp(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="not-a-date",
            headline="malformed ts",
        )
        result = _APPLY_FN(db_path=self._tmp, confirm=True)
        rows = self._event_dates()
        self.assertEqual(len(rows), 1)
        self.assertIn(
            rows[0][1], (None, ""),
            "Rule 5 — malformed-timestamp row must remain undated",
        )
        skipped = result.get("skipped_counts") or {}
        self.assertGreaterEqual(
            skipped.get("timestamp_unparseable", 0), 1,
            "Rule 5 — malformed timestamp must surface in skipped_counts",
        )
        self.assertEqual(result.get("applied_count", 0), 0)

    # Rule 6 — idempotent rerun ----------------------------------------

    def test_apply_is_idempotent(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        self._seed(
            event_date=None, symbols=["MSFT"],
            timestamp="not-a-date",
        )
        _APPLY_FN(db_path=self._tmp, confirm=True)
        first  = _snapshot_tables(self._tmp)
        _APPLY_FN(db_path=self._tmp, confirm=True)
        second = _snapshot_tables(self._tmp)
        _APPLY_FN(db_path=self._tmp, confirm=True)
        third  = _snapshot_tables(self._tmp)
        self.assertEqual(
            first, second,
            "Rule 6 — second apply must be byte-identical to first",
        )
        self.assertEqual(
            second, third,
            "Rule 6 — third apply must be byte-identical to second",
        )

    # Rule 7 — no provider/yfinance/LLM seams --------------------------

    def test_apply_does_not_call_provider_yfinance_or_llm(self) -> None:
        from contextlib import ExitStack

        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("price_cache",  "_purge_corrupt_rows"),
            ("price_cache",  "_ensure_table"),
        )
        with ExitStack() as stack:
            for module_name, attr in candidate_seams:
                try:
                    mod = __import__(module_name)
                except Exception:
                    continue
                if not hasattr(mod, attr):
                    continue
                stack.enter_context(patch.object(
                    mod, attr,
                    side_effect=AssertionError(
                        f"{_APPLY_FN_NAME} must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        f"{_APPLY_FN_NAME} must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            _APPLY_FN(db_path=self._tmp, confirm=True)

        # Sanity: the writer ran for real, not via a fallback.
        rows = self._event_dates()
        self.assertEqual(
            rows[0][1], "2026-04-15",
            "writer must persist event_date even when paid seams are "
            "patched (proves the paid surfaces were never needed)",
        )

    def test_cli_write_confirm_runs_apply(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        out = StringIO()
        try:
            rc = cli.main(
                ["--write", "--confirm", "--db-path", self._tmp], out=out,
            )
        except SystemExit as exc:
            rc = exc.code
        self.assertEqual(rc, 0, "CLI --write --confirm must exit 0")
        rows = self._event_dates()
        self.assertEqual(
            rows[0][1], "2026-04-15",
            "CLI --write --confirm must persist event_date via the writer",
        )

    # Rule 8 — no FastAPI route surface for writes ---------------------

    def test_cli_does_not_expose_fastapi_app_or_router(self) -> None:
        self.assertFalse(
            hasattr(cli, "app"),
            "Rule 8 — CLI must not host a FastAPI app",
        )
        self.assertFalse(
            hasattr(cli, "router"),
            "Rule 8 — CLI must not host a FastAPI router",
        )


if __name__ == "__main__":
    unittest.main()
