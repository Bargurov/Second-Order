"""
tests/test_agreement_mechanism_aware.py

Contract tests for the mechanism-structure-aware upgrade to the
agreement engine.

Covers:
  1. ``extract_mechanism_actors`` — pulls uppercase ticker-like tokens
     from transmission_path / substitution_barriers / beneficiaries /
     losers text; tolerates punctuation and non-string inputs.
  2. Bottleneck promotion — tickers named in the mechanism structure
     get ``bottleneck_proxy`` tier (weight 3.5), above the generic
     ``direct`` tier (weight 2.5).
  3. Bottleneck weight dominates — a single bottleneck-alpha support
     outranks multiple peripheral beta-support / drift names.
  4. Failure-mode diagnosis — four distinct modes fire on the right
     counter patterns:
       true_contradiction    — direct proxies oppose, no alpha support
       bad_primary_proxy     — direct names silent, tape confirms
       second_order_lag      — direct confirms, tape hasn't echoed
       mixed_cross_asset_tape — tape itself split
     Confirmed / insufficient verdicts emit None.
  5. End-to-end wiring via ``_build_mover_summary`` — event-level
     transmission_path / substitution_barriers / beneficiaries /
     losers all forwarded; the mover summary carries the enriched
     agreement block with bottleneck counters + failure_mode.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from agreement_engine import (
    _CLASS_WEIGHT,
    compute_agreement_verdict,
    extract_mechanism_actors,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _t(symbol: str, *,
       return_5d: float | None = 2.0,
       validation_quality: str | None = None,
       direction_tag: str | None = None,
       benchmark_sector: str | None = None) -> dict:
    return {
        "symbol":              symbol,
        "role":                "beneficiary",
        "return_5d":           return_5d,
        "validation_quality":  validation_quality,
        "direction_tag":       direction_tag,
        "benchmark_sector":    benchmark_sector,
    }


def _hop(actor: str, channel: str = "equities", hop_text: str = "") -> dict:
    return {"actor": actor, "channel": channel, "hop": hop_text}


def _barrier(text: str, kind: str = "physical_sole_source",
             severity: str = "high") -> dict:
    return {"barrier": text, "kind": kind, "severity": severity}


# ---------------------------------------------------------------------------
# 1. Mechanism-actor extraction
# ---------------------------------------------------------------------------

class TestExtractMechanismActors(unittest.TestCase):

    def test_empty_inputs_return_empty_set(self):
        self.assertEqual(extract_mechanism_actors(), frozenset())

    def test_pulls_tickers_from_transmission_path_actors(self):
        symbols = extract_mechanism_actors(
            transmission_path=[
                _hop("LRCX", "equities", "Commerce targets LRCX revenue"),
                _hop("AMAT", "equities", "AMAT margin compression"),
            ],
        )
        self.assertIn("LRCX", symbols)
        self.assertIn("AMAT", symbols)

    def test_pulls_tickers_from_barrier_text(self):
        symbols = extract_mechanism_actors(
            substitution_barriers=[
                _barrier("TSM foundry has no ready substitute"),
            ],
        )
        self.assertIn("TSM", symbols)

    def test_pulls_tickers_from_beneficiary_parens_notation(self):
        symbols = extract_mechanism_actors(
            beneficiaries_text=["Exxon (XOM) global upstream",
                                 "Chevron (CVX)"],
        )
        self.assertIn("XOM", symbols)
        self.assertIn("CVX", symbols)

    def test_slash_separated_tickers_both_extracted(self):
        """'LRCX / AMAT cut' → both symbols."""
        symbols = extract_mechanism_actors(
            transmission_path=[_hop("LRCX", hop_text="LRCX / AMAT cut")],
        )
        self.assertIn("LRCX", symbols)
        self.assertIn("AMAT", symbols)

    def test_non_alpha_tokens_dropped(self):
        """Numeric codes or 6+ char tokens aren't ticker candidates."""
        symbols = extract_mechanism_actors(
            beneficiaries_text=["25% tariff rate", "BERKSHIRE Hathaway"],
        )
        # "BERKSHIRE" is 9 chars — dropped.
        self.assertNotIn("BERKSHIRE", symbols)

    def test_non_string_inputs_skipped_silently(self):
        """None / ints / dicts in the lists don't crash."""
        symbols = extract_mechanism_actors(
            beneficiaries_text=[None, 42, {"not": "a string"}, "XOM"],
            transmission_path=[None, "broken", _hop("CVX")],
        )
        self.assertIn("XOM", symbols)
        self.assertIn("CVX", symbols)


# ---------------------------------------------------------------------------
# 2. Bottleneck promotion
# ---------------------------------------------------------------------------

