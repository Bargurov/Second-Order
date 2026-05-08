"""Tests for ``scripts/stat_validation_blocker_report.py``.

Pin the contract:

* The script consumes the readiness report's payload via the
  patchable :func:`scripts.stat_validation_blocker_report._run_readiness_report`
  seam.  Most tests synthesise a readiness payload directly and pin
  the per-blocker decomposition; one end-to-end test exercises the
  real seam against a temp DB to confirm the wiring.
* Aggregate counts (``count``) walk every not-ready event the
  readiness payload surfaced.  ``--limit`` truncates each blocker's
  ``examples`` list only.
* The six blocker buckets are NOT a partition — an event without
  ``event_date`` lights up every cache-anchored blocker because the
  underlying readiness check degrades to ``False``.
* Examples preserve the readiness report's id-ascending order.
* ``--json``, ``--limit``, ``--db-path`` plumbing.
* No provider, yfinance, market_check, market_data, LLM, or FastAPI
  seam invoked.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import stat_validation_blocker_report as cli  # noqa: E402


_BLOCKER_KEYS = (
    "missing_market_tickers",
    "missing_forward_cache_1d",
    "missing_forward_cache_5d",
    "missing_forward_cache_20d",
    "missing_benchmark_proxy",
    "insufficient_estimation_window",
)


_TOP_KEYS = (
    "total_events",
    "events_fully_ready",
    "events_not_fully_ready",
    "blockers",
    "recommended_next_action",
)


_PER_EVENT_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "checks",
    "fully_ready",
)


_CHECK_KEYS = (
    "has_event_date",
    "has_market_tickers",
    "forward_cache_1d",
    "forward_cache_5d",
    "forward_cache_20d",
    "benchmark_proxy_available",
    "estimation_window_sufficient",
)


# ---------------------------------------------------------------------------
# Synthetic readiness payload helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    event_id: int,
    event_date: str | None = "2026-04-15",
    primary_ticker: str | None = "AAPL",
    has_event_date: bool = True,
    has_market_tickers: bool = True,
    forward_cache_1d: bool = True,
    forward_cache_5d: bool = True,
    forward_cache_20d: bool = True,
    benchmark_proxy_available: bool = True,
    estimation_window_sufficient: bool = True,
) -> dict:
    """Build one synthetic readiness per-event entry.

    Defaults to fully-ready; flip individual checks to False to
    sculpt blocker fixtures.  The ``fully_ready`` field is recomputed
    here so the synthetic payload stays self-consistent — a test that
    sets one check to False automatically gets ``fully_ready=False``.
    """
    checks = {
        "has_event_date":               has_event_date,
        "has_market_tickers":           has_market_tickers,
        "forward_cache_1d":             forward_cache_1d,
        "forward_cache_5d":             forward_cache_5d,
        "forward_cache_20d":            forward_cache_20d,
        "benchmark_proxy_available":    benchmark_proxy_available,
        "estimation_window_sufficient": estimation_window_sufficient,
    }
    return {
        "event_id":       event_id,
        "event_date":     event_date,
        "primary_ticker": primary_ticker,
        "checks":         checks,
        "fully_ready":    all(checks.values()),
    }


def _readiness_payload(events: list[dict]) -> dict:
    fully_ready_count = sum(1 for e in events if e["fully_ready"])
    return {
        "total_events":                                len(events),
        "events_with_event_date":                      sum(1 for e in events if e["checks"]["has_event_date"]),
        "events_with_market_tickers":                  sum(1 for e in events if e["checks"]["has_market_tickers"]),
        "events_with_event_date_and_tickers":          sum(
            1 for e in events
            if e["checks"]["has_event_date"] and e["checks"]["has_market_tickers"]
        ),
        "events_with_1d_forward_cache":                sum(1 for e in events if e["checks"]["forward_cache_1d"]),
        "events_with_5d_forward_cache":                sum(1 for e in events if e["checks"]["forward_cache_5d"]),
        "events_with_20d_forward_cache":               sum(1 for e in events if e["checks"]["forward_cache_20d"]),
        "events_missing_benchmark_proxy":              sum(
            1 for e in events if not e["checks"]["benchmark_proxy_available"]
        ),
        "events_with_insufficient_estimation_window":  sum(
            1 for e in events if not e["checks"]["estimation_window_sufficient"]
        ),
        "events_fully_ready":                          fully_ready_count,
        "events":                                      events,
        "recommended_next_action":                     "synthetic",
    }


def _patch_readiness(payload: dict):
    return patch.object(cli, "_run_readiness_report", return_value=payload)


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        rc = cli.main(argv, out=out)
    except SystemExit as exc:
        rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(unittest.TestCase):
    def test_returns_dict_with_top_keys(self) -> None:
        payload = _readiness_payload([
            _make_event(event_id=1),
        ])
        with _patch_readiness(payload):
            result = cli.summarize_blockers()
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_blockers_dict_has_every_required_bucket(self) -> None:
        with _patch_readiness(_readiness_payload([])):
            result = cli.summarize_blockers()
        self.assertIsInstance(result["blockers"], dict)
        for key in _BLOCKER_KEYS:
            self.assertIn(key, result["blockers"],
                          f"missing blocker bucket: {key}")
            bucket = result["blockers"][key]
            self.assertIn("count",    bucket)
            self.assertIn("examples", bucket)
            self.assertIsInstance(bucket["count"],    int)
            self.assertIsInstance(bucket["examples"], list)


# ---------------------------------------------------------------------------
# Empty / fully-ready archives
# ---------------------------------------------------------------------------


class TestEmptyAndAllReady(unittest.TestCase):
    def test_empty_payload_zeros_every_count(self) -> None:
        with _patch_readiness(_readiness_payload([])):
            result = cli.summarize_blockers()
        self.assertEqual(result["total_events"],           0)
        self.assertEqual(result["events_fully_ready"],     0)
        self.assertEqual(result["events_not_fully_ready"], 0)
        for key in _BLOCKER_KEYS:
            self.assertEqual(result["blockers"][key]["count"],    0)
            self.assertEqual(result["blockers"][key]["examples"], [])
        self.assertIn("empty",
                      result["recommended_next_action"].lower())

    def test_all_ready_yields_zero_blocker_counts(self) -> None:
        events = [_make_event(event_id=i) for i in range(1, 4)]
        with _patch_readiness(_readiness_payload(events)):
            result = cli.summarize_blockers()
        self.assertEqual(result["total_events"],           3)
        self.assertEqual(result["events_fully_ready"],     3)
        self.assertEqual(result["events_not_fully_ready"], 0)
        for key in _BLOCKER_KEYS:
            self.assertEqual(result["blockers"][key]["count"],    0)
            self.assertEqual(result["blockers"][key]["examples"], [])
        self.assertIn("fully ready",
                      result["recommended_next_action"].lower())


# ---------------------------------------------------------------------------
# Per-blocker decomposition
# ---------------------------------------------------------------------------


class TestPerBlockerDecomposition(unittest.TestCase):
    def test_each_check_failure_lights_up_its_blocker(self) -> None:
        # One event per blocker, each failing exactly one check.
        events = [
            _make_event(event_id=1,  has_market_tickers=False),
            _make_event(event_id=2,  forward_cache_1d=False),
            _make_event(event_id=3,  forward_cache_5d=False),
            _make_event(event_id=4,  forward_cache_20d=False),
            _make_event(event_id=5,  benchmark_proxy_available=False),
            _make_event(event_id=6,  estimation_window_sufficient=False),
            # And one fully-ready row that should never appear.
            _make_event(event_id=7),
        ]
        with _patch_readiness(_readiness_payload(events)):
            result = cli.summarize_blockers()
        # Each blocker should carry exactly one event, and the
        # event_id of that event should match the fixture.
        expected_id = {
            "missing_market_tickers":         1,
            "missing_forward_cache_1d":       2,
            "missing_forward_cache_5d":       3,
            "missing_forward_cache_20d":      4,
            "missing_benchmark_proxy":        5,
            "insufficient_estimation_window": 6,
        }
        for key in _BLOCKER_KEYS:
            bucket = result["blockers"][key]
            self.assertEqual(bucket["count"], 1, f"{key} count")
            self.assertEqual(len(bucket["examples"]), 1)
            self.assertEqual(bucket["examples"][0]["event_id"],
                             expected_id[key], f"{key} example id")
        self.assertEqual(result["events_not_fully_ready"], 6)
        self.assertEqual(result["events_fully_ready"],     1)

    def test_event_with_multiple_failing_checks_appears_in_each_bucket(self) -> None:
        # The six categories are NOT a partition — a single event
        # with three failing checks shows up in three blocker
        # buckets.  This pins the "not a partition" property
        # explicitly so a future "exclusive" reading can't quietly
        # regress.
        bad = _make_event(
            event_id=42,
            forward_cache_1d=False,
            forward_cache_5d=False,
            forward_cache_20d=False,
        )
        with _patch_readiness(_readiness_payload([bad])):
            result = cli.summarize_blockers()
        self.assertEqual(result["events_not_fully_ready"], 1)
        for key in (
            "missing_forward_cache_1d",
            "missing_forward_cache_5d",
            "missing_forward_cache_20d",
        ):
            self.assertEqual(result["blockers"][key]["count"], 1)
            self.assertEqual(
                result["blockers"][key]["examples"][0]["event_id"], 42,
            )
        for key in (
            "missing_market_tickers",
            "missing_benchmark_proxy",
            "insufficient_estimation_window",
        ):
            self.assertEqual(result["blockers"][key]["count"], 0)

    def test_no_event_date_event_lights_up_every_cache_anchored_blocker(self) -> None:
        # An event without event_date has every cache check
        # degraded to False by the readiness report.  The blocker
        # report must surface this honestly: the cache-anchored
        # blockers all light up, but missing_market_tickers does NOT
        # (the event has tickers).
        no_date = _make_event(
            event_id=1, event_date=None,
            has_event_date=False,
            forward_cache_1d=False,
            forward_cache_5d=False,
            forward_cache_20d=False,
            benchmark_proxy_available=False,
            estimation_window_sufficient=False,
        )
        with _patch_readiness(_readiness_payload([no_date])):
            result = cli.summarize_blockers()
        self.assertEqual(result["blockers"]["missing_market_tickers"]["count"], 0)
        for key in (
            "missing_forward_cache_1d",
            "missing_forward_cache_5d",
            "missing_forward_cache_20d",
            "missing_benchmark_proxy",
            "insufficient_estimation_window",
        ):
            self.assertEqual(result["blockers"][key]["count"], 1, key)

    def test_aggregates_against_overlapping_failures(self) -> None:
        events = [
            # 5 events missing tickers only.
            *[_make_event(event_id=i, has_market_tickers=False)
              for i in range(1, 6)],
            # 3 events missing benchmark proxy AND 20d forward cache.
            *[_make_event(
                event_id=10 + i,
                benchmark_proxy_available=False,
                forward_cache_20d=False,
            ) for i in range(3)],
            # 7 fully ready.
            *[_make_event(event_id=20 + i) for i in range(7)],
        ]
        with _patch_readiness(_readiness_payload(events)):
            result = cli.summarize_blockers()
        self.assertEqual(result["total_events"],           15)
        self.assertEqual(result["events_fully_ready"],     7)
        self.assertEqual(result["events_not_fully_ready"], 8)
        self.assertEqual(
            result["blockers"]["missing_market_tickers"]["count"], 5,
        )
        self.assertEqual(
            result["blockers"]["missing_forward_cache_20d"]["count"], 3,
        )
        self.assertEqual(
            result["blockers"]["missing_benchmark_proxy"]["count"], 3,
        )
        # And these blockers were not tripped by either group.
        for key in (
            "missing_forward_cache_1d",
            "missing_forward_cache_5d",
            "insufficient_estimation_window",
        ):
            self.assertEqual(result["blockers"][key]["count"], 0)


# ---------------------------------------------------------------------------
# Examples ordering + --limit
# ---------------------------------------------------------------------------


class TestExamplesOrderAndLimit(unittest.TestCase):
    def test_examples_preserve_id_ascending_order(self) -> None:
        events = [
            _make_event(event_id=eid, has_market_tickers=False)
            for eid in (3, 1, 2)  # readiness sorts asc, but pin
                                   # the contract regardless of input
        ]
        # The blocker report doesn't re-sort — it relies on the
        # readiness payload's order.  Synthesise the readiness
        # payload pre-sorted (matching production behaviour).
        events.sort(key=lambda e: e["event_id"])
        with _patch_readiness(_readiness_payload(events)):
            result = cli.summarize_blockers()
        ids = [e["event_id"] for e in
               result["blockers"]["missing_market_tickers"]["examples"]]
        self.assertEqual(ids, [1, 2, 3])

    def test_limit_truncates_examples_only(self) -> None:
        events = [
            _make_event(event_id=eid, has_market_tickers=False)
            for eid in range(1, 11)
        ]
        with _patch_readiness(_readiness_payload(events)):
            result = cli.summarize_blockers(limit=3)
        bucket = result["blockers"]["missing_market_tickers"]
        # Count walks every not-ready event regardless of limit.
        self.assertEqual(bucket["count"],          10)
        self.assertEqual(len(bucket["examples"]),  3)
        self.assertEqual(
            [e["event_id"] for e in bucket["examples"]], [1, 2, 3],
        )
        self.assertEqual(result["events_not_fully_ready"], 10)

    def test_negative_limit_clamps_to_zero(self) -> None:
        events = [
            _make_event(event_id=eid, has_market_tickers=False)
            for eid in range(1, 4)
        ]
        with _patch_readiness(_readiness_payload(events)):
            result = cli.summarize_blockers(limit=-5)
        self.assertEqual(
            result["blockers"]["missing_market_tickers"]["count"],     3,
        )
        self.assertEqual(
            result["blockers"]["missing_market_tickers"]["examples"], [],
        )

    def test_limit_does_not_drop_events_from_aggregate_count(self) -> None:
        # Pin the "counts cover every not-ready event, examples are
        # only a sample" property — the easy regression where someone
        # truncates the not_ready list before counting blockers and
        # silently undercounts.
        events = [
            _make_event(event_id=eid, has_market_tickers=False)
            for eid in range(1, 51)  # 50 not-ready events
        ]
        with _patch_readiness(_readiness_payload(events)):
            result = cli.summarize_blockers(limit=5)
        self.assertEqual(result["events_not_fully_ready"], 50)
        self.assertEqual(
            result["blockers"]["missing_market_tickers"]["count"], 50,
        )
        self.assertEqual(
            len(result["blockers"]["missing_market_tickers"]["examples"]), 5,
        )


# ---------------------------------------------------------------------------
# Readiness seam plumbing
# ---------------------------------------------------------------------------


class TestReadinessSeam(unittest.TestCase):
    def test_seam_is_called_with_the_supplied_db_path(self) -> None:
        seam_calls: list[dict] = []

        def fake(*, db_path):
            seam_calls.append({"db_path": db_path})
            return _readiness_payload([])

        with patch.object(cli, "_run_readiness_report", side_effect=fake):
            cli.summarize_blockers(db_path="/tmp/some-events.db")
        self.assertEqual(len(seam_calls), 1)
        self.assertEqual(seam_calls[0]["db_path"], "/tmp/some-events.db")

    def test_seam_is_called_with_unbounded_limit_in_default_path(self) -> None:
        # The production seam (unpatched at this layer) must request
        # every event so blocker counts cover the full archive.
        # Verify by patching the underlying ``summarize_readiness``
        # function and capturing the kwargs.
        from scripts import stat_validation_readiness_report as rr

        captured: list[dict] = []

        def fake_summarize(**kwargs):
            captured.append(kwargs)
            return _readiness_payload([])

        with patch.object(rr, "summarize_readiness", side_effect=fake_summarize):
            cli.summarize_blockers(db_path=None)
        self.assertEqual(len(captured), 1)
        self.assertGreaterEqual(
            captured[0].get("limit", 0), 1_000_000,
            "blocker report must call the readiness report with an "
            "effectively unbounded per-event cap so no events are "
            "dropped before blocker counting",
        )

    def test_malformed_readiness_payload_degrades_gracefully(self) -> None:
        # If the readiness seam returns garbage (eg ``None``), the
        # blocker report should still produce a well-formed payload
        # rather than raising.
        for bad in (None, "string", 42, [1, 2, 3]):
            with self.subTest(bad=bad):
                with patch.object(
                    cli, "_run_readiness_report", return_value=bad,
                ):
                    result = cli.summarize_blockers()
                self.assertEqual(result["total_events"],           0)
                self.assertEqual(result["events_fully_ready"],     0)
                self.assertEqual(result["events_not_fully_ready"], 0)
                for key in _BLOCKER_KEYS:
                    self.assertEqual(
                        result["blockers"][key]["count"],    0,
                    )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_text_output_summarises_each_blocker(self) -> None:
        events = [
            _make_event(event_id=1,  has_market_tickers=False),
            _make_event(event_id=2,  forward_cache_20d=False),
        ]
        with _patch_readiness(_readiness_payload(events)):
            rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        for blocker_key in _BLOCKER_KEYS:
            self.assertIn(blocker_key, output,
                          f"text output missing blocker line: {blocker_key}")
        self.assertIn("Total events",       output)
        self.assertIn("not fully ready",    output)
        self.assertIn("Recommended next action", output)

    def test_json_output_carries_required_keys(self) -> None:
        events = [
            _make_event(event_id=1, has_market_tickers=False),
        ]
        with _patch_readiness(_readiness_payload(events)):
            rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        for blocker_key in _BLOCKER_KEYS:
            self.assertIn(blocker_key, body["blockers"],
                          f"missing blocker bucket: {blocker_key}")
        # Per-event examples carry the readiness shape.
        ex = body["blockers"]["missing_market_tickers"]["examples"][0]
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, ex, f"example missing field: {key}")

    def test_cli_limit_truncates_examples_only(self) -> None:
        events = [
            _make_event(event_id=eid, has_market_tickers=False)
            for eid in range(1, 11)
        ]
        with _patch_readiness(_readiness_payload(events)):
            rc, output = _run_cli(["--json", "--limit", "2"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        bucket = body["blockers"]["missing_market_tickers"]
        self.assertEqual(bucket["count"],          10)
        self.assertEqual(len(bucket["examples"]),  2)

    def test_cli_db_path_forwarded_to_seam(self) -> None:
        captured: list[str | None] = []

        def fake(*, db_path):
            captured.append(db_path)
            return _readiness_payload([])

        with patch.object(cli, "_run_readiness_report", side_effect=fake):
            rc, _ = _run_cli([
                "--db-path", "/tmp/alt.db", "--json",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(captured, ["/tmp/alt.db"])


# ---------------------------------------------------------------------------
# End-to-end against a temp DB — exercises the real readiness seam
# ---------------------------------------------------------------------------


_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT
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


def _seed_event(
    conn: sqlite3.Connection,
    *,
    event_date: str | None,
    market_tickers: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO events (headline, event_date, market_tickers) "
        "VALUES (?, ?, ?)",
        ("hl", event_date, market_tickers),
    )
    return int(cur.lastrowid)


def _seed_cache(
    conn: sqlite3.Connection,
    *,
    ticker: str, date_str: str, auto_adjust: int = 1,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO price_cache "
        "(ticker, date, close, volume, auto_adjust, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, date_str, 100.0, 5_000_000.0, auto_adjust,
         "2026-05-06T12:00:00+00:00"),
    )


def _bd(start: date, n: int) -> date:
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


class TestEndToEndAgainstTempDb(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_svbr_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
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

    def test_real_seam_decomposes_temp_db_blockers(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            # Event 1 — fully ready.  Seed estimation window (60
            # pre-event business days), forward cache for the ticker
            # at +20bd, and SPY at +20bd.
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            cursor = ed - timedelta(days=1)
            seeded = 0
            while seeded < 60:
                if cursor.weekday() < 5:
                    _seed_cache(conn, ticker="AAPL",
                                date_str=cursor.isoformat())
                    seeded += 1
                cursor = cursor - timedelta(days=1)
            for h in (1, 5, 20):
                _seed_cache(conn, ticker="AAPL",
                            date_str=_bd(ed, h).isoformat())
            _seed_cache(conn, ticker="SPY",
                        date_str=_bd(ed, 20).isoformat())

            # Event 2 — ticker present but no cache anywhere.
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "MSFT"}]),
            )
            # Event 3 — no tickers at all.
            _seed_event(conn, event_date=ed.isoformat(),
                        market_tickers="[]")
            conn.commit()

        result = cli.summarize_blockers(db_path=self._tmp)
        self.assertEqual(result["total_events"],            3)
        self.assertEqual(result["events_fully_ready"],      1)
        self.assertEqual(result["events_not_fully_ready"],  2)

        # Event 3 has no tickers — exactly one event tripped that
        # blocker.  Note: events 2 and 3 share event_date with event 1,
        # so SPY seeded for event 1 also satisfies the benchmark
        # check for events 2 and 3 (the readiness check is per-date,
        # not per-event-and-ticker).
        self.assertEqual(
            result["blockers"]["missing_market_tickers"]["count"], 1,
        )
        # Both events 2 and 3 fail every cache check for MSFT/no-ticker
        # (event 2's primary ticker MSFT has zero cache; event 3 has
        # no primary ticker so cache anchored checks return False).
        for key in (
            "missing_forward_cache_1d",
            "missing_forward_cache_5d",
            "missing_forward_cache_20d",
            "insufficient_estimation_window",
        ):
            self.assertEqual(
                result["blockers"][key]["count"], 2,
                f"{key} should pin both not-ready events",
            )

    def test_repeated_runs_leave_temp_db_byte_identical(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker="AAPL", date_str="2026-04-16")
            conn.commit()

        def _snapshot() -> tuple[list, list]:
            conn = sqlite3.connect(self._tmp)
            try:
                events = list(conn.execute(
                    "SELECT * FROM events ORDER BY id",
                ))
                cache = list(conn.execute(
                    "SELECT ticker, date, close, volume, "
                    "auto_adjust, fetched_at FROM price_cache "
                    "ORDER BY ticker, date, auto_adjust",
                ))
                return events, cache
            finally:
                conn.close()

        before = _snapshot()
        for _ in range(3):
            cli.summarize_blockers(db_path=self._tmp)
        after = _snapshot()
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical across "
            "repeated runs",
        )


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(unittest.TestCase):
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

        events = [_make_event(event_id=1, has_market_tickers=False)]
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
                        f"stat_validation_blocker_report must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "stat_validation_blocker_report must not call "
                        "yfinance",
                    ),
                ))
            except ImportError:
                pass

            stack.enter_context(_patch_readiness(_readiness_payload(events)))
            result = cli.summarize_blockers()

        self.assertEqual(result["events_not_fully_ready"], 1)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(cli, "app"))
        self.assertFalse(hasattr(cli, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard: instrument ``builtins.__import__``
        # so any actual import statement targeting ``api`` /
        # ``routes`` / ``routes.*`` is recorded — even when an earlier
        # suite already cached the target in ``sys.modules``.  The
        # patched readiness seam keeps the test off the production
        # SELECT path.
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
        with _patch_readiness(_readiness_payload([])):
            with patch("builtins.__import__", side_effect=tracing_import):
                cli.summarize_blockers()
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
