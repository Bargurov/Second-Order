"""Tests for coverage_registry — shape, enum pins, drift-prevention.

The drift-prevention tests are the point of this file: they make
silent coverage changes (adding a feed to FEED_METADATA without
updating the registry, dropping a market from LIQUID_MARKETS, etc.)
fail CI instead of passing review unnoticed.
"""

from __future__ import annotations

import copy
import unittest

from coverage_registry import (
    ASSET_CLASSES,
    COVERAGE_REGISTRY,
    COVERAGE_REGISTRY_VERSION,
    COVERAGE_TIERS,
    FEED_CATEGORIES,
    iter_feed_coverage,
    iter_market_coverage,
    load_coverage_registry,
    resolve_feed_group,
    resolve_market_group,
    validate_coverage_registry,
)


# ---------------------------------------------------------------------------
# Enum + version pins — changes to these must be deliberate.
# ---------------------------------------------------------------------------

class TestPins(unittest.TestCase):
    def test_version_pinned(self):
        self.assertEqual(COVERAGE_REGISTRY_VERSION, "2026.04.01")
        self.assertEqual(COVERAGE_REGISTRY["version"], COVERAGE_REGISTRY_VERSION)

    def test_feed_categories_pinned(self):
        self.assertEqual(FEED_CATEGORIES, frozenset({
            "macro_wire", "financial_media", "policy",
            "commodity", "trade", "regional_macro", "geopolitical",
        }))

    def test_coverage_tiers_pinned(self):
        self.assertEqual(COVERAGE_TIERS, ("high", "medium", "low"))

    def test_asset_classes_pinned(self):
        self.assertEqual(
            ASSET_CLASSES,
            frozenset({"equity_index", "commodity", "currency", "rate"}),
        )


# ---------------------------------------------------------------------------
# load + validate happy path
# ---------------------------------------------------------------------------

class TestLoad(unittest.TestCase):
    def test_load_returns_validated_copy(self):
        reg = load_coverage_registry()
        self.assertEqual(reg["version"], COVERAGE_REGISTRY_VERSION)
        self.assertIn("feed_groups", reg)
        self.assertIn("market_groups", reg)

    def test_load_returns_deep_copy(self):
        a = load_coverage_registry()
        b = load_coverage_registry()
        a["feed_groups"][0]["members"].append("MUTATED")
        self.assertNotIn("MUTATED", b["feed_groups"][0]["members"])
        self.assertNotIn(
            "MUTATED",
            COVERAGE_REGISTRY["feed_groups"][0]["members"],
        )

    def test_live_registry_passes_validation(self):
        # Must not raise.
        validate_coverage_registry(copy.deepcopy(COVERAGE_REGISTRY))


