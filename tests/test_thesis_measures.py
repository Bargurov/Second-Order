"""A reason's or risk's measure (thesis_sections._measure): two years within one retained edition (ruling R12) beside
two editions of one series, and years read as four ASCII digits and ordered as integers; two sources of one edition are
not two editions, a revision keeps one period and a period comparison one kind of period (final review M1).

Runs on the SYNTHETIC version 1 (tests/thesis_fakes.py) through test_thesis_schema's fixture base, kept apart from
test_thesis_schema.py only so that file stays within the slice's 800-line limit. Loading reads content only.
"""
import re
import unittest
from unittest.mock import patch

from second_order import thesis_schema
from test_thesis_schema import ONE_EDITION, Theses, figure, find

# Final review M1, as thesis_sections words each rule.
SAME_EDITION = "come from two sources of one edition (the same edition text), so they do not compare two editions"
REVISION = "a revision compares one year, and the same period within it, in two editions"
PERIOD_KIND = "a period comparison compares periods of one kind (years, quarters, months or days)"


def periods(**by_figure):
    """A change giving each named figure a period within its year."""
    def change(body):
        for name, period in by_figure.items():
            figure(body, name).update(period=period)
    return change


class MeasureTests(Theses):
    def test_a_measure_may_compare_two_years_within_one_edition(self):  # Ruling R12.
        def within(latest, previous, compare="period"):
            return lambda b: b["reasons"][0]["measure"].update(latest=latest, previous=previous, compare=compare)
        loaded = self.accepted(within("iea26-clean-2035", "iea26-clean-2030"))
        measure = loaded["reasons"][0]["measure"]
        self.assertEqual([(figure(loaded, measure[key])["source"], figure(loaded, measure[key])["year"])
                          for key in ("latest", "previous")], [("iea-2026", "2035"), ("iea-2026", "2030")])
        self.accepted(lambda b: b["risks"][1]["measure"].update(latest="iea26-primary-2035",
                                                                previous="iea26-primary-2030", compare="period"))
        place = "reasons[clean-tech-demand].measure"

        def same_year(body):  # Two figures of one year in one edition.
            figure(body, "iea25-clean-2030").update(source="iea-2026")
            body["reasons"][0]["measure"].update(compare="period")
        refused = [("a revision within one edition", within("iea26-clean-2035", "iea26-clean-2030", "revision")),
                   ("an earlier year", within("iea26-clean-2030", "iea26-clean-2035")),
                   ("the same year", same_year)]
        for case, change in refused:
            with self.subTest(case=case):
                self.assertIn(ONE_EDITION, self.refused(change, f"{place}.compare"))
        self.assertIn("one figure twice", self.refused(within("iea26-clean-2035", "iea26-clean-2035"), place))
        self.assertIn("differ in measure", self.refused(within("iea26-clean-2035", "iea26-other-2030"), place))

    def test_years_are_ascii_digits_and_ordered_as_integers(self):
        # Arabic-Indic digits (U+0660 to U+0669) match \d, and as text they sort after "2", so 2023 written in them would
        # read as later than "2024"; under R12 a year's order is the only order a same-source measure has.
        def arabic(year):
            return "".join(chr(0x0660 + int(digit)) for digit in year)
        cases = [
            (lambda b: figure(b, "iea25-demand-2030").update(year=arabic("2030")), "figures[iea25-demand-2030].year"),
            (lambda b: figure(b, "wb-copper-2026m10").update(year=arabic("2026"), period=arabic("2026") + "M10"),
             "figures[wb-copper-2026m10].year"),
            (lambda b: b["balance"]["tables"][1]["rows"][1].update(year=arabic("2025")),
             "balance.tables[balance-side-by-side].rows[1].year"),
        ]
        for change, where in cases:
            with self.subTest(where=where):
                self.refused(change, where)

        def earlier(body):  # A same-source period whose latest year, 2023, is before the previous one, 2024.
            figure(body, "iea25-demand-2030").update(year=arabic("2023"))
            body["reasons"][0]["measure"].update(latest="iea25-demand-2030", previous="iea25-demand-2024",
                                                 compare="period")
        # The order compares integers itself: with the year pattern loosened to any digit, it still refuses.
        with patch.object(thesis_schema, "YEAR", re.compile(r"\d{4}")):
            self.assertIn(ONE_EDITION, self.refused(earlier, "reasons[clean-tech-demand].measure.compare"))

    # Final review M1: two sources must be two editions, and the label must hold for the periods compared.

    def test_two_sources_of_one_edition_are_not_two_editions(self):
        # Two files with one edition text (in v1, the MCS 2026 data release and the MCS 2026 chapter): a revision
        # between them would compare a figure with itself, as ruling R12 refuses within one source.
        def same(body):
            find(body["sources"], "usgs-2025").update(edition="2026")
        self.assertIn(SAME_EDITION, self.refused(same, "reasons[mine-supply-slow].measure"))

    def test_a_revision_compares_one_period_of_one_year(self):
        clean = "reasons[clean-tech-demand].measure.compare"
        # Q4 2030 against Q1 2030 is not one figure revised, although both are of 2030.
        self.assertIn(REVISION, self.refused(periods(**{"iea26-clean-2030": "2030Q4", "iea25-clean-2030": "2030Q1"}),
                                             clean))
        self.assertIn(REVISION, self.refused(periods(**{"iea26-clean-2030": "2030Q4"}), clean))  # a quarter, a year
        self.accepted(periods(**{"iea26-clean-2030": "2030Q4", "iea25-clean-2030": "2030Q4"}))

    def test_a_period_comparison_compares_periods_of_one_kind(self):
        # A quarter against a year, across two editions and (ruling R12) within one.
        self.assertIn(PERIOD_KIND, self.refused(periods(**{"usgs26-mine-2025": "2025Q4"}),
                                                "risks[mine-output-rising].measure.compare"))
        self.assertIn(PERIOD_KIND, self.refused(periods(**{"iea26-demand-2035": "2035Q4"}),
                                                "reasons[total-demand-rising].measure.compare"))
        # (usgs25-mine-2024 is also the previous figure of a revision, whose latest must then be of the same quarter.)
        self.accepted(periods(**{"usgs26-mine-2025": "2025Q4", "usgs25-mine-2024": "2024Q4",
                                 "usgs26-mine-2024": "2024Q4"}))
        self.accepted(periods(**{"iea26-demand-2035": "2035M12", "iea26-demand-2030": "2030M01"}))


if __name__ == "__main__":
    unittest.main()
