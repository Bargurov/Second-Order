"""
tests/test_agreement_engine.py

Contract tests for the upgraded agreement / validation engine.

Covers:
  1. Ticker classification — alpha_support → direct, beta_aligned →
     second_order, drift → satellite, flat/unavailable → noise.
     Legacy rows (no validation_quality) fall back to direction_tag
     and get mechanism-family-aware direct/second-order routing.
  2. Weighted score bands — confirmed / partial / mixed / weak /
     contradicted / insufficient.  Rescues the "partial" band that
     the old naive count used to miss.
  3. Mechanism-family awareness — same ticker classified differently
     when the family's primary channel pack matches its sector.
  4. Reason string — mentions the direct proxies by symbol; names
     the counter-signals in contradicted / weak cases.
  5. Backward-compat shim — compute_support_ratio preserves the
     canonical legacy outputs (0.0 / 0.5 / 1.0) in the split cases.
  6. /market-movers pipeline — mover summaries now carry an
     ``agreement`` block alongside the legacy ``support_ratio``.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from agreement_engine import (
    _CONTRADICTED_CEIL,
    _CONFIRMED_FLOOR,
    _PARTIAL_FLOOR,
    compute_agreement_verdict,
    compute_support_ratio,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _t(symbol: str, *,
       return_5d: float | None = 2.0,
       direction_tag: str | None = None,
       validation_quality: str | None = None,
       benchmark_sector: str | None = None,
       role: str = "beneficiary") -> dict:
    return {
        "symbol":              symbol,
        "role":                role,
        "return_5d":           return_5d,
        "direction_tag":       direction_tag,
        "validation_quality":  validation_quality,
        "benchmark_sector":    benchmark_sector,
    }


# ---------------------------------------------------------------------------
# 1. Ticker classification
# ---------------------------------------------------------------------------

class TestTickerClassification(unittest.TestCase):

    def test_alpha_support_is_direct_not_second_order(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
        ])
        self.assertEqual(v["direct_support"], 2)
        self.assertEqual(v["second_order_support"], 0)

    def test_beta_aligned_is_second_order(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="beta_aligned"),
            _t("CVX", validation_quality="beta_aligned"),
        ])
        self.assertEqual(v["direct_support"], 0)
        self.assertEqual(v["second_order_support"], 2)

    def test_drift_is_satellite_not_support(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="drift"),
        ])
        self.assertEqual(v["satellite"], 1)
        self.assertEqual(v["direct_support"], 0)

    def test_flat_and_unavailable_are_noise(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="flat"),
            _t("CVX", validation_quality="unavailable"),
        ])
        # Neither counts toward any classification bucket.
        self.assertEqual(v["direct_support"], 0)
        self.assertEqual(v["second_order_support"], 0)
        self.assertEqual(v["satellite"], 0)

    def test_legacy_row_falls_back_to_direction_tag(self):
        v = compute_agreement_verdict([
            _t("XOM", direction_tag="supports thesis"),
            _t("CVX", direction_tag="contradicts thesis"),
        ])
        # With no family + no validation_quality, legacy rows route to
        # second_order by default.
        self.assertEqual(v["second_order_support"], 1)
        self.assertEqual(v["second_order_contradict"], 1)


# ---------------------------------------------------------------------------
# 2. Weighted verdict bands
# ---------------------------------------------------------------------------

class TestVerdictBands(unittest.TestCase):

    def test_confirmed_requires_direct_support_above_floor(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
            _t("BP",  validation_quality="beta_aligned"),
        ])
        self.assertEqual(v["verdict"], "confirmed")
        self.assertGreaterEqual(v["weighted_score"], _CONFIRMED_FLOOR)

    def test_partial_when_direct_support_offset_by_beta_contradict(self):
        """The finance-real partial band — one direct proxy supports,
        beta noise drags the aggregate but doesn't flip the verdict."""
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("JPM", validation_quality="beta_contradicts"),
            _t("SPY", validation_quality="beta_contradicts"),
        ])
        self.assertEqual(v["verdict"], "partial")
        self.assertGreaterEqual(v["weighted_score"], _PARTIAL_FLOOR)
        self.assertLess(v["weighted_score"], _CONFIRMED_FLOOR)

    def test_mixed_when_split_evenly(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("BP",  validation_quality="alpha_contradicts"),
        ])
        self.assertEqual(v["verdict"], "mixed")

    def test_weak_lean_against_but_not_outright(self):
        """Mild beta-led pushback with one corroborating beta name —
        lands in the weak band (lean-contradict, not outright)."""
        v = compute_agreement_verdict([
            _t("JPM", validation_quality="beta_aligned"),
            _t("SPY", validation_quality="beta_contradicts"),
            _t("QQQ", validation_quality="beta_contradicts"),
        ])
        self.assertEqual(v["verdict"], "weak")
        self.assertGreater(v["weighted_score"], _CONTRADICTED_CEIL)
        self.assertLess(v["weighted_score"], -_PARTIAL_FLOOR)

    def test_contradicted_when_direct_proxies_oppose(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_contradicts"),
            _t("CVX", validation_quality="alpha_contradicts"),
        ])
        self.assertEqual(v["verdict"], "contradicted")
        self.assertLess(v["weighted_score"], _CONTRADICTED_CEIL)

    def test_insufficient_when_single_ticker_eligible(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
        ])
        self.assertEqual(v["verdict"], "insufficient")

    def test_no_tickers_returns_insufficient(self):
        v = compute_agreement_verdict([])
        self.assertEqual(v["verdict"], "insufficient")
        self.assertEqual(v["n_eligible"], 0)

    def test_second_order_only_when_direct_silent_but_tape_confirms(self):
        """Tape / beta-aligned names confirm while direct proxies drift —
        deserves its own label, not a flat 'partial'."""
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="drift"),
            _t("BP",  validation_quality="beta_aligned"),
            _t("SPY", validation_quality="beta_aligned"),
        ])
        self.assertEqual(v["verdict"], "second_order_only")
        self.assertEqual(v["direct_support"], 0)
        self.assertEqual(v["direct_contradict"], 0)
        self.assertGreaterEqual(v["second_order_support"], 1)

    def test_direct_miss_when_named_proxy_contradicts(self):
        """A direct proxy moves against the thesis but aggregate is not
        a full collapse — gets the 'direct_miss' label so the desk note
        flags which specific name missed."""
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_contradicts"),
            _t("BP",  validation_quality="beta_aligned"),
            _t("SPY", validation_quality="beta_aligned"),
        ])
        self.assertEqual(v["verdict"], "direct_miss")
        self.assertEqual(v["direct_contradict"], 1)
        self.assertGreater(v["weighted_score"], _CONTRADICTED_CEIL)
        self.assertLess(v["weighted_score"], -_PARTIAL_FLOOR)

    def test_weak_preserved_when_direct_proxies_absent(self):
        """When the lean-against comes purely from beta names (no direct
        proxy missed), keep the 'weak' label — not direct_miss."""
        v = compute_agreement_verdict([
            _t("JPM", validation_quality="beta_aligned"),
            _t("SPY", validation_quality="beta_contradicts"),
            _t("QQQ", validation_quality="beta_contradicts"),
        ])
        self.assertEqual(v["verdict"], "weak")
        self.assertEqual(v["direct_contradict"], 0)


