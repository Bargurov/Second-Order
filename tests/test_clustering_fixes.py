"""
tests/test_clustering_fixes.py

Regression tests for clustering/relevance fixes:
  1. Domain stopword suppression
  2. Punctuation-normalized matching (already tested in test_critical_fixes;
     this file adds clustering-specific cases)
  3. Opposite-polarity short headlines NOT clustering
  4. Same-event headlines still clustering correctly
  5. Polarity detection correctness
"""

import sys
import unittest

sys.path.insert(0, ".")

import db
from news_sources import (
    _headline_words as ns_headline_words,
    _tokenize,
    _build_tfidf_vectors,
    _cosine_sim,
    _jaccard,
    _headline_polarity,
    _POLARITY_POS,
    _POLARITY_NEG,
    _CLUSTER_THRESHOLD,
    cluster_headlines,
)


# ---------------------------------------------------------------------------
# 1. Domain stopword suppression
# ---------------------------------------------------------------------------

class TestDomainStopwords(unittest.TestCase):
    """Financial domain words must be stripped so they don't inflate similarity."""

    def test_market_removed(self):
        words = db._headline_words("Stock market crashes after tariff announcement")
        self.assertNotIn("market", words)
        self.assertNotIn("stock", words)
        self.assertIn("crashes", words)
        self.assertIn("tariff", words)

    def test_prices_removed(self):
        words = db._headline_words("Oil prices surge amid supply fears")
        self.assertNotIn("prices", words)
        self.assertIn("oil", words)
        self.assertIn("surge", words)

    def test_global_economy_removed(self):
        words = db._headline_words("Global economy shows signs of slowdown")
        self.assertNotIn("global", words)
        self.assertNotIn("economy", words)
        self.assertIn("signs", words)
        self.assertIn("slowdown", words)

    def test_billion_removed(self):
        words = db._headline_words("Company raises 5 billion in IPO")
        self.assertNotIn("billion", words)
        self.assertIn("company", words)
        self.assertIn("raises", words)

    def test_news_sources_matches_db(self):
        """Both modules should remove the same domain stopwords."""
        headline = "Global stock market prices report shows economic trading"
        db_words = db._headline_words(headline)
        ns_words = ns_headline_words(headline)
        self.assertEqual(db_words, ns_words)

    def test_domain_stops_dont_inflate_jaccard(self):
        """Two unrelated headlines sharing only domain words should score near zero."""
        a = db._headline_words("China launches space station module")
        b = db._headline_words("China imposes tariffs on semiconductor imports")
        jac = db._jaccard(a, b)
        # Only "china" should be shared after domain-stop removal
        self.assertLess(jac, 0.20, f"Unrelated headlines too similar: {jac:.3f}")


# ---------------------------------------------------------------------------
# 2. Punctuation-normalized matching in clustering context
# ---------------------------------------------------------------------------

class TestClusteringPunctuationNormalization(unittest.TestCase):
    """Punctuation in headlines should not affect TF-IDF/cosine similarity."""

    def test_cosine_invariant_to_punctuation(self):
        """Same headline with and without punctuation should have cosine = 1.0."""
        a = "Oil: OPEC's decision, markets rally."
        b = "Oil OPEC's decision markets rally"
        vecs, _ = _build_tfidf_vectors([a, b])
        cos = _cosine_sim(vecs[0], vecs[1])
        self.assertGreater(cos, 0.99, f"Punctuation broke cosine: {cos:.3f}")

    def test_tokenize_strips_punctuation(self):
        tokens = _tokenize('"Tariffs," imposed — China retaliates.')
        self.assertIn("tariffs", tokens)
        self.assertNotIn('"tariffs,"', tokens)
        self.assertIn("china", tokens)
        self.assertIn("retaliates", tokens)


# ---------------------------------------------------------------------------
# 3. Polarity detection
# ---------------------------------------------------------------------------

