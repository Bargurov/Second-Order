"""Focused tests for the Terms-of-Trade / External Vulnerability composer.

Required scenarios:
  - Oil shock importer/exporter split
  - FX / external-balance stress (pure DXY spike, no commodity catalyst)
  - Mixed or unclear exposure
  - Stale / unavailable context

Plus helper coverage (theme detection, channel resolution, stress
fallback) so the classifier can't be silently reshaped.
"""

from __future__ import annotations

import unittest

from terms_of_trade import (
    CHANNEL_IDS,
    compute_terms_of_trade,
    _detect_theme,
    _dxy_from_stress,
    _resolve_channel,
    _snap_change_5d,
)


# ---------------------------------------------------------------------------
# Canonical inputs
# ---------------------------------------------------------------------------

def _snap(market: str, change_5d: float) -> dict:
    return {
        "market":    market,
        "symbol":    market,
        "label":     market,
        "unit":      "idx",
        "asset_class": "commodity" if market in ("CL", "GC") else "currency",
        "source":    "test",
        "value":     100.0,
        "change_1d": 0.0,
        "change_5d": change_5d,
        "fetched_at": "2026-04-07T00:00:00+00:00",
        "error":     None,
        "stale":     False,
    }


def _stress_with_dollar(dollar_5d: float | None) -> dict:
    return {
        "regime": "calm",
        "signals": {},
        "raw":    {},
        "detail": {
            "safe_haven": {
                "label":  "Safe Haven Flows",
                "assets": {"Gold": 0.1, "Dollar": dollar_5d, "Long Bonds": 0.2},
            },
        },
    }


# ---------------------------------------------------------------------------
# Helper-level coverage
# ---------------------------------------------------------------------------

class TestSnapChange5d(unittest.TestCase):
    def test_returns_value_when_present(self):
        self.assertEqual(_snap_change_5d([_snap("CL", 4.5)], "CL"), 4.5)

    def test_none_on_missing_market(self):
        self.assertIsNone(_snap_change_5d([_snap("CL", 4.5)], "DXY"))

    def test_none_on_error_row(self):
        snap = _snap("CL", 4.5)
        snap["error"] = "provider down"
        self.assertIsNone(_snap_change_5d([snap], "CL"))

    def test_none_on_empty_input(self):
        self.assertIsNone(_snap_change_5d(None, "CL"))
        self.assertIsNone(_snap_change_5d([], "CL"))


class TestDxyFromStress(unittest.TestCase):
    def test_reads_dollar_from_safe_haven(self):
        self.assertEqual(_dxy_from_stress(_stress_with_dollar(1.2)), 1.2)

    def test_none_when_missing(self):
        self.assertIsNone(_dxy_from_stress(None))
        self.assertIsNone(_dxy_from_stress({}))
        self.assertIsNone(_dxy_from_stress({"detail": {}}))

    def test_none_when_dollar_absent(self):
        s = _stress_with_dollar(None)
        self.assertIsNone(_dxy_from_stress(s))


class TestDetectTheme(unittest.TestCase):
    def test_inventory_proxy_wins(self):
        inv = {"proxy": "WEAT", "proxy_label": "Wheat"}
        # Even with an unrelated headline the proxy routes to "food"
        self.assertEqual(_detect_theme("random story", inv), "food")

    def test_keyword_fallback_oil(self):
        self.assertEqual(_detect_theme("OPEC cuts crude output", None), "oil")

    def test_keyword_fallback_metal(self):
        self.assertEqual(_detect_theme("Chile copper strike hits global supply", None), "metal")

    def test_none_when_nothing_matches(self):
        self.assertEqual(_detect_theme("Fed raises rates 25bps", None), "none")

    def test_inventory_semiconductor_is_not_tot_channel(self):
        inv = {"proxy": "SMH", "proxy_label": "Semiconductors"}
        # SMH maps to "none" — proxy doesn't force a channel.
        self.assertEqual(_detect_theme("chip foundry outage", inv), "none")


class TestResolveChannel(unittest.TestCase):
    def test_oil_theme_positive_crude_importers_lose(self):
        ch, _basis = _resolve_channel("oil", crude_5d=5.0, dxy_5d=0.0)
        self.assertEqual(ch, "oil_import")

    def test_oil_theme_negative_crude_exporters_lose(self):
        ch, _basis = _resolve_channel("oil", crude_5d=-5.0, dxy_5d=0.0)
        self.assertEqual(ch, "oil_export")

    def test_food_theme(self):
        ch, _basis = _resolve_channel("food", crude_5d=None, dxy_5d=None)
        self.assertEqual(ch, "food_import")

    def test_metal_theme(self):
        ch, _basis = _resolve_channel("metal", crude_5d=None, dxy_5d=0.2)
        self.assertEqual(ch, "industrial_metal")

    def test_pure_dxy_rally_triggers_usd_funding(self):
        ch, _basis = _resolve_channel("none", crude_5d=None, dxy_5d=1.5)
        self.assertEqual(ch, "usd_funding")

    def test_moderate_dxy_still_usd_funding(self):
        ch, _basis = _resolve_channel("none", crude_5d=None, dxy_5d=0.8)
        self.assertEqual(ch, "usd_funding")

    def test_no_inputs_returns_none(self):
        ch, _basis = _resolve_channel("none", crude_5d=None, dxy_5d=None)
        self.assertEqual(ch, "none")


