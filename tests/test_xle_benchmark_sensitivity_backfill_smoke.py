"""Tests for ``scripts/xle_benchmark_sensitivity_backfill_smoke.py``.

Pin the contract:

* Temp DB only — copies the live events DB to a fresh file in
  ``tempfile.gettempdir()`` and runs every read/write step against
  that copy.  ``live_db_unchanged`` propagates the hash-before /
  hash-after byte-identity guard.
* No provider / yfinance / LLM / FastAPI surface; never imports
  ``api`` / ``routes.*``.
* Reads the existing local ``price_cache`` only.  If a missing date
  cannot be filled from a row already in local cache, it lands in
  ``still_missing_ranges`` — never fabricated.
* Output dict has EXACTLY these 14 keys::

    ok, temp_db_path, checked_events_before, checked_events_after,
    ready_before, ready_after, blocked_before, blocked_after,
    added_rows, still_missing_ranges, live_db_unchanged, warnings,
    errors, recommended_next_action

* CLI ``main`` returns 0 iff envelope ``ok`` is True.
* Conservative wording — banned tokens absent from any text the
  smoke emits.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import xle_benchmark_sensitivity_backfill_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "temp_db_path",
    "checked_events_before",
    "checked_events_after",
    "ready_before",
    "ready_after",
    "blocked_before",
    "blocked_after",
    "added_rows",
    "still_missing_ranges",
    "live_db_unchanged",
    "warnings",
    "errors",
    "recommended_next_action",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "correct ticker",
    "guaranteed",
)


_EVENTS_DDL = """
CREATE TABLE events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    headline         TEXT,
    event_date       TEXT,
    market_tickers   TEXT,
    low_signal       INTEGER DEFAULT 0,
    mechanism_family TEXT DEFAULT 'none'
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


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_live_db(
    *,
    event_id_to_date: dict[int, str] | None = None,
    primary_ticker: str = "XOM",
    xle_dates: list[str] | None = None,
    extra_cache_rows: list[tuple[str, str]] | None = None,
) -> str:
    """Build a tempfile SQLite DB carrying the events + price_cache
    surface the smoke reads from.  Returns the path.

    * ``event_id_to_date`` seeds one row per event with the given ISO
      date.  Each event carries ``primary_ticker`` in
      ``market_tickers``.
    * ``xle_dates`` are inserted into price_cache under ticker XLE.
    * ``extra_cache_rows`` is a list of ``(ticker, date)`` for any
      additional cache rows the test wants to seed.
    """
    path = os.path.join(
        tempfile.gettempdir(),
        f"xle_backfill_live_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_PRICE_CACHE_DDL)
        for ev_id, ev_date in (event_id_to_date or {}).items():
            conn.execute(
                "INSERT INTO events (id, headline, event_date, market_tickers) "
                "VALUES (?, ?, ?, ?)",
                (
                    ev_id,
                    f"fixture headline {ev_id}",
                    ev_date,
                    json.dumps([{"symbol": primary_ticker}]),
                ),
            )
        # Seed primary ticker with a generous cache covering the
        # estimation window for every event_date so the primary side
        # of the preflight is uniformly ready.  This isolates each
        # test to the XLE / benchmark side.
        seeded: set[tuple[str, str]] = set()
        if event_id_to_date:
            for ev_date in event_id_to_date.values():
                if not isinstance(ev_date, str) or not ev_date:
                    continue
                from datetime import date as _d, timedelta as _td
                anchor = _d.fromisoformat(ev_date)
                # 120 business days back and 25 forward gives the
                # default 60-day estimation window plus the 20d
                # forward horizon plenty of slack.
                from datetime import date as _date
                cur = anchor - _td(days=1)
                added = 0
                while added < 120:
                    if cur.weekday() < 5:
                        key = (primary_ticker, cur.isoformat())
                        if key not in seeded:
                            seeded.add(key)
                            conn.execute(
                                "INSERT OR IGNORE INTO price_cache "
                                "(ticker, date, close, volume, "
                                "auto_adjust, fetched_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (primary_ticker, cur.isoformat(),
                                 100.0, 1.0, 1, "2026-01-01"),
                            )
                        added += 1
                    cur = cur - _td(days=1)
                cur = anchor + _td(days=1)
                added = 0
                while added < 25:
                    if cur.weekday() < 5:
                        key = (primary_ticker, cur.isoformat())
                        if key not in seeded:
                            seeded.add(key)
                            conn.execute(
                                "INSERT OR IGNORE INTO price_cache "
                                "(ticker, date, close, volume, "
                                "auto_adjust, fetched_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (primary_ticker, cur.isoformat(),
                                 100.0, 1.0, 1, "2026-01-01"),
                            )
                        added += 1
                    cur = cur + _td(days=1)
        for d in (xle_dates or []):
            conn.execute(
                "INSERT OR IGNORE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("XLE", d, 75.0, 1.0, 1, "2026-01-01"),
            )
        for ticker, d in (extra_cache_rows or []):
            conn.execute(
                "INSERT OR IGNORE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, d, 50.0, 1.0, 1, "2026-01-01"),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_xle_rows(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            'SELECT COUNT(*) FROM price_cache WHERE ticker = "XLE"',
        ).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_no_live_db_returns_failure_envelope_with_required_keys(
        self,
    ) -> None:
        report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
            db_path="/nonexistent/events.db",
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "no live events db" in e.lower() for e in report["errors"]
        ))

    def test_real_run_against_temp_live_db_has_required_keys(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08", 73: "2026-04-06"},
            xle_dates=[],   # zero XLE coverage forces no_cache_for_ticker
        )
        try:
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live,
                estimation_window=5,    # smaller window for cheaper test
                horizons=(1, 5),
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Live DB byte identity
# ---------------------------------------------------------------------------