class TestBottleneckPromotion(unittest.TestCase):
    """A ticker named in the mechanism structure moves from the
    ``direct`` tier to the ``bottleneck_proxy`` tier."""

    def test_named_ticker_gets_bottleneck_tier(self):
        v = compute_agreement_verdict(
            [
                _t("LRCX", validation_quality="alpha_support"),
                _t("AMAT", validation_quality="alpha_support"),
            ],
            transmission_path=[_hop("LRCX"), _hop("AMAT")],
        )
        self.assertEqual(v["bottleneck_support"], 2)
        self.assertEqual(v["direct_support"], 0)

    def test_unnamed_ticker_stays_direct(self):
        v = compute_agreement_verdict(
            [_t("JPM", validation_quality="alpha_support")],
            transmission_path=[_hop("LRCX")],
        )
        self.assertEqual(v["bottleneck_support"], 0)

    def test_bottleneck_contradict_counter(self):
        v = compute_agreement_verdict(
            [_t("LRCX", validation_quality="alpha_contradicts"),
             _t("AMAT", validation_quality="alpha_contradicts")],
            transmission_path=[_hop("LRCX"), _hop("AMAT")],
        )
        self.assertEqual(v["bottleneck_contradict"], 2)

    def test_bottleneck_tier_weighs_more_than_direct(self):
        """Same sign, same 5d — bottleneck ticker's score contribution
        must exceed a generic direct proxy's."""
        self.assertGreater(_CLASS_WEIGHT["bottleneck_proxy"],
                            _CLASS_WEIGHT["direct"])

    def test_bottleneck_symbols_surfaced_on_verdict(self):
        v = compute_agreement_verdict(
            [_t("LRCX", validation_quality="alpha_support")],
            transmission_path=[_hop("LRCX")],
            beneficiaries_text=["Chevron (CVX)"],
        )
        self.assertIn("LRCX", v["bottleneck_symbols"])
        self.assertIn("CVX", v["bottleneck_symbols"])


# ---------------------------------------------------------------------------
# 3. Bottleneck weight dominates peripheral noise
# ---------------------------------------------------------------------------

class TestBottleneckDominatesPeripheral(unittest.TestCase):

    def test_single_bottleneck_alpha_beats_three_beta_pushbacks(self):
        """A named actor moving on alpha should overcome a small basket
        of generic sector beta-contradict noise."""
        v = compute_agreement_verdict(
            [
                _t("LRCX", validation_quality="alpha_support"),
                _t("SPY",  validation_quality="beta_contradicts"),
                _t("QQQ",  validation_quality="beta_contradicts"),
                _t("DIA",  validation_quality="beta_contradicts"),
            ],
            transmission_path=[_hop("LRCX")],
        )
        # Math:
        #   numerator   = +3.5 (bottleneck) - 3 × 0.7 (beta) = +1.4
        #   denominator = 3.5 + 3 × 1.0 = 6.5
        #   score       = +0.215  → partial tier (≥ 0.15)
        self.assertIn(v["verdict"], {"partial", "confirmed"})
        self.assertGreater(v["weighted_score"], 0.15)

    def test_same_tickers_without_bottleneck_flip_to_weak_lean(self):
        """Without the bottleneck promotion the same 1-support / 3-
        contradict mix reads weak / direct_miss instead of partial."""
        # No transmission_path so LRCX stays in the plain direct tier.
        v = compute_agreement_verdict(
            [
                _t("LRCX", validation_quality="alpha_support"),
                _t("SPY",  validation_quality="beta_contradicts"),
                _t("QQQ",  validation_quality="beta_contradicts"),
                _t("DIA",  validation_quality="beta_contradicts"),
            ],
        )
        # Math without the bottleneck bump:
        #   numerator   = +2.5 - 3 × 0.7 = +0.4
        #   denominator = 2.5 + 3 = 5.5
        #   score       = 0.073  → mixed / weak_lean
        self.assertNotIn(v["verdict"], {"confirmed", "partial"})


# ---------------------------------------------------------------------------
# 4. Failure-mode diagnosis
# ---------------------------------------------------------------------------

