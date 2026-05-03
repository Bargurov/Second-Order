"""Focused tests for country_backdrop fixture + normaliser + integrations."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from country_backdrop import (
    COUNTRY_BACKDROP_FIXTURE,
    attach_country_backdrop,
    get_country_backdrop,
    normalize_country_backdrop,
)


# ---------------------------------------------------------------------------
# Fixture shape
# ---------------------------------------------------------------------------

class TestFixture(unittest.TestCase):
    _required = (
        "iso", "reserves_months_import", "current_account_pct_gdp",
        "external_debt_pct_exports", "fuel_import_dependence",
        "food_import_dependence", "commodity_export_share",
    )

    def test_each_profile_has_required_fields(self) -> None:
        for name, profile in COUNTRY_BACKDROP_FIXTURE.items():
            with self.subTest(name=name):
                for field in self._required:
                    self.assertIn(field, profile, msg=f"{name} missing {field}")
                # Numeric ranges.
                self.assertGreaterEqual(profile["reserves_months_import"], 0.0)
                self.assertGreaterEqual(profile["external_debt_pct_exports"], 0.0)
                for share_field in (
                    "fuel_import_dependence", "food_import_dependence",
                    "commodity_export_share",
                ):
                    v = profile[share_field]
                    self.assertGreaterEqual(v, 0.0, msg=f"{name}.{share_field}")
                    self.assertLessEqual(v, 1.0, msg=f"{name}.{share_field}")

    def test_get_country_backdrop_resolves_canonical_name(self) -> None:
        self.assertIsNotNone(get_country_backdrop("Turkey"))
        # Case-insensitive.
        self.assertIsNotNone(get_country_backdrop("turkey"))
        # Unknown country returns None — never a half-shaped default.
        self.assertIsNone(get_country_backdrop("Atlantis"))

    def test_get_country_backdrop_rejects_blank_input(self) -> None:
        self.assertIsNone(get_country_backdrop(None))
        self.assertIsNone(get_country_backdrop(""))
        self.assertIsNone(get_country_backdrop("   "))


# ---------------------------------------------------------------------------
# Normaliser — output shape + bucketing
# ---------------------------------------------------------------------------

class TestNormalizer(unittest.TestCase):
    _block_keys = {
        "country", "external_balance_risk", "import_shock_risk",
        "commodity_dependence", "overall_vulnerability", "rationale", "stale",
    }

    def test_unknown_country_returns_none(self) -> None:
        self.assertIsNone(normalize_country_backdrop("Atlantis"))

    def test_block_shape_stable(self) -> None:
        block = normalize_country_backdrop("Turkey")
        self.assertIsNotNone(block)
        self.assertEqual(set(block.keys()), self._block_keys)

    def test_stale_when_field_missing(self) -> None:
        block = normalize_country_backdrop(
            "synthetic",
            profile={"reserves_months_import": 3.0},  # only one field
        )
        self.assertIsNotNone(block)
        self.assertTrue(block["stale"])

    def test_stale_false_on_complete_fixture(self) -> None:
        block = normalize_country_backdrop("Saudi Arabia")
        self.assertFalse(block["stale"])

    # ------------- bucket validation on representative countries -------------

    def test_saudi_arabia_resilient_overall(self) -> None:
        block = normalize_country_backdrop("Saudi Arabia")
        self.assertEqual(block["external_balance_risk"], "resilient")
        # Saudi imports nearly all food — import_shock_risk is real…
        self.assertEqual(block["import_shock_risk"], "fragile")
        # …but a resilient external balance buffers it; overall stays resilient.
        self.assertEqual(block["overall_vulnerability"], "resilient")
        self.assertEqual(block["commodity_dependence"], "dominant")

    def test_turkey_fragile_overall(self) -> None:
        block = normalize_country_backdrop("Turkey")
        self.assertEqual(block["external_balance_risk"], "vulnerable")
        self.assertEqual(block["import_shock_risk"], "fragile")
        self.assertEqual(block["overall_vulnerability"], "fragile")

    def test_argentina_fragile_external_balance(self) -> None:
        block = normalize_country_backdrop("Argentina")
        self.assertEqual(block["external_balance_risk"], "fragile")
        self.assertEqual(block["overall_vulnerability"], "fragile")

    def test_brazil_moderate_overall(self) -> None:
        block = normalize_country_backdrop("Brazil")
        self.assertEqual(block["external_balance_risk"], "moderate")
        self.assertEqual(block["overall_vulnerability"], "moderate")
        self.assertEqual(block["commodity_dependence"], "high")

    def test_india_capped_at_vulnerable(self) -> None:
        # India has 11mo reserves + low ext-debt (moderate external) but
        # 85% fuel-import dependence (fragile import_shock).  The cap
        # rule keeps overall at vulnerable — fragile would over-state
        # the desk read for an economy that can pay for the imports.
        block = normalize_country_backdrop("India")
        self.assertEqual(block["external_balance_risk"], "moderate")
        self.assertEqual(block["import_shock_risk"], "fragile")
        self.assertEqual(block["overall_vulnerability"], "vulnerable")


# ---------------------------------------------------------------------------
# attach_country_backdrop — list-mutation pattern; stable for unprofiled rows
# ---------------------------------------------------------------------------

class TestAttachToExposures(unittest.TestCase):
    def test_profiled_country_gets_block(self) -> None:
        exposures = [{"country": "Turkey", "role": "loser"}]
        out = attach_country_backdrop(exposures)
        self.assertEqual(len(out), 1)
        self.assertIn("country_backdrop", out[0])
        self.assertEqual(
            out[0]["country_backdrop"]["overall_vulnerability"], "fragile",
        )

    def test_unprofiled_country_is_byte_identical(self) -> None:
        original = {"country": "Atlantis", "role": "loser", "weight": 1}
        out = attach_country_backdrop([original])
        self.assertEqual(len(out), 1)
        self.assertNotIn("country_backdrop", out[0])
        self.assertEqual(out[0], original)

    def test_input_list_is_not_mutated(self) -> None:
        exposures = [{"country": "Turkey"}, {"country": "Atlantis"}]
        out = attach_country_backdrop(exposures)
        # Inputs stay as-is; new dicts were returned in the result.
        self.assertNotIn("country_backdrop", exposures[0])
        self.assertNotIn("country_backdrop", exposures[1])
        # Returned profiled entry is a different dict.
        self.assertIsNot(out[0], exposures[0])

    def test_empty_or_none_inputs(self) -> None:
        self.assertEqual(attach_country_backdrop([]), [])
        self.assertEqual(attach_country_backdrop(None), [])

    def test_non_dict_entries_pass_through(self) -> None:
        exposures = ["not-a-dict", 7, {"country": "Turkey"}]
        out = attach_country_backdrop(exposures)
        self.assertEqual(out[0], "not-a-dict")
        self.assertEqual(out[1], 7)
        self.assertIn("country_backdrop", out[2])


# ---------------------------------------------------------------------------
# Integration — terms_of_trade attaches the block when country is on the list
# ---------------------------------------------------------------------------

class TestTermsOfTradeIntegration(unittest.TestCase):
    def test_block_attached_on_profiled_exposure(self) -> None:
        from terms_of_trade import compute_terms_of_trade
        # Headline + mech text that triggers an oil/import theme so the
        # composer builds an exposure list.  Snapshots provide a crude
        # 5d move so the channel resolves.
        snapshots = [
            {"market": "CL", "change_5d": 5.0},
            {"market": "DXY", "change_5d": 0.5},
        ]
        result = compute_terms_of_trade(
            "Turkey hit by crude squeeze, lira slides",
            "Crude price spike widens import bill for net oil importers.",
            snapshots=snapshots,
        )
        self.assertTrue(result.get("available"))
        # At least one exposure should be a profiled country with a backdrop.
        with_backdrop = [
            e for e in (result.get("exposures") or [])
            if isinstance(e, dict) and "country_backdrop" in e
        ]
        self.assertTrue(
            with_backdrop,
            msg="Expected at least one exposure to carry country_backdrop",
        )
        for entry in with_backdrop:
            block = entry["country_backdrop"]
            for key in (
                "external_balance_risk", "import_shock_risk",
                "commodity_dependence", "overall_vulnerability",
                "rationale", "stale",
            ):
                self.assertIn(key, block)


if __name__ == "__main__":
    unittest.main()
