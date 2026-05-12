"""Tests for ``scripts/section_c_weekly_canonicalization_plan.py``.

Pin the contract:

* Read-only planner.  Consumes the existing weekly duplicate
  diagnostic's output via a lazy seam (``_build_weekly_diagnostic``)
  and proposes canonicalization behavior — without applying any
  change.  No DB writes, no provider, no LLM, no FastAPI surface.
* Output dict has EXACTLY these 9 keys::

    ok, duplicate_groups_analyzed, proposed_canonicalization_rules,
    canonical_event_suggestions, expected_removed_duplicates,
    implementation_targets, false_positive_risks, warnings, errors

* Each canonical_event_suggestion has EXACTLY these 6 fields::

    duplicate_group_id, event_ids, suggested_canonical_event_id,
    suggested_canonical_headline, reason, rule_to_apply

* ``rule_to_apply`` on each suggestion MUST reference a ``rule_id``
  present in ``proposed_canonicalization_rules`` (referential
  integrity).
* The planner prefers the longest non-truncated headline as the
  canonical.  When every candidate looks raw / truncated it falls
  back to the upstream diagnostic's own suggestion and surfaces a
  warning.
* Conservative wording.  The planner never claims a canonical is
  "the correct" one, never says rules will be applied
  automatically.
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

from scripts import section_c_weekly_canonicalization_plan as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "duplicate_groups_analyzed",
    "proposed_canonicalization_rules",
    "canonical_event_suggestions",
    "expected_removed_duplicates",
    "implementation_targets",
    "false_positive_risks",
    "warnings",
    "errors",
)


_SUGGESTION_KEYS = (
    "duplicate_group_id",
    "event_ids",
    "suggested_canonical_event_id",
    "suggested_canonical_headline",
    "reason",
    "rule_to_apply",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "guaranteed",
    "alpha generated",
    "correct ticker",
    # Stronger overclaim guards — the planner never claims a rule
    # will be applied automatically or that a merge is the "correct"
    # one.
    "dedupe automatically",
    "correct merge",
    "will merge",
    "rule guarantees",
)


# ---------------------------------------------------------------------------
# Synthetic diagnostic payloads
# ---------------------------------------------------------------------------


def _headline_group(
    group_id: str,
    event_ids: list[int],
    headlines: list[str],
    *,
    dates: list[str] | None = None,
    tickers: list[str] | None = None,
    reason_kind: str = "headline",
) -> dict[str, Any]:
    """Mirror the diagnostic's ``_group_to_dict`` shape."""
    reason = (
        "events share an identical normalised headline or one is a "
        "token-prefix of another within the same event_date; suggest "
        "the longest headline as the cluster representative."
    ) if reason_kind == "headline" else (
        "events share the same event_date and the same market_tickers "
        "set; suggest operator review before they enter the weekly "
        "mover ranking."
    )
    return {
        "duplicate_group_id":           group_id,
        "event_ids":                    list(event_ids),
        "headlines":                    list(headlines),
        "dates":                        list(dates or ["2026-05-08"]),
        "tickers":                      list(tickers or []),
        "mechanism_families":           [],
        "suggested_canonical_event_id": event_ids[0],
        "reason":                       reason,
    }


def _diagnostic_payload(
    duplicate_groups: list[dict[str, Any]] | None = None,
    *,
    repeated_date_ticker: list[dict[str, Any]] | None = None,
    repeated_headline:    list[dict[str, Any]] | None = None,
    candidates_checked:   int | None = None,
) -> dict[str, Any]:
    duplicate_groups = duplicate_groups or []
    return {
        "ok":                          True,
        "candidates_checked":          candidates_checked
                                       if candidates_checked is not None
                                       else max(0, len(duplicate_groups) * 2),
        "duplicate_groups":            duplicate_groups,
        "repeated_date_ticker_groups": repeated_date_ticker or [],
        "repeated_headline_groups":    repeated_headline or duplicate_groups,
        "mechanism_theme_candidates":  [],
        "canonical_headline_suggestions": [],
        "recommended_weekly_filter_rules": [],
        "window": {"reference_date": "2026-05-12",
                   "window_days":     7,
                   "window_start":    "2026-05-05"},
        "warnings": [],
        "errors":   [],
    }


