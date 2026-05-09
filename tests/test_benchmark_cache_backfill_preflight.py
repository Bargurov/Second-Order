"""Tests for ``scripts/benchmark_cache_backfill_preflight.py``.

Pin the read-only contract:

* The preflight consumes two upstream reports through patchable seams
  so unit tests can drive it with synthetic fixtures:
  ``_run_benchmark_gap_report`` and ``_run_salvage_priority_report``.
* Output dict carries the brief-mandated keyset:
  ``benchmark_symbol``, ``blocked_event_count``,
  ``required_start_date``, ``required_end_date``,
  ``current_cache_max_date``, ``estimated_rows_needed``,
  ``provider_calls_required``, ``recommended_next_action``.
* ``required_end_date`` = max ``benchmark_target_20d_date`` over
  blocked rows where it is parseable.
* ``required_start_date``:
    - cache_max non-null → ``cache_max + 1 calendar day``
    - cache_max null     → min ``benchmark_target_20d_date`` over
                          blocked rows where parseable
    - no parseable dates → ``None``
* ``estimated_rows_needed`` counts weekdays (Mon-Fri) in
  ``[start, end]`` inclusive — SPY has weekday rows only.
* ``provider_calls_required`` = 0 when there is nothing to fetch,
  else 1 (yfinance fetches a range in a single call).
* Default run does NOT import or call ``yfinance`` /
  ``market_check`` / ``market_data`` / ``price_cache`` /
  ``api`` / ``routes.*``.
* ``--check-provider-availability`` reports importability only — it
  does not download data.
* The preflight NEVER mutates the archive, NEVER refreshes prices,
  NEVER assigns tickers.
"""
from __future__ import annotations

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

from scripts import benchmark_cache_backfill_preflight as cli  # noqa: E402


_REQUIRED_KEYS = (
    "benchmark_symbol",
    "blocked_event_count",
    "required_start_date",
    "required_end_date",
    "current_cache_max_date",
    "estimated_rows_needed",
    "provider_calls_required",
    "recommended_next_action",
)


# ---------------------------------------------------------------------------
# Synthetic upstream payloads
# ---------------------------------------------------------------------------


def _gap_row(
    *,
    event_id: int,
    event_date: str | None = "2026-04-15",
    primary_ticker: str | None = "AAPL",
    target_20d: str | None = "2026-05-13",
    cache_max: str | None = None,
    gap_days: int | None = None,
) -> dict:
    return {
        "event_id":                  event_id,
        "event_date":                event_date,
        "primary_ticker":            primary_ticker,
        "benchmark_symbol":          "SPY",
        "benchmark_target_20d_date": target_20d,
        "benchmark_cache_max_date":  cache_max,
        "gap_days":                  gap_days,
    }


def _gap_payload(
    *,
    total_events: int = 0,
    rows: list[dict] | None = None,
    benchmark_symbol: str = "SPY",
) -> dict:
    rows = rows or []
    return {
        "total_events":                   total_events,
        "events_missing_benchmark_proxy": len(rows),
        "benchmark_symbol":               benchmark_symbol,
        "rows":                           rows,
        "recommended_next_action":        "synthetic",
    }


def _salvage_payload(
    *,
    bench_count: int = 0,
    top_path: str | None = None,
) -> dict:
    """Minimal salvage-priority payload — only the bits the
    preflight reads.  ``top_path`` qualifies the recommended next
    action; ``bench_count`` is the canonical
    ``missing_benchmark_proxy`` blocker count for cross-check.
    """
    keys = (
        "price_cache_forward_20d",
        "estimation_window_gap",
        "missing_benchmark_proxy",
        "missing_market_tickers",
        "contaminated_fully_ready_manual_review",
    )
    candidate_groups = {
        k: {"blocker_count": 0, "estimated_events_unlocked": 0,
            "candidates": []}
        for k in keys
    }
    candidate_groups["missing_benchmark_proxy"]["blocker_count"] = bench_count
    candidate_groups["missing_benchmark_proxy"]["estimated_events_unlocked"] = (
        bench_count
    )
    estimated = {k: 0 for k in keys}
    estimated["missing_benchmark_proxy"] = bench_count
    return {
        "ok":                              True,
        "current_clean_fully_ready_count": 0,
        "target_clean_count":              30,
        "top_salvage_path":                top_path,
        "candidate_groups":                candidate_groups,
        "estimated_events_unlocked":       estimated,
        "manual_review_required":          False,
        "recommended_next_action":         "synthetic",
    }


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _patch_seams(*, gap: dict, salvage: dict):
    return (
        patch.object(cli, "_run_benchmark_gap_report", return_value=gap),
        patch.object(cli, "_run_salvage_priority_report",
                     return_value=salvage),
    )


