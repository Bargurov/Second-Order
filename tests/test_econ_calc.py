"""Figures and derived calculations of an economic explanation (econ-calc-0.2): every figure is quoted from its
evidence with its unit, period, nominal or real basis, seasonal adjustment and vintage, and every derived figure is
computed here, never written by a drafter. Planted mistakes: a percent change of growth rates (levels versus growth),
nominal against real, seasonally adjusted against not, deflating across periods, and a figure its quote does not
hold. All SYNTHETIC."""
import unittest

from second_order import econ_calc
from second_order.accounts import AccountsRefused

SOURCES = {
    "report:synthetic-ledger:00000000000000000001": {
        "text": "SYNTHETIC: Retail sales were $745.0 billion in September, up 0.8 percent from August's $739.1 "
                "billion. Inflation was 3.1% over the year; nominal wages rose 4.2% over the year.",
        "publisher": "Synthetic Ledger", "published": "2026-10-15T12:30:00+00:00"},
    "context:o1": {"text": "SYNTHETIC: GDP grew 2.0% in 2025 and 2.5% in 2026 (seasonally adjusted).",
                   "publisher": "Synthetic Statistics Office", "published": "2026-09-30"},
}
REPORT = "report:synthetic-ledger:00000000000000000001"


def figure(fid: str, value, quote: str, **extra) -> dict:
    row = {"id": fid, "label": "SYNTHETIC measure", "value": value, "unit": "billion dollars", "measure": "level",
           "period": "September 2026", "basis": "nominal", "seasonal": "not_stated", "price": False,
           "source": REPORT, "quote": quote, "vintage_label": None, "sign": "as_quoted", "sign_words": None,
           "bound": "exact", "statistic": "observed", "stock_flow": "not_applicable"}
    row.update(extra)
    return row


SEPTEMBER = figure("f1", 745.0, "Retail sales were $745.0 billion in September")
AUGUST = figure("f2", 739.1, "August's $739.1 billion", period="August 2026")
GROWTH_2025 = figure("f3", 2.0, "GDP grew 2.0% in 2025", unit="percent", measure="growth_rate", period="2025",
                     basis="real", seasonal="seasonally_adjusted", source="context:o1")
GROWTH_2026 = figure("f4", 2.5, "2.5% in 2026", unit="percent", measure="growth_rate", period="2026", basis="real",
                     seasonal="seasonally_adjusted", source="context:o1")
WAGES = figure("f5", 4.2, "nominal wages rose 4.2% over the year", unit="percent", measure="growth_rate",
               period="the year to September 2026")
PRICES = figure("f6", 3.1, "Inflation was 3.1% over the year", unit="percent", measure="growth_rate",
                period="the year to September 2026", basis="not_applicable", price=True)


def checked(*rows):
    return {row["id"]: row for row in econ_calc.checked_figures(list(rows), SOURCES)}


class FigureTest(unittest.TestCase):
    def test_a_figure_keeps_its_unit_period_basis_and_vintage_and_shows_its_quoted_precision(self):
        row = checked(SEPTEMBER)["f1"]
        self.assertEqual((row["unit"], row["period"], row["basis"], row["seasonal"]),
                         ("billion dollars", "September 2026", "nominal", "not_stated"))
        self.assertEqual(row["vintage"], {"source": "Synthetic Ledger", "published": "2026-10-15T12:30:00+00:00",
                                          "label": None})
        self.assertEqual((row["decimals"], row["display"]), (1, "745.0 billion dollars"))
        self.assertEqual(checked(PRICES)["f6"]["display"], "3.1%")

    def test_a_figure_its_evidence_does_not_hold_is_refused(self):
        for bad, why in ((figure("f1", 745.0, "Retail sales were $760.0 billion"), "not found"),
                         (figure("f1", 760.0, "Retail sales were $745.0 billion in September"), "does not hold"),
                         (figure("f1", 745.0, "Retail sales were $745.0 billion", source="report:other:1"), "evidence"),
                         (figure("f1", 745.0, "Retail sales were $745.0 billion", unit="percent"), "percent"),
                         (figure("f1", 3.1, "Inflation was 3.1%", measure="growth_rate"), "percent"),
                         (figure("f1", True, "Retail sales were $745.0 billion"), "number"),
                         (figure("f1", 745.0, "Retail sales were $745.0 billion", basis="inflation"), "basis")):
            with self.subTest(why=why), self.assertRaises(AccountsRefused) as refused:
                econ_calc.checked_figures([bad], SOURCES)
            self.assertIn(why, str(refused.exception))
        with self.assertRaises(AccountsRefused):
            econ_calc.checked_figures([SEPTEMBER, {**AUGUST, "id": "f1"}], SOURCES)  # Two figures, one ID.


