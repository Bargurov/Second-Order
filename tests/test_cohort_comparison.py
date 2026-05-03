"""Tests for cohort_comparison — side-by-side cohort diff."""

from __future__ import annotations

import unittest

from cohort_comparison import (
    MAGNITUDES,
    _PP_LARGE,
    _PP_MEDIUM,
    _PP_SMALL,
    _RATE_LARGE,
    _RATE_MEDIUM,
    _RATE_SMALL,
    compare_cohorts,
)
from cohort_research import run_batch_research


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _ticker(role: str, r5: float | None, r20: float | None) -> dict:
    return {"symbol": "X", "role": role, "return_5d": r5, "return_20d": r20}


def _event(
    eid: int,
    family: str = "none",
    stage: str = "confirmed",
    persistence: str = "medium",
    tickers=None,
    regime: dict | None = None,
) -> dict:
    ev = {
        "id": eid,
        "headline": f"Headline {eid}",
        "event_date": f"2025-01-{eid:02d}",
        "mechanism_family": family,
        "stage": stage,
        "persistence": persistence,
        "market_tickers": tickers or [],
    }
    if regime is not None:
        ev["regime_snapshot"] = regime
    return ev


def _holding_events(n: int, family: str = "tariff") -> list[dict]:
    return [
        _event(i, family, tickers=[_ticker("beneficiary", 2.0, 4.0)])
        for i in range(1, n + 1)
    ]


def _fading_events(n: int, family: str = "tariff") -> list[dict]:
    return [
        _event(i, family, tickers=[_ticker("beneficiary", 0.5, 4.0)])
        for i in range(1, n + 1)
    ]


def _contradicted_events(n: int, family: str = "tariff") -> list[dict]:
    # Beneficiaries that went down → falsified (persistence still holds at
    # 20d in magnitude, but the sign violates the thesis).
    return [
        _event(i, family, tickers=[_ticker("beneficiary", -2.0, -4.0)])
        for i in range(1, n + 1)
    ]


def _faded_events(n: int, family: str = "tariff") -> list[dict]:
    """Events whose 20d return decayed below the hold threshold — the
    ``persistence`` axis reports faded even if repricing-path labels
    classify them as Negligible.
    """
    return [
        _event(i, family, tickers=[_ticker("beneficiary", 0.1, 0.3)])
        for i in range(1, n + 1)
    ]


def _accelerating_failing_events(n: int, family: str = "tariff") -> list[dict]:
    """Beneficiaries with accelerating negative drift — repricing label
    = Accelerating, persistence holds, and the role-sign flip makes
    every event a falsification.
    """
    return [
        _event(i, family, tickers=[_ticker("beneficiary", -3.0, -1.0)])
        for i in range(1, n + 1)
    ]


def _report(events: list[dict], label: str, **filters) -> dict:
    if not filters:
        return run_batch_research(events, cohort_label=label)
    return run_batch_research(events, cohort_label=label, **filters)


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

class TestShape(unittest.TestCase):
    def test_report_now_carries_composition(self):
        r = _report(_holding_events(5), "A")
        self.assertIn("composition", r)
        self.assertIn("mechanism_family", r["composition"])
        self.assertIn("stage", r["composition"])
        self.assertIn("persistence_label", r["composition"])
        self.assertIn("regime", r["composition"])

    def test_comparison_shape(self):
        a = _report(_holding_events(5), "Holders")
        b = _report(_fading_events(5), "Faders")
        c = compare_cohorts(a, b)
        for key in [
            "a_label", "b_label", "a_size", "b_size",
            "confidence_basis", "dimensions", "divergence_score",
            "headline_insight", "rationale",
        ]:
            self.assertIn(key, c, f"missing key {key}")

    def test_dimensions_cover_all_axes(self):
        a = _report(_holding_events(5), "A")
        b = _report(_fading_events(5), "B")
        c = compare_cohorts(a, b)
        axes = {d["axis"] for d in c["dimensions"]}
        self.assertEqual(
            axes,
            {
                "repricing_path", "hold_rate", "failure_rate", "mean_20d",
                "mechanism_family", "stage", "persistence_label", "regime",
            },
        )

    def test_magnitudes_pinned(self):
        self.assertEqual(MAGNITUDES, ("noise", "small", "medium", "large"))

    def test_thresholds_pinned(self):
        self.assertGreater(_RATE_LARGE, _RATE_MEDIUM)
        self.assertGreater(_RATE_MEDIUM, _RATE_SMALL)
        self.assertGreater(_PP_LARGE, _PP_MEDIUM)
        self.assertGreater(_PP_MEDIUM, _PP_SMALL)


