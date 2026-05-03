"""
tests/test_validation_matrix.py

Contract tests for the mechanism-specific validation matrix.

Covers:
  1. Coverage — every mechanism_family has an entry.
  2. Invariant — primary-pack channels appear in the matrix's primary list.
  3. Timing vocabulary — all timing tokens come from the controlled set.
  4. False-positive discipline — every entry names a distinguishing_signal.
  5. Shape — composer returns a stable dict even for unknown families.
  6. Family specificity — spot-check that the four example families the
     task called out produce different primary-channel sets.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mechanism_family import (
    FAMILY_IDS, FAMILY_CHANNEL_PACKS,
    FAMILY_SUBTYPES,
    FAMILY_VALIDATION_MATRIX, TIMING_VOCABULARY,
    get_validation_matrix,
    infer_mechanism_subtype,
)
from validation_plan import compute_validation_matrix
from asset_selection import _ticker_channel


# ---------------------------------------------------------------------------
# 1. Coverage
# ---------------------------------------------------------------------------

class TestMatrixCoverage(unittest.TestCase):

    def test_every_family_has_an_entry(self):
        missing = set(FAMILY_IDS) - set(FAMILY_VALIDATION_MATRIX.keys())
        self.assertFalse(
            missing, f"FAMILY_VALIDATION_MATRIX missing families: {missing}",
        )

    def test_none_family_has_empty_shape(self):
        entry = FAMILY_VALIDATION_MATRIX["none"]
        self.assertEqual(entry["primary"], [])
        self.assertEqual(entry["secondary"], [])
        self.assertEqual(entry["false_positives"], [])
        self.assertEqual(entry["invalidation"], [])


# ---------------------------------------------------------------------------
# 2. Primary-pack invariant
# ---------------------------------------------------------------------------

class TestPrimaryInvariant(unittest.TestCase):
    """Every channel in ``FAMILY_CHANNEL_PACKS[fam]["first"]`` must appear
    in the matrix's primary list so the two registries can't drift."""

    def test_primary_is_superset_of_first_pack(self):
        for fam in FAMILY_IDS:
            if fam == "none":
                continue
            first = set(FAMILY_CHANNEL_PACKS[fam]["first"])
            primary_channels = {
                e["channel"] for e in FAMILY_VALIDATION_MATRIX[fam]["primary"]
            }
            missing = first - primary_channels
            self.assertFalse(
                missing,
                f"{fam}: primary pack channels {missing} not in matrix primary",
            )


# ---------------------------------------------------------------------------
# 3. Timing vocabulary
# ---------------------------------------------------------------------------

class TestTimingVocabulary(unittest.TestCase):

    def test_timing_tokens_are_controlled(self):
        for fam, entry in FAMILY_VALIDATION_MATRIX.items():
            for row in entry.get("primary", []) + entry.get("secondary", []):
                timing = row.get("timing")
                if timing is None:
                    continue
                self.assertIn(
                    timing, TIMING_VOCABULARY,
                    f"{fam} row {row} has free-text timing {timing!r}",
                )
            for row in entry.get("invalidation", []):
                timing = row.get("timing")
                if timing is None:
                    continue
                self.assertIn(
                    timing, TIMING_VOCABULARY,
                    f"{fam} invalidation row has free-text timing {timing!r}",
                )
            for channel, timing in (entry.get("timing_by_channel") or {}).items():
                self.assertIn(
                    timing, TIMING_VOCABULARY,
                    f"{fam}.timing_by_channel[{channel}] = {timing!r} off-vocab",
                )


# ---------------------------------------------------------------------------
# 4. False-positive discipline
# ---------------------------------------------------------------------------

class TestFalsePositiveDiscipline(unittest.TestCase):
    """Every false_positives entry must name a distinguishing_signal —
    otherwise it's just a caveat, not an actionable false-positive flag."""

    def test_every_false_positive_has_distinguishing_signal(self):
        for fam, entry in FAMILY_VALIDATION_MATRIX.items():
            for row in entry.get("false_positives", []):
                self.assertIn(
                    "distinguishing_signal", row,
                    f"{fam} false_positives missing distinguishing_signal: {row}",
                )
                sig = row["distinguishing_signal"]
                self.assertTrue(
                    isinstance(sig, str) and len(sig.strip()) > 15,
                    f"{fam} distinguishing_signal too thin: {sig!r}",
                )


