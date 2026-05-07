"""Tests for ``scripts/duplicate_event_cluster_report.py``.

Pin the read-only contract:

* Cluster identification: rows where ``headline`` is non-empty AND
  ``event_date`` is non-empty cluster on the (headline, event_date)
  pair when count >= 2.  Rows with NULL/empty headline or event_date
  are excluded entirely.  Malformed-but-non-empty event_date strings
  are still grouped — the duplicate signal is "rows agreed on the
  same value", not "this value parses as a date".
* Aggregate fields: ``total_clusters``, ``total_rows_in_clusters``,
  ``largest_cluster_size`` always reflect the full clustering, not
  the truncated example list.
* ``--limit`` truncation: caps ``clusters`` at N without lowering the
  aggregate counts.
* ``--json`` and ``--db-path`` plumbing.
* No mutation: events table byte-identical across repeated runs.
* No provider, yfinance, market_check, market_data, price_cache,
  LLM, or FastAPI seam is invoked.
"""
from __future__ import annotations

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

from scripts import duplicate_event_cluster_report as report  # noqa: E402


# Hand-rolled minimal events DDL — the report only reads
# ``id``, ``headline``, ``event_date``.  Avoiding ``db.save_event``
# keeps the fixture decoupled from the production schema migrations
# and lets the tests pin the SQL contract directly.
_EVENTS_DDL = """
CREATE TABLE events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    headline   TEXT,
    event_date TEXT
)
""".strip()


_TOP_KEYS = (
    "total_clusters",
    "total_rows_in_clusters",
    "largest_cluster_size",
    "clusters",
    "recommended_next_action",
)

_CLUSTER_KEYS = (
    "headline",
    "event_date",
    "count",
    "event_ids",
)


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _seed(conn: sqlite3.Connection, *, headline, event_date) -> int:
    cur = conn.execute(
        "INSERT INTO events (headline, event_date) VALUES (?, ?)",
        (headline, event_date),
    )
    return int(cur.lastrowid)


def _snapshot_events(db_path: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_decr_{uuid.uuid4().hex}.db",
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


class TestReportShape(_Base):
    def test_returns_dict_with_top_keyset(self) -> None:
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_clusters_is_list(self) -> None:
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertIsInstance(result["clusters"], list)

    def test_recommended_next_action_is_non_empty_string(self) -> None:
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])


# ---------------------------------------------------------------------------
# No duplicates
# ---------------------------------------------------------------------------