# ---------------------------------------------------------------------------
# Validation — every negative case must surface as a clear ValueError.
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def _base(self) -> dict:
        return copy.deepcopy(COVERAGE_REGISTRY)

    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            validate_coverage_registry([])

    def test_missing_top_level_keys(self):
        r = self._base()
        del r["feed_groups"]
        with self.assertRaises(ValueError) as cm:
            validate_coverage_registry(r)
        self.assertIn("feed_groups", str(cm.exception))

    def test_extra_top_level_keys(self):
        r = self._base()
        r["unexpected"] = True
        with self.assertRaises(ValueError):
            validate_coverage_registry(r)

    def test_bad_iso_date(self):
        r = self._base()
        r["updated_at"] = "2026/04/19"
        with self.assertRaises(ValueError):
            validate_coverage_registry(r)

    def test_feed_group_missing_keys(self):
        r = self._base()
        del r["feed_groups"][0]["owner"]
        with self.assertRaises(ValueError):
            validate_coverage_registry(r)

    def test_feed_group_unknown_key(self):
        r = self._base()
        r["feed_groups"][0]["owner_email"] = "x@example.com"
        with self.assertRaises(ValueError):
            validate_coverage_registry(r)

    def test_feed_group_bad_category(self):
        r = self._base()
        r["feed_groups"][0]["category"] = "not_a_category"
        with self.assertRaises(ValueError) as cm:
            validate_coverage_registry(r)
        self.assertIn("category", str(cm.exception))

    def test_feed_group_bad_tier(self):
        r = self._base()
        r["feed_groups"][0]["tier"] = "platinum"
        with self.assertRaises(ValueError) as cm:
            validate_coverage_registry(r)
        self.assertIn("tier", str(cm.exception))

    def test_market_group_bad_asset_class(self):
        r = self._base()
        r["market_groups"][0]["asset_class"] = "crypto"
        with self.assertRaises(ValueError):
            validate_coverage_registry(r)

    def test_empty_members_rejected(self):
        r = self._base()
        r["feed_groups"][0]["members"] = []
        with self.assertRaises(ValueError):
            validate_coverage_registry(r)

    def test_duplicate_member_across_groups(self):
        r = self._base()
        # Force a cross-group collision.
        r["feed_groups"][0]["members"].append(r["feed_groups"][1]["members"][0])
        with self.assertRaises(ValueError) as cm:
            validate_coverage_registry(r)
        self.assertIn("more than one group", str(cm.exception))

    def test_duplicate_member_within_group(self):
        r = self._base()
        r["feed_groups"][0]["members"].append(r["feed_groups"][0]["members"][0])
        with self.assertRaises(ValueError) as cm:
            validate_coverage_registry(r)
        self.assertIn("duplicate", str(cm.exception))

    def test_duplicate_feed_group_id(self):
        r = self._base()
        r["feed_groups"].append({
            **r["feed_groups"][0],
            "members": ["Unique feed A"],
        })
        with self.assertRaises(ValueError) as cm:
            validate_coverage_registry(r)
        self.assertIn("duplicate feed_group id", str(cm.exception))

    def test_duplicate_market_group_id(self):
        r = self._base()
        r["market_groups"].append({
            **r["market_groups"][0],
            "members": ["UNIQUE"],
        })
        with self.assertRaises(ValueError) as cm:
            validate_coverage_registry(r)
        self.assertIn("duplicate market_group id", str(cm.exception))

    def test_non_string_member_rejected(self):
        r = self._base()
        r["feed_groups"][0]["members"][0] = 42
        with self.assertRaises(ValueError):
            validate_coverage_registry(r)


# ---------------------------------------------------------------------------
# Flat-iteration contract
# ---------------------------------------------------------------------------

class TestIteration(unittest.TestCase):
    def test_iter_feed_coverage_shape(self):
        rows = list(iter_feed_coverage())
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual(
                set(row),
                {"feed", "group_id", "owner", "tier", "category"},
            )

    def test_iter_market_coverage_shape(self):
        rows = list(iter_market_coverage())
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual(
                set(row),
                {"market", "group_id", "owner", "asset_class"},
            )

    def test_resolve_feed_group(self):
        # Pick a known feed from the registry.
        sample = COVERAGE_REGISTRY["feed_groups"][0]["members"][0]
        self.assertEqual(
            resolve_feed_group(sample),
            COVERAGE_REGISTRY["feed_groups"][0]["id"],
        )

    def test_resolve_feed_group_unknown(self):
        self.assertIsNone(resolve_feed_group("Not a real feed"))

    def test_resolve_market_group_case_insensitive(self):
        sample = COVERAGE_REGISTRY["market_groups"][0]["members"][0]
        self.assertEqual(
            resolve_market_group(sample.lower()),
            COVERAGE_REGISTRY["market_groups"][0]["id"],
        )

    def test_resolve_market_group_unknown(self):
        self.assertIsNone(resolve_market_group("DOGE"))


# ---------------------------------------------------------------------------
# Drift prevention — the whole point of this registry.
# ---------------------------------------------------------------------------

