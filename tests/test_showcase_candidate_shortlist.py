"""Tests for ``scripts/showcase_candidate_shortlist.py``.

Pin the read-only contract:

* The shortlist consumes three upstream reports through patchable
  seams: ``_run_archive_stat_validation`` (per-event signal records),
  ``_run_ticker_contamination_report`` (contaminated event_ids),
  and ``_run_clean_cohort_report`` (clean event_ids and current
  blocker buckets).
* Contaminated event_ids are NEVER surfaced — exclusion is hard, not
  a low-score nudge.
* Each candidate carries: ``event_id``, ``headline``, ``reason``,
  ``current_blocker`` (``None`` when clean), ``ticker_status``,
  ``showcase_score``.
* Candidates are sorted by ``showcase_score`` descending; ties
  resolve by ``event_id`` ascending.
* Clean fully-ready events outrank events with the same signal
  magnitude that still carry a blocker.
* Events with stronger ``|abnormal_return|`` outrank events with
  weaker signal at the same readiness level.
* Conservative language: recommendation never says "fix the X",
  "delete", "auto-correct", "guaranteed".
* Default run does NOT import yfinance / market_check / market_data /
  price_cache / api / routes.* / fastapi.
"""
from __future__ import annotations

import gc
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import showcase_candidate_shortlist as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "candidate_count",
    "candidates",
    "recommended_next_action",
)


_REQUIRED_CANDIDATE_KEYS = (
    "event_id",
    "headline",
    "reason",
    "current_blocker",
    "ticker_status",
    "showcase_score",
)


# ---------------------------------------------------------------------------
# Synthetic payload helpers
# ---------------------------------------------------------------------------


def _archive_record(
    *,
    event_id: int,
    horizon: int = 20,
    headline: str = "synthetic event",
    ticker: str | None = "AAPL",
    abnormal_return: float = 0.0,
    interpretation: str = "not_significant",
    fdr_q: float = 0.5,
) -> dict:
    return {
        "event_id":        event_id,
        "horizon":         horizon,
        "headline":        headline,
        "ticker":          ticker,
        "abnormal_return": abnormal_return,
        "sar":             0.0,
        "ci_low":          -0.05,
        "ci_high":         0.05,
        "p_value":         0.5,
        "fdr_q":           fdr_q,
        "interpretation":  interpretation,
    }


def _archive_payload(records: list[dict] | None = None) -> dict:
    """Synthetic archive_stat_validation_run payload.  The upstream
    function returns the per-(event, horizon) sample as ``examples``
    (the ``records`` list is internal); we mirror that contract.
    """
    records = records or []
    return {
        "ok":                       True,
        "events_evaluated":         len({r.get("event_id") for r in records}),
        "examples":                 records,
        "records_count":            len(records),
        "significant_count":        sum(
            1 for r in records if r.get("interpretation") == "significant"
        ),
        "by_horizon":               {},
        "by_mechanism_family":      {},
        "errors":                   [],
        "config":                   {"alpha": 0.05, "estimation_window": 60,
                                     "horizons": [1, 5, 20]},
        "recommended_next_action":  "synthetic",
    }


def _contamination_example(
    *, event_id: int, flags: list[str] | None = None,
    headline: str = "contaminated", primary_ticker: str = "DRIV",
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       "2026-04-04",
        "headline":         headline,
        "flags":            flags or ["driv_lit_off_topic"],
        "primary_ticker":   primary_ticker,
        "mechanism_family": "none",
    }


def _contamination_payload(examples: list[dict] | None = None) -> dict:
    examples = examples or []
    return {
        "ok":                      True,
        "total_fully_ready":       0,
        "suspicious_count":        len(examples),
        "examples":                examples,
        "by_flag":                 {},
        "duplicate_date_ticker_count": 0,
        "recommended_next_action": "synthetic",
    }


