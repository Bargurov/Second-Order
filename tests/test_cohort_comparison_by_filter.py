"""
tests/test_cohort_comparison_by_filter.py

Contract tests for ``compare_cohorts_by_filter`` — the declarative
filter-spec wrapper around ``compare_cohorts``.

Covers:
  1. Filter-spec schema — closed key set, unknown keys raise.
  2. Cohort selection by family / regime / compound_regime.
  3. Thin-sample refusal — n<3 per cohort yields available=False.
  4. Delegates to ``compare_cohorts`` and carries filter provenance
     through on the envelope.
  5. Auto-derived labels when caller doesn't provide them.
  6. Regime filters on select_cohort — filter arguments are wired.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from cohort_comparison import compare_cohorts_by_filter
from cohort_research import run_batch_research, select_cohort


def _event(
    eid: int,
    family: str,
    *,
    inflation: str = "neutral",
    policy: str = "neutral",
    compound: str = "goldilocks",
    stage: str = "realized",
    persistence: str = "medium",
    supports: int = 2,
    contradicts: int = 0,
    return_5d: float | None = 1.5,
    return_20d: float | None = 3.0,
) -> dict:
    """Build a minimal archive event row."""
    tickers: list[dict] = []
    for i in range(supports):
        tickers.append({
            "symbol": f"S{i}", "direction_tag": "supports thesis",
            "return_5d": return_5d, "return_20d": return_20d,
        })
    for i in range(contradicts):
        tickers.append({
            "symbol": f"C{i}", "direction_tag": "contradicts thesis",
            "return_5d": -abs(return_5d or 0) if return_5d is not None else None,
            "return_20d": -abs(return_20d or 0) if return_20d is not None else None,
        })
    return {
        "id":               eid,
        "headline":         f"Event {eid}",
        "event_date":       f"2026-03-{(eid % 28) + 1:02d}",
        "mechanism_family": family,
        "stage":            stage,
        "persistence":      persistence,
        "regime_snapshot":  json.dumps({
            "inflation":     inflation,
            "policy_stance": policy,
            "compound":      {"label": compound},
        }),
        "market_tickers":   json.dumps(tickers),
        "revisit_snapshots": json.dumps([]),
    }


# ---------------------------------------------------------------------------
# 1. Filter-spec validation
# ---------------------------------------------------------------------------

class TestFilterSpecValidation(unittest.TestCase):

    def test_unknown_key_raises_valueerror(self):
        with self.assertRaises(ValueError) as ctx:
            compare_cohorts_by_filter(
                [],
                {"family": "tariff", "geography": "EU"},
                {"family": "tariff"},
            )
        self.assertIn("unknown keys", str(ctx.exception).lower())

    def test_invalid_family_raises(self):
        with self.assertRaises(ValueError):
            compare_cohorts_by_filter(
                [],
                {"family": "not_a_family"},
                {"family": "tariff"},
            )

    def test_non_string_value_raises(self):
        with self.assertRaises(ValueError):
            compare_cohorts_by_filter(
                [],
                {"family": 123},  # non-string
                {"family": "tariff"},
            )

    def test_empty_filter_spec_is_valid(self):
        # Empty spec selects all events.  With thin samples it'll return
        # available=False/thin_sample, which is the expected behavior.
        result = compare_cohorts_by_filter([], {}, {})
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "thin_sample")

    def test_none_filter_is_valid(self):
        # None normalises to empty dict.
        result = compare_cohorts_by_filter([], None, None)
        self.assertFalse(result["available"])


# ---------------------------------------------------------------------------
# 2. Cohort selection by family / regime
# ---------------------------------------------------------------------------

class TestCohortSelection(unittest.TestCase):

    def _build_archive(self) -> list[dict]:
        """10 tariff events — 5 in reflation, 5 in stagflation_pulse."""
        events = []
        for i in range(5):
            events.append(_event(
                100 + i, "tariff", compound="reflation",
                supports=3, contradicts=0,
            ))
        for i in range(5):
            events.append(_event(
                200 + i, "tariff", compound="stagflation_pulse",
                supports=1, contradicts=2,
            ))
        return events

    def test_compound_regime_filter_applies(self):
        archive = self._build_archive()
        result = compare_cohorts_by_filter(
            archive,
            {"family": "tariff", "compound_regime": "reflation"},
            {"family": "tariff", "compound_regime": "stagflation_pulse"},
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["a_size"], 5)
        self.assertEqual(result["b_size"], 5)

    def test_inflation_axis_filter(self):
        events = []
        for i in range(3):
            events.append(_event(
                300 + i, "supply_shock", inflation="high",
                supports=3,
            ))
        for i in range(3):
            events.append(_event(
                400 + i, "supply_shock", inflation="low",
                supports=3,
            ))
        result = compare_cohorts_by_filter(
            events,
            {"family": "supply_shock", "regime_inflation": "high"},
            {"family": "supply_shock", "regime_inflation": "low"},
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["a_size"], 3)
        self.assertEqual(result["b_size"], 3)

    def test_policy_stance_axis_filter(self):
        events = []
        for i in range(3):
            events.append(_event(
                500 + i, "policy_surprise", policy="hawkish",
                supports=3,
            ))
        for i in range(3):
            events.append(_event(
                600 + i, "policy_surprise", policy="dovish",
                supports=3,
            ))
        result = compare_cohorts_by_filter(
            events,
            {"family": "policy_surprise", "regime_policy_stance": "hawkish"},
            {"family": "policy_surprise", "regime_policy_stance": "dovish"},
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["a_size"], 3)

    def test_family_comparison_same_regime(self):
        events = []
        for i in range(3):
            events.append(_event(700 + i, "tariff"))
        for i in range(3):
            events.append(_event(800 + i, "bank_stress"))
        result = compare_cohorts_by_filter(
            events,
            {"family": "tariff"},
            {"family": "bank_stress"},
        )
        self.assertTrue(result["available"])


# ---------------------------------------------------------------------------
# 3. Thin-sample refusal
# ---------------------------------------------------------------------------

class TestThinSampleRefusal(unittest.TestCase):

    def test_one_event_cohort_refuses(self):
        events = [
            _event(1, "tariff"),
            _event(2, "tariff"),
            _event(3, "tariff"),
            _event(4, "bank_stress"),   # only 1 event for cohort B
        ]
        result = compare_cohorts_by_filter(
            events,
            {"family": "tariff"},
            {"family": "bank_stress"},
        )
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "thin_sample")
        self.assertEqual(result["a_size"], 3)
        self.assertEqual(result["b_size"], 1)

    def test_both_cohorts_empty_refuses(self):
        result = compare_cohorts_by_filter(
            [_event(1, "tariff")],
            {"family": "sanction"},     # 0 matches
            {"family": "bank_stress"},  # 0 matches
        )
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "thin_sample")

    def test_thin_sample_returns_shaped_envelope(self):
        """Thin-sample failure still emits the full envelope so the UI
        doesn't have to special-case it."""
        result = compare_cohorts_by_filter(
            [_event(1, "tariff")],
            {"family": "tariff"},
            {"family": "tariff"},
        )
        required_keys = {
            "available", "reason", "a_label", "b_label",
            "a_size", "b_size", "filter_a", "filter_b",
            "confidence_basis", "dimensions", "divergence_score",
            "headline_insight", "rationale",
        }
        self.assertTrue(required_keys <= set(result.keys()))


