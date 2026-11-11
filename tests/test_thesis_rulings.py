"""Rulings R15 to R18 of the copper thesis slice, on the SYNTHETIC version 1 (tests/thesis_fakes.py).

R15 an element must cite something; R16 edition_date is an ordering key (its cross-edition order check is pinned in
test_thesis_schema.test_reason_editions_must_be_one_series_in_order, and the frontend's wording in
frontend/tests/thesisRulings.test.ts); R17 two truthful transcription methods; R18 a cents-per-pound price unit.
Loading reads content only.
"""
import unittest

from second_order import thesis_schema, thesis_view
from test_thesis_schema import Theses, figure, find

NOTHING = "cites no figure or passage, so nothing on it could be checked"
PAGE_IMAGE = "transcribed from the page image"
TEXT_LAYER = "transcribed from the PDF's text layer"
CENTS = "usd_cents_per_lb"


def silent_risk(body):  # The untracked risk, now stating nothing and citing nothing.
    risk = find(body["risks"], "construction-slowdown")
    risk["statement"] = {"status": "not_stated", "text": "Synthetic: the retained sources do not state this.",
                         "cites": []}


def cents(*names):
    def change(body):
        for name in names:
            figure(body, name).update(unit=CENTS)
    return change


class CitesSomethingTests(Theses):  # Ruling R15.
    def test_a_risk_citing_nothing_is_refused_at_its_path(self):
        message = self.refused(silent_risk, "risks[construction-slowdown]")
        self.assertIn(NOTHING, message)

    def test_a_view_citing_nothing_is_refused_at_view(self):  # Final review I1: the view is an element too.
        def silent_view(body):
            body["view"] = {"status": "not_stated", "text": "Synthetic: the sources do not state a view.", "cites": []}
        self.assertIn(f"(view: {NOTHING})", self.refused(silent_view, "view"))

    def test_a_not_stated_statement_beside_a_measure_still_loads(self):
        def reason_says_nothing(body):
            reason = body["reasons"][0]
            reason["statement"] = {"status": "not_stated", "text": "Synthetic: the sources do not say more.",
                                   "cites": []}
        loaded = self.accepted(reason_says_nothing)
        self.assertEqual(loaded["reasons"][0]["statement"]["status"], "not_stated")
        self.assertIsNotNone(loaded["reasons"][0]["measure"])

    def test_a_not_stated_risk_citing_something_through_its_measure_loads(self):
        def risk_with_measure(body):
            risk = find(body["risks"], "mine-output-rising")
            risk["statement"] = {"status": "not_stated", "text": "Synthetic: the sources state nothing further.",
                                 "cites": []}
        self.accepted(risk_with_measure)

    def test_the_other_kinds_cannot_be_empty(self):
        # Balance rows need demand and supply totals, a differs entry needs one or more others, a reason needs a
        # measure, a condition a figure, movers cites, a moved entry a figure or its computed inputs, and the price
        # record two figures: each is refused before it could cite nothing.
        self.refused(lambda b: b["balance"]["tables"][0].update(rows=[]), "balance.tables[balance-steps].rows")
        self.refused(lambda b: b["balance"]["tables"][1].update(rows=[]), "balance.tables[balance-side-by-side].rows")
        self.refused(lambda b: b["differs"][0].update(others=[]), "differs[differs-earlier-edition].others")
        self.refused(lambda b: b["reasons"][0].update(measure=None), "reasons[clean-tech-demand].measure")
        self.refused(lambda b: b["conditions"][0].update(figure=None), "conditions[supply-above].figure")
        self.refused(lambda b: b["exposure"]["movers"][0].update(cites=[]), "exposure.movers[0].cites")


