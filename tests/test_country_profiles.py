"""Tests for country_profiles — shape, enums, resolver, shock mapper,
drift prevention.
"""

from __future__ import annotations

import copy
import unittest

from country_profiles import (
    COMMODITY_DIMENSIONS,
    COUNTRY_PROFILES,
    COUNTRY_PROFILES_VERSION,
    FUNDING_MIXES,
    FX_REGIMES,
    IMPORT_LEVELS,
    REGIONS,
    RESERVE_LEVELS,
    countries_by_region,
    iter_profiles,
    load_country_profiles,
    map_shock_to_vulnerability,
    resolve_country,
    score_cohort,
    validate_country_profiles,
)


# ---------------------------------------------------------------------------
# Enum + version pins
# ---------------------------------------------------------------------------

class TestPins(unittest.TestCase):
    def test_version_pinned(self):
        self.assertEqual(COUNTRY_PROFILES_VERSION, "2026.04.01")
        self.assertEqual(
            COUNTRY_PROFILES["version"], COUNTRY_PROFILES_VERSION,
        )

    def test_reserve_levels_pinned(self):
        self.assertEqual(
            RESERVE_LEVELS, ("strong", "adequate", "thin", "critical"),
        )

    def test_import_levels_pinned(self):
        self.assertEqual(
            IMPORT_LEVELS, ("low", "moderate", "high", "severe"),
        )

    def test_funding_mixes_pinned(self):
        self.assertEqual(FUNDING_MIXES, (
            "domestic_funded", "mixed", "external_dependent", "usd_funded",
        ))

    def test_fx_regimes_pinned(self):
        self.assertEqual(FX_REGIMES, (
            "free_floating", "managed_float", "pegged",
            "crisis_multiple_rates",
        ))

    def test_commodity_dimensions_pinned(self):
        self.assertEqual(COMMODITY_DIMENSIONS, ("oil", "metals", "food"))

    def test_regions_pinned(self):
        self.assertEqual(REGIONS, frozenset({
            "DM NA", "DM EU", "DM Asia",
            "GCC",
            "EM EMEA", "EM Asia", "EM LatAm",
            "Africa",
        }))


# ---------------------------------------------------------------------------
# Load contract
# ---------------------------------------------------------------------------

class TestLoad(unittest.TestCase):
    def test_load_returns_validated_copy(self):
        reg = load_country_profiles()
        self.assertIn("profiles", reg)
        self.assertGreater(len(reg["profiles"]), 0)

    def test_load_returns_deep_copy(self):
        a = load_country_profiles()
        b = load_country_profiles()
        a["profiles"][0]["aliases"].append("MUTATED")
        self.assertNotIn("MUTATED", b["profiles"][0]["aliases"])
        self.assertNotIn(
            "MUTATED", COUNTRY_PROFILES["profiles"][0]["aliases"],
        )

    def test_live_registry_parses_clean(self):
        validate_country_profiles(copy.deepcopy(COUNTRY_PROFILES))


# ---------------------------------------------------------------------------
# Validation — every negative path must surface as ValueError.
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def _base(self) -> dict:
        return copy.deepcopy(COUNTRY_PROFILES)

    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            validate_country_profiles([])

    def test_missing_top_level_keys(self):
        r = self._base()
        del r["profiles"]
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_extra_top_level_keys(self):
        r = self._base()
        r["unexpected"] = True
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_bad_updated_at(self):
        r = self._base()
        r["updated_at"] = "04-19-2026"
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_profile_bad_region(self):
        r = self._base()
        r["profiles"][0]["region"] = "Atlantis"
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_profile_bad_reserve_level(self):
        r = self._base()
        r["profiles"][0]["reserve_coverage"]["level"] = "excessive"
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_profile_bad_import_level(self):
        r = self._base()
        r["profiles"][0]["import_dependence"]["oil"] = "extreme"
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_profile_bad_funding_mix_level(self):
        r = self._base()
        r["profiles"][0]["funding_mix"]["level"] = "gold_backed"
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_profile_bad_fx_regime(self):
        r = self._base()
        r["profiles"][0]["funding_mix"]["fx_regime"] = "gold_standard"
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_reserve_score_out_of_range(self):
        r = self._base()
        r["profiles"][0]["reserve_coverage"]["score"] = 1.2
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_usd_debt_share_out_of_range(self):
        r = self._base()
        r["profiles"][0]["funding_mix"]["usd_debt_share"] = -0.1
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_commodity_sensitivity_out_of_range(self):
        r = self._base()
        r["profiles"][0]["commodity_sensitivity"]["oil"] = 4
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_duplicate_iso(self):
        r = self._base()
        r["profiles"].append({
            **copy.deepcopy(r["profiles"][0]),
            "name": "Clone",
            "aliases": ["ZZZZ-unique"],
        })
        with self.assertRaises(ValueError) as cm:
            validate_country_profiles(r)
        self.assertIn("duplicate iso", str(cm.exception))

    def test_duplicate_label_across_profiles(self):
        r = self._base()
        r["profiles"][1]["aliases"].append(r["profiles"][0]["name"])
        with self.assertRaises(ValueError) as cm:
            validate_country_profiles(r)
        self.assertIn("more than one profile", str(cm.exception))

    def test_missing_commodity_dim(self):
        r = self._base()
        del r["profiles"][0]["commodity_sensitivity"]["oil"]
        with self.assertRaises(ValueError):
            validate_country_profiles(r)

    def test_unknown_profile_key(self):
        r = self._base()
        r["profiles"][0]["mystery"] = "x"
        with self.assertRaises(ValueError):
            validate_country_profiles(r)


