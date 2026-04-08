"""Focused tests for the Surprise vs Anticipation Decomposition composer.

Four required scenarios:
  - Genuine surprise case
  - Anticipated / priced-in case
  - Uncertainty resolution case
  - Partial / stale context

Plus helper coverage (intraday share, ticker usability, decision margin)
so that the classifier can't be accidentally silently reshaped.
"""

from __future__ import annotations

import unittest

from surprise_vs_anticipation import (
    compute_surprise_vs_anticipation,
    _decide_regime,
    _intraday_share,
    _tickers_usable,
)


# ---------------------------------------------------------------------------
# Canonical stress-regime shapes used across cases
# ---------------------------------------------------------------------------

def _stress(
    regime: str = "calm",
    *,
    vix_change_5d: float = 0.0,
    vix_elevated: bool = False,
    term_inversion: bool = False,
    credit_widening: bool = False,
    safe_haven_bid: bool = False,
    breadth_deterioration: bool = False,
) -> dict:
    return {
        "regime": regime,
        "signals": {
            "vix_elevated":          vix_elevated,
            "term_inversion":        term_inversion,
            "credit_widening":       credit_widening,
            "safe_haven_bid":        safe_haven_bid,
            "breadth_deterioration": breadth_deterioration,
        },
        "raw": {
            "vix_change_5d": vix_change_5d,
        },
    }


def _ticker(symbol: str, r1: float | None, r5: float | None, role: str = "beneficiary") -> dict:
    return {
        "symbol":     symbol,
        "role":       role,
        "return_1d":  r1,
        "return_5d":  r5,
        "return_20d": None,
        "direction":  "up" if (r5 or 0) >= 0 else "down",
    }


# ---------------------------------------------------------------------------
# Helper-level behaviour
# ---------------------------------------------------------------------------

class TestIntradayShare(unittest.TestCase):
    def test_half_of_move_today(self):
        self.assertAlmostEqual(_intraday_share(1.0, 2.0), 0.5)

    def test_all_of_move_today(self):
        self.assertAlmostEqual(_intraday_share(2.0, 2.0), 1.0)

    def test_reversal_returns_none(self):
        self.assertIsNone(_intraday_share(-0.5, 1.0))
        self.assertIsNone(_intraday_share(0.5, -1.0))

    def test_tiny_5d_returns_none(self):
        self.assertIsNone(_intraday_share(0.05, 0.05))

    def test_missing_returns_none(self):
        self.assertIsNone(_intraday_share(None, 1.0))
        self.assertIsNone(_intraday_share(1.0, None))

    def test_clipped_at_1_5(self):
        self.assertAlmostEqual(_intraday_share(10.0, 5.0), 1.5)


class TestTickersUsable(unittest.TestCase):
    def test_filters_out_missing_returns(self):
        usable = _tickers_usable([
            {"symbol": "X", "return_1d": None, "return_5d": None},
            {"symbol": "Y", "return_1d": 0.5, "return_5d": 1.0},
        ])
        self.assertEqual(len(usable), 1)
        self.assertEqual(usable[0]["symbol"], "Y")

    def test_handles_none_input(self):
        self.assertEqual(_tickers_usable(None), [])
        self.assertEqual(_tickers_usable([]), [])

    def test_rejects_non_dict_entries(self):
        self.assertEqual(_tickers_usable(["bogus", 5, None]), [])


class TestDecideRegime(unittest.TestCase):
    def test_empty_or_zero_returns_mixed(self):
        self.assertEqual(_decide_regime({})[0], "mixed")
        self.assertEqual(_decide_regime({"surprise_shock": 0, "anticipated_confirmation": 0})[0], "mixed")

    def test_margin_rule_forces_mixed(self):
        pts = {"surprise_shock": 3, "anticipated_confirmation": 2, "uncertainty_resolution": 0}
        self.assertEqual(_decide_regime(pts)[0], "mixed")

    def test_clear_leader_wins(self):
        pts = {"surprise_shock": 5, "anticipated_confirmation": 1, "uncertainty_resolution": 0}
        self.assertEqual(_decide_regime(pts)[0], "surprise_shock")


# ---------------------------------------------------------------------------
# The four required scenarios
# ---------------------------------------------------------------------------

class TestSurpriseShockCase(unittest.TestCase):
    """Genuine surprise: most of the 5d move lands today AND VIX spikes."""

    def test_surprise_shock_classification(self):
        tickers = [
            _ticker("ES",  r1=-1.8, r5=-2.0),   # share 0.90 → surprise
            _ticker("VIX", r1=+3.0, r5=+3.2),   # share 0.94 → surprise
            _ticker("DXY", r1=+0.9, r5=+1.0),   # share 0.90 → surprise
        ]
        stress = _stress(
            regime="stressed",
            vix_change_5d=+2.5,
            vix_elevated=True,
            term_inversion=True,
        )

        out = compute_surprise_vs_anticipation(
            stage="escalation",
            tickers=tickers,
            stress_regime=stress,
        )
        self.assertEqual(out["regime"], "surprise_shock")
        self.assertEqual(out["regime_label"], "Surprise Shock")
        self.assertFalse(out["stale"])
        self.assertTrue(out["available"])
        self.assertIn("key_markets", out)
        self.assertGreaterEqual(len(out["key_markets"]), 3)
        # Signal strip must reflect what it computed.
        self.assertGreaterEqual(out["signals"]["intraday_share"], 0.6)
        self.assertEqual(out["signals"]["vix_change_5d"], 2.5)
        self.assertEqual(out["signals"]["stage"], "escalation")
        self.assertGreaterEqual(out["signals"]["ticker_move_count"], 1)


