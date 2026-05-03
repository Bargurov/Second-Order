"""Tests for deepened policy-constraint detection.

Covers:
  * Macro-surprise linkage (CPI / PCE / NFP / Unemployment) contributes to
    the correct constraint with the documented point values
  * Macro-surprise window is respected (only days_until in -3..0 fires)
  * Front-end policy repricing detector fires when 2Y moves with a twisted
    curve, and is silent on parallel / quiet moves
  * policy_room widens with boxed_in (two conflicting mandates at severity)
    and free_to_respond (clean strong signal, no conflicts)
  * front_end_repricing_active downgrades policy_room one notch
  * Shape stability: new fields always present on the output
  * Back-compat: existing 4-positional-arg callers still work
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from policy_constraint import (
    compute_policy_constraint,
    _detect_front_end_repricing,
    _score_macro_surprises,
    _policy_room,
    _BOXED_IN_FLOOR,
    _FREE_TO_RESPOND_TOP,
)


def _rates(regime="Mixed", nom_5d=0.0, tip_5d=0.0, be_5d=0.0):
    return {
        "regime": regime, "available": True,
        "nominal":    {"label": "10Y", "value": 4.25, "change_5d": nom_5d},
        "real_proxy": {"label": "TIP", "value": 108.0, "change_5d": tip_5d},
        "breakeven_proxy": {"change_5d": be_5d},
        "raw": {"tnx": 4.25},
    }


def _stress(vix=False, credit=False, safe_haven=False, term_inv=False,
            breadth=False, regime="Calm", raw_hook=None):
    raw = {"vix": 18.0}
    if raw_hook:
        raw.update(raw_hook)
    return {
        "regime": regime,
        "signals": {
            "vix_elevated":          vix,
            "credit_widening":       credit,
            "safe_haven_bid":        safe_haven,
            "term_inversion":        term_inv,
            "breadth_deterioration": breadth,
        },
        "raw": raw,
    }


def _release(name, signal, days_until=-1):
    return {
        "name":             name,
        "release_date":     "2026-04-18",
        "period":           "Mar 2026",
        "status":           "recent",
        "days_until":       days_until,
        "surprise_signal":  signal,
        "headline_evidence": None,
    }


# ---------------------------------------------------------------------------
# _score_macro_surprises — pure helper
# ---------------------------------------------------------------------------

class TestMacroSurpriseScoring(unittest.TestCase):
    def test_none_releases_yields_no_deltas(self):
        deltas, rationales, log = _score_macro_surprises(None)
        self.assertEqual(log, [])
        for v in deltas.values():
            self.assertEqual(v, 0.0)

    def test_cpi_beat_adds_inflation_points(self):
        deltas, _rats, log = _score_macro_surprises([_release("CPI", "beat")])
        self.assertEqual(deltas["inflation"], 2)
        self.assertEqual(log[0]["indicator"], "CPI")
        self.assertEqual(log[0]["constraint"], "inflation")

    def test_nfp_miss_adds_growth_points(self):
        deltas, _rats, log = _score_macro_surprises([_release("NFP", "miss")])
        self.assertEqual(deltas["growth"], 2)

    def test_pce_beat_adds_inflation_points(self):
        deltas, _, _ = _score_macro_surprises([_release("PCE", "beat")])
        self.assertEqual(deltas["inflation"], 2)

    def test_unemployment_beat_adds_growth(self):
        """Unemployment 'beat' = higher than expected = growth concern."""
        deltas, _, _ = _score_macro_surprises([_release("Unemployment", "beat")])
        self.assertEqual(deltas["growth"], 2)

    def test_outside_window_skipped(self):
        """days_until beyond -3 is outside the in-window range."""
        deltas, _, log = _score_macro_surprises([_release("CPI", "beat", days_until=-5)])
        self.assertEqual(deltas["inflation"], 0)
        self.assertEqual(log, [])

    def test_in_line_and_unknown_ignored(self):
        deltas, _, log = _score_macro_surprises([
            _release("CPI", "in_line"),
            _release("NFP", "unknown"),
            _release("PCE", None),
        ])
        self.assertEqual(log, [])
        self.assertTrue(all(v == 0.0 for v in deltas.values()))


# ---------------------------------------------------------------------------
# _detect_front_end_repricing
# ---------------------------------------------------------------------------

class TestFrontEndRepricingDetector(unittest.TestCase):
    def test_twisted_curve_with_2y_move_fires(self):
        pack = {"twoy_5d_pp": 0.25, "slope_5d_pp": 0.20}
        active, rationale = _detect_front_end_repricing(pack)
        self.assertTrue(active)
        self.assertIn("hikes priced", rationale)

    def test_cuts_priced_when_2y_drops(self):
        pack = {"twoy_5d_pp": -0.22, "slope_5d_pp": -0.18}
        active, rationale = _detect_front_end_repricing(pack)
        self.assertTrue(active)
        self.assertIn("cuts priced", rationale)

    def test_small_2y_move_silent(self):
        """2Y only moved 5bps — below the 15bps threshold."""
        pack = {"twoy_5d_pp": 0.05, "slope_5d_pp": 0.20}
        active, _ = _detect_front_end_repricing(pack)
        self.assertFalse(active)

    def test_parallel_shift_silent(self):
        """2Y moved 25bps but curve didn't twist — 2s10s slope barely moved."""
        pack = {"twoy_5d_pp": 0.25, "slope_5d_pp": 0.05}
        active, _ = _detect_front_end_repricing(pack)
        self.assertFalse(active)

    def test_none_pack_silent(self):
        active, _ = _detect_front_end_repricing(None)
        self.assertFalse(active)

    def test_missing_fields_silent(self):
        active, _ = _detect_front_end_repricing({"some": "other"})
        self.assertFalse(active)


