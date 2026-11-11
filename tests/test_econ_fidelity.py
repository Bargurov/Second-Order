"""Economic meaning across the shared news workflow and its reader surfaces (econ-fidelity-0.1, brief-stages-0.2).

Two kinds of evidence. The five outcomes of the 28 October fresh update (tests/fresh_update_cases.json: real, not
SYNTHETIC; our saved model replies and briefs, with only the source passages their checks need) are regression cases:
each historical outcome must still reproduce under the contract it was sent under, and the general rule it exposed must
hold. SYNTHETIC figures and stories (news_desk_fakes) cover the negative cases. Nothing reaches a network, and passing
these checks is not evidence that an explanation is economically right."""
import copy
import json
from pathlib import Path
import re
import unittest

from news_desk_fakes import SALES, TARIFF, tariff_economics
from second_order import (brief_drafting, brief_stages, brief_wire, econ_fidelity, econ_framework, story_briefs,
                          story_economics)
from second_order.accounts import AccountsRefused
from test_news_economics import World, explanation, figure

CASES = json.loads((Path(__file__).with_name("fresh_update_cases.json")).read_text(encoding="utf-8"))["cases"]


def case(name: str) -> dict:
    return copy.deepcopy(CASES[name])


def found(name: str) -> dict:
    """The case's evidence as the application reads it (story_economics.evidence), from the kept source passages."""
    return story_economics.evidence({"reports": case(name)["reports"]}, None, None, case(name)["released_at"])


def material(name: str) -> dict:
    return {"reports": case(name)["reports"]}


def row(**fields) -> dict:
    """A SYNTHETIC checked figure."""
    base = {"id": "f1", "label": "SYNTHETIC sales", "value": 676000, "decimals": 0, "unit": "houses", "measure": "level",
            "period": "September 2026", "basis": "not_stated", "seasonal": "seasonally_adjusted", "price": False,
            "source": "report:x", "quote": "SYNTHETIC: sales were at a seasonally adjusted annual rate of 676,000.",
            "sign": "as_quoted", "sign_words": None, "direction_check": "as_quoted", "bound": "exact",
            "statistic": "observed", "stock_flow": "flow_annual_rate", "vintage": {"label": None}}
    base.update(fields)
    return base