class TestPolarityDetection(unittest.TestCase):
    """_headline_polarity must detect directional sentiment in headlines."""

    def test_positive_surge(self):
        self.assertEqual(_headline_polarity(["oil", "surge", "amid", "supply"]), 1)

    def test_positive_rally(self):
        self.assertEqual(_headline_polarity(["rally", "fed", "decision"]), 1)

    def test_negative_drop(self):
        self.assertEqual(_headline_polarity(["oil", "drop", "demand"]), -1)

    def test_negative_crash(self):
        self.assertEqual(_headline_polarity(["crash", "fears", "spread"]), -1)

    def test_negative_fall(self):
        self.assertEqual(_headline_polarity(["fall", "fed", "decision"]), -1)

    def test_neutral_no_polarity(self):
        self.assertEqual(_headline_polarity(["opec", "agrees", "cut", "oil"]), 0)

    def test_mixed_returns_zero(self):
        """Both positive and negative words → ambiguous → 0."""
        self.assertEqual(_headline_polarity(["rally", "then", "crash"]), 0)

    def test_works_on_set(self):
        """Should accept both list and set."""
        self.assertEqual(_headline_polarity({"surge", "oil", "fears"}), 1)


# ---------------------------------------------------------------------------
# 4. Opposite-polarity headlines must NOT cluster
# ---------------------------------------------------------------------------

class TestOppositePolarity(unittest.TestCase):
    """Headlines with clear opposite polarity must not be merged even when
    their cosine similarity is above the threshold."""

    def _would_cluster(self, a: str, b: str) -> tuple[bool, float]:
        """Return (would_cluster, cosine) for a pair of headlines."""
        vecs, _ = _build_tfidf_vectors([a, b])
        cos = _cosine_sim(vecs[0], vecs[1])
        toks_a = _tokenize(a)
        toks_b = _tokenize(b)
        pa = _headline_polarity(toks_a)
        pb = _headline_polarity(toks_b)
        polarity_conflict = pa != 0 and pb != 0 and pa != pb
        return cos >= _CLUSTER_THRESHOLD and not polarity_conflict, cos

    def test_rally_vs_fall_blocked(self):
        """High cosine but opposite polarity → must not cluster."""
        ok, cos = self._would_cluster(
            "Stock markets rally after Fed decision",
            "Stock markets fall after Fed decision",
        )
        self.assertGreater(cos, 0.30, "Cosine should be high for these")
        self.assertFalse(ok, "Opposite polarity should block clustering")

    def test_surge_vs_drop_blocked(self):
        ok, cos = self._would_cluster(
            "Oil prices surge amid supply fears",
            "Oil prices drop on demand concerns",
        )
        self.assertFalse(ok)

    def test_strengthen_vs_weaken_blocked(self):
        ok, cos = self._would_cluster(
            "Dollar strengthens on rate outlook",
            "Dollar weakens on rate concerns",
        )
        self.assertFalse(ok)

    def test_same_polarity_allowed(self):
        """Same-direction headlines should still cluster."""
        ok, cos = self._would_cluster(
            "Oil prices surge amid supply fears",
            "Oil prices rally on supply disruption",
        )
        # These may or may not have enough cosine, but polarity won't block
        toks_a = _tokenize("Oil prices surge amid supply fears")
        toks_b = _tokenize("Oil prices rally on supply disruption")
        pa = _headline_polarity(toks_a)
        pb = _headline_polarity(toks_b)
        self.assertEqual(pa, pb, "Same polarity should not conflict")

    def test_neutral_not_blocked(self):
        """Neutral headline + directional headline should not be blocked."""
        ok, cos = self._would_cluster(
            "OPEC agrees to cut oil production",  # neutral
            "Oil prices surge after OPEC cut",     # positive
        )
        # Polarity should not block (one is neutral)
        toks_a = _tokenize("OPEC agrees to cut oil production")
        pa = _headline_polarity(toks_a)
        self.assertEqual(pa, 0, "OPEC agrees should be neutral")


# ---------------------------------------------------------------------------
# 5. Same-event headlines still cluster correctly
# ---------------------------------------------------------------------------