# ---------------------------------------------------------------------------
# 4. Delegation + filter provenance
# ---------------------------------------------------------------------------

class TestDelegationAndProvenance(unittest.TestCase):

    def test_successful_comparison_carries_filter_provenance(self):
        events = [_event(i, "tariff", compound="reflation") for i in range(1, 4)]
        events += [_event(i, "tariff", compound="stagflation_pulse")
                    for i in range(100, 103)]
        result = compare_cohorts_by_filter(
            events,
            {"family": "tariff", "compound_regime": "reflation"},
            {"family": "tariff", "compound_regime": "stagflation_pulse"},
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["filter_a"]["compound_regime"], "reflation")
        self.assertEqual(result["filter_b"]["compound_regime"], "stagflation_pulse")

    def test_successful_comparison_has_dimensions(self):
        """Delegates to compare_cohorts → dimensions list is populated."""
        events = [_event(i, "tariff") for i in range(1, 4)]
        events += [_event(i, "bank_stress") for i in range(100, 103)]
        result = compare_cohorts_by_filter(
            events,
            {"family": "tariff"},
            {"family": "bank_stress"},
        )
        self.assertTrue(result["available"])
        self.assertGreater(len(result["dimensions"]), 0)

    def test_successful_comparison_has_headline_insight(self):
        events = [_event(i, "tariff", supports=3, contradicts=0)
                  for i in range(1, 4)]
        events += [_event(i, "bank_stress", supports=0, contradicts=3)
                    for i in range(100, 103)]
        result = compare_cohorts_by_filter(
            events,
            {"family": "tariff"},
            {"family": "bank_stress"},
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["headline_insight"])