# ---------------------------------------------------------------------------
# 5. Composer shape
# ---------------------------------------------------------------------------

class TestComposerShape(unittest.TestCase):

    def test_unknown_family_degrades_gracefully(self):
        m = compute_validation_matrix("not_a_real_family")
        self.assertFalse(m["available"])
        self.assertEqual(m["primary"], [])
        self.assertEqual(m["timing_by_channel"], {})

    def test_none_family_is_not_available(self):
        m = compute_validation_matrix("none")
        self.assertFalse(m["available"])

    def test_known_family_is_available_and_shaped(self):
        m = compute_validation_matrix("supply_shock")
        self.assertTrue(m["available"])
        self.assertEqual(m["mechanism_family"], "supply_shock")
        for key in ("primary", "secondary", "false_positives",
                    "invalidation", "timing_by_channel"):
            self.assertIn(key, m)

    def test_mutation_is_safe(self):
        """Caller mutations must not leak into the registry."""
        m = compute_validation_matrix("supply_shock")
        m["primary"].append({"channel": "bogus"})
        fresh = compute_validation_matrix("supply_shock")
        for entry in fresh["primary"]:
            self.assertNotEqual(entry.get("channel"), "bogus")


# ---------------------------------------------------------------------------
# 6. Family specificity
# ---------------------------------------------------------------------------

class TestFamilySpecificity(unittest.TestCase):
    """Spot-check that the four families called out in the task produce
    distinctive matrices — not a uniform validation logic reused."""

    def test_supply_shock_confirms_via_commodities(self):
        m = compute_validation_matrix("supply_shock")
        channels = {e["channel"] for e in m["primary"]}
        self.assertIn("commodities", channels)
        self.assertIn("equities", channels)

    def test_policy_surprise_confirms_via_rates_and_fx(self):
        m = compute_validation_matrix("policy_surprise")
        channels = {e["channel"] for e in m["primary"]}
        self.assertIn("rates", channels)
        self.assertIn("fx", channels)

    def test_bank_stress_confirms_via_credit_and_equities(self):
        m = compute_validation_matrix("bank_stress")
        channels = {e["channel"] for e in m["primary"]}
        self.assertIn("credit", channels)
        self.assertIn("equities", channels)

    def test_ceasefire_confirms_via_vol_and_commodities(self):
        m = compute_validation_matrix("ceasefire_deescalation")
        channels = {e["channel"] for e in m["primary"]}
        self.assertIn("vol", channels)
        self.assertIn("commodities", channels)

    def test_different_families_have_distinct_primary_sets(self):
        """The four example families in the task must not all confirm
        through the same primary-channel set — that would prove the
        matrix is a thin wrapper around FAMILY_CHANNEL_PACKS."""
        sets = {}
        for fam in ("supply_shock", "policy_surprise", "bank_stress",
                    "ceasefire_deescalation"):
            m = compute_validation_matrix(fam)
            sets[fam] = frozenset(e["channel"] for e in m["primary"])
        # At least 3 distinct sets across the 4 families.
        self.assertGreaterEqual(
            len(set(sets.values())), 3,
            f"Primary-channel sets too similar: {sets}",
        )


# ---------------------------------------------------------------------------
# 7. Named-asset discipline
# ---------------------------------------------------------------------------

