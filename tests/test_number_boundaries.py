"""A number is read whole only where its digit groups say so, and a fragment is never a figure (econ-calc-0.7;
docs/news-number-boundaries-2026-11-04.md (private; not in the public repository)).

Codex's independent review of 4 November 2026 (number-boundary-diagnostic.json, beside
PROJECT_DEEP_REVIEW_2026-11-04.md) reproduced two SYNTHETIC quotes against econ-calc-0.6 in which a fragment of a
space-grouped number passed as a figure while the complete number was refused:

- "An annual quota of 350 000-400 000 vehicles.": 350 accepted, 350000 refused;
- "In 2025 350 000 vehicles were supplied.": 350 accepted, 350000 refused.

From econ-calc-0.7 a token of four or more digits (a year) cannot be a group of thousands, so a grouped number written
after it is read whole; a hyphen between two complete grouped numbers is a range, read as its two ends; any other run of
digit groups that could also be one number (a telephone number, a grouping cut short) gives no figure; and a figure read
from one end of a range written with a dash is a bound, never an exact or approximate point. Figures checked under
econ-calc-0.6 and earlier read numbers as they did, so a recorded acceptance or refusal reproduces.

Everything here is SYNTHETIC or a quoted press contact. Nothing reaches a network, and passing these checks is not
evidence that a figure is economically right."""
import hashlib
import unittest

from second_order import brief_claims, brief_stages, econ_calc, news_explanations, story_economics
from second_order.accounts import AccountsRefused
from test_econ_consistency import figure, synthetic

RANGE = "An annual quota of 350 000-400 000 vehicles."
YEAR = "In 2025 350 000 vehicles were supplied."
SPACES = {"space": " ", "no-break space": " ", "narrow no-break space": " ", "thin space": " "}
EARLIER = ("econ-calc-0.2", "econ-calc-0.3", "econ-calc-0.4", "econ-calc-0.5", "econ-calc-0.6")
# SHA-256 of the number patterns as committed at bd269fa (econ-calc-0.6 and the commas-only reading up to 0.5).
PATTERN_06 = "afe5f55cf3682dfe0bca849a9e5f7df9083c216f735710ac1bb4e6d49d188a13"
PATTERN_COMMAS = "205178335191f9030fe21bf70b52e72f89e8dfc0c88c1712519828c656cabbf6"
NOT_HELD = r"^Figure 1's quote does not hold its value \(350000\)\.$"  # The whole detail, as recorded under 0.6.


def check(text: str, value: float, bound: str = "exact", version: str = econ_calc.CALC_VERSION,
          quote: str | None = None, **fields) -> dict:
    """One SYNTHETIC figure quoted from ``text`` (the whole text unless ``quote``), checked under ``version``."""
    row = {**figure("quota", "f1", quote or text, value, "vehicles", "annual", "flow_per_year", bound),
           "source": "report:synthetic", "basis": "not_applicable", **fields}
    return econ_calc.checked_figures([row], synthetic(text), version)[0]


def change(text: str, value: float, bound: str, version: str = econ_calc.CALC_VERSION) -> dict:
    """A SYNTHETIC growth rate whose direction the words "fell by" state."""
    return check(text, value, bound, version, unit="percent", measure="growth_rate", stock_flow="not_applicable",
                 sign="from_words", sign_words="fell by")


def evidence(text: str) -> dict:
    report = {"entry_id": "synthetic", "title": "SYNTHETIC report", "excerpt": text, "text": None,
              "publisher": "Synthetic", "published_utc": None, "published": "2026-11-04"}
    return story_economics.evidence({"reports": [report]}, None, None, "2026-11-04T00:00:00+00:00")