# ---------------------------------------------------------------------------
# 3. Mechanism-family awareness
# ---------------------------------------------------------------------------

class TestMechanismFamilyAwareness(unittest.TestCase):
    """Legacy rows (direction_tag only) route to direct when the
    ticker's benchmark_sector matches a primary channel for the
    event's mechanism family."""

    def test_supply_shock_energy_ticker_classified_direct(self):
        # supply_shock has "commodities" as a first-channel → an energy
        # ticker maps to commodities → direct.
        v = compute_agreement_verdict(
            [
                _t("XOM", direction_tag="supports thesis",
                    benchmark_sector="energy"),
            ],
            mechanism_family="supply_shock",
        )
        # Only one eligible ticker → insufficient verdict, but the
        # direct_support counter must still have been populated so
        # downstream reporting is correct.
        self.assertEqual(v["direct_support"], 1)
        self.assertEqual(v["second_order_support"], 0)

    def test_policy_surprise_energy_ticker_stays_second_order(self):
        # policy_surprise has "rates"/"fx"/"vol" as first-channel.
        # An energy-sector ticker is NOT primary → second-order.
        v = compute_agreement_verdict(
            [
                _t("XOM", direction_tag="supports thesis",
                    benchmark_sector="energy"),
            ],
            mechanism_family="policy_surprise",
        )
        self.assertEqual(v["direct_support"], 0)
        self.assertEqual(v["second_order_support"], 1)

    def test_unknown_family_no_refinement(self):
        """A family we don't recognise falls through to the default
        second-order classification — no crash."""
        v = compute_agreement_verdict(
            [
                _t("XOM", direction_tag="supports thesis",
                    benchmark_sector="energy"),
                _t("CVX", direction_tag="supports thesis",
                    benchmark_sector="energy"),
            ],
            mechanism_family="not_a_real_family",
        )
        self.assertEqual(v["second_order_support"], 2)


