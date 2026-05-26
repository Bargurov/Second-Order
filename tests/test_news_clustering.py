"""
tests/test_news_clustering.py

Regression tests for the generic-document title guard added to
``news_clustering.cluster_headlines`` and mirrored in
``news_cluster_store._can_merge`` / ``_find_merge_target``.

Covers:
  - ``_is_generic_document_title`` recognises the documented patterns
    (TRADE SUMMARY, Doing Business, Connecting to Compete, World
    Development Report, Annual Report, Working Paper, Open Knowledge,
    DataBank, "- World Bank Group" / "- World Bank Open Data" suffixes).
  - Block at cluster_headlines: a generic-doc title never bridges into
    a live-news title.
  - Block at cluster_headlines: two unrelated docs sharing only
    boilerplate do NOT merge.
  - Allow at cluster_headlines: two near-duplicate generic-doc titles
    still merge (high-cosine escape).
  - Allow at cluster_headlines: two live-news headlines on the same
    event still merge (regression guard against over-blocking).
  - Block at news_cluster_store._can_merge for the cross-refresh path.
"""

import sys

sys.path.insert(0, ".")

import pytest

from news_clustering import (
    _is_generic_document_title,
    _GENERIC_DOC_NEAR_DUP_THRESHOLD,
    cluster_headlines,
)


# ---------------------------------------------------------------------------
# _is_generic_document_title — positive cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "TRADE SUMMARY The U.S. goods trade deficit with India was $18.2 billion in 2012",
    "Announcement of Doing Business 2008 on September 26, 2007 : Large Emerging Markets",
    "Vietnam development report 2012 : market economy for a middle-income Vietnam",
    "Connecting to Compete 2018 : Trade Logistics in the Global Economy",
    "World Development Report 2026",
    "Apple Annual Report 2025",
    "Policy Research Working Paper 12345",
    "Working Paper on emerging-market debt sustainability",
    "Open Knowledge Repository - World Bank Group",
    "DataBank reference notes",
    "Zimbabwe | World Bank Group",
    "Gender Data Portal - World Bank Group",
    "Europe & Central Asia Italy - World Bank Open Data",
])
def test_is_generic_doc_positive(title):
    assert _is_generic_document_title(title), title


# ---------------------------------------------------------------------------
# _is_generic_document_title — negative cases (live news must not match)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Trump announces 25% tariff on EU steel imports",
    "India, US discuss Middle East, trade as Rubio cites progress on Iran conflict",
    "Oil prices surge after OPEC+ production cut",
    "Fed leaves rates unchanged amid inflation concerns",
    "Apple unveils new iPhone with foldable screen",
    "EU paves way to finalise US trade deal and avoid Trump tariff hike",
    "",
])
def test_is_generic_doc_negative(title):
    assert not _is_generic_document_title(title), repr(title)


def test_is_generic_doc_none_input():
    assert _is_generic_document_title(None) is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(source: str, title: str, pub: str = "2026-05-26T12:00:00") -> dict:
    return {"source": source, "title": title, "published_at": pub, "url": ""}


def _headlines(clusters):
    return sorted(c.get("headline", "") for c in clusters)


# ---------------------------------------------------------------------------
# cluster_headlines — guard blocks doc ↔ live-news bridge merges
# ---------------------------------------------------------------------------

def test_trade_summary_does_not_merge_with_live_india_trade_news():
    """Audit case #1: the 2015 USTR 'TRADE SUMMARY' document must not
    absorb a May-2026 India/Rubio trade-policy live headline."""
    records = [
        _rec("USTR Trade Policy",
             "TRADE SUMMARY The U.S. goods trade deficit with India was $18.2 billion in 2012"),
        _rec("AP News",
             "India, US discuss Middle East, trade as Rubio cites progress on Iran conflict"),
    ]
    clusters = cluster_headlines(records)
    assert len(clusters) == 2, _headlines(clusters)


def test_connecting_to_compete_does_not_merge_with_live_trade_news():
    """World-Bank 'Connecting to Compete YYYY' must not bridge into live
    EU/US trade headlines."""
    records = [
        _rec("World Bank",
             "Connecting to Compete 2018 : Trade Logistics in the Global Economy"),
        _rec("Reuters World",
             "EU paves way to finalise US trade deal and avoid Trump tariff hike"),
    ]
    clusters = cluster_headlines(records)
    assert len(clusters) == 2, _headlines(clusters)


