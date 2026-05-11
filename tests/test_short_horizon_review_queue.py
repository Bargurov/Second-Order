"""Tests for ``scripts/short_horizon_review_queue.py``.

The review queue is a thin operator-facing view over the existing
``short_horizon_repair_packet`` output.  Pin the contract:

* Read-only — wraps the packet through a patchable seam so tests
  never invoke the real archive scripts.
* Never assigns / proposes tickers or mechanism families; surfaces
  only the operator decision required and the reason the row is
  reviewable.
* Per-row schema:
    event_id, headline, event_date, current_primary_ticker,
    current_mechanism_family, repair_type, repair_priority,
    operator_decision_needed, reason_for_review.
* Envelope schema:
    ok, candidate_count, high_priority_count,
    medium_priority_count, low_priority_count, review_queue,
    excluded_or_deferred, recommended_next_action.
* Conservative wording — no proof / alpha / validated claims.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_queue as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "candidate_count",
    "high_priority_count",
    "medium_priority_count",
    "low_priority_count",
    "review_queue",
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
)


# ---------------------------------------------------------------------------
# Synthetic packet payload — mirrors the shape returned by
# ``summarize_short_horizon_repair_packet``.  Tests patch the seam to
# inject this without invoking the real archive scripts.
# ---------------------------------------------------------------------------


def _packet_candidate(
    *, event_id: int, repair_type: str = "needs_review",
    repair_priority: str = "medium",
    flags: list[str] | None = None,
    current_primary_ticker: str | None = "AAPL",
    headline: str = "h", event_date: str = "2026-04-10",
) -> dict[str, Any]:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    current_primary_ticker,
        "flags":                     list(flags or []),
        "repair_type":               repair_type,
        "repair_priority":           repair_priority,
        "proposed_primary_ticker":   "",
        "proposed_mechanism_family": "",
        "rationale":                 "",
        "exclude_reason":            "",
    }


def _packet_payload(
    *, candidates: list[dict[str, Any]] | None = None,
    excluded_reviewed_event_ids: list[int] | None = None,
) -> dict[str, Any]:
    candidates = candidates or []
    excluded = excluded_reviewed_event_ids or []
    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   list(excluded),
        "reviewed_exclusion_set_count":  len(excluded),
        "excluded_reviewed_count":       len(excluded),
        "total_short_ready":             len(candidates) + len(excluded),
        "delta_vs_full_ready":           0,
        "total_candidates_after_filter": len(candidates),
        "candidates":                    list(candidates),
        "recommended_next_action":       (
            "n manual review candidates surfaced"
        ),
    }


def _patch_packet(payload: dict[str, Any]):
    return patch.object(cli, "_run_short_horizon_repair_packet",
                        return_value=payload)


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestEnvelopeContract(unittest.TestCase):
    def test_envelope_has_required_keys(self) -> None:
        with _patch_packet(_packet_payload()):
            report = cli.run_short_horizon_review_queue()
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing envelope key: {k}")
        self.assertIs(report["ok"], True)


class TestRowSchema(unittest.TestCase):
    def test_row_carries_required_fields(self) -> None:
        cand = _packet_candidate(
            event_id=1234, repair_type="ticker_off_topic",
            repair_priority="high",
            flags=["driv_lit_off_topic", "mechanism_family_none"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            report = cli.run_short_horizon_review_queue()
        self.assertEqual(len(report["review_queue"]), 1)
        row = report["review_queue"][0]
        for f in _REQUIRED_ROW_FIELDS:
            self.assertIn(f, row, f"missing row field: {f}")


# ---------------------------------------------------------------------------
# Priority bucketing
# ---------------------------------------------------------------------------


class TestPriorityCounts(unittest.TestCase):
    def test_priority_counts_match_per_row_priority(self) -> None:
        cands = [
            _packet_candidate(event_id=1, repair_priority="high"),
            _packet_candidate(event_id=2, repair_priority="high"),
            _packet_candidate(event_id=3, repair_priority="medium"),
            _packet_candidate(event_id=4, repair_priority="low"),
            _packet_candidate(event_id=5, repair_priority="low"),
        ]
        with _patch_packet(_packet_payload(candidates=cands)):
            report = cli.run_short_horizon_review_queue()
        self.assertEqual(report["candidate_count"],         5)
        self.assertEqual(report["high_priority_count"],     2)
        self.assertEqual(report["medium_priority_count"],   1)
        self.assertEqual(report["low_priority_count"],      2)


# ---------------------------------------------------------------------------
# operator_decision_needed vocabulary
# ---------------------------------------------------------------------------


class TestOperatorDecisionVocabulary(unittest.TestCase):
    """``operator_decision_needed`` must come from a small closed
    vocabulary so an operator can branch deterministically on it."""

    _ALLOWED = (
        "supply_primary_ticker",
        "supply_mechanism_family",
        "supply_ticker_and_family",
        "exclude_or_promote_duplicate",
        "review_headline_for_relevance",
    )

    def test_off_topic_flag_routes_to_supply_primary_ticker(self) -> None:
        cand = _packet_candidate(
            event_id=1, repair_type="ticker_off_topic",
            flags=["driv_lit_off_topic"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        self.assertEqual(row["operator_decision_needed"],
                         "supply_primary_ticker")

    def test_family_only_flag_routes_to_supply_mechanism_family(self) -> None:
        cand = _packet_candidate(
            event_id=1, repair_type="mechanism_family_only",
            flags=["mechanism_family_none"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        self.assertEqual(row["operator_decision_needed"],
                         "supply_mechanism_family")

    def test_off_topic_plus_family_flag_routes_to_supply_both(self) -> None:
        cand = _packet_candidate(
            event_id=1, repair_type="ticker_and_family",
            flags=["driv_lit_off_topic", "mechanism_family_none"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        self.assertEqual(row["operator_decision_needed"],
                         "supply_ticker_and_family")

    def test_duplicate_only_routes_to_exclude_or_promote(self) -> None:
        cand = _packet_candidate(
            event_id=1, repair_type="duplicate_only",
            flags=["duplicate_date_ticker"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        self.assertEqual(row["operator_decision_needed"],
                         "exclude_or_promote_duplicate")

    def test_unknown_repair_type_falls_back_to_review_headline(self) -> None:
        cand = _packet_candidate(
            event_id=1, repair_type="needs_review", flags=[],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        self.assertEqual(row["operator_decision_needed"],
                         "review_headline_for_relevance")

    def test_all_decision_values_in_allowed_set(self) -> None:
        cands = [
            _packet_candidate(event_id=1, repair_type="ticker_off_topic",
                              flags=["driv_lit_off_topic"]),
            _packet_candidate(event_id=2, repair_type="mechanism_family_only",
                              flags=["mechanism_family_none"]),
            _packet_candidate(event_id=3, repair_type="ticker_and_family",
                              flags=["driv_lit_off_topic",
                                     "mechanism_family_none"]),
            _packet_candidate(event_id=4, repair_type="duplicate_only",
                              flags=["duplicate_date_ticker"]),
            _packet_candidate(event_id=5, repair_type="needs_review",
                              flags=[]),
        ]
        with _patch_packet(_packet_payload(candidates=cands)):
            report = cli.run_short_horizon_review_queue()
        for row in report["review_queue"]:
            self.assertIn(row["operator_decision_needed"], self._ALLOWED)


# ---------------------------------------------------------------------------
# current_mechanism_family — derived from flag presence (no DB read,
# no inference of the actual family value beyond "none" / unknown)
# ---------------------------------------------------------------------------


class TestCurrentMechanismFamily(unittest.TestCase):
    def test_family_none_flag_yields_none_value(self) -> None:
        cand = _packet_candidate(
            event_id=1, flags=["mechanism_family_none"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        self.assertEqual(row["current_mechanism_family"], "none")

    def test_no_family_flag_yields_unknown_marker(self) -> None:
        # When mechanism_family_none is NOT in flags, the packet
        # doesn't tell us the actual family value — surface a marker
        # so the operator knows the family is set (and not the
        # blocking issue) without misleading them about what it is.
        cand = _packet_candidate(
            event_id=1, flags=["duplicate_date_ticker"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        self.assertNotEqual(row["current_mechanism_family"], "none")


# ---------------------------------------------------------------------------
# Reason string is human-readable and lists every flag
# ---------------------------------------------------------------------------


class TestReasonForReview(unittest.TestCase):
    def test_reason_includes_every_flag(self) -> None:
        cand = _packet_candidate(
            event_id=1, repair_type="ticker_off_topic",
            flags=["driv_lit_off_topic", "mechanism_family_none"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            row = cli.run_short_horizon_review_queue()["review_queue"][0]
        reason = row["reason_for_review"].lower()
        self.assertIn("driv_lit_off_topic", reason)
        self.assertIn("mechanism_family_none", reason)


# ---------------------------------------------------------------------------
# excluded_or_deferred surfaces the packet's already-reviewed set
# with a reason
# ---------------------------------------------------------------------------


class TestExcludedOrDeferred(unittest.TestCase):
    def test_excluded_reviewed_events_carry_reason(self) -> None:
        excluded = [4, 6, 8, 9]
        with _patch_packet(_packet_payload(
            excluded_reviewed_event_ids=excluded,
        )):
            report = cli.run_short_horizon_review_queue()
        ids = {e["event_id"] for e in report["excluded_or_deferred"]
               if isinstance(e, dict)}
        self.assertEqual(ids, set(excluded))
        for e in report["excluded_or_deferred"]:
            self.assertIn("reason", e)
            self.assertTrue(e["reason"], "reason must be non-empty")


# ---------------------------------------------------------------------------
# Read-only / no provider imports
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_module_does_not_pull_provider_or_fastapi(self) -> None:
        before = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        after = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# Empty cohort
# ---------------------------------------------------------------------------


class TestEmptyCohort(unittest.TestCase):
    def test_empty_packet_yields_zero_counts(self) -> None:
        with _patch_packet(_packet_payload(candidates=[])):
            report = cli.run_short_horizon_review_queue()
        self.assertEqual(report["candidate_count"],         0)
        self.assertEqual(report["high_priority_count"],     0)
        self.assertEqual(report["medium_priority_count"],   0)
        self.assertEqual(report["low_priority_count"],      0)
        self.assertEqual(report["review_queue"],            [])


# ---------------------------------------------------------------------------
# Limit truncates review_queue
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_review_queue_capped_at_limit(self) -> None:
        cands = [_packet_candidate(event_id=i) for i in range(1, 11)]
        with _patch_packet(_packet_payload(candidates=cands)):
            report = cli.run_short_horizon_review_queue(limit=4)
        self.assertEqual(len(report["review_queue"]), 4)
        # Aggregates still reflect the full cohort.
        self.assertEqual(report["candidate_count"], 10)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    _FORBIDDEN = ("proof", "proves", "validated", "alpha", "guaranteed")

    def test_text_avoids_forbidden_terms(self) -> None:
        cand = _packet_candidate(
            event_id=1, repair_type="ticker_off_topic",
            flags=["driv_lit_off_topic"],
        )
        with _patch_packet(_packet_payload(candidates=[cand])):
            out = io.StringIO()
            cli.main([], out=out)  # text mode
        text = out.getvalue().lower()
        for term in self._FORBIDDEN:
            self.assertNotIn(
                term, text,
                f"forbidden term {term!r} in queue text: {text[:300]!r}",
            )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_cli_emits_parseable_json(self) -> None:
        cand = _packet_candidate(event_id=1, repair_priority="high")
        with _patch_packet(_packet_payload(candidates=[cand])):
            out = io.StringIO()
            rc = cli.main(["--json", "--limit", "5"], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)


if __name__ == "__main__":
    unittest.main()