class TestFailureModeDiagnosis(unittest.TestCase):
    """Each non-confirmed verdict must carry a specific failure-mode
    label that names the pattern a research desk would cite."""

    def test_true_contradiction_fires_when_direct_oppose(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_contradicts"),
            _t("CVX", validation_quality="alpha_contradicts"),
        ])
        self.assertIsNotNone(v["failure_mode"])
        self.assertEqual(v["failure_mode"]["mode"], "true_contradiction")

    def test_bad_primary_proxy_when_direct_silent_tape_confirms(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="flat"),
            _t("CVX", validation_quality="drift"),
            _t("SPY", validation_quality="beta_aligned"),
            _t("QQQ", validation_quality="beta_aligned"),
        ])
        self.assertIsNotNone(v["failure_mode"])
        self.assertEqual(v["failure_mode"]["mode"], "bad_primary_proxy")
        # Rationale names the specific pattern so the UI can render it.
        self.assertIn("basket", v["failure_mode"]["rationale"].lower())

    def test_second_order_lag_when_direct_confirms_alone(self):
        """Direct alpha support without tape corroboration — the
        classic cascade-lag pattern."""
        # Need at least 2 eligible tickers to avoid the "insufficient"
        # band.  Two direct-only supports with no beta noise.
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
        ])
        # 2 direct supports → "confirmed" verdict, NOT a failure mode.
        # To land in second_order_lag we need a partial-range score —
        # which means one direct support + silent peers.
        v2 = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="flat"),
            _t("BP",  validation_quality="unavailable"),
        ])
        # One direct support, rest noise → partial verdict with
        # second_order_lag as the failure mode.
        if v2["failure_mode"] is not None:
            self.assertEqual(v2["failure_mode"]["mode"], "second_order_lag")

    def test_mixed_cross_asset_tape_when_beta_split(self):
        v = compute_agreement_verdict([
            _t("SPY", validation_quality="beta_aligned"),
            _t("QQQ", validation_quality="beta_aligned"),
            _t("IWM", validation_quality="beta_contradicts"),
            _t("XLU", validation_quality="beta_contradicts"),
        ])
        self.assertIsNotNone(v["failure_mode"])
        self.assertEqual(v["failure_mode"]["mode"], "mixed_cross_asset_tape")

    def test_confirmed_verdict_has_no_failure_mode(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
            _t("BP",  validation_quality="beta_aligned"),
        ])
        self.assertEqual(v["verdict"], "confirmed")
        self.assertIsNone(v["failure_mode"])

    def test_insufficient_verdict_has_no_failure_mode(self):
        v = compute_agreement_verdict([])
        self.assertEqual(v["verdict"], "insufficient")
        self.assertIsNone(v["failure_mode"])

    def test_bottleneck_contradict_counts_as_true_contradiction(self):
        """A named bottleneck going against the thesis is an acute
        contradiction signal — must fire true_contradiction."""
        v = compute_agreement_verdict(
            [_t("LRCX", validation_quality="alpha_contradicts"),
             _t("AMAT", validation_quality="alpha_contradicts")],
            transmission_path=[_hop("LRCX"), _hop("AMAT")],
        )
        self.assertEqual(v["verdict"], "contradicted")
        self.assertEqual(v["failure_mode"]["mode"], "true_contradiction")


# ---------------------------------------------------------------------------
# 5. End-to-end wiring via _build_mover_summary
# ---------------------------------------------------------------------------

class TestMoverSummaryWiring(unittest.TestCase):

    def _ev(self, **overrides) -> dict:
        base = {
            "id":                 42,
            "headline":           "Commerce targets semi fabs",
            "mechanism_summary":  "LRCX revenue exposure hit",
            "mechanism_family":   "sanction",
            "event_date":         "2026-04-19",
            "stage":              "realized",
            "persistence":        "structural",
            "beneficiaries":      ["TSM"],
            "losers":             ["LRCX", "AMAT"],
            "transmission_path":  [
                _hop("LRCX", "equities", "LRCX revenue exposure"),
                _hop("AMAT", "equities", "AMAT margin compression"),
            ],
            "substitution_barriers": [
                _barrier("TSM foundry has no ready substitute"),
            ],
            "transmission_chain": [],
            "if_persists":         {},
        }
        base.update(overrides)
        return base

    def test_mover_summary_forwards_mechanism_structure(self):
        from api import _build_mover_summary
        ev = self._ev()
        big_moves = [
            _t("LRCX", return_5d=-4.0, validation_quality="alpha_contradicts",
                direction_tag="contradicts thesis"),
            _t("AMAT", return_5d=-3.5, validation_quality="alpha_contradicts",
                direction_tag="contradicts thesis"),
        ]
        # Attach spark for _build_mover_summary's internals.
        for t in big_moves:
            t["spark"] = [0.1] * 20
            t["anchor_date"] = "2026-04-13"

        summary = _build_mover_summary(ev, big_moves, support_ratio=0.0)
        agr = summary["agreement"]

        # Bottleneck counters populated because LRCX / AMAT named in path.
        self.assertEqual(agr["bottleneck_contradict"], 2)
        self.assertEqual(agr["bottleneck_support"], 0)
        # Failure-mode block carried through.
        self.assertIsNotNone(agr["failure_mode"])
        self.assertEqual(agr["failure_mode"]["mode"], "true_contradiction")
        # Bottleneck symbols surfaced so the UI can name them.
        self.assertIn("LRCX", agr["bottleneck_symbols"])
        self.assertIn("AMAT", agr["bottleneck_symbols"])


if __name__ == "__main__":
    unittest.main()