class TestNamedAssetDiscipline(unittest.TestCase):
    """Each primary/secondary row must carry a non-empty named_assets
    list, and every ticker in it must route via _ticker_channel back
    to the row's channel — otherwise the family-level read silently
    points at an asset on the wrong channel."""

    def test_every_primary_row_has_named_assets(self):
        for fam in FAMILY_IDS:
            if fam == "none":
                continue
            for row in FAMILY_VALIDATION_MATRIX[fam]["primary"]:
                self.assertIn(
                    "named_assets", row,
                    f"{fam} primary row missing named_assets: {row}",
                )
                self.assertTrue(
                    isinstance(row["named_assets"], list) and row["named_assets"],
                    f"{fam} primary row named_assets must be a non-empty list",
                )

    def test_every_secondary_row_has_named_assets(self):
        for fam in FAMILY_IDS:
            if fam == "none":
                continue
            for row in FAMILY_VALIDATION_MATRIX[fam]["secondary"]:
                self.assertIn(
                    "named_assets", row,
                    f"{fam} secondary row missing named_assets: {row}",
                )
                self.assertTrue(
                    isinstance(row["named_assets"], list) and row["named_assets"],
                    f"{fam} secondary row named_assets must be a non-empty list",
                )

    def test_named_assets_route_to_row_channel(self):
        """Every ticker in a row's named_assets must map via
        _ticker_channel back to the row's channel — catches
        authoring drift (e.g. a vol ticker in a credit row)."""
        for fam in FAMILY_IDS:
            if fam == "none":
                continue
            for section in ("primary", "secondary"):
                for row in FAMILY_VALIDATION_MATRIX[fam][section]:
                    channel = row.get("channel")
                    for sym in row.get("named_assets") or []:
                        routed = _ticker_channel(sym)
                        self.assertEqual(
                            routed, channel,
                            f"{fam} {section} channel={channel!r} but "
                            f"named_asset {sym!r} routes to {routed!r}",
                        )


class TestFalsePositiveBasketDiscipline(unittest.TestCase):
    """false_positives entries must lift the prose contrast pair into
    structured primary_basket / false_basket lists so the scorer can
    consume them without text parsing."""

    def test_every_false_positive_has_basket_pair(self):
        for fam in FAMILY_IDS:
            if fam == "none":
                continue
            for row in FAMILY_VALIDATION_MATRIX[fam].get("false_positives", []):
                self.assertIn(
                    "primary_basket", row,
                    f"{fam} false_positives missing primary_basket: {row}",
                )
                self.assertIn(
                    "false_basket", row,
                    f"{fam} false_positives missing false_basket: {row}",
                )
                self.assertTrue(
                    isinstance(row["primary_basket"], list) and row["primary_basket"],
                    f"{fam} false_positives primary_basket empty: {row}",
                )
                self.assertTrue(
                    isinstance(row["false_basket"], list) and row["false_basket"],
                    f"{fam} false_positives false_basket empty: {row}",
                )


# ---------------------------------------------------------------------------
# 8. get_validation_matrix mutation safety extends to nested lists
# ---------------------------------------------------------------------------

class TestNestedListMutationSafety(unittest.TestCase):
    """Mutating the named_assets list on a returned row must not leak
    back into the registry."""

    def test_mutating_named_assets_does_not_leak(self):
        m = get_validation_matrix("supply_shock")
        m["primary"][0]["named_assets"].append("SPY")
        fresh = get_validation_matrix("supply_shock")
        self.assertNotIn("SPY", fresh["primary"][0]["named_assets"])


# ---------------------------------------------------------------------------
# 7. Mechanism subtypes — optional tighter overlay on the family matrix
# ---------------------------------------------------------------------------

class TestMechanismSubtypeRegistry(unittest.TestCase):
    """Subtype keys must be disjoint from family ids and stay scoped
    to a single family — no subtype lives under two families."""

    def test_subtype_keys_disjoint_from_family_ids(self):
        family_ids = set(FAMILY_IDS)
        for fam, subtypes in FAMILY_SUBTYPES.items():
            for subtype_id in subtypes:
                self.assertNotIn(
                    subtype_id, family_ids,
                    f"subtype {subtype_id!r} collides with a family id",
                )

    def test_each_subtype_has_keywords_or_overrides(self):
        """A registered subtype MUST carry either keywords (so the
        inference pass can pick it) or primary_overrides (so it
        actually tightens the matrix) — typically both."""
        for fam, subtypes in FAMILY_SUBTYPES.items():
            for subtype_id, meta in subtypes.items():
                self.assertTrue(
                    meta.get("keywords") or meta.get("primary_overrides"),
                    f"subtype {subtype_id!r} on {fam!r} is empty",
                )


