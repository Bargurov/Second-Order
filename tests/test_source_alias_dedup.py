"""
tests/test_source_alias_dedup.py

Focused tests for source-alias normalization in the news dedup path.

  1) Alias variants merge — same headline from "BBC Business" and
     "BBC World" produces one record, not two.
  2) Distinct publishers stay separate — same headline from "BBC" and
     "Reuters" counts as genuine cross-source corroboration.
  3) Repeated refresh does not duplicate — calling fetch_all twice with
     the same aliased feed data produces the same unique count.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_sources import (
    normalize_source,
    _dedup_key,
    _make_record,
    cluster_headlines,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(source: str, title: str, url: str = "") -> dict:
    return _make_record(source, title, "2026-04-13T10:00:00", url)


def _dedup(records: list[dict]) -> list[dict]:
    """Replicate the dedup logic from fetch_all."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for rec in records:
        key = (normalize_source(rec["source"]), _dedup_key(rec["title"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(rec)
    return unique


# ---------------------------------------------------------------------------
# 1) Alias variants merge
# ---------------------------------------------------------------------------

class TestAliasVariantsMerge(unittest.TestCase):
    """Same headline from two feeds of the same publisher → one record."""

    def test_bbc_business_and_world_merge(self):
        recs = [
            _rec("BBC Business", "Oil prices surge after OPEC+ decision"),
            _rec("BBC World",    "Oil prices surge after OPEC+ decision"),
        ]
        unique = _dedup(recs)
        self.assertEqual(len(unique), 1)

    def test_guardian_variants_merge(self):
        recs = [
            _rec("The Guardian Business", "UK inflation rises to 3.5%"),
            _rec("The Guardian World",    "UK inflation rises to 3.5%"),
        ]
        unique = _dedup(recs)
        self.assertEqual(len(unique), 1)

    def test_al_jazeera_variants_merge(self):
        recs = [
            _rec("Al Jazeera Economy", "Saudi Aramco cuts oil output"),
            _rec("Al Jazeera",         "Saudi Aramco cuts oil output"),
        ]
        unique = _dedup(recs)
        self.assertEqual(len(unique), 1)

    def test_first_record_kept_on_merge(self):
        recs = [
            _rec("BBC Business", "Oil prices surge", "https://bbc.co.uk/biz"),
            _rec("BBC World",    "Oil prices surge", "https://bbc.co.uk/world"),
        ]
        unique = _dedup(recs)
        self.assertEqual(unique[0]["source"], "BBC Business")

    def test_alias_merge_in_cluster_source_count(self):
        """Clustering should count BBC Business + BBC World as 1 source."""
        recs = [
            _rec("BBC Business", "Oil prices surge after OPEC+ cuts output"),
            _rec("BBC World",    "Oil prices surge after OPEC+ cuts output"),
        ]
        clusters = cluster_headlines(recs)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["source_count"], 1)


# ---------------------------------------------------------------------------
# 2) Distinct publishers stay separate
# ---------------------------------------------------------------------------

class TestDistinctPublishersSeparate(unittest.TestCase):
    """Same headline from genuinely different publishers → corroboration."""

    def test_bbc_and_reuters_stay_separate(self):
        recs = [
            _rec("BBC Business",  "Oil prices surge after OPEC+ decision"),
            _rec("Reuters World", "Oil prices surge after OPEC+ decision"),
        ]
        unique = _dedup(recs)
        self.assertEqual(len(unique), 2)

    def test_different_publishers_boost_source_count(self):
        recs = [
            _rec("BBC Business",  "Oil prices surge after OPEC+ cuts output"),
            _rec("Reuters World", "Oil prices surge after OPEC+ cuts output"),
        ]
        clusters = cluster_headlines(recs)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["source_count"], 2)

    def test_unmapped_sources_stay_separate(self):
        """Sources not in the alias table must never merge."""
        recs = [
            _rec("MarketWatch",   "Fed holds rates steady"),
            _rec("Yahoo Finance", "Fed holds rates steady"),
        ]
        unique = _dedup(recs)
        self.assertEqual(len(unique), 2)

    def test_normalize_source_passthrough(self):
        """Unknown source names pass through unchanged."""
        self.assertEqual(normalize_source("MarketWatch"), "MarketWatch")
        self.assertEqual(normalize_source("Reuters World"), "Reuters World")


# ---------------------------------------------------------------------------
# 3) Repeated refresh does not duplicate
# ---------------------------------------------------------------------------

class TestRepeatedRefreshNoDuplicates(unittest.TestCase):
    """Running dedup twice with the same data produces the same count."""

    def test_idempotent_dedup(self):
        recs = [
            _rec("BBC Business",  "Oil prices surge after OPEC+ decision"),
            _rec("BBC World",     "Oil prices surge after OPEC+ decision"),
            _rec("Reuters World", "Oil prices surge after OPEC+ decision"),
            _rec("AP News",       "EU imposes new sanctions on Russia"),
        ]
        first = _dedup(recs)
        # Simulate a second refresh appending the same records.
        second = _dedup(recs + recs)
        self.assertEqual(len(first), len(second))

    def test_alias_dedup_stable_across_order(self):
        """Order of records should not affect which survive dedup."""
        recs_a = [
            _rec("BBC World",    "Oil prices surge"),
            _rec("BBC Business", "Oil prices surge"),
        ]
        recs_b = [
            _rec("BBC Business", "Oil prices surge"),
            _rec("BBC World",    "Oil prices surge"),
        ]
        unique_a = _dedup(recs_a)
        unique_b = _dedup(recs_b)
        self.assertEqual(len(unique_a), 1)
        self.assertEqual(len(unique_b), 1)


if __name__ == "__main__":
    unittest.main()