class FigureMeaningTest(unittest.TestCase):
    """What changes the kind of number a figure is goes wherever the figure goes, from its stated metadata only."""

    def test_an_annual_rate_is_never_shown_as_a_months_count(self):
        rate = row()
        self.assertEqual(econ_fidelity.render("SYNTHETIC: sales were {f1} in September.", {"f1": rate}),
                         "SYNTHETIC: sales were 676,000 houses (seasonally adjusted annual rate) in September.")
        self.assertIn("676,000 houses (seasonally adjusted annual rate): SYNTHETIC sales (September 2026)",
                      econ_fidelity.reference(rate))
        monthly = row(stock_flow="flow_per_month", seasonal="not_stated", value=56000, quote="56,000")
        self.assertEqual(econ_fidelity.render("SYNTHETIC: {f1} were sold.", {"f1": monthly}),
                         "SYNTHETIC: 56,000 houses were sold.")  # A month's total, and nothing not stated is shown.
        unadjusted = row(seasonal="not_seasonally_adjusted")
        self.assertIn("(annual rate, not seasonally adjusted)", econ_fidelity.render("{f1}", {"f1": unadjusted}))
        difference = {"id": "c1", "op": "difference", "inputs": ["f1", "f2"], "label": "SYNTHETIC change",
                      "value": -4000, "unit": "houses", "decimals": 0, "seasonal": "seasonally_adjusted",
                      "basis": "not_stated", "bound": "exact", "measure": "change"}
        rows = {"f1": rate, "f2": row(id="f2", value=680000), "c1": difference}
        self.assertIn("(seasonally adjusted annual rate)", econ_fidelity.render("SYNTHETIC: {c1}.", rows))

    def test_a_sentence_that_says_it_already_is_not_repeated(self):
        rate = row()
        self.assertEqual(econ_fidelity.render("SYNTHETIC: at a seasonally adjusted annual rate of {f1}.", {"f1": rate}),
                         "SYNTHETIC: at a seasonally adjusted annual rate of 676,000 houses.")
        adjusted = row(stock_flow="not_applicable", measure="change", value=-0.6, decimals=1, unit="percent")
        self.assertEqual(econ_fidelity.render("SYNTHETIC: {f1}, not seasonally adjusted elsewhere.",
                                              {"f1": adjusted}),
                         "SYNTHETIC: −0.6% (seasonally adjusted), not seasonally adjusted elsewhere.")
        bounded = row(stock_flow="not_applicable", bound="upper_bound", seasonal="not_stated", value=95,
                      unit="percent", measure="share")
        self.assertEqual(econ_fidelity.render("SYNTHETIC: up to {f1}.", {"f1": bounded}), "SYNTHETIC: up to 95%.")

    def test_a_point_estimate_inside_its_stated_margin_is_never_shown_as_a_definite_change(self):
        change = row(measure="change", unit="percent", value=-0.6, stock_flow="not_applicable",
                     quote="This is 0.6 percent (+/- 13.8%)* below the revised estimate")
        self.assertEqual(econ_fidelity.margin(change)["display"], "±13.8%")
        self.assertIn("stated margin ±13.8%, wider than the change", econ_fidelity.render("{f1}", {"f1": change}))
        narrow = row(measure="growth_rate", unit="percent", value=5.2, stock_flow="not_applicable",
                     quote="SYNTHETIC: up 5.2 percent (±1.0%)")
        self.assertEqual(econ_fidelity.margin(narrow)["text"], "stated margin ±1.0%")
        apart = row(measure="change", unit="percent", value=3, stock_flow="not_applicable",
                    quote="SYNTHETIC: sales rose 3 percent, and the error was +/- 1 percent")
        self.assertIsNone(econ_fidelity.margin(apart))  # A margin elsewhere in the quote is not this number's.
        self.assertIsNone(econ_fidelity.margin(row()))

    def test_nominal_or_real_is_stated_only_where_it_applies(self):
        self.assertFalse(econ_fidelity.shows_basis(row()))  # A count of houses is neither.
        self.assertTrue(econ_fidelity.shows_basis(row(unit="billion dollars")))
        self.assertTrue(econ_fidelity.shows_basis(row(unit="percent", measure="growth_rate")))
        self.assertFalse(econ_fidelity.shows_basis(row(unit="percent", measure="rate")))
        self.assertTrue(econ_fidelity.shows_basis(row(basis="real", unit="percent", measure="rate")))  # As stated.
        self.assertEqual(econ_fidelity.qualifiers(row(basis="real", stock_flow="not_applicable",
                                                      seasonal="not_stated")), ["inflation-adjusted"])
        self.assertEqual(econ_fidelity.qualifiers(row(statistic="median", stock_flow="not_applicable",
                                                      seasonal="not_stated")), ["a median of survey answers"])

    def test_the_home_sales_rate_and_margin_reach_every_reader_surface(self):
        homes = case("homes")
        economics = homes["content"]["economics"]
        view = story_economics.reader_view(economics, homes["content"]["facts"])
        what = view["summary"]["what_changed"]
        self.assertIn("676,000 houses (seasonally adjusted annual rate) in September 2026", what)
        self.assertIn("−0.6% (seasonally adjusted; stated margin ±13.8%, wider than the change)", what)
        self.assertIn("680,000 houses (seasonally adjusted annual rate)", what)
        labels = [ref["label"] for ref in view["summary"]["what_changed_basis"]]
        self.assertIn("676,000 houses (seasonally adjusted annual rate): September 2026 new home sales "
                      "(September 2026; September 2026 estimate)", labels)
        figures = {row["id"]: row for row in view["figures"]}
        self.assertEqual(figures["f3"]["margin"], "±13.8%")
        self.assertEqual((figures["f1"]["basis_label"], figures["f3"]["basis_label"]),
                         (None, "nominal or real not stated"))
        self.assertEqual(figures["f1"]["stock_flow_label"], "a flow at an annual rate")
        self.assertIn("Here the −0.6% (seasonally adjusted) change sits well inside the stated margin of error",
                      view["summary"]["why_it_matters"])  # Its sentence already speaks of the margin.
        self.assertIsNone(re.search(r"\{[fc]\d{1,2}\}", json.dumps(view)))  # The client refuses any left unrendered.


