"""Tests for ``routes/archive_diagnostics.py`` — archive consistency audit.

The diagnostic is a pure read over the local SQLite ``events`` table that
surfaces malformed / missing fields and duplicate ``(headline,
event_date)`` clusters.  Tests use temp SQLite fixtures so no live
archive is touched.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.archive_diagnostics import compute_archive_consistency  # noqa: E402


_TEST_SCHEMA = """
CREATE TABLE events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT,
    headline       TEXT,
    market_tickers TEXT,
    event_date     TEXT
)
"""


_CATEGORIES: tuple[str, ...] = (
    "malformed_market_tickers_json",
    "missing_headline",
    "missing_timestamp",
    "missing_event_date",
    "malformed_event_date",
    "missing_market_tickers",
    "duplicate_headline_event_date_clusters",
)


def _tmp_db_path() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_archive_diag_{uuid.uuid4().hex}.db",
    )


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.path = _tmp_db_path()
        with sqlite3.connect(self.path) as conn:
            conn.execute(_TEST_SCHEMA)
            conn.commit()

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except (OSError, PermissionError):
            pass

    def _good_row(self, **overrides) -> dict:
        defaults = {
            "timestamp":      "2026-04-15T10:00:00",
            "headline":       "Good headline",
            "market_tickers": "[]",
            "event_date":     "2026-04-15",
        }
        defaults.update(overrides)
        return defaults

    def _insert(self, **fields) -> int:
        cols = list(fields.keys())
        vals = [fields[k] for k in cols]
        placeholders = ",".join("?" * len(cols))
        col_names = ",".join(cols)
        with sqlite3.connect(self.path) as conn:
            cur = conn.execute(
                f"INSERT INTO events ({col_names}) VALUES ({placeholders})",
                vals,
            )
            conn.commit()
            return int(cur.lastrowid)

    def _result(self) -> dict:
        return compute_archive_consistency(db_path=self.path)


class TestEmpty(_Base):
    def test_empty_table_returns_zero_counts_in_all_categories(self) -> None:
        result = self._result()
        for category in _CATEGORIES:
            self.assertEqual(result[category]["count"], 0, category)
            self.assertEqual(result[category]["examples"], [], category)

    def test_response_includes_all_seven_categories(self) -> None:
        result = self._result()
        self.assertEqual(set(result.keys()), set(_CATEGORIES))


class TestMissingHeadline(_Base):
    def test_null_headline_counted(self) -> None:
        eid = self._insert(**self._good_row(headline=None))
        cat = self._result()["missing_headline"]
        self.assertEqual(cat["count"], 1)
        self.assertEqual(cat["examples"][0]["event_id"], eid)

    def test_empty_headline_counted(self) -> None:
        self._insert(**self._good_row(headline=""))
        cat = self._result()["missing_headline"]
        self.assertEqual(cat["count"], 1)

    def test_whitespace_only_headline_counted_as_missing(self) -> None:
        self._insert(**self._good_row(headline="   "))
        cat = self._result()["missing_headline"]
        self.assertEqual(cat["count"], 1)

    def test_good_headline_not_counted(self) -> None:
        self._insert(**self._good_row())
        cat = self._result()["missing_headline"]
        self.assertEqual(cat["count"], 0)


class TestMissingTimestamp(_Base):
    def test_null_and_empty_timestamps_both_counted(self) -> None:
        self._insert(**self._good_row(timestamp=None))
        self._insert(**self._good_row(timestamp=""))
        cat = self._result()["missing_timestamp"]
        self.assertEqual(cat["count"], 2)

    def test_whitespace_only_timestamp_counted_as_missing(self) -> None:
        self._insert(**self._good_row(timestamp="   "))
        cat = self._result()["missing_timestamp"]
        self.assertEqual(cat["count"], 1)


class TestEventDate(_Base):
    def test_null_event_date_is_missing_not_malformed(self) -> None:
        self._insert(**self._good_row(event_date=None))
        result = self._result()
        self.assertEqual(result["missing_event_date"]["count"], 1)
        self.assertEqual(result["malformed_event_date"]["count"], 0)

    def test_empty_event_date_is_missing_not_malformed(self) -> None:
        self._insert(**self._good_row(event_date=""))
        result = self._result()
        self.assertEqual(result["missing_event_date"]["count"], 1)
        self.assertEqual(result["malformed_event_date"]["count"], 0)

    def test_unparseable_event_date_is_malformed(self) -> None:
        self._insert(**self._good_row(event_date="not-a-date"))
        self._insert(**self._good_row(event_date="2026-13-99"))
        self._insert(**self._good_row(event_date="15/04/2026"))
        result = self._result()
        self.assertEqual(result["missing_event_date"]["count"], 0)
        self.assertEqual(result["malformed_event_date"]["count"], 3)

    def test_iso_event_date_passes_neither_check(self) -> None:
        self._insert(**self._good_row(event_date="2026-04-15"))
        result = self._result()
        self.assertEqual(result["missing_event_date"]["count"], 0)
        self.assertEqual(result["malformed_event_date"]["count"], 0)

    def test_iso_datetime_string_event_date_passes(self) -> None:
        # ``event_date`` may legitimately carry a full ISO timestamp on
        # some legacy rows; the date prefix must parse.
        self._insert(**self._good_row(event_date="2026-04-15T10:00:00"))
        result = self._result()
        self.assertEqual(result["malformed_event_date"]["count"], 0)
        self.assertEqual(result["missing_event_date"]["count"], 0)


class TestMarketTickers(_Base):
    def test_null_market_tickers_is_missing(self) -> None:
        self._insert(**self._good_row(market_tickers=None))
        result = self._result()
        self.assertEqual(result["missing_market_tickers"]["count"], 1)
        self.assertEqual(result["malformed_market_tickers_json"]["count"], 0)

    def test_empty_string_market_tickers_is_missing(self) -> None:
        self._insert(**self._good_row(market_tickers=""))
        result = self._result()
        self.assertEqual(result["missing_market_tickers"]["count"], 1)
        self.assertEqual(result["malformed_market_tickers_json"]["count"], 0)

    def test_empty_list_market_tickers_is_neither(self) -> None:
        self._insert(**self._good_row(market_tickers="[]"))
        result = self._result()
        self.assertEqual(result["missing_market_tickers"]["count"], 0)
        self.assertEqual(result["malformed_market_tickers_json"]["count"], 0)

    def test_unparseable_market_tickers_is_malformed(self) -> None:
        self._insert(**self._good_row(market_tickers="not json"))
        self._insert(**self._good_row(market_tickers="[broken"))
        result = self._result()
        self.assertEqual(result["malformed_market_tickers_json"]["count"], 2)
        self.assertEqual(result["missing_market_tickers"]["count"], 0)

    def test_non_list_json_market_tickers_is_malformed(self) -> None:
        # The schema treats market_tickers as a JSON list; parseable
        # but non-list values are unusable downstream.
        self._insert(**self._good_row(market_tickers='{"AAPL": 1}'))
        self._insert(**self._good_row(market_tickers="42"))
        result = self._result()
        self.assertEqual(result["malformed_market_tickers_json"]["count"], 2)

    def test_valid_list_market_tickers_passes(self) -> None:
        self._insert(**self._good_row(market_tickers='[{"symbol":"AAPL"}]'))
        result = self._result()
        self.assertEqual(result["malformed_market_tickers_json"]["count"], 0)
        self.assertEqual(result["missing_market_tickers"]["count"], 0)


class TestDuplicateClusters(_Base):
    def test_two_rows_with_same_headline_and_event_date_form_one_cluster(self) -> None:
        eid_a = self._insert(**self._good_row(
            headline="Same news", event_date="2026-04-15",
        ))
        eid_b = self._insert(**self._good_row(
            headline="Same news", event_date="2026-04-15",
        ))
        cat = self._result()["duplicate_headline_event_date_clusters"]
        self.assertEqual(cat["count"], 1)
        self.assertEqual(len(cat["examples"]), 1)
        ex = cat["examples"][0]
        self.assertEqual(ex["headline"], "Same news")
        self.assertEqual(ex["event_date"], "2026-04-15")
        self.assertEqual(ex["count"], 2)
        self.assertEqual(sorted(ex["event_ids"]), sorted([eid_a, eid_b]))

    def test_distinct_pairs_form_no_cluster(self) -> None:
        self._insert(**self._good_row(headline="A", event_date="2026-04-15"))
        self._insert(**self._good_row(headline="B", event_date="2026-04-15"))
        self._insert(**self._good_row(headline="A", event_date="2026-04-16"))
        cat = self._result()["duplicate_headline_event_date_clusters"]
        self.assertEqual(cat["count"], 0)

    def test_null_or_empty_headline_excluded_from_clusters(self) -> None:
        # A pair of rows with NULL or empty headline are flagged by the
        # missing_headline category; they must not also surface as a
        # duplicate cluster (which would be noise).
        self._insert(**self._good_row(headline=None, event_date="2026-04-15"))
        self._insert(**self._good_row(headline=None, event_date="2026-04-15"))
        self._insert(**self._good_row(headline="",   event_date="2026-04-16"))
        self._insert(**self._good_row(headline="",   event_date="2026-04-16"))
        cat = self._result()["duplicate_headline_event_date_clusters"]
        self.assertEqual(cat["count"], 0)

    def test_null_or_empty_event_date_excluded_from_clusters(self) -> None:
        self._insert(**self._good_row(headline="X", event_date=None))
        self._insert(**self._good_row(headline="X", event_date=None))
        self._insert(**self._good_row(headline="Y", event_date=""))
        self._insert(**self._good_row(headline="Y", event_date=""))
        cat = self._result()["duplicate_headline_event_date_clusters"]
        self.assertEqual(cat["count"], 0)

    def test_three_rows_same_pair_yield_one_cluster_with_count_three(self) -> None:
        for _ in range(3):
            self._insert(**self._good_row(
                headline="Triple", event_date="2026-04-15",
            ))
        cat = self._result()["duplicate_headline_event_date_clusters"]
        self.assertEqual(cat["count"], 1)
        self.assertEqual(cat["examples"][0]["count"], 3)
        self.assertEqual(len(cat["examples"][0]["event_ids"]), 3)


class TestExamplesCappedAt10(_Base):
    def test_more_than_ten_missing_event_date_caps_examples_at_ten(self) -> None:
        for i in range(15):
            self._insert(
                timestamp="2026-04-15T10:00:00",
                headline=f"Row {i}",
                market_tickers="[]",
                event_date=None,
            )
        cat = self._result()["missing_event_date"]
        self.assertEqual(cat["count"], 15)
        self.assertEqual(len(cat["examples"]), 10)

    def test_more_than_ten_duplicate_clusters_caps_examples_at_ten(self) -> None:
        for i in range(12):
            for _ in range(2):
                self._insert(**self._good_row(
                    headline=f"Dup {i}", event_date="2026-04-15",
                ))
        cat = self._result()["duplicate_headline_event_date_clusters"]
        self.assertEqual(cat["count"], 12)
        self.assertEqual(len(cat["examples"]), 10)


class TestExampleShape(_Base):
    def test_missing_headline_example_carries_event_id_and_timestamp(self) -> None:
        eid = self._insert(**self._good_row(headline="", timestamp="2026-04-15T10:00:00"))
        ex = self._result()["missing_headline"]["examples"][0]
        self.assertEqual(ex["event_id"], eid)
        self.assertEqual(ex["timestamp"], "2026-04-15T10:00:00")

    def test_malformed_event_date_example_carries_bad_value(self) -> None:
        self._insert(**self._good_row(event_date="not-a-date"))
        ex = self._result()["malformed_event_date"]["examples"][0]
        self.assertEqual(ex["event_date"], "not-a-date")

    def test_malformed_market_tickers_example_carries_raw_value(self) -> None:
        self._insert(**self._good_row(market_tickers="not json"))
        ex = self._result()["malformed_market_tickers_json"]["examples"][0]
        self.assertEqual(ex["market_tickers"], "not json")


class TestMultiCategorySingleRow(_Base):
    def test_single_row_can_appear_in_multiple_categories(self) -> None:
        # A row with empty headline AND missing event_date AND null
        # market_tickers must contribute to all three categories.
        eid = self._insert(
            timestamp="",
            headline="",
            market_tickers=None,
            event_date=None,
        )
        result = self._result()
        for category in (
            "missing_headline",
            "missing_timestamp",
            "missing_event_date",
            "missing_market_tickers",
        ):
            cat = result[category]
            self.assertEqual(cat["count"], 1, category)
            self.assertEqual(cat["examples"][0]["event_id"], eid, category)


class TestNoWrites(_Base):
    def test_function_does_not_mutate_db(self) -> None:
        for i in range(6):
            self._insert(
                timestamp="2026-04-15T10:00:00",
                headline=f"H{i}" if i % 2 == 0 else "",
                market_tickers="bad json" if i % 3 == 0 else "[]",
                event_date=None if i == 0 else (
                    "2026-04-15" if i % 2 == 1 else "2026-13-99"
                ),
            )
        before = self._snapshot()
        compute_archive_consistency(db_path=self.path)
        after = self._snapshot()
        self.assertEqual(before, after)

    def _snapshot(self) -> list:
        with sqlite3.connect(self.path) as conn:
            return list(conn.execute(
                "SELECT id, timestamp, headline, market_tickers, event_date "
                "FROM events ORDER BY id"
            ))


class TestDefensiveFailures(unittest.TestCase):
    def test_nonexistent_db_path_returns_zero_counts(self) -> None:
        result = compute_archive_consistency(
            db_path=os.path.join(tempfile.gettempdir(),
                                 f"missing_{uuid.uuid4().hex}.db"),
        )
        for category in _CATEGORIES:
            self.assertEqual(result[category]["count"], 0, category)

    def test_db_without_events_table_returns_zero_counts(self) -> None:
        path = _tmp_db_path()
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE other (id INTEGER)")
            conn.commit()
        try:
            result = compute_archive_consistency(db_path=path)
            for category in _CATEGORIES:
                self.assertEqual(result[category]["count"], 0, category)
        finally:
            try:
                os.remove(path)
            except (OSError, PermissionError):
                pass


class TestRouterModule(unittest.TestCase):
    def test_module_exposes_router_with_archive_consistency_get(self) -> None:
        from fastapi import APIRouter

        from routes import archive_diagnostics

        self.assertIsInstance(archive_diagnostics.router, APIRouter)
        routes_by_path = {
            getattr(r, "path", None): getattr(r, "methods", set())
            for r in archive_diagnostics.router.routes
        }
        self.assertIn("/diagnostics/archive-consistency", routes_by_path)
        self.assertIn("GET", routes_by_path["/diagnostics/archive-consistency"])


# ---------------------------------------------------------------------------
# Public-mount regression: GET /diagnostics/archive-consistency through the
# live FastAPI app.  Exercises the include_router wiring in api.py and pins
# read-only behavior (no DB writes) and structural shape.
# ---------------------------------------------------------------------------


import db as _db  # noqa: E402


def _full_events_schema_path() -> str:
    """Bind db.DB_FILE to a fresh temp DB initialised by db.init_db().

    The route reads db.DB_FILE at request time, so swapping the global
    is enough to point the live handler at this isolated archive
    without touching any production state.
    """
    return os.path.join(
        tempfile.gettempdir(),
        f"test_archive_diag_app_{uuid.uuid4().hex}.db",
    )


def _snapshot_events(path: str) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return list(conn.execute(
            "SELECT id, timestamp, headline, market_tickers, event_date "
            "FROM events ORDER BY id"
        ))


class TestPublicMount(unittest.TestCase):
    """Regression: api.app must include the archive-diagnostics router and
    serve GET /diagnostics/archive-consistency with the documented shape."""

    @classmethod
    def setUpClass(cls) -> None:
        # Imported lazily so the rest of the module's pure-function
        # tests don't pay the api import cost.
        from fastapi.testclient import TestClient

        import api  # noqa: F401  (imported for app)

        cls._client = TestClient(api.app)

    def setUp(self) -> None:
        self._orig_db = _db.DB_FILE
        self._tmp = _full_events_schema_path()
        _db.DB_FILE = self._tmp
        _db._db_ready = False
        _db.init_db()

    def tearDown(self) -> None:
        _db.DB_FILE = self._orig_db
        _db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def test_get_returns_200_and_full_category_keyset(self) -> None:
        response = self._client.get("/diagnostics/archive-consistency")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body, dict)
        self.assertEqual(set(body.keys()), set(_CATEGORIES))
        for category in _CATEGORIES:
            self.assertIn("count",    body[category], category)
            self.assertIn("examples", body[category], category)

    def test_get_does_not_mutate_events_table(self) -> None:
        # Plant a row with a deliberate consistency issue so the
        # endpoint has work to do; then prove the GET request leaves
        # the table byte-identical.
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events "
                "(timestamp, headline, stage, persistence, "
                " market_tickers, event_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-04-15T10:00:00", "mount-regression seed",
                 "realized", "medium", "not json", None),
            )
            conn.commit()

        before = _snapshot_events(self._tmp)
        response = self._client.get("/diagnostics/archive-consistency")
        after = _snapshot_events(self._tmp)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)
        body = response.json()
        # Sanity: the seeded malformed_market_tickers row was surfaced
        # — proves the live handler is reading the bound DB, not a
        # cached/empty fallback.
        self.assertGreaterEqual(
            body["malformed_market_tickers_json"]["count"], 1,
        )
        self.assertGreaterEqual(
            body["missing_event_date"]["count"], 1,
        )


if __name__ == "__main__":
    unittest.main()