# ---------------------------------------------------------------------------
# 4. Reason string quality
# ---------------------------------------------------------------------------

class TestReasonString(unittest.TestCase):

    def test_confirmed_names_direct_proxies(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
            _t("BP",  validation_quality="beta_aligned"),
        ])
        self.assertEqual(v["verdict"], "confirmed")
        self.assertIn("XOM", v["reason"])
        self.assertIn("CVX", v["reason"])

    def test_partial_reason_includes_but_pushback(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("JPM", validation_quality="beta_contradicts"),
            _t("SPY", validation_quality="beta_contradicts"),
        ])
        # partial → the "but" language signals the pushback
        self.assertEqual(v["verdict"], "partial")
        reason = v["reason"].lower()
        self.assertTrue(
            "but" in reason or "counter" in reason,
            f"expected partial reason to flag counter-move, got: {v['reason']!r}",
        )

    def test_contradicted_names_counter_proxies(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_contradicts"),
            _t("CVX", validation_quality="alpha_contradicts"),
        ])
        self.assertIn("XOM", v["reason"])
        self.assertIn("contradict", v["reason"].lower())

    def test_insufficient_reason_explains_sample(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
        ])
        self.assertIn("thin", v["reason"].lower())

    def test_second_order_only_reason_names_tape_confirms(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="drift"),
            _t("BP",  validation_quality="beta_aligned"),
            _t("SPY", validation_quality="beta_aligned"),
        ])
        reason = v["reason"].lower()
        self.assertTrue(
            "beta-aligned" in reason or "tape" in reason,
            f"expected second_order_only reason to reference tape/beta, got: {v['reason']!r}",
        )
        self.assertTrue(
            "direct" in reason or "silent" in reason or "lag" in reason,
            f"expected reason to flag direct proxies as silent/lagging, got: {v['reason']!r}",
        )

    def test_direct_miss_reason_names_the_missing_proxy(self):
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_contradicts"),
            _t("BP",  validation_quality="beta_aligned"),
            _t("SPY", validation_quality="beta_aligned"),
        ])
        self.assertIn("XOM", v["reason"])
        self.assertIn("miss", v["reason"].lower())


# ---------------------------------------------------------------------------
# 5. Backward-compat shim
# ---------------------------------------------------------------------------

class TestBackwardCompatFloat(unittest.TestCase):
    """compute_support_ratio must preserve the canonical 0.0 / 0.5 /
    1.0 results that existing test suites + UI pills depend on."""

    def test_all_support_is_one(self):
        ratio = compute_support_ratio([
            _t("XOM", direction_tag="supports thesis"),
            _t("CVX", direction_tag="supports thesis"),
        ])
        self.assertAlmostEqual(ratio, 1.0, places=2)

    def test_all_contradict_is_zero(self):
        ratio = compute_support_ratio([
            _t("XOM", direction_tag="contradicts thesis"),
            _t("CVX", direction_tag="contradicts thesis"),
        ])
        self.assertAlmostEqual(ratio, 0.0, places=2)

    def test_even_split_is_half(self):
        """The key finance-real rescue: 50/50 no longer collapses to 0%."""
        ratio = compute_support_ratio([
            _t("XOM", direction_tag="supports thesis"),
            _t("CVX", direction_tag="contradicts thesis"),
        ])
        self.assertAlmostEqual(ratio, 0.5, places=2)

    def test_single_support_maps_to_one(self):
        """Legacy pill contract — a single supporting ticker reads 1.0
        on the float shim even though the verdict is 'insufficient'."""
        ratio = compute_support_ratio([
            _t("XOM", direction_tag="supports thesis"),
        ])
        self.assertAlmostEqual(ratio, 1.0, places=2)

    def test_empty_tickers_returns_zero(self):
        """No eligible tickers → 0.0 (not mapped to the 0.5 midpoint)."""
        self.assertEqual(compute_support_ratio([]), 0.0)

    def test_verdict_dict_still_carries_legacy_ratio(self):
        """compute_agreement_verdict's ``support_ratio`` key stays the
        legacy naive count for callers that serialize it."""
        v = compute_agreement_verdict([
            _t("XOM", direction_tag="supports thesis"),
            _t("CVX", direction_tag="contradicts thesis"),
        ])
        self.assertAlmostEqual(v["support_ratio"], 0.5, places=2)