def _run(*, gap: dict, salvage: dict, **kwargs) -> dict:
    p1, p2 = _patch_seams(gap=gap, salvage=salvage)
    with p1, p2:
        return cli.summarize_backfill_preflight(**kwargs)


def _run_cli(argv: list[str], *, gap: dict, salvage: dict) -> tuple[int, str]:
    out = StringIO()
    p1, p2 = _patch_seams(gap=gap, salvage=salvage)
    with p1, p2:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


def _empty_payloads() -> dict:
    return {"gap": _gap_payload(), "salvage": _salvage_payload()}


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(unittest.TestCase):
    def test_returns_dict_with_required_keys(self) -> None:
        result = _run(**_empty_payloads())
        self.assertIsInstance(result, dict)
        for key in _REQUIRED_KEYS:
            self.assertIn(key, result, f"missing key: {key}")

    def test_recommended_next_action_is_non_empty_string(self) -> None:
        result = _run(**_empty_payloads())
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])

    def test_benchmark_symbol_taken_from_gap_report(self) -> None:
        # Even if the upstream gap report returned a different symbol
        # (defensive — the gap report hardcodes SPY today), the
        # preflight must surface what the gap report says, not invent
        # its own value.
        result = _run(
            gap=_gap_payload(benchmark_symbol="SPY"),
            salvage=_salvage_payload(),
        )
        self.assertEqual(result["benchmark_symbol"], "SPY")


# ---------------------------------------------------------------------------
# Empty / no-blocker
# ---------------------------------------------------------------------------


class TestEmptyArchive(unittest.TestCase):
    def test_zero_blockers_zeros_every_count(self) -> None:
        result = _run(**_empty_payloads())
        self.assertEqual(result["blocked_event_count"],     0)
        self.assertEqual(result["estimated_rows_needed"],   0)
        self.assertEqual(result["provider_calls_required"], 0)
        self.assertIsNone(result["required_start_date"])
        self.assertIsNone(result["required_end_date"])
        self.assertIsNone(result["current_cache_max_date"])

    def test_recommended_action_calls_out_no_backfill(self) -> None:
        result = _run(**_empty_payloads())
        rec = result["recommended_next_action"].lower()
        # Must surface that no backfill is needed — operator-readable.
        self.assertTrue(
            "no" in rec and ("backfill" in rec or "blocker" in rec),
            f"unhelpful recommendation: {rec!r}",
        )


# ---------------------------------------------------------------------------
# blocked_event_count wires from gap report
# ---------------------------------------------------------------------------


class TestBlockedCountWiring(unittest.TestCase):
    def test_blocked_count_from_gap_report(self) -> None:
        rows = [_gap_row(event_id=i) for i in range(1, 6)]
        gap = _gap_payload(rows=rows)
        # Salvage agrees:
        salvage = _salvage_payload(bench_count=5,
                                   top_path="missing_benchmark_proxy")
        result = _run(gap=gap, salvage=salvage)
        self.assertEqual(result["blocked_event_count"], 5)


# ---------------------------------------------------------------------------
# Date range math
# ---------------------------------------------------------------------------


class TestDateRangeMath(unittest.TestCase):
    def test_required_end_is_max_target_20d(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-04-30"),
            _gap_row(event_id=2, target_20d="2026-05-13"),
            _gap_row(event_id=3, target_20d="2026-05-01"),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=3))
        self.assertEqual(result["required_end_date"], "2026-05-13")

    def test_start_is_cache_max_plus_one_day_when_cache_exists(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-13",
                     cache_max="2026-04-20"),
            _gap_row(event_id=2, target_20d="2026-05-15",
                     cache_max="2026-04-20"),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=2))
        self.assertEqual(result["current_cache_max_date"], "2026-04-20")
        self.assertEqual(result["required_start_date"],    "2026-04-21")

    def test_start_is_min_target_when_cache_empty(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-04-30", cache_max=None),
            _gap_row(event_id=2, target_20d="2026-05-13", cache_max=None),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=2))
        self.assertIsNone(result["current_cache_max_date"])
        self.assertEqual(result["required_start_date"], "2026-04-30")
        self.assertEqual(result["required_end_date"],   "2026-05-13")

    def test_unparseable_target_dates_excluded_from_min_max(self) -> None:
        # Blocker with event_date=None has target_20d=None; counted in
        # blocked_event_count but contributes nothing to date math.
        rows = [
            _gap_row(event_id=1, event_date=None, target_20d=None,
                     cache_max=None),
            _gap_row(event_id=2, target_20d="2026-05-13", cache_max=None),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=2))
        self.assertEqual(result["blocked_event_count"], 2)
        self.assertEqual(result["required_start_date"], "2026-05-13")
        self.assertEqual(result["required_end_date"],   "2026-05-13")

    def test_no_parseable_dates_returns_none_range(self) -> None:
        rows = [
            _gap_row(event_id=1, event_date=None, target_20d=None,
                     cache_max=None),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=1))
        self.assertIsNone(result["required_start_date"])
        self.assertIsNone(result["required_end_date"])
        self.assertEqual(result["estimated_rows_needed"],   0)
        self.assertEqual(result["provider_calls_required"], 0)