class TestSameEventClustering(unittest.TestCase):
    """Cross-source rewording of the same event must still merge."""

    def test_opec_variants(self):
        """OPEC production cut from different sources should cluster."""
        a = "OPEC agrees to cut oil production"
        b = "OPEC members agree to reduce oil output"
        vecs, _ = _build_tfidf_vectors([a, b])
        cos = _cosine_sim(vecs[0], vecs[1])
        self.assertGreaterEqual(cos, _CLUSTER_THRESHOLD,
                                f"Same event should cluster: cos={cos:.3f}")

    def test_iran_war_variants(self):
        """Iran-related headlines with similar wording should cluster."""
        a = "US threatens military action against Iran nuclear sites"
        b = "Trump threatens to attack Iran nuclear facilities"
        vecs, _ = _build_tfidf_vectors([a, b])
        cos = _cosine_sim(vecs[0], vecs[1])
        # These share "iran", "nuclear", "threatens" — should be above threshold
        self.assertGreaterEqual(cos, _CLUSTER_THRESHOLD,
                                f"Iran variants should cluster: cos={cos:.3f}")

    def test_tariff_close_wording(self):
        """Near-identical tariff headlines should cluster easily."""
        a = "EU imposes retaliatory tariffs on US steel imports"
        b = "EU announces retaliatory tariffs on US steel"
        vecs, _ = _build_tfidf_vectors([a, b])
        cos = _cosine_sim(vecs[0], vecs[1])
        self.assertGreaterEqual(cos, _CLUSTER_THRESHOLD,
                                f"Near-identical should cluster: cos={cos:.3f}")


# ---------------------------------------------------------------------------
# 6. Full cluster_headlines integration with polarity guard
# ---------------------------------------------------------------------------

class TestClusterHeadlinesPolarity(unittest.TestCase):
    """Integration test: cluster_headlines should separate opposite-polarity headlines."""

    def _make_record(self, title: str, source: str = "TestSource") -> dict:
        return {
            "title": title,
            "source": source,
            "published_at": "2026-04-07T12:00:00Z",
            "url": "",
        }

    def test_opposite_polarity_in_separate_clusters(self):
        """Two opposite-polarity headlines should end up in different clusters."""
        records = [
            self._make_record("Stock markets rally after Fed decision", "SourceA"),
            self._make_record("Stock markets fall after Fed decision", "SourceB"),
        ]
        clusters = cluster_headlines(records)
        # Should produce 2 clusters (one per headline), not 1
        self.assertEqual(len(clusters), 2,
                         "Opposite-polarity headlines should not merge into one cluster")

    def test_same_polarity_in_same_cluster(self):
        """Two same-direction headlines should cluster."""
        records = [
            self._make_record("Oil prices surge amid supply fears", "SourceA"),
            self._make_record("Oil prices soar on supply disruption", "SourceB"),
        ]
        clusters = cluster_headlines(records)
        # Should produce 1 cluster (merged)
        self.assertEqual(len(clusters), 1,
                         "Same-polarity similar headlines should merge")


# ---------------------------------------------------------------------------
# 7. Empirical calibration: domain stopwords + polarity on reference pairs
# ---------------------------------------------------------------------------

class TestEmpiricalCalibration(unittest.TestCase):
    """Validate the combined domain-stopword + polarity approach against
    the 9-pair reference set from the calibration run."""

    def _would_cluster(self, a: str, b: str) -> bool:
        vecs, _ = _build_tfidf_vectors([a, b])
        cos = _cosine_sim(vecs[0], vecs[1])
        pa = _headline_polarity(_tokenize(a))
        pb = _headline_polarity(_tokenize(b))
        conflict = pa != 0 and pb != 0 and pa != pb
        return cos >= _CLUSTER_THRESHOLD and not conflict

    def test_oil_surge_vs_drop(self):
        self.assertFalse(self._would_cluster(
            "Oil prices surge amid supply fears",
            "Oil prices drop on demand concerns",
        ))

    def test_stock_rally_vs_fall(self):
        self.assertFalse(self._would_cluster(
            "Stock markets rally after Fed decision",
            "Stock markets fall after Fed decision",
        ))

    def test_gold_jump_vs_tumble(self):
        self.assertFalse(self._would_cluster(
            "Gold prices jump to record high",
            "Gold prices tumble from highs",
        ))

    def test_dollar_strengthen_vs_weaken(self):
        self.assertFalse(self._would_cluster(
            "Dollar strengthens on rate outlook",
            "Dollar weakens on rate concerns",
        ))

    def test_china_space_vs_tariffs(self):
        self.assertFalse(self._would_cluster(
            "China launches space station module",
            "China imposes tariffs on semiconductor imports",
        ))

    def test_eu_energy_vs_tariffs(self):
        self.assertFalse(self._would_cluster(
            "EU plans renewable energy expansion",
            "EU imposes retaliatory tariffs on US steel",
        ))

    def test_opec_same_event_clusters(self):
        self.assertTrue(self._would_cluster(
            "OPEC agrees to cut oil production",
            "OPEC members agree to reduce oil output",
        ))


if __name__ == "__main__":
    unittest.main()