class TestLiveDbByteIdentity(unittest.TestCase):
    def test_live_db_unchanged_in_typical_run(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08", 73: "2026-04-06"},
            xle_dates=[],
        )
        try:
            before = _sha256(live)
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live, estimation_window=5, horizons=(1, 5),
            )
            after = _sha256(live)
            self.assertEqual(before, after)
            self.assertTrue(report["live_db_unchanged"])
        finally:
            os.unlink(live)

    def test_temp_db_path_is_not_the_live_db_path(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        try:
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live, estimation_window=5, horizons=(1, 5),
            )
            self.assertIsNotNone(report["temp_db_path"])
            self.assertNotEqual(report["temp_db_path"], live)
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Before / after preflight counts
# ---------------------------------------------------------------------------


class TestBeforeAfterCounts(unittest.TestCase):
    def test_no_local_source_means_after_equals_before(self) -> None:
        # No XLE cache rows at all; the seam returns nothing local.
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08", 73: "2026-04-06"},
            xle_dates=[],
        )
        try:
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live, estimation_window=5, horizons=(1, 5),
            )
            self.assertEqual(
                report["checked_events_before"],
                report["checked_events_after"],
            )
            self.assertEqual(
                report["ready_before"], report["ready_after"],
            )
            self.assertEqual(
                report["blocked_before"], report["blocked_after"],
            )
            self.assertEqual(report["added_rows"], [])
            self.assertTrue(report["still_missing_ranges"])
        finally:
            os.unlink(live)

    def test_seam_supplies_rows_clears_after(self) -> None:
        # XLE pre-event cache is short by exactly the two business
        # days the seam will supply.  The smoke inserts those rows
        # into the temp DB and the after-preflight clears.
        #
        # estimation_window=5; XLE seeded with 3 pre-event business
        # days starting from the third business day before anchor; the
        # gap the preflight then reports is the two business days
        # immediately before that earliest seeded date.
        anchor = "2026-04-10"  # Friday
        # 3 pre-event business days: Thu 4-09, Wed 4-08, Tue 4-07
        pre_event_xle = ["2026-04-07", "2026-04-08", "2026-04-09"]
        # Forward horizon coverage so the forward check passes.
        forward_xle = [
            "2026-04-13", "2026-04-14", "2026-04-15",
            "2026-04-16", "2026-04-17",
        ]
        # The 2 business days immediately before the earliest seeded
        # XLE row (Tue 4-07) are Fri 4-03 and Mon 4-06 — those are
        # the dates the seam will supply.
        seam_dates = {"2026-04-03", "2026-04-06"}

        live = _make_live_db(
            event_id_to_date={60: anchor},
            xle_dates=pre_event_xle + forward_xle,
        )

        def _seam(*, db_path: str, ticker: str, missing_dates):
            return [
                {
                    "ticker":      "XLE",
                    "date":        d,
                    "close":       80.0,
                    "volume":      1.0,
                    "auto_adjust": 1,
                    "fetched_at":  "2026-04-12",
                }
                for d in missing_dates
                if d in seam_dates
            ]

        try:
            with patch.object(
                cli, "_load_xle_rows_from_local_cache", side_effect=_seam,
            ):
                report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                    db_path=live, estimation_window=5, horizons=(1, 5),
                    event_ids=(60,),
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["ready_before"], 0)
            self.assertGreaterEqual(report["ready_after"], 1)
            self.assertEqual(len(report["added_rows"]), 2)
            for row in report["added_rows"]:
                self.assertEqual(row["ticker"], "XLE")
                self.assertEqual(row["source"], "local_price_cache_existing")
                self.assertIn(row["date"], seam_dates)
            self.assertEqual(report["still_missing_ranges"], [])
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Still-missing ranges + no-fabrication guard
# ---------------------------------------------------------------------------