# ---------------------------------------------------------------------------
# policy_room: boxed_in + free_to_respond
# ---------------------------------------------------------------------------

class TestPolicyRoomWidened(unittest.TestCase):
    def test_boxed_in_when_two_conflicting_mandates_both_severe(self):
        """Inflation AND growth both clearing the severity floor → boxed_in."""
        scores = {
            "inflation": _BOXED_IN_FLOOR + 0.5,
            "growth":    _BOXED_IN_FLOOR + 0.3,
            "financial_stability": 0.0,
            "external_balance": 0.0,
            "fiscal": 0.0,
        }
        self.assertEqual(
            _policy_room("inflation", scores, rates_usable=True, stress_usable=True),
            "boxed_in",
        )

    def test_free_to_respond_when_clean_strong_signal(self):
        """Top score clears free_to_respond threshold AND no secondary fires."""
        scores = {cid: 0.0 for cid in (
            "inflation", "growth", "financial_stability",
            "external_balance", "fiscal",
        )}
        scores["inflation"] = _FREE_TO_RESPOND_TOP + 1.0
        self.assertEqual(
            _policy_room("inflation", scores, rates_usable=True, stress_usable=True),
            "free_to_respond",
        )

    def test_non_conflict_pair_does_not_box_in(self):
        """Financial stability + external balance aren't in the conflict set
        — a high-severity pairing there reads as mixed, not boxed_in."""
        scores = {
            "inflation": 0.0, "growth": 0.0,
            "financial_stability": _BOXED_IN_FLOOR + 1,
            "external_balance":    _BOXED_IN_FLOOR + 1,
            "fiscal": 0.0,
        }
        out = _policy_room("financial_stability", scores, True, True)
        self.assertNotEqual(out, "boxed_in")

    def test_front_end_repricing_downgrades_one_notch(self):
        """When front-end repricing is active, free_to_respond → ample,
        ample → limited, limited → constrained."""
        scores = {cid: 0.0 for cid in (
            "inflation", "growth", "financial_stability",
            "external_balance", "fiscal",
        )}
        scores["inflation"] = _FREE_TO_RESPOND_TOP + 1.0

        raw = _policy_room("inflation", scores, True, True, front_end_repricing=False)
        downgraded = _policy_room("inflation", scores, True, True, front_end_repricing=True)
        self.assertEqual(raw, "free_to_respond")
        self.assertEqual(downgraded, "ample")

    def test_boxed_in_not_downgraded_by_front_end(self):
        """boxed_in is already tighter than ample; front-end repricing
        doesn't narrow it further."""
        scores = {
            "inflation": _BOXED_IN_FLOOR + 0.5,
            "growth":    _BOXED_IN_FLOOR + 0.3,
            "financial_stability": 0.0,
            "external_balance": 0.0,
            "fiscal": 0.0,
        }
        out = _policy_room("inflation", scores, True, True, front_end_repricing=True)
        self.assertEqual(out, "boxed_in")


# ---------------------------------------------------------------------------
# compute_policy_constraint integration
# ---------------------------------------------------------------------------

