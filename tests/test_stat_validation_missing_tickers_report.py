"""Tests for ``scripts/stat_validation_missing_tickers_report.py``.

Pin the contract:

* The report walks the archive once and surfaces only events whose
  ``market_tickers`` JSON resolves to no usable primary symbol.
* Per-event row carries event_id, event_date, headline, stage,
  persistence, confidence, suggested_next_action — and
  ``suggested_next_action`` is *always* the constant
  ``"manual_review_required"`` (no LLM, no inference).
* NULL / blank passthrough: stage/persistence/confidence/event_date/
  headline that were NULL or empty in the row come out as ``None`` —
  not coerced to ``""`` or ``"unknown"``.
* The "missing" definition aligns with the readiness report's
  ``has_market_tickers=False`` — every malformed market_tickers shape
  surfaces here.
* ``--json``, ``--csv``, ``--limit``, ``--db-path`` plumbing, and
  ``--json --csv`` mutual exclusion.
* Read-only: repeated runs leave the events table byte-identical, and
  no provider/yfinance/market_check/market_data/LLM/FastAPI seam is
  invoked.
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
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import stat_validation_missing_tickers_report as cli  # noqa: E402


_TOP_KEYS = (
    "total_events",
    "events_missing_market_tickers",
    "events",
    "recommended_next_action",
)


_PER_EVENT_KEYS = (
    "event_id",
    "event_date",
    "headline",
    "stage",
    "persistence",
    "confidence",
    "suggested_next_action",
)


# ---------------------------------------------------------------------------
# Temp DB fixtures
# ---------------------------------------------------------------------------


_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT,
    stage           TEXT,
    persistence     TEXT,
    confidence      TEXT
)
""".strip()


def _seed_event(
    conn: sqlite3.Connection,
    *,
    event_date:     str | None = "2026-04-15",
    market_tickers: str | None = None,
    headline:       str | None = "test headline",
    stage:          str | None = "realized",
    persistence:    str | None = "medium",
    confidence:     str | None = "low",
) -> int:
    cur = conn.execute(
        "INSERT INTO events "
        "(headline, event_date, market_tickers, stage, persistence, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (headline, event_date, market_tickers, stage, persistence, confidence),
    )
    return int(cur.lastrowid)


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        rc = cli.main(argv, out=out)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 0
    return rc, out.getvalue()


class _TempDbCase(unittest.TestCase):
    """Create a fresh temp SQLite file with the events DDL per test."""

    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_svmtr_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._tmp)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(_TempDbCase):
    def test_returns_dict_with_top_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, market_tickers=None)
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")
        self.assertIsInstance(result["events"], list)

    def test_per_event_rows_carry_required_fields(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, market_tickers=None)
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertEqual(len(result["events"]), 1)
        row = result["events"][0]
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, row, f"per-event row missing key: {key}")


# ---------------------------------------------------------------------------
# Empty / fully-tickered archives
# ---------------------------------------------------------------------------


class TestEmptyAndAllTickered(_TempDbCase):
    def test_empty_db_zeros_every_count(self) -> None:
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertEqual(result["total_events"],                  0)
        self.assertEqual(result["events_missing_market_tickers"], 0)
        self.assertEqual(result["events"],                        [])
        self.assertIn("empty",
                      result["recommended_next_action"].lower())

    def test_all_tickered_yields_zero_missing(self) -> None:
        with self._conn() as conn:
            for sym in ("AAPL", "MSFT", "GOOG"):
                _seed_event(
                    conn,
                    market_tickers=json.dumps([{"symbol": sym}]),
                )
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertEqual(result["total_events"],                  3)
        self.assertEqual(result["events_missing_market_tickers"], 0)
        self.assertEqual(result["events"],                        [])
        self.assertIn("no manual review",
                      result["recommended_next_action"].lower())

    def test_unresolvable_db_path_yields_empty_report(self) -> None:
        bogus = os.path.join(
            tempfile.gettempdir(),
            f"does_not_exist_{uuid.uuid4().hex}.db",
        )
        # SQLite will create the file even if it doesn't exist; what we
        # really want to pin is that a path with no events table
        # degrades gracefully (counts of 0, no crash).
        result = cli.summarize_missing_tickers(db_path=bogus)
        self.assertEqual(result["total_events"],                  0)
        self.assertEqual(result["events_missing_market_tickers"], 0)
        try:
            os.remove(bogus)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Missing-tickers detection — pin every shape locally so a refactor
