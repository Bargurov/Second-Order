"""Tests for ``scripts/archive_cleanup_candidate_ticker_readiness.py``.

Pin the read-only contract:

* The report exposes the documented top-level keyset:
  ``candidate_count``, ``tickers_present_count``,
  ``price_cache_present_count``, ``low_information_count``,
  ``examples``, ``recommended_next_action``.
* Aggregates reflect every candidate event in the archive — only
  ``examples`` is truncated by ``--limit``.
* The counts are scoped to *cleanup candidates*: events the candidate
  report did NOT flag never contribute to any of the four counts even
  when they carry tickers / cache / low_signal.
* Per-event flags collapse cleanly: missing ``market_tickers`` →
  ``has_market_tickers=False``, no cache row for the primary ticker
  → ``has_price_cache=False``, falsy / missing ``low_signal`` →
  ``low_information=False``.
* Patchable seam works two ways: a ``candidate_report=`` kwarg and a
  ``patch.object(plan._candidate_report, "summarize_cleanup_candidates")``
  intercept.
* Read-only: repeated runs leave events byte-identical; only SELECT
  statements reach sqlite3.
* ``recommended_next_action`` is a closed two-string vocabulary.
* Source pins forbid destructive SQL, paid seams, FastAPI surface,
  and filesystem destructors.
* CLI plumbing: ``--json``, ``--limit``, ``--db-path``,
  ``--fixture-timestamp-threshold``.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import archive_cleanup_candidate_ticker_readiness as readiness  # noqa: E402


_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    timestamp       TEXT,
    event_date      TEXT,
    market_tickers  TEXT,
    low_signal      INTEGER DEFAULT 0
)
""".strip()


