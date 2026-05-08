"""Tests for ``scripts/stat_validation_forward_cache_gap_export.py``.

The export drills into the ``missing_forward_cache_20d`` blocker
surfaced by ``stat_validation_readiness_report``: one row per (event,
primary_ticker) pair whose 20-business-day forward cache window is
either entirely empty or stops short of the horizon date.  Tests run
against temp SQLite fixtures — no project DB, no provider, no LLM, no
network.
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
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import stat_validation_forward_cache_gap_export as export  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders — minimal events + price_cache schema mirroring the
# production tables enough for the read-only SELECT path.
# ---------------------------------------------------------------------------


_EVENTS_DDL = """
CREATE TABLE events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    headline       TEXT,
    event_date     TEXT,
    timestamp      TEXT,
    market_tickers TEXT
)
""".strip()

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


def _seed_db(
    path: Path,
    events: list[dict],
    cache: list[tuple[str, str]] | None = None,
) -> None:
    """Build a SQLite events archive at ``path``.

    ``events`` entries: ``{event_date, market_tickers}`` (the latter is a
    Python list — serialised to JSON here so callers don't have to).
    ``cache`` entries: ``(ticker, iso_date)`` pairs, written under
    ``auto_adjust=1`` (the readiness check ignores the flag, so a single
    flag is enough).
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_PRICE_CACHE_DDL)
        for ev in events:
            conn.execute(
                "INSERT INTO events "
                "(headline, event_date, timestamp, market_tickers) "
                "VALUES (?, ?, ?, ?)",
                (
                    ev.get("headline") or "h",
                    ev.get("event_date"),
                    ev.get("timestamp") or "2026-01-01T00:00:00",
                    (
                        ev["market_tickers"]
                        if isinstance(ev.get("market_tickers"), str)
                        or ev.get("market_tickers") is None
                        else json.dumps(ev["market_tickers"])
                    ),
                ),
            )
        for ticker, d in cache or []:
            conn.execute(
                "INSERT INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, d, 100.0, 1000, 1, "2026-01-01T00:00:00Z"),
            )
        conn.commit()
    finally:
        conn.close()


def _bday_offset(start: date, n: int) -> date:
    """Same business-day calendar the readiness report uses.

    Tests inline this rather than importing the production helper so a
    refactor to the production calendar shows up as a visible test
    diff, not a silent change.
    """
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _snapshot_db(path: Path) -> dict:
    conn = sqlite3.connect(str(path))
    try:
        snap: dict = {}
        for table in ("events", "price_cache"):
            try:
                snap[table] = list(conn.execute(
                    f"SELECT * FROM {table} ORDER BY rowid"
                ))
            except sqlite3.Error:
                snap[table] = None
        return snap
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.mkdtemp(prefix="test_svfcge_")
        self._tmp_root = Path(self._td)
        self._db = self._tmp_root / "events.db"

    def tearDown(self) -> None:
        for root, dirs, files in os.walk(self._tmp_root, topdown=False):
            for name in files:
                try:
                    Path(root, name).unlink()
                except OSError:
                    pass
            for name in dirs:
                try:
                    Path(root, name).rmdir()
                except OSError:
                    pass
        try:
            self._tmp_root.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Core classification — does the export pick up the right rows and
# attach the right blocker_reason?
# ---------------------------------------------------------------------------