# ---------------------------------------------------------------------------
# Dimension correctness
# ---------------------------------------------------------------------------

class TestDimensions(unittest.TestCase):
    def _dim(self, c: dict, axis: str) -> dict:
        return next(d for d in c["dimensions"] if d["axis"] == axis)

    def test_repricing_path_divergence(self):
        a = _report(_holding_events(5), "Holders")
        b = _report(_fading_events(5), "Faders")
        c = compare_cohorts(a, b)
        d = self._dim(c, "repricing_path")
        self.assertEqual(d["a_value"], "holding")
        self.assertEqual(d["b_value"], "fading")
        self.assertIn(d["magnitude"], {"medium", "large"})

    def test_hold_rate_identical_is_noise(self):
        a = _report(_holding_events(5), "A")
        b = _report(_holding_events(5), "B")
        c = compare_cohorts(a, b)
        d = self._dim(c, "hold_rate")
        self.assertEqual(d["delta"], 0.0)
        self.assertEqual(d["magnitude"], "noise")
        self.assertEqual(d["direction"], "tie")

    def test_hold_rate_large_divergence(self):
        a = _report(_holding_events(5), "A")  # hold_rate ~1.0
        b = _report(_faded_events(5), "B")    # hold_rate ~0.0
        c = compare_cohorts(a, b)
        d = self._dim(c, "hold_rate")
        self.assertAlmostEqual(d["delta"], 1.0, places=2)
        self.assertEqual(d["magnitude"], "large")
        self.assertEqual(d["direction"], "a")

    def test_failure_rate_detection(self):
        a = _report(_holding_events(5), "Clean")
        b = _report(_contradicted_events(5), "Contradicted")
        c = compare_cohorts(a, b)
        d = self._dim(c, "failure_rate")
        # a failure rate = 0, b failure rate = 1.0
        self.assertEqual(d["direction"], "b")
        self.assertEqual(d["magnitude"], "large")

    def test_mean_20d_delta(self):
        a = _report(_holding_events(5), "Positive")   # mean_20d = 4.0
        b = _report(_contradicted_events(5), "Negative")  # mean_20d = -4.0
        c = compare_cohorts(a, b)
        d = self._dim(c, "mean_20d")
        self.assertAlmostEqual(d["delta"], 8.0, places=1)
        self.assertEqual(d["magnitude"], "large")

    def test_regime_composition_diff(self):
        a_events = _holding_events(5)
        for e in a_events:
            e["regime_snapshot"] = {
                "inflation": "rising", "policy_stance": "hawkish",
            }
        b_events = _holding_events(5)
        for e in b_events:
            e["regime_snapshot"] = {
                "inflation": "falling", "policy_stance": "dovish",
            }
        a = _report(a_events, "Hawkish")
        b = _report(b_events, "Dovish")
        c = compare_cohorts(a, b)
        d = self._dim(c, "regime")
        self.assertEqual(d["magnitude"], "large")
        self.assertNotEqual(d["a_top"], d["b_top"])

    def test_family_composition_diff(self):
        a = _report(_holding_events(5, "tariff"), "Tariff")
        b = _report(_holding_events(5, "sanction"), "Sanction")
        c = compare_cohorts(a, b)
        d = self._dim(c, "mechanism_family")
        self.assertEqual(d["a_top"], "tariff")
        self.assertEqual(d["b_top"], "sanction")
        self.assertEqual(d["magnitude"], "large")

    def test_rounding_deterministic(self):
        a = _report(_holding_events(5), "A")
        b = _report(_fading_events(5), "B")
        c1 = compare_cohorts(a, b)
        c2 = compare_cohorts(a, b)
        self.assertEqual(c1, c2)


# ---------------------------------------------------------------------------
# Divergence score
# ---------------------------------------------------------------------------