class TestNoDuplicates(_Base):
    def test_empty_db_returns_zero_clusters(self) -> None:
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         0)
        self.assertEqual(result["total_rows_in_clusters"], 0)
        self.assertEqual(result["largest_cluster_size"],   0)
        self.assertEqual(result["clusters"],               [])
        self.assertIn("clean", result["recommended_next_action"])

    def test_unique_rows_yield_zero_clusters(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="beta",  event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-16")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         0)
        self.assertEqual(result["total_rows_in_clusters"], 0)
        self.assertEqual(result["largest_cluster_size"],   0)
        self.assertEqual(result["clusters"],               [])


# ---------------------------------------------------------------------------
# Duplicate clusters
# ---------------------------------------------------------------------------


class TestDuplicateClusters(_Base):
    def test_single_cluster_is_surfaced(self) -> None:
        with self._conn() as conn:
            id_a = _seed(conn, headline="ECB hike", event_date="2026-04-15")
            id_b = _seed(conn, headline="ECB hike", event_date="2026-04-15")
            id_c = _seed(conn, headline="ECB hike", event_date="2026-04-15")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         1)
        self.assertEqual(result["total_rows_in_clusters"], 3)
        self.assertEqual(result["largest_cluster_size"],   3)
        self.assertEqual(len(result["clusters"]),          1)
        cluster = result["clusters"][0]
        for key in _CLUSTER_KEYS:
            self.assertIn(key, cluster, f"cluster missing field: {key}")
        self.assertEqual(cluster["headline"],   "ECB hike")
        self.assertEqual(cluster["event_date"], "2026-04-15")
        self.assertEqual(cluster["count"],      3)
        self.assertEqual(cluster["event_ids"],  sorted([id_a, id_b, id_c]))

    def test_two_clusters_are_ordered_by_size_desc(self) -> None:
        with self._conn() as conn:
            # Smaller cluster first by id, but larger should sort first.
            _seed(conn, headline="small",  event_date="2026-04-15")
            _seed(conn, headline="small",  event_date="2026-04-15")
            _seed(conn, headline="bigger", event_date="2026-04-16")
            _seed(conn, headline="bigger", event_date="2026-04-16")
            _seed(conn, headline="bigger", event_date="2026-04-16")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         2)
        self.assertEqual(result["total_rows_in_clusters"], 5)
        self.assertEqual(result["largest_cluster_size"],   3)
        sizes = [c["count"] for c in result["clusters"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(result["clusters"][0]["headline"], "bigger")
        self.assertEqual(result["clusters"][1]["headline"], "small")

    def test_aggregate_counts_independent_of_limit(self) -> None:
        with self._conn() as conn:
            for letter in ("a", "b", "c", "d", "e"):
                _seed(conn, headline=f"hl-{letter}", event_date="2026-04-15")
                _seed(conn, headline=f"hl-{letter}", event_date="2026-04-15")
            conn.commit()
        capped = report.find_duplicate_clusters(db_path=self._tmp, limit=2)
        full   = report.find_duplicate_clusters(db_path=self._tmp, limit=99)
        self.assertEqual(capped["total_clusters"],         5)
        self.assertEqual(capped["total_rows_in_clusters"], 10)
        self.assertEqual(capped["largest_cluster_size"],   2)
        self.assertEqual(len(capped["clusters"]),          2)
        # Aggregate fields are identical across limits — only the
        # ``clusters`` list is truncated.
        self.assertEqual(capped["total_clusters"],
                         full["total_clusters"])
        self.assertEqual(capped["total_rows_in_clusters"],
                         full["total_rows_in_clusters"])
        self.assertEqual(capped["largest_cluster_size"],
                         full["largest_cluster_size"])
        self.assertEqual(len(full["clusters"]), 5)

    def test_event_ids_are_ascending(self) -> None:
        with self._conn() as conn:
            ids = [
                _seed(conn, headline="alpha", event_date="2026-04-15")
                for _ in range(4)
            ]
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(len(result["clusters"]), 1)
        self.assertEqual(
            result["clusters"][0]["event_ids"], sorted(ids),
        )

    def test_recommendation_flips_when_clusters_present(self) -> None:
        # Capture the empty-state recommendation off a freshly created
        # temp DB, then seed the suite's fixture and confirm the
        # recommendation moves to a distinct cluster-state string.
        empty_path = os.path.join(
            tempfile.gettempdir(),
            f"test_decr_rec_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(empty_path)
        try:
            conn.execute(_EVENTS_DDL)
            conn.commit()
        finally:
            conn.close()
        try:
            empty_msg = report.find_duplicate_clusters(
                db_path=empty_path,
            )["recommended_next_action"]
        finally:
            try:
                os.remove(empty_path)
            except (OSError, PermissionError):
                pass

        with self._conn() as conn:
            _seed(conn, headline="dupe", event_date="2026-04-15")
            _seed(conn, headline="dupe", event_date="2026-04-15")
            conn.commit()
        cluster_msg = report.find_duplicate_clusters(
            db_path=self._tmp,
        )["recommended_next_action"]

        self.assertNotEqual(empty_msg, cluster_msg)
        self.assertIn("Duplicate", cluster_msg)


# ---------------------------------------------------------------------------
# Exclusion rules
# ---------------------------------------------------------------------------


class TestNullEmptyHeadlineExcluded(_Base):
    def test_null_headline_pair_does_not_form_a_cluster(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline=None, event_date="2026-04-15")
            _seed(conn, headline=None, event_date="2026-04-15")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         0)
        self.assertEqual(result["total_rows_in_clusters"], 0)
        self.assertEqual(result["clusters"],               [])

    def test_empty_headline_pair_does_not_form_a_cluster(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="", event_date="2026-04-15")
            _seed(conn, headline="", event_date="2026-04-15")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         0)
        self.assertEqual(result["total_rows_in_clusters"], 0)
        self.assertEqual(result["clusters"],               [])

    def test_mixed_null_headline_does_not_pollute_real_cluster(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline=None,    event_date="2026-04-15")
            _seed(conn, headline="",      event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         1)
        self.assertEqual(result["total_rows_in_clusters"], 2)
        self.assertEqual(result["clusters"][0]["headline"], "alpha")


class TestNullEmptyEventDateExcluded(_Base):
    def test_null_event_date_pair_does_not_form_a_cluster(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date=None)
            _seed(conn, headline="alpha", event_date=None)
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         0)
        self.assertEqual(result["total_rows_in_clusters"], 0)
        self.assertEqual(result["clusters"],               [])

    def test_empty_event_date_pair_does_not_form_a_cluster(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="")
            _seed(conn, headline="alpha", event_date="")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         0)
        self.assertEqual(result["total_rows_in_clusters"], 0)
        self.assertEqual(result["clusters"],               [])

    def test_mixed_null_event_date_does_not_pollute_real_cluster(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date=None)
            _seed(conn, headline="alpha", event_date="")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],          1)
        self.assertEqual(result["total_rows_in_clusters"],  2)
        self.assertEqual(
            result["clusters"][0]["event_date"], "2026-04-15",
        )


# ---------------------------------------------------------------------------
# Malformed event_date still groups
# ---------------------------------------------------------------------------