class ReadingTest(unittest.TestCase):
    def test_a_grouped_number_written_after_a_year_is_read_whole(self):
        for name, space in SPACES.items():
            with self.subTest(name):
                self.assertEqual(econ_calc.numbers(YEAR.replace(" ", space)), [(2025.0, 0), (350000.0, 0)])
        self.assertEqual(econ_calc.numbers("In 2024-2025 1 250 000 vehicles"),
                         [(2024.0, 0), (2025.0, 0), (1250000.0, 0)])

    def test_a_hyphen_between_two_grouped_numbers_is_a_range_of_two_unsigned_numbers(self):
        for name, space in SPACES.items():
            with self.subTest(name):
                self.assertEqual(econ_calc.signed_numbers(RANGE.replace(" ", space)),
                                 [(350000.0, 0, None), (400000.0, 0, None)])

    def test_telephone_numbers_read_as_before(self):
        for text, want in (("Tel.: +32 2 295 75 01;", [32.0, 2.0, 295.0, 75.0, 1.0]),
                           ("Tel.: +32 229-69776;", [32.0, 229.0, 69776.0]),
                           ("tel.: +49 170 227 9090.", [49.0, 170.0, 227.0, 9090.0]),
                           ("SYNTHETIC tel.: +33 1 234 567.", [33.0, 1.0, 234.0, 567.0]),
                           # A long token after another digit group is a telephone number's, not a year before a
                           # quantity: the grouping after it is not joined.
                           ("SYNTHETIC tel.: +49 6221 123 456.", [49.0, 6221.0, 123.0, 456.0])):
            with self.subTest(text=text):
                self.assertEqual([value for value, _ in econ_calc.numbers(text)], want)

    def test_earlier_versions_keep_their_readings_byte_for_byte(self):
        self.assertEqual(hashlib.sha256(econ_calc.READING_OF["econ-calc-0.6"].pattern.encode()).hexdigest(), PATTERN_06)
        for version in EARLIER[:-1]:
            with self.subTest(version):
                self.assertEqual(hashlib.sha256(econ_calc.READING_OF[version].pattern.encode()).hexdigest(),
                                 PATTERN_COMMAS)
        reading = econ_calc.READING_OF["econ-calc-0.6"]
        self.assertEqual(econ_calc.numbers(YEAR, reading), [(2025.0, 0), (350.0, 0), (0.0, 0)])
        self.assertEqual(econ_calc.numbers(RANGE, reading), [(350.0, 0), (0.0, 0), (400000.0, 0)])


class FigureCheckTest(unittest.TestCase):
    """econ-calc-0.7, the current calculation version."""

    def test_a_quantity_after_a_year_is_held_whole_and_its_fragment_is_refused(self):
        for name, space in SPACES.items():
            with self.subTest(name):
                text = YEAR.replace(" ", space)
                row = check(text, 350000)
                self.assertEqual((row["value"], row["decimals"], row["display"]), (350000, 0, "350,000 vehicles"))
                with self.assertRaisesRegex(AccountsRefused, r"does not hold its value \(350\)"):
                    check(text, 350)

    def test_the_ends_of_a_grouped_range_are_held_as_bounds_and_its_fragments_refused(self):
        for name, space in SPACES.items():
            with self.subTest(name):
                text = RANGE.replace(" ", space)
                self.assertEqual(check(text, 350000, "lower_bound")["display"], "at least 350,000 vehicles")
                self.assertEqual(check(text, 400000, "upper_bound")["display"], "at most 400,000 vehicles")
                for fragment in (350, 0):
                    with self.assertRaisesRegex(AccountsRefused, rf"does not hold its value \({fragment}\)"):
                        check(text, fragment, "lower_bound")

    def test_an_end_of_a_range_is_never_an_exact_or_approximate_point(self):
        for bound in ("exact", "approximate", "upper_bound"):
            with self.subTest(bound):
                with self.assertRaisesRegex(AccountsRefused, "Figure 1: its quote writes 350000 only as an end of the "
                                                             "range “350 000-400 000”.*bound lower_bound"):
                    check(RANGE, 350000, bound)
        with self.assertRaisesRegex(AccountsRefused, "bound upper_bound"):
            check(RANGE, 400000, "lower_bound")

    def test_ranges_written_with_commas_an_en_dash_or_a_spaced_dash_follow_the_same_rule(self):
        for text in ("SYNTHETIC: a quota of 350,000-400,000 vehicles.",
                     "SYNTHETIC: a quota of 350 000–400 000 vehicles.",
                     "SYNTHETIC: a quota of 350 000 - 400 000 vehicles.", "SYNTHETIC: a quota of 350-400 vehicles."):
            low = 350 if "350-400" in text else 350000
            with self.subTest(text=text):
                with self.assertRaisesRegex(AccountsRefused, "only as an end of the range"):
                    check(text, low)
                self.assertEqual(check(text, low, "lower_bound")["value"], low)

    def test_a_change_read_from_a_range_states_the_bound_its_direction_gives(self):
        text = "SYNTHETIC: output fell by 3-4% in 2025."
        self.assertEqual(change(text, -3, "upper_bound")["display"], "at most −3%")  # A fall of at least 3%.
        self.assertEqual(change(text, -4, "lower_bound")["display"], "at least −4%")
        for bound in ("exact", "lower_bound"):
            with self.subTest(bound):
                with self.assertRaisesRegex(AccountsRefused, "bound upper_bound"):
                    change(text, -3, bound)

    def test_a_value_the_quote_also_writes_on_its_own_may_be_exact(self):
        text = "SYNTHETIC: 350 000 vehicles this year, within a band of 350 000-400 000."
        self.assertEqual(check(text, 350000)["bound"], "exact")

    def test_numbers_joined_by_words_are_not_read_as_a_range(self):
        # "from 3% to 4%" is a change between two levels, not a range, so its start may be an exact figure. A range
        # written in words ("between 3% and 4%") is not detected either: a stated limit.
        self.assertEqual(check("SYNTHETIC: the rate rose from 3% to 4%.", 3, unit="percent", measure="rate",
                               stock_flow="not_applicable")["bound"], "exact")

    def test_a_run_that_could_also_be_one_number_gives_no_figure(self):
        for text, value, run in (("SYNTHETIC: a quota of 350 000 12 months later.", 350, "350 000 12"),
                                 ("SYNTHETIC: a quota of 350 000 12 months later.", 12, "350 000 12"),
                                 ("SYNTHETIC: a quota of 350 000-400 vehicles.", 350, "350 000-400"),
                                 ("SYNTHETIC: a quota of 350 000-400 vehicles.", 400, "350 000-400"),
                                 ("Tel.: +32 2 295 75 01;", 295, "32 2 295 75 01"),
                                 ("Tel.: +32 229-69776;", 69776, "32 229-69776"),
                                 ("SYNTHETIC tel.: +49 6221 123 456.", 6221, "49 6221 123 456")):
            with self.subTest(text=text, value=value):
                with self.assertRaisesRegex(AccountsRefused, f"Figure 1: its quote writes {value} only inside “{run}”"):
                    check(text, value)

    def test_a_complete_number_refused_beside_such_a_run_names_it(self):
        with self.assertRaisesRegex(AccountsRefused, r"does not hold its value \(350000\) \(it writes digit groups "
                                                     "that do not read as one number: “350 000 12”\\)"):
            check("SYNTHETIC: a quota of 350 000 12 months later.", 350000)