class TestClassification(_Base):

    def test_empty_db_yields_no_rows(self) -> None:
        _seed_db(self._db, events=[])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows, [])

    def test_event_without_event_date_skipped(self) -> None:
        # No event_date means the export has nothing to anchor a target
        # date on.  The readiness report counts these in the
        # missing_forward_cache_20d count (the check fails by
        # degraded-input rule); the export deliberately omits them
        # because there's no actionable refresh to suggest.
        _seed_db(self._db, events=[
            {"event_date": None,
             "market_tickers": [{"symbol": "AAPL"}]},
            {"event_date": "",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows, [])

    def test_event_without_primary_ticker_skipped(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": []},
            {"event_date": "2026-01-05",
             "market_tickers": None},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows, [])

    def test_event_with_no_ticker_cache_emits_ticker_cache_missing(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["blocker_reason"], "ticker_cache_missing")
        self.assertEqual(rows[0]["primary_ticker"], "AAPL")
        self.assertIsNone(rows[0]["ticker_cache_max_date"])

    def test_event_with_cache_below_target_emits_window_gap(self) -> None:
        # Target date is 2026-01-05 + 20 business days — well past
        # 2026-01-12.
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ], cache=[
            ("AAPL", "2026-01-12"),
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["blocker_reason"], "ticker_cache_window_gap")
        self.assertEqual(rows[0]["ticker_cache_max_date"], "2026-01-12")

    def test_event_with_cache_at_target_not_emitted(self) -> None:
        # Cache exactly at the 20bd horizon is "ready" — readiness check
        # passes when any date >= target.
        event_d = date(2026, 1, 5)
        target  = _bday_offset(event_d, 20)
        _seed_db(self._db, events=[
            {"event_date": event_d.isoformat(),
             "market_tickers": [{"symbol": "AAPL"}]},
        ], cache=[
            ("AAPL", target.isoformat()),
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows, [])

    def test_event_with_cache_past_target_not_emitted(self) -> None:
        event_d = date(2026, 1, 5)
        past_target = _bday_offset(event_d, 30)
        _seed_db(self._db, events=[
            {"event_date": event_d.isoformat(),
             "market_tickers": [{"symbol": "AAPL"}]},
        ], cache=[
            ("AAPL", past_target.isoformat()),
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows, [])

    def test_target_date_is_event_date_plus_20_business_days(self) -> None:
        event_d = date(2026, 1, 5)  # Monday
        expected_target = _bday_offset(event_d, 20)
        _seed_db(self._db, events=[
            {"event_date": event_d.isoformat(),
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows[0]["target_date"], expected_target.isoformat())

    def test_horizon_field_is_twenty(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows[0]["horizon"], 20)

    def test_benchmark_field_is_spy(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows[0]["benchmark"], "SPY")

    def test_benchmark_cache_max_populated_when_spy_in_cache(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ], cache=[
            ("SPY", "2026-01-15"),
            ("SPY", "2026-01-30"),
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows[0]["benchmark_cache_max_date"], "2026-01-30")

    def test_benchmark_cache_max_is_none_when_no_spy_cache(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertIsNone(rows[0]["benchmark_cache_max_date"])

    def test_ticker_cache_max_uses_max_across_auto_adjust_flags(self) -> None:
        # Both flags share the (ticker, date) date space; the export
        # cares only about the latest cached date regardless of the
        # auto_adjust flag.  Seed both flags with different dates; the
        # max wins.
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        # Manually insert at both flags so the helper's default flag
        # doesn't mask the test.
        conn = sqlite3.connect(str(self._db))
        try:
            for flag, d in ((0, "2026-01-08"), (1, "2026-01-15")):
                conn.execute(
                    "INSERT INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("AAPL", d, 100.0, 1000, flag, "2026-01-01T00:00:00Z"),
                )
            conn.commit()
        finally:
            conn.close()
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows[0]["ticker_cache_max_date"], "2026-01-15")

    def test_event_with_malformed_event_date_skipped(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "not-a-date",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows, [])

    def test_event_with_unparseable_market_tickers_json_skipped(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": "not-json"},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(rows, [])

    def test_first_non_empty_symbol_used_as_primary_ticker(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [
                 {"symbol": ""},
                 {"symbol": "MSFT"},
                 {"symbol": "AAPL"},
             ]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["primary_ticker"], "MSFT")


# ---------------------------------------------------------------------------
# Field shape — every emitted row must carry the full field set in the
# pinned order.
# ---------------------------------------------------------------------------


class TestFieldShape(_Base):

    def test_field_names_pinned(self) -> None:
        self.assertEqual(export._FIELD_NAMES, (
            "event_id",
            "event_date",
            "primary_ticker",
            "horizon",
            "target_date",
            "ticker_cache_max_date",
            "benchmark",
            "benchmark_cache_max_date",
            "blocker_reason",
        ))

    def test_every_emitted_row_has_full_field_set(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
            {"event_date": "2026-02-05",
             "market_tickers": [{"symbol": "MSFT"}]},
        ], cache=[
            ("AAPL", "2026-01-10"),
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual(set(row.keys()), set(export._FIELD_NAMES))

    def test_event_id_is_int(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        rows = export._load_export_rows(db_path=str(self._db))
        self.assertIsInstance(rows[0]["event_id"], int)
        self.assertGreater(rows[0]["event_id"], 0)


# ---------------------------------------------------------------------------
# Defense-in-depth filter — the seam already restricts to the
# missing_forward_cache_20d blocker, but a future patched-in test row
# could smuggle in a different reason.  The filter strips those.
# ---------------------------------------------------------------------------


class TestFilter(unittest.TestCase):

    def test_filter_passes_canonical_reasons(self) -> None:
        rows = [
            {"blocker_reason": "ticker_cache_missing"},
            {"blocker_reason": "ticker_cache_window_gap"},
        ]
        kept = export._filter_to_missing_20d(rows)
        self.assertEqual(kept, rows)

    def test_filter_drops_non_20d_reasons(self) -> None:
        rows = [
            {"blocker_reason": "ticker_cache_missing"},
            {"blocker_reason": "auto_adjust_mismatch_for_20d"},
            {"blocker_reason": "no_action_needed_no_gaps"},
        ]
        kept = export._filter_to_missing_20d(rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["blocker_reason"], "ticker_cache_missing")

    def test_filter_drops_non_dict_entries(self) -> None:
        kept = export._filter_to_missing_20d([
            None,
            "string",
            ["list"],
            {"blocker_reason": "ticker_cache_missing"},
        ])
        self.assertEqual(len(kept), 1)


# ---------------------------------------------------------------------------
# Limit handling
# ---------------------------------------------------------------------------


class TestLimit(_Base):

    def _seed_three(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
            {"event_date": "2026-01-06",
             "market_tickers": [{"symbol": "MSFT"}]},
            {"event_date": "2026-01-07",
             "market_tickers": [{"symbol": "GOOG"}]},
        ])

    def test_limit_truncates_to_first_n_rows(self) -> None:
        self._seed_three()
        out = StringIO()
        rc = export.main(
            ["--db-path", str(self._db), "--json", "--limit", "2"],
            out=out,
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["rows"]), 2)

    def test_limit_zero_yields_no_rows(self) -> None:
        self._seed_three()
        out = StringIO()
        rc = export.main(
            ["--db-path", str(self._db), "--json", "--limit", "0"],
            out=out,
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["count"], 0)

    def test_negative_limit_clamped_to_zero(self) -> None:
        self._seed_three()
        out = StringIO()
        rc = export.main(
            ["--db-path", str(self._db), "--json", "--limit", "-5"],
            out=out,
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["count"], 0)


# ---------------------------------------------------------------------------
# JSON envelope contract
# ---------------------------------------------------------------------------


class TestJsonEnvelope(_Base):

    def test_json_envelope_carries_ok_count_fields_rows(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        out = StringIO()
        rc = export.main(["--db-path", str(self._db), "--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["fields"], list(export._FIELD_NAMES))
        self.assertIsInstance(payload["rows"], list)
        self.assertEqual(len(payload["rows"]), 1)

    def test_json_envelope_empty_when_no_events(self) -> None:
        _seed_db(self._db, events=[])
        out = StringIO()
        rc = export.main(["--db-path", str(self._db), "--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["fields"], list(export._FIELD_NAMES))


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


class TestCsvOutput(_Base):

    def test_csv_emits_header_and_data_row(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        out = StringIO()
        rc = export.main(["--db-path", str(self._db), "--csv"], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue().strip()
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        self.assertEqual(rows[0], list(export._FIELD_NAMES))
        self.assertEqual(len(rows), 2)  # header + one data row
        # event_id is the first column.
        self.assertNotEqual(rows[1][0], "")

    def test_csv_default_when_neither_flag_passed(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        out = StringIO()
        rc = export.main(["--db-path", str(self._db)], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        # JSON output starts with "{" — CSV starts with the header.
        self.assertFalse(text.lstrip().startswith("{"))
        self.assertIn(",".join(export._FIELD_NAMES), text)

    def test_csv_emits_header_only_when_no_rows(self) -> None:
        _seed_db(self._db, events=[])
        out = StringIO()
        rc = export.main(["--db-path", str(self._db), "--csv"], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue().strip()
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        self.assertEqual(rows, [list(export._FIELD_NAMES)])

    def test_csv_field_order_matches_pinned_field_names(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        out = StringIO()
        rc = export.main(["--db-path", str(self._db), "--csv"], out=out)
        self.assertEqual(rc, 0)
        first_line = out.getvalue().splitlines()[0]
        self.assertEqual(first_line, ",".join(export._FIELD_NAMES))

    def test_csv_and_json_are_mutually_exclusive(self) -> None:
        # argparse exits 2 on mutually-exclusive group violation.
        try:
            rc = export.main(
                ["--db-path", str(self._db), "--csv", "--json"],
                out=StringIO(),
            )
        except SystemExit as exc:
            rc = exc.code
        self.assertEqual(rc, 2)


# ---------------------------------------------------------------------------
# CLI plumbing — --db-path, --limit forwarded; exit code; both formats.
# ---------------------------------------------------------------------------


class TestCli(_Base):

    def test_main_default_exits_zero(self) -> None:
        _seed_db(self._db, events=[])
        out = StringIO()
        rc = export.main(["--db-path", str(self._db)], out=out)
        self.assertEqual(rc, 0)

    def test_main_db_path_arg_plumbed(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        seen: list[dict] = []
        original = export._load_export_rows

        def spy(*, db_path):
            seen.append({"db_path": db_path})
            return original(db_path=db_path)

        with patch.object(export, "_load_export_rows", side_effect=spy):
            export.main(
                ["--db-path", str(self._db), "--json"],
                out=StringIO(),
            )
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["db_path"], str(self._db))


# ---------------------------------------------------------------------------
# Read-only safety — the export must never mutate the DB or import
# provider / yfinance / LLM / FastAPI seams.
# ---------------------------------------------------------------------------


class TestReadOnly(_Base):

    def test_run_does_not_mutate_db(self) -> None:
        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ], cache=[("AAPL", "2026-01-08")])
        before = _snapshot_db(self._db)
        export._load_export_rows(db_path=str(self._db))
        after = _snapshot_db(self._db)
        self.assertEqual(before, after)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(export, "app"))
        self.assertFalse(hasattr(export, "router"))

    def test_running_does_not_import_provider_or_llm(self) -> None:
        import builtins

        forbidden_prefixes = (
            "yfinance",
            "market_check",
            "market_data",
            "analyze_event",
        )

        def _is_forbidden(name: str) -> bool:
            return any(
                name == p or name.startswith(p + ".")
                for p in forbidden_prefixes
            )

        forbidden_imports: list[str] = []
        real_import = builtins.__import__

        def tracing_import(name, *args, **kwargs):
            if _is_forbidden(name):
                forbidden_imports.append(name)
            return real_import(name, *args, **kwargs)

        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        with patch("builtins.__import__", side_effect=tracing_import):
            export._load_export_rows(db_path=str(self._db))
        self.assertEqual(forbidden_imports, [])

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard: instrument ``__import__`` so any
        # actual import statement targeting ``api`` / ``routes`` /
        # ``routes.*`` is recorded, even when the target is already
        # cached.  The export must never reach the FastAPI surface.
        import builtins

        def _is_forbidden(name: str) -> bool:
            return (
                name == "api" or name.startswith("api.")
                or name == "routes" or name.startswith("routes.")
            )

        forbidden_imports: list[str] = []
        real_import = builtins.__import__

        def tracing_import(
            name, globals=None, locals=None, fromlist=(), level=0,
        ):
            if _is_forbidden(name):
                forbidden_imports.append(name)
            if name == "routes":
                for sub in fromlist or ():
                    forbidden_imports.append(f"routes.{sub}")
            return real_import(name, globals, locals, fromlist, level)

        _seed_db(self._db, events=[
            {"event_date": "2026-01-05",
             "market_tickers": [{"symbol": "AAPL"}]},
        ])
        with patch("builtins.__import__", side_effect=tracing_import):
            export._load_export_rows(db_path=str(self._db))
        self.assertEqual(
            forbidden_imports, [],
            "export must not import api / routes during a run; "
            f"saw: {forbidden_imports}",
        )


# ---------------------------------------------------------------------------
# Seam patchability — tests can swap _load_export_rows directly to
# inject synthetic rows.
# ---------------------------------------------------------------------------


class TestSeamPatchable(_Base):

    def test_synthetic_rows_pass_through_renderer(self) -> None:
        synthetic = [{
            "event_id":                 99,
            "event_date":               "2026-01-05",
            "primary_ticker":           "TSLA",
            "horizon":                  20,
            "target_date":              "2026-02-02",
            "ticker_cache_max_date":    "2026-01-12",
            "benchmark":                "SPY",
            "benchmark_cache_max_date": "2026-01-12",
            "blocker_reason":           "ticker_cache_window_gap",
        }]
        out = StringIO()
        with patch.object(
            export, "_load_export_rows", return_value=synthetic,
        ):
            rc = export.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["rows"][0]["event_id"], 99)
        self.assertEqual(payload["rows"][0]["primary_ticker"], "TSLA")


if __name__ == "__main__":
    unittest.main()