def test_doing_business_does_not_merge_with_unrelated_world_bank_doc():
    """Two generic-doc titles whose only overlap is boilerplate (one
    'doing business' + one '| World Bank Group' suffix) must not merge."""
    records = [
        _rec("World Bank", "Announcement of Doing Business 2008 on September 26, 2007"),
        _rec("World Bank", "Zimbabwe | World Bank Group"),
    ]
    clusters = cluster_headlines(records)
    assert len(clusters) == 2, _headlines(clusters)


def test_world_bank_group_boilerplate_does_not_bridge_repo_docs():
    """Three '- World Bank Group'-suffixed documents on substantively
    different topics must each form their own cluster.  The
    near-duplicate threshold prevents boilerplate-only merges."""
    records = [
        _rec("World Bank", "Gender Data Portal - World Bank Group"),
        _rec("World Bank", "Carbon Pricing Trends 2026 - World Bank Group"),
        _rec("World Bank", "British Guiana economy (English) - World Bank Group"),
    ]
    clusters = cluster_headlines(records)
    assert len(clusters) == 3, _headlines(clusters)


# ---------------------------------------------------------------------------
# cluster_headlines — guard preserves legitimate merges
# ---------------------------------------------------------------------------

def test_near_duplicate_generic_documents_still_merge():
    """Two near-identical versions of the same publication must still
    cluster (high-cosine escape above near-dup threshold)."""
    records = [
        _rec("World Bank",
             "World Development Report 2026: Climate and Growth"),
        _rec("Reuters World",
             "World Development Report 2026: Climate and Growth (Updated)"),
    ]
    clusters = cluster_headlines(records)
    assert len(clusters) == 1, _headlines(clusters)


def test_live_trade_policy_duplicates_still_merge():
    """Regression guard: two live-news headlines on the same EU/US
    trade-deal story must still cluster — the guard must not interfere
    with non-document live news."""
    records = [
        _rec("Reuters World",
             "EU paves way to finalise US trade deal and avoid Trump tariff hike"),
        _rec("AFP World",
             "EU reaches deal on US trade pact as Trump threatens new tariffs"),
    ]
    clusters = cluster_headlines(records)
    assert len(clusters) == 1, _headlines(clusters)


# ---------------------------------------------------------------------------
# news_cluster_store._can_merge — cross-refresh consistency
# ---------------------------------------------------------------------------

def test_cluster_store_can_merge_blocks_doc_vs_live_news():
    """The store-level merge path must apply the same guard so a stored
    generic-doc cluster never absorbs a new live-news cluster across
    refreshes."""
    from news_cluster_store import _can_merge
    assert _can_merge(
        "TRADE SUMMARY The U.S. goods trade deficit with India was $18.2 billion in 2012",
        "India, US discuss Middle East, trade as Rubio cites progress on Iran conflict",
    ) is False


def test_cluster_store_can_merge_blocks_two_unrelated_docs():
    """Two repository docs sharing only the World-Bank-Group suffix
    must not merge across refreshes either."""
    from news_cluster_store import _can_merge
    assert _can_merge(
        "Gender Data Portal - World Bank Group",
        "Carbon Pricing Trends 2026 - World Bank Group",
    ) is False


def test_cluster_store_can_merge_allows_near_duplicate_documents():
    """Two near-duplicate document titles must still cross-merge via
    the high-cosine escape."""
    from news_cluster_store import _can_merge
    assert _can_merge(
        "World Development Report 2026: Climate and Growth",
        "World Development Report 2026: Climate and Growth (Updated)",
    ) is True


def test_cluster_store_can_merge_allows_live_news_duplicates():
    """Regression guard for cross-refresh path."""
    from news_cluster_store import _can_merge
    assert _can_merge(
        "EU paves way to finalise US trade deal and avoid Trump tariff hike",
        "EU reaches deal on US trade pact as Trump threatens new tariffs",
    ) is True


# ---------------------------------------------------------------------------
# Sanity: near-dup threshold is above the regular cluster threshold
# (documents that share only boilerplate sit between the two).
# ---------------------------------------------------------------------------

def test_near_dup_threshold_higher_than_cluster_threshold():
    from news_clustering import _CLUSTER_THRESHOLD
    assert _GENERIC_DOC_NEAR_DUP_THRESHOLD > _CLUSTER_THRESHOLD
