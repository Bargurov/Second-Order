"""Tests for ``scripts/no_forward_20d_refreshability_export.py`` —
read-only export of the ``cache_window_gap`` (refreshable) rows from the
no_forward_20d diagnostic.

The CLI defines a single seam (:func:`_load_export_rows`) that returns
fully-formed export rows with every field populated.  Most tests patch
that seam with synthetic rows so the CSV / JSON contract can be pinned
without touching SQLite.  A pair of integration tests use a temp DB
fixture so the un-patched production path also has direct coverage:

  * ``TestSeamCorrectness`` — plants one in-bucket event/ticker pair on
    a temp DB and asserts the seam returns a row with all eight fields
    populated correctly (event_id, event_date, symbol, diagnostic_reason,
    cache_max_date, horizon_20d_date, gap_days, source).
  * ``TestNoMutation`` — runs the CLI three times against the temp DB
    and verifies ``events`` + ``price_cache`` are byte-identical before
    and after.

Other invariants pinned here:

  * ``--json`` and ``--csv`` are mutually exclusive at argparse.
  * Default invocation emits CSV with the documented header and field
    order.
  * ``--limit`` truncates AFTER the cache_window_gap filter; rows above
    the cap are dropped.
  * Mixed-reason input (synthetic) is filtered down to only
    ``cache_max_before_20d_horizon`` rows.
  * No provider, yfinance, market_check, market_data, price_cache,
    LLM, or paid-execution seam is invoked by the export.
  * No archive mutation (``db.save_event`` / ``update_review`` /
    ``append_revisit_snapshot`` etc. never called).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402,F401  — pre-loads ``routes.diagnostics`` so the
                                 # CLI's lazy import in ``_load_export_rows``
                                 # cannot trip the api ↔ routes.diagnostics
                                 # cycle when the un-patched seam is
                                 # exercised by ``TestSeamCorrectness`` /
                                 # ``TestNoMutation``.
import db  # noqa: E402
from scripts import no_forward_20d_refreshability_export as cli  # noqa: E402


_REFRESHABLE = "cache_max_before_20d_horizon"
_NON_REFRESHABLE_REASONS = (
    "event_too_recent_for_20d",
    "auto_adjust_mismatch_for_20d",
    "likely_delisted_or_sparse",
)


# ---------------------------------------------------------------------------
# Synthetic row builder — produces rows in the export shape so the tests
# patch the seam directly with rows the CLI will not need to enrich.
# ---------------------------------------------------------------------------


def _row(
    *,
    event_id: int,
    symbol: str = "AAPL",
    event_date: str = "2026-04-01",
    diagnostic_reason: str = _REFRESHABLE,
    cache_max_date: str = "2026-04-15",
    horizon_20d_date: str = "2026-04-29",
    gap_days: int = 14,
    source: str = "no_forward_20d_blockers",
) -> dict:
    return {
        "event_id":          event_id,
        "event_date":        event_date,
        "symbol":             symbol,
        "diagnostic_reason": diagnostic_reason,
        "cache_max_date":    cache_max_date,
        "horizon_20d_date":  horizon_20d_date,
        "gap_days":          gap_days,
        "source":            source,
    }


def _run_cli(argv):
    out = StringIO()
    rc = cli.main(argv, out=out)
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Argparse plumbing — help, mutex, defaults
# ---------------------------------------------------------------------------


class TestArgparsePlumbing(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--help"], out=StringIO())
        self.assertEqual(ctx.exception.code, 0)

    def test_default_limit_value(self) -> None:
        ns = cli._parse_args([])
        self.assertEqual(ns.limit, cli._DEFAULT_LIMIT)
        self.assertFalse(ns.json)
        self.assertFalse(ns.csv)

    def test_json_and_csv_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(["--json", "--csv"], out=StringIO())


# ---------------------------------------------------------------------------
# CSV mode — default output, header, field order, data rows
# ---------------------------------------------------------------------------


class TestCsvOutput(unittest.TestCase):
    def test_default_invocation_emits_csv_header(self) -> None:
        with patch.object(cli, "_load_export_rows", return_value=[]):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        first_line = output.splitlines()[0]
        self.assertEqual(
            first_line,
            ",".join(cli._FIELD_NAMES),
            "CSV header must list the eight contract fields in order",
        )

    def test_csv_flag_emits_csv_same_as_default(self) -> None:
        with patch.object(cli, "_load_export_rows", return_value=[]):
            rc_default, out_default = _run_cli([])
            rc_csv,     out_csv     = _run_cli(["--csv"])
        self.assertEqual(rc_default, rc_csv)
        self.assertEqual(out_default, out_csv)

    def test_csv_emits_one_row_per_input_row(self) -> None:
        rows = [
            _row(event_id=1, symbol="AAPL"),
            _row(event_id=2, symbol="MSFT", gap_days=7),
            _row(event_id=3, symbol="TSLA", gap_days=21),
        ]
        with patch.object(cli, "_load_export_rows", return_value=rows):
            rc, output = _run_cli(["--csv"])
        self.assertEqual(rc, 0)
        reader = csv.DictReader(io.StringIO(output))
        parsed = list(reader)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(reader.fieldnames, list(cli._FIELD_NAMES))
        symbols = [r["symbol"] for r in parsed]
        self.assertEqual(symbols, ["AAPL", "MSFT", "TSLA"])

    def test_csv_data_row_carries_all_eight_fields(self) -> None:
        rows = [_row(event_id=42, symbol="NVDA", gap_days=5)]
        with patch.object(cli, "_load_export_rows", return_value=rows):
            _, output = _run_cli(["--csv"])
        reader = csv.DictReader(io.StringIO(output))
        parsed = next(reader)
        for field in cli._FIELD_NAMES:
            self.assertIn(field, parsed)
            self.assertNotEqual(parsed[field], "", f"empty field: {field}")
        self.assertEqual(parsed["event_id"], "42")
        self.assertEqual(parsed["symbol"],   "NVDA")
        self.assertEqual(parsed["gap_days"], "5")


# ---------------------------------------------------------------------------
# JSON mode — structured envelope
# ---------------------------------------------------------------------------


class TestJsonOutput(unittest.TestCase):
    def test_json_envelope_carries_ok_count_fields_rows(self) -> None:
        rows = [
            _row(event_id=1),
            _row(event_id=2, symbol="MSFT"),
        ]
        with patch.object(cli, "_load_export_rows", return_value=rows):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in ("ok", "count", "fields", "rows"):
            self.assertIn(key, body, f"missing JSON key: {key}")
        self.assertIs(body["ok"], True)
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["fields"], list(cli._FIELD_NAMES))
        self.assertEqual(len(body["rows"]), 2)

    def test_json_row_carries_every_field(self) -> None:
        rows = [_row(event_id=99, symbol="TSLA", gap_days=12)]
        with patch.object(cli, "_load_export_rows", return_value=rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        row = body["rows"][0]
        for field in cli._FIELD_NAMES:
            self.assertIn(field, row, f"missing row field: {field}")
        self.assertEqual(row["event_id"], 99)
        self.assertEqual(row["symbol"],   "TSLA")
        self.assertEqual(row["gap_days"], 12)

    def test_json_empty_seam_emits_count_zero(self) -> None:
        with patch.object(cli, "_load_export_rows", return_value=[]):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["rows"],  [])
        self.assertIs(body["ok"], True)


# ---------------------------------------------------------------------------
# Filter — "include only cache_window_gap rows by default" invariant
# ---------------------------------------------------------------------------


class TestCacheWindowGapFilter(unittest.TestCase):
    def test_mixed_input_keeps_only_cache_window_gap_rows(self) -> None:
        # Inject rows from every sub-bucket; the script must pass through
        # only the refreshable bucket.
        rows = [
            _row(event_id=1, symbol="AAPL", diagnostic_reason=_REFRESHABLE),
            _row(event_id=2, symbol="MSFT",
                 diagnostic_reason="event_too_recent_for_20d"),
            _row(event_id=3, symbol="GOOG", diagnostic_reason=_REFRESHABLE),
            _row(event_id=4, symbol="ZZZZ",
                 diagnostic_reason="likely_delisted_or_sparse"),
            _row(event_id=5, symbol="META",
                 diagnostic_reason="auto_adjust_mismatch_for_20d"),
        ]
        with patch.object(cli, "_load_export_rows", return_value=rows):
            _, output = _run_cli(["--json"])
        body = json.loads(output)
        self.assertEqual(body["count"], 2)
        survivors = {r["symbol"] for r in body["rows"]}
        self.assertEqual(survivors, {"AAPL", "GOOG"})
        for r in body["rows"]:
            self.assertEqual(r["diagnostic_reason"], _REFRESHABLE)

    def test_filter_drops_non_dict_inputs_safely(self) -> None:
        # Defense-in-depth: a malformed seam return must not crash the
        # render path.
        rows = [
            _row(event_id=1),
            None,
            "garbage",
            _row(event_id=2, diagnostic_reason="event_too_recent_for_20d"),
            _row(event_id=3),
        ]
        with patch.object(cli, "_load_export_rows", return_value=rows):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["count"], 2)
        self.assertEqual(
            [r["event_id"] for r in body["rows"]], [1, 3],
        )


# ---------------------------------------------------------------------------
# --limit behaviour
# ---------------------------------------------------------------------------


class TestLimitFlag(unittest.TestCase):
    def _five_refreshable(self) -> list[dict]:
        return [
            _row(event_id=i, symbol=f"SYM{i:02d}") for i in range(1, 6)
        ]

    def test_limit_truncates_to_requested_count(self) -> None:
        with patch.object(cli, "_load_export_rows",
                          return_value=self._five_refreshable()):
            _, output = _run_cli(["--json", "--limit", "3"])
        body = json.loads(output)
        self.assertEqual(body["count"], 3)
        self.assertEqual(
            [r["event_id"] for r in body["rows"]], [1, 2, 3],
        )

    def test_limit_above_supply_returns_full_supply(self) -> None:
        with patch.object(cli, "_load_export_rows",
                          return_value=self._five_refreshable()):
            _, output = _run_cli(["--json", "--limit", "100"])
        body = json.loads(output)
        self.assertEqual(body["count"], 5)

    def test_limit_zero_returns_no_rows(self) -> None:
        with patch.object(cli, "_load_export_rows",
                          return_value=self._five_refreshable()):
            _, output = _run_cli(["--json", "--limit", "0"])
        body = json.loads(output)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["rows"],  [])

    def test_limit_negative_clamps_to_zero(self) -> None:
        with patch.object(cli, "_load_export_rows",
                          return_value=self._five_refreshable()):
            _, output = _run_cli(["--json", "--limit", "-3"])
        body = json.loads(output)
        self.assertEqual(body["count"], 0)

    def test_limit_applied_after_filter(self) -> None:
        # Mixed input: 3 refreshable + 2 non-refreshable.  With --limit 5
        # the cap is irrelevant because only 3 survive the filter.  This
        # pins the order: filter then truncate, NOT truncate then filter.
        rows = [
            _row(event_id=1, diagnostic_reason="event_too_recent_for_20d"),
            _row(event_id=2),
            _row(event_id=3, diagnostic_reason="likely_delisted_or_sparse"),
            _row(event_id=4),
            _row(event_id=5),
        ]
        with patch.object(cli, "_load_export_rows", return_value=rows):
            _, output = _run_cli(["--json", "--limit", "5"])
        body = json.loads(output)
        self.assertEqual(body["count"], 3)
        self.assertEqual(
            [r["event_id"] for r in body["rows"]], [2, 4, 5],
        )


# ---------------------------------------------------------------------------
# Forbidden seams — no provider, no LLM, no DB writers
# ---------------------------------------------------------------------------


_FORBIDDEN_PROVIDER_SEAMS: tuple[tuple[str, str], ...] = (
    ("market_check",         "_fetch"),
    ("market_check",         "_fetch_since"),
    ("market_check",         "market_check"),
    ("market_check",         "_check_one_ticker"),
    ("market_data",          "get_provider"),
    ("market_data",          "reload_provider_from_env"),
    ("price_cache",          "fetch_daily_cached"),
    ("price_cache",          "_purge_corrupt_rows"),
    ("price_cache",          "_ensure_table"),
    ("analyze_event",        "analyze_event"),
    ("analyze_event",        "_call_anthropic"),
    ("analyze_event",        "_call_openai"),
    ("analyze_event",        "_call_llm_provider"),
    ("auto_backfill_runner", "execute_paid_candidate"),
)

_FORBIDDEN_DB_WRITERS: tuple[tuple[str, str], ...] = (
    ("db", "save_event"),
    ("db", "update_review"),
    ("db", "append_revisit_snapshot"),
    ("db", "delete_event"),
    ("db", "save_movers_cache"),
    ("db", "clear_movers_cache"),
)


def _patch_raisers(stack, seams, *, label):
    for module_name, attr in seams:
        try:
            mod = __import__(module_name)
        except Exception:
            continue
        if not hasattr(mod, attr):
            continue
        stack.enter_context(patch.object(
            mod, attr,
            side_effect=AssertionError(
                f"refreshability_export must not invoke "
                f"{module_name}.{attr} ({label})",
            ),
        ))


class TestNoForbiddenSeams(unittest.TestCase):
    def test_no_provider_or_llm_seam_invoked(self) -> None:
        rows = [_row(event_id=1, symbol="AAPL")]
        with ExitStack() as stack:
            _patch_raisers(
                stack, _FORBIDDEN_PROVIDER_SEAMS, label="provider/LLM seam",
            )
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "refreshability_export must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            stack.enter_context(patch.object(
                cli, "_load_export_rows", return_value=rows,
            ))
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0, msg=output)

    def test_no_db_writers_invoked(self) -> None:
        rows = [_row(event_id=1, symbol="MSFT"), _row(event_id=2, symbol="AAPL")]
        with ExitStack() as stack:
            _patch_raisers(stack, _FORBIDDEN_DB_WRITERS, label="db writer")
            stack.enter_context(patch.object(
                cli, "_load_export_rows", return_value=rows,
            ))
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0, msg=output)


# ---------------------------------------------------------------------------
# Production seam — temp DB fixture exercises ``_load_export_rows`` un-
# patched.  These tests mirror the read-only contract pattern in
# ``test_no_forward_20d_gap_report.py:473-528``.
# ---------------------------------------------------------------------------


def _snapshot_tables(db_path: str) -> tuple[list[tuple], list[tuple]]:
    conn = sqlite3.connect(db_path)
    try:
        events = list(conn.execute("SELECT * FROM events ORDER BY id"))
        cache  = list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))
        return events, cache
    finally:
        conn.close()


class _TempDbBase(unittest.TestCase):
    """Shared fixture: temp ``events.db`` with ONE event/ticker pair
    that lands in the ``cache_max_before_20d_horizon`` bucket.

    Construction:
      * event_date is ~30 calendar days in the past so
        ``event_date + 20 business days`` is comfortably <= today.
      * cache_max_date is ~10 calendar days in the past — fresh enough
        to dodge the ``likely_delisted_or_sparse`` threshold (60 days),
        old enough to fall short of the 20bd horizon.
      * Same auto_adjust flag is planted on every cache row so the
        ``auto_adjust_mismatch_for_20d`` branch cannot fire.
      * 1d / 5d closes are present in cache so ``_classify_blocker_for_ticker``
        actually classifies as ``no_forward_20d_close`` (the bucket the
        sub-classifier needs to reach).
    """

    SYMBOL = "AAPL"

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_nf20_export_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

        today = date.today()
        # 35 calendar days ago lands the +20bd horizon ~5 weeks earlier
        # than today, well below the today threshold.
        event_d = today - timedelta(days=35)
        # cache_max sits 10 calendar days behind today — enough to give
        # 1d and 5d closes after event_d, but short of event_d+20bd.
        cache_max = today - timedelta(days=10)

        self._event_date_str  = event_d.isoformat()
        self._cache_max_str   = cache_max.isoformat()

        record = {
            "headline":   "NF20 refreshability export probe",
            "stage":      "realized",
            "persistence": "medium",
            "event_date":  self._event_date_str,
            "market_tickers": [{"symbol": self.SYMBOL}],
        }
        db.save_event(record)

        # Plant a CONTIGUOUS run of business-day bars from event_d through
        # cache_max.  ``hydrate_per_ticker_profile`` walks day-by-day from
        # the anchor and needs every business day populated; sparse
        # offsets (anchor / +1bd / +5bd only) collapse the hydration
        # status to ``no_forward_5d_close`` which would dodge the
        # ``no_forward_20d_close`` blocker we want this fixture to drive.
        with sqlite3.connect(self._tmp) as conn:
            d = event_d
            close_value = 100.0
            while d <= cache_max:
                if d.weekday() < 5:  # business days only
                    conn.execute(
                        "INSERT OR REPLACE INTO price_cache "
                        "(ticker, date, close, volume, auto_adjust, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            self.SYMBOL, d.isoformat(),
                            close_value, 5_000_000.0, 0,
                            "2026-05-06T12:00:00+00:00",
                        ),
                    )
                    close_value += 0.5
                d = d + timedelta(days=1)
            conn.commit()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


class TestSeamCorrectness(_TempDbBase):
    """Direct coverage of the un-patched production seam.  Verifies the
    eight export fields are populated against a known-good fixture.
    """

    def test_seam_returns_one_row_with_all_eight_fields(self) -> None:
        rows = cli._load_export_rows()
        # Filter to the symbol planted by the fixture so the test stays
        # robust if the test process somehow inherits other fixtures.
        ours = [r for r in rows if r.get("symbol") == self.SYMBOL]
        self.assertEqual(
            len(ours), 1,
            f"expected exactly one cache_window_gap row for {self.SYMBOL}, "
            f"got {len(ours)}: {ours}",
        )
        row = ours[0]

        # All eight contract fields populated (no ``None`` slots).
        for field in cli._FIELD_NAMES:
            self.assertIn(field, row)
            self.assertIsNotNone(row[field], f"None field: {field}")

        # Field-level pinning.
        self.assertEqual(row["symbol"],            self.SYMBOL)
        self.assertEqual(row["diagnostic_reason"], _REFRESHABLE)
        self.assertEqual(row["event_date"],        self._event_date_str)
        self.assertEqual(row["cache_max_date"],    self._cache_max_str)
        self.assertEqual(row["source"],            "no_forward_20d_blockers")
        self.assertIsInstance(row["event_id"],     int)
        self.assertIsInstance(row["gap_days"],     int)
        # Horizon must be event_date + 20 business days (non-empty,
        # parseable, strictly after event_date).
        horizon = date.fromisoformat(row["horizon_20d_date"])
        event_d = date.fromisoformat(row["event_date"])
        self.assertGreater(horizon, event_d)
        # gap_days = (horizon - cache_max).days, calendar days, > 0.
        self.assertEqual(
            row["gap_days"],
            (horizon - date.fromisoformat(row["cache_max_date"])).days,
        )
        self.assertGreater(row["gap_days"], 0)

    def test_cli_default_csv_run_emits_header_plus_one_data_row(self) -> None:
        rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        reader = csv.DictReader(io.StringIO(output))
        parsed = [r for r in reader if r["symbol"] == self.SYMBOL]
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["diagnostic_reason"], _REFRESHABLE)


class TestNoMutation(_TempDbBase):
    """Repeated CLI runs leave the temp ``events.db`` byte-identical."""

    def test_repeated_runs_leave_db_byte_identical(self) -> None:
        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            rc, _ = _run_cli(["--json"])
            self.assertEqual(rc, 0)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical before and after "
            "repeated refreshability-export runs",
        )


if __name__ == "__main__":
    unittest.main()
