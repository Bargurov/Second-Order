"""Tests for ``scripts/xle_benchmark_comparison_input_diagnostic.py``.

The diagnostic is a read-only coverage report — for each event in
the default backlog (60, 73) it asks whether the primary ticker AND
both ``SPY`` AND ``XLE`` have enough ``price_cache`` rows for the
forward horizons and the estimation window a benchmark comparison
would need.

Pin the contract:

* Read-only: no DB writes, no provider, no LLM, no FastAPI.  The
  diagnostic calls
  :func:`scripts.benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight`
  twice (once per benchmark) via a single patchable seam and reads
  cache summaries (count, min_date, max_date) via a second seam.  It
  does NOT depend on ``xle_benchmark_sensitivity_compare_smoke``
  internals.
* Per-event row carries the keys the spec lists, every cache summary
  has ``rows_in_cache``, ``min_date``, ``max_date``, ``available``.
* ``missing_by_ticker`` is keyed by ticker SYMBOL (not by role), and
  the primary key is omitted when ``primary_ticker is None``.
* ``missing_inputs`` is a flat list of ``{event_id, ticker, ranges}``
  entries, one per (event, ticker) with non-empty missing ranges —
  audit-friendly aggregation across all events.
* ``ready_for_comparison`` is an INT count of events whose
  ``can_attempt_comparison`` is True.
* Conservative wording — banned tokens (``proof``, ``proves``,
  ``proven``, ``alpha``, ``guaranteed``, ``automatically``,
  ``validated``, ``definitely``, ``causes``, ``causation``) absent
  from any text the diagnostic emits.  No SPY-vs-XLE verdict ever.
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
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import xle_benchmark_comparison_input_diagnostic as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "checked_events",
    "rows",
    "missing_inputs",
    "ready_for_comparison",
    "warnings",
    "errors",
    "recommended_next_action",
)


_REQUIRED_ROW_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "benchmark_tickers_checked",
    "primary_cache_summary",
    "spy_cache_summary",
    "xle_cache_summary",
    "horizons_checked",
    "missing_by_ticker",
    "can_attempt_comparison",
)


_REQUIRED_SUMMARY_KEYS = (
    "rows_in_cache",
    "min_date",
    "max_date",
    "available",
)


_BANNED_WORDS = (
    "proof",
    "proves",
    "proven",
    "alpha",
    "guaranteed",
    "automatically",
    "validated",
    "definitely",
    "causes",
    "causation",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _preflight_report(
    *,
    benchmark: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a synthetic preflight envelope for ``benchmark`` carrying
    the rows the diagnostic will combine.  Mirrors the public shape
    of :func:`summarize_benchmark_sensitivity_preflight`.
    """
    ready = sum(1 for r in rows if r.get("can_run_sensitivity"))
    return {
        "ok":             True,
        "checked_events": len(rows),
        "ready_count":    ready,
        "blocked_count":  len(rows) - ready,
        "rows":           list(rows),
        "recommended_next_action": "synthetic",
    }


def _event_row(
    *,
    event_id: int,
    event_date: str | None = "2026-04-08",
    primary_ticker: str | None = "XOM",
    benchmark_ticker: str = "SPY",
    primary_cache_available: bool = True,
    benchmark_cache_available: bool = True,
    missing_primary_ranges: list[dict[str, str]] | None = None,
    missing_benchmark_ranges: list[dict[str, str]] | None = None,
    can_run_sensitivity: bool | None = None,
) -> dict[str, Any]:
    """Build a single per-event preflight row.  Defaults to a happy
    case so tests override only the fields they care about.
    """
    if can_run_sensitivity is None:
        can_run_sensitivity = bool(
            primary_cache_available and benchmark_cache_available
        )
    return {
        "event_id":                  event_id,
        "event_date":                event_date,
        "primary_ticker":            primary_ticker,
        "benchmark_ticker":          benchmark_ticker,
        "required_horizons":         [1, 5, 20],
        "primary_cache_available":   primary_cache_available,
        "benchmark_cache_available": benchmark_cache_available,
        "missing_primary_ranges":    list(missing_primary_ranges or []),
        "missing_benchmark_ranges":  list(missing_benchmark_ranges or []),
        "can_run_sensitivity":       can_run_sensitivity,
        "blocker_reason":            "" if can_run_sensitivity else "missing_estimation_window",
    }