def _cohort_payload(
    *,
    clean_ids: list[int] | None = None,
    excluded_examples: list[dict] | None = None,
    salvage: dict[str, list[int]] | None = None,
) -> dict:
    """``salvage`` is a dict ``{bucket_name: [event_id, ...]}``.  We
    project it into the cohort report's ``next_salvage_candidates``
    shape so the shortlist's blocker map can be derived from it.
    """
    clean_ids = clean_ids or []
    excluded_examples = excluded_examples or []
    salvage = salvage or {}
    next_salvage: dict[str, dict] = {}
    for bucket, ids in salvage.items():
        next_salvage[bucket] = {
            "count":      len(ids),
            "candidates": [
                {"event_id": int(i), "event_date": "2026-04-15",
                 "primary_ticker": "AAPL"}
                for i in ids
            ],
        }
    return {
        "ok":                              True,
        "total_events":                    0,
        "fully_ready_count":               len(clean_ids) + len(excluded_examples),
        "clean_fully_ready_count":         len(clean_ids),
        "clean_fully_ready_event_ids":     [int(i) for i in clean_ids],
        "contaminated_fully_ready_count":  len(excluded_examples),
        "excluded_fully_ready_examples":   excluded_examples,
        "next_salvage_candidates":         next_salvage,
        "recommended_next_action":         "synthetic",
    }


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _patch_seams(*, archive: dict, contamination: dict, cohort: dict):
    return (
        patch.object(cli, "_run_archive_stat_validation",
                     return_value=archive),
        patch.object(cli, "_run_ticker_contamination_report",
                     return_value=contamination),
        patch.object(cli, "_run_clean_cohort_report",
                     return_value=cohort),
    )


def _run(*, archive=None, contamination=None, cohort=None, **kwargs) -> dict:
    archive       = archive       if archive       is not None else _archive_payload()
    contamination = contamination if contamination is not None else _contamination_payload()
    cohort        = cohort        if cohort        is not None else _cohort_payload()
    p1, p2, p3 = _patch_seams(archive=archive, contamination=contamination,
                              cohort=cohort)
    with p1, p2, p3:
        return cli.summarize_showcase_candidates(**kwargs)


def _run_cli(argv, *, archive=None, contamination=None, cohort=None) -> tuple[int, str]:
    archive       = archive       if archive       is not None else _archive_payload()
    contamination = contamination if contamination is not None else _contamination_payload()
    cohort        = cohort        if cohort        is not None else _cohort_payload()
    out = StringIO()
    p1, p2, p3 = _patch_seams(archive=archive, contamination=contamination,
                              cohort=cohort)
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
    def test_returns_dict_with_required_top_keys(self) -> None:
        result = _run()
        for k in _REQUIRED_TOP_KEYS:
            self.assertIn(k, result)

    def test_candidates_is_list(self) -> None:
        result = _run()
        self.assertIsInstance(result["candidates"], list)

    def test_each_candidate_has_required_fields(self) -> None:
        archive = _archive_payload([_archive_record(
            event_id=1, abnormal_return=0.05)])
        cohort = _cohort_payload(clean_ids=[1])
        result = _run(archive=archive, cohort=cohort)
        self.assertEqual(len(result["candidates"]), 1)
        for k in _REQUIRED_CANDIDATE_KEYS:
            self.assertIn(k, result["candidates"][0])


# ---------------------------------------------------------------------------
# Contamination exclusion
# ---------------------------------------------------------------------------


class TestContaminatedExcluded(unittest.TestCase):
    def test_contaminated_event_ids_never_surface(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=1, abnormal_return=0.10),
            _archive_record(event_id=2, abnormal_return=0.20),
        ])
        contamination = _contamination_payload([
            _contamination_example(event_id=1),
        ])
        cohort = _cohort_payload(
            clean_ids=[2],
            excluded_examples=[_contamination_example(event_id=1)],
        )
        result = _run(archive=archive, contamination=contamination,
                      cohort=cohort)
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertNotIn(1, ids)
        self.assertIn(2, ids)

    def test_contaminated_via_cohort_excluded_examples_too(self) -> None:
        # Defensive: even if the contamination report missed an event,
        # the cohort's ``excluded_fully_ready_examples`` must also act
        # as an exclusion source.
        archive = _archive_payload([_archive_record(event_id=1)])
        contamination = _contamination_payload()  # empty
        cohort = _cohort_payload(
            excluded_examples=[_contamination_example(event_id=1)],
        )
        result = _run(archive=archive, contamination=contamination,
                      cohort=cohort)
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertNotIn(1, ids)


# ---------------------------------------------------------------------------
# Score ordering
# ---------------------------------------------------------------------------


