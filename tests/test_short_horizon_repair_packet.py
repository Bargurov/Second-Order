"""Tests for ``scripts/short_horizon_repair_packet.py``.

Pin the contract:

* The packet builds on TWO upstream reports through patchable seams
  so unit tests can drive it with synthetic payloads — no DB is ever
  touched on the test path:
    - ``_run_short_horizon_readiness_report`` — short-horizon (1d/5d)
      readiness coverage report.
    - ``_run_short_horizon_contamination_report`` — topical
      contamination report scoped to the short-horizon-ready cohort.
* Per-row entries carry EXACTLY these 11 packet keys:
  ``event_id``, ``headline``, ``event_date``,
  ``current_primary_ticker``, ``flags``, ``repair_type``,
  ``repair_priority``, ``proposed_primary_ticker``,
  ``proposed_mechanism_family``, ``rationale``, ``exclude_reason``.
* The four operator-input fields (``proposed_primary_ticker``,
  ``proposed_mechanism_family``, ``rationale``, ``exclude_reason``)
  are ALWAYS empty strings — the packet does not assign tickers or
  mechanism families.
* Twenty-four already-reviewed event_ids are dropped before ranking
  — same set as the prior manual review batch.
* Conservative wording — banned tokens in ``recommended_next_action``
  and other text output: ``delete``, ``auto-correct``, ``auto fix``,
  ``automatic``, ``assign``, ``fix the``, ``replace``, ``correct``.
  (Column names like ``proposed_primary_ticker`` are schema, not
  text — exempt by design.)
* Read-only: default run does not import yfinance / market_check /
  market_data / price_cache / api / fastapi / routes.*.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_repair_packet as cli  # noqa: E402


_PACKET_KEYS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "flags",
    "repair_type",
    "repair_priority",
    "proposed_primary_ticker",
    "proposed_mechanism_family",
    "rationale",
    "exclude_reason",
)


_BLANK_KEYS = (
    "proposed_primary_ticker",
    "proposed_mechanism_family",
    "rationale",
    "exclude_reason",
)


_BANNED_WORDS = (
    "delete",
    "auto-correct",
    "auto fix",
    "automatic",
    "assign",
    "fix the",
    "replace",
    "correct",
)


_EXPECTED_EXCLUDED_IDS = frozenset({
    4, 6, 8, 9,
    46, 47, 49, 51,
    60, 64, 73,
    112,
    153, 154, 160,
    206, 207, 208, 216, 220, 226, 231, 237,
    281,
})


_PLAUSIBLE_HEADLINE = "Bank of America announces dividend increase"
_SHORT_HEADLINE = "x"


# ---------------------------------------------------------------------------
# Synthetic payloads
# ---------------------------------------------------------------------------


def _contamination_example(
    *,
    event_id: int,
    flags: list[str],
    headline: str | None = _PLAUSIBLE_HEADLINE,
    event_date: str | None = "2026-04-01",
    primary_ticker: str | None = "BAC",
    mechanism_family: str | None = None,
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "flags":            list(flags),
    }


def _contamination_payload(
    examples: list[dict],
    *,
    total_short_ready: int | None = None,
) -> dict:
    by_flag = {
        "driv_lit_off_topic":       sum(1 for e in examples if "driv_lit_off_topic"       in e["flags"]),
        "mechanism_family_none":    sum(1 for e in examples if "mechanism_family_none"    in e["flags"]),
        "duplicate_date_ticker":    sum(1 for e in examples if "duplicate_date_ticker"    in e["flags"]),
        "local_off_topic_headline": sum(1 for e in examples if "local_off_topic_headline" in e["flags"]),
    }
    n = total_short_ready if total_short_ready is not None else max(len(examples), 1)
    return {
        "ok":                       True,
        "total_short_ready":        n,
        "suspicious_count":         len(examples),
        "clean_short_ready_count":  max(n - len(examples), 0),
        "by_flag":                  by_flag,
        "examples":                 list(examples),
        "recommended_next_action":  "synthetic",
    }


def _readiness_payload(
    *,
    events_ready_1d5d: int = 0,
    delta_vs_full_ready: int = 0,
) -> dict:
    return {
        "total_events":                          events_ready_1d5d,
        "events_ready_1d5d":                     events_ready_1d5d,
        "delta_vs_full_ready":                   delta_vs_full_ready,
        "missing_tickers_count":                 0,
        "missing_benchmark_count":               0,
        "insufficient_estimation_window_count":  0,
        "examples":                              [],
        "recommended_next_action":               "synthetic",
    }


def _patch_seams(*, contamination: dict, readiness: dict | None = None):
    readiness_obj = readiness if readiness is not None else _readiness_payload()
    return _SeamPatch(contamination=contamination, readiness=readiness_obj)


class _SeamPatch:
    def __init__(self, *, contamination: dict, readiness: dict) -> None:
        self._cont = patch.object(
            cli, "_run_short_horizon_contamination_report",
            return_value=contamination,
        )
        self._read = patch.object(
            cli, "_run_short_horizon_readiness_report",
            return_value=readiness,
        )

    def __enter__(self):
        self._cont.__enter__()
        self._read.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._read.__exit__(exc_type, exc, tb)
        self._cont.__exit__(exc_type, exc, tb)
        return False


def _run(
    *,
    contamination: dict | None = None,
    readiness: dict | None = None,
    **kwargs,
) -> dict:
    contamination = (
        contamination if contamination is not None
        else _contamination_payload([])
    )
    with _patch_seams(contamination=contamination, readiness=readiness):
        return cli.summarize_short_horizon_repair_packet(**kwargs)


def _run_cli(
    argv: list[str], *,
    contamination: dict | None = None,
    readiness: dict | None = None,
) -> tuple[int, str]:
    contamination = (
        contamination if contamination is not None
        else _contamination_payload([])
    )
    out = StringIO()
    with _patch_seams(contamination=contamination, readiness=readiness):
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Per-row contract
# ---------------------------------------------------------------------------


class TestPerRowContract(unittest.TestCase):
    def test_each_row_has_exactly_eleven_keys(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
                _contamination_example(event_id=1001, flags=["driv_lit_off_topic"]),
            ]),
        )
        self.assertGreater(len(result["candidates"]), 0)
        for entry in result["candidates"]:
            self.assertEqual(set(entry.keys()), set(_PACKET_KEYS),
                             f"unexpected keys: {entry.keys()!r}")

    def test_blank_proposal_fields_are_empty_strings(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        entry = result["candidates"][0]
        for k in _BLANK_KEYS:
            self.assertEqual(entry[k], "",
                             f"{k} must be blank string, got {entry[k]!r}")

    def test_event_date_carried_through(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    event_date="2026-03-15"),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["event_date"], "2026-03-15")

    def test_current_primary_ticker_carried_through(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    primary_ticker="AAPL"),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["current_primary_ticker"], "AAPL")

    def test_headline_carried_through(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    headline="Apple Inc reports earnings beat"),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["headline"],
            "Apple Inc reports earnings beat")

    def test_flags_list_preserved(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(
            sorted(result["candidates"][0]["flags"]),
            sorted(["mechanism_family_none", "duplicate_date_ticker"]),
        )

    def test_unflagged_rows_dropped_defensively(self) -> None:
        # Contamination examples are flagged by construction, but the
        # packet must defensively drop any non-flagged row that slips
        # through — we only surface rows that need repair.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=[]),
                _contamination_example(event_id=1001, flags=["mechanism_family_none"]),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1001])


# ---------------------------------------------------------------------------
# Reviewed-id exclusion
# ---------------------------------------------------------------------------


class TestReviewedIdExclusion(unittest.TestCase):
    def test_excluded_event_ids_set_count_is_24(self) -> None:
        self.assertEqual(len(cli._EXCLUDED_EVENT_IDS), 24)

    def test_excluded_event_ids_match_expected_membership(self) -> None:
        self.assertEqual(
            set(cli._EXCLUDED_EVENT_IDS), set(_EXPECTED_EXCLUDED_IDS))

    def test_excluded_event_ids_surfaced_sorted(self) -> None:
        result = _run(contamination=_contamination_payload([]))
        self.assertEqual(
            result["excluded_reviewed_event_ids"],
            sorted(_EXPECTED_EXCLUDED_IDS),
        )
        self.assertEqual(result["reviewed_exclusion_set_count"], 24)

    def test_reviewed_ids_dropped_from_candidates(self) -> None:
        # A reviewed id (4) and a fresh id (1000) — only the fresh id
        # should remain.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4, flags=["mechanism_family_none"]),
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1000])

    def test_excluded_count_reflects_dropped_reviewed_rows(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4,    flags=["mechanism_family_none"]),
                _contamination_example(event_id=6,    flags=["driv_lit_off_topic"]),
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(result["excluded_reviewed_count"], 2)

    def test_unflagged_reviewed_ids_do_not_inflate_count(self) -> None:
        # An event in the reviewed set but with no flags is dropped by
        # the defensive empty-flag filter, NOT by the reviewed-id
        # exclusion — so the excluded_reviewed_count must not count it.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4, flags=[]),
                _contamination_example(event_id=6, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(result["excluded_reviewed_count"], 1)


# ---------------------------------------------------------------------------
# Repair type
# ---------------------------------------------------------------------------


class TestRepairType(unittest.TestCase):
    def test_mechanism_family_only(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["repair_type"], "mechanism_family_only")

    def test_ticker_off_topic_driv(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["driv_lit_off_topic"]),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["repair_type"], "ticker_off_topic")

    def test_ticker_off_topic_local(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["local_off_topic_headline"]),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["repair_type"], "ticker_off_topic")

    def test_ticker_and_family(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["driv_lit_off_topic", "mechanism_family_none"]),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["repair_type"], "ticker_and_family")

    def test_duplicate_only(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["repair_type"], "duplicate_only")

    def test_mechanism_family_with_dup_is_mechanism_family_only(self) -> None:
        # ``mechanism_family_none`` + ``duplicate_date_ticker`` — the
        # primary repair path is still mechanism_family.  The dup flag
        # only lowers priority.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(
            result["candidates"][0]["repair_type"], "mechanism_family_only")


# ---------------------------------------------------------------------------
# Repair priority
# ---------------------------------------------------------------------------


class TestRepairPriority(unittest.TestCase):
    def test_mechanism_family_only_plausible_headline_is_high(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "high")

    def test_mechanism_family_only_short_headline_is_medium(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline=_SHORT_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "medium")

    def test_mechanism_family_only_missing_headline_is_medium(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline=None),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "medium")

    def test_driv_only_plausible_headline_is_high(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["driv_lit_off_topic"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "high")

    def test_driv_only_short_headline_is_medium(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["driv_lit_off_topic"],
                    headline=_SHORT_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "medium")

    def test_local_off_topic_is_low(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["local_off_topic_headline"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "low")

    def test_dup_with_mechanism_family_is_low(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "low")

    def test_dup_only_is_low(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["duplicate_date_ticker"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "low")

    def test_driv_plus_family_is_low(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["driv_lit_off_topic", "mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        self.assertEqual(result["candidates"][0]["repair_priority"], "low")


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder(unittest.TestCase):
    def test_high_before_medium_before_low(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                # low: dup + family
                _contamination_example(
                    event_id=3000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"],
                    headline=_PLAUSIBLE_HEADLINE),
                # medium: family + short headline
                _contamination_example(
                    event_id=2000,
                    flags=["mechanism_family_none"],
                    headline=_SHORT_HEADLINE),
                # high: family + plausible headline
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        priorities = [c["repair_priority"] for c in result["candidates"]]
        self.assertEqual(priorities, ["high", "medium", "low"])

    def test_within_priority_ties_break_by_event_id_asc(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1003, flags=["mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE),
                _contamination_example(
                    event_id=1001, flags=["mechanism_family_none"],
                    headline="Apple Inc announces share buyback program"),
                _contamination_example(
                    event_id=1002, flags=["mechanism_family_none"],
                    headline="Microsoft Corp posts record quarterly earnings"),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1001, 1002, 1003])


# ---------------------------------------------------------------------------
# Limit truncation
# ---------------------------------------------------------------------------


class TestLimitTruncation(unittest.TestCase):
    def test_limit_truncates_candidates_only(self) -> None:
        examples = [
            _contamination_example(
                event_id=1000 + i,
                flags=["mechanism_family_none"],
                headline=_PLAUSIBLE_HEADLINE)
            for i in range(10)
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=3)
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["total_candidates_after_filter"], 10)

    def test_zero_limit_emits_no_candidates_but_keeps_count(self) -> None:
        examples = [
            _contamination_example(
                event_id=1000 + i, flags=["mechanism_family_none"])
            for i in range(5)
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=0)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["total_candidates_after_filter"], 5)

    def test_negative_limit_clamps_to_zero(self) -> None:
        examples = [
            _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=-5)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["total_candidates_after_filter"], 1)


# ---------------------------------------------------------------------------
# Aggregate counts
# ---------------------------------------------------------------------------


class TestAggregateCounts(unittest.TestCase):
    def test_total_short_ready_from_readiness(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ], total_short_ready=42),
            readiness=_readiness_payload(
                events_ready_1d5d=99, delta_vs_full_ready=17),
        )
        # Readiness wins when both are present.
        self.assertEqual(result["total_short_ready"], 99)
        self.assertEqual(result["delta_vs_full_ready"], 17)

    def test_total_short_ready_falls_back_to_contamination(self) -> None:
        # Readiness payload missing ``events_ready_1d5d`` — packet
        # should fall back to the contamination report's
        # ``total_short_ready``.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ], total_short_ready=42),
            readiness={"recommended_next_action": "synthetic"},
        )
        self.assertEqual(result["total_short_ready"], 42)

    def test_total_short_ready_defaults_to_zero(self) -> None:
        result = _run(
            contamination={"examples": [], "ok": True},
            readiness={"recommended_next_action": "synthetic"},
        )
        self.assertEqual(result["total_short_ready"], 0)
        self.assertEqual(result["delta_vs_full_ready"], 0)

    def test_total_after_filter_equals_eligible_rows(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
                _contamination_example(event_id=4,    flags=["mechanism_family_none"]),  # reviewed
                _contamination_example(event_id=1002, flags=["driv_lit_off_topic"]),
            ]),
        )
        # 4 dropped by reviewed-id exclusion; 1000 + 1002 remain.
        self.assertEqual(result["total_candidates_after_filter"], 2)


# ---------------------------------------------------------------------------
# Export summary
# ---------------------------------------------------------------------------


_EXPORT_SUMMARY_KEYS = (
    "candidate_count",
    "reviewed_exclusion_set_count",
    "top_candidates",
)


_TOP_CANDIDATE_KEYS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "repair_type",
    "repair_priority",
)


class TestExportSummary(unittest.TestCase):
    def test_export_summary_present(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertIn("export_summary", result)

    def test_export_summary_keys(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(
            set(result["export_summary"].keys()), set(_EXPORT_SUMMARY_KEYS),
            f"unexpected export_summary keys: "
            f"{set(result['export_summary'].keys())!r}",
        )

    def test_candidate_count_matches_candidates_len(self) -> None:
        examples = [
            _contamination_example(
                event_id=1000 + i,
                flags=["mechanism_family_none"],
                headline=_PLAUSIBLE_HEADLINE)
            for i in range(7)
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=4)
        # candidate_count reflects the post-limit list, NOT the
        # pre-limit total (that's total_candidates_after_filter).
        self.assertEqual(result["export_summary"]["candidate_count"], 4)
        self.assertEqual(result["total_candidates_after_filter"], 7)
        self.assertEqual(
            result["export_summary"]["candidate_count"],
            len(result["candidates"]),
        )

    def test_reviewed_exclusion_set_count_is_24(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(
            result["export_summary"]["reviewed_exclusion_set_count"], 24)

    def test_top_candidates_length_matches_candidates(self) -> None:
        examples = [
            _contamination_example(
                event_id=1000 + i, flags=["mechanism_family_none"],
                headline=_PLAUSIBLE_HEADLINE)
            for i in range(5)
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=3)
        self.assertEqual(len(result["export_summary"]["top_candidates"]), 3)

    def test_top_candidate_entries_have_pinned_keys(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE,
                    primary_ticker="BAC", event_date="2026-04-01"),
            ]),
        )
        entry = result["export_summary"]["top_candidates"][0]
        self.assertEqual(set(entry.keys()), set(_TOP_CANDIDATE_KEYS),
                         f"unexpected top_candidate keys: {entry.keys()!r}")

    def test_top_candidates_carry_headline_and_ticker_for_review(self) -> None:
        # Operator review hinges on the ``headline`` + ticker pair —
        # both must round-trip through the export summary intact so
        # review tooling can quote them without re-reading the
        # ``candidates`` list.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    headline="Apple Inc reports earnings beat",
                    primary_ticker="AAPL", event_date="2026-04-15"),
            ]),
        )
        entry = result["export_summary"]["top_candidates"][0]
        self.assertEqual(entry["event_id"], 1000)
        self.assertEqual(entry["headline"], "Apple Inc reports earnings beat")
        self.assertEqual(entry["current_primary_ticker"], "AAPL")
        self.assertEqual(entry["event_date"], "2026-04-15")
        self.assertEqual(entry["repair_type"], "mechanism_family_only")
        self.assertEqual(entry["repair_priority"], "high")

    def test_top_candidates_preserve_sort_order(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                # low: dup + family
                _contamination_example(
                    event_id=3000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"],
                    headline=_PLAUSIBLE_HEADLINE),
                # medium: family + short headline
                _contamination_example(
                    event_id=2000,
                    flags=["mechanism_family_none"],
                    headline=_SHORT_HEADLINE),
                # high: family + plausible headline
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        ids_in_candidates = [c["event_id"] for c in result["candidates"]]
        ids_in_summary = [
            t["event_id"] for t in result["export_summary"]["top_candidates"]
        ]
        self.assertEqual(ids_in_candidates, ids_in_summary)

    def test_empty_packet_export_summary_is_well_formed(self) -> None:
        result = _run(contamination=_contamination_payload([]))
        summary = result["export_summary"]
        self.assertEqual(summary["candidate_count"], 0)
        self.assertEqual(summary["reviewed_exclusion_set_count"], 24)
        self.assertEqual(summary["top_candidates"], [])

    def test_top_candidates_carry_through_none_headline(self) -> None:
        # A missing headline still surfaces as ``None`` (not omitted)
        # so review tooling can detect the gap explicitly rather than
        # treating an absent key as "no data".
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    headline=None),
            ]),
        )
        entry = result["export_summary"]["top_candidates"][0]
        self.assertIsNone(entry["headline"])


# ---------------------------------------------------------------------------
# Recommended next action
# ---------------------------------------------------------------------------


class TestRecommendedAction(unittest.TestCase):
    def test_recommended_action_avoids_banned_words(self) -> None:
        for examples in (
            [],
            [_contamination_example(event_id=1000, flags=["mechanism_family_none"])],
            [_contamination_example(event_id=1000, flags=["driv_lit_off_topic"])],
            [_contamination_example(event_id=1000, flags=["local_off_topic_headline"])],
        ):
            result = _run(contamination=_contamination_payload(examples))
            rec = result["recommended_next_action"].lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(
                    w, rec,
                    f"banned word {w!r} in: {rec!r}")

    def test_recommended_action_mentions_manual_review(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertIn("manual review",
                      result["recommended_next_action"].lower())

    def test_recommended_action_mentions_not_proof(self) -> None:
        # Conservative wording: explicitly disclaim that surfaced rows
        # are "manual review candidates," "not proof" of repairability.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertIn("not proof",
                      result["recommended_next_action"].lower())

    def test_empty_packet_recommendation_is_conservative(self) -> None:
        result = _run(contamination=_contamination_payload([]))
        rec = result["recommended_next_action"].lower()
        # Empty case must still avoid banned words and not be empty.
        self.assertGreater(len(rec.strip()), 0)
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec)


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_readiness_seam_exists(self) -> None:
        self.assertTrue(callable(
            getattr(cli, "_run_short_horizon_readiness_report")))

    def test_contamination_seam_exists(self) -> None:
        self.assertTrue(callable(
            getattr(cli, "_run_short_horizon_contamination_report")))

    def test_both_seams_called_with_db_path(self) -> None:
        captured: dict = {"readiness": None, "contamination": None}

        def fake_readiness(*, db_path):
            captured["readiness"] = db_path
            return _readiness_payload()

        def fake_contamination(*, db_path):
            captured["contamination"] = db_path
            return _contamination_payload([])

        with patch.object(
            cli, "_run_short_horizon_readiness_report",
            side_effect=fake_readiness,
        ), patch.object(
            cli, "_run_short_horizon_contamination_report",
            side_effect=fake_contamination,
        ):
            cli.summarize_short_horizon_repair_packet(
                db_path="/sentinel/path.db")
        self.assertEqual(captured["readiness"],    "/sentinel/path.db")
        self.assertEqual(captured["contamination"], "/sentinel/path.db")


# ---------------------------------------------------------------------------
# CSV format
# ---------------------------------------------------------------------------


class TestCSVRendering(unittest.TestCase):
    def test_csv_header_matches_packet_keys_in_order(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        self.assertEqual(tuple(header), _PACKET_KEYS)

    def test_csv_flags_pipe_separated(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(output))
        next(reader)
        first_row = next(reader)
        flags_idx = _PACKET_KEYS.index("flags")
        self.assertEqual(
            first_row[flags_idx],
            "mechanism_family_none|duplicate_date_ticker",
        )

    def test_csv_blank_fields_are_empty_strings(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        reader = csv.reader(io.StringIO(output))
        next(reader)
        row = next(reader)
        for k in _BLANK_KEYS:
            self.assertEqual(row[_PACKET_KEYS.index(k)], "")

    def test_csv_uses_lf_line_terminator(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertNotIn("\r\r", output)
        self.assertNotIn("\r\n", output)

    def test_csv_quotes_headlines_with_commas(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline="Apple, Inc. announces buyback"),
            ]),
        )
        reader = csv.reader(io.StringIO(output))
        next(reader)
        row = next(reader)
        self.assertEqual(
            row[_PACKET_KEYS.index("headline")],
            "Apple, Inc. announces buyback",
        )

    def test_csv_repair_type_and_priority_emitted(self) -> None:
        rc, output = _run_cli(
            ["--csv"],
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE),
            ]),
        )
        reader = csv.reader(io.StringIO(output))
        next(reader)
        row = next(reader)
        self.assertEqual(
            row[_PACKET_KEYS.index("repair_type")], "mechanism_family_only")
        self.assertEqual(
            row[_PACKET_KEYS.index("repair_priority")], "high")


# ---------------------------------------------------------------------------
# JSON CLI
# ---------------------------------------------------------------------------


class TestJSONRendering(unittest.TestCase):
    def test_json_payload_has_candidates_list(self) -> None:
        rc, output = _run_cli(
            ["--json", "--limit", "20"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertIn("candidates", parsed)
        self.assertEqual(parsed["candidates"][0]["event_id"], 1000)
        for k in _PACKET_KEYS:
            self.assertIn(k, parsed["candidates"][0])

    def test_json_top_level_keys_present(self) -> None:
        rc, output = _run_cli(
            ["--json"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
            readiness=_readiness_payload(
                events_ready_1d5d=10, delta_vs_full_ready=3),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for top_key in (
            "ok",
            "excluded_reviewed_event_ids",
            "reviewed_exclusion_set_count",
            "excluded_reviewed_count",
            "total_short_ready",
            "delta_vs_full_ready",
            "total_candidates_after_filter",
            "candidates",
            "export_summary",
            "recommended_next_action",
        ):
            self.assertIn(top_key, parsed)

    def test_json_export_summary_round_trips(self) -> None:
        rc, output = _run_cli(
            ["--json"],
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000, flags=["mechanism_family_none"],
                    headline=_PLAUSIBLE_HEADLINE, primary_ticker="BAC"),
            ]),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        summary = parsed["export_summary"]
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["reviewed_exclusion_set_count"], 24)
        self.assertEqual(len(summary["top_candidates"]), 1)
        top = summary["top_candidates"][0]
        self.assertEqual(top["event_id"], 1000)
        self.assertEqual(top["headline"], _PLAUSIBLE_HEADLINE)
        self.assertEqual(top["current_primary_ticker"], "BAC")

    def test_csv_and_json_mutually_exclusive(self) -> None:
        rc, _ = _run_cli(
            ["--json", "--csv"],
            contamination=_contamination_payload([]),
        )
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# Read-only / import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
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
        with patch.object(
            cli, "_run_short_horizon_readiness_report",
            return_value=_readiness_payload(),
        ), patch.object(
            cli, "_run_short_horizon_contamination_report",
            return_value=_contamination_payload([]),
        ):
            cli.summarize_short_horizon_repair_packet()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_text_mode_default_does_not_raise(self) -> None:
        rc, output = _run_cli(
            [],
            contamination=_contamination_payload([
                _contamination_example(event_id=1000, flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(rc, 0)
        lower = output.lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, lower,
                             f"text rendering used banned word {w!r}")

    def test_text_mode_empty_packet_does_not_raise(self) -> None:
        rc, output = _run_cli(
            [], contamination=_contamination_payload([]),
        )
        self.assertEqual(rc, 0)
        self.assertGreater(len(output.strip()), 0)


if __name__ == "__main__":
    unittest.main()