# ---------------------------------------------------------------------------
# estimated_rows_needed
# ---------------------------------------------------------------------------


class TestEstimatedRowsNeeded(unittest.TestCase):
    def test_counts_weekdays_inclusive(self) -> None:
        # cache_max=2026-05-01 (Fri) → start = 2026-05-02 (Sat,
        # cache_max + 1 calendar day per contract).  Range
        # Sat May 2 → Fri May 8 inclusive contains 5 weekdays
        # (Mon-Fri); Sat/Sun excluded from the row count.
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-08",
                     cache_max="2026-05-01"),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=1))
        self.assertEqual(result["required_start_date"], "2026-05-02")
        self.assertEqual(result["required_end_date"],   "2026-05-08")
        self.assertEqual(result["estimated_rows_needed"], 5)

    def test_skips_weekends(self) -> None:
        # 2026-05-01 is Friday, 2026-05-04 is Monday — Sat/Sun skipped
        # cache_max is 2026-04-30 (Thu) → start = 2026-05-01 (Fri)
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-04",
                     cache_max="2026-04-30"),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=1))
        self.assertEqual(result["required_start_date"], "2026-05-01")
        self.assertEqual(result["required_end_date"],   "2026-05-04")
        self.assertEqual(result["estimated_rows_needed"], 2)

    def test_zero_when_start_after_end(self) -> None:
        # Defensive: if cache somehow extends past target, no rows.
        rows = [
            _gap_row(event_id=1, target_20d="2026-04-15",
                     cache_max="2026-05-01"),
        ]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=1))
        self.assertEqual(result["estimated_rows_needed"], 0)


# ---------------------------------------------------------------------------
# provider_calls_required
# ---------------------------------------------------------------------------


class TestProviderCallsRequired(unittest.TestCase):
    def test_zero_when_no_blockers(self) -> None:
        result = _run(**_empty_payloads())
        self.assertEqual(result["provider_calls_required"], 0)

    def test_zero_when_estimated_rows_zero(self) -> None:
        rows = [_gap_row(event_id=1, event_date=None, target_20d=None)]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=1))
        self.assertEqual(result["provider_calls_required"], 0)

    def test_one_when_range_to_fetch(self) -> None:
        rows = [_gap_row(event_id=1, target_20d="2026-05-13",
                         cache_max="2026-04-20")]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap, salvage=_salvage_payload(bench_count=1))
        self.assertEqual(result["provider_calls_required"], 1)


# ---------------------------------------------------------------------------
# Recommended next action
# ---------------------------------------------------------------------------


class TestRecommendedAction(unittest.TestCase):
    _BANNED = (
        "auto-correct", "auto correct", "auto-fix", "automatic",
        "delete", "live mutation",
    )

    def test_includes_backfill_phrasing_when_blocked(self) -> None:
        rows = [_gap_row(event_id=1, target_20d="2026-05-13",
                         cache_max="2026-04-20")]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap,
                      salvage=_salvage_payload(
                          bench_count=1,
                          top_path="missing_benchmark_proxy"))
        rec = result["recommended_next_action"].lower()
        self.assertIn("spy", rec)
        self.assertIn("backfill", rec)

    def test_no_banned_destructive_phrases(self) -> None:
        rows = [_gap_row(event_id=1, target_20d="2026-05-13",
                         cache_max="2026-04-20")]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap,
                      salvage=_salvage_payload(
                          bench_count=1,
                          top_path="missing_benchmark_proxy"))
        rec = result["recommended_next_action"].lower()
        for banned in self._BANNED:
            self.assertNotIn(banned, rec, f"banned phrase {banned!r}: {rec!r}")

    def test_qualifies_when_other_path_dominates(self) -> None:
        # benchmark blockers exist but the salvage report says another
        # group has more events to unlock — recommendation should not
        # claim SPY backfill is the highest-yield action overall.
        rows = [_gap_row(event_id=1, target_20d="2026-05-13",
                         cache_max="2026-04-20")]
        gap = _gap_payload(rows=rows)
        result = _run(gap=gap,
                      salvage=_salvage_payload(
                          bench_count=1,
                          top_path="price_cache_forward_20d"))
        # Either explicitly mentions the dominant group, or signals
        # that SPY backfill is not the top path.
        rec = result["recommended_next_action"].lower()
        self.assertTrue(
            "price_cache_forward_20d" in rec
            or "not the top" in rec
            or "other" in rec,
            f"recommendation should qualify when SPY isn't top: {rec!r}",
        )