# of the readiness helper can't silently flip the contract.
# ---------------------------------------------------------------------------


class TestMissingDetection(_TempDbCase):
    def test_every_malformed_shape_lands_in_missing(self) -> None:
        cases = (
            ("null",            None),
            ("empty_string",    ""),
            ("empty_list",      "[]"),
            ("list_of_empty_dict", "[{}]"),
            ("blank_symbol",    json.dumps([{"symbol": ""}])),
            ("whitespace_symbol", json.dumps([{"symbol": "   "}])),
            ("null_symbol",     json.dumps([{"symbol": None}])),
            ("non_string_symbol", json.dumps([{"symbol": 123}])),
            ("malformed_json",  "{not-json"),
            ("non_list_payload", json.dumps({"symbol": "AAPL"})),
            ("list_of_strings", json.dumps(["AAPL"])),
        )
        with self._conn() as conn:
            for label, raw in cases:
                _seed_event(
                    conn,
                    headline=f"hl_{label}",
                    market_tickers=raw,
                )
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertEqual(result["total_events"],                  len(cases))
        self.assertEqual(
            result["events_missing_market_tickers"], len(cases),
            "every malformed market_tickers shape must surface as missing",
        )
        self.assertEqual(len(result["events"]), len(cases))
        # Headlines preserved so the operator can distinguish each row.
        surfaced_headlines = sorted(
            e["headline"] for e in result["events"]
        )
        expected_headlines = sorted(f"hl_{label}" for label, _ in cases)
        self.assertEqual(surfaced_headlines, expected_headlines)

    def test_resolvable_payload_does_not_surface(self) -> None:
        cases = (
            ("primary_only",   json.dumps([{"symbol": "AAPL"}])),
            ("first_blank_then_real",
             json.dumps([{"symbol": ""}, {"symbol": "MSFT"}])),
            ("mixed_with_strings",
             json.dumps(["junk", {"symbol": "GOOG"}])),
            ("padded_symbol",  json.dumps([{"symbol": "  TSLA  "}])),
        )
        with self._conn() as conn:
            for _, raw in cases:
                _seed_event(conn, market_tickers=raw)
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertEqual(result["total_events"],                  len(cases))
        self.assertEqual(result["events_missing_market_tickers"], 0)


# ---------------------------------------------------------------------------
# Field passthrough + suggested_next_action invariant
# ---------------------------------------------------------------------------


class TestPerEventFieldPassthrough(_TempDbCase):
    def test_text_fields_passed_through_verbatim(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                event_date="2026-04-15",
                headline="OPEC slashes output by 2 mbpd",
                stage="realized",
                persistence="medium",
                confidence="high",
                market_tickers=None,
            )
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        row = result["events"][0]
        self.assertEqual(row["event_date"],  "2026-04-15")
        self.assertEqual(row["headline"],
                         "OPEC slashes output by 2 mbpd")
        self.assertEqual(row["stage"],       "realized")
        self.assertEqual(row["persistence"], "medium")
        self.assertEqual(row["confidence"],  "high")

    def test_null_fields_surface_as_none(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                event_date=None,
                headline=None,
                stage=None,
                persistence=None,
                confidence=None,
                market_tickers=None,
            )
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        row = result["events"][0]
        self.assertIsNone(row["event_date"])
        self.assertIsNone(row["headline"])
        self.assertIsNone(row["stage"])
        self.assertIsNone(row["persistence"])
        self.assertIsNone(row["confidence"])

    def test_empty_string_fields_surface_as_none(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                event_date="",
                headline="",
                stage="",
                persistence="",
                confidence="",
                market_tickers="",
            )
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        row = result["events"][0]
        self.assertIsNone(row["event_date"])
        self.assertIsNone(row["headline"])
        self.assertIsNone(row["stage"])
        self.assertIsNone(row["persistence"])
        self.assertIsNone(row["confidence"])

    def test_suggested_next_action_is_always_manual_review_required(self) -> None:
        # Mix every kind of missing market_tickers shape and assert the
        # suggested_next_action is the constant for *every* row.  This
        # is the no-LLM / no-inference invariant.
        shapes = (None, "", "[]", "[{}]", '[{"symbol":""}]', "{junk")
        with self._conn() as conn:
            for raw in shapes:
                _seed_event(conn, market_tickers=raw)
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertEqual(len(result["events"]), len(shapes))
        for row in result["events"]:
            self.assertEqual(
                row["suggested_next_action"], "manual_review_required",
            )