class TestScoreOrdering(unittest.TestCase):
    def test_clean_outranks_blocked_at_same_signal(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=1, abnormal_return=0.10),
            _archive_record(event_id=2, abnormal_return=0.10),
        ])
        cohort = _cohort_payload(
            clean_ids=[1],
            salvage={"missing_benchmark_proxy": [2]},
        )
        result = _run(archive=archive, cohort=cohort)
        scores = {c["event_id"]: c["showcase_score"] for c in result["candidates"]}
        self.assertGreater(scores[1], scores[2])

    def test_higher_signal_outranks_lower_at_same_readiness(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=1, abnormal_return=0.05),
            _archive_record(event_id=2, abnormal_return=0.20),
        ])
        cohort = _cohort_payload(clean_ids=[1, 2])
        result = _run(archive=archive, cohort=cohort)
        scores = {c["event_id"]: c["showcase_score"] for c in result["candidates"]}
        self.assertGreater(scores[2], scores[1])

    def test_significant_interpretation_boosts_score(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=1, abnormal_return=0.10,
                            interpretation="significant"),
            _archive_record(event_id=2, abnormal_return=0.10,
                            interpretation="not_significant"),
        ])
        cohort = _cohort_payload(clean_ids=[1, 2])
        result = _run(archive=archive, cohort=cohort)
        scores = {c["event_id"]: c["showcase_score"] for c in result["candidates"]}
        self.assertGreater(scores[1], scores[2])

    def test_candidates_sorted_descending_by_score(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=i, abnormal_return=0.01 * i)
            for i in (1, 2, 3, 4, 5)
        ])
        cohort = _cohort_payload(clean_ids=[1, 2, 3, 4, 5])
        result = _run(archive=archive, cohort=cohort)
        scores = [c["showcase_score"] for c in result["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_tie_resolved_by_event_id_ascending(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=eid, abnormal_return=0.05)
            for eid in (5, 1, 9, 3)
        ])
        cohort = _cohort_payload(clean_ids=[5, 1, 9, 3])
        result = _run(archive=archive, cohort=cohort)
        # All same readiness + signal → same score → ties → asc id
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, sorted(ids))


# ---------------------------------------------------------------------------
# current_blocker wiring
# ---------------------------------------------------------------------------


class TestCurrentBlockerWiring(unittest.TestCase):
    def test_clean_event_has_none_blocker(self) -> None:
        archive = _archive_payload([_archive_record(event_id=1)])
        cohort = _cohort_payload(clean_ids=[1])
        result = _run(archive=archive, cohort=cohort)
        self.assertIsNone(result["candidates"][0]["current_blocker"])

    def test_blocked_event_carries_bucket_label(self) -> None:
        archive = _archive_payload([_archive_record(event_id=1)])
        cohort = _cohort_payload(
            salvage={"missing_benchmark_proxy": [1]},
        )
        result = _run(archive=archive, cohort=cohort)
        self.assertEqual(
            result["candidates"][0]["current_blocker"],
            "missing_benchmark_proxy",
        )


# ---------------------------------------------------------------------------
# ticker_status
# ---------------------------------------------------------------------------


class TestTickerStatus(unittest.TestCase):
    def test_ticker_present_yields_set_status(self) -> None:
        archive = _archive_payload([_archive_record(
            event_id=1, ticker="XOM")])
        cohort = _cohort_payload(clean_ids=[1])
        result = _run(archive=archive, cohort=cohort)
        self.assertEqual(
            result["candidates"][0]["ticker_status"], "primary_ticker_set")

    def test_ticker_missing_yields_missing_status(self) -> None:
        archive = _archive_payload([_archive_record(
            event_id=1, ticker=None)])
        cohort = _cohort_payload(clean_ids=[1])
        result = _run(archive=archive, cohort=cohort)
        self.assertEqual(
            result["candidates"][0]["ticker_status"], "missing")


# ---------------------------------------------------------------------------
# Empty / no-candidates
# ---------------------------------------------------------------------------


class TestEmptyArchive(unittest.TestCase):
    def test_no_records_yields_empty_candidate_list(self) -> None:
        result = _run()
        self.assertEqual(result["candidate_count"],     0)
        self.assertEqual(result["candidates"],          [])

    def test_all_contaminated_yields_empty_with_recommendation(self) -> None:
        archive = _archive_payload([_archive_record(event_id=1)])
        contamination = _contamination_payload([
            _contamination_example(event_id=1)])
        cohort = _cohort_payload(
            excluded_examples=[_contamination_example(event_id=1)])
        result = _run(archive=archive, contamination=contamination,
                      cohort=cohort)
        self.assertEqual(result["candidate_count"], 0)
        rec = result["recommended_next_action"].lower()
        self.assertTrue(
            "contaminat" in rec or "no candidate" in rec
            or "manual review" in rec,
            f"unhelpful empty-shortlist recommendation: {rec!r}",
        )


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_limit_truncates_candidates_only(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=i, abnormal_return=0.10)
            for i in range(1, 11)
        ])
        cohort = _cohort_payload(
            clean_ids=list(range(1, 11)),
        )
        result = _run(archive=archive, cohort=cohort, limit=3)
        self.assertEqual(len(result["candidates"]),    3)
        self.assertEqual(result["candidate_count"],   10)

    def test_negative_limit_clamps_to_zero(self) -> None:
        archive = _archive_payload([_archive_record(event_id=1)])
        cohort = _cohort_payload(clean_ids=[1])
        result = _run(archive=archive, cohort=cohort, limit=-5)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["candidate_count"], 1)