def _cache_summary(
    *,
    rows_in_cache: int = 100,
    min_date: str | None = "2025-01-01",
    max_date: str | None = "2026-04-30",
) -> dict[str, Any]:
    return {
        "rows_in_cache": rows_in_cache,
        "min_date":      min_date,
        "max_date":      max_date,
    }


def _summaries_seam(
    *,
    primary_summary: dict[str, Any] | None = None,
    spy_summary:     dict[str, Any] | None = None,
    xle_summary:     dict[str, Any] | None = None,
    primary_ticker:  str = "XOM",
):
    """Build a callable suitable for ``patch.object(cli,
    '_load_cache_summaries', side_effect=...)`` that returns one
    canned dict regardless of the tickers argument.
    """
    def _seam(*, db_path, tickers):  # noqa: ANN001
        out: dict[str, dict[str, Any]] = {}
        if primary_summary is not None:
            out[primary_ticker.strip().upper()] = primary_summary
        if spy_summary is not None:
            out["SPY"] = spy_summary
        if xle_summary is not None:
            out["XLE"] = xle_summary
        return out
    return _seam


class _PreflightSeam:
    """Routes each preflight call to the canned report for the
    benchmark the diagnostic asked about."""

    def __init__(
        self, *,
        spy: dict[str, Any],
        xle: dict[str, Any],
    ) -> None:
        self.spy = spy
        self.xle = xle
        self.call_log: list[str] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        bench = (kwargs.get("benchmark") or "").upper()
        self.call_log.append(bench)
        if bench == "SPY":
            return self.spy
        if bench == "XLE":
            return self.xle
        return {"ok": True, "rows": []}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    def test_all_events_ready_for_comparison(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60, benchmark_ticker="SPY"),
            _event_row(event_id=73, benchmark_ticker="SPY"),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60, benchmark_ticker="XLE"),
            _event_row(event_id=73, benchmark_ticker="XLE"),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60, 73],
            )
        self.assertTrue(report["ok"], report.get("errors"))
        self.assertEqual(report["checked_events"], 2)
        self.assertEqual(report["ready_for_comparison"], 2)
        self.assertEqual(report["missing_inputs"], [])
        for row in report["rows"]:
            self.assertTrue(row["can_attempt_comparison"],
                            f"row: {row}")
            for key in ("primary_cache_summary",
                        "spy_cache_summary", "xle_cache_summary"):
                self.assertTrue(row[key]["available"],
                                f"{key}: {row[key]}")

    def test_preflight_called_once_per_benchmark(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60),
        ])
        seam = _PreflightSeam(spy=spy, xle=xle)
        with patch.object(
            cli, "_run_preflight", side_effect=seam,
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        self.assertEqual(sorted(seam.call_log), ["SPY", "XLE"])


# ---------------------------------------------------------------------------
# Missing inputs
# ---------------------------------------------------------------------------


class TestMissingInputs(unittest.TestCase):
    def test_spy_short_coverage_blocks_event(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(
                event_id=60, benchmark_ticker="SPY",
                benchmark_cache_available=False,
                missing_benchmark_ranges=[
                    {"start": "2026-01-01", "end": "2026-03-30",
                     "reason": "estimation_window_short"},
                ],
            ),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(
                event_id=60, benchmark_ticker="XLE",
            ),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(rows_in_cache=10),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        self.assertEqual(report["ready_for_comparison"], 0)
        row = report["rows"][0]
        self.assertFalse(row["can_attempt_comparison"])
        self.assertFalse(row["spy_cache_summary"]["available"])
        self.assertTrue(row["xle_cache_summary"]["available"])
        self.assertIn("SPY", row["missing_by_ticker"])
        self.assertNotIn("XLE", row["missing_by_ticker"])
        self.assertEqual(report["missing_inputs"], [{
            "event_id": 60, "ticker": "SPY",
            "ranges": [{"start": "2026-01-01",
                        "end": "2026-03-30",
                        "reason": "estimation_window_short"}],
        }])

    def test_xle_short_coverage_surfaces_xle_in_missing_inputs(
        self,
    ) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=73),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(
                event_id=73, benchmark_ticker="XLE",
                benchmark_cache_available=False,
                missing_benchmark_ranges=[
                    {"start": "2026-03-26", "end": "2026-04-02",
                     "reason": "estimation_window_short"},
                ],
            ),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(rows_in_cache=2),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[73],
            )
        self.assertEqual(report["missing_inputs"], [{
            "event_id": 73, "ticker": "XLE",
            "ranges": [{"start": "2026-03-26",
                        "end": "2026-04-02",
                        "reason": "estimation_window_short"}],
        }])

    def test_primary_short_coverage_surfaces_primary_in_missing_inputs(
        self,
    ) -> None:
        primary_range = [{
            "start": "2026-01-01", "end": "2026-03-30",
            "reason": "estimation_window_short",
        }]
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(
                event_id=60,
                primary_cache_available=False,
                missing_primary_ranges=primary_range,
            ),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(
                event_id=60, benchmark_ticker="XLE",
                primary_cache_available=False,
                missing_primary_ranges=primary_range,
            ),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(rows_in_cache=5),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        row = report["rows"][0]
        # Primary short → both benchmarks become moot for THIS event,
        # but the diagnostic still reports each ticker's coverage flag
        # independently.
        self.assertFalse(row["primary_cache_summary"]["available"])
        self.assertFalse(row["can_attempt_comparison"])
        # missing_by_ticker keyed by the actual primary symbol.
        self.assertIn("XOM", row["missing_by_ticker"])
        # And missing_inputs lists primary first per the spec order.
        self.assertEqual(report["missing_inputs"][0]["ticker"], "XOM")

    def test_primary_ranges_deduped_across_preflights(self) -> None:
        same_range = [{
            "start": "2026-01-01", "end": "2026-03-30",
            "reason": "estimation_window_short",
        }]
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(
                event_id=60,
                primary_cache_available=False,
                missing_primary_ranges=same_range,
            ),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(
                event_id=60, benchmark_ticker="XLE",
                primary_cache_available=False,
                missing_primary_ranges=same_range,
            ),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        # The same range was returned by both preflights; the
        # diagnostic must dedupe so missing_by_ticker['XOM'] has only
        # one entry, not two.
        self.assertEqual(
            report["rows"][0]["missing_by_ticker"]["XOM"],
            same_range,
        )


