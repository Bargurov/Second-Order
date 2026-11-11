"""Text rules for the committed thesis (thesis_rules): claim words, price-direction wording, figures held to sources."""
import unittest

from second_order import policy_research, thesis_rules

PRICE_TOKENS = ["upside", "up-side", "downside", "bullish", "bearish", "rally", "rallies", "overvalued",
                "undervalued", "overpriced", "underpriced", "price target", "target price", "fair value"]
AFTER_PRICE = ["rise", "rises", "rising", "rose", "risen", "fall", "falls", "falling", "fell", "fallen", "increase",
               "increased", "decrease", "declines", "climbs", "drops", "jumps", "surges", "soars", "spikes", "slumps",
               "plunges", "higher", "lower", "up", "down", "pressure", "tighten", "support", "gains"]
BEFORE_PRICE = ["higher", "lower", "rising", "falling", "upward", "downward", "pressure on", "support for", "tighter",
                "firmer", "weaker", "stronger"]


class PriceDirectionTests(unittest.TestCase):
    def test_every_atomic_token_is_refused(self):
        for token in PRICE_TOKENS:
            with self.subTest(token=token), self.assertRaises(thesis_rules.ThesisRefused):
                thesis_rules.author_text(f"The view sees {token.upper()} here.", "x")

    def test_direction_after_the_price_within_four_words_is_refused(self):
        for word in AFTER_PRICE:
            with self.subTest(word=word), self.assertRaises(thesis_rules.ThesisRefused):
                thesis_rules.author_text(f"The copper price will likely {word} next year.", "x")

    def test_direction_before_the_price_within_four_words_is_refused(self):
        for word in BEFORE_PRICE:
            with self.subTest(word=word), self.assertRaises(thesis_rules.ThesisRefused):
                thesis_rules.author_text(f"This points to {word} copper prices.", "x")

    def test_neutral_balance_and_exposure_wording_passes(self):
        for text in ["Mine supply grew more slowly than demand.", "The monthly price is shown as a record.",
                     "A change of ten cents a pound changes operating income.", "The gap is a deficit.",
                     "Demand from grids rises in the stated projection."]:
            self.assertEqual(thesis_rules.author_text(text, "x"), text)

    def test_claim_words_are_refused_too(self):
        with self.assertRaises(thesis_rules.ThesisRefused):
            thesis_rules.author_text("This proves the thesis.", "x")

    def test_the_message_names_the_matched_text(self):
        with self.assertRaises(thesis_rules.ThesisRefused) as caught:
            thesis_rules.author_text("The price will rise.", "view.note")
        self.assertIn("price will rise", str(caught.exception))
        self.assertIn("view.note", str(caught.exception))


class ShapeTests(unittest.TestCase):
    def test_refused_is_a_500_value_error_with_the_exact_message(self):
        error = thesis_rules.invalid("a.b", "bad")
        self.assertIsInstance(error, ValueError)
        self.assertEqual(error.status, 500)
        self.assertEqual(str(error), "The thesis file is invalid (a.b: bad); nothing is served")

    def test_check_passes_or_raises(self):
        self.assertIsNone(thesis_rules.check(True, "x", "y"))
        with self.assertRaises(thesis_rules.ThesisRefused):
            thesis_rules.check(False, "x", "y")

    def test_shape_rules_apply_to_both_text_functions(self):
        for function in (lambda v: thesis_rules.author_text(v, "x", 10), lambda v: thesis_rules.free_text(v, "x", 10)):
            for bad in [None, 3, "", " a", "a ", "a\nb", "a\tb", "x" * 11]:
                with self.subTest(bad=bad), self.assertRaises(thesis_rules.ThesisRefused):
                    function(bad)
            self.assertEqual(function("x" * 10), "x" * 10)

    def test_free_text_runs_no_scans(self):
        text = "This proves a bullish rally; the price will rise."
        self.assertEqual(thesis_rules.free_text(text, "x", 100), text)

    def test_default_author_limit_is_900(self):
        thesis_rules.author_text("a" * 900, "x")
        with self.assertRaises(thesis_rules.ThesisRefused):
            thesis_rules.author_text("a" * 901, "x")

    def test_banned_list_is_reused_not_copied(self):
        self.assertIs(thesis_rules.BANNED, policy_research.BANNED)


class FigureRuleTests(unittest.TestCase):
    def test_a_figure_not_in_the_cited_text_is_refused(self):
        with self.assertRaises(thesis_rules.ThesisRefused):
            thesis_rules.held_to("about 25,000 kt", "23,000", "x")

    def test_figures_in_the_cited_text_pass(self):
        self.assertIsNone(thesis_rules.held_to("about 23,000 kt", "a gap of 23,000 kt", "x"))
        self.assertIsNone(thesis_rules.held_to("no figures here", "", "x"))

    def test_plain_notes_state_no_figures(self):
        with self.assertRaises(thesis_rules.ThesisRefused):
            thesis_rules.no_figures("since 2021", "x")
        self.assertEqual(thesis_rules.no_figures("since the last edition", "x"), "since the last edition")


class VocabularyTests(unittest.TestCase):
    def test_vocabularies(self):
        self.assertEqual(thesis_rules.CONFIDENCE, ("low", "medium", "high"))
        self.assertEqual(thesis_rules.STATEMENT_STATUSES, {
            "stated": "Source statement", "interpretation": "Author's reading",
            "not_stated": "Not stated in the sources"})
        self.assertEqual(thesis_rules.REASON_STATES, ("strengthening", "weakening", "unchanged"))
        self.assertEqual(thesis_rules.RISK_STATES, ("materialising", "receding", "unchanged", "not_tracked"))
        self.assertEqual(thesis_rules.CONDITION_STATES, ("happened", "not_happened"))
        self.assertIs(thesis_rules.SOURCE_STATES, policy_research.PUBLICATION_STATES)
        self.assertIs(thesis_rules.ELEMENT_STATES, policy_research.COMPARISON_STATES)


if __name__ == "__main__":
    unittest.main()