class TestFeedDrift(unittest.TestCase):
    def test_registry_feeds_all_exist_in_feed_metadata(self):
        from feed_registry import FEED_METADATA
        registry_feeds = {row["feed"] for row in iter_feed_coverage()}
        missing = registry_feeds - set(FEED_METADATA)
        self.assertFalse(
            missing,
            msg=(
                f"coverage_registry references feeds that are not in "
                f"FEED_METADATA: {sorted(missing)}"
            ),
        )

    def test_feed_metadata_fully_covered_by_registry(self):
        from feed_registry import FEED_METADATA
        registry_feeds = {row["feed"] for row in iter_feed_coverage()}
        missing = set(FEED_METADATA) - registry_feeds
        self.assertFalse(
            missing,
            msg=(
                f"FEED_METADATA has feeds missing from coverage_registry "
                f"(add them to a feed_group): {sorted(missing)}"
            ),
        )

    def test_every_feed_has_one_owner(self):
        counts: dict[str, int] = {}
        for row in iter_feed_coverage():
            counts[row["feed"]] = counts.get(row["feed"], 0) + 1
        multi = {k: v for k, v in counts.items() if v > 1}
        self.assertFalse(
            multi,
            msg=f"feeds assigned to multiple groups: {multi}",
        )


class TestMarketDrift(unittest.TestCase):
    def test_registry_markets_all_exist_in_liquid_markets(self):
        from market_universe import LIQUID_MARKETS
        registry_markets = {row["market"] for row in iter_market_coverage()}
        missing = registry_markets - set(LIQUID_MARKETS)
        self.assertFalse(
            missing,
            msg=(
                f"coverage_registry references markets not in "
                f"LIQUID_MARKETS: {sorted(missing)}"
            ),
        )

    def test_liquid_markets_fully_covered_by_registry(self):
        from market_universe import LIQUID_MARKETS
        registry_markets = {row["market"] for row in iter_market_coverage()}
        missing = set(LIQUID_MARKETS) - registry_markets
        self.assertFalse(
            missing,
            msg=(
                f"LIQUID_MARKETS has entries missing from coverage_registry "
                f"(add them to a market_group): {sorted(missing)}"
            ),
        )

    def test_registry_asset_class_matches_market_info(self):
        from market_universe import LIQUID_MARKET_INFO
        for row in iter_market_coverage():
            info = LIQUID_MARKET_INFO.get(row["market"])
            self.assertIsNotNone(
                info,
                msg=f"{row['market']} missing from LIQUID_MARKET_INFO",
            )
            self.assertEqual(
                info["asset_class"],
                row["asset_class"],
                msg=(
                    f"asset_class drift for {row['market']}: "
                    f"registry={row['asset_class']!r} vs "
                    f"market_universe={info['asset_class']!r}"
                ),
            )

    def test_every_market_has_one_owner(self):
        counts: dict[str, int] = {}
        for row in iter_market_coverage():
            counts[row["market"]] = counts.get(row["market"], 0) + 1
        multi = {k: v for k, v in counts.items() if v > 1}
        self.assertFalse(
            multi,
            msg=f"markets assigned to multiple groups: {multi}",
        )


# ---------------------------------------------------------------------------
# Coverage-completeness sanity — if these numbers change, the reviewer
# sees a test diff and has to acknowledge the shift.
# ---------------------------------------------------------------------------

class TestCoverageSize(unittest.TestCase):
    def test_feed_group_count(self):
        # +sector_regulators (FDA / USDA primary sources), added 2026-05-26.
        self.assertEqual(len(COVERAGE_REGISTRY["feed_groups"]), 10)

    def test_market_group_count(self):
        self.assertEqual(len(COVERAGE_REGISTRY["market_groups"]), 4)

    def test_total_feed_coverage(self):
        total = sum(
            len(g["members"]) for g in COVERAGE_REGISTRY["feed_groups"]
        )
        # 35 + FDA Press Releases + USDA News = 37.
        self.assertEqual(total, 37)

    def test_total_market_coverage(self):
        total = sum(
            len(g["members"]) for g in COVERAGE_REGISTRY["market_groups"]
        )
        # 8-market product contract: 3 equity index + 2 commodity +
        # 1 USD index (FX cross aliases resolvable but not counted in
        # the default set) + 2 rate = 8.
        self.assertEqual(total, 8)


if __name__ == "__main__":
    unittest.main()
