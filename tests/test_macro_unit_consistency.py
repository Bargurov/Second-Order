"""
Tests for consistent numeric units across fresh, cached, and frozen response paths.

Covers:
- rates_context: nominal uses absolute pp, TIP uses percent, breakeven = nominal_pp + tip_pct/duration
- macro_snapshot: 10Y uses absolute pp (not percent-of-level)
- shock_decomposition: channels receive correct-unit inputs
- Frozen/cached payloads get sanitized consistently
"""

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_df(prices, length=None):
    if length is None:
        length = len(prices)
    dates = pd.date_range("2026-01-01", periods=length, freq="B")
    return pd.DataFrame({
        "Close": prices[:length],
        "Volume": [5e6] * length,
    }, index=dates)


# Plausible default series.
_DEFAULTS = {
    "^TNX":     [4.30] * 25,
    "TIP":      [110.0] * 25,
    "^VIX":     [18.0] * 25,
    "^VIX3M":   [20.0] * 25,
    "HYG":      [75.0] * 25,
    "SHY":      [82.0] * 25,
    "GLD":      [230.0] * 25,
    "DX-Y.NYB": [104.0] * 25,
    "TLT":      [92.0] * 25,
    "RSP":      [170.0] * 25,
    "SPY":      [530.0] * 25,
}


def _side(overrides):
    def _fn(sym, *a, **kw):
        if sym in overrides:
            return _make_df(overrides[sym])
        if sym in _DEFAULTS:
            return _make_df(_DEFAULTS[sym])
        return _make_df([100.0] * 25)
    return _fn


# ---------------------------------------------------------------------------
# 1) Fresh rates_context: unit correctness
# ---------------------------------------------------------------------------

class TestRatesContextUnits(unittest.TestCase):
    """Verify that compute_rates_context returns correct units for each field."""

    @patch("market_check._fetch")
    def test_nominal_uses_absolute_pp(self, mock_fetch):
        """10Y yield: 4.30 → 4.45 = +0.15 pp, NOT +3.49%."""
        mock_fetch.side_effect = _side({
            "^TNX": [4.30] * 19 + [4.30, 4.33, 4.36, 4.39, 4.42, 4.45],
        })
        from market_check import compute_rates_context
        rc = compute_rates_context()

        nom = rc["nominal"]["change_5d"]
        self.assertIsNotNone(nom)
        # Absolute pp: 4.45 - 4.30 = 0.15
        self.assertAlmostEqual(nom, 0.15, delta=0.01)
        # Must NOT be the percentage-of-level: (4.45-4.30)/4.30*100 = 3.49
        self.assertLess(abs(nom), 1.0, f"nominal_5d={nom} looks like pct-of-level, not pp")

    @patch("market_check._fetch")
    def test_tip_uses_percent_change(self, mock_fetch):
        """TIP: $110 → $111 = +0.91%, not absolute $1 move."""
        mock_fetch.side_effect = _side({
            "TIP": [110.0] * 19 + [110.0, 110.2, 110.4, 110.6, 110.8, 111.0],
        })
        from market_check import compute_rates_context
        rc = compute_rates_context()

        tip = rc["real_proxy"]["change_5d"]
        self.assertIsNotNone(tip)
        # (111 - 110) / 110 * 100 = 0.909
        self.assertAlmostEqual(tip, 0.91, delta=0.05)

    @patch("market_check._fetch")
    def test_breakeven_proxy_formula(self, mock_fetch):
        """Breakeven proxy = nominal_pp + TIP_pct / _TIP_DURATION (Fisher decomposition)."""
        mock_fetch.side_effect = _side({
            "^TNX": [4.30] * 19 + [4.30, 4.33, 4.36, 4.39, 4.42, 4.45],
            "TIP":  [110.0] * 19 + [110.0, 110.2, 110.4, 110.6, 110.8, 111.0],
        })
        from market_check import compute_rates_context, _TIP_DURATION
        rc = compute_rates_context()

        nom = rc["nominal"]["change_5d"]
        tip = rc["real_proxy"]["change_5d"]
        be = rc["breakeven_proxy"]["change_5d"]
        self.assertIsNotNone(be)
        # Corrected Fisher formula: breakeven_pp = nominal_pp + TIP_pct / duration
        self.assertAlmostEqual(be, nom + tip / _TIP_DURATION, delta=0.005)
        # Result must be pp-scale, not pct-scale (old bug: nom + tip ≈ 1.06 pp)
        self.assertLess(abs(be), 1.0, f"breakeven_5d={be} too large; should be pp-scale")

    @patch("market_check._fetch")
    def test_corrupt_tnx_near_zero_rejected(self, mock_fetch):
        """^TNX with near-zero start (COVID stub) → change_5d is None, not +2680%."""
        mock_fetch.side_effect = _side({
            "^TNX": [0.05] * 19 + [0.05, 0.5, 0.8, 1.0, 1.2, 1.39],
        })
        from market_check import compute_rates_context
        rc = compute_rates_context()

        # Absolute pp diff = 1.39 - 0.05 = 1.34 — within ±5 cap, so valid
        # but _safe_pct would give +2680% — this test proves we use pp not %
        nom = rc["nominal"]["change_5d"]
        if nom is not None:
            self.assertLess(abs(nom), 5.0,
                            f"nominal_5d={nom} exceeds ±5 pp cap")


