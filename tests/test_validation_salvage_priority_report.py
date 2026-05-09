"""Tests for ``scripts/validation_salvage_priority_report.py``.

Pin the contract:

* The salvage priority report consumes five upstream reports through
  patchable seams so unit tests can drive it with synthetic fixtures:
  ``_run_clean_cohort_report``, ``_run_blocker_report``,
  ``_run_forward_cache_gap_export``, ``_run_missing_tickers_report``,
  ``_run_estimation_gap_report``.
* Five candidate groups are surfaced, in this stable order::

      price_cache_forward_20d
      estimation_window_gap
      missing_benchmark_proxy
      missing_market_tickers
      contaminated_fully_ready_manual_review

* ``top_salvage_path`` is the group_key with the largest
  ``estimated_events_unlocked``; ties resolve via the stable order
  above (mechanical price-cache backfill preferred over human review).
* ``manual_review_required`` is ``True`` iff
  ``contaminated_fully_ready_manual_review`` carries any events.
* Conservative language: recommended_next_action mentions
  "candidate", "estimated", or "manual review required"; never
  "delete", "auto-correct", "assign", "replace", "fix the".
* The report NEVER assigns or proposes replacement tickers.
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
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import validation_salvage_priority_report as cli  # noqa: E402


_TOP_KEYS = (
    "ok",
    "current_clean_fully_ready_count",
    "target_clean_count",
    "top_salvage_path",
    "candidate_groups",
    "estimated_events_unlocked",
    "manual_review_required",
    "recommended_next_action",
)


_GROUP_KEYS = (
    "price_cache_forward_20d",
    "estimation_window_gap",
    "missing_benchmark_proxy",
    "missing_market_tickers",
    "contaminated_fully_ready_manual_review",
)


_GROUP_BUCKET_KEYS = (
    "blocker_count",
    "estimated_events_unlocked",
    "candidates",
)


# ---------------------------------------------------------------------------
# Synthetic upstream payload helpers
# ---------------------------------------------------------------------------


def _clean_cohort_payload(
    *, total_events: int = 0, fully_ready: int = 0,
    contaminated: int = 0, clean: int = 0,
    excluded_examples: list[dict] | None = None,
) -> dict:
    return {
        "ok":                              True,
        "total_events":                    total_events,
        "fully_ready_count":               fully_ready,
        "contaminated_fully_ready_count":  contaminated,
        "clean_fully_ready_count":         clean,
        "clean_fully_ready_event_ids":     [],
        "excluded_fully_ready_examples":   excluded_examples or [],
        "next_salvage_candidates":         {},
        "recommended_next_action":         "synthetic",
    }


def _blocker_payload(*, missing_benchmark: list[dict] | None = None) -> dict:
    """Synthetic blocker-report payload — only the missing_benchmark
    bucket matters for the salvage report (the others are sourced
    from their own dedicated reports)."""
    keys = (
        "missing_market_tickers",
        "missing_forward_cache_1d",
        "missing_forward_cache_5d",
        "missing_forward_cache_20d",
        "missing_benchmark_proxy",
        "insufficient_estimation_window",
    )
    blockers: dict[str, dict] = {
        k: {"count": 0, "examples": []} for k in keys
    }
    if missing_benchmark:
        blockers["missing_benchmark_proxy"] = {
            "count":    len(missing_benchmark),
            "examples": missing_benchmark,
        }
    return {
        "total_events":           0,
        "events_fully_ready":     0,
        "events_not_fully_ready": 0,
        "blockers":               blockers,
        "recommended_next_action": "synthetic",
    }


def _forward_cache_gap_payload(rows: list[dict] | None = None) -> dict:
    rows = rows or []
    return {
        "ok":     True,
        "count":  len(rows),
        "fields": ["event_id", "event_date", "primary_ticker", "horizon",
                   "blocker_reason", "target_date", "benchmark"],
        "rows":   rows,
    }


def _missing_tickers_payload(events: list[dict] | None = None) -> dict:
    events = events or []
    return {
        "total_events":                  0,
        "events_missing_market_tickers": len(events),
        "events":                        events,
        "recommended_next_action":       "synthetic",
    }


def _estimation_gap_payload(events: list[dict] | None = None) -> dict:
    events = events or []
    return {
        "total_events":      0,
        "events_evaluable":  len(events),
        "events_with_gap":   len(events),
        "required_days":     60,
        "events":            events,
        "recommended_next_action": "synthetic",
    }


def _bench_blocker_entry(
    *, event_id: int, event_date: str = "2026-04-15",
    primary_ticker: str = "AAPL",
) -> dict:
    return {
        "event_id":       event_id,
        "event_date":     event_date,
        "primary_ticker": primary_ticker,
    }


def _forward_gap_row(
    *, event_id: int, horizon: int,
    event_date: str = "2026-04-15",
    primary_ticker: str = "AAPL",
    target_date: str = "2026-05-13",
    blocker_reason: str = "ticker_cache_missing",
) -> dict:
    return {
        "event_id":       event_id,
        "event_date":     event_date,
        "primary_ticker": primary_ticker,
        "horizon":        horizon,
        "target_date":    target_date,
        "blocker_reason": blocker_reason,
        "benchmark":      "SPY",
    }


def _missing_ticker_event(
    *, event_id: int, event_date: str = "2026-04-15",
    headline: str = "Synthetic headline",
) -> dict:
    return {
        "event_id":   event_id,
        "event_date": event_date,
        "headline":   headline,
        "stage":      "realized",
        "persistence":"medium",
        "confidence": "low",
        "suggested_next_action": "manual_review_required",
    }


def _estimation_event(
    *, event_id: int, event_date: str = "2026-04-15",
    primary_ticker: str = "AAPL", missing_days: int = 60,
) -> dict:
    return {
        "event_id":                  event_id,
        "event_date":                event_date,
        "primary_ticker":            primary_ticker,
        "missing_days":              missing_days,
        "pre_event_cached_days":     60 - missing_days,
        "earliest_cache_date":       None,
        "latest_pre_event_cache_date": None,
        "required_days":             60,
    }


def _excluded_example(
    *, event_id: int, flags: list[str],
    event_date: str = "2026-04-15",
    primary_ticker: str = "DRIV",
    headline: str = "synthetic off-topic",
    mechanism_family: str | None = "none",
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "flags":            flags,
    }


# ---------------------------------------------------------------------------
# Patch / run helpers
# ---------------------------------------------------------------------------


def _patch_all(*, clean_cohort: dict, blockers: dict,
               forward_gap: dict, missing_tickers: dict,
               estimation_gap: dict):
    return (
        patch.object(cli, "_run_clean_cohort_report",
                     return_value=clean_cohort),
        patch.object(cli, "_run_blocker_report",
                     return_value=blockers),
        patch.object(cli, "_run_forward_cache_gap_export",
                     return_value=forward_gap),
        patch.object(cli, "_run_missing_tickers_report",
                     return_value=missing_tickers),
        patch.object(cli, "_run_estimation_gap_report",
                     return_value=estimation_gap),
    )


def _run_with(**payloads):
    p1, p2, p3, p4, p5 = _patch_all(**payloads)
    with p1, p2, p3, p4, p5:
        kwargs = payloads.pop("kwargs", {})
        return cli.summarize_salvage_priority(**kwargs)


def _run_with_kwargs(**kwargs):
    """Convenience: split kwargs from synthetic payloads."""
    payloads = {
        k: kwargs.pop(k) for k in (
            "clean_cohort", "blockers", "forward_gap",
            "missing_tickers", "estimation_gap",
        )
    }
    p1, p2, p3, p4, p5 = _patch_all(**payloads)
    with p1, p2, p3, p4, p5:
        return cli.summarize_salvage_priority(**kwargs)


def _run_cli(argv: list[str], **payloads) -> tuple[int, str]:
    out = StringIO()
    p1, p2, p3, p4, p5 = _patch_all(**payloads)
    with p1, p2, p3, p4, p5:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


def _empty_payloads() -> dict:
    return {
        "clean_cohort":    _clean_cohort_payload(),
        "blockers":        _blocker_payload(),
        "forward_gap":     _forward_cache_gap_payload(),
        "missing_tickers": _missing_tickers_payload(),
        "estimation_gap":  _estimation_gap_payload(),
    }


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(unittest.TestCase):
    def test_returns_dict_with_top_keys(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_candidate_groups_dict_has_every_group(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertIsInstance(result["candidate_groups"], dict)
        for key in _GROUP_KEYS:
            self.assertIn(key, result["candidate_groups"])
            bucket = result["candidate_groups"][key]
            for sub in _GROUP_BUCKET_KEYS:
                self.assertIn(sub, bucket)

    def test_estimated_events_unlocked_dict_has_every_group(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertIsInstance(result["estimated_events_unlocked"], dict)
        for key in _GROUP_KEYS:
            self.assertIn(key, result["estimated_events_unlocked"])
            self.assertIsInstance(
                result["estimated_events_unlocked"][key], int)

    def test_ok_is_true_on_clean_run(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertIs(result["ok"], True)


# ---------------------------------------------------------------------------
# Empty archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(unittest.TestCase):
    def test_zero_events_zeros_every_count(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertEqual(result["current_clean_fully_ready_count"], 0)
        for key in _GROUP_KEYS:
            self.assertEqual(
                result["candidate_groups"][key]["blocker_count"], 0)
            self.assertEqual(
                result["candidate_groups"][key]["estimated_events_unlocked"], 0)
            self.assertEqual(
                result["candidate_groups"][key]["candidates"], [])
        self.assertIsNone(result["top_salvage_path"])
        self.assertIs(result["manual_review_required"], False)


# ---------------------------------------------------------------------------
# Group counts wire from upstream payloads
# ---------------------------------------------------------------------------


class TestGroupCountsWiring(unittest.TestCase):
    def test_forward_cache_gap_filtered_to_horizon_20(self) -> None:
        # 5 horizon-20 rows + 3 horizon-1 + 2 horizon-5; only the
        # 5 horizon-20 rows should land in price_cache_forward_20d.
        rows = (
            [_forward_gap_row(event_id=i, horizon=20) for i in range(1, 6)]
            + [_forward_gap_row(event_id=i, horizon=1) for i in range(10, 13)]
            + [_forward_gap_row(event_id=i, horizon=5) for i in range(20, 22)]
        )
        payloads = _empty_payloads()
        payloads["forward_gap"] = _forward_cache_gap_payload(rows)
        result = _run_with_kwargs(**payloads)
        self.assertEqual(
            result["candidate_groups"]["price_cache_forward_20d"]["blocker_count"],
            5,
        )

    def test_estimation_gap_count_wires_through(self) -> None:
        events = [_estimation_event(event_id=i) for i in (1, 2, 3, 4, 5)]
        payloads = _empty_payloads()
        payloads["estimation_gap"] = _estimation_gap_payload(events)
        result = _run_with_kwargs(**payloads)
        self.assertEqual(
            result["candidate_groups"]["estimation_window_gap"]["blocker_count"],
            5,
        )

    def test_missing_benchmark_count_from_blocker_report(self) -> None:
        bench = [_bench_blocker_entry(event_id=i) for i in (1, 2, 3)]
        payloads = _empty_payloads()
        payloads["blockers"] = _blocker_payload(missing_benchmark=bench)
        result = _run_with_kwargs(**payloads)
        self.assertEqual(
            result["candidate_groups"]["missing_benchmark_proxy"]["blocker_count"],
            3,
        )

    def test_missing_market_tickers_count_wires_through(self) -> None:
        evs = [_missing_ticker_event(event_id=i) for i in range(1, 8)]
        payloads = _empty_payloads()
        payloads["missing_tickers"] = _missing_tickers_payload(evs)
        result = _run_with_kwargs(**payloads)
        self.assertEqual(
            result["candidate_groups"]["missing_market_tickers"]["blocker_count"],
            7,
        )

    def test_contaminated_count_from_clean_cohort_report(self) -> None:
        excluded = [
            _excluded_example(event_id=i, flags=["driv_lit_off_topic"])
            for i in (1, 2)
        ]
        payloads = _empty_payloads()
        payloads["clean_cohort"] = _clean_cohort_payload(
            total_events=2, fully_ready=2, contaminated=2, clean=0,
            excluded_examples=excluded,
        )
        result = _run_with_kwargs(**payloads)
        self.assertEqual(
            result["candidate_groups"]
                  ["contaminated_fully_ready_manual_review"]["blocker_count"],
            2,
        )

    def test_current_clean_count_wires_through(self) -> None:
        payloads = _empty_payloads()
        payloads["clean_cohort"] = _clean_cohort_payload(
            total_events=10, fully_ready=10, contaminated=2, clean=8,
        )
        result = _run_with_kwargs(**payloads)
        self.assertEqual(result["current_clean_fully_ready_count"], 8)


# ---------------------------------------------------------------------------
# top_salvage_path selection
# ---------------------------------------------------------------------------


class TestTopSalvagePath(unittest.TestCase):
    def test_picks_group_with_largest_count(self) -> None:
        payloads = _empty_payloads()
        # forward_20d=2, estimation=10, benchmark=5
        payloads["forward_gap"] = _forward_cache_gap_payload(
            [_forward_gap_row(event_id=i, horizon=20) for i in (1, 2)],
        )
        payloads["estimation_gap"] = _estimation_gap_payload(
            [_estimation_event(event_id=i) for i in range(20, 30)],
        )
        payloads["blockers"] = _blocker_payload(
            missing_benchmark=[_bench_blocker_entry(event_id=i)
                               for i in range(40, 45)],
        )
        result = _run_with_kwargs(**payloads)
        self.assertEqual(result["top_salvage_path"],
                         "estimation_window_gap")

    def test_tie_resolved_in_stable_order_prefers_mechanical(self) -> None:
        # Tie between price_cache_forward_20d and missing_market_tickers
        # at count=4 — stable order says forward_20d wins.
        payloads = _empty_payloads()
        payloads["forward_gap"] = _forward_cache_gap_payload(
            [_forward_gap_row(event_id=i, horizon=20) for i in (1, 2, 3, 4)],
        )
        payloads["missing_tickers"] = _missing_tickers_payload(
            [_missing_ticker_event(event_id=i) for i in (10, 11, 12, 13)],
        )
        result = _run_with_kwargs(**payloads)
        self.assertEqual(result["top_salvage_path"],
                         "price_cache_forward_20d")

    def test_top_salvage_is_none_when_all_groups_empty(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertIsNone(result["top_salvage_path"])

    def test_estimated_events_unlocked_matches_per_group_count(self) -> None:
        payloads = _empty_payloads()
        payloads["estimation_gap"] = _estimation_gap_payload(
            [_estimation_event(event_id=i) for i in range(1, 6)],
        )
        result = _run_with_kwargs(**payloads)
        self.assertEqual(
            result["estimated_events_unlocked"]["estimation_window_gap"], 5)
        self.assertEqual(
            result["candidate_groups"]
                  ["estimation_window_gap"]["estimated_events_unlocked"], 5)


# ---------------------------------------------------------------------------
# manual_review_required flag
# ---------------------------------------------------------------------------


class TestManualReviewRequired(unittest.TestCase):
    def test_false_when_no_contamination(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertIs(result["manual_review_required"], False)

    def test_true_when_any_contaminated_event_present(self) -> None:
        payloads = _empty_payloads()
        payloads["clean_cohort"] = _clean_cohort_payload(
            total_events=1, fully_ready=1, contaminated=1, clean=0,
            excluded_examples=[
                _excluded_example(event_id=1,
                                  flags=["driv_lit_off_topic"])],
        )
        result = _run_with_kwargs(**payloads)
        self.assertIs(result["manual_review_required"], True)


# ---------------------------------------------------------------------------
# Candidate entries shape and limit
# ---------------------------------------------------------------------------


class TestCandidatesContract(unittest.TestCase):
    def test_candidate_entry_has_event_id_and_event_date(self) -> None:
        payloads = _empty_payloads()
        payloads["estimation_gap"] = _estimation_gap_payload(
            [_estimation_event(event_id=42, event_date="2026-04-09",
                               primary_ticker="XOM", missing_days=20)],
        )
        result = _run_with_kwargs(**payloads)
        candidates = result["candidate_groups"][
            "estimation_window_gap"]["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["event_id"],   42)
        self.assertEqual(candidates[0]["event_date"], "2026-04-09")
        self.assertEqual(candidates[0]["primary_ticker"], "XOM")

    def test_candidates_sorted_by_event_id_ascending(self) -> None:
        payloads = _empty_payloads()
        payloads["forward_gap"] = _forward_cache_gap_payload([
            _forward_gap_row(event_id=eid, horizon=20)
            for eid in (5, 1, 9, 3)
        ])
        result = _run_with_kwargs(**payloads)
        ids = [c["event_id"] for c in
               result["candidate_groups"]
                     ["price_cache_forward_20d"]["candidates"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_truncates_per_group_candidates_only(self) -> None:
        payloads = _empty_payloads()
        payloads["forward_gap"] = _forward_cache_gap_payload(
            [_forward_gap_row(event_id=i, horizon=20) for i in range(1, 11)],
        )
        result = cli.summarize_salvage_priority  # noqa: F841 (compat)
        # Drive through the patched seams with limit=3.
        p1, p2, p3, p4, p5 = _patch_all(**payloads)
        with p1, p2, p3, p4, p5:
            result = cli.summarize_salvage_priority(limit=3)
        bucket = result["candidate_groups"]["price_cache_forward_20d"]
        self.assertEqual(bucket["blocker_count"],            10)
        self.assertEqual(bucket["estimated_events_unlocked"], 10)
        self.assertEqual(len(bucket["candidates"]),            3)

    def test_negative_limit_clamps_to_zero(self) -> None:
        payloads = _empty_payloads()
        payloads["forward_gap"] = _forward_cache_gap_payload(
            [_forward_gap_row(event_id=1, horizon=20)],
        )
        p1, p2, p3, p4, p5 = _patch_all(**payloads)
        with p1, p2, p3, p4, p5:
            result = cli.summarize_salvage_priority(limit=-5)
        self.assertEqual(
            result["candidate_groups"]
                  ["price_cache_forward_20d"]["candidates"], [])
        self.assertEqual(
            result["candidate_groups"]
                  ["price_cache_forward_20d"]["blocker_count"], 1)


# ---------------------------------------------------------------------------
# target_clean_count
# ---------------------------------------------------------------------------


class TestTargetCleanCount(unittest.TestCase):
    def test_target_clean_count_default_is_positive(self) -> None:
        result = _run_with_kwargs(**_empty_payloads())
        self.assertGreater(result["target_clean_count"], 0)

    def test_target_clean_count_is_overridable(self) -> None:
        p1, p2, p3, p4, p5 = _patch_all(**_empty_payloads())
        with p1, p2, p3, p4, p5:
            result = cli.summarize_salvage_priority(target=50)
        self.assertEqual(result["target_clean_count"], 50)


# ---------------------------------------------------------------------------
# Conservative language
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    _BANNED = (
        "delete", "auto-correct", "auto correct", "auto-fix",
        "automatic", "fix the", "correct the", "replace the",
        "assign the", "reassign", "refresh prices", "live mutation",
    )

    def test_recommended_action_uses_conservative_phrasing(self) -> None:
        # Run a few scenarios and confirm none of them leak banned
        # vocabulary into the recommended_next_action prose.
        empty = _empty_payloads()
        scenarios: list[dict] = [empty, dict(**_empty_payloads(),
            ), ]
        # Scenario with mechanical-only path
        sc1 = _empty_payloads()
        sc1["estimation_gap"] = _estimation_gap_payload(
            [_estimation_event(event_id=i) for i in range(1, 4)])
        scenarios.append(sc1)
        # Scenario with contaminated path
        sc2 = _empty_payloads()
        sc2["clean_cohort"] = _clean_cohort_payload(
            total_events=1, fully_ready=1, contaminated=1, clean=0,
            excluded_examples=[
                _excluded_example(event_id=1,
                                  flags=["driv_lit_off_topic"])],
        )
        scenarios.append(sc2)

        for payloads in scenarios:
            p1, p2, p3, p4, p5 = _patch_all(**payloads)
            with p1, p2, p3, p4, p5:
                result = cli.summarize_salvage_priority()
            rec = result["recommended_next_action"].lower()
            for banned in self._BANNED:
                self.assertNotIn(
                    banned, rec,
                    f"banned phrase {banned!r} in: {rec!r}",
                )

    def test_recommended_action_uses_required_vocabulary(self) -> None:
        payloads = _empty_payloads()
        payloads["estimation_gap"] = _estimation_gap_payload(
            [_estimation_event(event_id=i) for i in range(1, 4)])
        p1, p2, p3, p4, p5 = _patch_all(**payloads)
        with p1, p2, p3, p4, p5:
            result = cli.summarize_salvage_priority()
        rec = result["recommended_next_action"].lower()
        # At least one of the brief-mandated words should appear:
        # "candidate" / "estimated" / "manual review required".
        self.assertTrue(
            any(w in rec for w in
                ("candidate", "estimated", "manual review")),
            f"recommended_next_action lacks required vocabulary: {rec!r}",
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_flag_emits_parseable_json(self) -> None:
        rc, output = _run_cli(["--json"], **_empty_payloads())
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, parsed)

    def test_text_mode_includes_salvage_word(self) -> None:
        rc, output = _run_cli([], **_empty_payloads())
        self.assertEqual(rc, 0)
        self.assertIn("salvage", output.lower())

    def test_limit_arg_caps_candidates(self) -> None:
        payloads = _empty_payloads()
        payloads["forward_gap"] = _forward_cache_gap_payload(
            [_forward_gap_row(event_id=i, horizon=20) for i in range(1, 8)],
        )
        rc, output = _run_cli(["--json", "--limit", "2"], **payloads)
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        bucket = parsed["candidate_groups"]["price_cache_forward_20d"]
        self.assertEqual(bucket["blocker_count"], 7)
        self.assertEqual(len(bucket["candidates"]), 2)

    def test_target_arg_overrides_default(self) -> None:
        rc, output = _run_cli(
            ["--json", "--target", "42"], **_empty_payloads(),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["target_clean_count"], 42)


# ---------------------------------------------------------------------------
# End-to-end: real seams against a temp DB.
# ---------------------------------------------------------------------------


class TestEndToEndAgainstTempDb(unittest.TestCase):
    def _make_temp_db(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"salvage_e2e_{uuid.uuid4().hex}.db",
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

    def test_runs_against_empty_temp_db_without_errors(self) -> None:
        path = self._make_temp_db()
        try:
            result = cli.summarize_salvage_priority(db_path=path)
        finally:
            os.unlink(path)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["current_clean_fully_ready_count"], 0)
        for k in _GROUP_KEYS:
            self.assertEqual(
                result["candidate_groups"][k]["blocker_count"], 0)


if __name__ == "__main__":
    unittest.main()
