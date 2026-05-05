"""Tests for the dry-run auto-backfill candidate planner."""

from __future__ import annotations

import unittest

from auto_backfill_ledger import AutoBackfillLedger
from auto_backfill_planner import plan_auto_backfill_candidates


def _item(
    headline: str,
    *,
    rank_score: float = 1.0,
    source_count: int = 1,
    published_at: str = "2026-05-05T12:00:00Z",
    registry_state: str | None = None,
    skip_reason: str | None = None,
    already_analyzed: bool = False,
) -> dict:
    item = {
        "headline": headline,
        "rank_score": rank_score,
        "source_count": source_count,
        "published_at": published_at,
    }
    if registry_state is not None:
        item["registry_state"] = registry_state
    if skip_reason is not None:
        item["skip_reason"] = skip_reason
    if already_analyzed:
        item["already_analyzed"] = True
    return item


class BasicPlanningTests(unittest.TestCase):
    def test_empty_queue_returns_empty_plan(self):
        plan = plan_auto_backfill_candidates([], max_calls_per_run=2)

        self.assertEqual(plan.selected, ())
        self.assertEqual(plan.selected_count, 0)
        self.assertEqual(plan.eligible_count, 0)
        self.assertEqual(plan.considered_count, 0)
        self.assertTrue(all(count == 0 for count in plan.skip_counts.values()))
        self.assertEqual(plan.skip_reasons, {})

    def test_selects_up_to_max_calls_per_run(self):
        plan = plan_auto_backfill_candidates(
            [
                _item("first", rank_score=3),
                _item("second", rank_score=2),
                _item("third", rank_score=1),
            ],
            max_calls_per_run=2,
        )

        self.assertEqual([row["headline"] for row in plan.selected], ["first", "second"])
        self.assertEqual(plan.skip_counts["run_cap_exhausted"], 1)
        self.assertEqual(plan.skip_counts["daily_cap_exhausted"], 0)
        self.assertEqual(plan.effective_call_cap, 2)

    def test_zero_run_cap_selects_nothing(self):
        plan = plan_auto_backfill_candidates(
            [_item("first"), _item("second")],
            max_calls_per_run=0,
        )

        self.assertEqual(plan.selected, ())
        self.assertEqual(plan.skip_counts["run_cap_exhausted"], 2)


class SkipReasonTests(unittest.TestCase):
    def test_default_skips_analyzed_expired_and_skip_reason_rows(self):
        plan = plan_auto_backfill_candidates(
            [
                _item("already flag", already_analyzed=True),
                _item("already state", registry_state="market_checked"),
                _item("expired", registry_state="expired_low_impact"),
                _item("skipped", skip_reason="llm_budget_exhausted"),
                _item("eligible", rank_score=9),
            ],
            max_calls_per_run=10,
        )

        self.assertEqual([row["headline"] for row in plan.selected], ["eligible"])
        self.assertEqual(plan.skip_counts["already_analyzed"], 2)
        self.assertEqual(plan.skip_counts["expired_low_impact"], 1)
        self.assertEqual(plan.skip_counts["skip_reason"], 1)
        self.assertEqual(plan.skip_reasons, {"llm_budget_exhausted": 1})

    def test_raw_registry_skip_reasons_map_to_product_skip_buckets(self):
        plan = plan_auto_backfill_candidates(
            [
                _item("already", skip_reason="registry_already_analyzed"),
                _item("expired", skip_reason="registry_expired_low_impact"),
                _item("checked", skip_reason="already_market_checked"),
            ],
            max_calls_per_run=10,
        )

        self.assertEqual(plan.selected, ())
        self.assertEqual(plan.skip_counts["already_analyzed"], 2)
        self.assertEqual(plan.skip_counts["expired_low_impact"], 1)
        self.assertEqual(
            plan.skip_reasons,
            {
                "registry_already_analyzed": 1,
                "registry_expired_low_impact": 1,
                "already_market_checked": 1,
            },
        )

    def test_skip_reason_rows_can_be_explicitly_allowed(self):
        plan = plan_auto_backfill_candidates(
            [
                _item("budgeted", skip_reason="llm_budget_exhausted"),
                _item("clean"),
            ],
            max_calls_per_run=10,
            allow_skip_reasons=True,
        )

        self.assertEqual([row["headline"] for row in plan.selected], ["budgeted", "clean"])
        self.assertEqual(plan.skip_counts["skip_reason"], 0)

    def test_analyzed_and_expired_require_their_own_allow_flags(self):
        plan = plan_auto_backfill_candidates(
            [
                _item("analyzed", registry_state="analyzed"),
                _item("expired", registry_state="expired_low_impact"),
            ],
            max_calls_per_run=10,
            allow_skip_reasons=True,
            allow_already_analyzed=True,
            allow_expired_low_impact=True,
        )

        self.assertEqual([row["headline"] for row in plan.selected], ["analyzed", "expired"])
        self.assertEqual(plan.skip_counts["already_analyzed"], 0)
        self.assertEqual(plan.skip_counts["expired_low_impact"], 0)