# ---------------------------------------------------------------------------
# 5b. Strong-contradiction override + hedge/signal weight reduction
# ---------------------------------------------------------------------------

class TestStrongContradictionOverride(unittest.TestCase):
    """A strong primary contradiction must override weak/noisy support
    that would otherwise lift the aggregate to ``partial``."""

    def test_strong_primary_contradiction_overrides_weak_support(self):
        """One alpha-grade direct contradiction with no direct alpha
        offset, but a tape-led pile of beta supports lifting the score
        above ``_PARTIAL_FLOOR``, must read 'contradicted', not
        'partial'."""
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_contradicts"),
            _t("BP",  validation_quality="beta_aligned"),
            _t("RDS", validation_quality="beta_aligned"),
            _t("EOG", validation_quality="beta_aligned"),
            _t("APA", validation_quality="beta_aligned"),
            _t("HES", validation_quality="beta_aligned"),
            _t("MRO", validation_quality="beta_aligned"),
        ])
        self.assertEqual(v["verdict"], "contradicted")
        self.assertEqual(v["direct_contradict"], 1)
        self.assertEqual(v["direct_support"], 0)
        self.assertGreaterEqual(v["weighted_score"], _PARTIAL_FLOOR)

    def test_weak_support_alone_is_ignored_against_primary_contradiction(self):
        """No primary supports, one primary contradiction, only
        satellite (drifting) noise — verdict must not be partial."""
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_contradicts"),
            _t("BP",  validation_quality="drift"),
            _t("RDS", validation_quality="drift"),
            _t("EOG", validation_quality="drift"),
        ])
        self.assertNotEqual(v["verdict"], "partial")
        # Either direct_miss or contradicted is acceptable — both
        # correctly attribute the failure to the named direct proxy.
        self.assertIn(v["verdict"], {"contradicted", "direct_miss"})

    def test_direct_alpha_support_keeps_partial_label(self):
        """Sanity check: when there IS at least one direct alpha
        support, the override must not fire — partial is the right
        label for a mixed direct read."""
        v = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_contradicts"),
            _t("BP",  validation_quality="beta_aligned"),
            _t("RDS", validation_quality="beta_aligned"),
            _t("EOG", validation_quality="beta_aligned"),
        ])
        self.assertNotEqual(v["verdict"], "contradicted")
        self.assertGreaterEqual(v["direct_support"], 1)