class TestSubtypeInference(unittest.TestCase):
    """``infer_mechanism_subtype`` is keyword-based, deterministic,
    and falls back to None when the family has no subtypes or no
    keywords match."""

    def test_returns_subtype_when_keywords_match(self):
        result = infer_mechanism_subtype(
            "tariff",
            "Section 301 tariff on Chinese imports widens trade-balance drag",
            "US Trade Representative announces 25% Section 301 tariff",
        )
        self.assertEqual(result, "import_tariff_china")

    def test_returns_none_when_no_keywords_match(self):
        result = infer_mechanism_subtype(
            "tariff",
            "EU announces dairy duties on Mediterranean producers",
            "Council vote on dairy quota",
        )
        self.assertIsNone(result)

    def test_returns_none_for_family_without_subtypes(self):
        result = infer_mechanism_subtype(
            "regulation",
            "FTC blocks pharma merger on antitrust grounds",
            "DOJ files complaint",
        )
        self.assertIsNone(result)

    def test_returns_none_for_unknown_family(self):
        result = infer_mechanism_subtype(
            "made_up_family",
            "Something happened",
            "Another thing",
        )
        self.assertIsNone(result)

    def test_returns_none_for_none_or_empty_family(self):
        for family in (None, "", "  ", "none"):
            self.assertIsNone(
                infer_mechanism_subtype(family, "any text", "any text"),
                f"family={family!r} should yield None",
            )

    def test_returns_none_for_empty_prose(self):
        self.assertIsNone(infer_mechanism_subtype("tariff", "", ""))
        self.assertIsNone(infer_mechanism_subtype("tariff", None, None))

    def test_match_is_case_insensitive(self):
        result = infer_mechanism_subtype(
            "supply_shock",
            "OPEC CUT ANNOUNCED — production lowered by 1mbd",
            "Saudi Arabia cuts liftings",
        )
        self.assertEqual(result, "oil_supply_shock")


class TestSubtypeMatrixOverlay(unittest.TestCase):
    """``get_validation_matrix`` accepts an optional subtype that
    tightens the family-level matrix without changing the response
    shape."""

    def test_no_subtype_preserves_family_matrix(self):
        """Backward compat: callers passing only ``family`` get the
        same matrix as before."""
        baseline = get_validation_matrix("tariff")
        with_none = get_validation_matrix("tariff", None)
        self.assertEqual(baseline, with_none)

    def test_unknown_subtype_falls_back_to_family(self):
        baseline = get_validation_matrix("tariff")
        unknown = get_validation_matrix("tariff", "made_up_subtype")
        self.assertEqual(baseline, unknown)

    def test_subtype_tightens_primary_channel(self):
        """A known subtype's ``primary_overrides`` replace the
        matching channel row from the family matrix — the named_assets
        from the subtype win, NOT the family default."""
        tightened = get_validation_matrix("tariff", "import_tariff_china")
        equity_rows = [
            r for r in tightened["primary"]
            if r.get("channel") == "equities"
        ]
        self.assertEqual(len(equity_rows), 1)
        self.assertEqual(
            equity_rows[0]["named_assets"], ["KWEB", "FXI", "MCHI"],
        )

    def test_subtype_response_shape_unchanged(self):
        """The five top-level matrix keys must be present whether or
        not a subtype is used."""
        tightened = get_validation_matrix("tariff", "import_tariff_china")
        for key in (
            "primary", "secondary", "false_positives",
            "invalidation", "timing_by_channel",
        ):
            self.assertIn(key, tightened)

    def test_oil_subtype_tightens_named_assets(self):
        tightened = get_validation_matrix("supply_shock", "oil_supply_shock")
        commodity_rows = [
            r for r in tightened["primary"]
            if r.get("channel") == "commodities"
        ]
        self.assertEqual(len(commodity_rows), 1)
        # Oil-specific named_assets win over the broad supply_shock default.
        self.assertEqual(
            commodity_rows[0]["named_assets"], ["USO", "XLE"],
        )

    def test_subtype_does_not_pollute_family_registry(self):
        """Mutating the subtype-tightened matrix must NOT leak back
        into ``FAMILY_VALIDATION_MATRIX`` or ``FAMILY_SUBTYPES``."""
        tightened = get_validation_matrix("tariff", "import_tariff_china")
        tightened["primary"][0]["named_assets"].append("SPY")
        fresh = get_validation_matrix("tariff", "import_tariff_china")
        self.assertNotIn("SPY", fresh["primary"][0]["named_assets"])
        # Family-level matrix is untouched too.
        family = get_validation_matrix("tariff")
        for row in family["primary"]:
            if row.get("channel") == "equities":
                self.assertNotIn("SPY", row["named_assets"])


if __name__ == "__main__":
    unittest.main()