# ---------------------------------------------------------------------------
# Required scenarios
# ---------------------------------------------------------------------------

class TestOilShockImporterExporterSplit(unittest.TestCase):
    """Crude rallies hard → importers lose, exporters win."""

    def test_oil_rally_importer_exporter_split(self):
        out = compute_terms_of_trade(
            headline="OPEC+ cuts output as Middle East tensions escalate",
            mechanism_text="Crude supply shock pushes oil prices materially higher.",
            inventory_context={"proxy": "USO", "proxy_label": "Crude Oil (USO)"},
            snapshots=[_snap("CL", 6.5), _snap("DXY", 0.2)],
            stress_regime=None,
        )
        self.assertEqual(out["dominant_channel"], "oil_import")
        self.assertEqual(out["signals"]["matched_theme"], "oil")
        self.assertIn("Japan", out["external_losers"])
        self.assertIn("India", out["external_losers"])
        self.assertIn("Saudi Arabia", out["external_winners"])
        self.assertIn("Norway", out["external_winners"])
        self.assertTrue(out["available"])
        self.assertFalse(out["stale"])
        # Each exposure entry should carry a full shape for the UI.
        for exp in out["exposures"]:
            self.assertIn("country", exp)
            self.assertIn("region", exp)
            self.assertIn("role", exp)
            self.assertIn("channel", exp)
            self.assertIn("rationale", exp)

    def test_oil_selloff_flips_winners_and_losers(self):
        out = compute_terms_of_trade(
            headline="OPEC+ unexpectedly lifts production",
            mechanism_text="Crude prices collapse on supply glut.",
            inventory_context={"proxy": "USO", "proxy_label": "Crude Oil (USO)"},
            snapshots=[_snap("CL", -6.5), _snap("DXY", -0.1)],
            stress_regime=None,
        )
        # Crude selloff → resolver routes to oil_export channel, but the
        # sign means exporters are actually the losers and importers win.
        self.assertEqual(out["dominant_channel"], "oil_export")
        self.assertIn("Japan", out["external_winners"])
        self.assertIn("Saudi Arabia", out["external_losers"])
        self.assertIn("Russia", out["external_losers"])


class TestFxExternalBalanceStress(unittest.TestCase):
    """Strong DXY rally with no commodity catalyst → usd_funding channel."""

    def test_pure_dxy_rally(self):
        out = compute_terms_of_trade(
            headline="Fed signals higher-for-longer, dollar rallies broadly",
            mechanism_text="Real yields rise; carry trades unwind.",
            inventory_context={},
            snapshots=[_snap("DXY", 1.8)],
            stress_regime=None,
        )
        self.assertEqual(out["dominant_channel"], "usd_funding")
        self.assertIn("Turkey", out["external_losers"])
        self.assertIn("Argentina", out["external_losers"])
        self.assertEqual(out["external_winners"], [])
        self.assertTrue(out["available"])

    def test_dxy_from_stress_regime_fallback(self):
        """When snapshots are unavailable, DXY is read from the stress
        regime's already-fetched safe-haven block — same number, no I/O."""
        out = compute_terms_of_trade(
            headline="USD climbs vs all majors on hawkish Fed",
            mechanism_text="Strong dollar across the EM basket.",
            inventory_context={},
            snapshots=None,
            stress_regime=_stress_with_dollar(1.5),
        )
        self.assertEqual(out["dominant_channel"], "usd_funding")
        self.assertIn("Turkey", out["external_losers"])
        # snapshots=None so the block is marked stale even though DXY
        # came through via the fallback path.
        self.assertTrue(out["stale"])