class PriceRecordSeriesTests(Theses):  # Final review I2: the series is author text, held to the record's figures.
    PLACE = "price_record.series"

    @staticmethod
    def series(text):
        return lambda b: b["price_record"].update(series=text)

    def test_a_claim_word_in_the_series_is_refused(self):
        message = self.refused(self.series("Synthetic monthly copper price, which confirms the view"), self.PLACE)
        self.assertIn("uses 'confirms'", message)

    def test_a_price_direction_in_the_series_is_refused(self):
        message = self.refused(self.series("Synthetic copper price, higher than at opening"), self.PLACE)
        self.assertIn("states a view on a price's direction", message)

    def test_a_digit_its_figures_do_not_hold_is_refused(self):
        message = self.refused(self.series("Synthetic monthly copper price, 2025 US dollars per tonne"), self.PLACE)
        self.assertIn("states figures its cited sources do not", message)
        self.assertIn("2025", message)

    def test_a_series_held_to_its_figures_loads(self):
        for text in ("Synthetic monthly copper price, 2026 US dollars per tonne",
                     "Synthetic monthly copper price, 9,180.25 at opening and 9,500 latest, US dollars per tonne"):
            with self.subTest(series=text):
                self.assertEqual(self.accepted(self.series(text))["price_record"]["series"], text)


class TranscriptionMethodTests(Theses):  # Ruling R17.
    def method(self, text):
        return lambda b: find(b["sources"], "iea-2021")["transcription"].update(method=text)

    def test_the_two_methods_are_the_only_ones(self):
        self.assertEqual(thesis_schema.TRANSCRIPTION_METHODS, (PAGE_IMAGE, TEXT_LAYER))
        self.assertEqual(thesis_schema.TRANSCRIBED, PAGE_IMAGE)

    def test_a_pdf_transcribed_from_its_text_layer_loads_and_the_view_prints_that_method(self):
        loaded = self.accepted(self.method(TEXT_LAYER))
        self.assertEqual(find(loaded["sources"], "iea-2021")["transcription"]["method"], TEXT_LAYER)
        self.assertIn("transcription", thesis_view.SOURCE_SHOWN)
        self.accepted(self.method(PAGE_IMAGE))

    def test_any_other_method_is_refused(self):
        for text in ("transcribed", "Transcribed from the page image", "transcribed from the PDF text layer",
                     "transcribed from the page image ", "read by a library", ""):
            with self.subTest(method=text):
                self.refused(self.method(text), "sources[iea-2021].transcription.method")


class CentsPerPoundTests(Theses):  # Ruling R18.
    def test_the_unit_is_listed_and_labelled(self):
        self.assertIn(CENTS, thesis_schema.UNITS)
        self.assertEqual(thesis_view.UNIT_LABELS[CENTS], "US cents per pound")
        self.assertEqual(list(thesis_view.UNIT_LABELS), list(thesis_schema.UNITS))

    def test_a_price_record_in_cents_per_pound_loads(self):
        loaded = self.accepted(self._record_in_cents)
        self.assertEqual(figure(loaded, loaded["price_record"]["opening"])["unit"], CENTS)
        self.assertEqual(figure(loaded, loaded["price_record"]["latest"])["unit"], CENTS)

    @staticmethod
    def _record_in_cents(body):
        # Re-point the computed exposure row at a figure left in dollars per tonne so only the record is in cents.
        body["figures"].append(dict(figure(body, "wb-copper-2026m10"), id="synthetic-price-per-tonne"))
        body["exposure"]["moved"][2]["amount"]["price"] = "synthetic-price-per-tonne"
        body["exposure"]["moved"][2]["how"]["cites"] = ["iea21-ev-copper", "synthetic-price-per-tonne",
                                                        "maker-price-2025"]
        cents("wb-copper-2026m08", "wb-copper-2026m10")(body)

    def test_mixed_units_are_refused(self):
        def opening_only(body):
            body["figures"].append(dict(figure(body, "wb-copper-2026m10"), id="synthetic-price-per-tonne"))
            body["exposure"]["moved"][2]["amount"]["price"] = "synthetic-price-per-tonne"
            body["exposure"]["moved"][2]["how"]["cites"] = ["iea21-ev-copper", "synthetic-price-per-tonne",
                                                            "maker-price-2025"]
            cents("wb-copper-2026m08")(body)
        message = self.refused(opening_only, "price_record")
        self.assertIn("usd_per_tonne", message)
        self.assertIn(CENTS, message)

    def test_other_units_are_refused_in_the_price_record(self):
        self.refused(lambda b: figure(b, "wb-copper-2026m08").update(unit="usd_per_lb"), "price_record.opening")

    def test_a_cents_figure_is_not_a_per_unit_cost_price(self):
        self.refused(cents("wb-copper-2026m10"), "exposure.moved[2].amount.price")


if __name__ == "__main__":
    unittest.main()
