"""
tests/test_finance_playbook.py

Contract tests for the finance playbook synthesis composer.

Covers:
  1. Per-block line composers: each line correctly summarises its
     upstream block and degrades to a dash when the block is missing.
  2. Headline: composed from regime + funding + thesis + rotation;
     falls back to a quiet-tape string when nothing is firing.
  3. Base case: thesis status echo + key sectors sourced from rotation.
  4. Key risks: structural (5d/20d failures), funding escalation,
     regime flipping, thin calibration, missing analogs — all
     surface with the right severity.
  5. "What would change the read": pulls LLM-written falsifiers from
     the scorecard, adds regime-flip and funding-escalation watches.
  6. Coherence flags: deterministic contradiction detection between
     compound regime, funding mode, rotation tilt, and thesis status.
  7. Total-missing input returns a well-formed shape with
     available=False.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finance_playbook import compose_finance_playbook


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _regime_snapshot(label="reflation", confidence=0.8,
                     transition="stable", changed_axes=None) -> dict:
    return {
        "available":       True,
        "stale":            False,
        "inflation":        "hot",
        "policy_stance":    "hawkish",
        "credit":           "risk_on",
        "fx":               "dollar_weak",
        "growth_stress":    "calm",
        "curve_shape":      "parallel",
        "inflation_path":   "hawkish_constraint",
        "compound": {"label": label, "confidence": confidence,
                     "rationale": "test", "matched_axes": [], "candidates": []},
        "transition": {"state": transition,
                        "changed_axes": changed_axes or [],
                        "rationale": "test"},
    }


def _funding_mode(primary="none", severity="none", active=None) -> dict:
    return {
        "available":           True,
        "primary_mode":        primary,
        "composite_severity":  severity,
        "active_modes":        active or ([primary] if severity != "none" else []),
        "modes": {
            m: {"fired": m == primary and severity != "none",
                "severity": severity if m == primary else "none"}
            for m in ("duration_shock", "credit_widening",
                     "dollar_shortage", "liquidity_squeeze")
        },
        "rationale": "test",
    }


def _scorecard(status="on_track", resolved=3, pending=0,
               per_horizon=None) -> dict:
    return {
        "available":       True,
        "timing_profile":  "fast_shock",
        "per_horizon":     per_horizon or [],
        "aggregate": {
            "status":             status,
            "resolved_horizons":   resolved,
            "pending_horizons":    pending,
            "rationale":           "test",
        },
    }


def _horizon(name, status, falsifiers=None, contradicting=None) -> dict:
    return {
        "horizon":                 name,
        "status":                  status,
        "expected_criteria":       [],
        "confirmation_criteria":   [],
        "falsification_criteria":  falsifiers or [],
        "realized": {
            "supporting":     [],
            "contradicting":   contradicting or [],
            "flat":           [],
            "pending":        [],
        },
        "rationale": "test",
    }


def _calibration(hit_rate=0.6, n=20, depth="family+regime", weak=False) -> dict:
    return {
        "hit_rate":        hit_rate,
        "n":               n,
        "depth_tier":      depth,
        "weak":            weak,
        "sample_warning":  None,
    }


def _rotation(tilt="neutral", winners=None, losers=None) -> dict:
    sectors: list[dict] = []
    for sym in winners or []:
        sectors.append({"symbol": sym, "direction": "winner", "net_score": 1.5})
    for sym in losers or []:
        sectors.append({"symbol": sym, "direction": "loser", "net_score": -1.5})
    # Mark available=True whenever a tilt is given explicitly — tests that
    # only want to probe the tilt (e.g. coherence flag tests) don't need
    # to seed individual winners/losers.
    available = bool(sectors) or tilt != "neutral"
    return {
        "available":              available,
        "broad_market_tilt":      tilt,
        "broad_market_drivers":   [],
        "sectors":                sectors,
        "winners":                {"direct": winners or [], "second_order": []},
        "losers":                 {"direct":  losers or [],  "second_order": []},
        "rationale":              "test",
    }


def _analog(headline, final_score=0.7, reason="shared: test") -> dict:
    return {"headline": headline, "final_score": final_score,
            "match_reason": reason}


# ---------------------------------------------------------------------------
# 1. Per-block lines
# ---------------------------------------------------------------------------

class TestLineComposers(unittest.TestCase):

    def test_regime_line_reports_compound_and_transition(self):
        playbook = compose_finance_playbook({
            "regime_snapshot": _regime_snapshot(label="stagflation_pulse",
                                                 transition="shifting"),
        })
        self.assertIn("stagflation_pulse", playbook["lines"]["regime"])
        self.assertIn("shifting", playbook["lines"]["regime"])

    def test_regime_line_handles_unavailable_snapshot(self):
        playbook = compose_finance_playbook({})
        self.assertIn("—", playbook["lines"]["regime"])

    def test_regime_line_flags_flipping_axes(self):
        snap = _regime_snapshot(
            transition="flipping",
            changed_axes=[{"axis": "credit", "before": "risk_on",
                           "after": "risk_off", "direction": "flip"}],
        )
        playbook = compose_finance_playbook({"regime_snapshot": snap})
        self.assertIn("FLIPPING", playbook["lines"]["regime"])
        self.assertIn("credit", playbook["lines"]["regime"])

    def test_funding_line_names_primary_and_active(self):
        playbook = compose_finance_playbook({
            "funding_stress_mode": _funding_mode(
                primary="credit_widening", severity="elevated",
                active=["credit_widening", "liquidity_squeeze"],
            ),
        })
        line = playbook["lines"]["funding"]
        self.assertIn("credit_widening", line)
        self.assertIn("elevated", line)
        self.assertIn("liquidity_squeeze", line)

    def test_funding_line_quiet_when_nothing_fires(self):
        playbook = compose_finance_playbook({
            "funding_stress_mode": _funding_mode(primary="none", severity="none"),
        })
        self.assertIn("quiet", playbook["lines"]["funding"])

    def test_thesis_line_embeds_calibration_when_available(self):
        playbook = compose_finance_playbook({
            "thesis_scorecard":        _scorecard(status="on_track", resolved=3),
            "confidence_calibration":  _calibration(hit_rate=0.58, n=18,
                                                     depth="family"),
        })
        line = playbook["lines"]["thesis"]
        self.assertIn("on_track", line)
        self.assertIn("58%", line)
        self.assertIn("family", line)

    def test_thesis_line_marks_thin_calibration(self):
        playbook = compose_finance_playbook({
            "thesis_scorecard":        _scorecard(status="on_track"),
            "confidence_calibration":  _calibration(hit_rate=0.4, n=4,
                                                     depth="global", weak=True),
        })
        self.assertIn("thin", playbook["lines"]["thesis"])

    def test_rotation_line_lists_top_winners_and_losers(self):
        playbook = compose_finance_playbook({
            "sector_rotation": _rotation(
                tilt="risk_off",
                winners=["XLP", "XLV"],
                losers=["XLK", "KRE"],
            ),
        })
        line = playbook["lines"]["rotation"]
        self.assertIn("risk_off", line)
        self.assertIn("XLP", line)
        self.assertIn("KRE", line)

    def test_analog_line_sorts_by_final_score(self):
        playbook = compose_finance_playbook({
            "historical_analogs": [
                _analog("lower-scored event", final_score=0.4),
                _analog("top-scored event", final_score=0.9),
            ],
        })
        self.assertIn("top-scored event", playbook["lines"]["analogs"])
        self.assertIn("0.90", playbook["lines"]["analogs"])

    def test_analog_line_reports_none_when_empty(self):
        playbook = compose_finance_playbook({"historical_analogs": []})
        self.assertIn("none matched", playbook["lines"]["analogs"])


# ---------------------------------------------------------------------------
# 2. Headline
# ---------------------------------------------------------------------------

class TestHeadline(unittest.TestCase):

    def test_quiet_tape_headline(self):
        p = compose_finance_playbook({})
        self.assertIn("Quiet tape", p["headline"])

    def test_compound_regime_in_headline(self):
        p = compose_finance_playbook({
            "regime_snapshot": _regime_snapshot(label="stagflation_pulse"),
        })
        self.assertIn("stagflation", p["headline"].lower())

    def test_rich_headline_composes_multiple_dimensions(self):
        p = compose_finance_playbook({
            "regime_snapshot": _regime_snapshot(label="funding_stress"),
            "funding_stress_mode": _funding_mode(
                primary="credit_widening", severity="acute",
            ),
            "thesis_scorecard": _scorecard(status="on_track"),
            "sector_rotation": _rotation(tilt="risk_off"),
        })
        for piece in ("funding stress", "credit widening acute",
                       "thesis on_track", "tape risk_off"):
            self.assertIn(piece.lower(), p["headline"].lower())


# ---------------------------------------------------------------------------
# 3. Base case
# ---------------------------------------------------------------------------

class TestBaseCase(unittest.TestCase):

    def test_base_case_echoes_thesis_status_and_sectors(self):
        p = compose_finance_playbook({
            "thesis_scorecard": _scorecard(status="on_track"),
            "sector_rotation": _rotation(
                tilt="risk_on", winners=["XLE", "XLB"], losers=["XLU"],
            ),
        })
        bc = p["base_case"]
        self.assertEqual(bc["thesis_status"], "on_track")
        self.assertEqual(bc["key_sectors"]["long"], ["XLE", "XLB"])
        self.assertEqual(bc["key_sectors"]["short"], ["XLU"])
        self.assertIn("thesis on_track", bc["rationale"])

    def test_base_case_quiet_fallback(self):
        p = compose_finance_playbook({})
        self.assertEqual(p["base_case"]["thesis_status"], "pending")
        self.assertIn("quiet tape", p["base_case"]["rationale"].lower())


# ---------------------------------------------------------------------------
# 4. Key risks
# ---------------------------------------------------------------------------

class TestKeyRisks(unittest.TestCase):

    def test_structural_thesis_failure_is_acute_risk(self):
        p = compose_finance_playbook({
            "thesis_scorecard": _scorecard(
                status="breaking", resolved=2, pending=1,
                per_horizon=[
                    _horizon("5d", "failed",
                              contradicting=[{"symbol": "XOM"}, {"symbol": "CVX"}]),
                ],
            ),
        })
        risks = p["key_risks"]
        self.assertTrue(any(r["severity"] == "acute" and "5d" in r["risk"]
                            for r in risks))
        self.assertTrue(any("XOM" in r["driver"] for r in risks))

    def test_funding_elevated_fires_risk(self):
        p = compose_finance_playbook({
            "funding_stress_mode": _funding_mode(
                primary="credit_widening", severity="elevated",
            ),
        })
        self.assertTrue(any(r["severity"] == "elevated" for r in p["key_risks"]))

    def test_regime_flipping_surfaces_as_risk(self):
        p = compose_finance_playbook({
            "regime_snapshot": _regime_snapshot(
                transition="flipping",
                changed_axes=[{"axis": "credit", "before": "risk_on",
                                "after": "risk_off", "direction": "flip"}],
            ),
        })
        risks = p["key_risks"]
        self.assertTrue(any("Regime flipping" in r["risk"] for r in risks))

    def test_thin_calibration_flagged_when_thesis_resolved(self):
        p = compose_finance_playbook({
            "thesis_scorecard":       _scorecard(status="on_track"),
            "confidence_calibration": _calibration(weak=True, depth="global"),
        })
        self.assertTrue(any("Calibration is thin" in r["risk"]
                            for r in p["key_risks"]))

    def test_no_analogs_surfaces_as_watch_risk(self):
        p = compose_finance_playbook({"historical_analogs": []})
        self.assertTrue(any("No historical analog" in r["risk"]
                            for r in p["key_risks"]))

    def test_pending_thesis_no_structural_risk(self):
        """A pending thesis should NOT surface a failure risk."""
        p = compose_finance_playbook({
            "thesis_scorecard": _scorecard(status="pending", resolved=0, pending=3),
        })
        self.assertFalse(any("Thesis failed" in r["risk"] for r in p["key_risks"]))


# ---------------------------------------------------------------------------
# 5. What would change the read
# ---------------------------------------------------------------------------

class TestWhatWouldChange(unittest.TestCase):

    def test_pulls_5d_and_20d_falsifiers(self):
        p = compose_finance_playbook({
            "thesis_scorecard": _scorecard(
                per_horizon=[
                    _horizon("1d",  "confirmed",
                              falsifiers=["1d falsifier should be IGNORED"]),
                    _horizon("5d",  "confirmed",
                              falsifiers=["5d falsifier A", "5d falsifier B"]),
                    _horizon("20d", "confirmed",
                              falsifiers=["20d falsifier"]),
                ],
            ),
        })
        watches = p["what_would_change_the_read"]
        joined = " | ".join(watches)
        self.assertIn("5d falsifier A", joined)
        self.assertIn("20d falsifier", joined)
        self.assertNotIn("1d falsifier", joined)

    def test_skips_falsifiers_for_already_failed_horizons(self):
        p = compose_finance_playbook({
            "thesis_scorecard": _scorecard(
                per_horizon=[
                    _horizon("5d", "failed",
                              falsifiers=["don't re-list failed horizon"]),
                ],
            ),
        })
        joined = " | ".join(p["what_would_change_the_read"])
        self.assertNotIn("don't re-list", joined)

    def test_regime_flip_watch_added_when_compound_present(self):
        p = compose_finance_playbook({
            "regime_snapshot": _regime_snapshot(label="reflation",
                                                 transition="stable"),
        })
        joined = " | ".join(p["what_would_change_the_read"])
        self.assertIn("reflation", joined)
        self.assertIn("flipping", joined)

    def test_funding_escalation_watch(self):
        p = compose_finance_playbook({
            "funding_stress_mode": _funding_mode(
                primary="duration_shock", severity="mild",
            ),
        })
        joined = " | ".join(p["what_would_change_the_read"])
        self.assertIn("duration_shock", joined)
        self.assertIn("elevated", joined)


# ---------------------------------------------------------------------------
# 6. Coherence flags
# ---------------------------------------------------------------------------

class TestCoherenceFlags(unittest.TestCase):

    def test_reflation_with_acute_credit_widening_flagged(self):
        p = compose_finance_playbook({
            "regime_snapshot": _regime_snapshot(label="reflation"),
            "funding_stress_mode": _funding_mode(
                primary="credit_widening", severity="acute",
            ),
        })
        self.assertTrue(any("conflicts" in f for f in p["coherence_flags"]))

    def test_funding_stress_compound_without_firing_mode_flagged(self):
        p = compose_finance_playbook({
            "regime_snapshot":     _regime_snapshot(label="funding_stress"),
            "funding_stress_mode": _funding_mode(primary="none", severity="none"),
        })
        self.assertTrue(any("no funding mode firing" in f
                            for f in p["coherence_flags"]))

    def test_breaking_thesis_with_risk_on_tape_flagged(self):
        p = compose_finance_playbook({
            "thesis_scorecard": _scorecard(status="breaking"),
            "sector_rotation":  _rotation(tilt="risk_on"),
        })
        self.assertTrue(any("thesis breaking but rotation tape is risk_on" in f
                            for f in p["coherence_flags"]))

    def test_on_track_inside_risk_off_acute_flagged(self):
        p = compose_finance_playbook({
            "thesis_scorecard":    _scorecard(status="on_track"),
            "sector_rotation":     _rotation(tilt="risk_off"),
            "funding_stress_mode": _funding_mode(
                primary="liquidity_squeeze", severity="acute",
            ),
        })
        self.assertTrue(any("tail risk" in f.lower()
                            for f in p["coherence_flags"]))

    def test_weak_calibration_no_analogs_flagged(self):
        p = compose_finance_playbook({
            "thesis_scorecard":       _scorecard(status="on_track"),
            "confidence_calibration": _calibration(weak=True),
            "historical_analogs":     [],
        })
        self.assertTrue(any("priors are thin" in f for f in p["coherence_flags"]))


# ---------------------------------------------------------------------------
# 7. Total-missing input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):

    def test_empty_analysis_returns_well_formed_shape(self):
        p = compose_finance_playbook({})
        self.assertFalse(p["available"])
        # Every documented key must still exist so callers can dereference.
        for key in (
            "headline", "lines", "base_case", "key_risks",
            "what_would_change_the_read", "coherence_flags", "sources_used",
        ):
            self.assertIn(key, p)
        self.assertEqual(p["sources_used"], [])

    def test_none_input_also_safe(self):
        p = compose_finance_playbook(None)
        self.assertFalse(p["available"])
        self.assertEqual(p["base_case"]["thesis_status"], "pending")


if __name__ == "__main__":
    unittest.main()