class TestComputePolicyConstraintDeepened(unittest.TestCase):
    def test_back_compat_without_new_kwargs(self):
        """Existing call signature (4 positional + snapshots kwarg) still
        works — the new kwargs default to safe None values."""
        result = compute_policy_constraint(
            "Fed signals hawkish pivot", "inflation pressure rising",
            _rates(regime="Inflation pressure", nom_5d=0.15, tip_5d=-0.1, be_5d=0.15),
            _stress(),
            snapshots=None,
        )
        self.assertEqual(result["binding"], "inflation")
        self.assertIn("policy_room", result)
        self.assertIn("front_end_repricing_active", result)
        self.assertFalse(result["front_end_repricing_active"])
        self.assertEqual(result["macro_surprise_signals"], [])

    def test_cpi_beat_reinforces_inflation_binding(self):
        """A CPI-beat release bumps the inflation score — when the base
        signals are modest, the surprise can flip the binding."""
        result = compute_policy_constraint(
            "Fed speakers rotate", "mild inflation mentions",
            _rates(regime="Mixed"),
            _stress(),
            snapshots=None,
            macro_releases=[_release("CPI", "beat")],
        )
        self.assertEqual(result["binding"], "inflation")
        log = result["macro_surprise_signals"]
        self.assertTrue(any(e["indicator"] == "CPI" and e["signal"] == "beat"
                            for e in log))

    def test_front_end_repricing_flagged_and_downgrades_room(self):
        """A twisted 2Y move narrows a would-be ample policy_room."""
        rates_pack = {"twoy_5d_pp": 0.25, "slope_5d_pp": 0.22}
        rates_ctx = _rates(regime="Inflation pressure", nom_5d=0.15,
                           tip_5d=-0.1, be_5d=0.15)
        baseline = compute_policy_constraint(
            "Inflation persistence risk", "CPI sticky, wages hot",
            rates_ctx, _stress(),
            snapshots=None,
        )
        downgraded = compute_policy_constraint(
            "Inflation persistence risk", "CPI sticky, wages hot",
            rates_ctx, _stress(),
            snapshots=None,
            rates_pack=rates_pack,
        )
        self.assertTrue(downgraded["front_end_repricing_active"])
        self.assertIn("hikes priced",
                      downgraded["front_end_repricing_rationale"])
        # Downgraded must be strictly tighter than baseline.
        order = {"free_to_respond": 6, "ample": 5, "limited": 4,
                 "constrained": 3, "boxed_in": 2, "mixed": 1, "unknown": 0}
        self.assertLess(order[downgraded["policy_room"]],
                        order[baseline["policy_room"]])

    def test_boxed_in_when_inflation_and_financial_stability_both_fire(self):
        """Stagflation-adjacent stress: inflation regime + credit widening +
        VIX elevated → inflation and financial_stability both above severity
        floor → boxed_in."""
        result = compute_policy_constraint(
            "CPI run-rate hot; HY spreads widen on bank stress",
            "inflation sticky and credit spreads widening simultaneously",
            _rates(regime="Inflation pressure", nom_5d=0.2, tip_5d=-0.15,
                   be_5d=0.2),
            _stress(vix=True, credit=True, regime="Systemic Stress"),
            snapshots=None,
            macro_releases=[_release("CPI", "beat")],
        )
        self.assertEqual(result["policy_room"], "boxed_in")
        self.assertIn("boxed in", result["why"])

    def test_front_end_mentioned_in_why_when_active(self):
        result = compute_policy_constraint(
            "Inflation risk elevated", "CPI hot",
            _rates(regime="Inflation pressure", nom_5d=0.15,
                   tip_5d=-0.1, be_5d=0.15),
            _stress(),
            snapshots=None,
            rates_pack={"twoy_5d_pp": 0.22, "slope_5d_pp": 0.18},
        )
        self.assertIn("Front-end repricing", result["why"])

    def test_output_shape_always_carries_new_fields(self):
        """Every compute_policy_constraint return that isn't {} carries the
        three new fields so the frontend shape is stable."""
        result = compute_policy_constraint(
            "anything", "anything",
            _rates(), _stress(), snapshots=None,
        )
        self.assertIn("front_end_repricing_active", result)
        self.assertIn("front_end_repricing_rationale", result)
        self.assertIn("macro_surprise_signals", result)


# ---------------------------------------------------------------------------
# Release-facts consumption inside policy-constraint scoring
# ---------------------------------------------------------------------------

