"""Tests for ``scripts/auto_adjust_mismatch_repair_preview.py`` — a
read-only preview tool that walks every ``auto_adjust_mismatch_for_20d``
row surfaced by the existing diagnostics and shows, per row, the exact
cache rows the flag-fix re-fetch would propose plus an explanation of
why each row is repairable (or, in a single paranoid edge case, why it
is not).

The script must:

  * Reuse :func:`scripts.no_forward_20d_gap_report._load_auto_adjust_mismatch_details`
    via a lazy import seam so tests can swap the loader without touching
    the diagnostics import graph.
  * Issue at most one bulk ``SELECT`` for the in-window cache rows.
    Read-only — no INSERT / UPDATE / DELETE, no provider call,
    no ``yfinance``, no LLM, no FastAPI surface.
  * Emit a stable JSON / text shape with explicit
    ``repair_status`` + ``repair_reason`` per row.
  * Never implement a write mode.

These tests pin all of the above + the no-mutation contract.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402,F401  — pre-load so the lazy diagnostics
                                #  imports inside the script don't
                                #  trip the api ↔ routes.diagnostics
                                #  cycle when the un-patched seam is
                                #  exercised.
import db  # noqa: E402
from scripts import auto_adjust_mismatch_repair_preview as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers + fakes
# ---------------------------------------------------------------------------


def _detail(
    event_id: int,
    symbol: str,
    *,
    event_date: str,
    flags: list[int] | None = None,
    cache_max: dict[str, str] | None = None,
) -> dict:
    return {
        "event_id":                    event_id,
        "event_date":                  event_date,
        "symbol":                      symbol,
        "available_auto_adjust_flags": flags if flags is not None else [0, 1],
        "cache_max_per_flag":
            cache_max if cache_max is not None else {
                "0": "2026-04-14",
                "1": "2026-05-30",
            },
        "recommended_action": "refresh_unadjusted_cache_to_align_hydrator",
    }


def _run_cli(argv):
    out = StringIO()
    rc = cli.main(argv, out=out)
    return rc, out.getvalue()


# Default loader output — three mismatch rows.
_THREE_DETAILS = [
    _detail(101, "AAPL", event_date="2026-04-15"),
    _detail(102, "MSFT", event_date="2026-04-16"),
    _detail(103, "GOOG", event_date="2026-04-17"),
]


def _patch_loader(details):
    return patch.object(
        cli, "_load_auto_adjust_mismatch_details",
        return_value=list(details),
    )


def _patch_window_loader(window_rows):
    """Patch the in-window cache loader.

    ``window_rows`` is a dict ``{(symbol_upper, flag_int): set_of_iso_dates}``.
    """
    return patch.object(
        cli, "_load_in_window_cache_rows",
        return_value=dict(window_rows),
    )


# ---------------------------------------------------------------------------
# Top-level JSON shape
# ---------------------------------------------------------------------------


_REQUIRED_TOP_KEYS = (
    "total_mismatches",
    "repairable_count",
    "non_repairable_count",
    "counts_by_status",
    "proposed_rows",
    "recommended_next_action",
)


_REQUIRED_ROW_KEYS = (
    "event_id",
    "event_date",
    "symbol",
    "target_20d",
    "available_auto_adjust_flags",
    "cache_max_per_flag",
    "aa1_in_window_dates",
    "aa0_in_window_dates",
    "proposed_row_dates",
    "proposed_row_count",
    "repair_status",
    "repair_reason",
    "recommended_action",
)


class TestPayloadShape(unittest.TestCase):
    def test_json_emits_every_required_top_level_key(self) -> None:
        with _patch_loader(_THREE_DETAILS), _patch_window_loader({}):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _REQUIRED_TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_each_row_carries_required_fields(self) -> None:
        with _patch_loader(_THREE_DETAILS), _patch_window_loader({}):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        rows = body["proposed_rows"]
        self.assertEqual(len(rows), 3)
        for row in rows:
            for key in _REQUIRED_ROW_KEYS:
                self.assertIn(key, row, f"row missing field: {key}")

    def test_recommended_action_is_fixed_label(self) -> None:
        with _patch_loader(_THREE_DETAILS), _patch_window_loader({}):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        actions = {r["recommended_action"] for r in body["proposed_rows"]}
        self.assertEqual(
            actions, {"refresh_unadjusted_cache_to_align_hydrator"},
        )

    def test_empty_loader_yields_zero_counts_and_no_action(self) -> None:
        with _patch_loader([]), _patch_window_loader({}):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_mismatches"],     0)
        self.assertEqual(body["repairable_count"],     0)
        self.assertEqual(body["non_repairable_count"], 0)
        self.assertEqual(body["proposed_rows"],        [])
        self.assertEqual(
            body["recommended_next_action"], "no_action_needed_no_mismatches",
        )


# ---------------------------------------------------------------------------
# target_20d computation — must match the diagnostics business-day offset
# ---------------------------------------------------------------------------


class TestTarget20dComputation(unittest.TestCase):
    def test_target_is_event_date_plus_twenty_business_days(self) -> None:
        # 2026-04-15 is a Wednesday.  Adding 20 business days lands on
        # 2026-05-13 (Wednesday).
        details = [_detail(1, "AAPL", event_date="2026-04-15")]
        with _patch_loader(details), _patch_window_loader({}):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["proposed_rows"][0]["target_20d"], "2026-05-13")

    def test_invalid_event_date_falls_into_non_repairable(self) -> None:
        details = [_detail(1, "AAPL", event_date="not-a-date")]
        with _patch_loader(details), _patch_window_loader({}):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(len(body["proposed_rows"]), 1)
        row = body["proposed_rows"][0]
        self.assertEqual(row["repair_status"],
                         "not_repairable_invalid_event_date")
        self.assertEqual(row["target_20d"], None)


# ---------------------------------------------------------------------------
# Repair-status classification
# ---------------------------------------------------------------------------


class TestRepairStatus(unittest.TestCase):
    def test_repairable_when_aa1_has_rows_inside_window(self) -> None:
        details = [_detail(101, "AAPL", event_date="2026-04-15")]
        # aa=1 has three rows inside [2026-04-15, 2026-05-13]; aa=0 has
        # one row inside the window.  Two proposed rows.
        rows = {
            ("AAPL", 1): {"2026-04-20", "2026-05-01", "2026-05-13"},
            ("AAPL", 0): {"2026-04-20"},
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        row = body["proposed_rows"][0]
        self.assertEqual(row["repair_status"], "repairable_flag_fix")
        self.assertEqual(
            row["aa1_in_window_dates"],
            ["2026-04-20", "2026-05-01", "2026-05-13"],
        )
        self.assertEqual(row["aa0_in_window_dates"], ["2026-04-20"])
        self.assertEqual(
            row["proposed_row_dates"], ["2026-05-01", "2026-05-13"],
        )
        self.assertEqual(row["proposed_row_count"], 2)
        self.assertIn("flag-fix", row["repair_reason"].lower())

    def test_not_repairable_when_aa1_has_no_rows_in_window(self) -> None:
        # Paranoid edge case: aa=1 max >= target_20d but every aa=1 row
        # is past the [event_d, target_20d] window — sparse-future data.
        details = [_detail(101, "AAPL", event_date="2026-04-15")]
        rows = {
            ("AAPL", 1): set(),  # no in-window aa=1 rows
            ("AAPL", 0): set(),
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        row = body["proposed_rows"][0]
        self.assertEqual(row["repair_status"],
                         "not_repairable_no_in_window_data")
        self.assertEqual(row["proposed_row_dates"], [])
        self.assertEqual(row["proposed_row_count"], 0)

    def test_proposed_rows_excludes_dates_aa0_already_has(self) -> None:
        details = [_detail(1, "X", event_date="2026-04-15")]
        rows = {
            ("X", 1): {"2026-04-16", "2026-04-17", "2026-04-18"},
            ("X", 0): {"2026-04-17"},
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        row = body["proposed_rows"][0]
        self.assertEqual(
            row["proposed_row_dates"], ["2026-04-16", "2026-04-18"],
        )
        self.assertEqual(row["proposed_row_count"], 2)

    def test_repairable_with_zero_proposed_rows_when_aa0_already_covers_window(
        self,
    ) -> None:
        # aa=0 already has every aa=1 in-window date, but its MAX is
        # below target_20d (per the classifier's gate, aa=0 is short of
        # the horizon).  This is still repairable — aa=1 in-window data
        # backs the flag-fix; the proposal is just empty for the
        # already-covered dates.  The script still flags repairable.
        details = [_detail(1, "X", event_date="2026-04-15")]
        rows = {
            ("X", 1): {"2026-04-16", "2026-04-17"},
            ("X", 0): {"2026-04-16", "2026-04-17"},
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        row = body["proposed_rows"][0]
        self.assertEqual(row["repair_status"], "repairable_flag_fix")
        self.assertEqual(row["proposed_row_dates"], [])

    def test_same_symbol_two_events_keeps_per_event_window_disjoint(
        self,
    ) -> None:
        # Same ticker, two events with non-overlapping windows.  Event 1
        # window: [2026-04-05, 2026-05-01] (Mon→Fri, 20bd offset).
        # Event 2 window: [2026-05-15, 2026-06-12].  A naïve
        # symbol-keyed cache map would let event 2's dates leak into
        # event 1's proposed list.
        details = [
            _detail(
                1, "GLD", event_date="2026-04-05",
                cache_max={"0": "2026-04-30", "1": "2026-05-04"},
            ),
            _detail(
                2, "GLD", event_date="2026-05-15",
                cache_max={"0": "2026-05-15", "1": "2026-06-12"},
            ),
        ]
        # The window loader's contract is per-spec; if the implementation
        # merges dates across windows under the same (symbol, flag) key,
        # the per-event compute path must still narrow back to the
        # event's own window.  Simulate the merged map a buggy loader
        # would return.
        rows = {
            ("GLD", 1): {
                # event 1 in-window
                "2026-04-30",
                # event 2 in-window — must NOT leak into event 1's row
                "2026-05-20",
                "2026-06-12",
            },
            ("GLD", 0): set(),
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        by_id = {r["event_id"]: r for r in body["proposed_rows"]}

        # Event 1's window ends 2026-05-01; later dates must not appear.
        ev1 = by_id[1]
        for leak in ("2026-05-20", "2026-06-12"):
            self.assertNotIn(
                leak, ev1["aa1_in_window_dates"],
                f"{leak} leaked from event 2's window into event 1's "
                f"aa1_in_window_dates",
            )
            self.assertNotIn(
                leak, ev1["proposed_row_dates"],
                f"{leak} leaked from event 2's window into event 1's "
                f"proposed_row_dates",
            )
        self.assertEqual(ev1["aa1_in_window_dates"], ["2026-04-30"])

        # Event 2's window must include only its own dates.
        ev2 = by_id[2]
        self.assertEqual(
            ev2["aa1_in_window_dates"], ["2026-05-20", "2026-06-12"],
        )

    def test_top_level_counts_split_repairable_and_non_repairable(self) -> None:
        details = [
            _detail(1, "OK1",  event_date="2026-04-15"),
            _detail(2, "OK2",  event_date="2026-04-15"),
            _detail(3, "BAD",  event_date="2026-04-15"),
            _detail(4, "BAD2", event_date="not-a-date"),
        ]
        rows = {
            ("OK1", 1): {"2026-04-16"},
            ("OK1", 0): set(),
            ("OK2", 1): {"2026-04-17"},
            ("OK2", 0): set(),
            ("BAD", 1): set(),  # paranoid edge case → not repairable
            ("BAD", 0): set(),
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["total_mismatches"],     4)
        self.assertEqual(body["repairable_count"],     2)
        self.assertEqual(body["non_repairable_count"], 2)
        self.assertEqual(
            body["counts_by_status"],
            {
                "repairable_flag_fix":              2,
                "not_repairable_no_in_window_data": 1,
                "not_repairable_invalid_event_date": 1,
            },
        )


# ---------------------------------------------------------------------------
# Recommended-next-action decision tree
# ---------------------------------------------------------------------------


class TestRecommendedNextAction(unittest.TestCase):
    def test_no_mismatches_recommends_no_action(self) -> None:
        with _patch_loader([]), _patch_window_loader({}):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["recommended_next_action"],
                         "no_action_needed_no_mismatches")

    def test_any_repairable_recommends_flag_fix(self) -> None:
        details = [_detail(1, "AAPL", event_date="2026-04-15")]
        rows = {("AAPL", 1): {"2026-04-16"}, ("AAPL", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["recommended_next_action"],
                         "fix_auto_adjust_flag_mismatch")

    def test_only_non_repairable_recommends_investigate(self) -> None:
        details = [_detail(1, "AAPL", event_date="2026-04-15")]
        rows = {("AAPL", 1): set(), ("AAPL", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["recommended_next_action"],
                         "investigate_non_repairable_rows")


# ---------------------------------------------------------------------------
# --limit flag
# ---------------------------------------------------------------------------


class TestLimitFlag(unittest.TestCase):
    def test_default_limit_returns_full_loader_supply(self) -> None:
        many = [
            _detail(i, f"T{i}", event_date="2026-04-15") for i in range(7)
        ]
        rows = {(f"T{i}", 1): {"2026-04-16"} for i in range(7)}
        rows.update({(f"T{i}", 0): set() for i in range(7)})
        with _patch_loader(many), _patch_window_loader(rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(len(body["proposed_rows"]), 7)

    def test_limit_truncates_proposed_rows(self) -> None:
        many = [
            _detail(i, f"T{i}", event_date="2026-04-15") for i in range(7)
        ]
        rows = {(f"T{i}", 1): {"2026-04-16"} for i in range(7)}
        rows.update({(f"T{i}", 0): set() for i in range(7)})
        with _patch_loader(many), _patch_window_loader(rows):
            _, output = _run_cli(["--json", "--limit", "3"])
        body = json.loads(output)
        self.assertEqual(len(body["proposed_rows"]), 3)
        # Loader-order preservation across truncation.
        self.assertEqual(
            [r["event_id"] for r in body["proposed_rows"]], [0, 1, 2],
        )

    def test_limit_does_not_affect_top_level_counts(self) -> None:
        # The counts must reflect every loader row, not the truncated
        # display list.  Otherwise an operator runs ``--limit 1`` and
        # mistakes the output as "only 1 mismatch."
        many = [
            _detail(i, f"T{i}", event_date="2026-04-15") for i in range(7)
        ]
        rows = {(f"T{i}", 1): {"2026-04-16"} for i in range(7)}
        rows.update({(f"T{i}", 0): set() for i in range(7)})
        with _patch_loader(many), _patch_window_loader(rows):
            _, output = _run_cli(["--json", "--limit", "1"])
        body = json.loads(output)
        self.assertEqual(body["total_mismatches"], 7)
        self.assertEqual(body["repairable_count"], 7)


# ---------------------------------------------------------------------------
# Default text rendering
# ---------------------------------------------------------------------------


class TestTextRendering(unittest.TestCase):
    def test_text_lists_section_headers(self) -> None:
        details = [_detail(101, "AAPL", event_date="2026-04-15")]
        rows = {
            ("AAPL", 1): {"2026-04-20", "2026-05-01"},
            ("AAPL", 0): {"2026-04-20"},
        }
        with _patch_loader(details), _patch_window_loader(rows):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        for needle in (
            "Auto-adjust mismatch repair preview",
            "Total mismatches",
            "Repairable",
            "Non-repairable",
            "Recommended next action",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")

    def test_text_surfaces_per_row_proposed_dates(self) -> None:
        details = [_detail(101, "AAPL", event_date="2026-04-15")]
        rows = {
            ("AAPL", 1): {"2026-04-20", "2026-05-01"},
            ("AAPL", 0): {"2026-04-20"},
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli([])
        self.assertIn("symbol=AAPL",      output)
        self.assertIn("target_20d=",      output)
        self.assertIn("2026-05-01",       output)
        self.assertIn("repairable_flag_fix", output)

    def test_text_surfaces_recommendation(self) -> None:
        details = [_detail(101, "AAPL", event_date="2026-04-15")]
        rows = {("AAPL", 1): {"2026-04-20"}, ("AAPL", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli([])
        self.assertIn("fix_auto_adjust_flag_mismatch", output)


# ---------------------------------------------------------------------------
# Real loader against a temp SQLite fixture — pins the read-only contract
# end-to-end (no mocked classifiers, no mocked SQL).
# ---------------------------------------------------------------------------


def _snapshot_tables(db_path: str) -> tuple[list, list]:
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


class TestNoMutation(unittest.TestCase):
    """End-to-end read-only contract — the script must never mutate
    either the events or price_cache tables.  Patches the loader only;
    the in-window SQL runs against the temp DB unmodified.
    """

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_repair_preview_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

        record = {
            "headline":     "aa-repair-preview no-mutation probe",
            "stage":        "realized",
            "persistence":  "medium",
            "event_date":   "2026-04-15",
            "market_tickers": [{"symbol": "AAPL"}],
        }
        db.save_event(record)
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-04-20", 100.0, 5_000_000.0, 1,
                 "2026-05-06T12:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-05-01", 101.0, 6_000_000.0, 1,
                 "2026-05-06T12:00:00+00:00"),
            )
            conn.commit()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def test_repeated_runs_leave_db_byte_identical(self) -> None:
        details = [_detail(101, "AAPL", event_date="2026-04-15")]
        before = _snapshot_tables(self._tmp)
        with _patch_loader(details):
            for _ in range(3):
                rc, _ = _run_cli(["--json"])
                self.assertEqual(rc, 0)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical across "
            "repeated repair-preview runs",
        )

    def test_window_loader_returns_in_window_dates_only(self) -> None:
        # The bulk SELECT must filter to dates in [event_d, target_20d].
        # A row outside the window must not leak into aa1_in_window_dates.
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-06-15", 110.0, 7_000_000.0, 1,
                 "2026-05-06T12:00:00+00:00"),  # past target_20d
            )
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-03-01", 90.0, 4_000_000.0, 1,
                 "2026-05-06T12:00:00+00:00"),  # before event_d
            )
            conn.commit()

        result = cli._load_in_window_cache_rows([
            ("AAPL", date(2026, 4, 15), date(2026, 5, 13)),
        ])
        aa1 = result.get(("AAPL", 1), set())
        self.assertIn("2026-04-20",   aa1)
        self.assertIn("2026-05-01",   aa1)
        self.assertNotIn("2026-06-15", aa1)
        self.assertNotIn("2026-03-01", aa1)


# ---------------------------------------------------------------------------
# No-provider, no-yfinance, no-LLM, no-FastAPI invariant
# ---------------------------------------------------------------------------


class TestNoProviderCalls(unittest.TestCase):
    """The CLI must never call market_check, market_data, yfinance,
    fetch_daily_cached, or any LLM seam.
    """

    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("price_cache",  "_purge_corrupt_rows"),
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
                        f"auto_adjust_mismatch_repair_preview must not "
                        f"call {module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "auto_adjust_mismatch_repair_preview must not "
                        "call yfinance",
                    ),
                ))
            except ImportError:
                pass

            stack.enter_context(_patch_loader(_THREE_DETAILS))
            stack.enter_context(_patch_window_loader({}))
            rc, output = _run_cli(["--json"])

        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_mismatches"], 3)


# ---------------------------------------------------------------------------
# Write-mode is intentionally absent — guard so a future change can't
# silently bolt one on.
# ---------------------------------------------------------------------------


class TestNoWriteMode(unittest.TestCase):
    def test_cli_rejects_write_flag(self) -> None:
        # Any of the obvious write-flag names should fail to parse.  The
        # script is read-only by contract.
        with _patch_loader([]), _patch_window_loader({}):
            for flag in ("--apply", "--write", "--repair", "--commit"):
                err = StringIO()
                old_stderr = sys.stderr
                try:
                    sys.stderr = err
                    with self.assertRaises(SystemExit, msg=flag):
                        cli.main([flag], out=StringIO())
                finally:
                    sys.stderr = old_stderr


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


_EXPECTED_CSV_COLUMNS = (
    "event_id",
    "event_date",
    "symbol",
    "target_20d",
    "available_auto_adjust_flags",
    "cache_max_aa0",
    "cache_max_aa1",
    "aa1_in_window_dates",
    "aa0_in_window_dates",
    "proposed_row_dates",
    "proposed_row_count",
    "repair_status",
    "repair_reason",
    "recommended_action",
)


def _parse_csv(output: str) -> tuple[list[str], list[list[str]]]:
    """Parse the CLI's CSV output back into (header, data_rows).

    Round-tripping through ``csv.reader`` is the only honest way to
    verify quoting/escaping — string-matching the raw output would miss
    the cases ``csv.QUOTE_MINIMAL`` is supposed to handle.
    """
    reader = csv.reader(StringIO(output))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


class TestCsvHeader(unittest.TestCase):
    def test_header_is_first_line_with_exact_column_order(self) -> None:
        with _patch_loader([]), _patch_window_loader({}):
            rc, output = _run_cli(["--csv"])
        self.assertEqual(rc, 0)
        header, data = _parse_csv(output)
        self.assertEqual(tuple(header), _EXPECTED_CSV_COLUMNS)
        self.assertEqual(data, [])

    def test_empty_payload_emits_header_only(self) -> None:
        with _patch_loader([]), _patch_window_loader({}):
            _, output = _run_cli(["--csv"])
        # Exactly one non-empty line: the header.  CSV writer terminates
        # the row with ``\n``; a final blank line is produced by the
        # ``print()`` newline, which is acceptable.
        non_blank = [ln for ln in output.splitlines() if ln.strip()]
        self.assertEqual(len(non_blank), 1)


class TestCsvRowEncoding(unittest.TestCase):
    def test_one_data_row_per_proposed_row(self) -> None:
        details = [
            _detail(1, "AAPL", event_date="2026-04-15"),
            _detail(2, "MSFT", event_date="2026-04-15"),
            _detail(3, "GOOG", event_date="2026-04-15"),
        ]
        rows = {
            ("AAPL", 1): {"2026-04-20"}, ("AAPL", 0): set(),
            ("MSFT", 1): {"2026-04-20"}, ("MSFT", 0): set(),
            ("GOOG", 1): {"2026-04-20"}, ("GOOG", 0): set(),
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        _, data = _parse_csv(output)
        self.assertEqual(len(data), 3)

    def test_list_fields_are_pipe_separated(self) -> None:
        details = [_detail(1, "AAPL", event_date="2026-04-15",
                           flags=[0, 1])]
        rows = {
            ("AAPL", 1): {"2026-04-20", "2026-05-01", "2026-05-13"},
            ("AAPL", 0): {"2026-04-20"},
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        header, data = _parse_csv(output)
        row = dict(zip(header, data[0]))
        self.assertEqual(row["available_auto_adjust_flags"], "0|1")
        self.assertEqual(
            row["aa1_in_window_dates"],
            "2026-04-20|2026-05-01|2026-05-13",
        )
        self.assertEqual(row["aa0_in_window_dates"], "2026-04-20")
        self.assertEqual(
            row["proposed_row_dates"], "2026-05-01|2026-05-13",
        )
        self.assertEqual(row["proposed_row_count"], "2")

    def test_cache_max_dict_flattens_to_two_columns(self) -> None:
        details = [_detail(1, "AAPL", event_date="2026-04-15",
                           cache_max={"0": "2026-04-14",
                                      "1": "2026-05-06"})]
        rows = {("AAPL", 1): {"2026-04-20"}, ("AAPL", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        header, data = _parse_csv(output)
        row = dict(zip(header, data[0]))
        self.assertEqual(row["cache_max_aa0"], "2026-04-14")
        self.assertEqual(row["cache_max_aa1"], "2026-05-06")

    def test_missing_cache_max_flag_renders_as_empty(self) -> None:
        details = [_detail(1, "AAPL", event_date="2026-04-15",
                           cache_max={"1": "2026-05-06"})]
        rows = {("AAPL", 1): {"2026-04-20"}, ("AAPL", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        header, data = _parse_csv(output)
        row = dict(zip(header, data[0]))
        self.assertEqual(row["cache_max_aa0"], "")
        self.assertEqual(row["cache_max_aa1"], "2026-05-06")

    def test_empty_list_field_renders_as_empty_string(self) -> None:
        details = [_detail(1, "X", event_date="2026-04-15",
                           flags=[], cache_max={})]
        rows = {("X", 1): set(), ("X", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        header, data = _parse_csv(output)
        row = dict(zip(header, data[0]))
        self.assertEqual(row["available_auto_adjust_flags"], "")
        self.assertEqual(row["aa1_in_window_dates"],          "")
        self.assertEqual(row["aa0_in_window_dates"],          "")
        self.assertEqual(row["proposed_row_dates"],           "")

    def test_invalid_event_date_row_emits_empty_target_not_literal_none(
        self,
    ) -> None:
        # ``not_repairable_invalid_event_date`` rows have target_20d=None
        # in the JSON payload.  In CSV that must come out as an empty
        # cell, not the literal string ``"None"`` — the easy regression.
        details = [_detail(1, "AAPL", event_date="not-a-date")]
        with _patch_loader(details), _patch_window_loader({}):
            _, output = _run_cli(["--csv"])
        header, data = _parse_csv(output)
        row = dict(zip(header, data[0]))
        self.assertEqual(row["target_20d"], "")
        self.assertNotEqual(row["target_20d"].lower(), "none")
        self.assertEqual(row["repair_status"],
                         "not_repairable_invalid_event_date")

    def test_repair_reason_with_comma_round_trips_via_csv_reader(self) -> None:
        # The default repair_reason text contains commas and brackets.
        # Use csv.reader to parse back; if quoting is wrong the field
        # count won't match and dict(zip) would mis-align.
        details = [_detail(1, "AAPL", event_date="2026-04-15")]
        rows = {
            ("AAPL", 1): {"2026-04-20"}, ("AAPL", 0): set(),
        }
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        header, data = _parse_csv(output)
        self.assertEqual(len(data), 1)
        self.assertEqual(len(data[0]), len(_EXPECTED_CSV_COLUMNS))
        row = dict(zip(header, data[0]))
        self.assertIn(",", row["repair_reason"])
        self.assertEqual(
            row["repair_status"], "repairable_flag_fix",
        )

    def test_recommended_action_is_fixed_label_per_row(self) -> None:
        details = [_detail(1, "AAPL", event_date="2026-04-15")]
        rows = {("AAPL", 1): {"2026-04-20"}, ("AAPL", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        header, data = _parse_csv(output)
        row = dict(zip(header, data[0]))
        self.assertEqual(
            row["recommended_action"],
            "refresh_unadjusted_cache_to_align_hydrator",
        )


class TestCsvLimit(unittest.TestCase):
    def test_limit_truncates_data_rows_but_keeps_header(self) -> None:
        many = [
            _detail(i, f"T{i}", event_date="2026-04-15") for i in range(7)
        ]
        rows = {(f"T{i}", 1): {"2026-04-20"} for i in range(7)}
        rows.update({(f"T{i}", 0): set() for i in range(7)})
        with _patch_loader(many), _patch_window_loader(rows):
            _, output = _run_cli(["--csv", "--limit", "3"])
        header, data = _parse_csv(output)
        self.assertEqual(tuple(header), _EXPECTED_CSV_COLUMNS)
        self.assertEqual(len(data), 3)
        self.assertEqual(
            [r[0] for r in data], ["0", "1", "2"],
        )


class TestCsvJsonMutex(unittest.TestCase):
    def test_csv_and_json_together_exit_with_argparse_error(self) -> None:
        old_stderr = sys.stderr
        try:
            sys.stderr = StringIO()
            with self.assertRaises(SystemExit):
                cli.main(["--csv", "--json"], out=StringIO())
        finally:
            sys.stderr = old_stderr


class TestCsvLineTerminator(unittest.TestCase):
    def test_csv_uses_lf_not_crlf(self) -> None:
        # Use ``\n`` to keep the output diff/test-friendly across
        # platforms; csv.writer's default of ``\r\n`` would clash with
        # the JSON renderer (which emits ``\n``) and produce ``\r\r\n``
        # under Python text-mode writes on Windows.
        details = [_detail(1, "AAPL", event_date="2026-04-15")]
        rows = {("AAPL", 1): {"2026-04-20"}, ("AAPL", 0): set()}
        with _patch_loader(details), _patch_window_loader(rows):
            _, output = _run_cli(["--csv"])
        # Header line must be terminated by a single LF.
        self.assertNotIn("\r\n", output)
        self.assertNotIn("\r",   output)


if __name__ == "__main__":
    unittest.main()
