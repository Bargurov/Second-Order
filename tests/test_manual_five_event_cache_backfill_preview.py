"""Tests for ``scripts/manual_five_event_cache_backfill_preview.py``.

The preview reads the operator-curated 5-event CSV, computes the
(ticker, start_date, end_date) windows the read-only validation path
would need, inspects what is already in the live ``price_cache``
table, and reports the gap.  Two modes:

* **Default (no ``--confirm-online``).**  Pure preview.  No network
  request, no DB write of any kind, no ``yfinance`` import, no temp
  storage created.  The envelope reports zero ``fetched_rows`` and an
  explicit ``blocked_reasons`` entry naming the missing flag.

* **``--confirm-online``.**  Authorises a single ``yfinance`` fetch
  per ticker/window via the patchable
  :func:`_fetch_ticker_rows_online` seam.  Rows are inserted into a
  freshly-created TEMP SQLite file (``temp_db_path`` surfaced for
  inspection) — NEVER the live cache.  The live ``events.db`` file is
  hashed before and after; ``live_db_unchanged`` must remain True.

Pinned contract:

* Envelope keys are exactly the documented set.
* Default mode emits ``ok=True``, ``mode="preview"``, ``fetched_rows=0``,
  ``inserted_temp_rows=0``, ``temp_db_path=None``,
  ``live_db_unchanged=True``, and a ``blocked_reasons`` entry citing
  ``--confirm-online``.
* ``_fetch_ticker_rows_online`` is NEVER called in the default mode.
* ``--confirm-online`` fetches per ticker/window via the seam, inserts
  rows into a temp SQLite, and never touches the live DB file.
* Live-DB byte-identity holds across both modes when ``db_path`` exists.
* ``tickers`` is the sorted union of primary + benchmark tickers; one
  ``windows`` entry per ``(ticker, candidate)`` pair carries the date
  range and the cached / fetched bar counts.
* Conservative wording — banned overclaim tokens absent from any
  rendered output.
* No paid / FastAPI surface — module load does not pull in yfinance,
  fastapi, api, or any ``routes.*`` submodule.
* The script source never calls a SQLite writer against the live cache
  path; every ``sqlite3.connect`` lands on a temp path.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_five_event_cache_backfill_preview as cli  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[1]

_REQUIRED_TOP_KEYS = (
    "ok",
    "mode",
    "confirm_online",
    "input_csv",
    "rows_loaded",
    "candidates",
    "tickers",
    "windows",
    "fetched_rows",
    "inserted_temp_rows",
    "temp_db_path",
    "blocked_reasons",
    "live_db_unchanged",
    "warnings",
    "errors",
    "recommended_next_action",
)


_REQUIRED_CANDIDATE_KEYS = (
    "candidate_id",
    "row_index",
    "event_date",
    "headline",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)


_REQUIRED_WINDOW_KEYS = (
    "ticker",
    "candidate_id",
    "event_date",
    "start",
    "end",
    "cached_bars",
    "fetched_bars",
)


_BANNED_TOKENS = (
    "proof",
    "proven",
    "guaranteed",
    "automatically",
    "validated",
    "alpha generated",
    "definitely",
    "production ready",
    "production-ready",
    "demo_ready",
    "demo-ready",
)


_PRICE_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


def _make_live_db_fixture() -> str:
    """Create a tiny SQLite file that stands in for the live
    ``events.db`` so we can hash it before / after the preview run
    and assert the live-DB byte-identity invariant without depending
    on the real file."""
    path = os.path.join(
        tempfile.gettempdir(),
        f"five_event_preview_live_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_PRICE_CACHE_DDL)
        conn.execute(
            "INSERT OR IGNORE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("SENTINEL", "1999-12-31", 1.0, 1.0, 0, "1999-12-31T00:00:00Z"),
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


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv
    columns = [
        "event_date",
        "headline",
        "source_url",
        "mechanism_family",
        "primary_ticker",
        "benchmark_ticker",
        "predicted_direction",
        "why_this_event_is_defensible",
        "what_would_falsify",
        "operator_notes",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def _row(
    *,
    event_date:        str = "2021-05-10",
    headline:          str = "synthetic",
    mechanism_family:  str = "synth_family",
    primary_ticker:    str = "UGA",
    benchmark_ticker:  str = "USO",
) -> dict[str, str]:
    return {
        "event_date":       event_date,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
    }


def _provider_row(
    *,
    ticker: str,
    date:   str,
    close:  float = 100.0,
    volume: float = 1_000_000.0,
) -> dict[str, Any]:
    return {
        "ticker":      ticker,
        "date":        date,
        "close":       close,
        "volume":      volume,
        "auto_adjust": 0,
        "fetched_at":  "2026-05-17T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class EnvelopeShapeTests(unittest.TestCase):

    def test_envelope_has_exactly_required_top_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ), patch.object(
                cli, "_fetch_ticker_rows_online",
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        self.assertEqual(set(env.keys()), set(_REQUIRED_TOP_KEYS))

    def test_candidate_entries_have_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        self.assertEqual(len(env["candidates"]), 1)
        for c in env["candidates"]:
            self.assertEqual(
                set(c.keys()), set(_REQUIRED_CANDIDATE_KEYS),
                msg=f"candidate key drift: {sorted(c.keys())}",
            )

    def test_window_entries_have_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        self.assertGreaterEqual(len(env["windows"]), 2)  # primary + benchmark
        for w in env["windows"]:
            self.assertEqual(
                set(w.keys()), set(_REQUIRED_WINDOW_KEYS),
                msg=f"window key drift: {sorted(w.keys())}",
            )

    def test_tickers_is_sorted_unique_union(self) -> None:
        rows = [
            _row(primary_ticker="UGA", benchmark_ticker="USO"),
            _row(primary_ticker="X",   benchmark_ticker="SPY"),
            _row(primary_ticker="KBE", benchmark_ticker="SPY"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, rows)
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        self.assertEqual(
            env["tickers"],
            sorted({"UGA", "USO", "X", "SPY", "KBE"}),
        )


# ---------------------------------------------------------------------------
# Default mode = pure preview
# ---------------------------------------------------------------------------


class DefaultPreviewModeTests(unittest.TestCase):

    def test_default_mode_reports_preview_and_zero_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ), patch.object(
                cli, "_fetch_ticker_rows_online",
            ) as fetch_seam:
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        self.assertTrue(env["ok"])
        self.assertEqual(env["mode"], "preview")
        self.assertFalse(env["confirm_online"])
        self.assertEqual(env["fetched_rows"], 0)
        self.assertEqual(env["inserted_temp_rows"], 0)
        self.assertIsNone(env["temp_db_path"])
        self.assertTrue(env["live_db_unchanged"])
        fetch_seam.assert_not_called()

    def test_default_mode_blocked_reasons_cites_confirm_online(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        joined = " ".join(env["blocked_reasons"]).lower()
        self.assertIn("confirm-online", joined,
                      f"blocked_reasons: {env['blocked_reasons']}")

    def test_default_mode_does_not_create_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            before = set(os.listdir(tempfile.gettempdir()))
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
            after = set(os.listdir(tempfile.gettempdir()))
        # Preview mode must not leave any new five_event_preview_* file.
        new_files = after - before
        for n in new_files:
            self.assertFalse(
                "five_event_preview" in n.lower(),
                msg=f"preview created temp file in default mode: {n}",
            )

    def test_cached_bars_count_matches_seam_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row(primary_ticker="UGA",
                                       benchmark_ticker="USO")])

            def fake_cache(*, ticker: str, start: str, end: str) -> list[str]:
                if ticker == "UGA":
                    return ["2021-05-07", "2021-05-10"]
                return []
            with patch.object(
                cli, "_read_cached_window", side_effect=fake_cache,
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        uga = next(w for w in env["windows"] if w["ticker"] == "UGA")
        uso = next(w for w in env["windows"] if w["ticker"] == "USO")
        self.assertEqual(uga["cached_bars"], 2)
        self.assertEqual(uso["cached_bars"], 0)


# ---------------------------------------------------------------------------
# --confirm-online flow
# ---------------------------------------------------------------------------


class ConfirmOnlineFlowTests(unittest.TestCase):

    def test_online_mode_invokes_fetch_seam_per_ticker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row(primary_ticker="UGA",
                                       benchmark_ticker="USO")])

            def fake_fetch(*, ticker: str, start: str, end: str):
                return [_provider_row(ticker=ticker, date="2021-05-10")], []

            fixture = _make_live_db_fixture()
            try:
                before = _sha256(fixture)
                with patch.object(
                    cli, "_read_cached_window",
                    return_value=[],
                ), patch.object(
                    cli, "_fetch_ticker_rows_online", side_effect=fake_fetch,
                ) as fetch_seam:
                    env = cli.run_manual_five_event_cache_backfill_preview(
                        input_csv=str(csv_path),
                        confirm_online=True,
                        db_path=fixture,
                    )
                after = _sha256(fixture)
            finally:
                os.unlink(fixture)
        self.assertTrue(env["ok"], env.get("errors"))
        self.assertEqual(env["mode"], "online")
        self.assertTrue(env["confirm_online"])
        self.assertEqual(fetch_seam.call_count, 2)  # UGA + USO
        self.assertEqual(env["fetched_rows"], 2)
        self.assertEqual(env["inserted_temp_rows"], 2)
        self.assertIsNotNone(env["temp_db_path"])
        self.assertNotEqual(env["temp_db_path"], fixture)
        self.assertTrue(env["live_db_unchanged"])
        self.assertEqual(before, after,
                         "live DB bytes changed during online preview run")

    def test_online_rows_actually_land_in_temp_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row(primary_ticker="X",
                                       benchmark_ticker="SPY")])

            def fake_fetch(*, ticker: str, start: str, end: str):
                return [
                    _provider_row(ticker=ticker, date="2018-05-30", close=10.0),
                    _provider_row(ticker=ticker, date="2018-05-31", close=11.0),
                ], []

            fixture = _make_live_db_fixture()
            try:
                with patch.object(
                    cli, "_read_cached_window",
                    return_value=[],
                ), patch.object(
                    cli, "_fetch_ticker_rows_online", side_effect=fake_fetch,
                ):
                    env = cli.run_manual_five_event_cache_backfill_preview(
                        input_csv=str(csv_path),
                        confirm_online=True,
                        db_path=fixture,
                    )
                self.assertTrue(env["ok"], env.get("errors"))
                temp_path = env["temp_db_path"]
                self.assertTrue(temp_path and Path(temp_path).exists())
                conn = sqlite3.connect(temp_path)
                try:
                    rows = conn.execute(
                        "SELECT ticker, date, close FROM price_cache "
                        "ORDER BY ticker, date"
                    ).fetchall()
                finally:
                    conn.close()
            finally:
                os.unlink(fixture)
                if temp_path and Path(temp_path).exists():
                    Path(temp_path).unlink(missing_ok=True)
        self.assertEqual(len(rows), 4)  # 2 X + 2 SPY
        self.assertEqual({r[0] for r in rows}, {"X", "SPY"})

    def test_online_fetch_zero_rows_still_keeps_live_db_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])

            def fake_fetch(*, ticker: str, start: str, end: str):
                return [], []

            fixture = _make_live_db_fixture()
            try:
                before = _sha256(fixture)
                with patch.object(
                    cli, "_read_cached_window",
                    return_value=[],
                ), patch.object(
                    cli, "_fetch_ticker_rows_online", side_effect=fake_fetch,
                ):
                    env = cli.run_manual_five_event_cache_backfill_preview(
                        input_csv=str(csv_path),
                        confirm_online=True,
                        db_path=fixture,
                    )
                after = _sha256(fixture)
            finally:
                os.unlink(fixture)
                if env.get("temp_db_path") and Path(env["temp_db_path"]).exists():
                    Path(env["temp_db_path"]).unlink(missing_ok=True)
        self.assertEqual(before, after)
        self.assertTrue(env["live_db_unchanged"])
        self.assertEqual(env["fetched_rows"], 0)
        self.assertEqual(env["inserted_temp_rows"], 0)

    def test_online_fetch_error_surfaces_but_live_db_still_unchanged(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])

            def fake_fetch(*, ticker: str, start: str, end: str):
                return [], [f"network failed for {ticker}"]

            fixture = _make_live_db_fixture()
            try:
                before = _sha256(fixture)
                with patch.object(
                    cli, "_read_cached_window",
                    return_value=[],
                ), patch.object(
                    cli, "_fetch_ticker_rows_online", side_effect=fake_fetch,
                ):
                    env = cli.run_manual_five_event_cache_backfill_preview(
                        input_csv=str(csv_path),
                        confirm_online=True,
                        db_path=fixture,
                    )
                after = _sha256(fixture)
            finally:
                os.unlink(fixture)
                if env.get("temp_db_path") and Path(env["temp_db_path"]).exists():
                    Path(env["temp_db_path"]).unlink(missing_ok=True)
        self.assertTrue(env["live_db_unchanged"])
        self.assertEqual(before, after)
        joined = " ".join(env["errors"]).lower()
        self.assertIn("network failed", joined)


# ---------------------------------------------------------------------------
# Live-DB byte identity
# ---------------------------------------------------------------------------


class LiveDbByteIdentityTests(unittest.TestCase):

    def test_default_mode_preserves_live_db_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            fixture = _make_live_db_fixture()
            try:
                before = _sha256(fixture)
                with patch.object(
                    cli, "_read_cached_window",
                    return_value=[],
                ):
                    env = cli.run_manual_five_event_cache_backfill_preview(
                        input_csv=str(csv_path),
                        confirm_online=False,
                        db_path=fixture,
                    )
                after = _sha256(fixture)
            finally:
                os.unlink(fixture)
        self.assertEqual(before, after)
        self.assertTrue(env["live_db_unchanged"])

    def test_online_mode_preserves_live_db_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])

            def fake_fetch(*, ticker: str, start: str, end: str):
                return [_provider_row(ticker=ticker, date="2021-05-10")], []

            fixture = _make_live_db_fixture()
            try:
                before = _sha256(fixture)
                with patch.object(
                    cli, "_read_cached_window",
                    return_value=[],
                ), patch.object(
                    cli, "_fetch_ticker_rows_online", side_effect=fake_fetch,
                ):
                    env = cli.run_manual_five_event_cache_backfill_preview(
                        input_csv=str(csv_path),
                        confirm_online=True,
                        db_path=fixture,
                    )
                after = _sha256(fixture)
            finally:
                os.unlink(fixture)
                if env.get("temp_db_path") and Path(env["temp_db_path"]).exists():
                    Path(env["temp_db_path"]).unlink(missing_ok=True)
        self.assertEqual(before, after)
        self.assertTrue(env["live_db_unchanged"])


# ---------------------------------------------------------------------------
# CSV ingestion
# ---------------------------------------------------------------------------


class CsvIngestionTests(unittest.TestCase):

    def test_missing_csv_yields_ok_false_with_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "no.csv")
            env = cli.run_manual_five_event_cache_backfill_preview(
                input_csv=missing,
                confirm_online=False,
                db_path=None,
            )
        self.assertFalse(env["ok"])
        self.assertGreaterEqual(len(env["errors"]), 1)

    def test_rows_with_missing_required_fields_surface_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [
                _row(primary_ticker=""),  # no ticker
            ])
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                env = cli.run_manual_five_event_cache_backfill_preview(
                    input_csv=str(csv_path),
                    confirm_online=False,
                    db_path=None,
                )
        self.assertEqual(env["rows_loaded"], 1)
        joined = " ".join(env["blocked_reasons"]).lower()
        self.assertIn("primary_ticker", joined)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):

    def test_json_emission_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            buf = io.StringIO()
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                rc = cli.main([
                    "--json", "--input-csv", str(csv_path),
                ], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(parsed["mode"], "preview")

    def test_confirm_online_cli_flag_switches_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            buf = io.StringIO()

            def fake_fetch(*, ticker: str, start: str, end: str):
                return [_provider_row(ticker=ticker, date="2021-05-10")], []

            fixture = _make_live_db_fixture()
            try:
                with patch.object(
                    cli, "_read_cached_window",
                    return_value=[],
                ), patch.object(
                    cli, "_fetch_ticker_rows_online", side_effect=fake_fetch,
                ):
                    rc = cli.main([
                        "--json", "--confirm-online",
                        "--input-csv", str(csv_path),
                        "--db-path", fixture,
                    ], out=buf)
            finally:
                os.unlink(fixture)
                parsed = json.loads(buf.getvalue())
                if parsed.get("temp_db_path") and Path(parsed["temp_db_path"]).exists():
                    Path(parsed["temp_db_path"]).unlink(missing_ok=True)
        self.assertEqual(rc, 0)
        self.assertEqual(parsed["mode"], "online")
        self.assertTrue(parsed["confirm_online"])


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class ConservativeWordingTests(unittest.TestCase):

    def test_rendered_json_carries_no_banned_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_row()])
            buf = io.StringIO()
            with patch.object(
                cli, "_read_cached_window",
                return_value=[],
            ):
                cli.main([
                    "--json", "--input-csv", str(csv_path),
                ], out=buf)
        text = buf.getvalue().lower()
        for tok in _BANNED_TOKENS:
            self.assertNotIn(
                tok, text,
                msg=f"banned token {tok!r} appeared in rendered JSON",
            )

    def test_module_docstring_carries_no_banned_tokens(self) -> None:
        doc = (cli.__doc__ or "").lower()
        for tok in _BANNED_TOKENS:
            self.assertNotIn(
                tok, doc,
                msg=f"banned token {tok!r} appeared in module docstring",
            )


# ---------------------------------------------------------------------------
# Read-only / import isolation
# ---------------------------------------------------------------------------


class ReadOnlyContractTests(unittest.TestCase):

    _BLOCKED: tuple[str, ...] = (
        "yfinance",
        "market_data",
        "market_check",
        "news_fetch",
        "news_relevance",
        "api",
        "openai",
        "anthropic",
        "fastapi",
    )

    def test_default_import_does_not_pull_in_yfinance_or_routes(self) -> None:
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name=(
                "scripts.manual_five_event_cache_backfill_preview"
            ),
            blocked=self._BLOCKED,
            blocked_starts_with=("routes.",),
        )

    def test_source_never_connects_to_live_db_path(self) -> None:
        """The script source must not contain a call that writes to
        the live cache.  ``sqlite3.connect`` may appear, but only in a
        helper that targets a temp path; this guard pins that any
        ``connect`` line either: (a) has a ``temp`` substring on the
        same call (e.g. ``temp_db_path``), or (b) sits in code whose
        intent is read-only.  The cleanest pin is the absence of any
        ``DB_FILE`` / ``connect_db`` / ``_db.connect`` references.
        """
        src_path = _REPO_ROOT / "scripts" / (
            "manual_five_event_cache_backfill_preview.py"
        )
        text = src_path.read_text(encoding="utf-8")
        # The script must NOT use db.connect_db / _db.connect_db — those
        # would route into the live events.db.
        for banned in (
            "db.connect_db",
            "_db.connect_db",
            "from db import",
        ):
            self.assertNotIn(
                banned, text,
                msg=f"forbidden live-DB writer reference: {banned!r}",
            )

    def test_source_does_not_call_writer_outside_temp_paths(self) -> None:
        """Any ``conn.execute(...INSERT...)`` in the source must run
        on a connection opened against a path that the source itself
        constructed under ``tempfile`` — never the live cache path.
        """
        src_path = _REPO_ROOT / "scripts" / (
            "manual_five_event_cache_backfill_preview.py"
        )
        text = src_path.read_text(encoding="utf-8")
        if "INSERT" in text.upper():
            # If we're inserting at all, the script must also reference
            # tempfile so the insert target is clearly a temp DB.
            self.assertIn(
                "tempfile", text,
                msg=(
                    "script INSERTs but does not import tempfile — "
                    "could be writing to a non-temp path"
                ),
            )


# ---------------------------------------------------------------------------
# Bundled CSV smoke
# ---------------------------------------------------------------------------


class BundledCsvTests(unittest.TestCase):

    _CSV_PATH = _REPO_ROOT / "examples" / "manual_five_event_expansion_batch.csv"

    def test_default_run_on_bundled_csv_is_ok(self) -> None:
        if not self._CSV_PATH.is_file():
            self.skipTest("bundled CSV not present in this checkout")
        with patch.object(
            cli, "_read_cached_window",
            return_value=[],
        ):
            env = cli.run_manual_five_event_cache_backfill_preview(
                input_csv=str(self._CSV_PATH),
                confirm_online=False,
                db_path=None,
            )
        self.assertTrue(env["ok"])
        self.assertEqual(env["rows_loaded"], 5)
        self.assertEqual(env["mode"], "preview")
        # Five rows × (primary, benchmark) = 10 windows.
        self.assertEqual(len(env["windows"]), 10)
        # The five canonical tickers from the operator batch.
        self.assertEqual(
            set(env["tickers"]),
            {"UGA", "USO", "NUE", "SPY", "KBE",
             "NVDA", "SMH", "MATX", "IYT"},
        )


if __name__ == "__main__":
    unittest.main()