# ---------------------------------------------------------------------------
# Recommendation language
# ---------------------------------------------------------------------------


class TestRecommendation(unittest.TestCase):
    _BANNED = (
        "delete", "auto-correct", "fix the", "guaranteed",
        "must demo", "auto-fix", "live mutation", "refresh prices",
    )

    def test_conservative_language(self) -> None:
        scenarios = [
            {},  # empty
            {  # contaminated only
                "archive": _archive_payload([_archive_record(event_id=1)]),
                "contamination": _contamination_payload(
                    [_contamination_example(event_id=1)]),
                "cohort": _cohort_payload(excluded_examples=[
                    _contamination_example(event_id=1)]),
            },
            {  # clean candidate
                "archive": _archive_payload([_archive_record(
                    event_id=1, abnormal_return=0.10)]),
                "cohort": _cohort_payload(clean_ids=[1]),
            },
        ]
        for kwargs in scenarios:
            result = _run(**kwargs)
            rec = result["recommended_next_action"].lower()
            for banned in self._BANNED:
                self.assertNotIn(banned, rec, f"banned phrase: {rec!r}")


# ---------------------------------------------------------------------------
# Provider isolation
# ---------------------------------------------------------------------------


class TestProviderIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "market_check", "market_data", "price_cache",
                "api", "fastapi")

    def test_default_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED)}
        _run()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# Seam patchability
# ---------------------------------------------------------------------------


class TestSeamPatchability(unittest.TestCase):
    def test_archive_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_archive_stat_validation")))

    def test_contamination_seam_exists(self) -> None:
        self.assertTrue(
            callable(getattr(cli, "_run_ticker_contamination_report")))

    def test_cohort_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_clean_cohort_report")))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_emits_parseable(self) -> None:
        rc, output = _run_cli(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_TOP_KEYS:
            self.assertIn(k, parsed)

    def test_text_mode_includes_showcase_word(self) -> None:
        rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("showcase", output.lower())

    def test_limit_arg_caps(self) -> None:
        archive = _archive_payload([
            _archive_record(event_id=i, abnormal_return=0.05)
            for i in range(1, 8)
        ])
        cohort = _cohort_payload(clean_ids=list(range(1, 8)))
        rc, output = _run_cli(["--json", "--limit", "2"],
                              archive=archive, cohort=cohort)
        parsed = json.loads(output)
        self.assertEqual(len(parsed["candidates"]), 2)
        self.assertEqual(parsed["candidate_count"], 7)


# ---------------------------------------------------------------------------
# End-to-end against an empty temp DB
# ---------------------------------------------------------------------------


def _safe_unlink(path: str, *, attempts: int = 5, delay: float = 0.05) -> None:
    """Windows-safe unlink for sqlite-backed temp files.

    Windows refuses to delete a file while any handle on it remains
    open.  Even after the product code's ``conn.close()`` returns,
    sqlite3 / Python may briefly hold the underlying file via a
    lingering reference; ``gc.collect`` plus a short retry loop
    releases it deterministically.  Only ``PermissionError`` /
    ``FileNotFoundError`` are swallowed — every other error
    propagates so a real bug is never masked by cleanup.
    """
    gc.collect()
    for _ in range(attempts):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(delay)
    # Final attempt — swallow PermissionError so a left-behind temp
    # file in the OS temp dir never masks the test's real assertion
    # outcome.  The OS temp dir is purged by the OS on its own cadence.
    try:
        os.unlink(path)
    except (FileNotFoundError, PermissionError):
        pass


class TestEndToEndAgainstTempDb(unittest.TestCase):
    def _make_temp_db(self) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"showcase_e2e_{uuid.uuid4().hex}.db",
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
            result = cli.summarize_showcase_candidates(db_path=path)
            for k in _REQUIRED_TOP_KEYS:
                self.assertIn(k, result)
            self.assertEqual(result["candidate_count"], 0)
        finally:
            _safe_unlink(path)


if __name__ == "__main__":
    unittest.main()