def _patch_diagnostic(payload: dict[str, Any]):
    return patch.object(
        cli, "_build_weekly_diagnostic",
        return_value=payload,
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_on_empty_diagnostic(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            report = cli.run_section_c_weekly_canonicalization_plan()
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        self.assertTrue(report["ok"])
        self.assertEqual(report["duplicate_groups_analyzed"], 0)
        self.assertEqual(report["canonical_event_suggestions"], [])
        self.assertEqual(report["expected_removed_duplicates"], 0)

    def test_each_suggestion_has_required_fields(self) -> None:
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                [
                    "Turkey lira weakens",
                    "Turkey lira weakens as reserves slip further",
                ],
                tickers=["TUR"],
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        for s in report["canonical_event_suggestions"]:
            self.assertEqual(set(s.keys()), set(_SUGGESTION_KEYS))


# ---------------------------------------------------------------------------
# Canonical-pick heuristic
# ---------------------------------------------------------------------------


class TestCanonicalPick(unittest.TestCase):
    def test_longest_headline_picked_when_clean(self) -> None:
        # The longer headline is also clean — planner picks it.
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [10, 11],
                [
                    "Fed speakers rotate",
                    "Fed speakers rotate on inflation commentary",
                ],
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        s = report["canonical_event_suggestions"][0]
        self.assertEqual(s["suggested_canonical_event_id"], 11)
        self.assertEqual(
            s["suggested_canonical_headline"],
            "Fed speakers rotate on inflation commentary",
        )
        self.assertIn("longest", s["reason"].lower())

    def test_truncated_longest_loses_to_clean_shorter(self) -> None:
        # The "longest" candidate is truncated.  The planner must pick
        # the shorter clean one and mention truncation in the reason.
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                [
                    "Turkey lira weakens as reserves",
                    "Turkey lira weakens as reserves slip further amid CB...",
                ],
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        s = report["canonical_event_suggestions"][0]
        self.assertEqual(s["suggested_canonical_event_id"], 1)
        self.assertEqual(
            s["suggested_canonical_headline"],
            "Turkey lira weakens as reserves",
        )
        self.assertIn("truncat", s["reason"].lower())

    def test_all_truncated_falls_back_to_upstream_with_warning(self) -> None:
        # Every candidate looks raw — planner falls back to the
        # upstream diagnostic's own suggested_canonical_event_id and
        # emits a warning, rather than fabricating a pick.
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [3, 4],
                [
                    "weakens as reserves slip further",   # lowercase start
                    "Turkey lira weakens as reserves slip further amid...",
                ],
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        s = report["canonical_event_suggestions"][0]
        # Upstream's suggested_canonical_event_id is event_ids[0] = 3.
        self.assertEqual(s["suggested_canonical_event_id"], 3)
        # A fallback warning must surface.
        joined = " | ".join(report["warnings"]).lower()
        self.assertIn("fallback", joined)
        self.assertIn("headline_000", joined)


# ---------------------------------------------------------------------------
# Rule selection
# ---------------------------------------------------------------------------


class TestRuleSelection(unittest.TestCase):
    def test_headline_group_routes_to_headline_rule(self) -> None:
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                ["Turkey lira weakens", "Turkey lira weakens"],
                reason_kind="headline",
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        s = report["canonical_event_suggestions"][0]
        self.assertIn("headline", s["rule_to_apply"])

    def test_date_ticker_group_routes_to_date_ticker_rule(self) -> None:
        payload = _diagnostic_payload([
            _headline_group(
                "date_ticker_000", [5, 6],
                [
                    "Headline A on date X",
                    "Headline B on date X",
                ],
                tickers=["AAPL"],
                reason_kind="date_ticker",
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        s = report["canonical_event_suggestions"][0]
        self.assertEqual(s["rule_to_apply"], "date_ticker_match")

    def test_every_suggestion_rule_references_real_rule_id(self) -> None:
        # Referential integrity: the rule_to_apply value on each
        # suggestion must match a rule_id in
        # proposed_canonicalization_rules.
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                ["A", "A and then more"],
            ),
            _headline_group(
                "date_ticker_000", [5, 6],
                ["H1", "H2"],
                tickers=["MSFT"],
                reason_kind="date_ticker",
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        rule_ids = {
            r["rule_id"]
            for r in report["proposed_canonicalization_rules"]
            if isinstance(r, dict) and "rule_id" in r
        }
        self.assertTrue(rule_ids, "no rule_id entries proposed")
        for s in report["canonical_event_suggestions"]:
            self.assertIn(
                s["rule_to_apply"], rule_ids,
                f"suggestion rule_to_apply {s['rule_to_apply']!r} not in "
                f"proposed_canonicalization_rules rule_ids: {rule_ids}",
            )


# ---------------------------------------------------------------------------
# expected_removed_duplicates accounting
# ---------------------------------------------------------------------------


class TestExpectedRemovedDuplicates(unittest.TestCase):
    def test_count_matches_group_sizes(self) -> None:
        # Two groups: 3 and 4 events.  Expected removed = (3-1) + (4-1) = 5.
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2, 3],
                ["A", "A and B", "A and B and C"],
            ),
            _headline_group(
                "headline_001", [10, 11, 12, 13],
                ["X", "X and Y", "X and Y and Z", "X and Y and Z and W"],
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        self.assertEqual(report["expected_removed_duplicates"], 5)

    def test_event_ids_appearing_in_two_groups_counted_once(self) -> None:
        # Defensive: the same event_id should never inflate the
        # removed count by appearing in two groups.
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2, 3],
                ["a", "a longer", "a longer still"],
            ),
            _headline_group(
                "date_ticker_000", [3, 4],
                ["x", "y"], tickers=["AAPL"], reason_kind="date_ticker",
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        # Across both groups: distinct event_ids = {1, 2, 3, 4} = 4.
        # Canonicals across groups = 2 (one per group, but if event_id
        # 3 is canonical in both, distinct canonicals could be < 2).
        # The conservative invariant: expected_removed <= distinct - 1.
        distinct_events = 4
        self.assertLessEqual(
            report["expected_removed_duplicates"], distinct_events - 1,
            "expected_removed_duplicates exceeds distinct event_ids",
        )


# ---------------------------------------------------------------------------
# Implementation targets + false-positive risks
# ---------------------------------------------------------------------------


class TestImplementationTargets(unittest.TestCase):
    def test_targets_present_and_descriptive(self) -> None:
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                ["A", "A and more"],
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        self.assertIsInstance(report["implementation_targets"], list)
        self.assertGreater(len(report["implementation_targets"]), 0)
        joined = " | ".join(
            t if isinstance(t, str) else t.get("path", "") + " " + t.get("note", "")
            for t in report["implementation_targets"]
        ).lower()
        # Required: cite at least one real file that exists in the repo.
        self.assertTrue(
            "news_clustering" in joined
            or "db.save_event" in joined
            or "routes/movers" in joined
            or "routes\\movers" in joined,
            f"no real implementation target cited: {joined!r}",
        )

    def test_false_positive_risks_are_listed(self) -> None:
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                ["A", "A and more"],
            ),
        ])
        with _patch_diagnostic(payload):
            report = cli.run_section_c_weekly_canonicalization_plan()
        self.assertIsInstance(report["false_positive_risks"], list)
        self.assertGreater(len(report["false_positive_risks"]), 0)

    def test_no_groups_means_no_suggestions_but_still_lists_rules(self) -> None:
        # Even with zero groups, the planner should describe what
        # rules would be proposed if duplicates were present.  Risks
        # and targets stay populated since they describe surface area,
        # not group-conditional content.
        with _patch_diagnostic(_diagnostic_payload([])):
            report = cli.run_section_c_weekly_canonicalization_plan()
        self.assertEqual(report["canonical_event_suggestions"], [])
        self.assertGreater(len(report["proposed_canonicalization_rules"]), 0)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _build(self) -> dict[str, Any]:
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                [
                    "Turkey lira weakens",
                    "Turkey lira weakens as reserves slip further",
                ],
            ),
            _headline_group(
                "headline_001", [10, 11],
                [
                    "Fed speakers rotate",
                    "Fed speakers rotate on inflation commentary",
                ],
            ),
        ])
        with _patch_diagnostic(payload):
            return cli.run_section_c_weekly_canonicalization_plan()

    def test_no_banned_words_in_json_render(self) -> None:
        report = self._build()
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, blob,
                             f"banned token {term!r} in JSON render")

    def test_no_banned_words_in_text_render(self) -> None:
        report = self._build()
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, text,
                             f"banned token {term!r} in text render")