class TestMixedOrUnclearExposure(unittest.TestCase):
    """No commodity catalyst and no meaningful DXY move → none / empty."""

    def test_fed_headline_without_fx_move(self):
        out = compute_terms_of_trade(
            headline="Fed holds rates steady, signals patient stance",
            mechanism_text="Policy unchanged; market reaction muted.",
            inventory_context={},
            snapshots=[_snap("DXY", 0.1), _snap("CL", 0.2)],
            stress_regime=None,
        )
        # None channel with empty exposures — caller can skip rendering.
        self.assertEqual(out["dominant_channel"], "none")
        self.assertEqual(out["exposures"], [])
        self.assertEqual(out["external_winners"], [])
        self.assertEqual(out["external_losers"], [])

    def test_semiconductor_is_not_a_tot_channel(self):
        out = compute_terms_of_trade(
            headline="Taiwan chip fab outage hits supply",
            mechanism_text="Memory and logic supply constrained.",
            inventory_context={"proxy": "SMH", "proxy_label": "Semiconductors"},
            snapshots=[_snap("DXY", 0.2), _snap("CL", 0.3)],
            stress_regime=None,
        )
        self.assertEqual(out["dominant_channel"], "none")


class TestStaleUnavailableContext(unittest.TestCase):
    """Degrades cleanly when snapshot / stress inputs are missing."""

    def test_everything_empty_returns_empty_dict(self):
        out = compute_terms_of_trade(
            headline="",
            mechanism_text="",
            inventory_context=None,
            snapshots=None,
            stress_regime=None,
        )
        self.assertEqual(out, {})

    def test_oil_theme_without_prices_still_renders_stale(self):
        out = compute_terms_of_trade(
            headline="OPEC+ considers output cuts",
            mechanism_text="Crude supply tightens ahead of the meeting.",
            inventory_context={"proxy": "USO", "proxy_label": "Crude Oil (USO)"},
            snapshots=None,
            stress_regime=None,
        )
        # No price signal but theme was detected → render a stale
        # oil_import block with crude marked as unavailable.  This is
        # the graceful-degradation path for the live /analyze flow
        # when the warm snapshot store is cold.
        self.assertEqual(out["dominant_channel"], "oil_import")
        self.assertTrue(out["stale"])
        self.assertIsNone(out["signals"]["crude_5d"])
        self.assertIsNone(out["signals"]["dxy_5d"])

    def test_oil_theme_with_stale_stress_fallback(self):
        """Oil theme + DXY from stress regime gives us a signal → stale."""
        out = compute_terms_of_trade(
            headline="OPEC+ considers output cuts",
            mechanism_text="Crude supply tightens ahead of the meeting.",
            inventory_context={"proxy": "USO", "proxy_label": "Crude Oil (USO)"},
            snapshots=None,
            stress_regime=_stress_with_dollar(0.3),
        )
        # Theme=oil with no crude and tiny DXY → oil_import with bias fragment
        self.assertEqual(out["dominant_channel"], "oil_import")
        self.assertTrue(out["stale"])

    def test_partial_snapshots_only_dxy(self):
        out = compute_terms_of_trade(
            headline="OPEC+ considers output cuts",
            mechanism_text="Crude supply tightens ahead of the meeting.",
            inventory_context={"proxy": "USO", "proxy_label": "Crude Oil (USO)"},
            snapshots=[_snap("DXY", 0.3)],  # no CL row
            stress_regime=None,
        )
        # Oil theme but no crude print → still oil_import with a mild bias,
        # and stale=True because the commodity leg is missing.
        self.assertEqual(out["dominant_channel"], "oil_import")
        self.assertTrue(out["stale"])
        self.assertIsNone(out["signals"]["crude_5d"])
        self.assertEqual(out["signals"]["dxy_5d"], 0.3)


# ---------------------------------------------------------------------------
# Shape contract — protects the frontend / persistence contract
# ---------------------------------------------------------------------------

class TestOutputShape(unittest.TestCase):
    def test_full_output_has_expected_fields(self):
        out = compute_terms_of_trade(
            headline="OPEC+ surprise cut",
            mechanism_text="Crude supply shock",
            inventory_context={"proxy": "USO"},
            snapshots=[_snap("CL", 5.0), _snap("DXY", 0.3)],
            stress_regime=None,
        )
        expected_keys = {
            "exposures", "external_winners", "external_losers",
            "dominant_channel", "dominant_channel_label", "rationale",
            "key_markets", "available", "stale", "signals",
        }
        self.assertTrue(expected_keys.issubset(out.keys()))
        self.assertIn(out["dominant_channel"], CHANNEL_IDS)
        self.assertIsInstance(out["exposures"], list)
        self.assertIsInstance(out["external_winners"], list)
        self.assertIsInstance(out["external_losers"], list)
        self.assertIsInstance(out["key_markets"], list)
        self.assertIsInstance(out["signals"], dict)
        self.assertIn("crude_5d", out["signals"])
        self.assertIn("dxy_5d", out["signals"])
        self.assertIn("matched_theme", out["signals"])
        self.assertIn("thresholds", out["signals"])


if __name__ == "__main__":
    unittest.main()
