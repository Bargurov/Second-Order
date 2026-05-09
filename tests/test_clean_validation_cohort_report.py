"""Tests for ``scripts/clean_validation_cohort_report.py``.

Pin the contract:

* The cohort selector consumes three upstream reports through the
  patchable seams ``_run_readiness_report``,
  ``_run_contamination_report`` and ``_run_blocker_report`` so unit
  tests can drive the selector with synthetic fixtures.
* Aggregates always reflect every event in the archive — ``--limit``
  truncates only the surfaced ``excluded_fully_ready_examples`` and
  the per-bucket ``candidates`` lists under
  ``next_salvage_candidates``.
* ``clean_fully_ready_event_ids`` is the set of fully-ready event ids
  that are NOT flagged as suspicious by the contamination report,
  sorted ascending.
* Conservative language: the recommended action references
  "candidate", "manual review", or "excluded from aggregate claim";
  never "delete", "auto-correct", "assign", "replace", or "fix".
* The selector NEVER assigns or proposes replacement tickers.
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

from scripts import clean_validation_cohort_report as cli  # noqa: E402


_TOP_KEYS = (
    "ok",
    "total_events",
    "fully_ready_count",
    "contaminated_fully_ready_count",
    "clean_fully_ready_count",
    "clean_fully_ready_event_ids",
    "excluded_fully_ready_examples",
    "next_salvage_candidates",
    "recommended_next_action",
)


_BLOCKER_KEYS = (
    "missing_market_tickers",
    "missing_forward_cache_1d",
    "missing_forward_cache_5d",
    "missing_forward_cache_20d",
    "missing_benchmark_proxy",
    "insufficient_estimation_window",
)


_EXCLUDED_EXAMPLE_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "headline",
    "mechanism_family",
    "flags",
)


_CANDIDATE_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
)


# ---------------------------------------------------------------------------
# Synthetic readiness / contamination / blocker payload helpers
# ---------------------------------------------------------------------------


def _ready_event(*, event_id: int, event_date: str = "2026-04-15",
                 primary_ticker: str = "AAPL") -> dict:
    """Build one fully-ready readiness per-event entry."""
    return {
        "event_id":       event_id,
        "event_date":     event_date,
        "primary_ticker": primary_ticker,
        "checks": {
            "has_event_date":               True,
            "has_market_tickers":           True,
            "forward_cache_1d":             True,
            "forward_cache_5d":             True,
            "forward_cache_20d":            True,
            "benchmark_proxy_available":    True,
            "estimation_window_sufficient": True,
        },
        "fully_ready": True,
    }


def _not_ready_event(
    *, event_id: int, event_date: str = "2026-04-15",
    primary_ticker: str | None = "AAPL",
    failing_checks: tuple[str, ...] = ("forward_cache_1d",),
) -> dict:
    """Build one not-ready readiness per-event entry, failing the
    checks listed in ``failing_checks``."""
    checks = {
        "has_event_date":               True,
        "has_market_tickers":           True,
        "forward_cache_1d":             True,
        "forward_cache_5d":             True,
        "forward_cache_20d":            True,
        "benchmark_proxy_available":    True,
        "estimation_window_sufficient": True,
    }
    for k in failing_checks:
        checks[k] = False
    return {
        "event_id":       event_id,
        "event_date":     event_date,
        "primary_ticker": primary_ticker,
        "checks":         checks,
        "fully_ready":    all(checks.values()),
    }


def _readiness_payload(events: list[dict]) -> dict:
    return {
        "total_events":       len(events),
        "events_fully_ready": sum(1 for e in events if e["fully_ready"]),
        "events":             events,
        "recommended_next_action": "synthetic",
    }


def _contamination_example(
    *, event_id: int, flags: list[str],
    event_date: str = "2026-04-15",
    primary_ticker: str = "AAPL",
    headline: str = "synthetic headline",
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


def _contamination_payload(
    *, total_fully_ready: int, examples: list[dict],
) -> dict:
    return {
        "ok":                          True,
        "total_fully_ready":           total_fully_ready,
        "suspicious_count":            len(examples),
        "duplicate_date_ticker_count": sum(
            1 for e in examples if "duplicate_date_ticker" in e["flags"]
        ),
        "by_flag": {
            "driv_lit_off_topic":      sum(1 for e in examples if "driv_lit_off_topic"      in e["flags"]),
            "mechanism_family_none":   sum(1 for e in examples if "mechanism_family_none"   in e["flags"]),
            "duplicate_date_ticker":   sum(1 for e in examples if "duplicate_date_ticker"   in e["flags"]),
            "local_off_topic_headline":sum(1 for e in examples if "local_off_topic_headline"in e["flags"]),
        },
        "examples":                    examples,
        "recommended_next_action":     "synthetic",
    }


def _blocker_payload(
    *, total_events: int, fully_ready: int,
    blockers: dict[str, list[dict]] | None = None,
) -> dict:
    """Build a synthetic blocker-report payload.  ``blockers`` maps
    each blocker key to the list of failing event entries; missing
    keys default to an empty list."""
    blockers = blockers or {}
    blockers_full: dict[str, dict] = {}
    for k in _BLOCKER_KEYS:
        entries = blockers.get(k, [])
        blockers_full[k] = {"count": len(entries), "examples": entries}
    return {
        "total_events":           total_events,
        "events_fully_ready":     fully_ready,
        "events_not_fully_ready": total_events - fully_ready,
        "blockers":               blockers_full,
        "recommended_next_action": "synthetic",
    }


def _patch_all(readiness: dict, contamination: dict, blockers: dict):
    return (
        patch.object(cli, "_run_readiness_report",     return_value=readiness),
        patch.object(cli, "_run_contamination_report", return_value=contamination),
        patch.object(cli, "_run_blocker_report",       return_value=blockers),
    )


def _run_with(readiness: dict, contamination: dict, blockers: dict,
              **kwargs):
    p1, p2, p3 = _patch_all(readiness, contamination, blockers)
    with p1, p2, p3:
        return cli.summarize_clean_cohort(**kwargs)


def _run_cli(argv: list[str], readiness: dict, contamination: dict,
             blockers: dict) -> tuple[int, str]:
    out = StringIO()
    p1, p2, p3 = _patch_all(readiness, contamination, blockers)
    with p1, p2, p3:
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
        result = _run_with(
            _readiness_payload([]),
            _contamination_payload(total_fully_ready=0, examples=[]),
            _blocker_payload(total_events=0, fully_ready=0),
        )
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_next_salvage_candidates_has_every_blocker_bucket(self) -> None:
        result = _run_with(
            _readiness_payload([]),
            _contamination_payload(total_fully_ready=0, examples=[]),
            _blocker_payload(total_events=0, fully_ready=0),
        )
        self.assertIsInstance(result["next_salvage_candidates"], dict)
        for key in _BLOCKER_KEYS:
            self.assertIn(key, result["next_salvage_candidates"])
            bucket = result["next_salvage_candidates"][key]
            self.assertIn("count",      bucket)
            self.assertIn("candidates", bucket)
            self.assertIsInstance(bucket["count"],      int)
            self.assertIsInstance(bucket["candidates"], list)

    def test_ok_is_true_on_clean_run(self) -> None:
        result = _run_with(
            _readiness_payload([]),
            _contamination_payload(total_fully_ready=0, examples=[]),
            _blocker_payload(total_events=0, fully_ready=0),
        )
        self.assertIs(result["ok"], True)


# ---------------------------------------------------------------------------
# Empty archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(unittest.TestCase):
    def test_zero_events_zeros_every_count(self) -> None:
        result = _run_with(
            _readiness_payload([]),
            _contamination_payload(total_fully_ready=0, examples=[]),
            _blocker_payload(total_events=0, fully_ready=0),
        )
        self.assertEqual(result["total_events"],                    0)
        self.assertEqual(result["fully_ready_count"],               0)
        self.assertEqual(result["contaminated_fully_ready_count"],  0)
        self.assertEqual(result["clean_fully_ready_count"],         0)
        self.assertEqual(result["clean_fully_ready_event_ids"],    [])
        self.assertEqual(result["excluded_fully_ready_examples"],  [])
        for key in _BLOCKER_KEYS:
            self.assertEqual(
                result["next_salvage_candidates"][key]["count"], 0,
            )
        self.assertIn("empty",
                      result["recommended_next_action"].lower())


# ---------------------------------------------------------------------------
# All fully-ready clean
# ---------------------------------------------------------------------------


class TestAllReadyClean(unittest.TestCase):
    def test_clean_count_equals_fully_ready_when_no_contamination(self) -> None:
        events = [_ready_event(event_id=i) for i in (1, 2, 3)]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=3, examples=[]),
            _blocker_payload(total_events=3, fully_ready=3),
        )
        self.assertEqual(result["fully_ready_count"],              3)
        self.assertEqual(result["contaminated_fully_ready_count"], 0)
        self.assertEqual(result["clean_fully_ready_count"],        3)
        self.assertEqual(result["clean_fully_ready_event_ids"],   [1, 2, 3])
        self.assertEqual(result["excluded_fully_ready_examples"], [])

    def test_recommended_action_when_all_clean(self) -> None:
        events = [_ready_event(event_id=i) for i in (1, 2)]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=2, examples=[]),
            _blocker_payload(total_events=2, fully_ready=2),
        )
        rec = result["recommended_next_action"].lower()
        self.assertTrue("clean" in rec or "no contamination" in rec
                        or "no suspicious" in rec,
                        f"recommended_next_action unexpected: {rec!r}")


# ---------------------------------------------------------------------------
# All fully-ready contaminated
# ---------------------------------------------------------------------------


class TestAllReadyContaminated(unittest.TestCase):
    def test_clean_count_zero_when_every_ready_event_is_suspicious(self) -> None:
        events = [_ready_event(event_id=i) for i in (1, 2)]
        contam_examples = [
            _contamination_example(event_id=1, flags=["driv_lit_off_topic"]),
            _contamination_example(event_id=2, flags=["mechanism_family_none"]),
        ]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=2,
                                   examples=contam_examples),
            _blocker_payload(total_events=2, fully_ready=2),
        )
        self.assertEqual(result["fully_ready_count"],              2)
        self.assertEqual(result["contaminated_fully_ready_count"], 2)
        self.assertEqual(result["clean_fully_ready_count"],        0)
        self.assertEqual(result["clean_fully_ready_event_ids"],   [])
        self.assertEqual(len(result["excluded_fully_ready_examples"]), 2)

    def test_recommended_action_when_all_ready_contaminated(self) -> None:
        events = [_ready_event(event_id=1)]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(
                total_fully_ready=1,
                examples=[_contamination_example(
                    event_id=1, flags=["driv_lit_off_topic"])],
            ),
            _blocker_payload(total_events=1, fully_ready=1),
        )
        rec = result["recommended_next_action"].lower()
        self.assertIn("manual review", rec)


# ---------------------------------------------------------------------------
# Mixed clean / contaminated
# ---------------------------------------------------------------------------


class TestMixedCohort(unittest.TestCase):
    def test_clean_event_ids_excludes_contaminated_ids(self) -> None:
        events = [_ready_event(event_id=i) for i in (1, 2, 3, 4)]
        contam_examples = [
            _contamination_example(event_id=2, flags=["driv_lit_off_topic"]),
            _contamination_example(event_id=4, flags=["mechanism_family_none"]),
        ]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=4,
                                   examples=contam_examples),
            _blocker_payload(total_events=4, fully_ready=4),
        )
        self.assertEqual(result["fully_ready_count"],              4)
        self.assertEqual(result["contaminated_fully_ready_count"], 2)
        self.assertEqual(result["clean_fully_ready_count"],        2)
        self.assertEqual(result["clean_fully_ready_event_ids"],   [1, 3])

    def test_excluded_examples_carry_flags_as_reasons(self) -> None:
        events = [_ready_event(event_id=i) for i in (1, 2)]
        contam_examples = [
            _contamination_example(
                event_id=2,
                flags=["driv_lit_off_topic", "mechanism_family_none"]),
        ]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=2,
                                   examples=contam_examples),
            _blocker_payload(total_events=2, fully_ready=2),
        )
        excluded = result["excluded_fully_ready_examples"]
        self.assertEqual(len(excluded), 1)
        for key in _EXCLUDED_EXAMPLE_KEYS:
            self.assertIn(key, excluded[0])
        self.assertEqual(excluded[0]["event_id"], 2)
        self.assertEqual(
            excluded[0]["flags"],
            ["driv_lit_off_topic", "mechanism_family_none"],
        )


# ---------------------------------------------------------------------------
# excluded_fully_ready_examples ordering and limit
# ---------------------------------------------------------------------------


class TestExcludedExamplesContract(unittest.TestCase):
    def test_examples_sorted_by_event_id_ascending(self) -> None:
        events = [_ready_event(event_id=i) for i in (1, 2, 3, 4)]
        contam_examples = [
            _contamination_example(event_id=4, flags=["driv_lit_off_topic"]),
            _contamination_example(event_id=1, flags=["mechanism_family_none"]),
            _contamination_example(event_id=3, flags=["duplicate_date_ticker"]),
        ]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=4,
                                   examples=contam_examples),
            _blocker_payload(total_events=4, fully_ready=4),
        )
        ids = [e["event_id"] for e in result["excluded_fully_ready_examples"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_truncates_excluded_examples_only(self) -> None:
        events = [_ready_event(event_id=i) for i in range(1, 11)]
        contam_examples = [
            _contamination_example(event_id=i, flags=["driv_lit_off_topic"])
            for i in range(1, 11)
        ]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=10,
                                   examples=contam_examples),
            _blocker_payload(total_events=10, fully_ready=10),
            limit=3,
        )
        self.assertEqual(len(result["excluded_fully_ready_examples"]), 3)
        # Aggregate count is NOT capped.
        self.assertEqual(result["contaminated_fully_ready_count"], 10)
        self.assertEqual(result["clean_fully_ready_count"],         0)

    def test_negative_limit_clamps_to_zero(self) -> None:
        events = [_ready_event(event_id=1)]
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(
                total_fully_ready=1,
                examples=[_contamination_example(
                    event_id=1, flags=["driv_lit_off_topic"])],
            ),
            _blocker_payload(total_events=1, fully_ready=1),
            limit=-5,
        )
        self.assertEqual(result["excluded_fully_ready_examples"], [])
        self.assertEqual(result["contaminated_fully_ready_count"], 1)


# ---------------------------------------------------------------------------
# next_salvage_candidates structure
# ---------------------------------------------------------------------------


class TestNextSalvageCandidates(unittest.TestCase):
    def test_blocker_buckets_carry_event_ids(self) -> None:
        events = [
            _not_ready_event(event_id=10,
                             failing_checks=("forward_cache_1d",
                                             "forward_cache_5d",
                                             "forward_cache_20d")),
            _not_ready_event(event_id=11,
                             failing_checks=("benchmark_proxy_available",)),
        ]
        readiness = _readiness_payload(events)
        # Synthesise a blocker payload that mirrors what the real
        # blocker report would produce for these two events.
        blockers = _blocker_payload(
            total_events=2,
            fully_ready=0,
            blockers={
                "missing_forward_cache_1d":  [events[0]],
                "missing_forward_cache_5d":  [events[0]],
                "missing_forward_cache_20d": [events[0]],
                "missing_benchmark_proxy":   [events[1]],
            },
        )
        result = _run_with(
            readiness,
            _contamination_payload(total_fully_ready=0, examples=[]),
            blockers,
        )
        nsc = result["next_salvage_candidates"]
        self.assertEqual(nsc["missing_forward_cache_1d"]["count"], 1)
        self.assertEqual(nsc["missing_benchmark_proxy"]["count"],  1)
        ids_b = [c["event_id"]
                 for c in nsc["missing_benchmark_proxy"]["candidates"]]
        self.assertEqual(ids_b, [11])

    def test_candidate_entry_has_minimal_keys(self) -> None:
        ev = _not_ready_event(event_id=42, primary_ticker="XOM",
                              event_date="2026-04-09",
                              failing_checks=("forward_cache_1d",))
        blockers = _blocker_payload(
            total_events=1, fully_ready=0,
            blockers={"missing_forward_cache_1d": [ev]},
        )
        result = _run_with(
            _readiness_payload([ev]),
            _contamination_payload(total_fully_ready=0, examples=[]),
            blockers,
        )
        candidates = result["next_salvage_candidates"][
            "missing_forward_cache_1d"]["candidates"]
        self.assertEqual(len(candidates), 1)
        for key in _CANDIDATE_KEYS:
            self.assertIn(key, candidates[0])
        self.assertEqual(candidates[0]["event_id"], 42)
        self.assertEqual(candidates[0]["primary_ticker"], "XOM")

    def test_limit_truncates_each_blocker_bucket_candidates(self) -> None:
        events = [
            _not_ready_event(event_id=i,
                             failing_checks=("forward_cache_1d",))
            for i in range(1, 11)
        ]
        blockers = _blocker_payload(
            total_events=10, fully_ready=0,
            blockers={"missing_forward_cache_1d": events},
        )
        result = _run_with(
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=0, examples=[]),
            blockers,
            limit=4,
        )
        bucket = result["next_salvage_candidates"]["missing_forward_cache_1d"]
        self.assertEqual(bucket["count"], 10)
        self.assertEqual(len(bucket["candidates"]), 4)


# ---------------------------------------------------------------------------
# Conservative language
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    _BANNED = (
        "delete", "auto-correct", "auto correct", "auto-fix",
        "automatic", "fix the", "correct the", "replace the",
        "assign the", "reassign",
    )

    def test_recommended_action_uses_conservative_phrasing(self) -> None:
        scenarios: list[tuple[dict, dict, dict]] = [
            # empty
            (_readiness_payload([]),
             _contamination_payload(total_fully_ready=0, examples=[]),
             _blocker_payload(total_events=0, fully_ready=0)),
            # all clean
            (_readiness_payload([_ready_event(event_id=1)]),
             _contamination_payload(total_fully_ready=1, examples=[]),
             _blocker_payload(total_events=1, fully_ready=1)),
            # all contaminated
            (_readiness_payload([_ready_event(event_id=1)]),
             _contamination_payload(
                 total_fully_ready=1,
                 examples=[_contamination_example(
                     event_id=1, flags=["driv_lit_off_topic"])]),
             _blocker_payload(total_events=1, fully_ready=1)),
            # mixed
            (_readiness_payload([_ready_event(event_id=i) for i in (1, 2)]),
             _contamination_payload(
                 total_fully_ready=2,
                 examples=[_contamination_example(
                     event_id=2, flags=["driv_lit_off_topic"])]),
             _blocker_payload(total_events=2, fully_ready=2)),
        ]
        for readiness, contam, blockers in scenarios:
            result = _run_with(readiness, contam, blockers)
            rec = result["recommended_next_action"].lower()
            for banned in self._BANNED:
                self.assertNotIn(
                    banned, rec,
                    f"banned phrase {banned!r} appeared in: {rec!r}",
                )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_flag_emits_parseable_json(self) -> None:
        rc, output = _run_cli(
            ["--json"],
            _readiness_payload([_ready_event(event_id=1)]),
            _contamination_payload(
                total_fully_ready=1,
                examples=[_contamination_example(
                    event_id=1, flags=["driv_lit_off_topic"])]),
            _blocker_payload(total_events=1, fully_ready=1),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, parsed)

    def test_text_mode_includes_clean_count(self) -> None:
        rc, output = _run_cli(
            [],
            _readiness_payload([_ready_event(event_id=1)]),
            _contamination_payload(total_fully_ready=1, examples=[]),
            _blocker_payload(total_events=1, fully_ready=1),
        )
        self.assertEqual(rc, 0)
        self.assertIn("clean", output.lower())

    def test_limit_arg_caps_examples(self) -> None:
        events = [_ready_event(event_id=i) for i in range(1, 6)]
        contam_examples = [
            _contamination_example(event_id=i, flags=["driv_lit_off_topic"])
            for i in range(1, 6)
        ]
        rc, output = _run_cli(
            ["--json", "--limit", "2"],
            _readiness_payload(events),
            _contamination_payload(total_fully_ready=5,
                                   examples=contam_examples),
            _blocker_payload(total_events=5, fully_ready=5),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(len(parsed["excluded_fully_ready_examples"]), 2)
        self.assertEqual(parsed["contaminated_fully_ready_count"], 5)


# ---------------------------------------------------------------------------
# End-to-end: real seams against a temp DB.
# ---------------------------------------------------------------------------


class TestEndToEndAgainstTempDb(unittest.TestCase):
    """Wire the un-patched seams against a synthetic SQLite DB to
    confirm the plumbing reaches the events table and the upstream
    reports without provider/network/LLM calls.
    """

    def _make_temp_db(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"clean_cohort_e2e_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "CREATE TABLE events ("
                " id INTEGER PRIMARY KEY,"
                " headline TEXT, event_date TEXT,"
                " market_tickers TEXT, mechanism_family TEXT)"
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
            result = cli.summarize_clean_cohort(db_path=path)
        finally:
            os.unlink(path)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["total_events"],                   0)
        self.assertEqual(result["fully_ready_count"],              0)
        self.assertEqual(result["contaminated_fully_ready_count"], 0)
        self.assertEqual(result["clean_fully_ready_count"],        0)


if __name__ == "__main__":
    unittest.main()
