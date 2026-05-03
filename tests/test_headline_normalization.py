"""
tests/test_headline_normalization.py

Focused tests for headline token normalization:
  1. Punctuation stripping (colons, quotes, periods, possessives)
  2. Singular/plural convergence (minimal suffix rules)
  3. Short-token safety (no mangling of 1-4 char words)
  4. Regression: clean matches must not break after normalization
  5. Parity between news_sources and db implementations
"""

import sys
import unittest

sys.path.insert(0, ".")

import db
from news_sources import (
    _normalize_token as ns_normalize,
    _headline_words as ns_headline_words,
    _tokenize,
    _build_tfidf_vectors,
    _cosine_sim,
    _jaccard,
    _headline_polarity,
    _CLUSTER_THRESHOLD,
)
from db import (
    _normalize_token as db_normalize,
    _headline_words as db_headline_words,
)


# ---------------------------------------------------------------------------
# 1. Punctuation stripping
# ---------------------------------------------------------------------------

class TestPunctuationNormalization(unittest.TestCase):
    """Punctuation must not prevent token matching."""

    def test_possessive_stripped(self):
        self.assertEqual(ns_normalize("Iran's"), "iran")
        self.assertEqual(ns_normalize("OPEC\u2019s"), "opec")

    def test_trailing_comma(self):
        self.assertEqual(ns_normalize("tariffs,"), "tariff")

    def test_leading_quote(self):
        self.assertEqual(ns_normalize('"Sanctions"'), "sanction")

    def test_internal_period_removed(self):
        """U.S. and US should produce the same token."""
        self.assertEqual(ns_normalize("U.S."), "us")
        self.assertEqual(ns_normalize("US"), "us")
        self.assertEqual(ns_normalize("U.K."), "uk")

    def test_hyphen_preserved(self):
        self.assertEqual(ns_normalize("multi-year"), "multi-year")
        self.assertEqual(ns_normalize("sell-off"), "sell-off")

    def test_colon_stripped(self):
        self.assertEqual(ns_normalize("Oil:"), "oil")

    def test_em_dash_stripped(self):
        # An em-dash glued to a word
        self.assertEqual(ns_normalize("tariffs\u2014"), "tariff")

    def test_headline_words_possessive_matches_bare(self):
        """'Iran's sanctions' and 'Iran sanctions' should share both tokens."""
        a = ns_headline_words("Iran's sanctions tighten")
        b = ns_headline_words("Iran sanctions tighten")
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# 2. Singular/plural convergence
# ---------------------------------------------------------------------------

class TestPluralNormalization(unittest.TestCase):
    """Minimal suffix rules should merge common singular/plural forms."""

    def test_simple_s(self):
        self.assertEqual(ns_normalize("sanctions"), "sanction")
        self.assertEqual(ns_normalize("tariffs"), "tariff")
        self.assertEqual(ns_normalize("gains"), "gain")

    def test_ies_to_y(self):
        self.assertEqual(ns_normalize("rallies"), "rally")
        self.assertEqual(ns_normalize("economies"), "economy")
        self.assertEqual(ns_normalize("facilities"), "facility")

    def test_sibilant_es(self):
        """Words where the plural adds -es to a sibilant stem."""
        self.assertEqual(ns_normalize("crashes"), "crash")
        self.assertEqual(ns_normalize("taxes"), "tax")
        self.assertEqual(ns_normalize("losses"), "loss")
        self.assertEqual(ns_normalize("launches"), "launch")
        self.assertEqual(ns_normalize("watches"), "watch")

    def test_non_sibilant_es(self):
        """Words ending in -es where only -s is the suffix."""
        self.assertEqual(ns_normalize("causes"), "cause")
        self.assertEqual(ns_normalize("increases"), "increase")
        self.assertEqual(ns_normalize("decreases"), "decrease")
        self.assertEqual(ns_normalize("phases"), "phase")

    def test_singular_unchanged(self):
        """Base forms must not be further mangled."""
        self.assertEqual(ns_normalize("sanction"), "sanction")
        self.assertEqual(ns_normalize("tariff"), "tariff")
        self.assertEqual(ns_normalize("crash"), "crash")
        self.assertEqual(ns_normalize("rally"), "rally")

    def test_headline_words_plural_matches_singular(self):
        a = ns_headline_words("EU imposes sanctions on Iran")
        b = ns_headline_words("EU imposes sanction on Iran")
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# 3. Short-token safety
# ---------------------------------------------------------------------------

