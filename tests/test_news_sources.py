"""
tests/test_news_sources.py

Unit tests for news_sources.py — local JSON loading, normalization, and dedup.
RSS tests mock feedparser so no network calls are needed.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".")
import news_sources


class TestLoadLocal(unittest.TestCase):

    def test_returns_empty_when_file_missing(self):
        result = news_sources.load_local("/nonexistent/path.json")
        self.assertEqual(result, [])

    def test_loads_valid_file(self):
        data = [
            {"title": "Headline A", "source": "test", "published_at": "2026-01-01", "url": "http://a"},
            {"title": "Headline B"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = news_sources.load_local(path)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["title"], "Headline A")
            self.assertEqual(result[0]["source"], "test")
            # Second item has defaults
            self.assertEqual(result[1]["source"], "local")
            self.assertEqual(result[1]["url"], "")
        finally:
            os.remove(path)

    def test_skips_entries_with_empty_title(self):
        data = [{"title": ""}, {"title": "  "}, {"title": "Valid"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = news_sources.load_local(path)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["title"], "Valid")
        finally:
            os.remove(path)

    def test_skips_non_dict_entries(self):
        data = [
            "just a string",
            42,
            None,
            ["a", "list"],
            True,
            {"title": "Valid headline"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = news_sources.load_local(path)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["title"], "Valid headline")
        finally:
            os.remove(path)

    def test_mixed_good_and_bad_entries(self):
        data = [
            {"title": "First real headline"},
            123,
            {"title": "Second real headline"},
            {"not_title": "missing title field"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = news_sources.load_local(path)
            self.assertEqual(len(result), 2)
        finally:
            os.remove(path)

    def test_returns_empty_on_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{bad json")
            path = f.name
        try:
            result = news_sources.load_local(path)
            self.assertEqual(result, [])
        finally:
            os.remove(path)


class TestDedupKey(unittest.TestCase):

    def test_lowercases_and_strips_punctuation(self):
        self.assertEqual(
            news_sources._dedup_key("US Imposes Tariffs!"),
            news_sources._dedup_key("us imposes tariffs"),
        )

    def test_different_headlines_produce_different_keys(self):
        self.assertNotEqual(
            news_sources._dedup_key("US imposes tariffs"),
            news_sources._dedup_key("China restricts exports"),
        )


class TestFetchAll(unittest.TestCase):

    def test_deduplicates_same_source_same_title(self):
        """Same source + same title = true duplicate → keep only one."""
        dupes = [
            {"title": "EU imposes new tariffs on steel", "source": "A"},
            {"title": "EU imposes new tariffs on steel", "source": "A"},
            {"title": "OPEC announces production cut", "source": "C"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(dupes, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 2)
            titles = [r["title"] for r in result]
            self.assertEqual(titles.count("EU imposes new tariffs on steel"), 1)
        finally:
            os.remove(path)

    def test_preserves_cross_source_identical_titles(self):
        """Different sources with the same title should both survive dedup."""
        items = [
            {"title": "China sanctions US defense firms", "source": "A"},
            {"title": "China sanctions US defense firms", "source": "B"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 2)
            sources = {r["source"] for r in result}
            self.assertEqual(sources, {"A", "B"})
        finally:
            os.remove(path)

    def test_deduplicates_same_source_despite_punctuation_differences(self):
        dupes = [
            {"title": "US imposes tariffs!", "source": "A", "published_at": "2026-01-02"},
            {"title": "US Imposes Tariffs",  "source": "A", "published_at": "2026-01-01"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(dupes, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 1)
        finally:
            os.remove(path)

    def test_cross_source_punctuation_variants_preserved(self):
        """Different sources with punctuation-only title diffs both survive."""
        items = [
            {"title": "US imposes tariffs!", "source": "A", "published_at": "2026-01-02"},
            {"title": "US Imposes Tariffs",  "source": "B", "published_at": "2026-01-01"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 2)
        finally:
            os.remove(path)

    def test_sorted_newest_first(self):
        items = [
            {"title": "Old sanctions imposed", "published_at": "2026-01-01"},
            {"title": "New tariff deal announced", "published_at": "2026-03-15"},
            {"title": "Central bank rate cut expected", "published_at": "2026-02-10"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            titles = [r["title"] for r in result]
            self.assertEqual(titles, ["New tariff deal announced",
                                      "Central bank rate cut expected",
                                      "Old sanctions imposed"])
        finally:
            os.remove(path)


def _make_mock_entry(title: str, link: str = "http://example.com", pub_parsed=None):
    """Helper: build a mock feedparser entry with predictable .get() behavior."""
    entry_data = {
        "title":            title,
        "link":             link,
        "published_parsed": pub_parsed or (2026, 4, 1, 12, 0, 0, 0, 0, 0),
    }
    entry = MagicMock()
    entry.get = lambda k, d="": entry_data.get(k, d)
    entry.published_parsed = entry_data["published_parsed"]
    entry.published = "Tue, 01 Apr 2026 12:00:00 GMT"
    return entry


class TestLoadRss(unittest.TestCase):

    def test_returns_empty_when_feedparser_missing(self):
        with patch.dict(sys.modules, {"feedparser": None}):
            result, status = news_sources.load_rss(feeds=[])
        self.assertEqual(result, [])

    def test_parses_mock_feed(self):
        mock_feed = MagicMock()
        mock_feed.entries = [_make_mock_entry("Test RSS Headline", "http://example.com/article")]

        mock_fp = MagicMock()
        mock_fp.parse.return_value = mock_feed

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            result, status = news_sources.load_rss(feeds=[{"name": "TestFeed", "url": "http://fake"}])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Test RSS Headline")
        self.assertEqual(result[0]["source"], "TestFeed")
        self.assertIn("2026-04-01", result[0]["published_at"])

    def test_failed_feed_is_skipped_gracefully(self):
        """A feed that raises an exception should not prevent other feeds from loading."""
        good_feed = MagicMock()
        good_feed.entries = [_make_mock_entry("Good Headline")]

        mock_fp = MagicMock()
        # First call raises, second call returns a good feed
        mock_fp.parse.side_effect = [Exception("connection timeout"), good_feed]

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            result, status = news_sources.load_rss(feeds=[
                {"name": "BadFeed",  "url": "http://bad-url"},
                {"name": "GoodFeed", "url": "http://good-url"},
            ])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Good Headline")
        self.assertEqual(result[0]["source"], "GoodFeed")

    def test_entries_with_empty_title_are_skipped(self):
        mock_feed = MagicMock()
        mock_feed.entries = [
            _make_mock_entry(""),          # empty title → skip
            _make_mock_entry("   "),       # whitespace-only → skip
            _make_mock_entry("Real one"),  # good
        ]

        mock_fp = MagicMock()
        mock_fp.parse.return_value = mock_feed

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            result, status = news_sources.load_rss(feeds=[{"name": "F", "url": "http://f"}])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Real one")

    def test_multiple_feeds_are_combined(self):
        """Records from two working feeds are concatenated."""
        feed_a = MagicMock()
        feed_a.entries = [_make_mock_entry("Headline from A")]
        feed_b = MagicMock()
        feed_b.entries = [_make_mock_entry("Headline from B")]

        mock_fp = MagicMock()
        mock_fp.parse.side_effect = [feed_a, feed_b]

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            result, status = news_sources.load_rss(feeds=[
                {"name": "FeedA", "url": "http://a"},
                {"name": "FeedB", "url": "http://b"},
            ])

        titles = [r["title"] for r in result]
        self.assertIn("Headline from A", titles)
        self.assertIn("Headline from B", titles)
        self.assertEqual(len(result), 2)

    def test_timeout_is_restored_after_feed_failure(self):
        """Socket default timeout must be restored even when a feed crashes."""
        import socket
        original_timeout = socket.getdefaulttimeout()

        mock_fp = MagicMock()
        mock_fp.parse.side_effect = Exception("boom")

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            news_sources.load_rss(feeds=[{"name": "Bad", "url": "http://x"}])

        self.assertEqual(socket.getdefaulttimeout(), original_timeout)

    def test_default_feeds_list_has_four_entries(self):
        self.assertEqual(len(news_sources.DEFAULT_FEEDS), 4)

    def test_guardian_is_in_default_feeds(self):
        names = [f["name"] for f in news_sources.DEFAULT_FEEDS]
        self.assertIn("The Guardian Business", names)

    def test_wsj_is_in_default_feeds(self):
        names = [f["name"] for f in news_sources.DEFAULT_FEEDS]
        self.assertIn("WSJ World News", names)

    def test_bbc_is_in_default_feeds(self):
        names = [f["name"] for f in news_sources.DEFAULT_FEEDS]
        self.assertIn("BBC Business", names)

    def test_reuters_is_in_default_feeds(self):
        names = [f["name"] for f in news_sources.DEFAULT_FEEDS]
        self.assertIn("Reuters World", names)

    def test_feeds_use_narrow_sections(self):
        """Feeds should target specific sections, not top-level catch-all feeds."""
        for feed in news_sources.DEFAULT_FEEDS:
            url = feed["url"].lower()
            has_section = any(s in url for s in [
                "/business", "/economy", "/world", "/rssworld",
                "site:reuters.com",  # Google News proxy filtered to Reuters
            ])
            self.assertTrue(
                has_section,
                f"{feed['name']} URL does not target a narrow section: {feed['url']}",
            )

    def test_no_al_jazeera_in_default_feeds(self):
        """Al Jazeera was replaced — should not appear in active feed list."""
        names = [f["name"] for f in news_sources.DEFAULT_FEEDS]
        for name in names:
            self.assertNotIn("Al Jazeera", name)


class TestFeedStatus(unittest.TestCase):
    """load_rss and fetch_all return per-feed status for UI display."""

    def test_healthy_feed_status(self):
        mock_feed = MagicMock()
        mock_feed.entries = [_make_mock_entry("Headline")]
        mock_fp = MagicMock()
        mock_fp.parse.return_value = mock_feed

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            _, status = news_sources.load_rss(
                feeds=[{"name": "Good", "url": "http://good"}])

        self.assertEqual(len(status), 1)
        self.assertTrue(status[0]["ok"])
        self.assertEqual(status[0]["name"], "Good")
        self.assertEqual(status[0]["headlines"], 1)

    def test_failed_feed_status(self):
        mock_fp = MagicMock()
        mock_fp.parse.side_effect = Exception("timeout")

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            _, status = news_sources.load_rss(
                feeds=[{"name": "Bad", "url": "http://bad"}])

        self.assertEqual(len(status), 1)
        self.assertFalse(status[0]["ok"])
        self.assertEqual(status[0]["headlines"], 0)

    def test_partial_failure_status(self):
        good_feed = MagicMock()
        good_feed.entries = [_make_mock_entry("OK headline")]
        mock_fp = MagicMock()
        mock_fp.parse.side_effect = [Exception("timeout"), good_feed]

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            records, status = news_sources.load_rss(feeds=[
                {"name": "BadFeed",  "url": "http://bad"},
                {"name": "GoodFeed", "url": "http://good"},
            ])

        self.assertEqual(len(status), 2)
        bad  = next(s for s in status if s["name"] == "BadFeed")
        good = next(s for s in status if s["name"] == "GoodFeed")
        self.assertFalse(bad["ok"])
        self.assertTrue(good["ok"])
        self.assertEqual(len(records), 1)

    def test_empty_feed_marked_not_ok(self):
        """A feed that parses but returns zero entries is not ok."""
        mock_feed = MagicMock()
        mock_feed.entries = []
        mock_fp = MagicMock()
        mock_fp.parse.return_value = mock_feed

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            _, status = news_sources.load_rss(
                feeds=[{"name": "Empty", "url": "http://empty"}])

        self.assertFalse(status[0]["ok"])
        self.assertEqual(status[0]["headlines"], 0)

    def test_feedparser_missing_all_feeds_fail(self):
        """When feedparser cannot be imported, every feed is marked failed."""
        with patch.dict(sys.modules, {"feedparser": None}):
            _, status = news_sources.load_rss(feeds=[
                {"name": "A", "url": "http://a"},
                {"name": "B", "url": "http://b"},
            ])
        self.assertEqual(len(status), 2)
        self.assertTrue(all(not s["ok"] for s in status))

    def test_fetch_all_returns_feed_status(self):
        """fetch_all passes feed_status through from load_rss."""
        items = [{"title": "Local trade sanctions update", "source": "local"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            records, status = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(records), 1)
            self.assertIsInstance(status, list)
        finally:
            os.remove(path)


class TestSourceTier(unittest.TestCase):

    def test_known_high_tier(self):
        self.assertEqual(news_sources.source_tier("BBC World"), "high")
        self.assertEqual(news_sources.source_tier("BBC Business"), "high")
        self.assertEqual(news_sources.source_tier("Reuters World"), "high")
        self.assertEqual(news_sources.source_tier("The Guardian World"), "high")
        self.assertEqual(news_sources.source_tier("The Guardian Business"), "high")
        self.assertEqual(news_sources.source_tier("WSJ World News"), "high")

    def test_known_medium_tier(self):
        self.assertEqual(news_sources.source_tier("Al Jazeera"), "medium")
        self.assertEqual(news_sources.source_tier("Al Jazeera Economy"), "medium")

    def test_known_low_tier(self):
        self.assertEqual(news_sources.source_tier("local"), "low")

    def test_unknown_source_defaults_to_low(self):
        self.assertEqual(news_sources.source_tier("Random Blog"), "low")


class TestHeadlineWords(unittest.TestCase):

    def test_removes_stop_words(self):
        words = news_sources._headline_words("The US imposes tariffs on China")
        self.assertNotIn("the", words)
        self.assertNotIn("on", words)
        self.assertIn("us", words)
        self.assertIn("tariffs", words)
        self.assertIn("china", words)

    def test_empty_string(self):
        self.assertEqual(news_sources._headline_words(""), set())


class TestJaccard(unittest.TestCase):

    def test_identical_sets(self):
        s = {"us", "tariffs", "china"}
        self.assertAlmostEqual(news_sources._jaccard(s, s), 1.0)

    def test_disjoint_sets(self):
        self.assertAlmostEqual(
            news_sources._jaccard({"us", "tariffs"}, {"oil", "opec"}), 0.0
        )

    def test_partial_overlap(self):
        a = {"us", "tariffs", "steel"}
        b = {"eu", "tariffs", "steel"}
        # intersection=2, union=4 → 0.5
        self.assertAlmostEqual(news_sources._jaccard(a, b), 0.5)

    def test_empty_set_returns_zero(self):
        self.assertEqual(news_sources._jaccard(set(), {"a"}), 0.0)
        self.assertEqual(news_sources._jaccard({"a"}, set()), 0.0)


class TestClusterHeadlines(unittest.TestCase):

    def _rec(self, title, source="local", pub="2026-04-01T12:00:00", url=""):
        return {"title": title, "source": source, "published_at": pub, "url": url}

    def test_identical_stories_cluster_together(self):
        records = [
            self._rec("EU imposes retaliatory tariffs on US steel", "BBC World"),
            self._rec("EU announces retaliatory tariffs on US steel imports", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["source_count"], 2)

    def test_different_stories_stay_separate(self):
        records = [
            self._rec("EU imposes tariffs on US steel", "BBC World"),
            self._rec("Japan launches lunar lander mission", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 2)

    def test_headline_picked_from_highest_tier(self):
        records = [
            self._rec("EU retaliatory tariffs target US steel imports", "local"),
            self._rec("EU retaliatory tariffs imposed on US steel imports today", "BBC World"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        # BBC (high tier) headline should win over local (low tier)
        self.assertEqual(clusters[0]["sources"][0]["name"], "BBC World")
        self.assertIn("BBC World", clusters[0]["sources"][0]["name"])

    def test_sources_ordered_by_tier(self):
        records = [
            self._rec("US steel tariffs announced", "local"),
            self._rec("US steel tariffs announced by EU", "Al Jazeera"),
            self._rec("EU announces US steel tariffs", "BBC World"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        tiers = [s["tier"] for s in clusters[0]["sources"]]
        self.assertEqual(tiers, ["high", "medium", "low"])

    def test_published_at_is_most_recent(self):
        records = [
            self._rec("Steel tariffs update", "BBC World", pub="2026-04-02T10:00:00"),
            self._rec("EU steel tariffs announced update", "Al Jazeera", pub="2026-04-01T08:00:00"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["published_at"], "2026-04-02T10:00:00")

    def test_cluster_with_old_corroboration_still_ranks_high(self):
        """A multi-source cluster with one old article should rank by its newest source."""
        records = [
            self._rec("Japan earthquake tsunami warning issued", "BBC World", pub="2026-04-03T14:00:00"),
            # Cluster: two sources, one old corroboration
            self._rec("EU steel tariffs escalation confirmed", "BBC World", pub="2026-04-03T12:00:00"),
            self._rec("EU steel tariffs escalation announced", "Al Jazeera", pub="2026-04-01T08:00:00"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 2)
        # The steel cluster has a newest source at 12:00 on Apr 3 — should rank second
        # (Japan at 14:00 is first)
        self.assertIn("Japan", clusters[0]["headline"])
        self.assertIn("tariffs", clusters[1]["headline"].lower())

    def test_agreement_consistent_for_similar_headlines(self):
        records = [
            self._rec("EU imposes retaliatory tariffs on US steel", "BBC World"),
            self._rec("EU announces retaliatory tariffs on US steel imports", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(clusters[0]["agreement"], "consistent")

    def test_empty_input(self):
        self.assertEqual(news_sources.cluster_headlines([]), [])

    def test_single_record_becomes_single_cluster(self):
        records = [self._rec("Breaking headline", "BBC World")]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["source_count"], 1)
        self.assertEqual(clusters[0]["agreement"], "consistent")

    def test_sorted_newest_first(self):
        records = [
            self._rec("Japan earthquake tsunami warning issued", "BBC World", pub="2026-03-01T08:00:00"),
            self._rec("EU proposes carbon border adjustment mechanism", "BBC World", pub="2026-04-03T08:00:00"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["headline"], "EU proposes carbon border adjustment mechanism")

    def test_duplicate_source_deduped_in_cluster(self):
        """Same source appearing twice in a cluster only listed once."""
        records = [
            self._rec("Tariffs on steel announced by EU", "BBC World", pub="2026-04-01T10:00:00"),
            self._rec("EU tariffs on steel imports start", "BBC World", pub="2026-04-01T12:00:00"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["source_count"], 1)


class TestClusterOrderIndependence(unittest.TestCase):
    """Clustering should produce the same groups regardless of input order."""

    def _rec(self, title, source="local", pub="2026-04-01T12:00:00", url=""):
        return {"title": title, "source": source, "published_at": pub, "url": url}

    def _cluster_source_sets(self, records):
        """Return a frozenset of frozensets — the grouping of sources, order-free."""
        clusters = news_sources.cluster_headlines(records)
        return frozenset(
            frozenset(s["name"] for s in c["sources"])
            for c in clusters
        )

    def test_two_similar_headlines_order_independent(self):
        a = self._rec("EU imposes retaliatory tariffs on US steel", "BBC World")
        b = self._rec("EU announces retaliatory tariffs on US steel imports", "Al Jazeera")
        self.assertEqual(
            self._cluster_source_sets([a, b]),
            self._cluster_source_sets([b, a]),
        )

    def test_three_headlines_all_orderings_same(self):
        import itertools
        recs = [
            self._rec("EU imposes retaliatory tariffs on US steel", "BBC World"),
            self._rec("EU announces retaliatory tariffs on US steel imports", "Al Jazeera"),
            self._rec("EU retaliatory tariffs target US steel products", "WSJ World News"),
        ]
        results = set()
        for perm in itertools.permutations(recs):
            results.add(self._cluster_source_sets(list(perm)))
        self.assertEqual(len(results), 1, "Clustering varied across input orderings")

    def test_mixed_stories_order_independent(self):
        """Two distinct stories should stay separate regardless of interleaving."""
        import itertools
        recs = [
            self._rec("EU imposes tariffs on US steel", "BBC World"),
            self._rec("Japan launches lunar lander mission", "Al Jazeera"),
            self._rec("EU announces tariffs on US steel imports", "WSJ World News"),
            self._rec("Japan moon lander reaches orbit", "BBC World"),
        ]
        results = set()
        for perm in itertools.permutations(recs):
            results.add(self._cluster_source_sets(list(perm)))
        self.assertEqual(len(results), 1, "Clustering varied across input orderings")

    def test_transitive_similarity(self):
        """A≈B and B≈C should put all three in one cluster even if A≉C.

        Headline A and C share fewer words directly, but B bridges them.
        """
        a = self._rec("EU steel tariffs imposed on imports", "BBC World")
        b = self._rec("EU steel tariffs raise trade tensions", "Al Jazeera")
        c = self._rec("Trade tensions escalate over tariffs", "WSJ World News")

        # Verify the bridge assumption: A≈B and B≈C above threshold, A≈C may be below
        wa = news_sources._headline_words(a["title"])
        wb = news_sources._headline_words(b["title"])
        wc = news_sources._headline_words(c["title"])
        self.assertGreaterEqual(news_sources._jaccard(wa, wb), news_sources._CLUSTER_THRESHOLD)
        self.assertGreaterEqual(news_sources._jaccard(wb, wc), news_sources._CLUSTER_THRESHOLD)

        clusters = news_sources.cluster_headlines([a, b, c])
        self.assertEqual(len(clusters), 1, "Transitive similarity should merge all three")
        self.assertEqual(clusters[0]["source_count"], 3)


class TestClusterCrossSourceIdenticalTitles(unittest.TestCase):
    """Identical titles from different sources should cluster together and
    produce a multi-source cluster — not be silently dropped."""

    def _rec(self, title, source="local", pub="2026-04-01T12:00:00", url=""):
        return {"title": title, "source": source, "published_at": pub, "url": url}

    def test_identical_titles_cluster_with_both_sources(self):
        records = [
            self._rec("EU imposes tariffs on US steel", "BBC World"),
            self._rec("EU imposes tariffs on US steel", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["source_count"], 2)
        source_names = {s["name"] for s in clusters[0]["sources"]}
        self.assertEqual(source_names, {"BBC World", "Al Jazeera"})

    def test_three_sources_identical_title_all_counted(self):
        records = [
            self._rec("Oil prices surge after OPEC cut", "BBC World"),
            self._rec("Oil prices surge after OPEC cut", "Al Jazeera"),
            self._rec("Oil prices surge after OPEC cut", "WSJ World News"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["source_count"], 3)

    def test_identical_titles_produce_corroborated_summary(self):
        records = [
            self._rec("EU imposes tariffs on US steel", "BBC World"),
            self._rec("EU imposes tariffs on US steel", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertIn("Corroborated", clusters[0]["summary"])

    def test_identical_titles_show_consistent_agreement(self):
        records = [
            self._rec("EU imposes tariffs on US steel", "BBC World"),
            self._rec("EU imposes tariffs on US steel", "WSJ World News"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(clusters[0]["agreement"], "consistent")


class TestBuildSummary(unittest.TestCase):
    """Tests for _build_summary() — the merged summary generator."""

    def _rec(self, title, source="local", pub="2026-04-01T12:00:00", url=""):
        return {"title": title, "source": source, "published_at": pub, "url": url}

    def _src(self, name, tier="low"):
        return {"name": name, "tier": tier, "url": ""}

    def test_single_source_includes_source_name(self):
        summary = news_sources._build_summary(
            best_headline="Oil prices surge after OPEC cut",
            best_source="BBC World",
            records=[self._rec("Oil prices surge after OPEC cut", "BBC World")],
            sources=[self._src("BBC World", "high")],
            agreement="consistent",
        )
        self.assertIn("BBC World", summary)

    def test_single_source_high_tier_label(self):
        summary = news_sources._build_summary(
            best_headline="Oil prices surge",
            best_source="BBC World",
            records=[self._rec("Oil prices surge", "BBC World")],
            sources=[self._src("BBC World", "high")],
            agreement="consistent",
        )
        self.assertIn("major outlet", summary)

    def test_single_source_medium_tier_label(self):
        summary = news_sources._build_summary(
            best_headline="Oil prices surge",
            best_source="Al Jazeera",
            records=[self._rec("Oil prices surge", "Al Jazeera")],
            sources=[self._src("Al Jazeera", "medium")],
            agreement="consistent",
        )
        self.assertIn("regional outlet", summary)

    def test_single_source_low_tier_label(self):
        summary = news_sources._build_summary(
            best_headline="Oil prices surge",
            best_source="local",
            records=[self._rec("Oil prices surge", "local")],
            sources=[self._src("local", "low")],
            agreement="consistent",
        )
        self.assertIn("single source", summary)

    def test_multi_source_consistent_mentions_corroboration(self):
        summary = news_sources._build_summary(
            best_headline="EU imposes steel tariffs on US",
            best_source="BBC World",
            records=[
                self._rec("EU imposes steel tariffs on US", "BBC World"),
                self._rec("EU announces steel tariffs on US imports", "Al Jazeera"),
            ],
            sources=[
                self._src("BBC World", "high"),
                self._src("Al Jazeera", "medium"),
            ],
            agreement="consistent",
        )
        self.assertIn("Corroborated", summary)
        self.assertIn("Al Jazeera", summary)

    def test_multi_source_consistent_leads_with_best_headline(self):
        summary = news_sources._build_summary(
            best_headline="EU imposes steel tariffs on US",
            best_source="BBC World",
            records=[
                self._rec("EU imposes steel tariffs on US", "BBC World"),
                self._rec("EU announces steel tariffs on US imports", "Al Jazeera"),
            ],
            sources=[
                self._src("BBC World", "high"),
                self._src("Al Jazeera", "medium"),
            ],
            agreement="consistent",
        )
        self.assertTrue(summary.startswith("EU imposes steel tariffs on US"))

    def test_mixed_agreement_surfaces_disagreement(self):
        summary = news_sources._build_summary(
            best_headline="US imposes sweeping sanctions on Iran",
            best_source="BBC World",
            records=[
                self._rec("US imposes sweeping sanctions on Iran", "BBC World"),
                self._rec("Washington considers limited diplomatic pressure on Tehran", "local"),
            ],
            sources=[
                self._src("BBC World", "high"),
                self._src("local", "low"),
            ],
            agreement="mixed",
        )
        self.assertIn("framing differs", summary)
        self.assertIn("local", summary)
        # The divergent headline should be quoted
        self.assertIn("Washington considers limited diplomatic pressure on Tehran", summary)

    def test_mixed_agreement_names_best_source(self):
        summary = news_sources._build_summary(
            best_headline="US imposes sanctions on Iran",
            best_source="WSJ World News",
            records=[
                self._rec("US imposes sanctions on Iran", "WSJ World News"),
                self._rec("Iran faces minor trade restrictions", "local"),
            ],
            sources=[
                self._src("WSJ World News", "high"),
                self._src("local", "low"),
            ],
            agreement="mixed",
        )
        self.assertIn("via WSJ World News", summary)

    def test_three_source_consistent_lists_all_others(self):
        summary = news_sources._build_summary(
            best_headline="OPEC agrees production cut",
            best_source="BBC World",
            records=[
                self._rec("OPEC agrees production cut", "BBC World"),
                self._rec("OPEC announces production cut deal", "Al Jazeera"),
                self._rec("OPEC production cut confirmed", "local"),
            ],
            sources=[
                self._src("BBC World", "high"),
                self._src("Al Jazeera", "medium"),
                self._src("local", "low"),
            ],
            agreement="consistent",
        )
        self.assertIn("Al Jazeera", summary)
        self.assertIn("local", summary)
        # Lead source should not appear in the "corroborated by" list
        corroborated_part = summary.split("Corroborated by")[1]
        self.assertNotIn("BBC World", corroborated_part)


class TestClusterSummaryIntegration(unittest.TestCase):
    """End-to-end: cluster_headlines() returns a summary field."""

    def _rec(self, title, source="local", pub="2026-04-01T12:00:00", url=""):
        return {"title": title, "source": source, "published_at": pub, "url": url}

    def test_cluster_output_has_summary_field(self):
        records = [self._rec("Breaking headline", "BBC World")]
        clusters = news_sources.cluster_headlines(records)
        self.assertIn("summary", clusters[0])
        self.assertIsInstance(clusters[0]["summary"], str)
        self.assertTrue(len(clusters[0]["summary"]) > 0)

    def test_multi_source_cluster_summary_mentions_corroboration(self):
        records = [
            self._rec("EU imposes retaliatory tariffs on US steel", "BBC World"),
            self._rec("EU announces retaliatory tariffs on US steel imports", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertIn("Corroborated", clusters[0]["summary"])


class TestScanKeywords(unittest.TestCase):

    def test_finds_single_actor(self):
        result = news_sources._scan_keywords("China restricts exports", news_sources._ACTOR_KEYWORDS)
        self.assertIn("China", result)

    def test_finds_multiple_actors(self):
        result = news_sources._scan_keywords(
            "EU proposes tariffs on US steel", news_sources._ACTOR_KEYWORDS,
        )
        self.assertIn("European Union", result)
        self.assertIn("United States", result)

    def test_case_insensitive(self):
        result = news_sources._scan_keywords("CHINA bans exports", news_sources._ACTOR_KEYWORDS)
        self.assertIn("China", result)

    def test_no_duplicates(self):
        result = news_sources._scan_keywords(
            "Chinese officials in China announce policy",
            news_sources._ACTOR_KEYWORDS,
        )
        self.assertEqual(result.count("China"), 1)

    def test_empty_text(self):
        self.assertEqual(news_sources._scan_keywords("", news_sources._ACTOR_KEYWORDS), [])

    def test_multi_word_match(self):
        result = news_sources._scan_keywords(
            "South Korea responds to North Korea missile test",
            news_sources._ACTOR_KEYWORDS,
        )
        self.assertIn("South Korea", result)
        self.assertIn("North Korea", result)


class TestScanAction(unittest.TestCase):

    def test_tariffs(self):
        self.assertEqual(news_sources._scan_action("EU imposes tariffs"), "tariffs")

    def test_sanctions(self):
        self.assertEqual(news_sources._scan_action("US sanctions on Iran"), "sanctions")

    def test_export_restrictions(self):
        self.assertEqual(
            news_sources._scan_action("China restricts rare earth exports"),
            "export restrictions",
        )

    def test_military_action(self):
        self.assertEqual(
            news_sources._scan_action("Houthi missile strikes on Red Sea shipping"),
            "military action",
        )

    def test_unknown_action(self):
        self.assertEqual(news_sources._scan_action("Something vague happened"), "unknown")


class TestExtractConsensus(unittest.TestCase):

    def _src(self, name, tier="low"):
        return {"name": name, "tier": tier, "url": ""}

    def test_basic_extraction(self):
        con = news_sources.extract_consensus(
            headline="EU proposes retaliatory tariffs on US steel imports",
            all_titles=["EU proposes retaliatory tariffs on US steel imports"],
            sources=[self._src("BBC World", "high")],
            agreement="consistent",
        )
        self.assertIn("European Union", con["actors"])
        self.assertIn("United States", con["actors"])
        self.assertEqual(con["action"], "tariffs")
        self.assertEqual(con["sector"], "metals")
        self.assertIn("Europe", con["geography"])

    def test_geography_derived_from_actors(self):
        con = news_sources.extract_consensus(
            headline="Japan and South Korea reach trade agreement",
            all_titles=["Japan and South Korea reach trade agreement"],
            sources=[self._src("BBC World", "high")],
            agreement="consistent",
        )
        self.assertIn("East Asia", con["geography"])

    def test_unknown_sector_when_no_match(self):
        con = news_sources.extract_consensus(
            headline="Leaders meet at summit for discussions",
            all_titles=["Leaders meet at summit for discussions"],
            sources=[self._src("local", "low")],
            agreement="consistent",
        )
        self.assertEqual(con["sector"], "unknown")

    def test_unknown_action_when_no_match(self):
        con = news_sources.extract_consensus(
            headline="Leaders meet at summit",
            all_titles=["Leaders meet at summit"],
            sources=[self._src("local", "low")],
            agreement="consistent",
        )
        self.assertEqual(con["action"], "unknown")

    def test_uncertainty_low_multiple_high_tier(self):
        con = news_sources.extract_consensus(
            headline="EU tariffs on US steel",
            all_titles=["EU tariffs on US steel", "EU tariffs on US steel imports"],
            sources=[
                self._src("BBC World", "high"),
                self._src("WSJ World News", "high"),
            ],
            agreement="consistent",
        )
        self.assertEqual(con["uncertainty"], "low")

    def test_uncertainty_medium_single_high_tier(self):
        con = news_sources.extract_consensus(
            headline="EU tariffs on US steel",
            all_titles=["EU tariffs on US steel"],
            sources=[self._src("BBC World", "high")],
            agreement="consistent",
        )
        self.assertEqual(con["uncertainty"], "medium")

    def test_uncertainty_high_when_mixed(self):
        con = news_sources.extract_consensus(
            headline="EU tariffs on US steel",
            all_titles=["EU tariffs on US steel", "EU considers trade response"],
            sources=[
                self._src("BBC World", "high"),
                self._src("local", "low"),
            ],
            agreement="mixed",
        )
        self.assertEqual(con["uncertainty"], "high")

    def test_uncertainty_high_single_low_tier(self):
        con = news_sources.extract_consensus(
            headline="EU tariffs on US steel",
            all_titles=["EU tariffs on US steel"],
            sources=[self._src("local", "low")],
            agreement="consistent",
        )
        self.assertEqual(con["uncertainty"], "high")

    def test_consensus_field_maps_agreement(self):
        con1 = news_sources.extract_consensus(
            "headline", ["headline"], [self._src("BBC World", "high")], "consistent",
        )
        con2 = news_sources.extract_consensus(
            "headline", ["headline"], [self._src("BBC World", "high")], "mixed",
        )
        self.assertEqual(con1["consensus"], "consensus")
        self.assertEqual(con2["consensus"], "mixed")

    def test_scans_all_titles_not_just_headline(self):
        """Keywords from secondary headlines should still be detected."""
        con = news_sources.extract_consensus(
            headline="New trade measures announced",
            all_titles=[
                "New trade measures announced",
                "EU tariffs target US steel sector",
            ],
            sources=[self._src("BBC World", "high"), self._src("Al Jazeera", "medium")],
            agreement="consistent",
        )
        # "steel" only appears in the second title
        self.assertEqual(con["sector"], "metals")
        self.assertIn("European Union", con["actors"])


class TestClusterConsensusIntegration(unittest.TestCase):
    """cluster_headlines() returns a consensus dict per cluster."""

    def _rec(self, title, source="local", pub="2026-04-01T12:00:00", url=""):
        return {"title": title, "source": source, "published_at": pub, "url": url}

    def test_cluster_has_consensus_field(self):
        records = [self._rec("EU tariffs on US steel", "BBC World")]
        clusters = news_sources.cluster_headlines(records)
        self.assertIn("consensus", clusters[0])
        self.assertIsInstance(clusters[0]["consensus"], dict)

    def test_consensus_actors_populated(self):
        records = [
            self._rec("EU imposes retaliatory tariffs on US steel", "BBC World"),
            self._rec("EU announces retaliatory tariffs on US steel imports", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        con = clusters[0]["consensus"]
        self.assertIn("European Union", con["actors"])
        self.assertIn("United States", con["actors"])
        self.assertEqual(con["action"], "tariffs")
        self.assertEqual(con["sector"], "metals")


class TestBuildEvidence(unittest.TestCase):
    """Tests for _build_evidence() and evidence in cluster output."""

    def _rec(self, title, source="local", pub="2026-04-01T12:00:00"):
        return {"title": title, "source": source, "published_at": pub, "url": ""}

    def test_single_source_returns_one_item(self):
        recs = [self._rec("EU tariffs on steel", "BBC World")]
        ev = news_sources._build_evidence(recs, "EU tariffs on steel", "consistent")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["source"], "BBC World")

    def test_ordered_by_tier_then_recency(self):
        recs = [
            self._rec("EU tariffs imposed on steel", "local", pub="2026-04-02T10:00:00"),
            self._rec("EU tariffs on steel imports", "Al Jazeera", pub="2026-04-01T08:00:00"),
            self._rec("EU announces tariffs on steel", "BBC World", pub="2026-04-01T09:00:00"),
        ]
        ev = news_sources._build_evidence(recs, "EU tariffs on steel", "consistent")
        # BBC (high) first, then Al Jazeera (medium), then local (low)
        self.assertEqual(ev[0]["source"], "BBC World")
        self.assertEqual(ev[1]["source"], "Al Jazeera")
        self.assertEqual(ev[2]["source"], "local")

    def test_recency_tiebreak_within_same_tier(self):
        recs = [
            self._rec("EU tariffs round one", "BBC World", pub="2026-04-01T08:00:00"),
            self._rec("EU tariffs round two", "The Guardian World", pub="2026-04-02T10:00:00"),
        ]
        ev = news_sources._build_evidence(recs, "EU tariffs", "consistent")
        # Both high tier — Guardian World is newer, should come first
        self.assertEqual(ev[0]["source"], "The Guardian World")
        self.assertEqual(ev[1]["source"], "BBC World")

    def test_capped_at_three(self):
        recs = [
            self._rec("Steel tariffs v1", "BBC World", pub="2026-04-01T08:00:00"),
            self._rec("Steel tariffs v2", "Al Jazeera", pub="2026-04-01T09:00:00"),
            self._rec("Steel tariffs v3", "The Guardian", pub="2026-04-01T10:00:00"),
            self._rec("Steel tariffs v4", "local", pub="2026-04-01T11:00:00"),
        ]
        ev = news_sources._build_evidence(recs, "Steel tariffs", "consistent")
        self.assertLessEqual(len(ev), 3)

    def test_mixed_agreement_flags_divergent(self):
        recs = [
            self._rec("EU imposes retaliatory tariffs on US steel", "BBC World"),
            self._rec("Something completely different about trade talks", "Al Jazeera"),
        ]
        ev = news_sources._build_evidence(
            recs, "EU imposes retaliatory tariffs on US steel", "mixed"
        )
        notes = [e["note"] for e in ev if e["note"]]
        self.assertTrue(any("framing differs" in n for n in notes))

    def test_consistent_agreement_no_note(self):
        recs = [
            self._rec("EU tariffs on steel imports", "BBC World"),
            self._rec("EU announces tariffs on steel imports", "Al Jazeera"),
        ]
        ev = news_sources._build_evidence(
            recs, "EU tariffs on steel imports", "consistent"
        )
        notes = [e["note"] for e in ev if e["note"]]
        self.assertEqual(notes, [])

    def test_deduplicates_by_source(self):
        recs = [
            self._rec("Steel tariffs v1", "BBC World", pub="2026-04-01T08:00:00"),
            self._rec("Steel tariffs v2", "BBC World", pub="2026-04-01T10:00:00"),
        ]
        ev = news_sources._build_evidence(recs, "Steel tariffs", "consistent")
        self.assertEqual(len(ev), 1)

    def test_evidence_present_in_cluster_output(self):
        records = [
            self._rec("EU imposes retaliatory tariffs on US steel", "BBC World"),
            self._rec("EU announces retaliatory tariffs on US steel imports", "Al Jazeera"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertIn("evidence", clusters[0])
        self.assertGreaterEqual(len(clusters[0]["evidence"]), 1)


class TestNormalizeTimestamp(unittest.TestCase):
    """Tests for _normalize_timestamp — mixed date format normalization."""

    def test_iso_passthrough(self):
        self.assertEqual(
            news_sources._normalize_timestamp("2026-04-05T14:30:00"),
            "2026-04-05T14:30:00",
        )

    def test_iso_with_timezone(self):
        result = news_sources._normalize_timestamp("2026-04-05T14:30:00+00:00")
        self.assertEqual(result, "2026-04-05T14:30:00+00:00")  # fast-path keeps it

    def test_rfc2822(self):
        result = news_sources._normalize_timestamp("Sat, 05 Apr 2026 10:30:00 GMT")
        self.assertEqual(result, "2026-04-05T10:30:00")

    def test_rfc2822_with_offset(self):
        result = news_sources._normalize_timestamp("Sat, 05 Apr 2026 10:30:00 +0000")
        self.assertEqual(result, "2026-04-05T10:30:00")

    def test_date_only(self):
        result = news_sources._normalize_timestamp("2026-04-05")
        self.assertEqual(result, "2026-04-05T00:00:00")

    def test_long_month_name(self):
        result = news_sources._normalize_timestamp("April 5, 2026")
        self.assertEqual(result, "2026-04-05T00:00:00")

    def test_short_month_name(self):
        result = news_sources._normalize_timestamp("Apr 5, 2026")
        self.assertEqual(result, "2026-04-05T00:00:00")

    def test_day_first_long_month(self):
        result = news_sources._normalize_timestamp("5 April 2026")
        self.assertEqual(result, "2026-04-05T00:00:00")

    def test_empty_string(self):
        self.assertEqual(news_sources._normalize_timestamp(""), "")

    def test_none_like_whitespace(self):
        self.assertEqual(news_sources._normalize_timestamp("   "), "")

    def test_unparseable_returns_original(self):
        self.assertEqual(
            news_sources._normalize_timestamp("not a date"),
            "not a date",
        )

    def test_make_record_normalizes(self):
        rec = news_sources._make_record(
            "test", "Headline", "Sat, 05 Apr 2026 10:30:00 GMT"
        )
        self.assertEqual(rec["published_at"], "2026-04-05T10:30:00")


class TestMixedTimestampOrdering(unittest.TestCase):
    """Confirm mixed-format timestamps sort chronologically after normalization."""

    def _rec(self, title, source="local", pub="", url=""):
        return news_sources._make_record(source, title, pub, url)

    def test_fetch_all_orders_mixed_formats_chronologically(self):
        """Records with different raw date formats should end up newest-first."""
        records = [
            self._rec("Old story", pub="April 1, 2026"),
            self._rec("Middle story", pub="2026-04-03T08:00:00"),
            self._rec("New story", pub="Sat, 05 Apr 2026 10:30:00 GMT"),
        ]
        # Sort the same way fetch_all does
        records.sort(key=lambda r: r["published_at"] or "", reverse=True)
        self.assertIn("New", records[0]["title"])
        self.assertIn("Middle", records[1]["title"])
        self.assertIn("Old", records[2]["title"])

    def test_cluster_published_at_picks_newest_across_formats(self):
        """Cluster timestamp should be the most recent regardless of input format."""
        records = [
            self._rec(
                "EU steel tariffs escalation confirmed", "BBC World",
                pub="Sat, 05 Apr 2026 12:00:00 GMT",
            ),
            self._rec(
                "EU steel tariffs escalation reported", "Al Jazeera",
                pub="April 1, 2026",
            ),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        # Newest is Apr 5 — the BBC story
        self.assertTrue(clusters[0]["published_at"].startswith("2026-04-05"))


class TestIsRelevant(unittest.TestCase):
    """is_relevant() should pass geopolitical/policy/trade headlines
    and reject lifestyle, sports, entertainment, etc."""

    # ── Should pass ──

    def test_tariff_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "EU imposes retaliatory tariffs on US steel"))

    def test_sanctions_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "US sanctions Russian oligarchs over Ukraine invasion"))

    def test_energy_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "OPEC agrees to production cut as oil prices fall"))

    def test_central_bank_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Federal Reserve signals rate cut amid recession fears"))

    def test_defense_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Germany ramps up defence spending in NATO push"))

    def test_trade_deal_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "US and China reach preliminary trade deal"))

    def test_shipping_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Red Sea shipping disruptions push freight costs higher"))

    def test_semiconductor_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "TSMC expands chip production amid semiconductor shortage"))

    def test_inflation_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Inflation rises to 4.2% as food prices surge"))

    def test_fiscal_policy_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Congress passes $1.2 trillion spending package"))

    def test_currency_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Dollar weakens against euro on trade uncertainty"))

    def test_military_escalation(self):
        self.assertTrue(news_sources.is_relevant(
            "Missile strikes hit Kyiv as conflict escalates"))

    def test_supply_chain_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Global supply chain disruptions worsen after port closures"))

    def test_market_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Stock market plunges on recession fears"))

    def test_diplomatic_headline(self):
        self.assertTrue(news_sources.is_relevant(
            "Diplomatic talks between India and Pakistan resume"))

    # ── Should reject ──

    def test_rejects_sports(self):
        self.assertFalse(news_sources.is_relevant(
            "Manchester United signs new striker for record fee"))

    def test_rejects_entertainment(self):
        self.assertFalse(news_sources.is_relevant(
            "Taylor Swift announces new world tour dates"))

    def test_rejects_lifestyle(self):
        self.assertFalse(news_sources.is_relevant(
            "Best recipes for a summer barbecue"))

    def test_rejects_celebrity(self):
        self.assertFalse(news_sources.is_relevant(
            "Royal family attends charity gala in London"))

    def test_rejects_weather(self):
        self.assertFalse(news_sources.is_relevant(
            "Sunny skies expected across the southeast this weekend"))

    def test_rejects_local_crime(self):
        self.assertFalse(news_sources.is_relevant(
            "Police investigate robbery at downtown convenience store"))

    def test_rejects_human_interest(self):
        self.assertFalse(news_sources.is_relevant(
            "Dog rescued from well after three days"))

    def test_rejects_tech_product(self):
        self.assertFalse(news_sources.is_relevant(
            "Apple unveils new iPhone with improved camera"))

    def test_case_insensitive(self):
        self.assertTrue(news_sources.is_relevant(
            "SANCTIONS IMPOSED ON RUSSIAN BANKS"))

    def test_stem_matching(self):
        """Keyword 'sanction' should match 'sanctioned', 'sanctions'."""
        self.assertTrue(news_sources.is_relevant(
            "Several companies were sanctioned by the Treasury"))


class TestRelevanceFilterInFetchAll(unittest.TestCase):
    """fetch_all should drop irrelevant headlines before returning."""

    def test_irrelevant_headlines_filtered_out(self):
        items = [
            {"title": "EU imposes tariffs on US steel", "source": "local"},
            {"title": "Dog rescued from well after three days", "source": "local"},
            {"title": "Best recipes for summer barbecue", "source": "local"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 1)
            self.assertIn("tariffs", result[0]["title"])
        finally:
            os.remove(path)

    def test_all_relevant_headlines_kept(self):
        items = [
            {"title": "OPEC announces production cut", "source": "local"},
            {"title": "Federal Reserve holds interest rate steady", "source": "local"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 2)
        finally:
            os.remove(path)

    def test_all_irrelevant_returns_empty(self):
        items = [
            {"title": "Football scores from the weekend", "source": "local"},
            {"title": "New restaurant opens in Brooklyn", "source": "local"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            result, _ = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 0)
        finally:
            os.remove(path)


class TestFeedSelection(unittest.TestCase):
    """Feed configuration should target narrow sections."""

    def test_no_top_level_all_xml_feeds(self):
        """No feed should point to a site's main /all.xml or top-level feed."""
        for feed in news_sources.DEFAULT_FEEDS:
            self.assertNotIn("/all.xml", feed["url"],
                             f"{feed['name']} uses overly broad /all.xml feed")

    def test_all_feeds_have_name_and_url(self):
        for feed in news_sources.DEFAULT_FEEDS:
            self.assertIn("name", feed)
            self.assertIn("url", feed)
            self.assertTrue(feed["name"])
            self.assertTrue(feed["url"].startswith("http"))

    def test_all_default_feeds_have_tier(self):
        """Every default feed name should appear in the source-tier map."""
        for feed in news_sources.DEFAULT_FEEDS:
            tier = news_sources.source_tier(feed["name"])
            self.assertIn(tier, ("high", "medium"),
                          f"{feed['name']} has unexpected tier '{tier}'")


if __name__ == "__main__":
    unittest.main()