class TestNoFabrication(unittest.TestCase):
    def test_seam_returning_nothing_leaves_added_rows_empty(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        try:
            with patch.object(
                cli, "_load_xle_rows_from_local_cache",
                return_value=[],
            ):
                report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                    db_path=live, estimation_window=5, horizons=(1, 5),
                    event_ids=(60,),
                )
            self.assertEqual(report["added_rows"], [])
            self.assertTrue(report["still_missing_ranges"])
            for entry in report["still_missing_ranges"]:
                self.assertEqual(entry["event_id"], 60)
                self.assertIn("start", entry)
                self.assertIn("end", entry)
                self.assertIn("reason", entry)
        finally:
            os.unlink(live)

    def test_temp_db_xle_row_count_does_not_exceed_seeded_plus_seam(
        self,
    ) -> None:
        # When the seam returns ZERO rows, the temp DB's XLE row count
        # must equal the live DB's (no fabricated inserts).
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=["2026-01-05", "2026-01-06"],
        )
        try:
            live_xle = _count_xle_rows(live)
            with patch.object(
                cli, "_load_xle_rows_from_local_cache",
                return_value=[],
            ):
                report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                    db_path=live, estimation_window=5, horizons=(1, 5),
                    event_ids=(60,),
                )
            # Live DB byte identity already pinned; assert no XLE rows
            # were added to the live cache either.
            self.assertEqual(_count_xle_rows(live), live_xle)
            self.assertEqual(report["added_rows"], [])
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Output persistence
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_passed(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"xle_backfill_out_{uuid.uuid4().hex}.json",
        )
        try:
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live, estimation_window=5, horizons=(1, 5),
                output_path=out_path,
            )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            self.assertEqual(set(blob.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(blob["ok"], report["ok"])
        finally:
            os.unlink(live)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_no_output_means_no_workflow_residue(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        try:
            before_listing = set(os.listdir(tempfile.gettempdir()))
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live, estimation_window=5, horizons=(1, 5),
            )
            after_listing = set(os.listdir(tempfile.gettempdir()))
            leaked = [
                f for f in (after_listing - before_listing)
                if f.startswith("xle_backfill_smoke_")
            ]
            self.assertEqual(
                leaked, [],
                f"temp DB not cleaned up: {leaked}",
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_text_render(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        try:
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live, estimation_window=5, horizons=(1, 5),
            )
            text = cli._render_text(report).lower()
            for term in _BANNED_WORDS:
                self.assertNotIn(
                    term, text,
                    f"banned token {term!r} in text render",
                )
        finally:
            os.unlink(live)

    def test_no_banned_words_in_json_render(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        try:
            report = cli.run_xle_benchmark_sensitivity_backfill_smoke(
                db_path=live, estimation_window=5, horizons=(1, 5),
            )
            blob = cli._render_json(report).lower()
            for term in _BANNED_WORDS:
                self.assertNotIn(
                    term, blob,
                    f"banned token {term!r} in JSON render",
                )
        finally:
            os.unlink(live)


# ---------------------------------------------------------------------------
# No-paid-surface import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_smoke_module_does_not_bind_provider_attrs(self) -> None:
        # The smoke surface itself must not carry provider / LLM
        # module attributes; other test files in the same process can
        # legitimately load yfinance / fastapi / etc., so we don't
        # assert their absence from sys.modules.
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"smoke must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, out.getvalue()

    def test_json_emits_required_keys(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        try:
            rc, output = self._run([
                "--db-path", live, "--json",
                "--event-ids", "60",
                "--estimation-window", "5",
                "--horizons", "1,5",
            ])
            parsed = json.loads(output)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
            # Smoke ran cleanly even though the event remains blocked.
            self.assertEqual(rc, 0)
        finally:
            os.unlink(live)

    def test_text_render_does_not_crash(self) -> None:
        live = _make_live_db(
            event_id_to_date={60: "2026-04-08"},
            xle_dates=[],
        )
        try:
            rc, output = self._run([
                "--db-path", live,
                "--event-ids", "60",
                "--estimation-window", "5",
                "--horizons", "1,5",
            ])
            self.assertEqual(rc, 0)
            self.assertIn("XLE benchmark-sensitivity backfill smoke", output)
        finally:
            os.unlink(live)

    def test_main_returns_nonzero_when_envelope_ok_false(self) -> None:
        rc, output = self._run([
            "--db-path", "/nonexistent/events.db", "--json",
        ])
        self.assertEqual(rc, 1)
        parsed = json.loads(output)
        self.assertFalse(parsed["ok"])


if __name__ == "__main__":
    unittest.main()