def _facts_release(
    name: str,
    *,
    days_until: int = -1,
    actual: float | None = None,
    prior: float | None = None,
    revised_prior: float | None = None,
    consensus: float | None = None,
    upstream_signal: str | None = None,
) -> dict:
    """Build a release dict shaped like ``get_macro_releases`` output with
    stored facts attached.  ``upstream_signal`` simulates the signal the
    heuristic path would have produced from a news headline — policy-
    constraint's facts-first rule must override it when facts are present.
    """
    return {
        "name":                name,
        "release_date":        "2026-04-18",
        "period":              "Mar 2026",
        "status":              "recent",
        "days_until":          days_until,
        "release_key":         f"{name}:2026-04-18",
        "actual":              actual,
        "prior":               prior,
        "revised_prior":       revised_prior,
        "consensus":           consensus,
        "release_facts_source": "BLS",
        "has_release_facts":   True,
        "surprise_signal":     upstream_signal,
        "headline_evidence":   None,
    }


class TestPolicyConstraintUsesReleaseFacts(unittest.TestCase):
    """Task contract: when macro-release facts exist, policy-constraint
    reasoning must be driven by ``actual`` / ``prior`` / ``revised_prior``
    / ``consensus`` before any heuristic inference; revisions count; the
    no-facts fallback keeps the existing headline-based behaviour."""

    # ---- 1. actual vs consensus surprise (facts override heuristic) -----

    def test_facts_beat_overrides_headline_in_line_guess(self):
        """CPI actual 3.5 vs consensus 3.0 must be scored as a beat even
        when the upstream heuristic said 'in_line' — facts win."""
        releases = [_facts_release(
            "CPI", actual=3.5, prior=3.0, consensus=3.0,
            upstream_signal="in_line",
        )]
        deltas, _rat, log = _score_macro_surprises(releases)
        self.assertEqual(deltas["inflation"], 2)
        self.assertTrue(
            any(e["indicator"] == "CPI" and e["signal"] == "beat"
                for e in log),
            f"expected facts-derived CPI beat in log, got {log}",
        )

    def test_facts_miss_when_actual_below_consensus(self):
        """PCE actual 2.4 vs consensus 3.0 — facts say miss even though
        upstream heuristic fed a 'beat' guess."""
        releases = [_facts_release(
            "PCE", actual=2.4, prior=2.8, consensus=3.0,
            upstream_signal="beat",
        )]
        deltas, _rat, _log = _score_macro_surprises(releases)
        # PCE miss maps to growth +1 under _SURPRISE_SCORES.
        self.assertEqual(deltas["growth"], 1)
        self.assertEqual(deltas["inflation"], 0.0)

    def test_facts_in_line_does_not_score_as_surprise(self):
        """A 3% print against a 3% consensus sits inside the 5% relative
        band — no surprise points even if upstream heuristic guessed
        'beat' from a noisy headline."""
        releases = [_facts_release(
            "CPI", actual=3.05, prior=3.0, consensus=3.0,
            upstream_signal="beat",
        )]
        deltas, _rat, log = _score_macro_surprises(releases)
        self.assertEqual(deltas["inflation"], 0.0)
        self.assertEqual(log, [])

    def test_facts_signal_reaches_binding_via_compute_policy_constraint(self):
        """End-to-end: a stored CPI beat bumps the inflation score high
        enough to become the binding constraint, with the official
        signal visible in the surfaced surprise log."""
        result = compute_policy_constraint(
            "Fed speakers quiet day", "sideways rates commentary",
            _rates(regime="Mixed"), _stress(), snapshots=None,
            macro_releases=[_facts_release(
                "CPI", actual=3.4, prior=3.0, consensus=3.0,
                upstream_signal="in_line",
            )],
        )
        self.assertEqual(result["binding"], "inflation")
        self.assertTrue(any(
            e["indicator"] == "CPI" and e["signal"] == "beat"
            for e in result["macro_surprise_signals"]
        ))

    # ---- 2. revision-only signal ---------------------------------------

    def test_revision_only_nfp_down_scores_growth(self):
        """An in-line NFP print with the prior revised DOWN by 20k on a
        200k base should still contribute to the growth constraint —
        the back-window revelation is real signal, not noise."""
        releases = [_facts_release(
            "NFP",
            actual=200_000, prior=200_000, revised_prior=180_000,
            consensus=200_000, upstream_signal="in_line",
        )]
        deltas, _rat, log = _score_macro_surprises(releases)
        # Surprise side: in-line → no surprise points.
        # Revision side: NFP down → growth +1.
        self.assertEqual(deltas["growth"], 1)
        self.assertTrue(any(e["signal"] == "revision_down" for e in log),
                        f"expected revision_down entry, got {log}")

    def test_revision_up_on_cpi_fires_inflation(self):
        """CPI prior revised upward is hotter-than-thought back-window
        inflation — inflation constraint picks up a point."""
        releases = [_facts_release(
            "CPI",
            actual=3.0, prior=2.8, revised_prior=3.0, consensus=3.0,
            upstream_signal="in_line",
        )]
        deltas, _rat, _log = _score_macro_surprises(releases)
        self.assertEqual(deltas["inflation"], 1)

    def test_revision_surprise_stack_independently(self):
        """A beat AND an upward revision on the same print should both
        contribute — revisions are additive to surprise, not a
        replacement."""
        releases = [_facts_release(
            "CPI",
            actual=3.5, prior=2.8, revised_prior=3.0, consensus=3.0,
            upstream_signal="in_line",
        )]
        deltas, _rat, log = _score_macro_surprises(releases)
        # Surprise: CPI beat → inflation +2.
        # Revision: CPI up    → inflation +1.
        self.assertEqual(deltas["inflation"], 3)
        signals = {e["signal"] for e in log}
        self.assertIn("beat", signals)
        self.assertIn("revision_up", signals)

    def test_small_revision_ignored_as_noise(self):
        """A 0.05pp revision on a 3.0 prior (≈1.7%) sits inside the 5%
        band and must not count as a revision signal."""
        releases = [_facts_release(
            "CPI",
            actual=3.0, prior=3.0, revised_prior=3.05, consensus=3.0,
            upstream_signal=None,
        )]
        deltas, _rat, log = _score_macro_surprises(releases)
        self.assertEqual(deltas["inflation"], 0.0)
        self.assertEqual(log, [])

    def test_revision_outside_window_is_skipped(self):
        """A 10-day-old release is outside the [-3, 0] window — neither
        surprise nor revision should fire."""
        releases = [_facts_release(
            "NFP", days_until=-10,
            actual=200_000, prior=200_000, revised_prior=150_000,
            consensus=200_000,
        )]
        deltas, _rat, log = _score_macro_surprises(releases)
        for v in deltas.values():
            self.assertEqual(v, 0.0)
        self.assertEqual(log, [])

    # ---- 3. no-data fallback keeps the heuristic path alive -------------

    def test_no_facts_falls_back_to_upstream_signal(self):
        """Without ``has_release_facts``, the existing heuristic
        ``surprise_signal`` drives scoring exactly as before."""
        release = {
            "name":              "CPI",
            "release_date":      "2026-04-18",
            "status":            "recent",
            "days_until":        -1,
            "surprise_signal":   "beat",
            "headline_evidence": "CPI beat expectations",
            # No has_release_facts / actual / consensus fields.
        }
        deltas, _rat, log = _score_macro_surprises([release])
        self.assertEqual(deltas["inflation"], 2)
        self.assertTrue(any(e["indicator"] == "CPI" for e in log))

    def test_has_facts_but_consensus_missing_falls_back(self):
        """``has_release_facts`` is True but ``consensus`` is None — the
        surprise path bails and the upstream ``surprise_signal`` kicks
        in as the fallback."""
        release = _facts_release(
            "CPI", actual=3.5, prior=3.0,
            consensus=None, upstream_signal="beat",
        )
        deltas, _rat, _log = _score_macro_surprises([release])
        self.assertEqual(deltas["inflation"], 2)

    def test_output_shape_stable_under_facts_path(self):
        """Driving the surprise via stored facts must not change the
        top-level keys on the policy-constraint result."""
        from_facts = compute_policy_constraint(
            "anything", "anything",
            _rates(), _stress(), snapshots=None,
            macro_releases=[_facts_release(
                "CPI", actual=3.5, prior=3.0, consensus=3.0,
            )],
        )
        heuristic = compute_policy_constraint(
            "anything", "anything",
            _rates(), _stress(), snapshots=None,
            macro_releases=[_release("CPI", "beat")],
        )
        # Same top-level shape regardless of which path supplied the signal.
        self.assertEqual(set(from_facts.keys()), set(heuristic.keys()))
        for key in (
            "binding", "binding_label", "secondary", "policy_room", "why",
            "reaction_function", "key_markets", "signals",
            "front_end_repricing_active", "front_end_repricing_rationale",
            "macro_surprise_signals", "available", "stale",
        ):
            self.assertIn(key, from_facts)


if __name__ == "__main__":
    unittest.main()
