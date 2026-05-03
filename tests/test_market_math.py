"""
tests/test_market_math.py

Contract tests for the ``market_math`` pure composer.

Covers:
  1. Quality enum is always present and one of QUALITY_IDS — every
     returned block, every fallback path.
  2. Real-rate / breakeven decomposition — derived vs proxy paths,
     cross-check agreement/divergence band, Fisher-identity invariant
     (real = nominal − breakeven when both available).
  3. USD basket sign convention — USD-base pairs keep sign, USD-quote
     pairs invert.  A flipped sign on ANY leg would fail here.
  4. Fallback matrix — every combination of present/missing inputs
     produces a valid block, never an exception, never a missing
     ``quality`` field.
  5. Agreement band between basket and DXY — below 0.5 % = confirmed,
     above = divergent (degraded quality).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import market_math as mm


# ---------------------------------------------------------------------------
# Quality enum / vocabulary
# ---------------------------------------------------------------------------


class TestQualityEnum(unittest.TestCase):
    def test_enum_closed(self) -> None:
        self.assertEqual(
            set(mm.QUALITY_IDS),
            {"direct", "derived", "proxy", "degraded", "unavailable"},
        )

    def test_worst_quality_picks_weakest(self) -> None:
        self.assertEqual(
            mm._worst_quality(["direct", "proxy", "derived"]), "proxy",
        )
        self.assertEqual(
            mm._worst_quality(["direct", "derived"]), "derived",
        )
        self.assertEqual(
            mm._worst_quality(["direct", "unavailable"]), "unavailable",
        )

    def test_worst_quality_on_empty_is_unavailable(self) -> None:
        self.assertEqual(mm._worst_quality([]), "unavailable")


# ---------------------------------------------------------------------------
# Real-rate / breakeven decomposition
# ---------------------------------------------------------------------------


class TestRealRateFullInputs(unittest.TestCase):
    """^TNX + TIP + IEF all present — the best case."""

    def setUp(self) -> None:
        # Plausible-scale inputs: +10 bps nominal, TIP up 1 %, IEF up 0.4 %.
        self.out = mm.compute_real_rate_read(
            nominal_5d_pp=0.10,
            tip_pct_5d=1.0,
            ief_pct_5d=0.4,
        )

    def test_nominal_is_direct(self) -> None:
        self.assertEqual(self.out["nominal"]["quality"], "direct")
        self.assertEqual(self.out["nominal"]["source"], "tnx_direct")
        self.assertAlmostEqual(
            self.out["nominal"]["value_5d_pp"], 0.10, places=4,
        )

    def test_breakeven_primary_is_derived(self) -> None:
        prim = self.out["breakeven_primary"]
        self.assertEqual(prim["quality"], "derived")
        self.assertEqual(prim["source"], "tip_over_ief_ratio")
        # (1.0 - 0.4) / 7.5 = 0.08
        self.assertAlmostEqual(prim["value_5d_pp"], 0.08, places=4)

    def test_breakeven_fallback_is_fisher_proxy(self) -> None:
        fallback = self.out["breakeven_fallback"]
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback["quality"], "proxy")
        # 0.10 + 1.0 / 7.5 = 0.233...
        self.assertAlmostEqual(fallback["value_5d_pp"], 0.2333, places=3)

    def test_real_inherits_derived_quality(self) -> None:
        # Real = nominal − breakeven_derived = 0.10 − 0.08 = 0.02
        real = self.out["real"]
        self.assertEqual(real["quality"], "derived")
        self.assertAlmostEqual(real["value_5d_pp"], 0.02, places=4)

    def test_fisher_identity_holds(self) -> None:
        # Real + breakeven == nominal (Fisher), within rounding.
        nom = self.out["nominal"]["value_5d_pp"]
        real = self.out["real"]["value_5d_pp"]
        be = self.out["breakeven_primary"]["value_5d_pp"]
        self.assertAlmostEqual(real + be, nom, places=4)

    def test_cross_check_agreement(self) -> None:
        # Derived 0.08 vs Fisher 0.233 — gap 0.153 > 0.10 pp → divergent.
        self.assertEqual(self.out["cross_check"]["agreement"], "divergent")
        self.assertIsNotNone(self.out["cross_check"]["gap_pp"])

    def test_cross_check_confirmed_when_close(self) -> None:
        out = mm.compute_real_rate_read(
            nominal_5d_pp=0.08, tip_pct_5d=0.6, ief_pct_5d=0.0,
        )
        # Derived: (0.6 − 0) / 7.5 = 0.08.  Fisher: 0.08 + 0.6/7.5 = 0.16.
        # Gap 0.08 → within the 0.10 pp band.
        self.assertEqual(out["cross_check"]["agreement"], "confirmed")


class TestRealRateProxyFallback(unittest.TestCase):
    """No IEF — must fall back to Fisher proxy, labelled accordingly."""

    def test_only_tnx_and_tip(self) -> None:
        out = mm.compute_real_rate_read(
            nominal_5d_pp=0.12, tip_pct_5d=0.9,
        )
        # Primary must exist (Fisher) but labelled degraded — the better
        # source is missing.
        prim = out["breakeven_primary"]
        self.assertEqual(prim["quality"], "degraded")
        self.assertEqual(prim["source"], "fisher_nominal_minus_tip_duration")
        self.assertIsNone(out["breakeven_fallback"])
        # Real leg inherits the degraded label via _worst_quality path.
        self.assertIn(
            out["real"]["quality"], {"proxy", "degraded"},
        )
        self.assertEqual(out["cross_check"]["agreement"], "single_source")
        self.assertEqual(out["overall_quality"], "degraded")


class TestRealRateDegradedPaths(unittest.TestCase):
    def test_only_tip_no_nominal(self) -> None:
        # No ^TNX — real_leg falls to TIP duration proxy; breakeven can't
        # be computed (needs either nominal for Fisher or IEF for ratio).
        out = mm.compute_real_rate_read(tip_pct_5d=0.9)
        self.assertEqual(out["nominal"]["quality"], "unavailable")
        self.assertEqual(out["breakeven_primary"]["quality"], "unavailable")
        self.assertEqual(out["real"]["quality"], "proxy")
        self.assertEqual(out["real"]["source"], "tip_duration_proxy")
        self.assertAlmostEqual(
            out["real"]["value_5d_pp"], -0.12, places=3,
        )
        self.assertEqual(out["overall_quality"], "unavailable")

    def test_only_tip_and_ief_no_nominal(self) -> None:
        # Derived breakeven works without nominal; real leg then becomes
        # "unavailable" (no nominal to subtract from).
        out = mm.compute_real_rate_read(
            tip_pct_5d=1.0, ief_pct_5d=0.2,
        )
        self.assertEqual(out["breakeven_primary"]["quality"], "derived")
        # Real needs nominal OR TIP fallback — TIP alone is available.
        self.assertIn(out["real"]["quality"], {"proxy"})
        self.assertEqual(out["nominal"]["quality"], "unavailable")

    def test_all_none(self) -> None:
        out = mm.compute_real_rate_read()
        self.assertEqual(out["overall_quality"], "unavailable")
        for leg in ("nominal", "real", "breakeven_primary"):
            self.assertEqual(out[leg]["quality"], "unavailable")
        self.assertIsNone(out["breakeven_fallback"])
        self.assertEqual(out["cross_check"]["agreement"], "unavailable")


class TestRealRateInputSanitisation(unittest.TestCase):
    def test_nan_coerced_to_none(self) -> None:
        out = mm.compute_real_rate_read(
            nominal_5d_pp=float("nan"), tip_pct_5d=0.5, ief_pct_5d=0.2,
        )
        self.assertEqual(out["nominal"]["quality"], "unavailable")
        # Breakeven (derived) still works.
        self.assertEqual(out["breakeven_primary"]["quality"], "derived")

    def test_inf_coerced_to_none(self) -> None:
        out = mm.compute_real_rate_read(
            nominal_5d_pp=float("inf"),
        )
        self.assertEqual(out["overall_quality"], "unavailable")

    def test_string_input_coerced(self) -> None:
        out = mm.compute_real_rate_read(
            nominal_5d_pp="0.10",  # type: ignore[arg-type]
            tip_pct_5d=1.0, ief_pct_5d=0.4,
        )
        self.assertAlmostEqual(
            out["nominal"]["value_5d_pp"], 0.10, places=4,
        )

    def test_bool_rejected(self) -> None:
        # bool is a subclass of int; must not silently coerce to 1/0.
        out = mm.compute_real_rate_read(nominal_5d_pp=True)  # type: ignore[arg-type]
        self.assertEqual(out["nominal"]["quality"], "unavailable")


# ---------------------------------------------------------------------------
# USD basket sign convention — the bug-magnet zone
# ---------------------------------------------------------------------------


class TestUSDBasketSignConvention(unittest.TestCase):
    def test_usd_strong_eurusd_down_all_four_agree(self) -> None:
        # Scenario: USD strengthened across the board.  EUR/USD down 1 %,
        # GBP/USD down 1 %, USD/JPY up 1 %, USD/CNY up 1 %.  Every leg
        # should contribute +1 to USD strength.
        out = mm.compute_usd_basket_read(
            eurusd_pct_5d=-1.0,
            gbpusd_pct_5d=-1.0,
            usdjpy_pct_5d=+1.0,
            usdcny_pct_5d=+1.0,
        )
        contribs = {
            c["pair"]: c["usd_strength_contrib"] for c in out["components"]
        }
        for pair in ("EURUSD", "GBPUSD", "USDJPY", "USDCNY"):
            self.assertAlmostEqual(
                contribs[pair], 1.0, places=4,
                msg=f"{pair} sign flipped — USD-strength convention wrong",
            )
        self.assertAlmostEqual(out["basket_5d_pct"], 1.0, places=4)

    def test_usd_weak_eurusd_up_all_four_agree(self) -> None:
        # Mirror scenario — USD weakened; every leg contributes −1.
        out = mm.compute_usd_basket_read(
            eurusd_pct_5d=+0.5,
            gbpusd_pct_5d=+0.5,
            usdjpy_pct_5d=-0.5,
            usdcny_pct_5d=-0.5,
        )
        self.assertAlmostEqual(out["basket_5d_pct"], -0.5, places=4)

    def test_basket_cancels_on_mixed_moves(self) -> None:
        # EUR strength + JPY weakness — USD strong vs JPY, weak vs EUR;
        # basket should wash out near zero.
        out = mm.compute_usd_basket_read(
            eurusd_pct_5d=+1.0,   # contrib −1
            gbpusd_pct_5d=+1.0,   # contrib −1
            usdjpy_pct_5d=+1.0,   # contrib +1
            usdcny_pct_5d=+1.0,   # contrib +1
        )
        self.assertAlmostEqual(out["basket_5d_pct"], 0.0, places=4)


class TestUSDBasketAgreement(unittest.TestCase):
    def test_confirmed_when_dxy_and_basket_agree(self) -> None:
        out = mm.compute_usd_basket_read(
            dxy_pct_5d=+0.80,
            eurusd_pct_5d=-1.0, gbpusd_pct_5d=-1.0,
            usdjpy_pct_5d=+0.6, usdcny_pct_5d=+0.4,
        )
        # Basket: (+1 +1 +0.6 +0.4)/4 = 0.75 — within 0.5 % of DXY 0.80.
        self.assertEqual(out["agreement"], "confirmed")
        self.assertEqual(out["quality"], "derived")
        self.assertEqual(out["source"], "dxy_plus_basket")

    def test_divergent_when_cny_concentrated(self) -> None:
        # DXY barely moves (EUR-heavy), basket sees a strong USD/CNY leg.
        out = mm.compute_usd_basket_read(
            dxy_pct_5d=0.05,
            eurusd_pct_5d=-0.05, gbpusd_pct_5d=-0.05,
            usdjpy_pct_5d=+0.10, usdcny_pct_5d=+3.0,
        )
        # Basket = (+0.05 + 0.05 + 0.1 + 3.0)/4 = 0.80; DXY = 0.05; gap 0.75.
        self.assertEqual(out["agreement"], "divergent")
        self.assertEqual(out["quality"], "degraded")


class TestUSDBasketFallbackMatrix(unittest.TestCase):
    def test_dxy_only(self) -> None:
        out = mm.compute_usd_basket_read(dxy_pct_5d=0.5)
        self.assertEqual(out["source"], "dxy_only")
        self.assertEqual(out["quality"], "direct")
        self.assertEqual(out["agreement"], "single_source")
        self.assertIsNone(out["basket_5d_pct"])

    def test_basket_only(self) -> None:
        out = mm.compute_usd_basket_read(
            eurusd_pct_5d=-0.5, usdjpy_pct_5d=+0.4,
        )
        self.assertEqual(out["source"], "basket_only")
        self.assertEqual(out["quality"], "derived")
        self.assertAlmostEqual(
            out["basket_5d_pct"], (0.5 + 0.4) / 2, places=4,
        )

    def test_one_pair_plus_dxy_still_dxy_only(self) -> None:
        # Basket thin (<2 components) → basket_value None → source dxy_only.
        out = mm.compute_usd_basket_read(
            dxy_pct_5d=0.3, eurusd_pct_5d=-0.5,
        )
        self.assertEqual(out["source"], "dxy_only")
        self.assertIsNone(out["basket_5d_pct"])

    def test_empty_input_is_unavailable(self) -> None:
        out = mm.compute_usd_basket_read()
        self.assertEqual(out["source"], "none")
        self.assertEqual(out["quality"], "unavailable")
        self.assertEqual(out["agreement"], "unavailable")
        self.assertIsNone(out["basket_5d_pct"])

    def test_every_output_has_quality_field(self) -> None:
        # Parametric sweep: every combination of present/missing inputs
        # should yield a block with a valid quality label.
        samples = [
            {},
            {"dxy_pct_5d": 0.1},
            {"eurusd_pct_5d": -0.1},
            {"usdjpy_pct_5d": 0.2, "usdcny_pct_5d": 0.3},
            {"dxy_pct_5d": 0.5, "eurusd_pct_5d": -0.5,
             "gbpusd_pct_5d": -0.4, "usdjpy_pct_5d": 0.3,
             "usdcny_pct_5d": 0.2},
            {"dxy_pct_5d": float("nan")},
        ]
        for kwargs in samples:
            out = mm.compute_usd_basket_read(**kwargs)
            self.assertIn(out["quality"], mm.QUALITY_IDS, f"kwargs={kwargs}")


class TestBasketComponentShape(unittest.TestCase):
    def test_every_pair_listed_even_when_missing(self) -> None:
        out = mm.compute_usd_basket_read(eurusd_pct_5d=-0.5)
        pairs = [c["pair"] for c in out["components"]]
        self.assertEqual(
            set(pairs), {"EURUSD", "GBPUSD", "USDJPY", "USDCNY"},
        )
        for c in out["components"]:
            if c["pair"] == "EURUSD":
                self.assertTrue(c["present"])
                self.assertIsNotNone(c["usd_strength_contrib"])
            else:
                self.assertFalse(c["present"])
                self.assertIsNone(c["raw_pct_5d"])

    def test_components_ordering_stable(self) -> None:
        out1 = mm.compute_usd_basket_read(
            eurusd_pct_5d=-0.1, gbpusd_pct_5d=-0.1,
            usdjpy_pct_5d=0.1, usdcny_pct_5d=0.1,
        )
        out2 = mm.compute_usd_basket_read(
            eurusd_pct_5d=-0.2, gbpusd_pct_5d=-0.2,
            usdjpy_pct_5d=0.2, usdcny_pct_5d=0.2,
        )
        self.assertEqual(
            [c["pair"] for c in out1["components"]],
            [c["pair"] for c in out2["components"]],
        )


if __name__ == "__main__":
    unittest.main()
