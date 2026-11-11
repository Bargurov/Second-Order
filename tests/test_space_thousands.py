"""Thousands grouped by spaces are one number (econ-calc-0.6;
docs/news-space-thousands-2026-11-01.md (private; not in the public repository)).

The approved von der Leyen stage-1 trial of 29 October 2026
(docs/news-flow-stage-1-result-2026-10-29.md (private; not in the public repository)) quoted the Commission's "annual
quota of 350 000 hybrid vehicles". Up to econ-calc-0.5 thousands were recognised only with commas, so that quote was read
as 350 and 0: the correct value 350,000 was refused, and a wrong value of 350 passed. From econ-calc-0.6 a space,
no-break space, narrow no-break space or thin space groups thousands, and every reader of numbers (figure quotes,
qualifiers, claims and the "number the evidence states" stops) reads them so. Figures checked under an earlier
calculation version are checked as they were, so the recorded refusal reproduces.

A run of digit groups is joined only when it can be one number: each group after the first has exactly three digits,
and no digit group stands directly before it or after it (by a space or a hyphen). The press contacts in retained
Commission and ECB texts ("+32 2 295 75 01", "+32 229-69776", "+49 170 227 9090") therefore read as they did.

Real case: tests/consistency_cases.json ("quota", the speech's own sentence). The rest is SYNTHETIC or a quoted press
contact. Nothing reaches a network, and passing these checks is not evidence that a figure is economically right."""
import unittest

from second_order import brief_claims, brief_stages, econ_calc, econ_fidelity, story_economics
from second_order.accounts import AccountsRefused
from test_econ_consistency import evidence, figure

QUOTA = "We agreed an annual quota of 350 000 hybrid vehicles from China."


def quota(value) -> dict:
    """The quota figure of the refused 29 October reply, with the value under test."""
    return {**figure("quota", "f1", QUOTA, value, "vehicles", "annual", "flow_per_year",
                     label="Annual quota on hybrid vehicles from China"), "basis": "not_applicable"}


class ReadingTest(unittest.TestCase):
    def test_thousands_grouped_by_any_space_are_one_number(self):
        for text, want in (("a quota of 350 000 vehicles", [(350000.0, 0)]),
                           ("a quota of 350 000 vehicles", [(350000.0, 0)]),  # no-break space
                           ("a quota of 350 000 vehicles", [(350000.0, 0)]),  # narrow no-break space
                           ("a quota of 350 000 vehicles", [(350000.0, 0)]),  # thin space
                           ("1 221 000 jobs", [(1221000.0, 0)]),
                           ("1 234.5 tonnes", [(1234.5, 1)]),
                           ("1,221,000 jobs", [(1221000.0, 0)])):
            with self.subTest(text=text):
                self.assertEqual(econ_calc.numbers(text), want)

    def test_a_grouped_number_keeps_its_sign_and_a_range_is_two_numbers(self):
        self.assertEqual(econ_calc.signed_numbers("output fell to −12 500 units"), [(-12500.0, 0, "-")])
        self.assertEqual(econ_calc.signed_numbers("+12 000 jobs"), [(12000.0, 0, "+")])
        self.assertEqual(econ_calc.signed_numbers("€22 000 of savings"), [(22000.0, 0, None)])
        self.assertEqual(econ_calc.signed_numbers("between 350 000–400 000 vehicles"),
                         [(350000.0, 0, None), (400000.0, 0, None)])

    def test_the_digit_groups_of_a_telephone_number_are_not_joined(self):
        for text, want in (("Tel.: +32 2 295 75 01;", [32.0, 2.0, 295.0, 75.0, 1.0]),
                           ("Tel. + 32 2 299 10 99;", [32.0, 2.0, 299.0, 10.0, 99.0]),
                           ("Tel.: +32 229-69776;", [32.0, 229.0, 69776.0]),
                           ("tel.: +49 170 227 9090.", [49.0, 170.0, 227.0, 9090.0]),
                           ("tel.: +49 172 1683704.", [49.0, 172.0, 1683704.0]),
                           ("SYNTHETIC tel.: +33 1 234 567.", [33.0, 1.0, 234.0, 567.0])):  # A group before it.
            with self.subTest(text=text):
                self.assertEqual([value for value, _ in econ_calc.numbers(text)], want)


class FigureCheckTest(unittest.TestCase):
    def test_the_speech_quota_holds_350000_and_not_350(self):
        sources = evidence("quota")["sources"]
        row = econ_calc.checked_figures([quota(350000)], sources)[0]
        self.assertEqual((row["value"], row["decimals"], row["display"]), (350000, 0, "350,000 vehicles"))
        with self.assertRaisesRegex(AccountsRefused, r"does not hold its value \(350\)"):
            econ_calc.checked_figures([quota(350)], sources)

    def test_the_current_explanation_checks_figures_with_the_new_reading(self):
        calc = story_economics.ANALYSES[story_economics.ANALYSIS_VERSION]
        self.assertEqual(econ_calc.checked_figures([quota(350000)], evidence("quota")["sources"], calc)[0]["value"],
                         350000)

    def test_calculation_versions_up_to_0_5_read_as_they_did(self):
        # Historical replay: econ-calc-0.5 (105c470) refused the correct value with this detail on 29 October.
        sources = evidence("quota")["sources"]
        for version in ("econ-calc-0.2", "econ-calc-0.3", "econ-calc-0.4", "econ-calc-0.5"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(AccountsRefused, r"Figure 1's quote does not hold its value \(350000\)"):
                    econ_calc.checked_figures([quota(350000)], sources, version)
                self.assertEqual(econ_calc.checked_figures([quota(350)], sources, version)[0]["value"], 350)


class ReadersAgreeTest(unittest.TestCase):
    """The figure check, its qualifiers, the claims check and the evidence stops read one number alike."""

    def test_a_margin_beside_a_grouped_number_is_read(self):
        found = econ_fidelity.margin({"value": 676000, "quote": "SYNTHETIC: sales of 676 000 (+/- 13 800) houses",
                                      "unit": "houses", "measure": "level"})
        self.assertEqual(found and (found["value"], found["display"]), (13800.0, "±13,800 houses"))

    def test_the_claims_check_reads_the_grouped_number_as_written(self):
        self.assertEqual([(value, written) for value, _, written in
                          brief_claims._magnitudes("SYNTHETIC: a quota of 350 000 vehicles")],
                         [(350000.0, "350 000")])

    def test_a_brief_may_write_with_commas_a_number_the_evidence_groups_with_spaces(self):
        content = {"headline": "SYNTHETIC: EU and China agree a hybrid quota",
                   "summary": "SYNTHETIC: an annual quota of 350,000 hybrid vehicles.",
                   "facts": [{"text": "SYNTHETIC: the EU and China agreed an annual quota of 350,000 hybrid vehicles."}],
                   "implications": [], "themes": [], "uncertainties": [], "missing": []}
        self.assertEqual(brief_stages.coherence(content, evidence("quota")), [])


if __name__ == "__main__":
    unittest.main()