_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker       TEXT,
    date         TEXT,
    close        REAL,
    volume       INTEGER,
    auto_adjust  INTEGER,
    fetched_at   TEXT
)
""".strip()


_TOP_KEYS: tuple[str, ...] = (
    "candidate_count",
    "tickers_present_count",
    "price_cache_present_count",
    "low_information_count",
    "examples",
    "recommended_next_action",
)


_EXAMPLE_KEYS: tuple[str, ...] = (
    "event_id",
    "headline",
    "primary_ticker",
    "has_market_tickers",
    "has_price_cache",
    "low_information",
    "reasons",
)


def _seed_event(
    conn: sqlite3.Connection,
    *,
    headline: str | None = "headline",
    timestamp: str | None = "2026-04-01T10:00:00",
    event_date: str | None = "2026-04-01",
    market_tickers: str | None = None,
    low_signal: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO events (headline, timestamp, event_date, "
        "market_tickers, low_signal) VALUES (?, ?, ?, ?, ?)",
        (headline, timestamp, event_date, market_tickers, low_signal),
    )
    return int(cur.lastrowid)


def _seed_cache_row(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    date: str = "2026-04-01",
) -> None:
    conn.execute(
        "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, date, 100.0, 1000, 0, "2026-05-01T00:00:00Z"),
    )


def _market_tickers(*symbols: str) -> str:
    return json.dumps([{"symbol": s, "role": "beneficiary"} for s in symbols])


def _snapshot_events(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute(
            "SELECT id, headline, timestamp, event_date, "
            "market_tickers, low_signal FROM events ORDER BY id"
        ))


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_acctr_{uuid.uuid4().hex}.db",
        )
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.commit()

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._tmp)


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


class TestReportShape(_Base):
    def test_returns_dict_with_top_keyset(self) -> None:
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_count_fields_are_non_negative_ints(self) -> None:
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        for key in (
            "candidate_count",
            "tickers_present_count",
            "price_cache_present_count",
            "low_information_count",
        ):
            self.assertIsInstance(result[key], int)
            self.assertGreaterEqual(result[key], 0)

    def test_examples_is_list_of_dicts_with_required_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(len(result["examples"]), 1)
        for entry in result["examples"]:
            for key in _EXAMPLE_KEYS:
                self.assertIn(key, entry, f"missing example key: {key}")


# ---------------------------------------------------------------------------
# Empty / clean archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(_Base):
    def test_clean_archive_yields_zero_counts(self) -> None:
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["tickers_present_count"], 0)
        self.assertEqual(result["price_cache_present_count"], 0)
        self.assertEqual(result["low_information_count"], 0)
        self.assertEqual(result["examples"], [])

    def test_clean_archive_recommends_ok(self) -> None:
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], readiness._RECOMMENDED_OK,
        )

    def test_archive_with_only_non_candidates_yields_zero(self) -> None:
        # Real news headline → not a candidate.  Even with tickers and
        # cache present, the report stays zero across the four counts.
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Real news headline",
                market_tickers=_market_tickers("AAPL"),
            )
            _seed_cache_row(conn, ticker="AAPL")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["tickers_present_count"], 0)
        self.assertEqual(result["price_cache_present_count"], 0)
        self.assertEqual(result["low_information_count"], 0)


# ---------------------------------------------------------------------------
# Tickers-present count
# ---------------------------------------------------------------------------


class TestTickersPresentCount(_Base):
    def test_candidate_with_tickers_increments_count(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=_market_tickers("AAPL", "MSFT"),
            )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["tickers_present_count"], 1)
        entry = result["examples"][0]
        self.assertTrue(entry["has_market_tickers"])
        self.assertEqual(entry["primary_ticker"], "AAPL")

    def test_candidate_without_tickers_does_not_increment(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=None,
            )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["tickers_present_count"], 0)
        entry = result["examples"][0]
        self.assertFalse(entry["has_market_tickers"])
        self.assertIsNone(entry["primary_ticker"])

    def test_candidate_with_empty_list_does_not_increment(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers="[]",
            )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["tickers_present_count"], 0)

    def test_count_only_tracks_candidates_not_full_archive(self) -> None:
        # Two real (non-candidate) events with tickers + one candidate
        # without tickers: the count is 0, not 2.  Distinct timestamps
        # so only test_fixture_phrase trips for the third row —
        # otherwise the shared default timestamp would land all three
        # in fixture_timestamp_cluster.
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Real news headline",
                timestamp="2026-04-01T08:00:00",
                event_date="2026-04-01",
                market_tickers=_market_tickers("AAPL"),
            )
            _seed_event(
                conn,
                headline="Another real headline",
                timestamp="2026-04-02T09:00:00",
                event_date="2026-04-02",
                market_tickers=_market_tickers("MSFT"),
            )
            _seed_event(
                conn,
                headline="Macro shock test event",
                timestamp="2026-04-03T10:00:00",
                event_date="2026-04-03",
                market_tickers=None,
            )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["tickers_present_count"], 0)


# ---------------------------------------------------------------------------
# Price-cache-present count
# ---------------------------------------------------------------------------


class TestPriceCachePresentCount(_Base):
    def test_candidate_primary_ticker_in_cache_increments(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=_market_tickers("TSLA"),
            )
            _seed_cache_row(conn, ticker="TSLA")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["price_cache_present_count"], 1)
        self.assertTrue(result["examples"][0]["has_price_cache"])

    def test_candidate_with_tickers_but_no_cache_row(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=_market_tickers("ZZZ"),
            )
            # No cache row for ZZZ.
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["tickers_present_count"], 1)
        self.assertEqual(result["price_cache_present_count"], 0)
        self.assertFalse(result["examples"][0]["has_price_cache"])

    def test_cache_lookup_is_case_insensitive(self) -> None:
        # Operators have stored cache tickers as lower-case in the
        # past; the readiness check upper-cases both sides before
        # comparison.
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=_market_tickers("tsla"),
            )
            _seed_cache_row(conn, ticker="TSLA")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["price_cache_present_count"], 1)

    def test_cache_for_non_candidate_ticker_does_not_count(self) -> None:
        # Cache rows for tickers no candidate references must not
        # leak into ``price_cache_present_count``.
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=_market_tickers("ZZZ"),
            )
            _seed_cache_row(conn, ticker="AAPL")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["price_cache_present_count"], 0)


# ---------------------------------------------------------------------------
# Low-information count
# ---------------------------------------------------------------------------


class TestLowInformationCount(_Base):
    def test_candidate_with_low_signal_one_increments(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                low_signal=1,
            )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["low_information_count"], 1)
        self.assertTrue(result["examples"][0]["low_information"])

    def test_candidate_with_low_signal_zero_does_not_increment(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                low_signal=0,
            )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["low_information_count"], 0)
        self.assertFalse(result["examples"][0]["low_information"])

    def test_low_signal_never_attributed_to_non_candidates(self) -> None:
        with self._conn() as conn:
            # Non-candidate but low_signal=1.
            _seed_event(
                conn,
                headline="Real news headline",
                low_signal=1,
            )
            # Candidate but low_signal=0.
            _seed_event(
                conn,
                headline="Macro shock test event",
                low_signal=0,
            )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["low_information_count"], 0)


# ---------------------------------------------------------------------------
# Limit truncation
# ---------------------------------------------------------------------------


class TestLimitTruncation(_Base):
    def test_limit_caps_examples_but_not_aggregates(self) -> None:
        with self._conn() as conn:
            for i in range(8):
                _seed_event(
                    conn,
                    headline="Macro shock test event",
                    timestamp=f"2026-04-01T{10 + i:02d}:00:00",
                    event_date=f"2026-04-{1 + i:02d}",
                    market_tickers=_market_tickers(f"TKR{i}"),
                )
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(
            db_path=self._tmp, limit=3,
        )
        self.assertEqual(result["candidate_count"], 8)
        self.assertEqual(result["tickers_present_count"], 8)
        self.assertEqual(len(result["examples"]), 3)

    def test_limit_zero_emits_no_examples(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(
            db_path=self._tmp, limit=0,
        )
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["examples"], [])

    def test_negative_limit_clamped_to_zero(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(
            db_path=self._tmp, limit=-7,
        )
        self.assertEqual(result["examples"], [])


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


class TestPatchableSeam(_Base):
    def test_candidate_report_kwarg_overrides_db_call(self) -> None:
        # Seed one candidate row in the events table so the per-event
        # SELECT can resolve metadata for the injected event_id.
        with self._conn() as conn:
            seeded_id = _seed_event(
                conn,
                headline="seeded fixture event",
                market_tickers=_market_tickers("AAPL"),
            )
            _seed_cache_row(conn, ticker="AAPL")
            conn.commit()

        injected = {
            "candidate_count": 1,
            "reasons": {
                "test_fixture_phrase": 1,
                "rotating_macro_template": 0,
                "fixture_timestamp_cluster": 0,
                "duplicate_headline_event_date": 0,
            },
            "examples": [
                {
                    "event_id":   seeded_id,
                    "headline":   "ignored — overridden by per-event SELECT",
                    "timestamp":  "2026-04-01T10:00:00",
                    "event_date": "2026-04-01",
                    "reasons":    ["test_fixture_phrase"],
                },
            ],
            "fixture_timestamp_threshold": 3,
            "recommended_next_action": "anything",
        }

        def _explode(*_a, **_kw):  # pragma: no cover — must not run
            raise AssertionError(
                "summarize_cleanup_candidates was called despite "
                "explicit candidate_report kwarg"
            )

        with patch.object(
            readiness._candidate_report,
            "summarize_cleanup_candidates",
            side_effect=_explode,
        ):
            result = readiness.summarize_candidate_ticker_readiness(
                db_path=self._tmp,
                candidate_report=injected,
            )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["tickers_present_count"], 1)
        self.assertEqual(result["price_cache_present_count"], 1)
        self.assertEqual(result["examples"][0]["event_id"], seeded_id)
        self.assertEqual(result["examples"][0]["primary_ticker"], "AAPL")

    def test_module_attribute_patch_intercepts_underlying_call(self) -> None:
        # Seed a real event so per-event metadata resolves.
        with self._conn() as conn:
            seeded_id = _seed_event(
                conn,
                headline="seeded fixture event",
                market_tickers=_market_tickers("MSFT"),
                low_signal=1,
            )
            conn.commit()

        fake_report = {
            "candidate_count": 1,
            "reasons": {
                "test_fixture_phrase": 0,
                "rotating_macro_template": 1,
                "fixture_timestamp_cluster": 0,
                "duplicate_headline_event_date": 0,
            },
            "examples": [
                {
                    "event_id":   seeded_id,
                    "headline":   "ignored",
                    "timestamp":  "2026-04-01T10:00:00",
                    "event_date": "2026-04-01",
                    "reasons":    ["rotating_macro_template"],
                },
            ],
            "fixture_timestamp_threshold": 3,
            "recommended_next_action": "anything",
        }

        with patch.object(
            readiness._candidate_report,
            "summarize_cleanup_candidates",
            return_value=fake_report,
        ):
            result = readiness.summarize_candidate_ticker_readiness(
                db_path=self._tmp,
            )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["tickers_present_count"], 1)
        self.assertEqual(result["low_information_count"], 1)
        self.assertEqual(
            result["examples"][0]["reasons"], ["rotating_macro_template"],
        )


# ---------------------------------------------------------------------------
# Read-only contract
# ---------------------------------------------------------------------------


class TestReadOnlyContract(_Base):
    def test_repeated_runs_leave_events_byte_identical(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            _seed_event(
                conn,
                headline="Real news headline",
                event_date="2026-04-15",
                market_tickers=_market_tickers("AAPL"),
            )
            _seed_cache_row(conn, ticker="AAPL")
            conn.commit()
        before = _snapshot_events(self._tmp)
        for _ in range(3):
            readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        after = _snapshot_events(self._tmp)
        self.assertEqual(before, after)

    def test_only_select_statements_reach_sqlite(self) -> None:
        # End-to-end: while the report runs, every SQL statement that
        # reaches sqlite3 must be a SELECT.  Catches a future regression
        # where the report grows its own write SQL.
        statements: list[str] = []
        real_connect = sqlite3.connect

        def _wrapper(path: str, *args, **kwargs):
            conn = real_connect(path, *args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn

        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=_market_tickers("AAPL"),
            )
            _seed_cache_row(conn, ticker="AAPL")
            conn.commit()

        with patch.object(sqlite3, "connect", _wrapper):
            readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)

        self.assertGreater(
            len(statements), 0,
            "expected at least one SQL statement during the readiness run",
        )
        for sql in statements:
            head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
            self.assertEqual(
                head, "SELECT",
                f"non-SELECT statement issued during readiness: {sql!r}",
            )


# ---------------------------------------------------------------------------
# Source pins
# ---------------------------------------------------------------------------


class TestSourcePins(unittest.TestCase):
    def setUp(self) -> None:
        self._src = Path(readiness.__file__).read_text(encoding="utf-8")

    def test_module_source_has_no_destructive_sql(self) -> None:
        forbidden = (
            r"\bDELETE\s+FROM\b",
            r"\bUPDATE\s+\w+\s+SET\b",
            r"\bINSERT\s+INTO\b",
            r"\bDROP\s+TABLE\b",
            r"\bTRUNCATE\s+TABLE\b",
            r"\bALTER\s+TABLE\b",
        )
        for pat in forbidden:
            self.assertIsNone(
                re.search(pat, self._src, flags=re.IGNORECASE),
                f"forbidden destructive SQL {pat!r} in readiness module",
            )

    def test_module_source_does_not_import_paid_seams(self) -> None:
        for pat in (
            r"^\s*import\s+yfinance\b",
            r"^\s*from\s+yfinance\b",
            r"^\s*import\s+market_check\b",
            r"^\s*from\s+market_check\b",
            r"^\s*import\s+market_data\b",
            r"^\s*from\s+market_data\b",
            r"^\s*import\s+price_cache\b",
            r"^\s*from\s+price_cache\b",
            r"^\s*from\s+anthropic\b",
            r"^\s*import\s+anthropic\b",
            r"^\s*import\s+openai\b",
            r"^\s*from\s+openai\b",
            r"^\s*import\s+api\b",
            r"^\s*from\s+api\b",
            r"^\s*from\s+routes\.",
            r"^\s*import\s+routes\.",
            r"^\s*from\s+analyze_event\b",
            r"^\s*import\s+analyze_event\b",
        ):
            self.assertIsNone(
                re.search(pat, self._src, flags=re.MULTILINE),
                f"forbidden import pattern {pat!r} in readiness module",
            )

    def test_module_source_does_not_call_filesystem_destructors(self) -> None:
        for pat in (
            r"\bos\.remove\s*\(",
            r"\bos\.unlink\s*\(",
            r"\bshutil\.rmtree\s*\(",
            r"\.unlink\s*\(",
        ):
            self.assertIsNone(
                re.search(pat, self._src),
                f"filesystem destructor pattern {pat!r} in readiness module",
            )


# ---------------------------------------------------------------------------
# Recommended-next-action vocabulary
# ---------------------------------------------------------------------------


class TestRecommendedNextActionVocabulary(_Base):
    def test_zero_candidates_recommends_ok(self) -> None:
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], readiness._RECOMMENDED_OK,
        )

    def test_any_candidate_recommends_review(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = readiness.summarize_candidate_ticker_readiness(db_path=self._tmp)
        self.assertEqual(
            result["recommended_next_action"], readiness._RECOMMENDED_REVIEW,
        )

    def test_recommended_review_explicitly_disclaims_writes(self) -> None:
        # The closed-vocabulary string must explicitly say this script
        # makes no DB writes — so an operator reading the JSON does
        # not assume the report performs deletion.
        self.assertIn("no DB writes", readiness._RECOMMENDED_REVIEW)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCliPlumbing(_Base):
    def test_main_default_returns_zero_and_prints_text(self) -> None:
        out = StringIO()
        code = readiness.main(["--db-path", self._tmp], out=out)
        self.assertEqual(code, 0)
        self.assertIn("ticker readiness", out.getvalue().lower())

    def test_main_json_emits_parseable_payload(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="Macro shock test event",
                market_tickers=_market_tickers("AAPL"),
                low_signal=1,
            )
            _seed_cache_row(conn, ticker="AAPL")
            conn.commit()
        out = StringIO()
        code = readiness.main(["--db-path", self._tmp, "--json"], out=out)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        for key in _TOP_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["tickers_present_count"], 1)
        self.assertEqual(payload["price_cache_present_count"], 1)
        self.assertEqual(payload["low_information_count"], 1)

    def test_main_limit_truncates_examples_only(self) -> None:
        with self._conn() as conn:
            for i in range(5):
                _seed_event(
                    conn,
                    headline="Macro shock test event",
                    timestamp=f"2026-04-01T{10 + i:02d}:00:00",
                    event_date=f"2026-04-{1 + i:02d}",
                )
            conn.commit()
        out = StringIO()
        code = readiness.main(
            ["--db-path", self._tmp, "--json", "--limit", "2"], out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["candidate_count"], 5)
        self.assertEqual(len(payload["examples"]), 2)

    def test_main_fixture_timestamp_threshold_flag(self) -> None:
        # Two rows sharing a timestamp → with threshold=2 they trip
        # fixture_timestamp_cluster and become candidates.
        with self._conn() as conn:
            _seed_event(
                conn,
                headline="A",
                timestamp="2026-04-15T10:00:00",
                event_date="2026-04-15",
            )
            _seed_event(
                conn,
                headline="B",
                timestamp="2026-04-15T10:00:00",
                event_date="2026-04-15",
            )
            conn.commit()
        out = StringIO()
        code = readiness.main(
            [
                "--db-path", self._tmp, "--json",
                "--fixture-timestamp-threshold", "2",
            ],
            out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        # The two events are now candidates via fixture_timestamp_cluster
        # (they also collide on (headline, event_date)? No — different
        # headlines).  candidate_count must reflect the cluster.
        self.assertGreaterEqual(payload["candidate_count"], 2)


# ---------------------------------------------------------------------------
# Live archive sanity — opt-in
# ---------------------------------------------------------------------------


class TestLiveArchiveSanity(unittest.TestCase):
    """If the project's ``events.db`` is present, the readiness report
    must run against it without raising and produce a well-formed
    payload.  Skipped when the DB file is absent so CI stays portable.
    """

    def setUp(self) -> None:
        self._project_root = Path(__file__).resolve().parents[1]
        self._db = self._project_root / "events.db"
        if not self._db.exists():
            self.skipTest(f"no live archive at {self._db}")

    def test_live_archive_produces_well_formed_report(self) -> None:
        before_mtime = self._db.stat().st_mtime
        result = readiness.summarize_candidate_ticker_readiness(
            db_path=str(self._db),
        )
        for key in _TOP_KEYS:
            self.assertIn(key, result)
        self.assertGreaterEqual(
            result["tickers_present_count"], 0,
        )
        self.assertLessEqual(
            result["tickers_present_count"], result["candidate_count"],
        )
        self.assertLessEqual(
            result["price_cache_present_count"],
            result["tickers_present_count"],
        )
        self.assertLessEqual(
            result["low_information_count"], result["candidate_count"],
        )
        # Read-only against the live DB: mtime must not move.
        self.assertEqual(self._db.stat().st_mtime, before_mtime)


if __name__ == "__main__":
    unittest.main()