class ReferenceTest(unittest.TestCase):
    """A reference is rendered where it is permitted and stops publication anywhere else."""

    def test_every_permitted_text_is_rendered_including_assumptions(self):
        homes = case("homes")
        economics = homes["content"]["economics"]
        economics["assumptions"].append({"id": "a3", "text": "SYNTHETIC: {f1} holds after revision."})
        view = story_economics.reader_view(economics, homes["content"]["facts"])
        self.assertEqual(view["assumptions"][-1]["text"],
                         "SYNTHETIC: 676,000 houses (seasonally adjusted annual rate) holds after revision.")
        self.assertEqual(econ_fidelity.reference_findings(homes["content"]), [])

    def test_a_reference_outside_the_explanations_texts_or_naming_nothing_stops_publication(self):
        homes = case("homes")
        content = homes["content"]
        content["summary"] = "SYNTHETIC: sales were {f1}."
        content["uncertainties"][0] = "SYNTHETIC: whether {F1} holds."
        content["economics"]["channels"][0]["affected"][0]["name"] = "SYNTHETIC builders of {f1}"
        content["economics"]["watch"][0]["observable"] = "SYNTHETIC figure:f2"
        content["economics"]["channels"][0]["text"] += " See {f 1}."
        rows = {(row["where"], row["rule"], row["matched"]) for row in econ_fidelity.reference_findings(content)}
        self.assertEqual(rows, {
            ("summary", "placeholder_in_brief", "{f1}"),
            ("uncertainties[0]", "unresolved_reference", "{F1}"),
            ("economics.channels[0].affected[0].name", "reference_in_label", "{f1}"),
            ("economics.watch[0].observable", "reference_in_label", "figure:f2"),
            ("economics.channels[0]", "unresolved_reference", "{f 1}")})

    def test_the_climate_publication_stop_reproduces_and_its_cause_is_in_the_request_contract(self):
        climate = case("climate")
        self.assertEqual(climate["stage_versions"], ["brief-evidence-1", "brief-explanation-1"])
        version = climate["stage_versions"][1]  # Decoded and assembled under the contract it was sent under.
        decoded = brief_wire.decode(climate["reply"], brief_stages.stage_2_schema(version=version))
        content = brief_stages.assemble(climate["first"], decoded, version)
        stops = brief_stages.coherence(content, found("climate"))
        self.assertIn({"where": "summary", "rule": "placeholder_in_brief", "matched": "{f1}",
                       "detail": econ_fidelity.PLACEHOLDER_IN_BRIEF}, stops)
        self.assertIn(climate["saved_findings"][0], stops)  # The saved draft's own finding, unchanged.
        self.assertIn("It cites estimated climate losses of {f1} a year", climate["first"]["change"]["text"])
        self.assertIn("It cites estimated climate losses of {f1} a year", content["summary"])  # Copied from stage 1.
        # brief-explanation-2 scopes references to the explanation's texts and shows the development in words.
        system = brief_stages.system(2)
        self.assertNotIn("In texts, write figures and calculations as {f1}", system)
        self.assertIn("never {f1} or {c1}, even where the foundations' development uses them", system)
        guide = brief_stages.foundations_text(climate["first"], climate["first_stage"])
        words = next(line for line in guide.splitlines() if line.startswith("What changed, in words"))
        self.assertIn("about 50 EUR billion (nominal) a year", words)
        self.assertNotIn("{f", words)
        corrected = copy.deepcopy(content)  # An assistant's correction would state the quoted words instead.
        corrected["summary"] = corrected["summary"].replace("{f1}", "about €50 billion").replace("{f2}",
                                                                                                 "around €70 billion")
        self.assertEqual(econ_fidelity.reference_findings(corrected), [])