class HistoricalTest(unittest.TestCase):
    """Figures checked under econ-calc-0.6 and earlier read numbers as they did: the defects reproduce."""

    def test_the_fragments_codex_reproduced_still_pass_under_earlier_versions(self):
        for version in EARLIER:
            with self.subTest(version):
                for text in (RANGE, YEAR):
                    self.assertEqual(check(text, 350, version=version)["value"], 350)
                    with self.assertRaisesRegex(AccountsRefused, NOT_HELD):
                        check(text, 350000, "lower_bound", version)

    def test_earlier_versions_have_no_range_or_run_rule(self):
        for version in EARLIER:
            with self.subTest(version):
                self.assertEqual(check("SYNTHETIC: a quota of 350,000-400,000 vehicles.", 350000,
                                       version=version)["bound"], "exact")
                self.assertEqual(check("Tel.: +32 2 295 75 01;", 295, version=version)["value"], 295)


class ReadersAgreeTest(unittest.TestCase):
    """The claims reader and the stops for a number the evidence does not state read the two shapes alike."""

    def test_the_evidence_states_the_whole_quantity_after_a_year_not_its_fragment(self):
        found = evidence(YEAR)
        self.assertIn(350000.0, found["numbers"])
        self.assertNotIn(350.0, found["numbers"])
        content = {"headline": "SYNTHETIC: 350,000 vehicles supplied in 2025", "summary": "SYNTHETIC.",
                   "facts": [{"text": "SYNTHETIC: in 2025 350,000 vehicles were supplied."}],
                   "implications": [], "themes": [], "uncertainties": [], "missing": []}
        self.assertEqual(brief_stages.coherence(content, found), [])
        content["facts"] = [{"text": "SYNTHETIC: 350 vehicles were supplied."}]
        stops = brief_stages.coherence(content, found)
        self.assertEqual([(row["where"], row["rule"], row["matched"]) for row in stops],
                         [("facts[0]", "unsourced_number", "350")])

    def test_the_claims_reader_reads_a_grouped_range_as_written(self):
        self.assertEqual([(value, written) for value, _, written in brief_claims._magnitudes(RANGE)],
                         [(350000.0, "350 000"), (400000.0, "400 000")])


class VersionTest(unittest.TestCase):
    def test_the_current_explanation_checks_figures_under_econ_calc_0_7(self):
        self.assertEqual(econ_calc.CALC_VERSION, "econ-calc-0.7")
        self.assertEqual(story_economics.ANALYSES[story_economics.ANALYSIS_VERSION], "econ-calc-0.7")
        for table in (econ_calc.MEASURES_OF, econ_calc.STOCK_FLOW_OF):
            self.assertEqual(table["econ-calc-0.7"], table["econ-calc-0.6"])
        self.assertIn("econ-calc-0.7", econ_calc.LENGTH_CHECKED)

    def test_a_result_saved_under_0_6_would_be_prepared_again(self):
        brief = {"content": {"economics": {"analysis_version": story_economics.ANALYSIS_VERSION,
                                           "status": "insufficient_evidence"}},
                 "material_sha256": "m", "at": "2026-11-04T12:00:00+00:00",
                 "preparation": {"analysis": {"calc_version": "econ-calc-0.6", "guard_version":
                                              story_economics.GUARD_VERSION, "context": None}}}
        self.assertEqual(news_explanations.reasons(brief, "m"), [
            "it was prepared under an earlier calculation method (econ-calc-0.6; now econ-calc-0.7)"])


if __name__ == "__main__":
    unittest.main()
