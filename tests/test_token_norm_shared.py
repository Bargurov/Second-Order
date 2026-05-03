"""
tests/test_token_norm_shared.py

Prove that db.py and news_clustering.py use the same normalization
from the single token_norm module.

  1) _tokenize and _headline_words produce the same tokens.
  2) Both call sites (db and clustering) resolve to the same functions.
  3) Normalization behavior is consistent: stemming, stopwords, possessives.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from token_norm import (
    _normalize_token,
    _headline_words,
    _tokenize,
    _STOP_WORDS,
)


# ---------------------------------------------------------------------------
# 1) _tokenize and _headline_words produce the same tokens
# ---------------------------------------------------------------------------

class TestTokenizeAndHeadlineWordsAligned(unittest.TestCase):

    def test_same_tokens_different_type(self):
        title = "US imposes tariffs on Chinese semiconductors"
        tokens = _tokenize(title)
        words = _headline_words(title)
        self.assertEqual(set(tokens), words)

    def test_order_preserved_in_tokenize(self):
        title = "OPEC cuts oil production sharply"
        tokens = _tokenize(title)
        self.assertIsInstance(tokens, list)
        self.assertEqual(tokens[0], "opec")

    def test_headline_words_is_set_of_tokenize(self):
        title = "Oil oil oil prices surge after OPEC decision"
        tokens = _tokenize(title)
        words = _headline_words(title)
        self.assertEqual(tokens.count("oil"), 3)
        self.assertIn("oil", words)
        self.assertEqual(set(tokens), words)

    def test_empty_title(self):
        self.assertEqual(_tokenize(""), [])
        self.assertEqual(_headline_words(""), set())

    def test_all_stopwords(self):
        title = "the a an in on at to for"
        self.assertEqual(_tokenize(title), [])
        self.assertEqual(_headline_words(title), set())


# ---------------------------------------------------------------------------
# 2) Both call sites resolve to the same functions
# ---------------------------------------------------------------------------

class TestCallSiteIdentity(unittest.TestCase):

    def test_db_uses_token_norm_headline_words(self):
        import db
        import token_norm
        self.assertIs(db._headline_words, token_norm._headline_words)

    def test_clustering_uses_token_norm_tokenize(self):
        import news_clustering
        import token_norm
        self.assertIs(news_clustering._tokenize, token_norm._tokenize)

    def test_clustering_uses_token_norm_headline_words(self):
        import news_clustering
        import token_norm
        self.assertIs(news_clustering._headline_words, token_norm._headline_words)

    def test_facade_reexports_tokenize(self):
        import news_sources
        import token_norm
        self.assertIs(news_sources._tokenize, token_norm._tokenize)


# ---------------------------------------------------------------------------
# 3) Normalization behavior is consistent
# ---------------------------------------------------------------------------

class TestNormalizationBehavior(unittest.TestCase):

    def test_plural_stemming(self):
        self.assertEqual(_normalize_token("tariffs"), "tariff")
        self.assertEqual(_normalize_token("sanctions"), "sanction")
        self.assertEqual(_normalize_token("rallies"), "rally")
        self.assertEqual(_normalize_token("crashes"), "crash")

    def test_possessive_stripping(self):
        self.assertEqual(_normalize_token("China's"), "china")
        self.assertEqual(_normalize_token("OPEC\u2019s"), "opec")

    def test_stopword_removal(self):
        for sw in ["the", "market", "global", "billion", "report"]:
            self.assertIn(sw, _STOP_WORDS)

    def test_short_words_not_mangled(self):
        self.assertEqual(_normalize_token("us"), "us")
        self.assertEqual(_normalize_token("gas"), "gas")
        self.assertEqual(_normalize_token("oil"), "oil")

    def test_case_insensitive(self):
        self.assertEqual(_normalize_token("TARIFFS"), "tariff")
        self.assertEqual(_normalize_token("Sanctions"), "sanction")

    def test_punctuation_stripped(self):
        self.assertEqual(_normalize_token("oil,"), "oil")
        self.assertEqual(_normalize_token("(crude)"), "crude")

    def test_headline_words_stems_in_context(self):
        words = _headline_words("US imposes tariffs on Chinese exports")
        self.assertIn("tariff", words)
        self.assertIn("export", words)
        self.assertNotIn("on", words)

    def test_tokenize_stems_in_context(self):
        tokens = _tokenize("OPEC cuts oil production")
        self.assertIn("cut", tokens)
        self.assertIn("oil", tokens)
        self.assertIn("production", tokens)


if __name__ == "__main__":
    unittest.main()