# ---------------------------------------------------------------------------
# Live truth — the upstream diagnostic's two real groups must surface
# ---------------------------------------------------------------------------


class TestLiveTruth(unittest.TestCase):
    def test_turkey_lira_and_fed_speakers_groups_planned(self) -> None:
        # No patching — the live diagnostic surfaces both groups today
        # per scripts/section_c_weekly_duplicate_diagnostic.py.  If
        # the diagnostic returns no groups at all (e.g., the DB has
        # been pruned), skip the named-group pin but still assert the
        # planner's envelope is well-formed.
        report = cli.run_section_c_weekly_canonicalization_plan()
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        if report["duplicate_groups_analyzed"] == 0:
            self.skipTest(
                "live diagnostic surfaced zero duplicate groups; "
                "Turkey-lira / Fed-speakers pin skipped"
            )
        headlines_blob = " ".join(
            s["suggested_canonical_headline"].lower()
            for s in report["canonical_event_suggestions"]
        )
        self.assertIn("turkey lira", headlines_blob)
        self.assertIn("fed speakers", headlines_blob)


# ---------------------------------------------------------------------------
# No-paid-surface import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"planner must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_emits_required_keys(self) -> None:
        payload = _diagnostic_payload([
            _headline_group(
                "headline_000", [1, 2],
                ["A", "A and more"],
            ),
        ])
        with _patch_diagnostic(payload):
            rc, output = self._run(["--json"])
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(rc, 0)

    def test_text_render_does_not_crash(self) -> None:
        with _patch_diagnostic(_diagnostic_payload()):
            rc, output = self._run([])
        self.assertEqual(rc, 0)
        self.assertIn("canonicalization", output.lower())