class RenderTest(unittest.TestCase):
    def test_a_bound_the_sentence_states_is_not_repeated_by_the_value(self):
        shown = {"f1": "at most 4.5 billion euros", "f2": "at least 5 billion dollars", "f3": "about −95%",
                 "f4": "at most 197 billion euros"}
        self.assertEqual(econ_calc.render("with up to {f1} of guarantees", shown), "with up to 4.5 billion euros of "
                                                                                     "guarantees")
        self.assertEqual(econ_calc.render("more than {f2} in loans", shown), "more than 5 billion dollars in loans")
        self.assertEqual(econ_calc.render("trade changed by {f3}", shown), "trade changed by about −95%")
        self.assertEqual(econ_calc.render("a deficit of almost {f4}", shown), "a deficit of almost 197 billion euros")
        self.assertEqual(econ_calc.render("a deficit of {f4}", shown), "a deficit of at most 197 billion euros")
        self.assertEqual(econ_calc.render("a setup to {f1}", shown), "a setup to at most 4.5 billion euros")
        self.assertEqual(econ_calc.render("about {f1}", shown), "about at most 4.5 billion euros")  # Not its bound.


class CalculationTest(unittest.TestCase):
    def test_a_percent_change_of_two_levels_is_computed_here(self):
        rows = econ_calc.computed([{"id": "c1", "op": "percent_change", "inputs": ["f1", "f2"],
                                    "label": "SYNTHETIC monthly change"}], checked(SEPTEMBER, AUGUST))
        self.assertEqual((rows[0]["value"], rows[0]["unit"], rows[0]["measure"], rows[0]["basis"]),
                         (0.798268, "percent", "growth_rate", "nominal"))
        self.assertEqual(rows[0]["display"], "+0.8%")
        self.assertEqual(rows[0]["formula"], "(f1 ÷ f2 − 1) × 100")
        self.assertEqual(rows[0]["calc_version"], econ_calc.CALC_VERSION)

    def test_growth_rates_differ_in_percentage_points_and_never_by_a_percent_change(self):
        figures = checked(GROWTH_2026, GROWTH_2025)
        rows = econ_calc.computed([{"id": "c1", "op": "difference", "inputs": ["f4", "f3"], "label": "x"}], figures)
        self.assertEqual((rows[0]["value"], rows[0]["unit"], rows[0]["display"]),
                         (0.5, "percentage points", "+0.5 percentage points"))
        with self.assertRaises(AccountsRefused) as refused:  # Planted: "growth rose 25%" from 2.0% to 2.5%.
            econ_calc.computed([{"id": "c1", "op": "percent_change", "inputs": ["f4", "f3"], "label": "x"}], figures)
        self.assertIn("levels", str(refused.exception))

    def test_nominal_and_real_figures_are_never_combined_but_a_nominal_rate_can_be_deflated(self):
        nominal_growth = {**WAGES}
        real_growth = figure("f7", 2.5, "2.5% in 2026", unit="percent", measure="growth_rate",
                             period="the year to September 2026", basis="real", source="context:o1")
        figures = checked(nominal_growth, real_growth, PRICES)
        with self.assertRaises(AccountsRefused) as refused:  # Planted: nominal minus real.
            econ_calc.computed([{"id": "c1", "op": "difference", "inputs": ["f5", "f7"], "label": "x"}], figures)
        self.assertIn("nominal", str(refused.exception))
        rows = econ_calc.computed([{"id": "c1", "op": "deflate", "inputs": ["f5", "f6"], "label": "real wages"}],
                                  figures)
        self.assertEqual((rows[0]["basis"], rows[0]["display"]), ("real", "+1.1%"))
        self.assertAlmostEqual(rows[0]["value"], (1.042 / 1.031 - 1) * 100, places=5)
        later = {**PRICES, "id": "f8", "period": "the year to August 2026"}
        with self.assertRaises(AccountsRefused) as refused:  # Deflating by another period's prices.
            econ_calc.computed([{"id": "c1", "op": "deflate", "inputs": ["f5", "f8"], "label": "x"}],
                               checked(nominal_growth, later))
        self.assertIn("period", str(refused.exception))
        with self.assertRaises(AccountsRefused):  # A real rate is not deflated again.
            econ_calc.computed([{"id": "c1", "op": "deflate", "inputs": ["f7", "f6"], "label": "x"}], figures)

    def test_seasonally_adjusted_and_unadjusted_figures_are_not_compared(self):
        adjusted = {**AUGUST, "seasonal": "seasonally_adjusted"}
        with self.assertRaises(AccountsRefused) as refused:
            econ_calc.computed([{"id": "c1", "op": "percent_change", "inputs": ["f1", "f2"], "label": "x"}],
                               checked(SEPTEMBER, adjusted))
        self.assertIn("seasonal", str(refused.exception))

    def test_a_share_needs_the_same_period_and_unknown_inputs_or_operations_are_refused(self):
        figures = checked(SEPTEMBER, AUGUST)
        for bad in ({"id": "c1", "op": "ratio", "inputs": ["f1", "f2"], "label": "x"},
                    {"id": "c1", "op": "percent_change", "inputs": ["f1", "f9"], "label": "x"},
                    {"id": "c1", "op": "average", "inputs": ["f1", "f2"], "label": "x"},
                    {"id": "x1", "op": "difference", "inputs": ["f1", "f2"], "label": "x"}):
            with self.subTest(bad=bad), self.assertRaises(AccountsRefused):
                econ_calc.computed([bad], figures)

    def test_placeholders_render_the_computed_values_and_nothing_else(self):
        figures = checked(SEPTEMBER, AUGUST)
        rows = econ_calc.computed([{"id": "c1", "op": "percent_change", "inputs": ["f1", "f2"], "label": "x"}],
                                  figures)
        shown = econ_calc.displays(figures, rows)
        self.assertEqual(econ_calc.render("Sales of {f1} were {c1} on the month.", shown),
                         "Sales of 745.0 billion dollars were +0.8% on the month.")
        self.assertEqual(econ_calc.placeholders("{f1} and {c1} and {f9}"), ["f1", "c1", "f9"])

    def test_one_point_is_singular_and_a_stored_value_is_formatted_when_read(self):
        self.assertEqual(econ_calc.display(-1, "percentage points", 0, True), "−1 percentage point")
        self.assertEqual(econ_calc.display(-4, "percentage points", 0, True), "−4 percentage points")
        recorded = {"value": -1.0, "unit": "percentage points", "decimals": 0, "op": "difference",
                    "display": "−1 percentage points"}  # As a version saved before the fix holds it.
        self.assertEqual(econ_calc.shown(recorded), "−1 percentage point")
        self.assertEqual(econ_calc.shown({"value": 132.7, "unit": "percent", "decimals": 1, "op": "ratio"}), "132.7%")