class TestHedgeSignalContradictionLowerWeight(unittest.TestCase):
    """Hedge / signal proxies (UUP, VIX, TLT, inverse ETFs) must weigh
    LESS than primary tickers — a contradicting hedge ETF cannot drag
    the aggregate as far as a contradicting primary."""

    def test_hedge_signal_contradiction_weighs_less_than_primary(self):
        """Same set of signals, but in one variant the alpha-grade
        contradiction is on a hedge/signal asset (UUP), in the other
        it's on a primary asset (XOM).  The hedge variant must score
        STRICTLY HIGHER (less negative)."""
        primary_contra = compute_agreement_verdict(
            [
                _t("XOM", validation_quality="alpha_contradicts"),
                _t("CVX", validation_quality="alpha_support"),
                _t("BP",  validation_quality="alpha_support"),
            ],
        )
        hedge_contra = compute_agreement_verdict(
            [
                _t("UUP", validation_quality="alpha_contradicts"),
                _t("CVX", validation_quality="alpha_support"),
                _t("BP",  validation_quality="alpha_support"),
            ],
            hedge_or_signal_assets=[{"symbol": "UUP", "rank": 1}],
        )
        self.assertGreater(
            hedge_contra["weighted_score"],
            primary_contra["weighted_score"],
            "hedge/signal contradiction should weigh less than primary "
            "contradiction — same alpha sign, lower tier weight",
        )

    def test_hedge_signal_does_not_trigger_strong_contradiction_override(self):
        """The strong-contradiction override watches direct contradicts
        only.  A contradicting hedge/signal asset with weak support
        must NOT route to ``contradicted`` via the override."""
        v = compute_agreement_verdict(
            [
                _t("UUP", validation_quality="alpha_contradicts"),
                _t("BP",  validation_quality="beta_aligned"),
                _t("RDS", validation_quality="beta_aligned"),
                _t("EOG", validation_quality="beta_aligned"),
                _t("APA", validation_quality="beta_aligned"),
                _t("HES", validation_quality="beta_aligned"),
                _t("MRO", validation_quality="beta_aligned"),
            ],
            hedge_or_signal_assets=["UUP"],
        )
        self.assertEqual(v["direct_contradict"], 0)

    def test_hedge_or_signal_assets_accepts_dict_or_string_shape(self):
        """The engine accepts both the structured ranked-asset dict
        shape and a flat string list — so callers passing the raw
        analysis field don't need to pre-process."""
        # Dict shape — like analysis['hedge_or_signal_assets'].
        v_dict = compute_agreement_verdict(
            [_t("UUP", validation_quality="alpha_support"),
             _t("CVX", validation_quality="alpha_support")],
            hedge_or_signal_assets=[{"symbol": "UUP", "rank": 1, "rationale": "x"}],
        )
        # String shape — flat list.
        v_str = compute_agreement_verdict(
            [_t("UUP", validation_quality="alpha_support"),
             _t("CVX", validation_quality="alpha_support")],
            hedge_or_signal_assets=["UUP"],
        )
        self.assertEqual(v_dict["weighted_score"], v_str["weighted_score"])

    def test_response_shape_unchanged_with_hedge_param(self):
        """Adding the hedge_or_signal_assets parameter must not change
        the keys of the verdict dict — output shape stays stable."""
        v_no_hedge = compute_agreement_verdict([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
        ])
        v_with_hedge = compute_agreement_verdict(
            [
                _t("XOM", validation_quality="alpha_support"),
                _t("CVX", validation_quality="alpha_support"),
                _t("UUP", validation_quality="alpha_support"),
            ],
            hedge_or_signal_assets=["UUP"],
        )
        self.assertEqual(set(v_no_hedge.keys()), set(v_with_hedge.keys()))


# ---------------------------------------------------------------------------
# 6. /market-movers summary emits the agreement verdict block
# ---------------------------------------------------------------------------

class TestMoverSummaryCarriesAgreement(unittest.TestCase):

    def test_build_mover_summary_attaches_agreement_block(self):
        from api import _build_mover_summary
        ev = {
            "id": 1,
            "headline": "OPEC cuts",
            "mechanism_summary": "tighter supply",
            "mechanism_family": "supply_shock",
            "event_date": "2026-04-19",
            "stage": "realized",
            "persistence": "structural",
            "transmission_chain": [],
            "if_persists": {},
        }
        big_moves = [
            _t("XOM", return_5d=3.0, validation_quality="alpha_support",
                benchmark_sector="energy"),
            _t("CVX", return_5d=2.5, validation_quality="alpha_support",
                benchmark_sector="energy"),
            _t("BP",  return_5d=1.8, validation_quality="beta_aligned",
                benchmark_sector="energy"),
        ]
        summary = _build_mover_summary(ev, big_moves, support_ratio=1.0)
        self.assertIn("agreement", summary)
        agr = summary["agreement"]
        self.assertEqual(agr["verdict"], "confirmed")
        # mechanism_family piped through → alpha-support already direct,
        # so the counter stays at 2 for direct_support.
        self.assertEqual(agr["direct_support"], 2)
        self.assertEqual(agr["second_order_support"], 1)


if __name__ == "__main__":
    unittest.main()