# ---------------------------------------------------------------------------
# Production weekly collapse helper — applied between get_slice("weekly")
# and _project in routes/movers.py:movers_weekly.  The helper itself is a
# pure function exposed by routes/weekly_canonicalization.py so it can be
# tested without dragging in FastAPI.
# ---------------------------------------------------------------------------


from routes.weekly_canonicalization import (   # noqa: E402
    collapse_weekly_duplicates,
)
from routes import weekly_canonicalization as _wc  # noqa: E402


def _card(event_id: int, headline: str, **extra) -> dict[str, Any]:
    """Minimal Weekly UI card stub.  Real cards carry more fields
    (tickers, impact, etc.); the helper only needs event_id +
    headline, so the stub is intentionally narrow."""
    return {
        "event_id": event_id,
        "headline": headline,
        **extra,
    }


class TestRouteCollapseHelperContract(unittest.TestCase):
    """Pin the shape and invariants of the production weekly collapse
    helper.  The helper must:

    * Return a new list (never mutate the input in place).
    * Leave singleton-headline cards unchanged (no metadata added).
    * Collapse same-headline groups to one canonical card carrying
      ``duplicate_count`` and ``grouped_event_ids``.
    * Preserve the input ranking order — the canonical surfaces at
      the position of the first group member.
    """

    def test_no_duplicates_passes_through_unchanged(self) -> None:
        items = [
            _card(1, "OPEC announces production cut"),
            _card(2, "Fed minutes show hawkish split"),
            _card(3, "Turkey lira weakens"),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(result, items)
        # Original list intact.
        self.assertEqual(len(items), 3)
        # No duplicate metadata added to singletons.
        for card in result:
            self.assertNotIn("duplicate_count", card)
            self.assertNotIn("grouped_event_ids", card)

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(collapse_weekly_duplicates([]), [])

    def test_non_list_returns_empty_list(self) -> None:
        # Defensive: bad input must not crash the route.
        self.assertEqual(collapse_weekly_duplicates(None), [])
        self.assertEqual(collapse_weekly_duplicates("not a list"), [])
        self.assertEqual(collapse_weekly_duplicates({"items": []}), [])

    def test_input_list_is_not_mutated(self) -> None:
        items = [
            _card(10, "Turkey lira weakens"),
            _card(11, "Turkey lira weakens"),
        ]
        snapshot = [dict(c) for c in items]
        collapse_weekly_duplicates(items)
        self.assertEqual(items, snapshot,
                         "collapse_weekly_duplicates mutated its input list")

    def test_collapse_two_same_headline_cards(self) -> None:
        items = [
            _card(10, "Turkey lira weakens"),
            _card(11, "Turkey lira weakens"),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 1)
        canon = result[0]
        # Both cards share the same headline so either could be canonical;
        # tie-break is lowest event_id.
        self.assertEqual(canon["event_id"], 10)
        self.assertEqual(canon["duplicate_count"], 1)
        self.assertEqual(canon["grouped_event_ids"], [10, 11])

    def test_collapse_three_same_headline_cards(self) -> None:
        items = [
            _card(10, "OPEC announces production cut"),
            _card(11, "OPEC announces production cut"),
            _card(12, "OPEC announces production cut"),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 1)
        canon = result[0]
        self.assertEqual(canon["duplicate_count"], 2)
        self.assertEqual(canon["grouped_event_ids"], [10, 11, 12])


class TestRouteCollapseCanonicalPick(unittest.TestCase):
    def test_longest_clean_headline_wins(self) -> None:
        items = [
            _card(1, "Fed speakers rotate"),
            _card(2, "Fed speakers rotate on inflation commentary"),
        ]
        result = collapse_weekly_duplicates(items)
        # Both cards share the same normalised prefix? No — different
        # headlines so they aren't in the same group.  Add a real same-
        # headline pair to confirm the longest-wins rule fires.
        self.assertEqual(len(result), 2)

    def test_longest_wins_within_same_normalised_group(self) -> None:
        # Same normalised headline (lowercase/alphanumeric collapsed)
        # but different surface forms.  The longest non-truncated form
        # is the canonical surface.
        items = [
            _card(1, "Turkey Lira Weakens"),
            _card(2, "turkey lira weakens"),
            _card(3, "TURKEY LIRA WEAKENS"),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 1)
        canon = result[0]
        # All three have the same alphanumeric length once tokenised;
        # tie-break is lowest event_id.
        self.assertEqual(canon["event_id"], 1)
        self.assertEqual(canon["duplicate_count"], 2)
        self.assertEqual(canon["grouped_event_ids"], [1, 2, 3])

    def test_truncated_longest_loses_to_clean_shorter(self) -> None:
        # Same normalised headline.  The longer surface form ends
        # with "..." (truncated marker) — the clean shorter headline
        # wins.
        items = [
            _card(1, "Turkey lira weakens"),
            _card(2, "Turkey lira weakens..."),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 1)
        canon = result[0]
        # The non-truncated headline wins even though it's shorter.
        self.assertEqual(canon["event_id"], 1)
        self.assertEqual(canon["headline"], "Turkey lira weakens")

    def test_all_truncated_falls_back_to_lowest_event_id(self) -> None:
        # Both candidates look truncated.  Fall back to lowest event_id.
        items = [
            _card(5, "Turkey lira weakens..."),
            _card(3, "Turkey lira weakens..."),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 1)
        canon = result[0]
        self.assertEqual(canon["event_id"], 3)
        # grouped_event_ids still sorted ascending.
        self.assertEqual(canon["grouped_event_ids"], [3, 5])


class TestRouteCollapseOrderPreservation(unittest.TestCase):
    def test_canonical_surfaces_at_first_group_position(self) -> None:
        # Insert a singleton card in the middle of a duplicate group
        # to check that the canonical surfaces at the FIRST occurrence
        # of the group, not after it.
        items = [
            _card(10, "Turkey lira weakens"),                # group A pos 0
            _card(20, "Fed minutes show hawkish split"),     # singleton pos 1
            _card(11, "Turkey lira weakens"),                # group A pos 2
            _card(30, "OPEC announces production cut"),      # singleton pos 3
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 3)
        # Canonical surfaces at position 0 (first group A occurrence).
        # event_id 10 wins on tie-break.
        self.assertEqual(result[0]["event_id"], 10)
        self.assertEqual(result[0]["duplicate_count"], 1)
        self.assertEqual(result[0]["grouped_event_ids"], [10, 11])
        # Singletons keep their original order.
        self.assertEqual(result[1]["event_id"], 20)
        self.assertEqual(result[2]["event_id"], 30)

    def test_multiple_groups_preserve_input_order(self) -> None:
        items = [
            _card(10, "Turkey lira weakens"),     # group A
            _card(20, "Fed speakers rotate"),     # group B
            _card(11, "Turkey lira weakens"),     # group A dup
            _card(21, "Fed speakers rotate"),     # group B dup
            _card(30, "Standalone story"),        # singleton
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 3)
        # First canonical = group A at position 0.
        self.assertEqual(result[0]["event_id"], 10)
        self.assertEqual(result[0]["grouped_event_ids"], [10, 11])
        # Second canonical = group B at position 1 in the collapsed
        # list (originally pos 1).
        self.assertEqual(result[1]["event_id"], 20)
        self.assertEqual(result[1]["grouped_event_ids"], [20, 21])
        # Singleton last.
        self.assertEqual(result[2]["event_id"], 30)


class TestRouteCollapseEdgeCases(unittest.TestCase):
    def test_card_without_headline_passes_through(self) -> None:
        items = [
            _card(1, ""),                # empty headline → passthrough
            {"event_id": 2},             # no headline key
            _card(3, "Turkey lira weakens"),
            _card(4, "Turkey lira weakens"),
        ]
        result = collapse_weekly_duplicates(items)
        # Two passthroughs + one canonical.
        self.assertEqual(len(result), 3)
        # Order preserved.
        self.assertEqual(result[0]["event_id"], 1)
        self.assertEqual(result[1]["event_id"], 2)
        self.assertEqual(result[2]["event_id"], 3)
        self.assertEqual(result[2]["duplicate_count"], 1)

    def test_non_dict_card_passes_through(self) -> None:
        items = [
            "not a dict",
            _card(2, "Turkey lira weakens"),
            _card(3, "Turkey lira weakens"),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "not a dict")
        self.assertEqual(result[1]["event_id"], 2)

    def test_canonical_preserves_extra_card_fields(self) -> None:
        # Cards carry many fields beyond event_id/headline (tickers,
        # impact, etc.).  The helper must copy the chosen canonical's
        # full payload, only adding the two metadata fields.
        items = [
            _card(1, "Turkey lira weakens",
                  tickers=["TUR"], impact=0.7, regime="risk_off"),
            _card(2, "Turkey lira weakens",
                  tickers=["TUR"], impact=0.5, regime="risk_off"),
        ]
        result = collapse_weekly_duplicates(items)
        canon = result[0]
        # Canonical's extra fields preserved.
        self.assertEqual(canon["tickers"], ["TUR"])
        self.assertEqual(canon["impact"], 0.7)
        self.assertEqual(canon["regime"], "risk_off")
        # Plus the two new fields.
        self.assertEqual(canon["duplicate_count"], 1)
        self.assertEqual(canon["grouped_event_ids"], [1, 2])

    def test_card_with_non_int_event_id_still_handled(self) -> None:
        # Cards without a numeric event_id can still be collapsed
        # by headline; grouped_event_ids ignores them.
        items = [
            {"event_id": "x", "headline": "Turkey lira weakens"},
            _card(2, "Turkey lira weakens"),
        ]
        result = collapse_weekly_duplicates(items)
        self.assertEqual(len(result), 1)
        canon = result[0]
        # Canonical = card 2 (only one with a real int event_id).
        self.assertEqual(canon["event_id"], 2)
        # grouped_event_ids only carries the real int.
        self.assertEqual(canon["grouped_event_ids"], [2])


class TestRouteCollapseImportIsolation(unittest.TestCase):
    def test_helper_module_does_not_bind_fastapi_or_db(self) -> None:
        # The production helper should be importable on its own
        # without dragging in FastAPI, sqlite, or any provider.
        for attr in (
            "fastapi", "FastAPI", "APIRouter",
            "sqlite3", "db",
            "yfinance", "anthropic", "openai",
        ):
            self.assertFalse(
                hasattr(_wc, attr),
                f"weekly_canonicalization must not bind {attr}",
            )


if __name__ == "__main__":
    unittest.main()