class TestMalformedEventDateGrouped(_Base):
    def test_unparseable_event_date_still_clusters_when_non_empty(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="not-a-date")
            _seed(conn, headline="alpha", event_date="not-a-date")
            _seed(conn, headline="alpha", event_date="not-a-date")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         1)
        self.assertEqual(result["total_rows_in_clusters"], 3)
        self.assertEqual(result["clusters"][0]["event_date"], "not-a-date")
        self.assertEqual(result["clusters"][0]["count"],      3)

    def test_malformed_and_iso_with_same_headline_do_not_collapse(self) -> None:
        # Two distinct event_date values must produce two distinct
        # cluster entries even when the headline matches.
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="not-a-date")
            _seed(conn, headline="alpha", event_date="not-a-date")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            conn.commit()
        result = report.find_duplicate_clusters(db_path=self._tmp)
        self.assertEqual(result["total_clusters"],         2)
        self.assertEqual(result["total_rows_in_clusters"], 4)
        event_dates = sorted(c["event_date"] for c in result["clusters"])
        self.assertEqual(event_dates, ["2026-04-15", "not-a-date"])


# ---------------------------------------------------------------------------
# No mutation
# ---------------------------------------------------------------------------


class TestNoMutation(_Base):
    def test_repeated_calls_leave_events_byte_identical(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="beta",  event_date="2026-04-16")
            _seed(conn, headline=None,    event_date="2026-04-15")
            _seed(conn, headline="gamma", event_date="")
            conn.commit()

        before = _snapshot_events(self._tmp)
        for _ in range(3):
            report.find_duplicate_clusters(db_path=self._tmp)
        after = _snapshot_events(self._tmp)
        self.assertEqual(
            before, after,
            "events table must be byte-identical across repeated runs",
        )


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_Base):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            conn.commit()

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
                        f"duplicate_event_cluster_report must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "duplicate_event_cluster_report must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            result = report.find_duplicate_clusters(db_path=self._tmp)

        self.assertEqual(result["total_clusters"], 1)
        self.assertEqual(result["total_rows_in_clusters"], 2)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(report, "app"))
        self.assertFalse(hasattr(report, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard: instrument ``builtins.__import__``
        # for the duration of ``find_duplicate_clusters`` so any actual
        # import statement targeting ``api`` / ``routes`` / ``routes.*``
        # is recorded — even when an earlier suite already cached the
        # target in ``sys.modules``.
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

        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            conn.commit()

        before_modules = set(sys.modules.keys())
        with patch("builtins.__import__", side_effect=tracing_import):
            report.find_duplicate_clusters(db_path=self._tmp)
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


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(_Base):
    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = report.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()

    def test_cli_text_output_summarises_each_field(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            conn.commit()
        rc, output = self._run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        for needle in (
            "Total clusters",
            "Total rows in clusters",
            "Largest cluster size",
            "Recommended next action",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")

    def test_cli_json_output_carries_required_keys(self) -> None:
        with self._conn() as conn:
            _seed(conn, headline="alpha", event_date="2026-04-15")
            _seed(conn, headline="alpha", event_date="2026-04-15")
            conn.commit()
        rc, output = self._run_cli([
            "--db-path", self._tmp,
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing JSON key: {key}")
        self.assertEqual(body["total_clusters"],         1)
        self.assertEqual(body["total_rows_in_clusters"], 2)
        self.assertEqual(body["largest_cluster_size"],   2)
        self.assertEqual(len(body["clusters"]),          1)

    def test_cli_limit_truncates_clusters_only(self) -> None:
        with self._conn() as conn:
            for letter in ("a", "b", "c"):
                _seed(conn, headline=f"hl-{letter}", event_date="2026-04-15")
                _seed(conn, headline=f"hl-{letter}", event_date="2026-04-15")
            conn.commit()
        rc, output = self._run_cli([
            "--db-path", self._tmp,
            "--limit",   "1",
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_clusters"],         3)
        self.assertEqual(body["total_rows_in_clusters"], 6)
        self.assertEqual(len(body["clusters"]),          1)

    def test_cli_db_path_resolves_supplied_archive(self) -> None:
        # Default db.DB_FILE points at the project's events.db.  Pass a
        # standalone temp DB explicitly and confirm the report walks
        # only that file.
        empty = os.path.join(
            tempfile.gettempdir(),
            f"test_decr_alt_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(empty)
        try:
            conn.execute(_EVENTS_DDL)
            conn.commit()
        finally:
            conn.close()
        try:
            rc, output = self._run_cli([
                "--db-path", empty,
                "--json",
            ])
            self.assertEqual(rc, 0)
            body = json.loads(output)
            self.assertEqual(body["total_clusters"],         0)
            self.assertEqual(body["total_rows_in_clusters"], 0)
            self.assertEqual(body["clusters"],               [])
        finally:
            try:
                os.remove(empty)
            except (OSError, PermissionError):
                pass


if __name__ == "__main__":
    unittest.main()
