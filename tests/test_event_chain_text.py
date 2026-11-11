import json
import unittest
from pathlib import Path

from second_order import event_chain_text, thesis_rules_he

# One table of owner texts and what is shown while a basis document fails; the page's tests read it too.
MASKING = Path(__file__).resolve().parents[1] / "frontend" / "tests" / "fixtures" / "event-chain-masking.json"


class HebrewRules(unittest.TestCase):
    REFUSED = {"האירוע גרם לירידה": "גרם", "זה מוכיח את הטענה": "מוכיח", "קשר סיבתי": "סיבתי",
               "המלצת קנייה": "המלצת", "תחזית לשנה הבאה": "תחזית", "ההיצע אינו קיים": "אינו קיים",
               "האירוע מאשר את התזה": "מאשר את התזה", "שקנה מניות": "שקנה"}
    PRICE = ["המחיר יעלה בשנה הבאה", "עליית מחיר הנחושת", "מחיר הנחושת השנתי גבוה יותר", "מחיר יעד", "שווי הוגן"]
    PASSES = ["סיבה חזקה בתזה", "מכירות הנחושת של החברה", "הדירקטוריון אישר את ההרחבה", "שינוי במחיר",
              "מה המחיר עשה אחר כך", "תומך בתזה", "ביטול הרישיון", "החברה צופה חזרה לפעילות", "מקנה יתרון"]

    def test_each_hebrew_row_refuses_and_passes(self):
        for text, word in self.REFUSED.items():
            self.assertEqual(thesis_rules_he.claim_word(text), word, text)
        for text in self.PRICE:
            self.assertIsNotNone(thesis_rules_he.price_direction(text), text)
        for text in self.PASSES:
            self.assertIsNone(event_chain_text.rule_problem(text), text)

    def test_hebrew_rules_see_through_niqqud_maqaf_and_prefixes(self):
        self.assertEqual(thesis_rules_he.claim_word("הַמַּפֹּלֶת גָּרַם"), "גרם")
        self.assertEqual(thesis_rules_he.claim_word("ושגרם"), "ושגרם")
        self.assertIsNotNone(thesis_rules_he.price_direction("המחיר־יעלה"))

    def test_english_rules_unchanged(self):
        self.assertIsNotNone(event_chain_text.rule_problem("prices rise after it"))
        self.assertIsNotNone(event_chain_text.rule_problem("this caused the fall"))
        self.assertIsNone(event_chain_text.rule_problem("a change in the price"))


class Overlap(unittest.TestCase):
    QUOTE = "Lower milling rates and production volumes in 2025, compared to 2024 and 2023"

    def test_six_words_refused_five_pass_case_and_punctuation_ignored(self):
        self.assertEqual(event_chain_text.overlap("LOWER milling rates, and production volumes!", [self.QUOTE]),
                         "lower milling rates and production volumes")
        self.assertIsNone(event_chain_text.overlap("lower milling rates and production", [self.QUOTE]))

    def test_a_pointed_copy_of_six_quoted_hebrew_words_is_refused(self):
        quote = "החברה צופה חזרה מלאה של הייצור במחצית השנייה של השנה"
        six = "חזרה מלאה של הייצור במחצית השנייה"
        # A patah under every letter, and a maqaf in place of the first space.
        pointed = "".join(c + "ַ" if "א" <= c <= "ת" else c for c in six).replace(" ", "־", 1)
        self.assertNotIn(six, pointed)
        self.assertEqual(event_chain_text.overlap(pointed, [quote]), six)
        with self.assertRaises(event_chain_text.TextRefused):
            event_chain_text.owner_notes(pointed, quotes=[quote], steps=4)
        with self.assertRaises(event_chain_text.TextRefused):
            event_chain_text.owner_line(pointed, quotes=[quote], allowed="", steps=4)
        self.assertIsNone(event_chain_text.overlap(pointed.rsplit(" ", 1)[0], [quote]))  # Five words pass.
        presented = six.replace("ש", "שׁ")  # SHIN WITH SHIN DOT, a presentation form NFKC takes apart.
        self.assertEqual(event_chain_text.overlap(presented, [quote]), six)


