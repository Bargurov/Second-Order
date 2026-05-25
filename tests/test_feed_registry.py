"""
tests/test_feed_registry.py

Unit tests for feed_registry.py — config loading, filtering logic,
and fallback behavior.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")
import feed_registry
from feed_registry import (
    get_active_feeds,
    _load_config,
    _feed_passes,
    FEED_METADATA,
    ALL_SECTORS,
    ALL_REGIONS,
)

# Minimal feed list used across tests to avoid coupling to DEFAULT_FEEDS size
_SAMPLE_FEEDS = [
    {"name": "Reuters World",     "url": "http://reuters.example"},
    {"name": "OilPrice.com",      "url": "http://oilprice.example"},
    {"name": "Defense News",      "url": "http://defensenews.example"},
    {"name": "OFAC Sanctions",    "url": "http://ofac.example"},
    {"name": "Nikkei Asia",       "url": "http://nikkei.example"},
    {"name": "MarketWatch",       "url": "http://marketwatch.example"},
    {"name": "Unknown Feed",      "url": "http://unknown.example"},
]


def _write_config(cfg: dict) -> str:
    """Write cfg to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(cfg, tmp)
    tmp.close()
    return tmp.name


class TestLoadConfig(unittest.TestCase):

    def test_returns_none_when_file_absent(self):
        self.assertIsNone(_load_config("/nonexistent/feed_config.json"))

    def test_loads_valid_file(self):
        path = _write_config({"active_sectors": ["macro"]})
        try:
            cfg = _load_config(path)
            self.assertEqual(cfg, {"active_sectors": ["macro"]})
        finally:
            os.unlink(path)

    def test_returns_none_on_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json {{")
            path = f.name
        try:
            self.assertIsNone(_load_config(path))
        finally:
            os.unlink(path)


class TestFeedPasses(unittest.TestCase):

    def test_no_filters_passes_everything(self):
        self.assertTrue(_feed_passes("Reuters World", None, None))
        self.assertTrue(_feed_passes("OilPrice.com", None, None))

    def test_unknown_feed_passes_when_filtered(self):
        active_sectors = frozenset({"macro"})
        self.assertTrue(_feed_passes("Unknown Feed", active_sectors, None))

    def test_sector_filter_includes_matching_feed(self):
        self.assertTrue(_feed_passes("OilPrice.com", frozenset({"energy"}), None))

    def test_sector_filter_excludes_non_matching_feed(self):
        self.assertFalse(_feed_passes("OilPrice.com", frozenset({"macro"}), None))

    def test_region_filter_includes_matching_feed(self):
        self.assertTrue(_feed_passes("Nikkei Asia", None, frozenset({"asia"})))

    def test_region_filter_excludes_non_matching_feed(self):
        self.assertFalse(_feed_passes("Nikkei Asia", None, frozenset({"europe"})))

    def test_both_filters_must_both_pass(self):
        # Reuters World: macro, global — passes macro+global
        self.assertTrue(_feed_passes("Reuters World", frozenset({"macro"}), frozenset({"global"})))
        # Reuters World: macro, global — fails when region is asia
        self.assertFalse(_feed_passes("Reuters World", frozenset({"macro"}), frozenset({"asia"})))

    def test_multi_sector_feed_matches_any(self):
        # WSJ World News has sectors [macro, financials]
        self.assertTrue(_feed_passes("WSJ World News", frozenset({"financials"}), None))
        self.assertTrue(_feed_passes("WSJ World News", frozenset({"macro"}), None))
        self.assertFalse(_feed_passes("WSJ World News", frozenset({"energy"}), None))


class TestGetActiveFeeds(unittest.TestCase):

    def test_no_config_returns_all_feeds(self):
        result = get_active_feeds(feeds=_SAMPLE_FEEDS, config_path="/nonexistent.json")
        self.assertEqual(result, _SAMPLE_FEEDS)

    def test_sector_filter_energy_only(self):
        path = _write_config({"active_sectors": ["energy"]})
        try:
            result = get_active_feeds(feeds=_SAMPLE_FEEDS, config_path=path)
            names = [f["name"] for f in result]
            self.assertIn("OilPrice.com", names)
            self.assertNotIn("Reuters World", names)
            self.assertNotIn("Defense News", names)
            # Unknown Feed passes through (unknown = include by default)
            self.assertIn("Unknown Feed", names)
        finally:
            os.unlink(path)

    def test_region_filter_asia_only(self):
        path = _write_config({"active_regions": ["asia"]})
        try:
            result = get_active_feeds(feeds=_SAMPLE_FEEDS, config_path=path)
            names = [f["name"] for f in result]
            self.assertIn("Nikkei Asia", names)
            self.assertNotIn("Reuters World", names)
            self.assertNotIn("MarketWatch", names)
        finally:
            os.unlink(path)

    def test_sector_and_region_both_required(self):
        # macro + americas → Reuters World (global, not americas) excluded
        path = _write_config({"active_sectors": ["macro"], "active_regions": ["americas"]})
        try:
            result = get_active_feeds(feeds=_SAMPLE_FEEDS, config_path=path)
            names = [f["name"] for f in result]
            self.assertNotIn("Reuters World", names)   # macro but global, not americas
            self.assertNotIn("OilPrice.com", names)    # energy, not macro
        finally:
            os.unlink(path)

    def test_empty_result_falls_back_to_all(self):
        # Use a feed list with only known feeds so we can produce a true empty result.
        # No known feeds have both sector=defense AND region=middle_east.
        known_only = [
            {"name": "Defense News", "url": "http://defensenews.example"},
            {"name": "Reuters World", "url": "http://reuters.example"},
        ]
        path = _write_config({"active_sectors": ["defense"], "active_regions": ["middle_east"]})
        try:
            result = get_active_feeds(feeds=known_only, config_path=path)
            # Falls back to full list (both feeds)
            self.assertEqual(result, known_only)
        finally:
            os.unlink(path)

    def test_invalid_config_returns_all(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{bad json")
            path = f.name
        try:
            result = get_active_feeds(feeds=_SAMPLE_FEEDS, config_path=path)
            self.assertEqual(result, _SAMPLE_FEEDS)
        finally:
            os.unlink(path)

    def test_unknown_sector_in_config_does_not_crash(self):
        path = _write_config({"active_sectors": ["macro", "foobar_unknown"]})
        try:
            result = get_active_feeds(feeds=_SAMPLE_FEEDS, config_path=path)
            # At minimum, macro feeds still come through
            names = [f["name"] for f in result]
            self.assertIn("Reuters World", names)
        finally:
            os.unlink(path)

    def test_uses_default_feeds_when_feeds_param_is_none(self):
        # No config → should return DEFAULT_FEEDS
        result = get_active_feeds(feeds=None, config_path="/nonexistent.json")
        from news_fetch import DEFAULT_FEEDS
        self.assertEqual(result, DEFAULT_FEEDS)


class TestMetadataCoverage(unittest.TestCase):
    """All DEFAULT_FEEDS should be present in FEED_METADATA (or gracefully absent)."""

    def test_all_metadata_sectors_are_valid(self):
        for name, meta in FEED_METADATA.items():
            for s in meta["sectors"]:
                self.assertIn(s, ALL_SECTORS, f"{name} has unknown sector '{s}'")

    def test_all_metadata_regions_are_valid(self):
        for name, meta in FEED_METADATA.items():
            for r in meta["regions"]:
                self.assertIn(r, ALL_REGIONS, f"{name} has unknown region '{r}'")

    def test_every_default_feed_has_metadata(self):
        from news_fetch import DEFAULT_FEEDS
        missing = [f["name"] for f in DEFAULT_FEEDS if f["name"] not in FEED_METADATA]
        self.assertEqual(missing, [], f"Feeds without metadata: {missing}")


class TestNewFeedCoverage(unittest.TestCase):
    """Pin that the healthcare and agriculture feeds are correctly wired."""

    def test_fda_feed_in_default_feeds(self) -> None:
        from news_fetch import DEFAULT_FEEDS
        names = [f["name"] for f in DEFAULT_FEEDS]
        self.assertIn("FDA Press Releases", names)

    def test_usda_feed_in_default_feeds(self) -> None:
        from news_fetch import DEFAULT_FEEDS
        names = [f["name"] for f in DEFAULT_FEEDS]
        self.assertIn("USDA News", names)

    def test_fda_feed_has_metadata(self) -> None:
        self.assertIn("FDA Press Releases", FEED_METADATA)
        meta = FEED_METADATA["FDA Press Releases"]
        self.assertIn("healthcare", meta["sectors"])
        self.assertIn("americas", meta["regions"])

    def test_usda_feed_has_metadata(self) -> None:
        self.assertIn("USDA News", FEED_METADATA)
        meta = FEED_METADATA["USDA News"]
        self.assertIn("agriculture", meta["sectors"])
        self.assertIn("americas", meta["regions"])

    def test_healthcare_sector_recognized(self) -> None:
        self.assertIn("healthcare", ALL_SECTORS)

    def test_agriculture_sector_recognized(self) -> None:
        self.assertIn("agriculture", ALL_SECTORS)

    def test_fda_passes_healthcare_sector_filter(self) -> None:
        self.assertTrue(
            _feed_passes("FDA Press Releases", frozenset({"healthcare"}), None))

    def test_usda_passes_agriculture_sector_filter(self) -> None:
        self.assertTrue(
            _feed_passes("USDA News", frozenset({"agriculture"}), None))

    def test_fda_excluded_by_energy_sector_filter(self) -> None:
        self.assertFalse(
            _feed_passes("FDA Press Releases", frozenset({"energy"}), None))

    def test_no_duplicate_feed_names(self) -> None:
        from news_fetch import DEFAULT_FEEDS
        names = [f["name"] for f in DEFAULT_FEEDS]
        self.assertEqual(len(names), len(set(names)),
                         f"Duplicate names: {[n for n in names if names.count(n) > 1]}")

    def test_no_duplicate_feed_urls(self) -> None:
        from news_fetch import DEFAULT_FEEDS
        urls = [f["url"] for f in DEFAULT_FEEDS]
        self.assertEqual(len(urls), len(set(urls)),
                         f"Duplicate URLs: {[u for u in urls if urls.count(u) > 1]}")


if __name__ == "__main__":
    unittest.main()
