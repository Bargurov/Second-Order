"""Tests for ``scripts/short_horizon_review_worksheet.py``.

The worksheet is a thin operator-facing view over the existing
``short_horizon_review_queue`` output: it surfaces the same review
rows the queue already classifies, then layers blank operator-input
columns that an operator hand-fills to expand the next short-horizon
validation cohort beyond the current 5 repaired events.

Pin the contract:

* Read-only — wraps ``run_short_horizon_review_queue`` through a
  single patchable seam so tests never invoke the real archive
  scripts.
* Never assigns / proposes tickers or mechanism families; the
  ``proposed_*`` / ``predicted_direction`` / ``include_*`` /
  ``exclude_reason`` / ``operator_notes`` columns are emitted as
  empty strings.
* Per-row schema (16 worksheet columns)::

      event_id, headline, event_date,
      current_primary_ticker, current_mechanism_family,
      repair_type, repair_priority,
      operator_decision_needed, reason_for_review,
      proposed_primary_ticker, proposed_benchmark_ticker,
      proposed_mechanism_family, predicted_direction,
      include_in_short_horizon_validation, exclude_reason,
      operator_notes

* Envelope schema::

      ok, worksheet_count, total_review_queue_count,
      high_priority_count, medium_priority_count, low_priority_count,
      worksheet, excluded_or_deferred, recommended_next_action

* Top rows prioritise high-priority candidates first (the upstream
  review_queue already sorts by ``(priority_rank, event_id)`` — the
  worksheet inherits that order and truncates at --limit).
* Default ``--limit`` is 10.
* JSON by default, CSV when ``--csv`` is passed.
* Conservative wording — banned tokens: ``proof``, ``proves``,
  ``validated``, ``alpha``, ``guaranteed``.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_worksheet as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "worksheet_count",
    "total_review_queue_count",
    "high_priority_count",
    "medium_priority_count",
    "low_priority_count",
    "worksheet",
    "excluded_or_deferred",
    "recommended_next_action",
)


_REQUIRED_ROW_FIELDS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


_BLANK_OPERATOR_FIELDS = (
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# ---------------------------------------------------------------------------
# Synthetic review-queue payload — mirrors the shape returned by
# ``run_short_horizon_review_queue``.  Tests patch the seam to inject
# this without invoking the real review queue.
# ---------------------------------------------------------------------------


def _queue_row(
    *, event_id: int,
    repair_priority: str = "medium",
    repair_type: str = "needs_review",
    operator_decision_needed: str = "review_headline_for_relevance",
    reason_for_review: str = "flags: ; repair_type=needs_review",
    headline: str = "h",
    event_date: str = "2026-04-10",
    current_primary_ticker: str | None = "AAPL",
    current_mechanism_family: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    current_primary_ticker,
        "current_mechanism_family":  current_mechanism_family,
        "repair_type":               repair_type,
        "repair_priority":           repair_priority,
        "operator_decision_needed":  operator_decision_needed,
        "reason_for_review":         reason_for_review,
    }


def _queue_payload(
    *, review_queue: list[dict[str, Any]] | None = None,
    excluded_or_deferred: list[dict[str, Any]] | None = None,
    high: int | None = None,
    medium: int | None = None,
    low: int | None = None,
) -> dict[str, Any]:
    rows = list(review_queue or [])
    excluded = list(excluded_or_deferred or [])
    if high is None:
        high = sum(1 for r in rows if r.get("repair_priority") == "high")
    if medium is None:
        medium = sum(1 for r in rows if r.get("repair_priority") == "medium")
    if low is None:
        low = sum(1 for r in rows if r.get("repair_priority") == "low")
    return {
        "ok":                       True,
        "candidate_count":          len(rows),
        "high_priority_count":      high,
        "medium_priority_count":    medium,
        "low_priority_count":       low,
        "review_queue":             rows,
        "excluded_or_deferred":     excluded,
        "recommended_next_action":  "n candidate(s) queued for operator review",
    }


def _patch_queue(payload: dict[str, Any]):
    return patch.object(cli, "_run_short_horizon_review_queue",
                        return_value=payload)


# ---------------------------------------------------------------------------
# Envelope contract
# ---------------------------------------------------------------------------


class TestEnvelopeContract(unittest.TestCase):
    def test_envelope_has_required_keys(self) -> None:
        with _patch_queue(_queue_payload()):
            report = cli.build_short_horizon_review_worksheet()
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing envelope key: {k}")
        self.assertIs(report["ok"], True)


# ---------------------------------------------------------------------------
# Row schema
# ---------------------------------------------------------------------------


class TestRowSchema(unittest.TestCase):
    def test_row_carries_all_sixteen_worksheet_fields(self) -> None:
        row = _queue_row(
            event_id=1234, repair_priority="high",
            repair_type="ticker_off_topic",
            operator_decision_needed="supply_primary_ticker",
            reason_for_review="flags: driv_lit_off_topic",
        )
        with _patch_queue(_queue_payload(review_queue=[row])):
            report = cli.build_short_horizon_review_worksheet()
        self.assertEqual(len(report["worksheet"]), 1)
        worksheet_row = report["worksheet"][0]
        for f in _REQUIRED_ROW_FIELDS:
            self.assertIn(f, worksheet_row, f"missing worksheet field: {f}")

    def test_row_field_count_is_exactly_sixteen(self) -> None:
        with _patch_queue(_queue_payload(review_queue=[_queue_row(event_id=1)])):
            report = cli.build_short_horizon_review_worksheet()
        worksheet_row = report["worksheet"][0]
        self.assertEqual(
            set(worksheet_row.keys()), set(_REQUIRED_ROW_FIELDS),
            "worksheet row must carry exactly the 16 declared fields"
        )


# ---------------------------------------------------------------------------
# Blank operator-input columns
# ---------------------------------------------------------------------------


class TestBlankOperatorFields(unittest.TestCase):
    def test_operator_fields_are_blank_strings(self) -> None:
        row = _queue_row(event_id=1, repair_priority="high")
        with _patch_queue(_queue_payload(review_queue=[row])):
            worksheet_row = (
                cli.build_short_horizon_review_worksheet()["worksheet"][0]
            )
        for key in _BLANK_OPERATOR_FIELDS:
            self.assertEqual(
                worksheet_row[key], "",
                f"{key} must be empty string for operator hand-fill"
            )

    def test_blank_fields_remain_blank_across_priorities(self) -> None:
        rows = [
            _queue_row(event_id=1, repair_priority="high"),
            _queue_row(event_id=2, repair_priority="medium"),
            _queue_row(event_id=3, repair_priority="low"),
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet()
        for worksheet_row in report["worksheet"]:
            for key in _BLANK_OPERATOR_FIELDS:
                self.assertEqual(worksheet_row[key], "")


# ---------------------------------------------------------------------------
# Filled fields come from upstream review queue
# ---------------------------------------------------------------------------


class TestFilledFieldsCopiedFromQueue(unittest.TestCase):
    def test_decision_and_reason_propagated_verbatim(self) -> None:
        row = _queue_row(
            event_id=42, repair_priority="high",
            repair_type="ticker_and_family",
            operator_decision_needed="supply_ticker_and_family",
            reason_for_review=(
                "flags: driv_lit_off_topic, mechanism_family_none; "
                "repair_type=ticker_and_family"
            ),
        )
        with _patch_queue(_queue_payload(review_queue=[row])):
            worksheet_row = (
                cli.build_short_horizon_review_worksheet()["worksheet"][0]
            )
        self.assertEqual(worksheet_row["event_id"], 42)
        self.assertEqual(worksheet_row["repair_priority"], "high")
        self.assertEqual(worksheet_row["repair_type"], "ticker_and_family")
        self.assertEqual(worksheet_row["operator_decision_needed"],
                         "supply_ticker_and_family")
        self.assertIn("driv_lit_off_topic",
                      worksheet_row["reason_for_review"])


# ---------------------------------------------------------------------------
# Sort: high priority first (inherited from upstream queue order)
# ---------------------------------------------------------------------------


class TestPriorityOrdering(unittest.TestCase):
    def test_high_priority_rows_come_first(self) -> None:
        # Upstream review queue already sorts by (priority_rank,
        # event_id) ascending — the worksheet must preserve that order.
        rows = [
            _queue_row(event_id=10, repair_priority="high"),
            _queue_row(event_id=11, repair_priority="medium"),
            _queue_row(event_id=12, repair_priority="low"),
            _queue_row(event_id=13, repair_priority="high"),
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            worksheet = (
                cli.build_short_horizon_review_worksheet()["worksheet"]
            )
        priorities = [r["repair_priority"] for r in worksheet]
        # High priority entries must precede medium/low entries.
        seen_lower = False
        for p in priorities:
            if p in ("medium", "low"):
                seen_lower = True
            elif p == "high" and seen_lower:
                self.fail(
                    f"high-priority row appeared after a lower-priority row: "
                    f"{priorities}"
                )


# ---------------------------------------------------------------------------
# --limit truncation
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_default_limit_is_ten(self) -> None:
        rows = [
            _queue_row(event_id=i, repair_priority="medium")
            for i in range(1, 21)
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet()
        self.assertEqual(len(report["worksheet"]), 10)
        self.assertEqual(report["worksheet_count"], 10)
        # Aggregate counts still reflect the full review-queue cohort.
        self.assertEqual(report["total_review_queue_count"], 20)
        self.assertEqual(report["medium_priority_count"], 20)

    def test_explicit_limit_truncates(self) -> None:
        rows = [_queue_row(event_id=i) for i in range(1, 11)]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(limit=3)
        self.assertEqual(len(report["worksheet"]), 3)
        self.assertEqual(report["worksheet_count"], 3)
        self.assertEqual(report["total_review_queue_count"], 10)

    def test_limit_zero_yields_empty_worksheet_but_keeps_counts(self) -> None:
        rows = [_queue_row(event_id=i) for i in range(1, 4)]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(limit=0)
        self.assertEqual(report["worksheet"], [])
        self.assertEqual(report["worksheet_count"], 0)
        self.assertEqual(report["total_review_queue_count"], 3)


# ---------------------------------------------------------------------------
# --offset paging
# ---------------------------------------------------------------------------


class TestOffset(unittest.TestCase):
    def test_offset_zero_matches_top_limit_behaviour(self) -> None:
        rows = [
            _queue_row(event_id=i, repair_priority="medium")
            for i in range(1, 21)
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            baseline = cli.build_short_horizon_review_worksheet(
                limit=10,
            )
            offset0 = cli.build_short_horizon_review_worksheet(
                limit=10, offset=0,
            )
        self.assertEqual(baseline["worksheet"], offset0["worksheet"])
        self.assertEqual(
            [r["event_id"] for r in offset0["worksheet"]],
            list(range(1, 11)),
        )

    def test_offset_pages_next_batch(self) -> None:
        rows = [
            _queue_row(event_id=i, repair_priority="medium")
            for i in range(1, 21)
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=10, offset=10,
            )
        self.assertEqual(report["worksheet_count"], 10)
        self.assertEqual(
            [r["event_id"] for r in report["worksheet"]],
            list(range(11, 21)),
        )
        # Aggregate counts are unaffected by offset.
        self.assertEqual(report["total_review_queue_count"], 20)
        self.assertEqual(report["medium_priority_count"], 20)

    def test_offset_beyond_end_yields_empty_worksheet(self) -> None:
        rows = [_queue_row(event_id=i) for i in range(1, 6)]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=10, offset=100,
            )
        self.assertEqual(report["worksheet"], [])
        self.assertEqual(report["worksheet_count"], 0)
        # The full upstream cohort is still surfaced via the count.
        self.assertEqual(report["total_review_queue_count"], 5)

    def test_offset_respects_priority_sort(self) -> None:
        # Sort is (priority_rank, event_id asc) — offset must skip the
        # first N rows of that sorted order, not the raw input order.
        rows = [
            _queue_row(event_id=20, repair_priority="low"),
            _queue_row(event_id=10, repair_priority="high"),
            _queue_row(event_id=15, repair_priority="medium"),
            _queue_row(event_id=11, repair_priority="high"),
        ]
        # Sorted order: [10 (high), 11 (high), 15 (medium), 20 (low)].
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=2, offset=2,
            )
        self.assertEqual(
            [r["event_id"] for r in report["worksheet"]],
            [15, 20],
        )

    def test_envelope_carries_limit_and_offset(self) -> None:
        rows = [_queue_row(event_id=i) for i in range(1, 6)]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=2, offset=3,
            )
        self.assertEqual(report["limit"], 2)
        self.assertEqual(report["offset"], 3)

    def test_negative_offset_is_clamped_to_zero(self) -> None:
        rows = [
            _queue_row(event_id=i, repair_priority="medium")
            for i in range(1, 6)
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=3, offset=-7,
            )
        self.assertEqual(
            [r["event_id"] for r in report["worksheet"]],
            [1, 2, 3],
        )
        self.assertEqual(report["offset"], 0)

    def test_offset_keeps_operator_columns_blank(self) -> None:
        rows = [_queue_row(event_id=i) for i in range(1, 6)]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=2, offset=2,
            )
        for worksheet_row in report["worksheet"]:
            for key in _BLANK_OPERATOR_FIELDS:
                self.assertEqual(worksheet_row[key], "")


# ---------------------------------------------------------------------------
# CLI offset paging
# ---------------------------------------------------------------------------


class TestCliOffset(unittest.TestCase):
    def test_cli_offset_pages_json(self) -> None:
        rows = [
            _queue_row(event_id=i, repair_priority="medium")
            for i in range(1, 21)
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            out = io.StringIO()
            rc = cli.main(["--json", "--limit", "10", "--offset", "10"], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["limit"], 10)
        self.assertEqual(parsed["offset"], 10)
        self.assertEqual(
            [r["event_id"] for r in parsed["worksheet"]],
            list(range(11, 21)),
        )

    def test_cli_csv_carries_only_offset_batch(self) -> None:
        rows = [
            _queue_row(event_id=i, repair_priority="medium")
            for i in range(1, 21)
        ]
        with _patch_queue(_queue_payload(review_queue=rows)):
            out = io.StringIO()
            rc = cli.main(["--csv", "--limit", "10", "--offset", "10"], out=out)
        self.assertEqual(rc, 0)
        reader = csv.DictReader(io.StringIO(out.getvalue()))
        csv_rows = list(reader)
        self.assertEqual(len(csv_rows), 10)
        self.assertEqual(
            [int(r["event_id"]) for r in csv_rows],
            list(range(11, 21)),
        )


# ---------------------------------------------------------------------------
# Final batch — operator's "remaining candidates after top10 and next10"
# scenario.  Pins the partial-tail slice behaviour: a 28-row queue paged
# with ``--limit 10 --offset 20`` returns 8 rows (event_ids 21-28 in the
# sorted order), with aggregate counts still reporting the full cohort.
# ---------------------------------------------------------------------------


def _twenty_eight_row_queue() -> list[dict[str, Any]]:
    """28 rows split across high / medium / low so the worksheet's
    defensive sort exercises end-to-end.  After sort by
    ``(priority_rank, event_id)`` ascending the queue is event_ids
    1..28 in order, so ``offset=20`` lands on event_id 21.
    """
    rows: list[dict[str, Any]] = []
    for i in range(1, 6):       # high  : event_ids 1-5   (5 rows)
        rows.append(_queue_row(event_id=i, repair_priority="high"))
    for i in range(6, 26):      # medium: event_ids 6-25  (20 rows)
        rows.append(_queue_row(event_id=i, repair_priority="medium"))
    for i in range(26, 29):     # low   : event_ids 26-28 (3 rows)
        rows.append(_queue_row(event_id=i, repair_priority="low"))
    return rows


class TestFinalBatchPaging(unittest.TestCase):
    def test_offset_20_limit_10_against_28_rows_yields_remaining_8(
        self,
    ) -> None:
        rows = _twenty_eight_row_queue()
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=10, offset=20,
            )
        # Slice semantics: only 8 rows remain after offset 20 even
        # though --limit is 10.  worksheet_count must reflect the
        # partial tail, not the requested limit.
        self.assertEqual(report["worksheet_count"], 8)
        self.assertEqual(len(report["worksheet"]),  8)
        self.assertEqual(report["total_review_queue_count"], 28)
        # Aggregate priority counts always reflect the full upstream
        # cohort, never the windowed batch.
        self.assertEqual(report["high_priority_count"],   5)
        self.assertEqual(report["medium_priority_count"], 20)
        self.assertEqual(report["low_priority_count"],    3)

    def test_offset_20_limit_10_returns_event_ids_21_through_28(
        self,
    ) -> None:
        # Sorted order: high (1-5), then medium (6-25), then low
        # (26-28).  Slice [20:30] of that 28-row list is event_ids
        # 21..28.
        rows = _twenty_eight_row_queue()
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=10, offset=20,
            )
        self.assertEqual(
            [r["event_id"] for r in report["worksheet"]],
            list(range(21, 29)),
        )

    def test_cli_final_batch_json_envelope_counts(self) -> None:
        rows = _twenty_eight_row_queue()
        with _patch_queue(_queue_payload(review_queue=rows)):
            out = io.StringIO()
            rc = cli.main(
                ["--json", "--limit", "10", "--offset", "20"], out=out,
            )
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["worksheet_count"], 8)
        self.assertEqual(parsed["total_review_queue_count"], 28)
        self.assertEqual(parsed["limit"],  10)
        self.assertEqual(parsed["offset"], 20)
        self.assertEqual(
            [r["event_id"] for r in parsed["worksheet"]],
            list(range(21, 29)),
        )

    def test_cli_final_batch_csv_carries_only_remaining_rows(self) -> None:
        rows = _twenty_eight_row_queue()
        with _patch_queue(_queue_payload(review_queue=rows)):
            out = io.StringIO()
            rc = cli.main(
                ["--csv", "--limit", "10", "--offset", "20"], out=out,
            )
        self.assertEqual(rc, 0)
        reader = csv.DictReader(io.StringIO(out.getvalue()))
        csv_rows = list(reader)
        self.assertEqual(len(csv_rows), 8)
        self.assertEqual(
            [int(r["event_id"]) for r in csv_rows],
            list(range(21, 29)),
        )

    def test_final_batch_operator_columns_remain_blank(self) -> None:
        rows = _twenty_eight_row_queue()
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet(
                limit=10, offset=20,
            )
        for r in report["worksheet"]:
            for key in _BLANK_OPERATOR_FIELDS:
                self.assertEqual(
                    r[key], "",
                    f"{key} must remain blank on final-batch rows "
                    "(operator hand-fills these)",
                )


# ---------------------------------------------------------------------------
# Empty cohort
# ---------------------------------------------------------------------------


class TestEmptyCohort(unittest.TestCase):
    def test_empty_queue_yields_zero_counts_and_empty_worksheet(self) -> None:
        with _patch_queue(_queue_payload(review_queue=[])):
            report = cli.build_short_horizon_review_worksheet()
        self.assertEqual(report["worksheet_count"],          0)
        self.assertEqual(report["total_review_queue_count"], 0)
        self.assertEqual(report["high_priority_count"],      0)
        self.assertEqual(report["medium_priority_count"],    0)
        self.assertEqual(report["low_priority_count"],       0)
        self.assertEqual(report["worksheet"],                [])


# ---------------------------------------------------------------------------
# Excluded / deferred propagated with reason
# ---------------------------------------------------------------------------


class TestExcludedOrDeferredPropagation(unittest.TestCase):
    def test_excluded_or_deferred_entries_propagated(self) -> None:
        excluded = [
            {"event_id": 4, "reason": "already manually reviewed"},
            {"event_id": 6, "reason": "already manually reviewed"},
        ]
        with _patch_queue(_queue_payload(excluded_or_deferred=excluded)):
            report = cli.build_short_horizon_review_worksheet()
        self.assertEqual(len(report["excluded_or_deferred"]), 2)
        ids = {e["event_id"] for e in report["excluded_or_deferred"]}
        self.assertEqual(ids, {4, 6})
        for e in report["excluded_or_deferred"]:
            self.assertIn("reason", e)
            self.assertTrue(e["reason"])


# ---------------------------------------------------------------------------
# CSV rendering
# ---------------------------------------------------------------------------


class TestCsvRendering(unittest.TestCase):
    def test_csv_header_matches_sixteen_field_order(self) -> None:
        row = _queue_row(event_id=1, repair_priority="high")
        with _patch_queue(_queue_payload(review_queue=[row])):
            out = io.StringIO()
            rc = cli.main(["--csv", "--limit", "5"], out=out)
        self.assertEqual(rc, 0)
        reader = csv.reader(io.StringIO(out.getvalue()))
        header = next(reader)
        self.assertEqual(tuple(header), _REQUIRED_ROW_FIELDS)

    def test_csv_row_has_blank_cells_for_operator_fields(self) -> None:
        row = _queue_row(
            event_id=1, repair_priority="high",
            operator_decision_needed="supply_primary_ticker",
        )
        with _patch_queue(_queue_payload(review_queue=[row])):
            out = io.StringIO()
            cli.main(["--csv"], out=out)
        reader = csv.DictReader(io.StringIO(out.getvalue()))
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        csv_row = rows[0]
        for key in _BLANK_OPERATOR_FIELDS:
            self.assertEqual(
                csv_row[key], "",
                f"CSV cell for {key} must be empty (got {csv_row[key]!r})"
            )

    def test_csv_uses_lf_line_terminator_not_crlf(self) -> None:
        row = _queue_row(event_id=1, repair_priority="high")
        with _patch_queue(_queue_payload(review_queue=[row])):
            out = io.StringIO()
            cli.main(["--csv"], out=out)
        text = out.getvalue()
        self.assertNotIn("\r\n", text,
                         "CSV must terminate lines with LF, not CRLF")

    def test_csv_none_values_render_as_empty_cells(self) -> None:
        row = _queue_row(
            event_id=1, repair_priority="high",
            current_primary_ticker=None,
            current_mechanism_family=None,
        )
        with _patch_queue(_queue_payload(review_queue=[row])):
            out = io.StringIO()
            cli.main(["--csv"], out=out)
        reader = csv.DictReader(io.StringIO(out.getvalue()))
        csv_row = list(reader)[0]
        self.assertEqual(csv_row["current_primary_ticker"], "")
        self.assertEqual(csv_row["current_mechanism_family"], "")


# ---------------------------------------------------------------------------
# JSON CLI is the default and parses cleanly
# ---------------------------------------------------------------------------


class TestJsonCli(unittest.TestCase):
    def test_default_invocation_emits_parseable_json(self) -> None:
        row = _queue_row(event_id=1, repair_priority="high")
        with _patch_queue(_queue_payload(review_queue=[row])):
            out = io.StringIO()
            rc = cli.main([], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(len(parsed["worksheet"]), 1)

    def test_explicit_json_flag_emits_parseable_json(self) -> None:
        row = _queue_row(event_id=1, repair_priority="high")
        with _patch_queue(_queue_payload(review_queue=[row])):
            out = io.StringIO()
            rc = cli.main(["--json", "--limit", "5"], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertIn("worksheet", parsed)


# ---------------------------------------------------------------------------
# Conservative wording — no proof/alpha/validated claims
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    _FORBIDDEN = ("proof", "proves", "validated", "alpha", "guaranteed")

    def test_json_output_avoids_forbidden_terms(self) -> None:
        row = _queue_row(
            event_id=1, repair_priority="high",
            operator_decision_needed="supply_primary_ticker",
        )
        with _patch_queue(_queue_payload(review_queue=[row])):
            out = io.StringIO()
            cli.main([], out=out)
        text = out.getvalue().lower()
        for term in self._FORBIDDEN:
            self.assertNotIn(
                term, text,
                f"forbidden term {term!r} in worksheet text"
            )

    def test_recommended_next_action_avoids_forbidden_terms(self) -> None:
        rows = [_queue_row(event_id=i) for i in range(1, 4)]
        with _patch_queue(_queue_payload(review_queue=rows)):
            report = cli.build_short_horizon_review_worksheet()
        action = (report.get("recommended_next_action") or "").lower()
        for term in self._FORBIDDEN:
            self.assertNotIn(term, action)


# ---------------------------------------------------------------------------
# Read-only / no provider imports
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_module_does_not_pull_provider_or_fastapi(self) -> None:
        # Under full test discovery, earlier tests may have already
        # imported fastapi/yfinance/etc.  We only want to know whether
        # importing the worksheet module *itself* pulls those in, so
        # snapshot sys.modules first, then reload and diff.
        import importlib

        before = set(sys.modules.keys())
        sys.modules.pop("scripts.short_horizon_review_worksheet", None)
        importlib.import_module("scripts.short_horizon_review_worksheet")
        newly_loaded = set(sys.modules.keys()) - before
        leaked = {
            k for k in newly_loaded
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        self.assertEqual(leaked, set(),
                         f"unexpected provider/fastapi imports: {leaked}")


if __name__ == "__main__":
    unittest.main()