class CategoryTest(unittest.TestCase):
    """A classification of goods is the evidence's; other categories stay a semantic check."""

    def test_durable_goods_never_become_capital_or_all_manufactured_goods(self):
        durables = case("durables")
        rows = econ_fidelity.category_findings(durables["content"], found("durables"))
        self.assertEqual({(row["where"], row["matched"]) for row in rows},
                         {("economics.channels[0]", "manufactured goods"),
                          ("economics.channels[0].affected[1].how", "capital goods")})
        corrected = durables["content"]
        corrected["economics"]["channels"][0]["text"] = corrected["economics"]["channels"][0]["text"].replace(
            "manufactured goods", "manufactured durable goods")
        corrected["economics"]["channels"][0]["affected"][1]["how"] = "Orders for durable goods may later mean more " \
                                                                      "production and hiring."
        self.assertEqual(econ_fidelity.category_findings(corrected, found("durables")), [])

    def test_a_classification_the_evidence_names_passes_and_an_origin_is_not_a_classification(self):
        evidence = {"text": "SYNTHETIC: new orders for nondefense capital goods rose; U.S. goods exports fell."}
        content = {"headline": "SYNTHETIC: capital goods orders rose", "summary": "SYNTHETIC: Canadian goods and "
                   "U.S. goods, while goods moved at home goods stores.", "facts": [], "implications": [],
                   "themes": [], "uncertainties": ["SYNTHETIC: non-durable goods are not covered."], "missing": []}
        rows = econ_fidelity.category_findings(content, evidence)
        self.assertEqual([(row["where"], row["matched"]) for row in rows],
                         [("uncertainties[0]", "non-durable goods")])


class ScaleTest(unittest.TestCase):
    """A figure keeps the number as its quote writes it, and its unit the scale word written after it."""
    QUOTE = "between 2023 and 2025, about 4.9 million Afghans returned to the country"

    def problem(self, value, unit, quote=QUOTE):
        return econ_fidelity.scale_problem({"value": value, "unit": unit, "quote": quote}, "Figure 1")

    def test_a_scale_word_dropped_converted_or_invented_is_found(self):
        self.assertIn("is never converted", self.problem(4900000, "people"))  # Exact decimal arithmetic.
        self.assertIn("leaves the scale out", self.problem(4.9, "people"))  # A millionfold error otherwise.
        self.assertIn("says billion", self.problem(4.9, "billion people"))
        self.assertIn("says thousand", self.problem(650000, "thousand people", "of 650,000 people"))
        self.assertIsNone(self.problem(4.9, "million people"))
        self.assertIsNone(self.problem(5, "billion euros", "a 5 bn euro fund"))
        self.assertIsNone(self.problem(345.4, "billion dollars", "increased $6.3 billion or 1.8 percent to "
                                                                 "$345.4 billion"))
        self.assertIsNone(self.problem(676000, "houses", "annual rate of 676,000."))
        self.assertIsNone(self.problem(-0.6, "percent", "This is 0.6 percent (+/- 13.8%)* below"))

    def test_every_saved_scaled_figure_already_keeps_the_convention(self):
        for name in ("homes", "durables"):
            for figure_row in case(name)["content"]["economics"]["figures"]:
                with self.subTest(name=name, figure=figure_row["id"]):
                    self.assertIsNone(econ_fidelity.scale_problem(figure_row, figure_row["id"]))
        for name in ("climate", "ecb"):
            for figure_row in case(name)["first"]["checked"]["figures"]:
                with self.subTest(name=name, figure=figure_row["id"]):
                    self.assertIsNone(econ_fidelity.scale_problem(figure_row, figure_row["id"]))

    def test_the_undp_refusal_reproduces_and_the_new_contract_refuses_every_scale_error(self):
        undp = case("undp")
        self.assertEqual(undp["stage_version"], "brief-evidence-1")
        reply = brief_wire.decode(undp["reply"], brief_stages.STAGE_1_SCHEMAS["brief-evidence-1"])
        with self.assertRaises(AccountsRefused) as original:
            brief_stages.foundations(reply, material("undp"), found("undp"), stage_version="brief-evidence-1")
        self.assertEqual(str(original.exception), undp["outcome_detail"])  # The historical outcome, unchanged.
        later = "brief-evidence-2"  # The contract that introduced the scale rule; brief-evidence-3 keeps it.
        current = {**reply, "change_form": "statement", "change_respondents": "",  # SYNTHETIC: classified, as now,
                   "facts": [{**fact, **{name: "" for name in brief_stages.CLAIM_FIELDS}}  # each fact recording no claim.
                             for fact in reply["facts"]]}
        for contract, sent in ((later, reply), (brief_stages.STAGE_VERSIONS[1], current)):
            with self.subTest(contract=contract), self.assertRaisesRegex(AccountsRefused, "gives 4900000"):
                brief_stages.foundations(sent, material("undp"), found("undp"), stage_version=contract)
        with self.assertRaises(AccountsRefused) as now:
            brief_stages.foundations(reply, material("undp"), found("undp"), stage_version=later)
        self.assertIn("gives 4900000 for the quoted “4.9 million”", str(now.exception))
        dropped = copy.deepcopy(reply)
        dropped["figures"][0].update(value=4.9)  # Unit "people": accepted under brief-evidence-1, refused now.
        record = brief_stages.foundations(dropped, material("undp"), found("undp"), stage_version="brief-evidence-1")
        self.assertEqual(record["checked"]["figures"][0]["display"], "about 4.9 people")
        with self.assertRaisesRegex(AccountsRefused, "leaves the scale out"):
            brief_stages.foundations(dropped, material("undp"), found("undp"), stage_version=later)
        kept = copy.deepcopy(reply)
        kept["figures"][0].update(value=4.9, unit="million people")
        record = brief_stages.foundations(kept, material("undp"), found("undp"), stage_version=later)
        self.assertEqual(record["checked"]["figures"][0]["display"], "about 4.9 million people")
        self.assertIn("\"about 4.9 million Afghans\" is value 4.9, unit \"million people\"", brief_stages.system(1))