class DailyCapTests(unittest.TestCase):
    def test_daily_remaining_limits_selected_count(self):
        plan = plan_auto_backfill_candidates(
            [_item("a", rank_score=3), _item("b", rank_score=2), _item("c", rank_score=1)],
            max_calls_per_run=3,
            daily_remaining=1,
        )

        self.assertEqual([row["headline"] for row in plan.selected], ["a"])
        self.assertEqual(plan.effective_call_cap, 1)
        self.assertEqual(plan.skip_counts["daily_cap_exhausted"], 2)
        self.assertEqual(plan.skip_counts["run_cap_exhausted"], 0)

    def test_daily_remaining_can_come_from_ledger_decision(self):
        ledger = AutoBackfillLedger(daily_cap=3)
        ledger.reserve_calls(2)
        decision = ledger.snapshot()

        plan = plan_auto_backfill_candidates(
            [_item("a", rank_score=2), _item("b", rank_score=1)],
            max_calls_per_run=2,
            daily_remaining=decision,
        )

        self.assertEqual(plan.daily_remaining, 1)
        self.assertEqual([row["headline"] for row in plan.selected], ["a"])
        self.assertEqual(plan.skip_counts["daily_cap_exhausted"], 1)

    def test_daily_remaining_can_come_from_mapping(self):
        plan = plan_auto_backfill_candidates(
            [_item("a"), _item("b")],
            max_calls_per_run=2,
            daily_remaining={"remaining": 0},
        )

        self.assertEqual(plan.selected, ())
        self.assertEqual(plan.skip_counts["daily_cap_exhausted"], 2)


class RankingTests(unittest.TestCase):
    def test_deterministic_ordering_uses_score_source_count_then_published_at(self):
        plan = plan_auto_backfill_candidates(
            [
                _item("lower score many sources", rank_score=8, source_count=99),
                _item(
                    "score tie newer",
                    rank_score=10,
                    source_count=2,
                    published_at="2026-05-05T09:00:00Z",
                ),
                _item(
                    "score tie older",
                    rank_score=10,
                    source_count=2,
                    published_at="2026-05-04T09:00:00Z",
                ),
                _item("top score fewer sources", rank_score=11, source_count=1),
                _item("source tie winner", rank_score=10, source_count=3),
            ],
            max_calls_per_run=10,
        )

        self.assertEqual(
            [row["headline"] for row in plan.selected],
            [
                "top score fewer sources",
                "source tie winner",
                "score tie newer",
                "score tie older",
                "lower score many sources",
            ],
        )

    def test_stable_tie_breaker_uses_headline_then_original_order(self):
        plan = plan_auto_backfill_candidates(
            [
                _item("charlie", rank_score=1),
                _item("alpha", rank_score=1),
                _item("alpha", rank_score=1),
            ],
            max_calls_per_run=10,
        )

        self.assertEqual(
            [row["headline"] for row in plan.selected],
            ["alpha", "alpha", "charlie"],
        )


class ValidationTests(unittest.TestCase):
    def test_invalid_and_missing_headline_rows_are_counted(self):
        plan = plan_auto_backfill_candidates(
            [
                {},  # missing headline
                "not a mapping",  # type: ignore[list-item]
                _item("valid"),
            ],
            max_calls_per_run=10,
        )

        self.assertEqual([row["headline"] for row in plan.selected], ["valid"])
        self.assertEqual(plan.skip_counts["missing_headline"], 1)
        self.assertEqual(plan.skip_counts["invalid_item"], 1)

    def test_negative_run_cap_rejected(self):
        with self.assertRaises(ValueError):
            plan_auto_backfill_candidates([], max_calls_per_run=-1)

    def test_non_integer_daily_remaining_rejected(self):
        with self.assertRaises(TypeError):
            plan_auto_backfill_candidates([], max_calls_per_run=1, daily_remaining=True)


if __name__ == "__main__":
    unittest.main()
