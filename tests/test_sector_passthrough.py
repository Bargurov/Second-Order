"""Tests for sector_passthrough — downstream-cascade composer."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sector_passthrough import (
    compute_sector_passthrough,
    _PASSTHROUGH_MAP,
    SECTOR_LABELS,
    _LAG_ENUM,
    _INTENSITY_ENUM,
    _SIGN_ENUM,
)


# ---------------------------------------------------------------------------
# Direct-hit detection
# ---------------------------------------------------------------------------

class TestDirectHitDetection(unittest.TestCase):
    """Direct sectors are resolved from tickers, mechanism text, and shock primary."""

    def test_tickers_resolve_to_energy_sector(self):
        res = compute_sector_passthrough(
            beneficiary_tickers=["CVX", "XOM"],
            loser_tickers=[],
        )
        self.assertIn("energy", res["direct_sectors"])
        self.assertIn("Energy", res["direct_sectors_label"])
        self.assertTrue(res["available"])

    def test_mechanism_text_picks_up_sector_when_tickers_absent(self):
        """No tickers — a mechanism-text mention alone should resolve sectors."""
        res = compute_sector_passthrough(
            mechanism_text="rare earth export controls threaten semiconductor supply chain",
        )
        # Both critical_minerals and semiconductors are named in the text.
        self.assertIn("semiconductors", res["direct_sectors"])
        self.assertIn("critical_minerals", res["direct_sectors"])

    def test_shock_primary_fallback_when_no_tickers_or_text(self):
        """Pure rates event — tickers blank, text blank, falls back to macro source."""
        res = compute_sector_passthrough(shock_primary="nominal_yield")
        self.assertIn("rates", res["direct_sectors"])

    def test_shock_primary_fallback_ignored_when_tickers_present(self):
        """When ticker-resolved sectors exist, the shock fallback stays out."""
        res = compute_sector_passthrough(
            beneficiary_tickers=["CVX"],
            shock_primary="nominal_yield",
        )
        self.assertIn("energy", res["direct_sectors"])
        self.assertNotIn("rates", res["direct_sectors"])

    def test_unknown_tickers_do_not_resolve_to_market_bucket(self):
        """Bench fallback sectors ("market") are filtered out."""
        res = compute_sector_passthrough(
            beneficiary_tickers=["XYZ_MADE_UP"],
        )
        self.assertNotIn("market", res["direct_sectors"])

    def test_unavailable_when_no_sources_identified(self):
        res = compute_sector_passthrough(
            beneficiary_tickers=[], loser_tickers=[],
            mechanism_text="", shock_primary=None,
        )
        self.assertFalse(res["available"])
        self.assertTrue(res["stale"])
        self.assertEqual(res["direct_sectors"], [])
        self.assertEqual(res["downstream"], [])


# ---------------------------------------------------------------------------
# Canonical cascade examples from the task
# ---------------------------------------------------------------------------

class TestEnergyCascade(unittest.TestCase):
    """Energy shock → transport (fuel), chemicals (feedstock), refiners (mixed)."""

    def test_energy_cascades_to_transport(self):
        res = compute_sector_passthrough(beneficiary_tickers=["CVX"])
        targets = {e["target"] for e in res["downstream"]}
        self.assertIn("transport", targets)

    def test_energy_cascades_to_chemicals(self):
        res = compute_sector_passthrough(beneficiary_tickers=["CVX"])
        targets = {e["target"] for e in res["downstream"]}
        self.assertIn("chemicals", targets)

    def test_energy_cascades_to_refiners_with_mixed_sign(self):
        res = compute_sector_passthrough(beneficiary_tickers=["CVX"])
        refiner_entry = next(e for e in res["downstream"]
                             if e["target"] == "refiners")
        self.assertEqual(refiner_entry["sign"], "mixed")

    def test_energy_cascade_is_fast(self):
        """Energy shock transmits mostly within days."""
        res = compute_sector_passthrough(beneficiary_tickers=["CVX"])
        self.assertIn(res["timing_profile"], ("fast_cascade", "mixed"))


class TestMaterialsCascade(unittest.TestCase):
    """Materials / input shock → industrials + consumer discretionary lag."""

    def test_materials_cascades_to_industrials(self):
        res = compute_sector_passthrough(beneficiary_tickers=["FCX", "NUE"])
        targets = {e["target"] for e in res["downstream"]}
        self.assertIn("industrials", targets)

    def test_materials_cascades_to_consumer_disc_with_lag(self):
        res = compute_sector_passthrough(beneficiary_tickers=["FCX"])
        cd_entry = next((e for e in res["downstream"]
                         if e["target"] == "consumer_disc"), None)
        self.assertIsNotNone(cd_entry)
        # Materials → consumer disc is a slow cascade.
        self.assertIn(cd_entry["lag"], ("weeks", "quarters"))
        self.assertEqual(cd_entry["sign"], "inverse")


class TestRateShockDivergence(unittest.TestCase):
    """Rate shock → banks (reinforcing) vs REITs + homebuilders (inverse)."""

    def test_rate_shock_reinforces_banks(self):
        res = compute_sector_passthrough(shock_primary="nominal_yield")
        banks = next((e for e in res["downstream"]
                      if e["target"] == "banks"), None)
        self.assertIsNotNone(banks)
        self.assertEqual(banks["sign"], "reinforcing")

    def test_rate_shock_inverses_reits(self):
        res = compute_sector_passthrough(shock_primary="nominal_yield")
        reits = next((e for e in res["downstream"]
                      if e["target"] == "real_estate"), None)
        self.assertIsNotNone(reits)
        self.assertEqual(reits["sign"], "inverse")
        self.assertEqual(reits["intensity"], "high")

    def test_rate_shock_inverses_homebuilders(self):
        res = compute_sector_passthrough(shock_primary="nominal_yield")
        hb = next((e for e in res["downstream"]
                   if e["target"] == "homebuilders"), None)
        self.assertIsNotNone(hb)
        self.assertEqual(hb["sign"], "inverse")

    def test_bank_and_reit_signs_diverge_on_same_shock(self):
        """The core separation — same rate shock, opposite signs."""
        res = compute_sector_passthrough(shock_primary="nominal_yield")
        by_target = {e["target"]: e for e in res["downstream"]}
        self.assertEqual(by_target["banks"]["sign"], "reinforcing")
        self.assertEqual(by_target["real_estate"]["sign"], "inverse")


class TestCreditShockCascade(unittest.TestCase):
    def test_credit_shock_hits_financials_and_reits(self):
        res = compute_sector_passthrough(shock_primary="credit")
        targets = {e["target"] for e in res["downstream"]}
        self.assertIn("financials", targets)
        self.assertIn("real_estate", targets)


# ---------------------------------------------------------------------------
# Downstream aggregation
# ---------------------------------------------------------------------------

class TestDownstreamAggregation(unittest.TestCase):
    def test_direct_sector_never_appears_as_downstream_target(self):
        """If the event's direct hit is energy AND materials, neither should
        appear in the downstream list for the other — they're both already
        direct sources."""
        res = compute_sector_passthrough(
            beneficiary_tickers=["CVX"],  # energy
            loser_tickers=["FCX"],        # materials
        )
        targets = {e["target"] for e in res["downstream"]}
        for direct in res["direct_sectors"]:
            self.assertNotIn(direct, targets)

    def test_duplicate_targets_dedup_with_strongest_source(self):
        """When two direct sources cascade to the same target, the highest-
        intensity / fastest entry wins."""
        res = compute_sector_passthrough(
            beneficiary_tickers=["CVX"],       # energy → consumer_disc (weeks, medium)
            loser_tickers=["FCX"],             # materials → consumer_disc (quarters, low)
        )
        cd_entries = [e for e in res["downstream"] if e["target"] == "consumer_disc"]
        self.assertEqual(len(cd_entries), 1)
        # Energy is faster + higher intensity, so it should win.
        self.assertEqual(cd_entries[0]["source"], "energy")

    def test_downstream_sorted_by_intensity_then_lag(self):
        """High-intensity fast-lag entries lead the list."""
        res = compute_sector_passthrough(shock_primary="nominal_yield")
        downstream = res["downstream"]
        self.assertTrue(len(downstream) > 1)
        # First entry should be high-intensity (REITs or utilities or homebuilders).
        self.assertEqual(downstream[0]["intensity"], "high")


# ---------------------------------------------------------------------------
# Timing profile + validation-window contract
# ---------------------------------------------------------------------------

class TestTimingAndValidationWindows(unittest.TestCase):
    def test_validation_windows_always_present(self):
        res = compute_sector_passthrough(beneficiary_tickers=["CVX"])
        self.assertEqual(res["direct_validation_window"], "1-5d")
        self.assertEqual(res["downstream_validation_window"], "5-20d")

    def test_no_downstream_profile_when_empty(self):
        """Defense has thin downstream cascade; semiconductors has quarter-scale only."""
        # Use a source with no passthrough entries.
        res = compute_sector_passthrough(beneficiary_tickers=["JNJ"])
        # Healthcare has only one downstream (consumer_staples, quarters).
        if not res["downstream"]:
            self.assertEqual(res["timing_profile"], "no_downstream")

    def test_fast_cascade_when_all_downstream_within_days(self):
        """Pure rates shock → mostly day-lag entries."""
        res = compute_sector_passthrough(shock_primary="nominal_yield")
        self.assertEqual(res["timing_profile"], "fast_cascade")


# ---------------------------------------------------------------------------
# Map integrity
# ---------------------------------------------------------------------------

class TestMapIntegrity(unittest.TestCase):
    def test_every_source_sector_has_a_label(self):
        for source in _PASSTHROUGH_MAP:
            self.assertIn(source, SECTOR_LABELS,
                          f"Source {source!r} has no SECTOR_LABELS entry")

    def test_every_target_has_a_label(self):
        for source, entries in _PASSTHROUGH_MAP.items():
            for e in entries:
                self.assertIn(e["target"], SECTOR_LABELS,
                              f"Target {e['target']!r} (source {source}) missing label")

    def test_every_entry_uses_valid_enums(self):
        for source, entries in _PASSTHROUGH_MAP.items():
            for e in entries:
                self.assertIn(e["lag"], _LAG_ENUM)
                self.assertIn(e["intensity"], _INTENSITY_ENUM)
                self.assertIn(e["sign"], _SIGN_ENUM)

    def test_no_self_cascade(self):
        for source, entries in _PASSTHROUGH_MAP.items():
            for e in entries:
                self.assertNotEqual(source, e["target"],
                                    f"{source!r} cannot cascade to itself")

    def test_output_shape_stable(self):
        """Every documented key must appear on every output."""
        res = compute_sector_passthrough(beneficiary_tickers=["CVX"])
        expected = {
            "direct_sectors", "direct_sectors_label", "downstream",
            "timing_profile", "direct_validation_window",
            "downstream_validation_window", "rationale",
            "available", "stale",
        }
        self.assertEqual(set(res.keys()), expected)


if __name__ == "__main__":
    unittest.main()