# ---------------------------------------------------------------------------
# 5. Auto-derived labels
# ---------------------------------------------------------------------------

class TestAutoDerivedLabels(unittest.TestCase):

    def test_labels_compose_family_and_regime(self):
        events = [_event(i, "tariff", compound="reflation")
                  for i in range(1, 4)]
        events += [_event(i, "tariff", compound="stagflation_pulse")
                    for i in range(100, 103)]
        result = compare_cohorts_by_filter(
            events,
            {"family": "tariff", "compound_regime": "reflation"},
            {"family": "tariff", "compound_regime": "stagflation_pulse"},
        )
        self.assertIn("tariff", result["a_label"])
        self.assertIn("reflation", result["a_label"])
        self.assertIn("stagflation_pulse", result["b_label"])

    def test_explicit_labels_preferred_over_auto(self):
        events = [_event(i, "tariff") for i in range(1, 4)]
        events += [_event(i, "bank_stress") for i in range(100, 103)]
        result = compare_cohorts_by_filter(
            events,
            {"family": "tariff"},
            {"family": "bank_stress"},
            label_a="Tariff cohort",
            label_b="Bank-stress cohort",
        )
        self.assertEqual(result["a_label"], "Tariff cohort")
        self.assertEqual(result["b_label"], "Bank-stress cohort")


# ---------------------------------------------------------------------------
# 6. select_cohort regime-filter wiring
# ---------------------------------------------------------------------------

class TestSelectCohortRegimeFilter(unittest.TestCase):
    """The filter surface we expose on compare_cohorts_by_filter threads
    through run_batch_research → select_cohort.  Test the wiring
    directly so a future refactor doesn't silently drop the filter."""

    def test_select_cohort_inflation_filter(self):
        events = [
            _event(1, "supply_shock", inflation="high"),
            _event(2, "supply_shock", inflation="high"),
            _event(3, "supply_shock", inflation="low"),
        ]
        result = select_cohort(events, regime_inflation="high")
        self.assertEqual(result["size"], 2)
        self.assertEqual(result["filter"]["regime_inflation"], "high")

    def test_select_cohort_compound_regime_filter(self):
        events = [
            _event(1, "tariff", compound="reflation"),
            _event(2, "tariff", compound="stagflation_pulse"),
            _event(3, "tariff", compound="reflation"),
        ]
        result = select_cohort(events, compound_regime="reflation")
        self.assertEqual(result["size"], 2)
        self.assertEqual(result["filter"]["compound_regime"], "reflation")

    def test_run_batch_research_passes_regime_filter(self):
        events = [
            _event(1, "tariff", compound="reflation", supports=3),
            _event(2, "tariff", compound="reflation", supports=3),
            _event(3, "tariff", compound="stagflation_pulse", supports=0,
                    contradicts=3),
        ]
        report = run_batch_research(
            events,
            mechanism_family="tariff",
            compound_regime="reflation",
        )
        self.assertEqual(report["size"], 2)
        self.assertEqual(report["filter"].get("compound_regime"), "reflation")


if __name__ == "__main__":
    unittest.main()