class TestDivergenceScore(unittest.TestCase):
    def test_identical_cohorts_score_zero(self):
        a = _report(_holding_events(5), "A")
        b = _report(_holding_events(5), "B")
        c = compare_cohorts(a, b)
        self.assertEqual(c["divergence_score"], 0.0)

    def test_maximally_different_cohorts_score_high(self):
        # Repricing path (holding vs accelerating), failure rate, and
        # mean_20d all diverge large → score should clear 0.5.
        a = _report(_holding_events(5), "Holders")
        b = _report(_accelerating_failing_events(5), "Accel-failures")
        c = compare_cohorts(a, b)
        self.assertGreater(c["divergence_score"], 0.5)

    def test_divergence_bounded(self):
        a = _report(_holding_events(5), "A")
        b = _report(_contradicted_events(5), "B")
        c = compare_cohorts(a, b)
        self.assertGreaterEqual(c["divergence_score"], 0.0)
        self.assertLessEqual(c["divergence_score"], 1.0)


# ---------------------------------------------------------------------------
# Headline insight
# ---------------------------------------------------------------------------

class TestHeadlineInsight(unittest.TestCase):
    def test_similar_cohorts_emit_rhyme_line(self):
        a = _report(_holding_events(5), "A")
        b = _report(_holding_events(5), "B")
        c = compare_cohorts(a, b)
        self.assertIn("rhyme", c["headline_insight"].lower())

    def test_repricing_divergence_surfaces(self):
        a = _report(_holding_events(5), "Holders")
        b = _report(_fading_events(5), "Faders")
        c = compare_cohorts(a, b)
        self.assertIn("repricing", c["headline_insight"].lower())

    def test_falsification_divergence_surfaces(self):
        a = _report(_holding_events(5), "Clean")
        b = _report(_contradicted_events(5), "Contradicted")
        c = compare_cohorts(a, b)
        hi = c["headline_insight"].lower()
        self.assertTrue(
            "falsified" in hi
            or "fails faster" in hi
            or "diverges" in hi
            or "follow-through" in hi,
            f"unexpected headline: {c['headline_insight']}",
        )

    def test_insight_mentions_both_labels(self):
        a = _report(_holding_events(5), "Alpha")
        b = _report(_fading_events(5), "Beta")
        c = compare_cohorts(a, b)
        self.assertIn("Alpha", c["headline_insight"])
        self.assertIn("Beta", c["headline_insight"])


# ---------------------------------------------------------------------------
# Confidence floor
# ---------------------------------------------------------------------------

class TestConfidenceFloor(unittest.TestCase):
    def test_floor_takes_lower(self):
        a = _report(_holding_events(15), "Big")    # deep
        b = _report(_holding_events(4), "Small")   # medium
        c = compare_cohorts(a, b)
        self.assertEqual(c["confidence_basis"], "medium")

    def test_thin_cohort_marks_basis_thin(self):
        a = _report(_holding_events(15), "Big")
        b = _report(_holding_events(1), "Tiny")
        c = compare_cohorts(a, b)
        self.assertEqual(c["confidence_basis"], "thin")


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------

class TestDefensive(unittest.TestCase):
    def test_none_cohort_a(self):
        b = _report(_holding_events(5), "B")
        c = compare_cohorts(None, b)
        self.assertEqual(c["a_size"], 0)
        self.assertEqual(c["confidence_basis"], "thin")
        self.assertIn("Cannot compare", c["headline_insight"])

    def test_none_cohort_b(self):
        a = _report(_holding_events(5), "A")
        c = compare_cohorts(a, None)
        self.assertEqual(c["b_size"], 0)

    def test_both_none(self):
        c = compare_cohorts(None, None)
        self.assertEqual(c["a_size"], 0)
        self.assertEqual(c["b_size"], 0)
        self.assertEqual(c["divergence_score"], 0.0)

    def test_empty_cohort_a(self):
        a = _report([], "Empty")
        b = _report(_holding_events(5), "Full")
        c = compare_cohorts(a, b)
        self.assertEqual(c["a_size"], 0)
        self.assertIn("Cannot compare", c["headline_insight"])

    def test_non_dict_cohort_treated_as_empty(self):
        c = compare_cohorts("garbage", [1, 2, 3])
        self.assertEqual(c["a_size"], 0)
        self.assertEqual(c["b_size"], 0)

    def test_missing_composition_degrades_gracefully(self):
        a = {
            "cohort_label": "A", "size": 5,
            "persistence": {"hold_rate": 0.6, "mean_20d": 4.0, "scored": 5},
            "repricing_path": {"typical": "holding", "typical_share": 0.8},
            "falsification": {"event_failure_rate": 0.0, "scored_events": 5,
                              "failed_events": 0, "ticker_failure_rate": 0.0,
                              "scored_tickers": 5, "ticker_contradictions": 0},
            "confidence_basis": "medium",
        }
        b = dict(a)
        b["cohort_label"] = "B"
        c = compare_cohorts(a, b)
        # Missing composition → distance = 0 → noise
        regime_dim = next(d for d in c["dimensions"] if d["axis"] == "regime")
        self.assertEqual(regime_dim["magnitude"], "noise")