# ---------------------------------------------------------------------------
# Order + --limit
# ---------------------------------------------------------------------------


class TestOrderAndLimit(_TempDbCase):
    def _seed_n_missing(self, n: int) -> None:
        with self._conn() as conn:
            for _ in range(n):
                _seed_event(conn, market_tickers=None)
            conn.commit()

    def test_examples_preserve_id_ascending_order(self) -> None:
        # Insert rows in non-ascending event_date so the sort is
        # demonstrably driven by id, not insert order.
        with self._conn() as conn:
            _seed_event(conn, event_date="2026-04-09",
                        headline="late", market_tickers=None)
            _seed_event(conn, event_date="2026-04-07",
                        headline="middle", market_tickers=None)
            _seed_event(conn, event_date="2026-04-08",
                        headline="last", market_tickers=None)
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        ids = [e["event_id"] for e in result["events"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_truncates_examples_only(self) -> None:
        self._seed_n_missing(10)
        result = cli.summarize_missing_tickers(db_path=self._tmp, limit=3)
        # Count walks every missing event regardless of limit.
        self.assertEqual(result["events_missing_market_tickers"], 10)
        self.assertEqual(len(result["events"]),                   3)
        ids = [e["event_id"] for e in result["events"]]
        self.assertEqual(ids, sorted(ids))

    def test_negative_limit_clamps_to_zero(self) -> None:
        self._seed_n_missing(3)
        result = cli.summarize_missing_tickers(db_path=self._tmp, limit=-5)
        self.assertEqual(result["events_missing_market_tickers"], 3)
        self.assertEqual(result["events"],                        [])

    def test_limit_zero_keeps_count_intact(self) -> None:
        self._seed_n_missing(7)
        result = cli.summarize_missing_tickers(db_path=self._tmp, limit=0)
        self.assertEqual(result["events_missing_market_tickers"], 7)
        self.assertEqual(result["events"],                        [])

    def test_limit_greater_than_population_returns_all(self) -> None:
        self._seed_n_missing(4)
        result = cli.summarize_missing_tickers(db_path=self._tmp, limit=100)
        self.assertEqual(len(result["events"]), 4)


# ---------------------------------------------------------------------------
# Mixed populations — only the missing ones surface
# ---------------------------------------------------------------------------


class TestMixedPopulation(_TempDbCase):
    def test_only_missing_events_appear(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="have_aapl",
                        market_tickers=json.dumps([{"symbol": "AAPL"}]))
            _seed_event(conn, headline="missing_null",
                        market_tickers=None)
            _seed_event(conn, headline="have_msft",
                        market_tickers=json.dumps([{"symbol": "MSFT"}]))
            _seed_event(conn, headline="missing_empty",
                        market_tickers="[]")
            _seed_event(conn, headline="have_goog",
                        market_tickers=json.dumps([{"symbol": "GOOG"}]))
            conn.commit()
        result = cli.summarize_missing_tickers(db_path=self._tmp)
        self.assertEqual(result["total_events"],                  5)
        self.assertEqual(result["events_missing_market_tickers"], 2)
        headlines = [e["headline"] for e in result["events"]]
        self.assertEqual(
            sorted(headlines), ["missing_empty", "missing_null"],
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(_TempDbCase):
    def _seed_two_missing_one_present(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="missing_a",
                        market_tickers=None)
            _seed_event(conn, headline="have_aapl",
                        market_tickers=json.dumps([{"symbol": "AAPL"}]))
            _seed_event(conn, headline="missing_b",
                        market_tickers="[]")
            conn.commit()

    def test_text_output_summarises_each_missing_row(self) -> None:
        self._seed_two_missing_one_present()
        rc, output = _run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        self.assertIn("Total events",       output)
        self.assertIn("missing market_tickers", output)
        self.assertIn("missing_a",          output)
        self.assertIn("missing_b",          output)
        # The fully-tickered event must not appear in any form.
        self.assertNotIn("have_aapl",       output)
        self.assertIn("Recommended next action", output)
        # suggested_next_action is rendered verbatim per row.
        self.assertIn("manual_review_required", output)

    def test_json_output_carries_required_keys(self) -> None:
        self._seed_two_missing_one_present()
        rc, output = _run_cli(["--db-path", self._tmp, "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertEqual(body["total_events"],                  3)
        self.assertEqual(body["events_missing_market_tickers"], 2)
        self.assertEqual(len(body["events"]),                    2)
        for row in body["events"]:
            for key in _PER_EVENT_KEYS:
                self.assertIn(key, row, f"missing per-event key: {key}")
            self.assertEqual(row["suggested_next_action"],
                             "manual_review_required")

    def test_csv_output_header_and_rows(self) -> None:
        self._seed_two_missing_one_present()
        rc, output = _run_cli(["--db-path", self._tmp, "--csv"])
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        self.assertEqual(header, list(_PER_EVENT_KEYS))
        rows = list(reader)
        self.assertEqual(len(rows), 2)
        # Header column index for headline + suggested_next_action so
        # we can pin those specifically.
        idx_headline   = _PER_EVENT_KEYS.index("headline")
        idx_suggestion = _PER_EVENT_KEYS.index("suggested_next_action")
        for row in rows:
            self.assertEqual(row[idx_suggestion],
                             "manual_review_required")
        headlines = sorted(r[idx_headline] for r in rows)
        self.assertEqual(headlines, ["missing_a", "missing_b"])

    def test_csv_omits_totals_to_stay_pipeline_friendly(self) -> None:
        self._seed_two_missing_one_present()
        rc, output = _run_cli(["--db-path", self._tmp, "--csv"])
        self.assertEqual(rc, 0)
        # The totals labels we use in text mode must NOT be in CSV
        # output — a downstream DictReader would parse them as data.
        self.assertNotIn("Total events",                output)
        self.assertNotIn("events_missing_market_tickers", output)
        self.assertNotIn("Recommended next action",    output)

    def test_csv_blank_cell_for_null_field(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                event_date="2026-04-15",
                headline=None,             # NULL in DB
                stage=None,
                persistence=None,
                confidence=None,
                market_tickers=None,
            )
            conn.commit()
        rc, output = _run_cli(["--db-path", self._tmp, "--csv"])
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        next(reader)  # header
        row = next(reader)
        idx_headline    = _PER_EVENT_KEYS.index("headline")
        idx_stage       = _PER_EVENT_KEYS.index("stage")
        idx_persistence = _PER_EVENT_KEYS.index("persistence")
        idx_confidence  = _PER_EVENT_KEYS.index("confidence")
        self.assertEqual(row[idx_headline],    "")
        self.assertEqual(row[idx_stage],       "")
        self.assertEqual(row[idx_persistence], "")
        self.assertEqual(row[idx_confidence],  "")

    def test_cli_limit_truncates_in_every_output_mode(self) -> None:
        with self._conn() as conn:
            for _ in range(8):
                _seed_event(conn, market_tickers=None)
            conn.commit()

        # JSON
        rc, output = _run_cli([
            "--db-path", self._tmp, "--json", "--limit", "2",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["events_missing_market_tickers"], 8)
        self.assertEqual(len(body["events"]),                    2)

        # CSV
        rc, output = _run_cli([
            "--db-path", self._tmp, "--csv", "--limit", "3",
        ])
        self.assertEqual(rc, 0)
        rows = list(csv.reader(io.StringIO(output)))
        # 1 header + 3 rows = 4
        self.assertEqual(len(rows), 4)

    def test_json_and_csv_are_mutually_exclusive(self) -> None:
        rc, _ = _run_cli([
            "--db-path", self._tmp, "--json", "--csv",
        ])
        # argparse exits with code 2 on argument errors.
        self.assertEqual(rc, 2)

    def test_default_db_path_uses_db_module(self) -> None:
        # When --db-path is omitted, the resolver consults the lazy
        # ``db`` module.  Patch it to point at the temp file so the
        # default code path is exercised end-to-end without touching
        # the production archive.
        with self._conn() as conn:
            _seed_event(conn, market_tickers=None)
            conn.commit()
        import db as real_db  # noqa: E402
        with patch.object(real_db, "DB_FILE", self._tmp):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_events"],                  1)
        self.assertEqual(body["events_missing_market_tickers"], 1)


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(_TempDbCase):
    def test_repeated_runs_leave_events_table_byte_identical(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="a", market_tickers=None)
            _seed_event(conn, headline="b",
                        market_tickers=json.dumps([{"symbol": "AAPL"}]))
            _seed_event(conn, headline="c", market_tickers="[]")
            conn.commit()

        def _snapshot() -> list:
            conn = sqlite3.connect(self._tmp)
            try:
                return list(conn.execute(
                    "SELECT id, headline, event_date, market_tickers, "
                    "stage, persistence, confidence FROM events "
                    "ORDER BY id"
                ))
            finally:
                conn.close()

        before = _snapshot()
        for _ in range(3):
            cli.summarize_missing_tickers(db_path=self._tmp)
            cli.main(["--db-path", self._tmp, "--json"], out=StringIO())
            cli.main(["--db-path", self._tmp, "--csv"],  out=StringIO())
            cli.main(["--db-path", self._tmp],            out=StringIO())
        after = _snapshot()
        self.assertEqual(
            before, after,
            "events table must be byte-identical across repeated "
            "report runs (read-only invariant)",
        )

    def test_no_write_statements_issued(self) -> None:
        # Wrap ``sqlite3.connect`` so every connection the report opens
        # carries a trace callback.  ``set_trace_callback`` fires for
        # every statement the SQLite engine executes, so any accidental
        # INSERT / UPDATE / DELETE / CREATE / DROP / REPLACE / ALTER
        # added in future maintenance is caught here.  We can't patch
        # ``sqlite3.Connection.execute`` directly because the type is
        # immutable in CPython.
        with self._conn() as conn:
            _seed_event(conn, market_tickers=None)
            conn.commit()

        executed: list[str] = []
        real_connect = sqlite3.connect

        def tracing_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            conn.set_trace_callback(executed.append)
            return conn

        with patch.object(sqlite3, "connect", side_effect=tracing_connect):
            cli.summarize_missing_tickers(db_path=self._tmp)

        forbidden_prefixes = (
            "INSERT", "UPDATE", "DELETE", "CREATE", "DROP",
            "REPLACE", "ALTER",
        )
        for sql in executed:
            stripped = sql.strip().upper()
            for prefix in forbidden_prefixes:
                self.assertFalse(
                    stripped.startswith(prefix),
                    f"forbidden SQL issued: {sql!r}",
                )
        # Sanity — at least one SELECT was issued so we know the
        # tracer actually saw the report's traffic.
        self.assertTrue(
            any(s.strip().upper().startswith("SELECT") for s in executed),
            "expected at least one SELECT statement",
        )


# ---------------------------------------------------------------------------
# Forbidden seams + FastAPI surface
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_TempDbCase):
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
            ("price_cache",  "_ensure_table"),
            ("price_cache",  "_write_rows"),
        )

        with self._conn() as conn:
            _seed_event(conn, market_tickers=None)
            conn.commit()

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
                        f"missing-tickers report must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "missing-tickers report must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            result = cli.summarize_missing_tickers(db_path=self._tmp)

        self.assertEqual(result["events_missing_market_tickers"], 1)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(cli, "app"))
        self.assertFalse(hasattr(cli, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard: instrument ``builtins.__import__``
        # so any actual import statement targeting ``api`` /
        # ``routes`` / ``routes.*`` is recorded — even when an earlier
        # suite already cached the target in ``sys.modules``.
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

        before_modules = set(sys.modules.keys())
        with patch("builtins.__import__", side_effect=tracing_import):
            cli.summarize_missing_tickers(db_path=self._tmp)
        new_modules = set(sys.modules.keys()) - before_modules
        newly_loaded_forbidden = sorted(
            m for m in new_modules if _is_forbidden(m)
        )

        self.assertEqual(
            forbidden_imports, [],
            f"forbidden imports: {forbidden_imports}",
        )
        self.assertEqual(
            newly_loaded_forbidden, [],
            f"forbidden modules loaded: {newly_loaded_forbidden}",
        )


if __name__ == "__main__":
    unittest.main()
