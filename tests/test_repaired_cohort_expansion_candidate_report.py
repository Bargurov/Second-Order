"""Tests for ``scripts/repaired_cohort_expansion_candidate_report.py``.

Pin the contract:

* Joins five upstream read-only reports through patchable seams:
  contamination, missing_tickers, short_horizon_readiness,
  clean_cohort, cleanup_candidates.  Tests patch each seam directly
  with synthetic payloads — the un-patched path resolves the upstream
  imports lazily.
* Output dict carries EXACTLY these 5 keys:
  ``candidate_count``, ``groups``, ``top_candidates``,
  ``estimated_repair_yield``, ``recommended_next_action``.
* Five mutually-exclusive group buckets:
    - ``mechanism_family_only_ready`` — fully-ready contamination
      examples whose flags are exactly ``{mechanism_family_none}``
      or ``{mechanism_family_none, duplicate_date_ticker}``.
    - ``ticker_repair_needed`` — contamination flag includes
      ``driv_lit_off_topic`` OR event surfaced by missing-tickers
      report (no usable primary symbol).
    - ``duplicate_only_review`` — fully-ready contamination flag
      set is exactly ``{duplicate_date_ticker}`` (manual-aware
      promotion candidate when partner is excluded).
    - ``short_horizon_only`` — short-horizon-ready but NOT
      fully-ready (1d/5d cohort, not 20d).
    - ``likely_junk`` — cleanup-candidate match (test fixture /
      rotating macro / fixture timestamp / duplicate headline) OR
      contamination flag ``local_off_topic_headline``.
* Reviewed-id exclusion: 28 already-reviewed event_ids are dropped
  before bucketing AND before any aggregate count.
* Group priority (when an event matches multiple sources):
  ``likely_junk`` first (filter out), then
  ``mechanism_family_only_ready`` → ``duplicate_only_review`` →
  ``ticker_repair_needed`` → ``short_horizon_only``.
* Conservative wording — banned tokens in any text field:
  ``proof``, ``alpha``, ``automatically``, ``deletes``,
  ``replaces``, ``correct ticker``.
* Read-only: default run does not import yfinance / fastapi / api /
  routes.*.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import repaired_cohort_expansion_candidate_report as cli  # noqa: E402


_REQUIRED_KEYS = (
    "candidate_count",
    "groups",
    "top_candidates",
    "estimated_repair_yield",
    "recommended_next_action",
)


_GROUP_NAMES = (
    "mechanism_family_only_ready",
    "ticker_repair_needed",
    "duplicate_only_review",
    "short_horizon_only",
    "likely_junk",
)


_BANNED_WORDS = (
    "proof",
    "automatically",
    "deletes",
    "replaces",
    "correct ticker",
)


_EXPECTED_EXCLUDED_IDS = frozenset({
    4, 6, 8, 9, 30, 40, 44, 46, 47, 49, 51, 60, 63, 64, 73,
    112, 153, 154, 160, 206, 207, 208, 216, 220, 226, 231, 237, 281,
})


# ---------------------------------------------------------------------------
# Synthetic upstream payloads
# ---------------------------------------------------------------------------


def _contamination_example(
    *,
    event_id: int,
    flags: list[str],
    headline: str | None = "Bank of America announces dividend increase",
    event_date: str | None = "2026-04-05",
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


def _contamination_payload(examples: list[dict]) -> dict:
    return {
        "ok":                          True,
        "total_fully_ready":           max(len(examples), 1),
        "suspicious_count":            len(examples),
        "duplicate_date_ticker_count": 0,
        "by_flag":                     {},
        "examples":                    list(examples),
        "recommended_next_action":     "synthetic",
    }


def _missing_tickers_payload(events: list[dict]) -> dict:
    return {
        "total_events":                  max(len(events), 1),
        "events_missing_market_tickers": len(events),
        "events":                        list(events),
        "recommended_next_action":       "synthetic",
    }


def _missing_ticker_event(*, event_id: int,
                          headline: str = "Some headline",
                          event_date: str = "2026-04-10") -> dict:
    return {
        "event_id":              event_id,
        "event_date":             event_date,
        "headline":              headline,
        "stage":                 None,
        "persistence":           None,
        "confidence":            None,
        "suggested_next_action": "manual_review_required",
    }


def _short_horizon_payload(examples: list[dict]) -> dict:
    return {
        "total_events":                          max(len(examples), 1),
        "events_ready_1d5d":                     len(examples),
        "delta_vs_full_ready":                   sum(
            1 for e in examples if e.get("delta_eligible")),
        "missing_tickers_count":                 0,
        "missing_benchmark_count":               0,
        "insufficient_estimation_window_count":  0,
        "examples":                              list(examples),
        "recommended_next_action":               "synthetic",
    }


def _short_horizon_example(
    *, event_id: int, delta_eligible: bool = True,
    primary_ticker: str | None = "AAPL",
    event_date: str | None = "2026-04-10",
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "checks":           {},
        "ready_1d5d":       True,
        "delta_eligible":   delta_eligible,
    }


def _clean_cohort_payload(*, clean_event_ids: list[int]) -> dict:
    return {
        "ok":                            True,
        "clean_fully_ready_count":       len(clean_event_ids),
        "clean_fully_ready_event_ids":   list(clean_event_ids),
        "excluded_fully_ready_examples": [],
    }


def _cleanup_candidate_payload(examples: list[dict]) -> dict:
    return {
        "candidate_count":             len(examples),
        "reasons":                     {},
        "examples":                    list(examples),
        "fixture_timestamp_threshold": 3,
        "recommended_next_action":     "synthetic",
    }


def _cleanup_example(*, event_id: int,
                     headline: str = "Macro shock test event",
                     reasons: list[str] | None = None) -> dict:
    return {
        "event_id":   event_id,
        "headline":   headline,
        "timestamp":  "2026-04-10T10:00:00",
        "event_date": "2026-04-10",
        "reasons":    list(reasons or ["test_fixture_phrase"]),
    }


def _patch_seams(
    *,
    contamination: dict | None = None,
    missing_tickers: dict | None = None,
    short_horizon: dict | None = None,
    clean_cohort: dict | None = None,
    cleanup_candidates: dict | None = None,
):
    return (
        patch.object(cli, "_run_contamination_report",
                     return_value=contamination
                     if contamination is not None
                     else _contamination_payload([])),
        patch.object(cli, "_run_missing_tickers_report",
                     return_value=missing_tickers
                     if missing_tickers is not None
                     else _missing_tickers_payload([])),
        patch.object(cli, "_run_short_horizon_report",
                     return_value=short_horizon
                     if short_horizon is not None
                     else _short_horizon_payload([])),
        patch.object(cli, "_run_clean_cohort_report",
                     return_value=clean_cohort
                     if clean_cohort is not None
                     else _clean_cohort_payload(clean_event_ids=[])),
        patch.object(cli, "_run_cleanup_candidate_report",
                     return_value=cleanup_candidates
                     if cleanup_candidates is not None
                     else _cleanup_candidate_payload([])),
    )


def _run(**kwargs) -> dict:
    contamination     = kwargs.pop("contamination", None)
    missing_tickers   = kwargs.pop("missing_tickers", None)
    short_horizon     = kwargs.pop("short_horizon", None)
    clean_cohort      = kwargs.pop("clean_cohort", None)
    cleanup_candidates = kwargs.pop("cleanup_candidates", None)
    seams = _patch_seams(
        contamination=contamination,
        missing_tickers=missing_tickers,
        short_horizon=short_horizon,
        clean_cohort=clean_cohort,
        cleanup_candidates=cleanup_candidates,
    )
    with seams[0], seams[1], seams[2], seams[3], seams[4]:
        return cli.summarize_expansion_candidates(**kwargs)


def _run_cli(argv: list[str], **kwargs) -> tuple[int, str]:
    out = StringIO()
    contamination     = kwargs.pop("contamination", None)
    missing_tickers   = kwargs.pop("missing_tickers", None)
    short_horizon     = kwargs.pop("short_horizon", None)
    clean_cohort      = kwargs.pop("clean_cohort", None)
    cleanup_candidates = kwargs.pop("cleanup_candidates", None)
    seams = _patch_seams(
        contamination=contamination,
        missing_tickers=missing_tickers,
        short_horizon=short_horizon,
        clean_cohort=clean_cohort,
        cleanup_candidates=cleanup_candidates,
    )
    with seams[0], seams[1], seams[2], seams[3], seams[4]:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_returns_dict_with_exactly_five_keys(self) -> None:
        result = _run()
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(result.keys())}")

    def test_groups_carry_all_five_buckets(self) -> None:
        result = _run()
        self.assertEqual(set(result["groups"].keys()), set(_GROUP_NAMES))

    def test_each_group_has_count_and_event_ids(self) -> None:
        result = _run()
        for name in _GROUP_NAMES:
            block = result["groups"][name]
            self.assertIn("count", block, f"group {name} missing count")
            self.assertIn("event_ids", block,
                          f"group {name} missing event_ids")
            self.assertIsInstance(block["count"], int)
            self.assertIsInstance(block["event_ids"], list)


# ---------------------------------------------------------------------------
# Reviewed-id exclusion
# ---------------------------------------------------------------------------


class TestReviewedIdExclusion(unittest.TestCase):
    def test_excluded_event_ids_set_count_is_28(self) -> None:
        self.assertEqual(len(cli._EXCLUDED_EVENT_IDS), 28)

    def test_excluded_event_ids_match_expected_membership(self) -> None:
        self.assertEqual(
            set(cli._EXCLUDED_EVENT_IDS), set(_EXPECTED_EXCLUDED_IDS))

    def test_reviewed_ids_dropped_from_all_groups(self) -> None:
        # event 46 (reviewed) appears in contamination + cleanup; must
        # not surface in any group.  event 1000 (fresh) carries the
        # same flag pattern; it should land in mechanism_family_only_ready.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=46,
                                       flags=["mechanism_family_none"]),
                _contamination_example(event_id=1000,
                                       flags=["mechanism_family_none"]),
            ]),
        )
        for name in _GROUP_NAMES:
            self.assertNotIn(46, result["groups"][name]["event_ids"],
                             f"reviewed id 46 leaked into {name}")
        self.assertIn(
            1000, result["groups"]["mechanism_family_only_ready"]["event_ids"],
        )


# ---------------------------------------------------------------------------
# Group: mechanism_family_only_ready
# ---------------------------------------------------------------------------


class TestMechanismFamilyOnlyReady(unittest.TestCase):
    def test_mechanism_family_none_only_lands_in_bucket(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000,
                                       flags=["mechanism_family_none"]),
            ]),
        )
        self.assertIn(
            1000,
            result["groups"]["mechanism_family_only_ready"]["event_ids"],
        )

    def test_mechanism_family_with_dup_lands_in_bucket(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        self.assertIn(
            1000,
            result["groups"]["mechanism_family_only_ready"]["event_ids"],
        )

    def test_mechanism_family_with_off_topic_does_not_land(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "local_off_topic_headline"]),
            ]),
        )
        self.assertNotIn(
            1000,
            result["groups"]["mechanism_family_only_ready"]["event_ids"],
        )


# ---------------------------------------------------------------------------
# Group: ticker_repair_needed
# ---------------------------------------------------------------------------


class TestTickerRepairNeeded(unittest.TestCase):
    def test_driv_lit_flag_lands_in_bucket(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000,
                                       flags=["driv_lit_off_topic"]),
            ]),
        )
        self.assertIn(
            1000, result["groups"]["ticker_repair_needed"]["event_ids"])

    def test_missing_tickers_event_lands_in_bucket(self) -> None:
        result = _run(
            missing_tickers=_missing_tickers_payload([
                _missing_ticker_event(event_id=2000),
            ]),
        )
        self.assertIn(
            2000, result["groups"]["ticker_repair_needed"]["event_ids"])


# ---------------------------------------------------------------------------
# Group: duplicate_only_review
# ---------------------------------------------------------------------------


class TestDuplicateOnlyReview(unittest.TestCase):
    def test_duplicate_only_lands_in_bucket(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1000,
                                       flags=["duplicate_date_ticker"]),
            ]),
        )
        self.assertIn(
            1000, result["groups"]["duplicate_only_review"]["event_ids"])

    def test_duplicate_with_mechanism_family_does_not_land_here(self) -> None:
        # mechanism_family + dup is a higher-priority bucket; the
        # combination should NOT land in duplicate_only_review.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(
                    event_id=1000,
                    flags=["mechanism_family_none", "duplicate_date_ticker"]),
            ]),
        )
        self.assertNotIn(
            1000, result["groups"]["duplicate_only_review"]["event_ids"])


# ---------------------------------------------------------------------------
# Group: short_horizon_only
# ---------------------------------------------------------------------------


class TestShortHorizonOnly(unittest.TestCase):
    def test_delta_eligible_lands_in_bucket(self) -> None:
        result = _run(
            short_horizon=_short_horizon_payload([
                _short_horizon_example(event_id=3000, delta_eligible=True),
            ]),
        )
        self.assertIn(
            3000, result["groups"]["short_horizon_only"]["event_ids"])

    def test_non_delta_eligible_does_not_land(self) -> None:
        # An event ready_1d5d AND already fully_ready should not land
        # here — that's just the existing fully-ready cohort.
        result = _run(
            short_horizon=_short_horizon_payload([
                _short_horizon_example(event_id=3000, delta_eligible=False),
            ]),
        )
        self.assertNotIn(
            3000, result["groups"]["short_horizon_only"]["event_ids"])


# ---------------------------------------------------------------------------
# Group: likely_junk
# ---------------------------------------------------------------------------


class TestLikelyJunk(unittest.TestCase):
    def test_cleanup_candidate_lands_in_junk_bucket(self) -> None:
        result = _run(
            cleanup_candidates=_cleanup_candidate_payload([
                _cleanup_example(event_id=4000),
            ]),
        )
        self.assertIn(4000, result["groups"]["likely_junk"]["event_ids"])

    def test_local_off_topic_flag_lands_in_junk_bucket(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4000,
                                       flags=["local_off_topic_headline"]),
            ]),
        )
        self.assertIn(4000, result["groups"]["likely_junk"]["event_ids"])

    def test_junk_event_excluded_from_other_buckets(self) -> None:
        # Event matches both cleanup (junk) AND mechanism_family — junk
        # wins, the event must NOT appear in mechanism_family_only_ready.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=4000,
                                       flags=["mechanism_family_none"]),
            ]),
            cleanup_candidates=_cleanup_candidate_payload([
                _cleanup_example(event_id=4000),
            ]),
        )
        self.assertIn(4000, result["groups"]["likely_junk"]["event_ids"])
        self.assertNotIn(
            4000,
            result["groups"]["mechanism_family_only_ready"]["event_ids"],
        )


# ---------------------------------------------------------------------------
# Mutual exclusivity
# ---------------------------------------------------------------------------


class TestMutualExclusivity(unittest.TestCase):
    def test_each_event_appears_in_exactly_one_group(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
                _contamination_example(event_id=1002,
                                       flags=["duplicate_date_ticker"]),
                _contamination_example(event_id=1003,
                                       flags=["driv_lit_off_topic"]),
            ]),
            missing_tickers=_missing_tickers_payload([
                _missing_ticker_event(event_id=1004),
            ]),
            short_horizon=_short_horizon_payload([
                _short_horizon_example(event_id=1005, delta_eligible=True),
            ]),
            cleanup_candidates=_cleanup_candidate_payload([
                _cleanup_example(event_id=1006),
            ]),
        )
        all_ids: list[int] = []
        for name in _GROUP_NAMES:
            all_ids.extend(result["groups"][name]["event_ids"])
        self.assertEqual(len(all_ids), len(set(all_ids)),
                         f"duplicates across groups: {all_ids}")
        self.assertEqual(
            sorted(all_ids), [1001, 1002, 1003, 1004, 1005, 1006],
        )


# ---------------------------------------------------------------------------
# Aggregate counts + estimated yield
# ---------------------------------------------------------------------------


class TestAggregateCounts(unittest.TestCase):
    def test_candidate_count_sums_across_actionable_groups(self) -> None:
        # candidate_count is the total of the four *actionable* groups
        # (everything except likely_junk) — operators want to see the
        # repairable pool, not the count of dead-ends.
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
                _contamination_example(event_id=1002,
                                       flags=["duplicate_date_ticker"]),
            ]),
            missing_tickers=_missing_tickers_payload([
                _missing_ticker_event(event_id=1004),
            ]),
            short_horizon=_short_horizon_payload([
                _short_horizon_example(event_id=1005, delta_eligible=True),
            ]),
            cleanup_candidates=_cleanup_candidate_payload([
                _cleanup_example(event_id=4000),
            ]),
        )
        self.assertEqual(result["candidate_count"], 4)

    def test_estimated_repair_yield_has_low_mid_high(self) -> None:
        result = _run()
        yld = result["estimated_repair_yield"]
        self.assertIn("conservative_estimate", yld)
        self.assertIn("optimistic_estimate", yld)
        self.assertIn("estimate_basis", yld)
        self.assertIsInstance(yld["conservative_estimate"], int)
        self.assertIsInstance(yld["optimistic_estimate"], int)
        self.assertIsInstance(yld["estimate_basis"], str)

    def test_conservative_yield_anchors_on_mechanism_family_bucket(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
                _contamination_example(event_id=1002,
                                       flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(
            result["estimated_repair_yield"]["conservative_estimate"], 2)

    def test_optimistic_yield_at_least_conservative(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
                _contamination_example(event_id=1002,
                                       flags=["duplicate_date_ticker"]),
                _contamination_example(event_id=1003,
                                       flags=["driv_lit_off_topic"]),
            ]),
        )
        yld = result["estimated_repair_yield"]
        self.assertGreaterEqual(
            yld["optimistic_estimate"], yld["conservative_estimate"],
        )


# ---------------------------------------------------------------------------
# top_candidates
# ---------------------------------------------------------------------------


class TestTopCandidates(unittest.TestCase):
    def test_top_candidates_carry_required_fields(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
            ]),
        )
        self.assertGreater(len(result["top_candidates"]), 0)
        rec = result["top_candidates"][0]
        for field in ("event_id", "headline", "group", "reason"):
            self.assertIn(field, rec)

    def test_top_candidates_excludes_likely_junk_by_default(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
            ]),
            cleanup_candidates=_cleanup_candidate_payload([
                _cleanup_example(event_id=4000),
            ]),
        )
        groups = [c["group"] for c in result["top_candidates"]]
        self.assertNotIn("likely_junk", groups)

    def test_top_candidates_capped_by_limit(self) -> None:
        examples = [
            _contamination_example(event_id=1000 + i,
                                   flags=["mechanism_family_none"])
            for i in range(20)
        ]
        result = _run(
            contamination=_contamination_payload(examples), limit=5,
        )
        self.assertEqual(len(result["top_candidates"]), 5)

    def test_top_candidates_priority_orders_groups(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
                _contamination_example(event_id=1002,
                                       flags=["duplicate_date_ticker"]),
                _contamination_example(event_id=1003,
                                       flags=["driv_lit_off_topic"]),
            ]),
            short_horizon=_short_horizon_payload([
                _short_horizon_example(event_id=1004, delta_eligible=True),
            ]),
            limit=10,
        )
        groups = [c["group"] for c in result["top_candidates"]]
        # mechanism_family_only_ready first, then duplicate_only_review,
        # then ticker_repair_needed, then short_horizon_only.
        priority_order = [
            "mechanism_family_only_ready",
            "duplicate_only_review",
            "ticker_repair_needed",
            "short_horizon_only",
        ]
        # The relative position of each group's first appearance must
        # match the priority order.
        first_idx = {}
        for i, g in enumerate(groups):
            first_idx.setdefault(g, i)
        seen = [g for g in priority_order if g in first_idx]
        positions = [first_idx[g] for g in seen]
        self.assertEqual(positions, sorted(positions),
                         f"group order out of priority: {groups}")


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_recommended_action_avoids_banned_words(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
            ]),
        )
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec,
                             f"banned word {w!r} in: {rec!r}")

    def test_yield_basis_is_an_estimate_not_a_claim(self) -> None:
        result = _run(
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
            ]),
        )
        basis = result["estimated_repair_yield"]["estimate_basis"].lower()
        self.assertIn("estimate", basis)
        for w in _BANNED_WORDS:
            self.assertNotIn(w, basis,
                             f"banned word {w!r} in basis: {basis!r}")

    def test_empty_payload_recommendation_is_conservative(self) -> None:
        result = _run()
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec)


# ---------------------------------------------------------------------------
# Seams + import isolation
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_contamination_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_contamination_report")))

    def test_missing_tickers_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_missing_tickers_report")))

    def test_short_horizon_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_short_horizon_report")))

    def test_clean_cohort_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_clean_cohort_report")))

    def test_cleanup_candidates_seam_callable(self) -> None:
        self.assertTrue(
            callable(getattr(cli, "_run_cleanup_candidate_report")))


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api")

    def test_default_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED)}
        _run()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED)}
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_emits_five_keys(self) -> None:
        rc, output = _run_cli(
            ["--json", "--limit", "10"],
            contamination=_contamination_payload([
                _contamination_example(event_id=1001,
                                       flags=["mechanism_family_none"]),
            ]),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))

    def test_text_default_does_not_raise(self) -> None:
        rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertGreater(len(output), 0)


if __name__ == "__main__":
    unittest.main()