class FrameworkApplicabilityTest(unittest.TestCase):
    """A statistical release is classified by what it measures; a request offers only the framework notes that apply
    to its development (from brief-explanation-3 by subject, form of evidence and respondents together:
    test_econ_form_subject)."""

    def test_the_ecb_refusal_reproduces_under_the_framework_it_was_checked_with(self):
        ecb = case("ecb")
        self.assertEqual((ecb["first"]["change"]["instrument"], ecb["outcome"]), ("official_statistic", "invalid"))
        version = ecb["stage_versions"][1]  # Decoded and assembled under the contract it was sent under.
        decoded = brief_wire.decode(ecb["reply"], brief_stages.stage_2_schema(version=version))
        content = brief_stages.assemble(ecb["first"], decoded, version)
        used = {row["entry_id"] for row in ecb["reports"]}
        with self.assertRaises(AccountsRefused) as refused:  # Under the contract and framework it was checked with.
            story_briefs.checked_content(content, used, found("ecb"), analysis_version="econ-explanation-0.3")
        self.assertEqual(str(refused.exception), ecb["outcome_detail"])

    def test_a_request_offers_only_the_notes_that_apply_to_its_development(self):
        release = {"stage": "observation", "instrument": "economic_activity", "form": "reported_observation",
                   "respondents": None}
        listed = brief_drafting.framework_text(release)
        for name, note in econ_framework.framework()["notes"].items():
            with self.subTest(note=name):
                applies = econ_framework.ANY in note["applies_to"] or "economic_activity" in note["applies_to"]
                self.assertEqual(f"- {name} (" in listed, applies and "reported_observation" in note["forms"])
        self.assertNotIn("credit-conditions", listed)
        self.assertIn("credit-conditions", brief_drafting.framework_text())  # Every note where nothing is classified.
        system = brief_stages.system(2)
        self.assertNotIn("channels[].note: tariff-pass-through", system)  # No longer every note as a choice.
        self.assertIn("listed as applying to this story's subject, form of evidence and respondents", system)

    def test_a_survey_of_credit_conditions_is_read_as_what_it_measures_never_as_a_policy_decision(self):
        rules = brief_stages.system(1)
        self.assertIn("a survey of credit or lending conditions is financial_conditions", rules)
        self.assertIn("a central bank publishing a survey is not making a policy decision", rules)
        # brief-explanation-2 accepted the firm note for a bank survey reclassified by its subject alone; from
        # brief-explanation-3 its form and respondents are checked too (test_econ_form_subject.EcbCaseTest).