class TestShortTokenSafety(unittest.TestCase):
    """Tokens <= 3 chars must NOT have suffix stripping applied.
    4-char words ending in -s (not -ss) DO normalize (cuts → cut)."""

    def test_four_char_stripped(self):
        """4-char plural words normalize to their singular form."""
        self.assertEqual(ns_normalize("cuts"), "cut")
        self.assertEqual(ns_normalize("bans"), "ban")
        self.assertEqual(ns_normalize("inks"), "ink")
        self.assertEqual(ns_normalize("gaps"), "gap")

    def test_three_char_untouched(self):
        self.assertEqual(ns_normalize("oil"), "oil")
        self.assertEqual(ns_normalize("fed"), "fed")
        self.assertEqual(ns_normalize("war"), "war")

    def test_ss_not_stripped(self):
        """Words ending in 'ss' should not lose their trailing s."""
        self.assertEqual(ns_normalize("gross"), "gross")
        self.assertEqual(ns_normalize("stress"), "stress")

    def test_empty_input(self):
        self.assertEqual(ns_normalize(""), "")
        self.assertEqual(ns_normalize("..."), "")


# ---------------------------------------------------------------------------
# 4. Regression: clean matches stable after normalization
# ---------------------------------------------------------------------------

class TestCleanMatchRegression(unittest.TestCase):
    """Headline pairs that clustered before must still cluster after."""

    def _cosine(self, a: str, b: str) -> float:
        vecs, _ = _build_tfidf_vectors([a, b])
        return _cosine_sim(vecs[0], vecs[1])

    def test_opec_variants_still_cluster(self):
        cos = self._cosine(
            "OPEC agrees to cut oil production",
            "OPEC members agree to reduce oil output",
        )
        self.assertGreaterEqual(cos, _CLUSTER_THRESHOLD)

    def test_iran_variants_still_cluster(self):
        cos = self._cosine(
            "US threatens military action against Iran nuclear sites",
            "Trump threatens to attack Iran nuclear facilities",
        )
        self.assertGreaterEqual(cos, _CLUSTER_THRESHOLD)

    def test_tariff_variants_still_cluster(self):
        cos = self._cosine(
            "EU imposes retaliatory tariffs on US steel imports",
            "EU announces retaliatory tariffs on US steel",
        )
        self.assertGreaterEqual(cos, _CLUSTER_THRESHOLD)

    def test_opposite_polarity_still_blocked(self):
        """Polarity detection must work on normalized tokens."""
        toks_a = _tokenize("Stock markets rally after Fed decision")
        toks_b = _tokenize("Stock markets fall after Fed decision")
        self.assertEqual(_headline_polarity(toks_a), 1)
        self.assertEqual(_headline_polarity(toks_b), -1)

    def test_unrelated_headlines_still_apart(self):
        cos = self._cosine(
            "China launches space station module",
            "China imposes tariffs on semiconductor imports",
        )
        self.assertLess(cos, _CLUSTER_THRESHOLD)

    def test_normalization_improves_agrees_agree_match(self):
        """'agrees' and 'agree' should now produce the same token."""
        a = ns_headline_words("OPEC agrees to cut output")
        b = ns_headline_words("OPEC members agree to cut output")
        # Both should contain 'agree' (not 'agrees' vs 'agree')
        self.assertIn("agree", a)
        self.assertIn("agree", b)

    def test_jaccard_improved_by_normalization(self):
        """Plural/possessive normalization should increase Jaccard overlap."""
        a = db_headline_words("Iran's sanctions target oil exports")
        b = db_headline_words("Iran sanctions target oil export")
        jac = db._jaccard(a, b)
        # All content tokens should now match after normalization
        self.assertEqual(a, b)
        self.assertAlmostEqual(jac, 1.0)


# ---------------------------------------------------------------------------
# 5. Parity: news_sources and db must produce identical results
# ---------------------------------------------------------------------------

class TestModuleParity(unittest.TestCase):

    def test_headline_words_match(self):
        for hl in [
            "Iran's sanctions hit oil markets",
            "EU imposes tariffs on U.S. steel",
            '"Breaking:" Fed crashes rates, rallies expected',
            "Global economy shows signs of slowdown",
        ]:
            with self.subTest(headline=hl):
                self.assertEqual(ns_headline_words(hl), db_headline_words(hl))

    def test_normalize_token_match(self):
        for tok in ["Iran's", "U.S.", "tariffs", "crashes", "rallies", "sell-off"]:
            with self.subTest(token=tok):
                self.assertEqual(ns_normalize(tok), db_normalize(tok))


if __name__ == "__main__":
    unittest.main()