# ---------------------------------------------------------------------------
# End-to-end research scenario
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):
    def test_tariff_across_regimes_scenario(self):
        """'How did tariff cycles differ across regimes?' scenario."""
        hawkish_events = []
        for i in range(1, 8):
            hawkish_events.append(_event(
                i, "tariff",
                tickers=[_ticker("beneficiary", 2.0, 4.0)],
                regime={"inflation": "rising", "policy_stance": "hawkish"},
            ))
        dovish_events = []
        for i in range(20, 27):
            dovish_events.append(_event(
                i, "tariff",
                tickers=[_ticker("beneficiary", 0.4, 4.0)],
                regime={"inflation": "falling", "policy_stance": "dovish"},
            ))

        all_events = hawkish_events + dovish_events
        hawkish_report = run_batch_research(
            all_events, mechanism_family="tariff",
            cohort_label="Tariff · Hawkish",
        )
        dovish_report = run_batch_research(
            all_events, mechanism_family="tariff",
            cohort_label="Tariff · Dovish",
        )

        # Restrict each cohort by regime filter (done manually here)
        hawkish_report_h = run_batch_research(
            hawkish_events, mechanism_family="tariff",
            cohort_label="Tariff · Hawkish",
        )
        dovish_report_d = run_batch_research(
            dovish_events, mechanism_family="tariff",
            cohort_label="Tariff · Dovish",
        )

        c = compare_cohorts(hawkish_report_h, dovish_report_d)

        # Both tariff, both held (r20=4.0 in both) → repricing paths differ
        # because hawkish has r5=2.0 → holding, dovish r5=0.4 → fading.
        by_axis = {d["axis"]: d for d in c["dimensions"]}
        self.assertEqual(by_axis["mechanism_family"]["a_top"], "tariff")
        self.assertEqual(by_axis["mechanism_family"]["b_top"], "tariff")
        # Regime composition diverges
        self.assertEqual(by_axis["regime"]["magnitude"], "large")
        # Repricing path diverges
        self.assertNotEqual(
            by_axis["repricing_path"]["a_value"],
            by_axis["repricing_path"]["b_value"],
        )

    def test_funding_squeeze_follow_through_scenario(self):
        """'Which funding-squeeze cohort had stronger follow-through?'"""
        strong = [
            _event(i, "bank_stress",
                   tickers=[_ticker("beneficiary", 2.5, 5.0)])
            for i in range(1, 8)
        ]
        weak = [
            _event(i, "bank_stress",
                   tickers=[_ticker("beneficiary", 0.3, 0.4)])
            for i in range(20, 27)
        ]
        a = run_batch_research(strong, mechanism_family="bank_stress",
                               cohort_label="Strong Banks")
        b = run_batch_research(weak, mechanism_family="bank_stress",
                               cohort_label="Weak Banks")
        c = compare_cohorts(a, b)
        # Strong cohort's hold rate is high, weak is low → direction == "a"
        hold = next(d for d in c["dimensions"] if d["axis"] == "hold_rate")
        self.assertEqual(hold["direction"], "a")
        self.assertEqual(hold["magnitude"], "large")


if __name__ == "__main__":
    unittest.main()