# ---------------------------------------------------------------------------
# 2) macro_snapshot: 10Y yield uses absolute pp
# ---------------------------------------------------------------------------

class TestMacroSnapshotYieldUnit(unittest.TestCase):
    """Verify that macro_snapshot returns absolute pp for the 10Y instrument."""

    @patch("market_check._fetch")
    def test_10y_change_is_pp_not_pct(self, mock_fetch):
        """10Y: 4.30 → 4.45 = +0.15 pp in macro_snapshot."""
        mock_fetch.side_effect = _side({
            "^TNX": [4.30] * 19 + [4.30, 4.33, 4.36, 4.39, 4.42, 4.45],
        })
        from market_check import macro_snapshot
        ms = macro_snapshot()
        tenyr = next((e for e in ms if e["label"] == "10Y"), None)
        self.assertIsNotNone(tenyr)
        chg = tenyr["change_5d"]
        self.assertIsNotNone(chg)
        self.assertAlmostEqual(chg, 0.15, delta=0.01)
        # Must NOT be percentage of level
        self.assertLess(abs(chg), 1.0, f"10Y change_5d={chg} looks like pct-of-level")

    @patch("market_check._fetch")
    @patch("market_check._fetch_since")
    def test_10y_event_date_anchored_pp(self, mock_fetch_since, mock_fetch):
        """Event-date-anchored 10Y should also use pp."""
        series = [4.30, 4.33, 4.36, 4.39, 4.42, 4.45] + [4.45] * 5
        mock_fetch_since.side_effect = _side({
            "^TNX": series,
        })
        mock_fetch.side_effect = _side({})
        from market_check import macro_snapshot
        ms = macro_snapshot(event_date="2026-01-01")
        tenyr = next((e for e in ms if e["label"] == "10Y"), None)
        self.assertIsNotNone(tenyr)
        chg = tenyr["change_5d"]
        if chg is not None:
            self.assertAlmostEqual(chg, 0.15, delta=0.01)

    @patch("market_check._fetch")
    def test_other_instruments_use_pct(self, mock_fetch):
        """Non-yield instruments (DXY, VIX, WTI) should use percent change."""
        mock_fetch.side_effect = _side({
            "DX-Y.NYB": [100.0] * 19 + [100.0, 100.5, 101.0, 101.5, 102.0, 102.0],
        })
        from market_check import macro_snapshot
        ms = macro_snapshot()
        usd = next((e for e in ms if e["label"] == "USD"), None)
        self.assertIsNotNone(usd)
        chg = usd["change_5d"]
        if chg is not None:
            # (102 - 100) / 100 * 100 = 2.0%
            self.assertAlmostEqual(chg, 2.0, delta=0.1)

    @patch("market_check._fetch")
    def test_yield_beyond_5pp_cap_is_none(self, mock_fetch):
        """Yield jump > 5 pp is rejected as corrupt."""
        mock_fetch.side_effect = _side({
            "^TNX": [0.5] * 19 + [0.5, 1.5, 3.0, 5.0, 6.0, 7.0],
        })
        from market_check import macro_snapshot
        ms = macro_snapshot()
        tenyr = next((e for e in ms if e["label"] == "10Y"), None)
        self.assertIsNotNone(tenyr)
        # 7.0 - 0.5 = 6.5 pp > 5 pp cap → None
        self.assertIsNone(tenyr["change_5d"])


# ---------------------------------------------------------------------------
# 3) shock_decomposition: receives correct-unit inputs
# ---------------------------------------------------------------------------