class ContractVersionTest(unittest.TestCase):
    def test_saved_requests_of_the_earlier_contract_are_superseded_and_read_as_before(self):
        self.assertEqual((brief_stages.VERSION, brief_stages.STAGE_VERSIONS),
                         ("brief-stages-0.8", {1: "brief-evidence-8", 2: "brief-explanation-6"}))
        for stage, version in ((1, "brief-evidence-1"), (2, "brief-explanation-1"), (2, "brief-summary-1"),
                               (1, "brief-evidence-2"), (2, "brief-explanation-2")):
            with self.subTest(version=version):
                reason = brief_drafting.superseded({"stage": stage, "stage_version": version,
                                                    "stages_version": "brief-stages-0.1"})
                self.assertIn("an earlier request contract", reason)
        for stage, version, stages in ((1, "brief-evidence-2", "brief-stages-0.2"),
                                       (1, "brief-evidence-3", "brief-stages-0.3"),
                                       (2, "brief-explanation-3", "brief-stages-0.3"),
                                       (1, "brief-evidence-4", "brief-stages-0.4"),
                                       (2, "brief-explanation-4", "brief-stages-0.4"),
                                       (2, "brief-summary-2", "brief-stages-0.4"),
                                       (1, "brief-evidence-5", "brief-stages-0.5"),
                                       (2, "brief-explanation-5", "brief-stages-0.5"),
                                       (2, "brief-summary-3", "brief-stages-0.5"),
                                       (1, "brief-evidence-6", "brief-stages-0.6"),
                                       (2, "brief-explanation-6", "brief-stages-0.6"),
                                       (2, "brief-summary-4", "brief-stages-0.6"),
                                       (1, "brief-evidence-7", "brief-stages-0.7"),
                                       (2, "brief-explanation-6", "brief-stages-0.7"),
                                       (2, "brief-summary-4", "brief-stages-0.7")):
            with self.subTest(version=version):
                self.assertIn("an earlier request contract", brief_drafting.superseded(
                    {"stage": stage, "stage_version": version, "stages_version": stages}))
        for stage, version in ((1, "brief-evidence-8"), (2, "brief-explanation-6"), (2, "brief-summary-4")):
            with self.subTest(current=version):
                self.assertIsNone(brief_drafting.superseded({"stage": stage, "stage_version": version,
                                                             "stages_version": "brief-stages-0.8"}))


class SavedVersionTest(unittest.TestCase):
    """econ-fidelity's stops are recorded with every new version; earlier versions keep the guard they were saved
    with."""

    def test_a_new_version_records_its_fidelity_findings_and_version(self):
        world = World(self)
        tariff = tariff_economics()
        tariff["channels"][0]["affected"][0]["how"] = "SYNTHETIC: buyers of capital goods could pay more."
        saved = world.save(TARIFF, tariff)
        self.assertEqual(saved["guard"]["fidelity_version"], econ_fidelity.FIDELITY_VERSION)
        self.assertIn(("economics.channels[0].affected[0].how", "category_not_in_evidence"),
                      {(row["where"], row["rule"]) for row in saved["guard"]["findings"]})
        unscaled = explanation(
            change={"stage": "observation", "instrument": "economic_activity", "form": "reported_observation",
                    "respondents": None, "basis": ["fact:1", "figure:f1"],
                    "text": "SYNTHETIC: retail sales were {f1} in September."},
            figures=[figure("f1", 745.0, "reach 745.0 billion", unit="dollars", measure="level",
                            period="September 2026", stock_flow="flow_per_month")])
        self.assertIn("scale_mismatch", world.rules(SALES, unscaled))
        self.assertNotIn("scale_mismatch", world.rules(SALES, {**unscaled, "figures": [
            figure("f1", 745.0, "reach 745.0 billion", unit="billion dollars", measure="level",
                   period="September 2026", stock_flow="flow_per_month")]}))

    def test_a_finding_both_checks_make_is_recorded_once(self):
        content = {"headline": "SYNTHETIC", "summary": "SYNTHETIC: {f1}.", "facts": [], "implications": [],
                   "themes": [], "uncertainties": [], "missing": []}
        both = brief_stages.coherence({**content, "facts": [], "implications": []},
                                      {"numbers": set()}) + econ_fidelity.reference_findings(content)
        self.assertEqual(len(story_briefs.merged([], both)), 1)


if __name__ == "__main__":
    unittest.main()