class Figures(unittest.TestCase):
    def test_step_references_are_not_figures_and_are_never_masked(self):
        text = "the company expects 85% in 2026, see step 3 and שלב 2"
        self.assertEqual(event_chain_text.figure_runs(text, steps=4), {"85", "2026"})
        self.assertEqual(event_chain_text.masked(text, steps=4),
                         "the company expects [figure withheld] in [figure withheld], see step 3 and שלב 2")
        self.assertEqual(event_chain_text.masked("see step 9", steps=4), "see step [figure withheld]")

    def test_hebrew_step_references_take_up_to_three_prefix_letters(self):
        text = "ראו בשלב 2, ובשלב 3 ושבשלבים 4"
        self.assertEqual(event_chain_text.figure_runs(text, steps=4), set())
        self.assertEqual(event_chain_text.masked(text, steps=4), text)
        self.assertEqual(event_chain_text.owner_line(text, quotes=[], allowed="", steps=4), text)
        self.assertEqual(event_chain_text.figure_runs("ראו בשלב 9", steps=4), {"9"})
        self.assertEqual(event_chain_text.masked("ראו בשלב 9", steps=4), "ראו בשלב [figure withheld]")
        with self.assertRaises(event_chain_text.TextRefused):
            event_chain_text.owner_line("ראו בשלב 9", quotes=[], allowed="", steps=4)
        # Four prefix letters are not a step reference.
        self.assertEqual(event_chain_text.figure_runs("ושבכשלב 2", steps=4), {"2"})

    def test_the_server_masks_every_text_of_the_table_as_the_page_does(self):
        cases = json.loads(MASKING.read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            with self.subTest(text=ascii(case["text"])):
                self.assertEqual(event_chain_text.masked(case["text"], case["steps"]), case["masked"])

    def test_a_digit_of_another_script_is_refused_in_the_line_and_in_the_notes(self):
        # "see step ٠3" once read as step 3 on the server and as a bare 3 on the page; neither side reads such digits
        # now, so the owner's text may not hold one.
        for text in ("see step ٠3", "made ٨٥% there", "step ３"):
            for save in (lambda: event_chain_text.owner_line(text, quotes=[], allowed="", steps=4),
                         lambda: event_chain_text.owner_notes(text, quotes=[], steps=4)):
                with self.subTest(text=ascii(text)):
                    with self.assertRaises(event_chain_text.TextRefused) as raised:
                        save()
                    self.assertEqual(raised.exception.status, 422)
                    self.assertIn("the digits 0 to 9", raised.exception.message)
        self.assertEqual(event_chain_text.owner_line("see step 3", quotes=[], allowed="", steps=4), "see step 3")
        self.assertEqual(event_chain_text.owner_notes("see step 3 of 4", quotes=[], steps=4), "see step 3 of 4")

    def test_the_line_is_one_line_without_line_or_paragraph_separators(self):
        for mark in (" ", " ", "\x85", "\x7f", "\n"):
            with self.subTest(mark=hex(ord(mark))), self.assertRaises(event_chain_text.TextRefused) as raised:
                event_chain_text.owner_line(f"one part{mark}another part", quotes=[], allowed="", steps=4)
            self.assertIn("one line", raised.exception.message)

    def test_owner_line_rules(self):
        quotes = ["approximately 85% of its total production ... in the second half of 2026."]
        ok = event_chain_text.owner_line("expects 85% in 2026, step 3", quotes=quotes, allowed=quotes[0], steps=4)
        self.assertEqual(ok, "expects 85% in 2026, step 3")
        for bad in ("expects 90% in 2026", "x" * 281, "two\nlines", ""):
            with self.assertRaises(event_chain_text.TextRefused) as raised:
                event_chain_text.owner_line(bad, quotes=quotes, allowed=quotes[0], steps=4)
            self.assertEqual(raised.exception.status, 422)

    def test_the_owners_line_is_free_of_the_claim_word_and_price_direction_lists(self):
        """The owner's decision of 2026-11-10: the two word lists bind the assistant's text, not the owner's own line.
        Each of these was refused before; the rules that protect sources still hold."""
        # Marked test values: wording of the kinds the lists refuse, never a view of the owner's.
        for line in ("TEST VALUE: the price will rise", "TEST VALUE: a higher copper price helps the cash flow",
                     "ערך בדיקה: האירוע גרם", "TEST VALUE: the company's forecast moved later",
                     "ערך בדיקה: ריכוז הזהב ירד, בגרם לטון", "ערך בדיקה: מחיר הנחושת יעלה"):
            self.assertIsNotNone(event_chain_text.rule_problem(line), line)  # Still refused in assistant text.
            self.assertEqual(event_chain_text.owner_line(line, quotes=[], allowed="", steps=4), line)
        with self.assertRaises(event_chain_text.TextRefused) as raised:
            event_chain_text.owner_line("TEST VALUE: the price will rise by 40%", quotes=[], allowed="", steps=4)
        self.assertIn("figures its sources do not", raised.exception.message)
        with self.assertRaises(event_chain_text.TextRefused) as raised:
            event_chain_text.owner_line("TEST VALUE: " + Overlap.QUOTE, quotes=[Overlap.QUOTE],
                                        allowed=Overlap.QUOTE, steps=4)
        self.assertIn("repeats 6 words of a source", raised.exception.message)

    def test_text_that_cannot_be_stored_as_sent_is_refused_never_changed_silently(self):
        """Half an emoji cannot be written as UTF-8 (it was a raw 500), and Python's strip() removes U+001C to U+001F
        and U+0085 at an end where a browser's trim() keeps them, so the saved text would not be the text sent."""
        surrogate, kept_by_trim = chr(0xD83D), [chr(code) for code in (0x1C, 0x1D, 0x1E, 0x1F, 0x85)]
        saves = (lambda text: event_chain_text.owner_line(text, quotes=[], allowed="", steps=4),
                 lambda text: event_chain_text.owner_notes(text, quotes=[], steps=4),
                 lambda text: event_chain_text.owner_text(text, quotes=[], limit=280, name="the note"))
        for save in saves:
            for text in [f"TEST VALUE {surrogate} half an emoji", *(f"TEST VALUE{mark}" for mark in kept_by_trim),
                         *(f"{mark}TEST VALUE" for mark in kept_by_trim)]:
                with self.subTest(text=ascii(text)):
                    with self.assertRaises(event_chain_text.TextRefused) as raised:
                        save(text)
                    self.assertEqual(raised.exception.status, 422)
            self.assertEqual(save("  TEST VALUE, spaces at both ends  "), "TEST VALUE, spaces at both ends")

    def test_owner_notes_skip_claim_words_but_keep_overlap(self):
        self.assertEqual(event_chain_text.owner_notes("step 2 sounds like it claims a cause", quotes=[], steps=4),
                         "step 2 sounds like it claims a cause")
        with self.assertRaises(event_chain_text.TextRefused):
            event_chain_text.owner_notes(Overlap.QUOTE, quotes=[Overlap.QUOTE], steps=4)


if __name__ == "__main__":
    unittest.main()
