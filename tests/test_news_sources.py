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

    def test_deduplicates_identical_titles(self):
        dupes = [
            {"title": "Same headline", "source": "A"},
            {"title": "Same headline", "source": "B"},
            {"title": "Different one", "source": "C"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(dupes, f)
            path = f.name
        try:
            # No RSS feeds — local only
            result = news_sources.fetch_all(local_path=path, feeds=[])
            titles = [r["title"] for r in result]
            self.assertEqual(titles.count("Same headline"), 1)
            self.assertEqual(len(result), 2)
        finally:
            os.remove(path)

    def test_deduplicates_despite_punctuation_differences(self):
        dupes = [
            {"title": "US imposes tariffs!", "source": "A", "published_at": "2026-01-02"},
            {"title": "US Imposes Tariffs",  "source": "B", "published_at": "2026-01-01"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(dupes, f)
            path = f.name
        try:
            result = news_sources.fetch_all(local_path=path, feeds=[])
            self.assertEqual(len(result), 1)
        finally:
            os.remove(path)

    def test_sorted_newest_first(self):
        items = [
            {"title": "Old", "published_at": "2026-01-01"},
            {"title": "New", "published_at": "2026-03-15"},
            {"title": "Mid", "published_at": "2026-02-10"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(items, f)
            path = f.name
        try:
            result = news_sources.fetch_all(local_path=path, feeds=[])
            titles = [r["title"] for r in result]
            self.assertEqual(titles, ["New", "Mid", "Old"])
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
            result = news_sources.load_rss(feeds=[])
        self.assertEqual(result, [])

    def test_parses_mock_feed(self):
        mock_feed = MagicMock()
        mock_feed.entries = [_make_mock_entry("Test RSS Headline", "http://example.com/article")]

        mock_fp = MagicMock()
        mock_fp.parse.return_value = mock_feed

        with patch.dict(sys.modules, {"feedparser": mock_fp}):
            result = news_sources.load_rss(feeds=[{"name": "TestFeed", "url": "http://fake"}])

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
            result = news_sources.load_rss(feeds=[
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
            result = news_sources.load_rss(feeds=[{"name": "F", "url": "http://f"}])

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
            result = news_sources.load_rss(feeds=[
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
        self.assertIn("The Guardian World", names)

    def test_wsj_is_in_default_feeds(self):
        names = [f["name"] for f in news_sources.DEFAULT_FEEDS]
        self.assertIn("WSJ World News", names)


class TestSourceTier(unittest.TestCase):

    def test_known_high_tier(self):
        self.assertEqual(news_sources.source_tier("BBC World"), "high")
        self.assertEqual(news_sources.source_tier("The Guardian World"), "high")
        self.assertEqual(news_sources.source_tier("WSJ World News"), "high")

    def test_known_medium_tier(self):
        self.assertEqual(news_sources.source_tier("Al Jazeera"), "medium")

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

    def test_published_at_is_earliest(self):
        records = [
            self._rec("Steel tariffs update", "BBC World", pub="2026-04-02T10:00:00"),
            self._rec("EU steel tariffs announced update", "Al Jazeera", pub="2026-04-01T08:00:00"),
        ]
        clusters = news_sources.cluster_headlines(records)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["published_at"], "2026-04-01T08:00:00")

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


if __name__ == "__main__":
    unittest.main()