def signed(quote: str, value, **extra) -> list[dict]:
    """A one-figure check against a SYNTHETIC report holding exactly ``quote``."""
    sources = {"report:synthetic:1": {"text": quote, "publisher": "Synthetic", "published": "2026-10-01"}}
    fields = {"unit": "percent", "measure": "growth_rate", "source": "report:synthetic:1", "period": "2026", **extra}
    return econ_calc.checked_figures([figure("f1", value, quote, **fields)], sources)


class SignTest(unittest.TestCase):
    """Reproduced 2026-10-26: a positive 5.2 was accepted against "output growth was -5.2%" (magnitudes compared)."""

    def test_an_explicitly_negative_quote_never_holds_a_positive_value(self):
        for quote in ("SYNTHETIC: output growth was -5.2%.", "SYNTHETIC: output growth was \u22125.2%.",
                      "SYNTHETIC: output growth was \u20135.2%.", "SYNTHETIC: output growth was \uff0d5.2%."):
            with self.subTest(quote=quote), self.assertRaises(AccountsRefused) as refused:
                signed(quote, 5.2)
            self.assertIn("opposite sign", str(refused.exception))
            self.assertEqual(signed(quote, -5.2)[0]["value"], -5.2)  # The negative value it states is accepted.
        self.assertEqual(signed("SYNTHETIC: growth was +5.2%.", 5.2)[0]["display"], "5.2%")
        with self.assertRaises(AccountsRefused):
            signed("SYNTHETIC: growth was +5.2%.", -5.2)

    def test_an_unsigned_magnitude_takes_its_direction_only_from_cited_words(self):
        quote = "SYNTHETIC: output fell by 5.2% in 2026."
        with self.assertRaises(AccountsRefused) as refused:  # A negative value needs the words that state it.
            signed(quote, -5.2)
        self.assertIn("sign", str(refused.exception))
        row = signed(quote, -5.2, sign="from_words", sign_words="fell by")[0]
        self.assertEqual((row["value"], row["direction_check"], row["display"]), (-5.2, "consistent", "\u22125.2%"))
        with self.assertRaises(AccountsRefused) as refused:  # Words that say the opposite direction.
            signed(quote, 5.2, sign="from_words", sign_words="fell by")
        self.assertIn("direction", str(refused.exception))
        with self.assertRaises(AccountsRefused):  # Cited words the quote does not hold.
            signed(quote, -5.2, sign="from_words", sign_words="dropped")
        with self.assertRaises(AccountsRefused):  # An explicit sign is used as quoted, not re-read from words.
            signed("SYNTHETIC: output was -5.2% lower.", -5.2, sign="from_words", sign_words="lower")
        unclear = signed("SYNTHETIC: output moved 5.2% in 2026.", -5.2, sign="from_words", sign_words="moved")[0]
        self.assertEqual(unclear["direction_check"], "unclear")  # Surfaced, never silently assumed.
        hinted = signed(quote, 5.2)[0]  # A positive reading of "fell by 5.2%" is flagged for the guard.
        self.assertEqual(hinted["direction_check"], "contradicted")
        plain = signed("SYNTHETIC: output grew 5.2% in 2026.", 5.2)[0]
        self.assertEqual(plain["direction_check"], "consistent")

    def test_ranges_and_margins_are_not_read_as_negative_numbers(self):
        self.assertEqual(econ_calc.signed_numbers("from 2021\u20132025 the rate was 3.0%")[:2],
                         [(2021.0, 0, None), (2025.0, 0, None)])
        self.assertEqual(econ_calc.signed_numbers("from 2021 \u2013 2025, pages 5 - 7"),
                         [(2021.0, 0, None), (2025.0, 0, None), (5.0, 0, None), (7.0, 0, None)])
        self.assertEqual(econ_calc.signed_numbers("growth was \u2013 5.2% (+/- 11.8%)"),
                         [(-5.2, 1, "-"), (11.8, 1, "\u00b1")])
        margin = signed("SYNTHETIC: up 0.8 percent (+/-0.4 percent) from the previous month", 0.4, measure="change",
                        unit="percentage points")[0]
        self.assertEqual(margin["value"], 0.4)

    def test_negative_values_flow_through_calculations_with_their_sign(self):
        sources = {"report:synthetic:1": {"text": "SYNTHETIC: growth was -1.5% after -1.2%; nominal pay fell by "
                                                  "2.0% while prices rose 3.1% over the year.",
                                          "publisher": "Synthetic", "published": "2026-10-01"}}
        base = {"unit": "percent", "measure": "growth_rate", "source": "report:synthetic:1", "period": "2026"}
        rows = {row["id"]: row for row in econ_calc.checked_figures([
            figure("f1", -1.5, "growth was -1.5%", **base), figure("f2", -1.2, "after -1.2%", **base),
            figure("f3", -2.0, "nominal pay fell by 2.0%", sign="from_words", sign_words="fell by", **base),
            figure("f4", 3.1, "prices rose 3.1% over the year", price=True, **{**base, "basis": "not_applicable"})],
            sources)}
        done = econ_calc.computed([{"id": "c1", "op": "difference", "inputs": ["f1", "f2"], "label": "x"},
                                   {"id": "c2", "op": "deflate", "inputs": ["f3", "f4"], "label": "x"}], rows)
        self.assertEqual((done[0]["display"], done[1]["display"]), ("\u22120.3 percentage points", "\u22124.9%"))
        self.assertAlmostEqual(done[1]["value"], (0.98 / 1.031 - 1) * 100, places=5)