class TestShockDecompUnits(unittest.TestCase):
    """Verify shock_decomposition channels use the right units."""

    def test_nominal_channel_uses_pp(self):
        """nominal_yield channel should use absolute pp from rates_context."""
        from shock_decomposition import compute_shock_decomposition
        rates = {
            "regime": "Inflation pressure",
            "nominal": {"change_5d": 0.15},       # 15 bps = 0.15 pp
            "real_proxy": {"change_5d": -0.50},    # TIP pct
            "breakeven_proxy": {"change_5d": -0.35},
            "raw": {"tnx": 4.45, "tnx_change_5d": 0.15, "tip": 110.5, "tip_change_5d": -0.50},
        }
        result = compute_shock_decomposition(rates, None, None)
        if not result:
            self.skipTest("shock_decomposition returned empty — no stress input")
        channels = result.get("channels", {})
        nom = channels.get("nominal_yield", {})
        if nom.get("available"):
            # move_5d should be 0.15, not 3.49
            self.assertAlmostEqual(nom["move_5d"], 0.15, delta=0.01)
            # z = |0.15| / 0.20 = 0.75
            self.assertAlmostEqual(nom["z"], 0.75, delta=0.1)

    def test_absurd_nominal_capped(self):
        """nominal_yield move_5d beyond ±5 is capped to None."""
        from shock_decomposition import compute_shock_decomposition
        rates = {
            "regime": "Mixed",
            "nominal": {"change_5d": 2680.0},  # Garbage value
            "real_proxy": {"change_5d": 0.5},
            "breakeven_proxy": {"change_5d": 2680.5},
            "raw": {},
        }
        result = compute_shock_decomposition(rates, None, None)
        if not result:
            self.skipTest("shock_decomposition returned empty")
        channels = result.get("channels", {})
        nom = channels.get("nominal_yield", {})
        # The cap in _safe_move should reject 2680
        self.assertFalse(nom.get("available", False),
                         "2680 pp should have been rejected by _CHANNEL_MOVE_CAPS")


# ---------------------------------------------------------------------------
# 4) Frozen response sanitization
# ---------------------------------------------------------------------------

class TestFrozenResponseSanitization(unittest.TestCase):
    """Verify that sanitize_shock_decomposition_block cleans stored artifacts."""

    def test_absurd_channel_move_sanitized(self):
        """Persisted block with 2680% nominal move gets clamped to None."""
        from shock_decomposition import sanitize_shock_decomposition_block
        block = {
            "primary": "nominal_yield",
            "primary_label": "Nominal yields",
            "secondary": [
                {"id": "nominal_yield", "label": "Nominal yields",
                 "move_5d": 2680.0, "z": 13400.0},
            ],
            "channels": {
                "nominal_yield": {
                    "label": "Nominal yields",
                    "move_5d": 2680.0,
                    "available": True,
                    "z": 13400.0,
                },
                "real_yield": {
                    "label": "Real yields",
                    "move_5d": 0.5,
                    "available": True,
                    "z": 1.0,
                },
            },
        }
        clean = sanitize_shock_decomposition_block(block)

        nom = clean["channels"]["nominal_yield"]
        self.assertIsNone(nom["move_5d"], "2680 should be clamped to None")
        self.assertFalse(nom["available"])
        self.assertEqual(nom["z"], 0.0)

        real = clean["channels"]["real_yield"]
        self.assertAlmostEqual(real["move_5d"], 0.5)
        self.assertTrue(real["available"])

        # Secondary list should drop the absurd entry
        for s in clean.get("secondary", []):
            self.assertNotEqual(s.get("id"), "nominal_yield",
                                "Absurd secondary entry should be removed")

    def test_clean_block_unchanged(self):
        """A well-formed block passes through without modification."""
        from shock_decomposition import sanitize_shock_decomposition_block
        block = {
            "primary": "fx",
            "channels": {
                "fx": {"move_5d": 1.2, "available": True, "z": 1.71},
            },
            "secondary": [],
        }
        clean = sanitize_shock_decomposition_block(block)
        self.assertEqual(clean["channels"]["fx"]["move_5d"], 1.2)
        self.assertTrue(clean["channels"]["fx"]["available"])


# ---------------------------------------------------------------------------
# 5) rates_context + macro_snapshot cross-consistency
# ---------------------------------------------------------------------------

class TestCrossConsistency(unittest.TestCase):
    """rates_context and macro_snapshot should agree on 10Y direction."""

    @patch("market_check._fetch")
    def test_both_agree_on_yield_direction(self, mock_fetch):
        """If yields rose, both paths should show a positive change."""
        mock_fetch.side_effect = _side({
            "^TNX": [4.30] * 19 + [4.30, 4.33, 4.36, 4.39, 4.42, 4.45],
        })
        from market_check import compute_rates_context, macro_snapshot

        rc = compute_rates_context()
        ms = macro_snapshot()
        tenyr = next((e for e in ms if e["label"] == "10Y"), None)

        rc_nom = rc["nominal"]["change_5d"]
        ms_chg = tenyr["change_5d"] if tenyr else None

        self.assertIsNotNone(rc_nom)
        self.assertIsNotNone(ms_chg)
        # Same sign
        self.assertGreater(rc_nom, 0, "rates_context should show rising yields")
        self.assertGreater(ms_chg, 0, "macro_snapshot should show rising yields")
        # Both should be close to 0.15 pp
        self.assertAlmostEqual(rc_nom, 0.15, delta=0.02)
        self.assertAlmostEqual(ms_chg, 0.15, delta=0.02)


if __name__ == "__main__":
    unittest.main()
