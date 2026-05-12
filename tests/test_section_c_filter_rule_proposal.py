"""Tests for ``scripts/section_c_filter_rule_proposal.py``.

Pin the contract:

* Read-only on every input.  The script never imports a production
  filter module (``api`` / ``routes.*`` / ``movers_cache``); doing
  so would couple a proposal-only generator to the thing it
  proposes to change.
* The envelope carries the documented 11 top-level keys.
* Every emitted rule (in any of the per-section lists or in
  ``rules_not_recommended_yet``) carries the 8 spec fields.
* Rule descriptions start with one of the suggestion verbs
  (``Consider``, ``Operators may``, ``Investigate``) — never an
  imperative.
* The two global rules (G1: missing mechanism family, G2: weak
  ticker proxy) are pinned ``priority='high'``.
* Missing diagnostic inputs surface as warnings, not errors.
* ``--output`` is the only filesystem side effect, and it refuses
  to overwrite an existing path.
* Conservative wording — banned tokens absent.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_filter_rule_proposal as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "generated_at",
    "daily_filter_proposals",
    "weekly_filter_proposals",
    "still_moving_filter_proposals",
    "cross_section_rules",
    "highest_impact_rules",
    "rules_not_recommended_yet",
    "evidence_from_diagnostics",
    "warnings",
    "errors",
)


_REQUIRED_RULE_FIELDS = (
    "rule_id",
    "section",
    "description",
    "diagnostic_evidence",
    "expected_benefit",
    "possible_false_positive_risk",
    "implementation_complexity",
    "priority",
)


_REQUIRED_EVIDENCE_FIELDS = (
    "source_diagnostic",
    "evidence_count",
    "sample_event_ids",
    "evidence_note",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "guaranteed",
    "correct ticker",
)


_SUGGESTION_VERB_PREFIXES = ("Consider", "Operators may", "Investigate")


# ---------------------------------------------------------------------------
# Synthetic diagnostic payloads
# ---------------------------------------------------------------------------


def _daily_payload(*, missing_mech=0, off_topic=0, raw_legal=0,
                    duplicates=0, candidates_checked=10) -> dict[str, Any]:
    def _row(ev_id: int) -> dict[str, Any]:
        return {
            "event_id":       ev_id,
            "headline":       f"synthetic headline {ev_id}",
            "event_date":     "2026-05-10",
            "primary_ticker": "XOM",
            "mechanism_family": None,
            "market_relevance_score": 0.6,
            "diagnostic_tags": [],
            "inclusion_reason": "",
            "exclusion_reason": "",
        }
    return {
        "ok":                        True,
        "candidates_checked":        candidates_checked,
        "accepted_like_candidates":  [],
        "junk_headlines":            [],
        "raw_legal_text_cases":      [_row(1000 + i) for i in range(raw_legal)],
        "off_topic_cases":           [_row(2000 + i) for i in range(off_topic)],
        "vague_cases":               [],
        "duplicate_cases":           [_row(3000 + i) for i in range(duplicates)],
        "missing_mechanism_cases":   [_row(4000 + i) for i in range(missing_mech)],
        "recommended_daily_filter_rules": [],
        "warnings": [], "errors": [],
    }


def _weekly_payload(
    *, repeated_headline_groups=0, repeated_date_ticker_groups=0,
    canonical_suggestions=0, candidates_checked=20,
) -> dict[str, Any]:
    def _group(prefix: str, i: int) -> dict[str, Any]:
        base = 5000 + i * 10
        return {
            "duplicate_group_id":  f"{prefix}-{i:03d}",
            "event_ids":           [base, base + 1, base + 2],
            "headlines":           ["dup headline"],
            "dates":               ["2026-05-08"],
            "tickers":             ["XOM"],
            "mechanism_families":  ["supply_shock"],
            "suggested_canonical_event_id": base,
            "reason":              "synthetic duplicate group",
        }
    return {
        "ok":                              True,
        "candidates_checked":              candidates_checked,
        "duplicate_groups":                [],
        "repeated_date_ticker_groups": [
            _group("dt", i) for i in range(repeated_date_ticker_groups)
        ],
        "repeated_headline_groups": [
            _group("hl", i) for i in range(repeated_headline_groups)
        ],
        "mechanism_theme_candidates":      [],
        "canonical_headline_suggestions": [
            _group("ch", i) for i in range(canonical_suggestions)
        ],
        "recommended_weekly_filter_rules": [],
        "window":                          {},
        "warnings": [], "errors": [],
    }


def _still_moving_payload(
    *, weak_ticker=0, bad_proxy=0, missing_price_cache=0,
    no_persistence=0, candidates_checked=30,
) -> dict[str, Any]:
    def _row(ev_id: int) -> dict[str, Any]:
        return {
            "event_id":         ev_id,
            "headline":         f"sm headline {ev_id}",
            "event_date":       "2026-04-15",
            "primary_ticker":   "XOM",
            "benchmark_ticker": "SPY",
            "mechanism_family": "supply_shock",
            "ticker_quality":   "ok",
            "price_cache_available": True,
            "benchmark_adjusted_evidence_available": True,
            "persistence_signal": "Accelerating",
            "diagnostic_tags":   [],
            "inclusion_reason":  "",
            "exclusion_reason":  "",
        }
    return {
        "ok":                        True,
        "candidates_checked":        candidates_checked,
        "defensible_candidates":     [],
        "weak_ticker_cases":         [_row(6000 + i) for i in range(weak_ticker)],
        "bad_proxy_cases":           [_row(7000 + i) for i in range(bad_proxy)],
        "missing_price_cache_cases": [_row(8000 + i) for i in range(missing_price_cache)],
        "no_persistence_cases":      [_row(9000 + i) for i in range(no_persistence)],
        "duplicate_narrative_cases": [],
        "candidates":                [],
        "recommended_still_moving_filter_rules": [],
        "warnings": [], "errors": [],
    }


def _combined_payload(
    *, missing_mech=0, bad_proxy=0, low_relevance=0,
) -> dict[str, Any]:
    def _row(ev_id: int, *, tags: list[str]) -> dict[str, Any]:
        return {
            "event_id":               ev_id,
            "diagnostic_tags":        list(tags),
            "source_section":         "daily",
            "headline":               f"combined {ev_id}",
        }
    return {
        "ok":                        True,
        "daily_candidates":          [
            _row(10_000 + i, tags=["low_market_relevance"])
            for i in range(low_relevance)
        ],
        "weekly_candidates":         [],
        "still_moving_candidates":   [],
        "junk_headlines":            [],
        "duplicate_groups":          [],
        "weak_ticker_cases":         [],
        "missing_mechanism_cases":   [
            _row(11_000 + i, tags=["missing_mechanism_family"])
            for i in range(missing_mech)
        ],
        "bad_proxy_cases":           [
            _row(12_000 + i, tags=["weak_proxy"])
            for i in range(bad_proxy)
        ],
    }


def _source_inventory_payload() -> dict[str, Any]:
    return {
        "ok":                       True,
        "daily_sources":            ["events", "movers_cache"],
        "weekly_sources":           ["movers_cache"],
        "still_moving_sources":     ["movers_cache"],
        "db_tables_used":           ["events", "movers_cache", "price_cache"],
        "scripts_used":             [],
        "routes_used":              [],
        "ranking_fields":           [],
        "filter_fields":            [],
        "suspected_quality_gaps":   [
            {"id": "q1", "summary": "no mechanism filter",
             "streams_affected": ["daily"]},
        ],
        "warnings": [], "errors": [],
    }


def _empty_payloads() -> dict[str, Any]:
    """A loader-style dict where every payload is None.  Tests that
    want the missing-input branch use this."""
    return {
        "source_inventory": None,
        "daily":            None,
        "weekly":           None,
        "still_moving":     None,
        "combined":         None,
        "warnings":         ["synthetic: all inputs missing"],
        "errors":           [],
    }


def _patch_loader(payload: dict[str, Any]):
    return patch.object(
        cli, "_load_diagnostic_payloads", return_value=payload,
    )


def _patched_load(**overrides) -> dict[str, Any]:
    """Build a complete loader-style payload, with overrides per
    short source name."""
    default = {
        "source_inventory": _source_inventory_payload(),
        "daily":            _daily_payload(),
        "weekly":           _weekly_payload(),
        "still_moving":     _still_moving_payload(),
        "combined":         _combined_payload(),
        "warnings":         [],
        "errors":           [],
    }
    default.update(overrides)
    return default


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_all_required_keys(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing key: {k}")

    def test_ok_true_when_no_errors(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_generated_at_passes_through(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2099-01-01T00:00:00Z",
            )
        self.assertEqual(report["generated_at"], "2099-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Per-rule schema and suggestion-verb invariant
# ---------------------------------------------------------------------------


class TestRuleSchema(unittest.TestCase):
    def test_every_rule_has_8_fields(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        all_rules = (
            report["daily_filter_proposals"]
            + report["weekly_filter_proposals"]
            + report["still_moving_filter_proposals"]
            + report["cross_section_rules"]
            + report["rules_not_recommended_yet"]
        )
        self.assertGreater(len(all_rules), 0)
        for r in all_rules:
            self.assertEqual(
                set(r.keys()), set(_REQUIRED_RULE_FIELDS),
                f"rule {r.get('rule_id')!r} has wrong field set",
            )

    def test_every_diagnostic_evidence_block_has_4_fields(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        all_rules = (
            report["daily_filter_proposals"]
            + report["weekly_filter_proposals"]
            + report["still_moving_filter_proposals"]
            + report["cross_section_rules"]
            + report["rules_not_recommended_yet"]
        )
        for r in all_rules:
            evidence = r["diagnostic_evidence"]
            self.assertEqual(
                set(evidence.keys()), set(_REQUIRED_EVIDENCE_FIELDS),
                f"evidence block on rule {r['rule_id']!r} has wrong field set",
            )

    def test_section_field_is_one_of_four(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        all_rules = (
            report["daily_filter_proposals"]
            + report["weekly_filter_proposals"]
            + report["still_moving_filter_proposals"]
            + report["cross_section_rules"]
            + report["rules_not_recommended_yet"]
        )
        for r in all_rules:
            self.assertIn(
                r["section"], {"daily", "weekly", "still_moving", "global"},
                f"rule {r['rule_id']!r} has unknown section {r['section']!r}",
            )

    def test_complexity_is_low_medium_or_high(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        all_rules = (
            report["daily_filter_proposals"]
            + report["weekly_filter_proposals"]
            + report["still_moving_filter_proposals"]
            + report["cross_section_rules"]
            + report["rules_not_recommended_yet"]
        )
        for r in all_rules:
            self.assertIn(r["implementation_complexity"],
                          {"low", "medium", "high"})

    def test_priority_is_low_medium_or_high(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        all_rules = (
            report["daily_filter_proposals"]
            + report["weekly_filter_proposals"]
            + report["still_moving_filter_proposals"]
            + report["cross_section_rules"]
            + report["rules_not_recommended_yet"]
        )
        for r in all_rules:
            self.assertIn(r["priority"], {"low", "medium", "high"})


class TestSuggestionVerbInvariant(unittest.TestCase):
    def test_every_rule_description_starts_with_suggestion_verb(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        all_rules = (
            report["daily_filter_proposals"]
            + report["weekly_filter_proposals"]
            + report["still_moving_filter_proposals"]
            + report["cross_section_rules"]
            + report["rules_not_recommended_yet"]
        )
        for r in all_rules:
            self.assertTrue(
                any(r["description"].startswith(v)
                    for v in _SUGGESTION_VERB_PREFIXES),
                f"rule {r['rule_id']!r} description must start with a "
                f"suggestion verb; got {r['description'][:80]!r}",
            )

    def test_descriptions_avoid_imperative_reject_or_drop(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        all_rules = (
            report["daily_filter_proposals"]
            + report["weekly_filter_proposals"]
            + report["still_moving_filter_proposals"]
            + report["cross_section_rules"]
            + report["rules_not_recommended_yet"]
        )
        joined = " ".join(r["description"] for r in all_rules).lower()
        for verb in ("reject ", "drop ", "delete ", "remove ", "ban "):
            self.assertNotIn(
                verb, joined,
                f"imperative {verb!r} leaked into rule descriptions",
            )


# ---------------------------------------------------------------------------
# Required-rule presence per section
# ---------------------------------------------------------------------------


class TestRequiredRulesPresence(unittest.TestCase):
    def test_daily_requires_mechanism_and_flags_junk(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        ids = {r["rule_id"] for r in report["daily_filter_proposals"]}
        self.assertIn("daily.require_mechanism_family", ids)
        self.assertIn("daily.flag_off_topic_headlines", ids)
        self.assertIn("daily.flag_raw_legal_text", ids)
        self.assertIn("daily.flag_low_market_relevance", ids)

    def test_weekly_proposes_collapse_and_canonical(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        ids = {r["rule_id"] for r in report["weekly_filter_proposals"]}
        self.assertIn("weekly.collapse_repeated_headline_clusters", ids)
        self.assertIn("weekly.collapse_date_ticker_duplicates", ids)
        self.assertIn("weekly.canonical_event_selection", ids)

    def test_still_moving_requires_four_axes(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        ids = {r["rule_id"] for r in report["still_moving_filter_proposals"]}
        self.assertIn("still_moving.require_price_cache", ids)
        self.assertIn(
            "still_moving.require_benchmark_adjusted_evidence", ids,
        )
        self.assertIn("still_moving.require_persistence_signal", ids)
        self.assertIn("still_moving.exclude_weak_ticker", ids)

    def test_global_rules_present_in_cross_section(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        ids = {r["rule_id"] for r in report["cross_section_rules"]}
        self.assertIn("global.require_mechanism_family", ids)
        self.assertIn("global.exclude_weak_ticker_proxy", ids)


# ---------------------------------------------------------------------------
# Priority — global rules are pinned, section rules adapt to count
# ---------------------------------------------------------------------------


class TestPriorityAssignment(unittest.TestCase):
    def test_global_rules_are_pinned_high(self) -> None:
        # Even with zero evidence, global rules must be high.
        with _patch_loader(_empty_payloads()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        for r in report["cross_section_rules"]:
            if r["rule_id"] in (
                "global.require_mechanism_family",
                "global.exclude_weak_ticker_proxy",
            ):
                self.assertEqual(
                    r["priority"], "high",
                    f"{r['rule_id']} must be pinned 'high' regardless of count",
                )

    def test_section_rule_priority_high_when_evidence_large(self) -> None:
        # 60 missing-mechanism daily cases → daily.require_mechanism gets 'high'.
        loader = _patched_load(daily=_daily_payload(missing_mech=60))
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        daily_by_id = {r["rule_id"]: r for r in report["daily_filter_proposals"]}
        self.assertEqual(
            daily_by_id["daily.require_mechanism_family"]["priority"],
            "high",
        )
        self.assertEqual(
            daily_by_id["daily.require_mechanism_family"]
                       ["diagnostic_evidence"]["evidence_count"],
            60,
        )

    def test_section_rule_priority_medium_when_evidence_moderate(self) -> None:
        loader = _patched_load(daily=_daily_payload(off_topic=15))
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        daily_by_id = {r["rule_id"]: r for r in report["daily_filter_proposals"]}
        self.assertEqual(
            daily_by_id["daily.flag_off_topic_headlines"]["priority"],
            "medium",
        )

    def test_section_rule_priority_low_when_evidence_thin(self) -> None:
        loader = _patched_load(daily=_daily_payload(raw_legal=3))
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        daily_by_id = {r["rule_id"]: r for r in report["daily_filter_proposals"]}
        self.assertEqual(
            daily_by_id["daily.flag_raw_legal_text"]["priority"], "low",
        )

    def test_highest_impact_rules_subset_priority_high(self) -> None:
        loader = _patched_load(
            daily=_daily_payload(missing_mech=80, off_topic=70),
            still_moving=_still_moving_payload(missing_price_cache=200),
        )
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        for r in report["highest_impact_rules"]:
            self.assertEqual(r["priority"], "high")

    def test_highest_impact_sorted_by_evidence_count_desc(self) -> None:
        loader = _patched_load(
            daily=_daily_payload(missing_mech=80),
            still_moving=_still_moving_payload(missing_price_cache=200),
        )
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        counts = [
            r["diagnostic_evidence"]["evidence_count"]
            for r in report["highest_impact_rules"]
        ]
        self.assertEqual(counts, sorted(counts, reverse=True))


# ---------------------------------------------------------------------------
# Diagnostic evidence wiring
# ---------------------------------------------------------------------------


class TestDiagnosticEvidence(unittest.TestCase):
    def test_evidence_count_matches_input_list_length(self) -> None:
        loader = _patched_load(daily=_daily_payload(missing_mech=7))
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        daily_by_id = {r["rule_id"]: r for r in report["daily_filter_proposals"]}
        self.assertEqual(
            daily_by_id["daily.require_mechanism_family"]
                       ["diagnostic_evidence"]["evidence_count"],
            7,
        )

    def test_sample_event_ids_capped_at_five(self) -> None:
        loader = _patched_load(daily=_daily_payload(missing_mech=20))
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        daily_by_id = {r["rule_id"]: r for r in report["daily_filter_proposals"]}
        samples = daily_by_id["daily.require_mechanism_family"] \
            ["diagnostic_evidence"]["sample_event_ids"]
        self.assertLessEqual(len(samples), 5)

    def test_weekly_evidence_count_uses_group_count(self) -> None:
        loader = _patched_load(
            weekly=_weekly_payload(repeated_headline_groups=4),
        )
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        weekly_by_id = {r["rule_id"]: r for r in report["weekly_filter_proposals"]}
        self.assertEqual(
            weekly_by_id["weekly.collapse_repeated_headline_clusters"]
                        ["diagnostic_evidence"]["evidence_count"],
            4,
        )

    def test_combined_low_relevance_counts_tagged_events(self) -> None:
        loader = _patched_load(
            combined=_combined_payload(low_relevance=8),
        )
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        daily_by_id = {r["rule_id"]: r for r in report["daily_filter_proposals"]}
        self.assertEqual(
            daily_by_id["daily.flag_low_market_relevance"]
                       ["diagnostic_evidence"]["evidence_count"],
            8,
        )


# ---------------------------------------------------------------------------
# rules_not_recommended_yet
# ---------------------------------------------------------------------------


class TestRulesNotRecommendedYet(unittest.TestCase):
    def test_has_at_least_one_deferred_rule(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        self.assertGreater(len(report["rules_not_recommended_yet"]), 0)

    def test_deferred_rules_have_low_priority(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        for r in report["rules_not_recommended_yet"]:
            self.assertEqual(r["priority"], "low",
                             f"deferred rule {r['rule_id']!r} must be 'low' priority")


# ---------------------------------------------------------------------------
# evidence_from_diagnostics rollup
# ---------------------------------------------------------------------------


class TestEvidenceRollup(unittest.TestCase):
    def test_evidence_summary_has_five_sources(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        summary = report["evidence_from_diagnostics"]
        self.assertEqual(
            set(summary.keys()),
            {"source_inventory", "daily", "weekly",
             "still_moving", "combined"},
        )

    def test_summary_marks_present_when_payload_supplied(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        for src, entry in report["evidence_from_diagnostics"].items():
            self.assertTrue(entry["present"], f"{src} should be present")

    def test_summary_marks_absent_when_payload_missing(self) -> None:
        with _patch_loader(_empty_payloads()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        for src, entry in report["evidence_from_diagnostics"].items():
            self.assertFalse(entry["present"], f"{src} should be absent")
            self.assertEqual(entry["counts"], {})

    def test_daily_summary_includes_named_counts(self) -> None:
        loader = _patched_load(daily=_daily_payload(missing_mech=5, off_topic=2))
        with _patch_loader(loader):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        daily_summary = report["evidence_from_diagnostics"]["daily"]
        self.assertEqual(daily_summary["counts"]["missing_mechanism_cases"], 5)
        self.assertEqual(daily_summary["counts"]["off_topic_cases"], 2)


# ---------------------------------------------------------------------------
# Missing-source handling
# ---------------------------------------------------------------------------


class TestMissingSourceHandling(unittest.TestCase):
    def test_all_missing_inputs_yield_warnings_not_errors(self) -> None:
        # Use the un-patched seam with real bogus paths.
        bogus = lambda: os.path.join(  # noqa: E731
            tempfile.gettempdir(), f"no_such_{uuid.uuid4().hex}.json",
        )
        report = cli.build_section_c_filter_rule_proposal(
            source_inventory_path=bogus(),
            daily_diagnostic_path=bogus(),
            weekly_diagnostic_path=bogus(),
            still_moving_diagnostic_path=bogus(),
            combined_diagnostic_path=bogus(),
            generated_at="2026-05-12T00:00:00Z",
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        # Five warnings — one per missing source.
        self.assertGreaterEqual(len(report["warnings"]), 5)

    def test_proposal_still_produces_rules_when_inputs_missing(self) -> None:
        # The rule templates exist regardless of evidence; missing
        # inputs just give them empty evidence (count=0).
        with _patch_loader(_empty_payloads()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        self.assertGreater(len(report["daily_filter_proposals"]), 0)
        self.assertGreater(len(report["weekly_filter_proposals"]), 0)
        self.assertGreater(len(report["still_moving_filter_proposals"]), 0)
        self.assertGreater(len(report["cross_section_rules"]), 0)

    def test_malformed_json_input_surfaces_error(self) -> None:
        tmp = os.path.join(
            tempfile.gettempdir(),
            f"bad_json_{uuid.uuid4().hex}.json",
        )
        try:
            Path(tmp).write_text("{not: valid json", encoding="utf-8")
            report = cli.build_section_c_filter_rule_proposal(
                source_inventory_path=os.path.join(tempfile.gettempdir(),
                                                    f"missing_{uuid.uuid4().hex}.json"),
                daily_diagnostic_path=tmp,
                weekly_diagnostic_path=os.path.join(tempfile.gettempdir(),
                                                     f"missing_{uuid.uuid4().hex}.json"),
                still_moving_diagnostic_path=os.path.join(tempfile.gettempdir(),
                                                         f"missing_{uuid.uuid4().hex}.json"),
                combined_diagnostic_path=os.path.join(tempfile.gettempdir(),
                                                      f"missing_{uuid.uuid4().hex}.json"),
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "failed to parse" in e for e in report["errors"]
            ))
        finally:
            if Path(tmp).exists():
                Path(tmp).unlink()


# ---------------------------------------------------------------------------
# --output file persistence
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def _tmp(self) -> str:
        return os.path.join(
            tempfile.gettempdir(),
            f"sc_proposal_{uuid.uuid4().hex}.json",
        )

    def test_no_output_means_no_file(self) -> None:
        sentinel = self._tmp()
        self.assertFalse(Path(sentinel).exists())
        with _patch_loader(_patched_load()):
            cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        self.assertFalse(Path(sentinel).exists())

    def test_output_writes_json_file(self) -> None:
        out = self._tmp()
        try:
            with _patch_loader(_patched_load()):
                report = cli.build_section_c_filter_rule_proposal(
                    output_path=out,
                    generated_at="2026-05-12T00:00:00Z",
                )
            self.assertTrue(Path(out).exists())
            parsed = json.loads(Path(out).read_text(encoding="utf-8"))
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_ENVELOPE_KEYS))
            self.assertEqual(parsed["ok"], report["ok"])
        finally:
            if Path(out).exists():
                Path(out).unlink()

    def test_output_refuses_to_overwrite_existing_file(self) -> None:
        out = self._tmp()
        try:
            Path(out).write_text("preexisting", encoding="utf-8")
            with _patch_loader(_patched_load()):
                report = cli.build_section_c_filter_rule_proposal(
                    output_path=out,
                    generated_at="2026-05-12T00:00:00Z",
                )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "refusing to overwrite" in e.lower()
                for e in report["errors"]
            ))
            # Pre-existing content untouched.
            self.assertEqual(
                Path(out).read_text(encoding="utf-8"), "preexisting",
            )
        finally:
            if Path(out).exists():
                Path(out).unlink()


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_json_render(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, blob,
                             f"banned token {term!r} in JSON render")

    def test_no_banned_tokens_in_text_render(self) -> None:
        with _patch_loader(_patched_load()):
            report = cli.build_section_c_filter_rule_proposal(
                generated_at="2026-05-12T00:00:00Z",
            )
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, text)


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_production_filter_modules(self) -> None:
        for attr in (
            "api", "routes", "movers_cache", "market_check",
            "market_data", "yfinance", "anthropic", "openai", "fastapi",
        ):
            self.assertFalse(
                hasattr(cli, attr),
                f"proposal must not bind {attr} as a module attr",
            )

    def test_module_does_not_open_sqlite(self) -> None:
        # The proposal reads JSON, not sqlite — sqlite3 should not
        # even be imported into the module's namespace.
        self.assertFalse(hasattr(cli, "sqlite3"))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_flag_emits_envelope(self) -> None:
        # Use bogus paths so the loader returns empty payloads and
        # the script returns ok=True with warnings.
        nope = lambda: os.path.join(  # noqa: E731
            tempfile.gettempdir(), f"no_{uuid.uuid4().hex}.json",
        )
        rc, output = self._run([
            "--json",
            "--source-inventory", nope(),
            "--daily-diagnostic", nope(),
            "--weekly-diagnostic", nope(),
            "--still-moving-diagnostic", nope(),
            "--combined-diagnostic", nope(),
        ])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)
        self.assertTrue(parsed["ok"])

    def test_default_text_render_runs(self) -> None:
        nope = lambda: os.path.join(  # noqa: E731
            tempfile.gettempdir(), f"no_{uuid.uuid4().hex}.json",
        )
        rc, output = self._run([
            "--source-inventory", nope(),
            "--daily-diagnostic", nope(),
            "--weekly-diagnostic", nope(),
            "--still-moving-diagnostic", nope(),
            "--combined-diagnostic", nope(),
        ])
        self.assertEqual(rc, 0)
        self.assertIn("Section C", output)


if __name__ == "__main__":
    unittest.main()