# ---------------------------------------------------------------------------
# Missing primary ticker (events table empty for the event)
# ---------------------------------------------------------------------------


class TestMissingPrimaryTicker(unittest.TestCase):
    def test_event_without_primary_ticker_blocked(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(
                event_id=60, primary_ticker=None,
                primary_cache_available=False,
                can_run_sensitivity=False,
            ),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(
                event_id=60, benchmark_ticker="XLE",
                primary_ticker=None,
                primary_cache_available=False,
                can_run_sensitivity=False,
            ),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        row = report["rows"][0]
        self.assertIsNone(row["primary_ticker"])
        self.assertFalse(row["can_attempt_comparison"])
        # missing_by_ticker must NOT carry a None key.
        for k in row["missing_by_ticker"].keys():
            self.assertIsInstance(k, str)
            self.assertTrue(k, f"empty key in missing_by_ticker: {k!r}")

    def test_event_with_missing_event_date_does_not_crash(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(
                event_id=60, event_date=None,
                primary_cache_available=False,
                benchmark_cache_available=False,
                can_run_sensitivity=False,
            ),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(
                event_id=60, event_date=None,
                benchmark_ticker="XLE",
                primary_cache_available=False,
                benchmark_cache_available=False,
                can_run_sensitivity=False,
            ),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        # ok stays True — the diagnostic *reports* missing inputs.
        self.assertTrue(report["ok"])
        row = report["rows"][0]
        self.assertIsNone(row["event_date"])
        self.assertFalse(row["can_attempt_comparison"])


# ---------------------------------------------------------------------------
# Disagreement reconciliation between SPY and XLE preflights
# ---------------------------------------------------------------------------


class TestPreflightDisagreement(unittest.TestCase):
    def test_primary_ticker_disagreement_surfaces_warning(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60, primary_ticker="XOM"),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60, primary_ticker="CVX",
                       benchmark_ticker="XLE"),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        joined = " ".join(report["warnings"]).lower()
        self.assertIn("primary_ticker", joined,
                      f"warnings: {report['warnings']}")

    def test_primary_availability_disagreement_takes_conservative_and(
        self,
    ) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60, primary_cache_available=True),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60, primary_cache_available=False,
                       benchmark_ticker="XLE"),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        row = report["rows"][0]
        self.assertFalse(row["primary_cache_summary"]["available"])
        joined = " ".join(report["warnings"]).lower()
        self.assertIn("primary_cache_available", joined,
                      f"warnings: {report['warnings']}")


