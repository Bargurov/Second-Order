"""Tests for ``scripts/benchmark_blocker_maturity_report.py``.

Pin the read-only contract:

* The maturity report consumes two upstream reports through
  patchable seams: ``_run_preflight`` (for ``current_cache_max_date``)
  and ``_run_benchmark_gap_report`` (for per-row blocker target
  dates).
* Three maturity buckets, evaluated against ``as_of_date``:

    - ``actionable_now``                    target_date <= as_of
    - ``too_early_future_horizon``          target_date >  as_of
    - ``already_covered_or_inconsistent``   target_date null /
                                            unparseable / already
                                            covered by cache

* ``actionable_required_start_date`` /
  ``actionable_required_end_date`` are computed from the
  actionable bucket only:

    - end = max(target_date) over actionable rows
    - start = ``cache_max + 1 calendar day`` if cache exists, else
              min(target_date) over actionable rows

  Both ``None`` if the actionable bucket is empty.

* ``latest_available_market_date`` defaults to today's local date;
  ``--as-of-date YYYY-MM-DD`` overrides explicitly.
* Default run does NOT import yfinance / market_check / market_data /
  price_cache / api / routes.* / fastapi.
* Conservative language: recommendation may use "candidate",
  "estimated", "appears", "may", "actionable now"; never
  "delete", "auto-correct", "fix the", "guaranteed", "must",
  "refresh prices", "live mutation".
* Output dict carries the brief-mandated keyset:
  ``total_blocked``, ``actionable_now_count``,
  ``too_early_future_horizon_count``,
  ``latest_available_market_date``,
  ``actionable_required_start_date``,
  ``actionable_required_end_date``, ``examples``,
  ``recommended_next_action``.
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
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import benchmark_blocker_maturity_report as cli  # noqa: E402


_REQUIRED_KEYS = (
    "total_blocked",
    "actionable_now_count",
    "too_early_future_horizon_count",
    "latest_available_market_date",
    "actionable_required_start_date",
    "actionable_required_end_date",
    "examples",
    "recommended_next_action",
)


_BUCKET_KEYS = (
    "actionable_now",
    "too_early_future_horizon",
    "already_covered_or_inconsistent",
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
    *, total_events: int = 0, rows: list[dict] | None = None,
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


def _preflight_payload(
    *,
    blocked: int = 0,
    current_cache_max_date: str | None = None,
    required_start: str | None = None,
    required_end: str | None = None,
) -> dict:
    return {
        "benchmark_symbol":        "SPY",
        "blocked_event_count":     blocked,
        "required_start_date":     required_start,
        "required_end_date":       required_end,
        "current_cache_max_date":  current_cache_max_date,
        "estimated_rows_needed":   0,
        "provider_calls_required": 0,
        "recommended_next_action": "synthetic",
    }


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _patch_seams(*, preflight: dict, gap: dict):
    return (
        patch.object(cli, "_run_preflight", return_value=preflight),
        patch.object(cli, "_run_benchmark_gap_report", return_value=gap),
    )


def _run(*, preflight: dict, gap: dict, **kwargs) -> dict:
    p1, p2 = _patch_seams(preflight=preflight, gap=gap)
    with p1, p2:
        return cli.summarize_blocker_maturity(**kwargs)


def _run_cli(argv: list[str], *, preflight: dict, gap: dict) -> tuple[int, str]:
    out = StringIO()
    p1, p2 = _patch_seams(preflight=preflight, gap=gap)
    with p1, p2:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


def _empty_payloads() -> dict:
    return {"preflight": _preflight_payload(), "gap": _gap_payload()}


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(unittest.TestCase):
    def test_returns_dict_with_required_keys(self) -> None:
        result = _run(**_empty_payloads(), as_of_date="2026-05-09")
        self.assertIsInstance(result, dict)
        for key in _REQUIRED_KEYS:
            self.assertIn(key, result, f"missing key: {key}")

    def test_examples_is_list(self) -> None:
        result = _run(**_empty_payloads(), as_of_date="2026-05-09")
        self.assertIsInstance(result["examples"], list)

    def test_recommended_next_action_is_non_empty_string(self) -> None:
        result = _run(**_empty_payloads(), as_of_date="2026-05-09")
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])


# ---------------------------------------------------------------------------
# Empty archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(unittest.TestCase):
    def test_zero_blockers_zeros_every_count(self) -> None:
        result = _run(**_empty_payloads(), as_of_date="2026-05-09")
        self.assertEqual(result["total_blocked"],                  0)
        self.assertEqual(result["actionable_now_count"],            0)
        self.assertEqual(result["too_early_future_horizon_count"],  0)
        self.assertEqual(result["examples"],                        [])
        self.assertIsNone(result["actionable_required_start_date"])
        self.assertIsNone(result["actionable_required_end_date"])


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


class TestBucketing(unittest.TestCase):
    def test_target_at_or_before_as_of_is_actionable_now(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-01"),  # past
            _gap_row(event_id=2, target_20d="2026-05-09"),  # equal
        ]
        result = _run(
            preflight=_preflight_payload(current_cache_max_date="2026-04-30"),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["total_blocked"],                  2)
        self.assertEqual(result["actionable_now_count"],            2)
        self.assertEqual(result["too_early_future_horizon_count"],  0)

    def test_target_after_as_of_is_too_early(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-10"),
            _gap_row(event_id=2, target_20d="2026-06-05"),
        ]
        result = _run(
            preflight=_preflight_payload(current_cache_max_date="2026-05-07"),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["actionable_now_count"],            0)
        self.assertEqual(result["too_early_future_horizon_count"],  2)

    def test_target_unparseable_goes_to_inconsistent_bucket(self) -> None:
        # Blocker with no parseable target_20d (event_date=None case)
        # belongs to neither maturity bucket — it cannot be classified
        # by horizon, so it lands in the inconsistent bucket.
        rows = [
            _gap_row(event_id=1, event_date=None, target_20d=None),
        ]
        result = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["total_blocked"],                  1)
        self.assertEqual(result["actionable_now_count"],            0)
        self.assertEqual(result["too_early_future_horizon_count"],  0)
        # Total = actionable + too_early + inconsistent must conserve
        self.assertEqual(
            result["actionable_now_count"]
            + result["too_early_future_horizon_count"]
            + sum(1 for e in result["examples"]
                  if e["maturity_bucket"]
                  == "already_covered_or_inconsistent"),
            1,
        )

    def test_mixed_archive_partitions_correctly(self) -> None:
        rows = (
            [_gap_row(event_id=i, target_20d="2026-05-08") for i in (1, 2, 3)]
            + [_gap_row(event_id=i, target_20d="2026-05-15") for i in (4, 5)]
            + [_gap_row(event_id=6, event_date=None, target_20d=None)]
        )
        result = _run(
            preflight=_preflight_payload(current_cache_max_date="2026-05-07"),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["total_blocked"],                  6)
        self.assertEqual(result["actionable_now_count"],            3)
        self.assertEqual(result["too_early_future_horizon_count"],  2)


# ---------------------------------------------------------------------------
# Actionable date range
# ---------------------------------------------------------------------------


class TestActionableDateRange(unittest.TestCase):
    def test_actionable_end_is_max_target_in_bucket(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-01"),
            _gap_row(event_id=2, target_20d="2026-05-08"),
            _gap_row(event_id=3, target_20d="2026-05-04"),
            # too_early — must NOT influence actionable end
            _gap_row(event_id=4, target_20d="2026-06-05"),
        ]
        result = _run(
            preflight=_preflight_payload(current_cache_max_date="2026-04-25"),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["actionable_required_end_date"], "2026-05-08")

    def test_actionable_start_is_cache_max_plus_one_day(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-01"),
            _gap_row(event_id=2, target_20d="2026-05-08"),
        ]
        result = _run(
            preflight=_preflight_payload(current_cache_max_date="2026-04-25"),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["actionable_required_start_date"],
                         "2026-04-26")

    def test_actionable_start_is_min_target_when_cache_empty(self) -> None:
        rows = [
            _gap_row(event_id=1, target_20d="2026-05-01"),
            _gap_row(event_id=2, target_20d="2026-05-08"),
        ]
        result = _run(
            preflight=_preflight_payload(current_cache_max_date=None),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["actionable_required_start_date"],
                         "2026-05-01")

    def test_no_actionable_returns_none_range(self) -> None:
        # Every blocker is too_early — no actionable date range.
        rows = [
            _gap_row(event_id=1, target_20d="2026-06-01"),
            _gap_row(event_id=2, target_20d="2026-06-05"),
        ]
        result = _run(
            preflight=_preflight_payload(current_cache_max_date="2026-05-07"),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(result["actionable_now_count"],            0)
        self.assertEqual(result["too_early_future_horizon_count"],  2)
        self.assertIsNone(result["actionable_required_start_date"])
        self.assertIsNone(result["actionable_required_end_date"])


# ---------------------------------------------------------------------------
# As-of date
# ---------------------------------------------------------------------------


class TestAsOfDate(unittest.TestCase):
    def test_explicit_as_of_changes_bucket_assignment(self) -> None:
        # 2026-05-08 target — actionable on/after that date, too_early
        # before.  Verify both directions.
        rows = [_gap_row(event_id=1, target_20d="2026-05-08")]
        before = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-01",
        )
        on = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-08",
        )
        self.assertEqual(before["too_early_future_horizon_count"], 1)
        self.assertEqual(before["actionable_now_count"],            0)
        self.assertEqual(on["actionable_now_count"],                1)
        self.assertEqual(on["too_early_future_horizon_count"],      0)

    def test_default_uses_today_local_date(self) -> None:
        # When ``as_of_date`` is not passed, the report fills in
        # today's local date.  The format is ISO YYYY-MM-DD.
        from datetime import date
        result = _run(**_empty_payloads())
        self.assertEqual(
            result["latest_available_market_date"],
            date.today().isoformat(),
        )

    def test_explicit_as_of_surfaced_in_payload(self) -> None:
        result = _run(**_empty_payloads(), as_of_date="2026-04-15")
        self.assertEqual(result["latest_available_market_date"], "2026-04-15")

    def test_unparseable_as_of_falls_back_to_today(self) -> None:
        # Defensive: a malformed ``as_of_date`` should not crash the
        # report; fall back to today and surface a warning-class
        # behavior in the recommendation.  The exact recommendation
        # is not pinned here — only that the report still produces a
        # well-formed payload with a parseable as_of.
        from datetime import date
        result = _run(**_empty_payloads(), as_of_date="not-a-date")
        self.assertEqual(
            result["latest_available_market_date"],
            date.today().isoformat(),
        )


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------


class TestExamples(unittest.TestCase):
    def test_examples_sorted_by_event_id_ascending(self) -> None:
        rows = [_gap_row(event_id=eid, target_20d="2026-05-08")
                for eid in (5, 1, 9, 3)]
        result = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        ids = [e["event_id"] for e in result["examples"]]
        self.assertEqual(ids, sorted(ids))

    def test_each_example_has_maturity_bucket_field(self) -> None:
        rows = [_gap_row(event_id=1, target_20d="2026-05-08")]
        result = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        self.assertEqual(len(result["examples"]), 1)
        self.assertIn("maturity_bucket", result["examples"][0])
        self.assertIn(result["examples"][0]["maturity_bucket"],
                      _BUCKET_KEYS)

    def test_limit_caps_examples_only_aggregates_unaffected(self) -> None:
        rows = [_gap_row(event_id=i, target_20d="2026-05-08")
                for i in range(1, 11)]
        result = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
            limit=3,
        )
        self.assertEqual(len(result["examples"]),     3)
        self.assertEqual(result["total_blocked"],     10)
        self.assertEqual(result["actionable_now_count"], 10)

    def test_negative_limit_clamps_to_zero(self) -> None:
        rows = [_gap_row(event_id=1, target_20d="2026-05-08")]
        result = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
            limit=-5,
        )
        self.assertEqual(result["examples"], [])
        self.assertEqual(result["total_blocked"], 1)


# ---------------------------------------------------------------------------
# Recommended action — conservative language
# ---------------------------------------------------------------------------


class TestRecommendedAction(unittest.TestCase):
    _BANNED = (
        "delete", "auto-correct", "auto correct", "auto-fix",
        "automatic", "fix the", "correct the", "replace the",
        "guaranteed", "must fetch", "must download",
        "refresh prices", "live mutation",
    )

    def _scenarios(self) -> list[dict]:
        empty = _empty_payloads() | {"as_of_date": "2026-05-09"}
        # Mixed: some actionable, some too_early
        sc_mixed_rows = (
            [_gap_row(event_id=i, target_20d="2026-05-08") for i in (1, 2)]
            + [_gap_row(event_id=i, target_20d="2026-06-05") for i in (3, 4)]
        )
        sc_mixed = {
            "preflight": _preflight_payload(
                current_cache_max_date="2026-05-07"),
            "gap": _gap_payload(rows=sc_mixed_rows),
            "as_of_date": "2026-05-09",
        }
        # All too_early
        sc_future_rows = [
            _gap_row(event_id=1, target_20d="2026-06-01"),
            _gap_row(event_id=2, target_20d="2026-06-05"),
        ]
        sc_future = {
            "preflight": _preflight_payload(
                current_cache_max_date="2026-05-07"),
            "gap": _gap_payload(rows=sc_future_rows),
            "as_of_date": "2026-05-09",
        }
        return [empty, sc_mixed, sc_future]

    def test_conservative_phrasing_in_every_scenario(self) -> None:
        for scenario in self._scenarios():
            result = _run(**scenario)
            rec = result["recommended_next_action"].lower()
            for banned in self._BANNED:
                self.assertNotIn(
                    banned, rec,
                    f"banned phrase {banned!r} in: {rec!r}",
                )

    def test_actionable_scenario_mentions_actionable(self) -> None:
        rows = [_gap_row(event_id=1, target_20d="2026-05-08")]
        result = _run(
            preflight=_preflight_payload(current_cache_max_date="2026-05-07"),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        rec = result["recommended_next_action"].lower()
        self.assertIn("actionable", rec)

    def test_all_future_scenario_mentions_wait_or_too_early(self) -> None:
        rows = [_gap_row(event_id=1, target_20d="2026-06-01")]
        result = _run(
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
            as_of_date="2026-05-09",
        )
        rec = result["recommended_next_action"].lower()
        self.assertTrue(
            "wait" in rec or "too early" in rec or "future" in rec
            or "mature" in rec,
            f"missing horizon-wait phrasing: {rec!r}",
        )


# ---------------------------------------------------------------------------
# Provider isolation — default run does not import yfinance / FastAPI
# ---------------------------------------------------------------------------


class TestProviderIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance",
        "market_check",
        "market_data",
        "price_cache",
        "api",
        "fastapi",
    )

    def test_default_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        _run(**_empty_payloads(), as_of_date="2026-05-09")
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# Seam patchability
# ---------------------------------------------------------------------------


class TestSeamPatchability(unittest.TestCase):
    def test_run_preflight_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_preflight")))

    def test_run_benchmark_gap_report_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_benchmark_gap_report")))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_emits_parseable_json_with_required_keys(self) -> None:
        rc, output = _run_cli(["--json"], **_empty_payloads())
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)

    def test_text_mode_includes_actionable_word(self) -> None:
        rc, output = _run_cli([], **_empty_payloads())
        self.assertEqual(rc, 0)
        self.assertIn("actionable", output.lower())

    def test_limit_arg_caps_examples(self) -> None:
        rows = [_gap_row(event_id=i, target_20d="2026-05-08")
                for i in range(1, 8)]
        rc, output = _run_cli(
            ["--json", "--limit", "2", "--as-of-date", "2026-05-09"],
            preflight=_preflight_payload(),
            gap=_gap_payload(rows=rows),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(len(parsed["examples"]), 2)
        self.assertEqual(parsed["total_blocked"], 7)

    def test_as_of_date_arg_overrides_default(self) -> None:
        rc, output = _run_cli(
            ["--json", "--as-of-date", "2026-04-01"],
            **_empty_payloads(),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["latest_available_market_date"],
                         "2026-04-01")

    def test_db_path_arg_accepted(self) -> None:
        rc, _ = _run_cli(
            ["--json", "--db-path", "/tmp/nonexistent.db"],
            **_empty_payloads(),
        )
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# End-to-end against an empty temp DB — exercises the un-patched seams.
# ---------------------------------------------------------------------------


class TestEndToEndAgainstTempDb(unittest.TestCase):
    def _make_temp_db(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"maturity_e2e_{uuid.uuid4().hex}.db",
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

    def test_runs_against_empty_temp_db_without_error(self) -> None:
        path = self._make_temp_db()
        try:
            result = cli.summarize_blocker_maturity(db_path=path)
        finally:
            os.unlink(path)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, result)
        self.assertEqual(result["total_blocked"], 0)


if __name__ == "__main__":
    unittest.main()