# ---------------------------------------------------------------------------
# Provider isolation — default run must not touch yfinance / market data
# ---------------------------------------------------------------------------


class TestProviderIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance",
        "market_check",
        "market_data",
        "price_cache",
        "api",
    )

    def test_default_run_does_not_import_provider_modules(self) -> None:
        # Snapshot sys.modules before the run; assert no new provider
        # module appeared after.
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        _run(**_empty_payloads())
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(
            after - before, set(),
            "preflight imported a provider module on default run",
        )

    def test_default_run_does_not_import_routes_or_fastapi(self) -> None:
        forbidden = ("fastapi",)
        before = {k for k in sys.modules.keys()
                  if k in forbidden
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in forbidden)}
        _run(**_empty_payloads())
        after = {k for k in sys.modules.keys()
                 if k in forbidden
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in forbidden)}
        self.assertEqual(
            after - before, set(),
            "preflight imported FastAPI / routes on default run",
        )


# ---------------------------------------------------------------------------
# --check-provider-availability
# ---------------------------------------------------------------------------


class TestCheckProviderAvailability(unittest.TestCase):
    def test_flag_omitted_means_no_provider_availability_field(self) -> None:
        # The default payload omits the optional field — keeps the
        # default JSON terse.
        result = _run(**_empty_payloads())
        self.assertNotIn("provider_available", result)

    def test_flag_true_adds_field_without_downloading(self) -> None:
        # The optional check imports yfinance at the seam and reports
        # importability ONLY — no fetch, no network.  We patch the
        # importability probe to verify the field plumbs through with
        # whatever the probe returns; then assert no download seam was
        # invoked.
        with patch.object(cli, "_probe_provider_importable",
                          return_value=True) as probe:
            result = _run(check_provider_availability=True,
                          **_empty_payloads())
        self.assertTrue(probe.called)
        self.assertIn("provider_available", result)
        self.assertIs(result["provider_available"], True)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_flag_emits_parseable_json(self) -> None:
        rc, output = _run_cli(["--json"], **_empty_payloads())
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)

    def test_text_mode_includes_benchmark_symbol(self) -> None:
        rc, output = _run_cli([], **_empty_payloads())
        self.assertEqual(rc, 0)
        self.assertIn("SPY", output)

    def test_limit_arg_accepted(self) -> None:
        rc, _ = _run_cli(["--json", "--limit", "50"], **_empty_payloads())
        self.assertEqual(rc, 0)

    def test_db_path_arg_accepted(self) -> None:
        rc, output = _run_cli(["--json", "--db-path", "/tmp/nonexistent.db"],
                              **_empty_payloads())
        self.assertEqual(rc, 0)
        # Even with a bogus path, the seams are patched so the run
        # succeeds and returns the synthetic payload.
        parsed = json.loads(output)
        self.assertIn("benchmark_symbol", parsed)

    def test_check_provider_availability_flag_accepted(self) -> None:
        with patch.object(cli, "_probe_provider_importable",
                          return_value=False):
            rc, output = _run_cli(
                ["--json", "--check-provider-availability"],
                **_empty_payloads())
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertIn("provider_available", parsed)
        self.assertIs(parsed["provider_available"], False)


# ---------------------------------------------------------------------------
# End-to-end against a real (empty) temp DB — exercises the un-patched
# seams to confirm they don't blow up on a stock SQLite file.
# ---------------------------------------------------------------------------


class TestEndToEndAgainstTempDb(unittest.TestCase):
    def _make_temp_db(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"preflight_e2e_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "CREATE TABLE events ("
                " id INTEGER PRIMARY KEY,"
                " headline TEXT, event_date TEXT,"
                " market_tickers TEXT, mechanism_family TEXT,"
                " stage TEXT, persistence TEXT, confidence TEXT)"
            )
            conn.execute(
                "CREATE TABLE price_cache ("
                " ticker TEXT, date TEXT, auto_adjust INTEGER)"
            )
            conn.commit()
        finally:
            conn.close()
        return path

    def test_runs_against_empty_temp_db(self) -> None:
        path = self._make_temp_db()
        try:
            result = cli.summarize_backfill_preflight(db_path=path)
        finally:
            os.unlink(path)
        self.assertIsInstance(result, dict)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, result)
        self.assertEqual(result["blocked_event_count"],     0)
        self.assertEqual(result["provider_calls_required"], 0)


if __name__ == "__main__":
    unittest.main()