# ---------------------------------------------------------------------------
# Cache summaries
# ---------------------------------------------------------------------------


class TestCacheSummaries(unittest.TestCase):
    def test_summary_values_propagate_from_seam(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(
                    rows_in_cache=512,
                    min_date="2025-01-02",
                    max_date="2026-04-30",
                ),
                spy_summary=_cache_summary(
                    rows_in_cache=1024,
                    min_date="2024-01-02",
                    max_date="2026-04-30",
                ),
                xle_summary=_cache_summary(
                    rows_in_cache=256,
                    min_date="2025-06-01",
                    max_date="2026-04-30",
                ),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        row = report["rows"][0]
        self.assertEqual(row["primary_cache_summary"]["rows_in_cache"], 512)
        self.assertEqual(row["spy_cache_summary"]["rows_in_cache"],     1024)
        self.assertEqual(row["xle_cache_summary"]["rows_in_cache"],     256)
        self.assertEqual(row["primary_cache_summary"]["min_date"], "2025-01-02")
        self.assertEqual(row["xle_cache_summary"]["max_date"],     "2026-04-30")

    def test_summary_keys_complete(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        row = report["rows"][0]
        for key in ("primary_cache_summary", "spy_cache_summary",
                    "xle_cache_summary"):
            self.assertEqual(set(row[key].keys()),
                             set(_REQUIRED_SUMMARY_KEYS),
                             f"{key}: {row[key]}")


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_top_level_keys(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[])
        xle = _preflight_report(benchmark="XLE", rows=[])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[],
            )
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")

    def test_per_row_keys(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        for row in report["rows"]:
            self.assertEqual(set(row.keys()), set(_REQUIRED_ROW_KEYS),
                             f"unexpected row keys: {sorted(row.keys())}")

    def test_benchmark_tickers_checked_is_spy_and_xle(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            report = cli.run_xle_benchmark_comparison_input_diagnostic(
                event_ids=[60],
            )
        self.assertEqual(report["rows"][0]["benchmark_tickers_checked"],
                         ["SPY", "XLE"])


# ---------------------------------------------------------------------------
# Read-only invariants
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_real_load_cache_summaries_issues_only_select(self) -> None:
        # Build a fixture price_cache and drive the REAL seam against
        # it.  After the call the DB byte hash must match the
        # pre-call hash — the seam issues only SELECT.
        path = os.path.join(
            tempfile.gettempdir(),
            f"xle_diag_fix_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(path)
        try:
            conn.execute("""
                CREATE TABLE price_cache (
                    ticker TEXT NOT NULL,
                    date   TEXT NOT NULL,
                    close  REAL,
                    volume REAL,
                    auto_adjust INTEGER NOT NULL,
                    fetched_at  TEXT NOT NULL,
                    PRIMARY KEY (ticker, date, auto_adjust)
                )
            """)
            conn.execute(
                "INSERT INTO price_cache VALUES "
                "('SPY', '2026-01-02', 480.0, 1.0, 1, '')"
            )
            conn.execute(
                "INSERT INTO price_cache VALUES "
                "('XLE', '2026-01-02',  90.0, 1.0, 1, '')"
            )
            conn.commit()
        finally:
            conn.close()
        try:
            import hashlib
            def sha256(p):  # noqa: ANN001
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                return h.hexdigest()
            before = sha256(path)
            result = cli._load_cache_summaries(
                db_path=path, tickers=["SPY", "XLE"],
            )
            self.assertEqual(sha256(path), before,
                             "_load_cache_summaries mutated the DB")
            # Sanity-check the values it returned.
            self.assertEqual(result["SPY"]["rows_in_cache"], 1)
            self.assertEqual(result["XLE"]["rows_in_cache"], 1)
            self.assertEqual(result["SPY"]["min_date"], "2026-01-02")
        finally:
            os.unlink(path)

    def test_load_cache_summaries_handles_missing_db(self) -> None:
        result = cli._load_cache_summaries(
            db_path=os.path.join(
                tempfile.gettempdir(),
                f"no_such_db_{uuid.uuid4().hex}.db",
            ),
            tickers=["SPY", "XLE"],
        )
        # Empty entries instead of a crash — degrades gracefully.
        self.assertEqual(result["SPY"]["rows_in_cache"], 0)
        self.assertEqual(result["XLE"]["rows_in_cache"], 0)
        self.assertIsNone(result["SPY"]["min_date"])
        self.assertIsNone(result["XLE"]["max_date"])


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _run_each_recommendation_path(self) -> list[str]:
        actions: list[str] = []
        cases = (
            # All ready
            (True, True, True, True, True),
            # SPY short
            (True, True, False, True, True),
            # XLE short
            (True, True, True, False, True),
            # Primary short for one of two events
            (True, False, True, True, False),
            # All blocked
            (False, False, False, False, False),
        )
        for case in cases:
            (
                primary_ev60, primary_ev73,
                spy_ev60, xle_ev60, dummy,
            ) = case
            spy_rows = [
                _event_row(
                    event_id=60,
                    primary_cache_available=primary_ev60,
                    benchmark_cache_available=spy_ev60,
                    benchmark_ticker="SPY",
                ),
                _event_row(
                    event_id=73,
                    primary_cache_available=primary_ev73,
                    benchmark_cache_available=spy_ev60,
                    benchmark_ticker="SPY",
                ),
            ]
            xle_rows = [
                _event_row(
                    event_id=60,
                    primary_cache_available=primary_ev60,
                    benchmark_cache_available=xle_ev60,
                    benchmark_ticker="XLE",
                ),
                _event_row(
                    event_id=73,
                    primary_cache_available=primary_ev73,
                    benchmark_cache_available=xle_ev60,
                    benchmark_ticker="XLE",
                ),
            ]
            with patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam(
                    spy=_preflight_report(benchmark="SPY", rows=spy_rows),
                    xle=_preflight_report(benchmark="XLE", rows=xle_rows),
                ),
            ), patch.object(
                cli, "_load_cache_summaries",
                side_effect=_summaries_seam(
                    primary_summary=_cache_summary(),
                    spy_summary=_cache_summary(),
                    xle_summary=_cache_summary(),
                ),
            ):
                report = cli.run_xle_benchmark_comparison_input_diagnostic(
                    event_ids=[60, 73],
                )
            actions.append(report["recommended_next_action"])
        return actions

    def test_no_banned_tokens_in_any_recommendation(self) -> None:
        for action in self._run_each_recommendation_path():
            lowered = action.lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(w, lowered,
                                 f"banned word {w!r} in {action!r}")

    def test_no_benchmark_verdict_in_any_recommendation(self) -> None:
        for action in self._run_each_recommendation_path():
            lowered = action.lower()
            for forbidden in (
                "spy is better than xle",
                "xle is better than spy",
                "spy outperforms",
                "xle outperforms",
                "spy beats xle",
                "xle beats spy",
                "more sensitive",
            ):
                self.assertNotIn(forbidden, lowered,
                                 f"premature verdict: {action!r}")


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api", "market_data")

    def test_module_import_does_not_pull_provider_or_fastapi(self) -> None:
        # Subprocess-isolated: an in-process scan reads sys.modules
        # state polluted by prior tests in the same discovery run.
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name=(
                "scripts.xle_benchmark_comparison_input_diagnostic"
            ),
            blocked=self._BLOCKED,
        )

    def test_module_does_not_import_compare_smoke(self) -> None:
        # Constraint: "Do not depend on
        # xle_benchmark_sensitivity_compare_smoke internals."  The
        # cleanest enforcement is: don't import it at all.
        # Subprocess-isolated so a prior test that imported the
        # compare smoke for its own use cannot make this test fail.
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name=(
                "scripts.xle_benchmark_comparison_input_diagnostic"
            ),
            blocked=(
                "scripts.xle_benchmark_sensitivity_compare_smoke",
                "xle_benchmark_sensitivity_compare_smoke",
            ),
            blocked_starts_with=(),
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_valid_json(self) -> None:
        spy = _preflight_report(benchmark="SPY", rows=[
            _event_row(event_id=60),
        ])
        xle = _preflight_report(benchmark="XLE", rows=[
            _event_row(event_id=60),
        ])
        with patch.object(
            cli, "_run_preflight",
            side_effect=_PreflightSeam(spy=spy, xle=xle),
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            out = StringIO()
            rc = cli.main(["--json", "--event-ids", "60"], out=out)
        self.assertEqual(rc, 0, f"output: {out.getvalue()}")
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_TOP_KEYS:
            self.assertIn(k, parsed)
        self.assertTrue(parsed["ok"])

    def test_cli_respects_horizons_and_estimation_window(self) -> None:
        seam = _PreflightSeam(
            spy=_preflight_report(benchmark="SPY", rows=[
                _event_row(event_id=60),
            ]),
            xle=_preflight_report(benchmark="XLE", rows=[
                _event_row(event_id=60),
            ]),
        )
        with patch.object(
            cli, "_run_preflight", side_effect=seam,
        ), patch.object(
            cli, "_load_cache_summaries",
            side_effect=_summaries_seam(
                primary_summary=_cache_summary(),
                spy_summary=_cache_summary(),
                xle_summary=_cache_summary(),
            ),
        ):
            out = StringIO()
            cli.main(
                ["--json", "--event-ids", "60",
                 "--horizons", "1,5",
                 "--estimation-window", "30"],
                out=out,
            )
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["rows"][0]["horizons_checked"], [1, 5])


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_path_passed(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"xle_diag_out_{uuid.uuid4().hex}.json",
        )
        try:
            spy = _preflight_report(benchmark="SPY", rows=[
                _event_row(event_id=60),
            ])
            xle = _preflight_report(benchmark="XLE", rows=[
                _event_row(event_id=60),
            ])
            with patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam(spy=spy, xle=xle),
            ), patch.object(
                cli, "_load_cache_summaries",
                side_effect=_summaries_seam(
                    primary_summary=_cache_summary(),
                    spy_summary=_cache_summary(),
                    xle_summary=_cache_summary(),
                ),
            ):
                cli.run_xle_benchmark_comparison_input_diagnostic(
                    event_ids=[60], output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            for k in _REQUIRED_TOP_KEYS:
                self.assertIn(k, parsed)
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
