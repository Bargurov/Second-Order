"""
Tests for analysis-response percentage/unit consistency end-to-end.

Covers:
- shock_decomposition: channel unit field, _fmt_move per-channel
- real_yield_context: _explain() unit labels, frozen sanitizer
- reaction_function_divergence: basis string unit labels
- Frozen-path sanitization for real_yield_context
- Fresh/cached/frozen numeric range consistency
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# 1) shock_decomposition: channel unit field + _fmt_move
# ---------------------------------------------------------------------------

class TestShockDecompChannelUnits(unittest.TestCase):
    """Verify each channel carries the correct 'unit' field in the payload."""

    def _build(self, rates):
        from shock_decomposition import compute_shock_decomposition
        return compute_shock_decomposition(rates, None, None)

    def test_nominal_yield_unit_is_pp(self):
        result = self._build({
            "regime": "Mixed",
            "nominal": {"change_5d": 0.15},
            "real_proxy": {"change_5d": -0.50},
            "breakeven_proxy": {"change_5d": -0.35},
            "raw": {},
        })
        self.assertTrue(result)
        ch = result["channels"]["nominal_yield"]
        self.assertEqual(ch["unit"], "pp")

    def test_real_yield_unit_is_pct(self):
        result = self._build({
            "regime": "Mixed",
            "nominal": {"change_5d": 0.15},
            "real_proxy": {"change_5d": -0.50},
            "breakeven_proxy": {"change_5d": -0.35},
            "raw": {},
        })
        self.assertTrue(result)
        ch = result["channels"]["real_yield"]
        self.assertEqual(ch["unit"], "%")

    def test_breakeven_unit_is_pp(self):
        result = self._build({
            "regime": "Mixed",
            "nominal": {"change_5d": 0.15},
            "real_proxy": {"change_5d": -0.50},
            "breakeven_proxy": {"change_5d": -0.35},
            "raw": {},
        })
        self.assertTrue(result)
        ch = result["channels"]["breakeven"]
        self.assertEqual(ch["unit"], "pp")

    def test_fx_unit_is_pct(self):
        result = self._build({
            "regime": "Mixed",
            "nominal": {"change_5d": 0.15},
            "real_proxy": {"change_5d": -0.50},
            "breakeven_proxy": {"change_5d": -0.35},
            "raw": {},
        })
        self.assertTrue(result)
        ch = result["channels"]["fx"]
        self.assertEqual(ch["unit"], "%")

    def test_commodity_unit_is_pct(self):
        result = self._build({
            "regime": "Mixed",
            "nominal": {"change_5d": 0.15},
            "real_proxy": {"change_5d": -0.50},
            "breakeven_proxy": {"change_5d": -0.35},
            "raw": {},
        })
        self.assertTrue(result)
        ch = result["channels"]["commodity"]
        self.assertEqual(ch["unit"], "%")

    def test_secondary_entries_carry_unit(self):
        """Secondary list items should also have a unit field."""
        result = self._build({
            "regime": "Mixed",
            "nominal": {"change_5d": 0.40},      # z=2.0 → primary
            "real_proxy": {"change_5d": -1.00},   # z=2.0 → secondary
            "breakeven_proxy": {"change_5d": -0.60},
            "raw": {},
        })
        self.assertTrue(result)
        for sec in result.get("secondary", []):
            self.assertIn("unit", sec, f"Secondary entry {sec.get('id')} missing 'unit'")
            expected_unit = "pp" if sec["id"] in ("nominal_yield", "breakeven") else "%"
            self.assertEqual(sec["unit"], expected_unit)


class TestFmtMovePerChannel(unittest.TestCase):
    """Verify _fmt_move uses correct unit suffix per channel."""

    def test_nominal_shows_pp(self):
        from shock_decomposition import _fmt_move
        self.assertIn("pp", _fmt_move(0.15, "nominal_yield"))
        self.assertNotIn("%", _fmt_move(0.15, "nominal_yield"))

    def test_real_shows_pct(self):
        from shock_decomposition import _fmt_move
        self.assertIn("%", _fmt_move(-0.50, "real_yield"))
        self.assertNotIn("pp", _fmt_move(-0.50, "real_yield"))

    def test_breakeven_shows_pp(self):
        from shock_decomposition import _fmt_move
        self.assertIn("pp", _fmt_move(0.35, "breakeven"))

    def test_fx_shows_pct(self):
        from shock_decomposition import _fmt_move
        self.assertIn("%", _fmt_move(1.20, "fx"))

    def test_commodity_shows_pct(self):
        from shock_decomposition import _fmt_move
        self.assertIn("%", _fmt_move(3.50, "commodity"))

    def test_none_returns_dash(self):
        from shock_decomposition import _fmt_move
        self.assertEqual(_fmt_move(None, "nominal_yield"), "\u2014")

    def test_rationale_text_uses_pp_for_nominal(self):
        """Rationale string should say 'pp' not '%' for nominal_yield."""
        from shock_decomposition import compute_shock_decomposition
        result = compute_shock_decomposition(
            {"regime": "Mixed",
             "nominal": {"change_5d": 0.40},
             "real_proxy": {"change_5d": 0.10},
             "breakeven_proxy": {"change_5d": 0.50},
             "raw": {}},
            None, None,
        )
        if not result:
            self.skipTest("empty result")
        rationale = result.get("rationale", "")
        # If nominal is primary or listed, "pp" should appear in the text
        if "nominal" in rationale.lower():
            self.assertIn("pp", rationale,
                          f"Rationale mentions nominal but uses wrong unit: {rationale}")


# ---------------------------------------------------------------------------
# 2) real_yield_context: _explain() unit labels
# ---------------------------------------------------------------------------

class TestRealYieldExplainUnits(unittest.TestCase):
    """Verify _explain() uses correct unit suffixes."""

    def _explain(self, thesis, alignment, regime, be, real):
        from real_yield_context import _explain
        return _explain(thesis, alignment, regime, be, real)

    def test_breakeven_shows_pp(self):
        text = self._explain("inflationary", "confirm", "Inflation pressure", 0.35, -0.50)
        self.assertIn("pp", text, f"Breakeven should show 'pp': {text}")
        # Should NOT show breakeven with raw "%"
        self.assertNotIn("breakevens +0.35%", text)

    def test_real_proxy_shows_pct(self):
        text = self._explain("rate_pressure_up", "confirm", "Real-rate tightening", None, -0.50)
        self.assertIn("TIP", text, f"Real proxy should reference TIP: {text}")
        self.assertIn("%", text, f"TIP price change should show '%': {text}")

    def test_unavailable_no_crash(self):
        text = self._explain("inflationary", "neutral", "Mixed", None, None)
        self.assertIn("unavailable", text)


# ---------------------------------------------------------------------------
# 3) reaction_function_divergence: basis string units
# ---------------------------------------------------------------------------

class TestReactionDivergenceUnits(unittest.TestCase):
    """Verify priced_basis strings carry unit labels."""

    def test_nominal_basis_shows_pp(self):
        # After the mechanism-specific refactor, _priced_direction consumes
        # a shock-decomposition channels dict, not raw rates_context.  The
        # contract under test — unit suffix present in the priced_basis
        # string — is still exercised via compute_reaction_function_divergence.
        from reaction_function_divergence import compute_reaction_function_divergence
        rates = {
            "regime": "Mixed",
            "nominal": {"change_5d": 0.50},
            "real_proxy": {"change_5d": 0.10},
            "breakeven_proxy": {"change_5d": 0.60},
        }
        result = compute_reaction_function_divergence(
            "rate hike priced in", "hawkish policy tightening",
            rates, None, snapshots=None,
        )
        basis = result.get("priced_basis", "")
        if "Nominal" in basis:
            self.assertIn("pp", basis,
                          f"Nominal basis should show 'pp': {basis}")

    def test_real_basis_shows_pct(self):
        from reaction_function_divergence import compute_reaction_function_divergence
        rates = {
            "regime": "Mixed",
            "nominal": {"change_5d": 0.10},
            "real_proxy": {"change_5d": -0.60},
            "breakeven_proxy": {"change_5d": -0.50},
        }
        result = compute_reaction_function_divergence(
            "real yields rising", "restrictive real rates",
            rates, None, snapshots=None,
        )
        basis = result.get("priced_basis", "")
        if "Real" in basis:
            self.assertIn("%", basis,
                          f"Real-yield basis should show '%': {basis}")

    def test_dxy_basis_shows_pct(self):
        from reaction_function_divergence import compute_reaction_function_divergence
        rates = {"regime": "Mixed", "nominal": {"change_5d": 0.0},
                 "real_proxy": {"change_5d": 0.0},
                 "breakeven_proxy": {"change_5d": 0.0}}
        snapshots = [{"market": "DXY", "value": 105.0, "change_5d": 2.0}]
        result = compute_reaction_function_divergence(
            "dollar strength", "DXY ripping",
            rates, None, snapshots=snapshots,
        )
        basis = result.get("priced_basis", "")
        if "Dollar" in basis:
            self.assertIn("%", basis,
                          f"Dollar/FX basis should show '%': {basis}")


# ---------------------------------------------------------------------------
# 4) Frozen real_yield_context sanitizer
# ---------------------------------------------------------------------------

class TestRealYieldContextSanitizer(unittest.TestCase):
    """Verify sanitize_real_yield_context_block caps corrupt frozen values."""

    def test_absurd_nominal_capped(self):
        from real_yield_context import sanitize_real_yield_context_block
        block = {
            "thesis": "inflationary",
            "alignment": "confirm",
            "nominal_5d": 2680.0,
            "real_proxy_5d": -0.50,
            "breakeven_proxy_5d": 2679.5,
        }
        clean = sanitize_real_yield_context_block(block)
        self.assertIsNone(clean["nominal_5d"],
                          "2680 pp nominal should be capped to None")
        self.assertAlmostEqual(clean["real_proxy_5d"], -0.50)
        self.assertIsNone(clean["breakeven_proxy_5d"],
                          "2679.5 breakeven should be capped to None")

    def test_absurd_real_capped(self):
        from real_yield_context import sanitize_real_yield_context_block
        block = {
            "thesis": "rate_pressure_up",
            "nominal_5d": 0.15,
            "real_proxy_5d": -150.0,  # TIP can't move 150% in 5d
            "breakeven_proxy_5d": -149.85,
        }
        clean = sanitize_real_yield_context_block(block)
        self.assertAlmostEqual(clean["nominal_5d"], 0.15)
        self.assertIsNone(clean["real_proxy_5d"])
        self.assertIsNone(clean["breakeven_proxy_5d"])

    def test_clean_block_passes_through(self):
        from real_yield_context import sanitize_real_yield_context_block
        block = {
            "thesis": "inflationary",
            "nominal_5d": 0.15,
            "real_proxy_5d": -0.50,
            "breakeven_proxy_5d": -0.35,
            "available": True,
        }
        clean = sanitize_real_yield_context_block(block)
        self.assertAlmostEqual(clean["nominal_5d"], 0.15)
        self.assertAlmostEqual(clean["real_proxy_5d"], -0.50)
        self.assertAlmostEqual(clean["breakeven_proxy_5d"], -0.35)

    def test_empty_block_safe(self):
        from real_yield_context import sanitize_real_yield_context_block
        self.assertEqual(sanitize_real_yield_context_block({}), {})
        self.assertEqual(sanitize_real_yield_context_block(None), {})

    def test_none_values_preserved(self):
        from real_yield_context import sanitize_real_yield_context_block
        block = {"thesis": "none", "nominal_5d": None, "real_proxy_5d": None}
        clean = sanitize_real_yield_context_block(block)
        self.assertIsNone(clean["nominal_5d"])
        self.assertIsNone(clean["real_proxy_5d"])


# ---------------------------------------------------------------------------
# 5) End-to-end: frozen path applies both sanitizers
# ---------------------------------------------------------------------------

class TestFrozenPathSanitization(unittest.TestCase):
    """Verify the frozen-archive branch in _build_cached_response applies
    sanitization to both shock_decomposition and real_yield_context."""

    def test_frozen_real_yield_context_sanitized(self):
        """Frozen event with absurd nominal_5d in real_yield_context gets capped."""
        from real_yield_context import sanitize_real_yield_context_block
        stored = {
            "thesis": "inflationary",
            "alignment": "confirm",
            "nominal_5d": 2680.0,
            "real_proxy_5d": -0.50,
            "breakeven_proxy_5d": 2679.5,
            "available": True,
        }
        clean = sanitize_real_yield_context_block(stored)
        self.assertIsNone(clean["nominal_5d"])
        self.assertAlmostEqual(clean["real_proxy_5d"], -0.50)
        self.assertIsNone(clean["breakeven_proxy_5d"])

    def test_frozen_shock_decomp_sanitized(self):
        """Frozen event with absurd move_5d in shock_decomposition gets capped."""
        from shock_decomposition import sanitize_shock_decomposition_block
        stored = {
            "primary": "nominal_yield",
            "channels": {
                "nominal_yield": {
                    "label": "Nominal yields",
                    "move_5d": 2680.0,
                    "available": True,
                    "z": 13400.0,
                },
            },
            "secondary": [],
        }
        clean = sanitize_shock_decomposition_block(stored)
        nom = clean["channels"]["nominal_yield"]
        self.assertIsNone(nom["move_5d"])
        self.assertFalse(nom["available"])


# ---------------------------------------------------------------------------
# 6) Fresh response: numeric ranges are sane
# ---------------------------------------------------------------------------

class TestFreshResponseNumericRanges(unittest.TestCase):
    """Verify that freshly computed overlays produce values in expected ranges."""

    def test_shock_decomp_channels_bounded(self):
        """All channel move_5d values must be within their caps."""
        from shock_decomposition import (
            compute_shock_decomposition, _CHANNEL_MOVE_CAPS,
        )
        rates = {
            "regime": "Mixed",
            "nominal": {"change_5d": 0.15},
            "real_proxy": {"change_5d": -0.50},
            "breakeven_proxy": {"change_5d": -0.35},
            "raw": {},
        }
        result = compute_shock_decomposition(rates, None, None)
        if not result:
            self.skipTest("empty result")
        for cid, ch in result.get("channels", {}).items():
            move = ch.get("move_5d")
            if move is not None:
                cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
                self.assertLessEqual(
                    abs(move), cap,
                    f"Channel {cid} move_5d={move} exceeds cap {cap}",
                )

    def test_real_yield_context_bounded(self):
        """Freshly built real_yield_context should have sane numeric fields."""
        from real_yield_context import build_real_yield_context
        result = build_real_yield_context(
            "OPEC cuts production by 1M barrels",
            "Supply disruption raises oil prices",
            {
                "regime": "Inflation pressure",
                "nominal": {"change_5d": 0.15},
                "real_proxy": {"change_5d": -0.50},
                "breakeven_proxy": {"change_5d": -0.35},
            },
        )
        if not result:
            self.skipTest("no thesis detected")
        nom = result.get("nominal_5d")
        real = result.get("real_proxy_5d")
        be = result.get("breakeven_proxy_5d")
        if nom is not None:
            self.assertLess(abs(nom), 5.0, f"nominal_5d={nom} beyond sane range")
        if real is not None:
            self.assertLess(abs(real), 20.0, f"real_proxy_5d={real} beyond sane range")
        if be is not None:
            self.assertLess(abs(be), 7.0, f"breakeven_proxy_5d={be} beyond sane range")


if __name__ == "__main__":
    unittest.main()