class TestAnticipatedConfirmationCase(unittest.TestCase):
    """Already priced: 5d move is large but today is small, VIX quiet."""

    def test_anticipated_confirmation_classification(self):
        tickers = [
            _ticker("ES",  r1=-0.15, r5=-2.0),   # share 0.075 → anticipated
            _ticker("TIP", r1=-0.05, r5=-0.8),   # share 0.0625 → anticipated
            _ticker("2Y",  r1=+0.03, r5=+0.5),   # share 0.06 → anticipated
        ]
        stress = _stress(
            regime="calm",
            vix_change_5d=-0.10,
            safe_haven_bid=True,
        )

        out = compute_surprise_vs_anticipation(
            stage="anticipation",
            tickers=tickers,
            stress_regime=stress,
        )
        self.assertEqual(out["regime"], "anticipated_confirmation")
        self.assertEqual(out["regime_label"], "Anticipated / Priced-In")
        self.assertFalse(out["stale"])
        self.assertLess(out["signals"]["intraday_share"], 0.3)


class TestUncertaintyResolutionCase(unittest.TestCase):
    """Event removed overhang: VIX collapses, stage = de-escalation."""

    def test_uncertainty_resolution_classification(self):
        tickers = [
            _ticker("ES", r1=+0.5, r5=+1.2),
            _ticker("HYG", r1=+0.3, r5=+0.6),
        ]
        stress = _stress(
            regime="calm",
            vix_change_5d=-2.5,
        )

        out = compute_surprise_vs_anticipation(
            stage="de-escalation",
            tickers=tickers,
            stress_regime=stress,
        )
        self.assertEqual(out["regime"], "uncertainty_resolution")
        self.assertEqual(out["regime_label"], "Uncertainty Resolution")
        self.assertFalse(out["stale"])
        self.assertEqual(out["signals"]["vix_change_5d"], -2.5)


class TestPartialStaleContext(unittest.TestCase):
    """Degrades cleanly when any input family is missing."""

    def test_empty_everything_returns_empty_dict(self):
        out = compute_surprise_vs_anticipation(stage="", tickers=None, stress_regime=None)
        self.assertEqual(out, {})

    def test_stage_only_marks_stale(self):
        out = compute_surprise_vs_anticipation(
            stage="escalation",
            tickers=None,
            stress_regime=None,
        )
        self.assertTrue(out)
        self.assertTrue(out["stale"])
        self.assertTrue(out["available"])
        self.assertIn("regime", out)
        # Escalation biases surprise_shock +2 with zero runner-up, so it
        # clears the margin rule; stage-only degrades content but still
        # returns a best-guess regime.
        self.assertEqual(out["regime"], "surprise_shock")

    def test_stage_only_with_split_bias_returns_mixed(self):
        """normalization biases anticipated+1 and uncertainty+1 — no
        leader clears the margin → mixed fallback."""
        out = compute_surprise_vs_anticipation(
            stage="normalization",
            tickers=None,
            stress_regime=None,
        )
        self.assertTrue(out["stale"])
        self.assertEqual(out["regime"], "mixed")

    def test_tickers_only_marks_stale(self):
        tickers = [
            _ticker("ES", r1=-1.8, r5=-2.0),
            _ticker("DXY", r1=+0.9, r5=+1.0),
        ]
        out = compute_surprise_vs_anticipation(
            stage="",
            tickers=tickers,
            stress_regime=None,
        )
        self.assertTrue(out["stale"])
        self.assertTrue(out["available"])

    def test_stress_only_marks_stale(self):
        stress = _stress(vix_change_5d=+2.5, vix_elevated=True, term_inversion=True)
        out = compute_surprise_vs_anticipation(
            stage="",
            tickers=None,
            stress_regime=stress,
        )
        self.assertTrue(out["stale"])
        self.assertEqual(out["regime"], "surprise_shock")

    def test_no_signals_no_stage_returns_empty(self):
        """Stress dict with neither raw nor signals is not usable."""
        out = compute_surprise_vs_anticipation(
            stage="",
            tickers=None,
            stress_regime={"regime": "calm"},  # no raw, no signals
        )
        self.assertEqual(out, {})


# ---------------------------------------------------------------------------
# Output shape contract — protects the frontend contract
# ---------------------------------------------------------------------------

class TestOutputShape(unittest.TestCase):
    def test_full_output_has_expected_fields(self):
        tickers = [_ticker("ES", r1=-1.8, r5=-2.0)]
        stress = _stress(vix_change_5d=+2.0, vix_elevated=True, term_inversion=True)
        out = compute_surprise_vs_anticipation(
            stage="escalation",
            tickers=tickers,
            stress_regime=stress,
        )
        expected_keys = {
            "regime", "regime_label", "rationale", "priced_before",
            "changed_on_realization", "key_markets", "available", "stale",
            "signals",
        }
        self.assertTrue(expected_keys.issubset(out.keys()))
        self.assertIsInstance(out["key_markets"], list)
        self.assertIsInstance(out["signals"], dict)
        self.assertIn("intraday_share", out["signals"])
        self.assertIn("vix_change_5d", out["signals"])
        self.assertIn("stage", out["signals"])
        self.assertIn("ticker_move_count", out["signals"])


if __name__ == "__main__":
    unittest.main()