class MeasurementTest(unittest.TestCase):
    """Bounds, summary statistics, stocks and flows (reviewed 2026-10-26)."""

    def test_a_lower_bound_stays_a_bound_through_a_calculation(self):
        sources = {"report:synthetic:1": {"text": "SYNTHETIC: utilization averaged more than 95% this summer, against "
                                                  "a 92% average and more than 90% last year.",
                                          "publisher": "Synthetic", "published": "2026-10-01"}}
        base = {"unit": "percent", "measure": "rate", "source": "report:synthetic:1", "basis": "not_applicable"}
        rows = {row["id"]: row for row in econ_calc.checked_figures([
            figure("f1", 95, "averaged more than 95% this summer", bound="lower_bound", period="summer", **base),
            figure("f2", 92, "a 92% average", period="long run", **base),
            figure("f3", 90, "more than 90% last year", bound="lower_bound", period="last year", **base)], sources)}
        self.assertEqual(rows["f1"]["display"], "at least 95%")
        done = econ_calc.computed([{"id": "c1", "op": "difference", "inputs": ["f1", "f2"], "label": "x"}], rows)
        self.assertEqual((done[0]["bound"], done[0]["display"]), ("lower_bound", "at least +3 percentage points"))
        with self.assertRaises(AccountsRefused):  # Two lower bounds bound nothing about their difference.
            econ_calc.computed([{"id": "c1", "op": "difference", "inputs": ["f1", "f3"], "label": "x"}], rows)

    def test_summaries_of_separate_survey_answers_are_not_deflated_into_a_new_statistic(self):
        sources = {"report:synthetic:1": {"text": "SYNTHETIC: expected income growth was 1.1% (mean) and median "
                                                  "expected inflation 3.1%.",
                                          "publisher": "Synthetic", "published": "2026-10-01"}}
        base = {"unit": "percent", "measure": "growth_rate", "source": "report:synthetic:1",
                "period": "next 12 months"}
        rows = {row["id"]: row for row in econ_calc.checked_figures([
            figure("f1", 1.1, "expected income growth was 1.1%", statistic="mean", **base),
            figure("f2", 3.1, "median expected inflation 3.1%", statistic="median", price=True,
                   **{**base, "basis": "not_applicable"})], sources)}
        with self.assertRaises(AccountsRefused) as refused:
            econ_calc.computed([{"id": "c1", "op": "deflate", "inputs": ["f1", "f2"], "label": "x"}], rows)
        self.assertIn("summar", str(refused.exception))

    def test_a_stock_against_a_monthly_flow_is_months_of_flow_never_a_share(self):
        sources = {"report:synthetic:1": {"text": "SYNTHETIC: end-of-month inventories were $2,818.8 billion and "
                                                  "monthly sales $2,123.5 billion; exports were $400.0 billion.",
                                          "publisher": "Synthetic", "published": "2026-10-01"}}
        base = {"source": "report:synthetic:1", "period": "August 2026"}
        rows = {row["id"]: row for row in econ_calc.checked_figures([
            figure("f1", 2818.8, "inventories were $2,818.8 billion", stock_flow="stock", **base),
            figure("f2", 2123.5, "monthly sales $2,123.5 billion", stock_flow="flow_per_month", **base),
            figure("f3", 400.0, "exports were $400.0 billion", stock_flow="flow_per_month", **base)], sources)}
        done = econ_calc.computed([{"id": "c1", "op": "stock_to_flow", "inputs": ["f1", "f2"], "label": "x"},
                                   {"id": "c2", "op": "share", "inputs": ["f3", "f2"], "label": "x"}], rows)
        self.assertEqual((done[0]["display"], done[0]["unit"]), ("1.33 months", "months"))
        self.assertEqual(done[1]["display"], "18.8%")
        for bad in ({"id": "c1", "op": "share", "inputs": ["f1", "f2"], "label": "x"},  # A stock is no part of a flow.
                    {"id": "c1", "op": "share", "inputs": ["f2", "f3"], "label": "x"},  # A part above its whole.
                    {"id": "c1", "op": "stock_to_flow", "inputs": ["f2", "f1"], "label": "x"},
                    {"id": "c1", "op": "ratio", "inputs": ["f1", "f2"], "label": "x"}):
            with self.subTest(bad=bad), self.assertRaises(AccountsRefused):
                econ_calc.computed([bad], rows)


if __name__ == "__main__":
    unittest.main()