# ---------------------------------------------------------------------------
# Resolver + region lookup
# ---------------------------------------------------------------------------

class TestResolver(unittest.TestCase):
    def test_resolve_by_name(self):
        p = resolve_country("Turkey")
        self.assertIsNotNone(p)
        self.assertEqual(p["iso"], "TR")

    def test_resolve_by_iso(self):
        p = resolve_country("TR")
        self.assertEqual(p["name"], "Turkey")

    def test_resolve_by_alias(self):
        p = resolve_country("UAE")
        self.assertEqual(p["iso"], "AE")

    def test_resolve_case_insensitive(self):
        p = resolve_country("turkey")
        self.assertEqual(p["iso"], "TR")

    def test_unknown_returns_none(self):
        self.assertIsNone(resolve_country("Atlantis"))

    def test_none_returns_none(self):
        self.assertIsNone(resolve_country(None))
        self.assertIsNone(resolve_country(""))

    def test_countries_by_region(self):
        dm_na = countries_by_region("DM NA")
        self.assertGreaterEqual(len(dm_na), 1)
        for p in dm_na:
            self.assertEqual(p["region"], "DM NA")

    def test_every_region_populated(self):
        populated = {p["region"] for p in iter_profiles()}
        # The registry must cover at least each of the main macro blocs.
        for required in ("DM NA", "DM EU", "DM Asia", "GCC",
                         "EM EMEA", "EM Asia", "EM LatAm"):
            self.assertIn(required, populated)


# ---------------------------------------------------------------------------
# Shock-mapping semantics
# ---------------------------------------------------------------------------

class TestShockMapping(unittest.TestCase):
    def test_unknown_profile_returns_unavailable(self):
        r = map_shock_to_vulnerability(None, {"dxy_change_pct": 2.0})
        self.assertFalse(r["available"])

    def test_unknown_shock_returns_unavailable(self):
        p = resolve_country("Turkey")
        r = map_shock_to_vulnerability(p, None)
        self.assertFalse(r["available"])

    def test_zero_shock_is_calm(self):
        p = resolve_country("Turkey")
        r = map_shock_to_vulnerability(p, {
            "dxy_change_pct": 0, "crude_5d_pct": 0,
            "credit_spread_bps": 0, "real_yield_bps": 0,
        })
        self.assertEqual(r["stress_label"], "calm")
        self.assertEqual(r["total_stress"], 0.0)

    def test_usd_rally_hits_usd_funded_more_than_domestic(self):
        shock = {"dxy_change_pct": 2.0, "crude_5d_pct": 0,
                 "credit_spread_bps": 0, "real_yield_bps": 0}
        tr = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        us = map_shock_to_vulnerability(resolve_country("United States"), shock)
        jp = map_shock_to_vulnerability(resolve_country("Japan"), shock)
        self.assertGreater(tr["channel_stress"]["fx"], us["channel_stress"]["fx"])
        self.assertGreater(tr["channel_stress"]["fx"], jp["channel_stress"]["fx"])

    def test_crude_spike_hits_oil_importer_not_exporter(self):
        shock = {"dxy_change_pct": 0, "crude_5d_pct": 10,
                 "credit_spread_bps": 0, "real_yield_bps": 0}
        jp = map_shock_to_vulnerability(resolve_country("Japan"), shock)
        sa = map_shock_to_vulnerability(resolve_country("Saudi Arabia"), shock)
        self.assertGreater(jp["channel_stress"]["commodity"], 0.0)
        self.assertEqual(sa["channel_stress"]["commodity"], 0.0)

    def test_crude_collapse_does_not_hurt_importer(self):
        shock = {"dxy_change_pct": 0, "crude_5d_pct": -10,
                 "credit_spread_bps": 0, "real_yield_bps": 0}
        jp = map_shock_to_vulnerability(resolve_country("Japan"), shock)
        # Importer + crude down → commodity channel should be 0.
        self.assertEqual(jp["channel_stress"]["commodity"], 0.0)

    def test_critical_reserves_amplify_stress(self):
        """Turkey (critical reserves) must score higher than Poland
        (adequate) on the identical FX shock, all else equal."""
        shock = {"dxy_change_pct": 2.0, "crude_5d_pct": 0,
                 "credit_spread_bps": 0, "real_yield_bps": 0}
        tr = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        pl = map_shock_to_vulnerability(resolve_country("Poland"), shock)
        self.assertGreater(tr["total_stress"], pl["total_stress"])

    def test_credit_widening_feeds_funding_channel(self):
        shock = {"dxy_change_pct": 0, "crude_5d_pct": 0,
                 "credit_spread_bps": 200, "real_yield_bps": 0}
        tr = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        us = map_shock_to_vulnerability(resolve_country("United States"), shock)
        self.assertGreater(tr["channel_stress"]["funding"],
                           us["channel_stress"]["funding"])

    def test_primary_channel_identified(self):
        shock = {"dxy_change_pct": 3.0, "crude_5d_pct": 0,
                 "credit_spread_bps": 0, "real_yield_bps": 0}
        r = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        self.assertEqual(r["primary_channel"], "fx")

    def test_acute_label_on_extreme_shock(self):
        shock = {"dxy_change_pct": 3.0, "crude_5d_pct": 12,
                 "credit_spread_bps": 200, "real_yield_bps": 50}
        r = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        self.assertEqual(r["stress_label"], "acute")

    def test_commodity_exporter_cushions_from_crude(self):
        shock = {"dxy_change_pct": 2.0, "crude_5d_pct": 8,
                 "credit_spread_bps": 0, "real_yield_bps": 0}
        sa = map_shock_to_vulnerability(resolve_country("Saudi Arabia"), shock)
        tr = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        self.assertLess(sa["total_stress"], tr["total_stress"])

    def test_rationale_is_nonempty(self):
        shock = {"dxy_change_pct": 2.0, "crude_5d_pct": 8,
                 "credit_spread_bps": 100, "real_yield_bps": 0}
        r = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        self.assertTrue(r["rationale"])

    def test_stress_is_bounded(self):
        shock = {"dxy_change_pct": 10.0, "crude_5d_pct": 30,
                 "credit_spread_bps": 500, "real_yield_bps": 200}
        r = map_shock_to_vulnerability(resolve_country("Turkey"), shock)
        self.assertLessEqual(r["total_stress"], 1.0)
        for axis in r["channel_stress"].values():
            self.assertLessEqual(axis, 1.0)
            self.assertGreaterEqual(axis, 0.0)

    def test_deterministic_repeat(self):
        p = resolve_country("Turkey")
        shock = {"dxy_change_pct": 1.5, "crude_5d_pct": 5,
                 "credit_spread_bps": 100, "real_yield_bps": 20}
        r1 = map_shock_to_vulnerability(p, shock)
        r2 = map_shock_to_vulnerability(p, shock)
        self.assertEqual(r1, r2)


class TestCohort(unittest.TestCase):
    def test_cohort_sorted_by_total_stress(self):
        shock = {"dxy_change_pct": 2.0, "crude_5d_pct": 6,
                 "credit_spread_bps": 100, "real_yield_bps": 0}
        rows = score_cohort(
            ["United States", "Turkey", "Saudi Arabia", "Pakistan"], shock,
        )
        totals = [r["total_stress"] for r in rows]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_unknown_labels_surface_available_false(self):
        rows = score_cohort(["Atlantis", "Turkey"],
                            {"dxy_change_pct": 2.0})
        atlantis = next(r for r in rows if r["country"] == "Atlantis")
        self.assertFalse(atlantis["available"])
        self.assertIn("No maintained profile", atlantis["rationale"])

    def test_none_cohort_safe(self):
        self.assertEqual(score_cohort(None, {}), [])

    def test_aliases_resolve_in_cohort(self):
        rows = score_cohort(["UAE", "USA"], {"dxy_change_pct": 1.0})
        for r in rows:
            self.assertTrue(r["available"])


# ---------------------------------------------------------------------------
# Drift prevention — the whole point of the registry.
# ---------------------------------------------------------------------------

class TestDrift(unittest.TestCase):
    """Every profile must be discoverable by existing legacy country
    modules so downstream callers can migrate progressively without
    half the archive's country references silently missing."""

    def test_every_profile_has_source_note(self):
        for p in iter_profiles():
            self.assertTrue(
                p["source_note"],
                msg=f"{p['name']} missing source_note",
            )

    def test_every_profile_has_updated_at(self):
        for p in iter_profiles():
            self.assertTrue(p["updated_at"])

    def test_country_name_uniqueness(self):
        names = [p["name"] for p in iter_profiles()]
        self.assertEqual(
            len(names), len(set(names)),
            msg="profile names are not unique",
        )

    def test_iso_uniqueness(self):
        isos = [p["iso"] for p in iter_profiles()]
        self.assertEqual(
            len(isos), len(set(isos)),
            msg="profile ISO codes are not unique",
        )

    def test_registry_covers_cross_module_anchors(self):
        """A handful of countries appear in every legacy vulnerability
        module.  If we drop one from the registry by accident, flag it."""
        anchors = {
            "Turkey", "Saudi Arabia", "Japan", "China",
            "India", "Brazil", "United States", "Eurozone",
        }
        registered = {p["name"] for p in iter_profiles()}
        missing = anchors - registered
        self.assertFalse(
            missing,
            msg=(
                f"country_profiles dropped cross-module anchor countries: "
                f"{sorted(missing)}"
            ),
        )

    def test_profile_count_pinned(self):
        """Coverage changes force a visible test diff."""
        self.assertEqual(len(COUNTRY_PROFILES["profiles"]), 24)


if __name__ == "__main__":
    unittest.main()
