"""The form of economic evidence and the subject it describes, kept apart and used together (econ-explanation-0.4,
econ-framework-0.3, econ-calc-0.3, econ-fidelity-0.2, brief-stages-0.3, news-explanations-0.4).

What changed is classified twice: by its subject (what it changes or describes: credit conditions, prices, housing, an
import tariff, …) and by the form of its evidence (a reported observation, respondents' answers in a survey, a forecast
or scenario, an announced or adopted decision, a statement of views, or an unclear form), with the respondents of a
survey. A framework note states the subjects, forms and respondents its reasoning assumes, and applies only where all
three match: a subject match alone never admits a note that assumes another kind of evidence or other respondents.

Two kinds of evidence, as in test_econ_fidelity. The saved ECB and climate cases of 28 October
(tests/fresh_update_cases.json, real) are regression cases: each historical outcome must still reproduce under the
contract it was sent under, and the general rule must hold for the case reclassified. SYNTHETIC surveys and stories
(news_desk_fakes) give the variations. No story ID, publisher or title decides any outcome here. Nothing reaches a
network, and passing these checks is not evidence that an explanation is economically right."""
import copy
import json
from pathlib import Path
import unittest

from news_desk_fakes import BANKS, FIRMS, START, TARIFF, survey_items, tariff_economics
from second_order import (brief_drafting, brief_stages, brief_wire, econ_calc, econ_classification, econ_fidelity,
                          econ_framework, economics_view, news_explanations, newsroom_store as ns, story_briefs,
                          story_economics)
from second_order.accounts import AccountsRefused
from test_news_economics import World, explanation, figure

CASES = json.loads((Path(__file__).with_name("fresh_update_cases.json")).read_text(encoding="utf-8"))["cases"]
LEGACY = "econ-explanation-0.3"
LEGACY_FRAMEWORK = "a2646115201c7e5afb24435a1c101cc38cd3f2cccbf2b304de13557489fe4c15"  # econ-framework-0.2


def case(name: str) -> dict:
    return copy.deepcopy(CASES[name])


def found(name: str, extra: dict[str, list[str]] | None = None) -> dict:
    """The case's evidence as the application reads it, from the kept source passages (and ``extra`` passages per
    report, appended to its kept excerpt)."""
    reports = case(name)["reports"]
    for row in reports:
        more = (extra or {}).get(row["entry_id"])
        if more:
            row["excerpt"] = "\n".join(part for part in [row["excerpt"], *more] if part)
    return story_economics.evidence({"reports": reports}, None, None, case(name)["released_at"])


def change(subject: str, form: str, respondents: str | None = None, stage: str = "observation",
           text: str = "SYNTHETIC: the report states a development ({f1}).") -> dict:
    return {"stage": stage, "instrument": subject, "form": form, "respondents": respondents,
            "basis": ["fact:1", "figure:f1"], "text": text}


def net(fid: str, value, quote: str, **extra) -> dict:
    """A SYNTHETIC net percentage: the share of respondents reporting one direction minus the share reporting the
    other."""
    return figure(fid, value, quote, **{"measure": "net_percentage", "basis": "not_applicable",
                                        "seasonal": "not_applicable", "statistic": "other_summary",
                                        "label": "SYNTHETIC net percentage", **extra})


def channel(note: str | None, support: str = "framework", conditions: str | None = None) -> dict:
    return {"id": "m1", "scope": "macro", "support": support, "note": note, "steps": ["SYNTHETIC step"],
            "text": "SYNTHETIC: borrowers who rely on bank loans could find credit harder to obtain.",
            "affected": [{"kind": "firms", "name": "SYNTHETIC borrowers", "how": "could find loans harder to get"}],
            "conditions": conditions, "horizon": "quarters", "basis": ["fact:1"], "assumptions": []}


def survey(respondents: str, note: str | None, **parts) -> dict:
    """A SYNTHETIC explanation of a credit-conditions survey answered by ``respondents``."""
    quote = "net percentage of 9% of banks" if respondents == "banks" else "net percentage of -5%"
    value = 9 if respondents == "banks" else -5
    return explanation(**{"change": change("financial_conditions", "survey_answers", respondents),
                          "figures": [net("f1", value, quote)],
                          "channels": [channel(note, "framework" if note else "event_evidence")], **parts})


class ClassificationTest(unittest.TestCase):
    """Form, subject and respondents are recorded apart, refused where they contradict the stage, and shown."""

    def test_form_subject_and_respondents_are_recorded_apart_and_shown_to_readers(self):
        world = World(self, extra=survey_items(START))
        row = world.save(BANKS, survey("banks", "bank-lending-survey"))
        economics = row["content"]["economics"]
        self.assertEqual(economics["analysis_version"], story_economics.ANALYSIS_VERSION)
        self.assertEqual({key: economics["change"][key] for key in ("stage", "instrument", "form", "respondents")},
                         {"stage": "observation", "instrument": "financial_conditions", "form": "survey_answers",
                          "respondents": "banks"})
        summary = story_economics.reader_view(economics, row["content"]["facts"])["summary"]
        self.assertEqual((summary["instrument_label"], summary["form_label"], summary["respondents_label"]),
                         ("credit or financing conditions", "respondents' answers in a survey", "banks"))
        self.assertIsNone(summary["classification_note"])  # Newly classified evidence, not legacy.

    def test_a_form_never_takes_a_stage_it_cannot_have(self):
        world = World(self, extra=survey_items(START))
        refused = {
            "a survey is observed answers, never a decision": (
                change("financial_conditions", "survey_answers", "banks", stage="decision"),
                "respondents' answers in a survey, so its stage is observation"),
            "a forecast is not a realised outcome": (
                change("financial_conditions", "forecast_or_scenario", stage="observation"),
                "a forecast, projection or scenario, so its stage is forecast"),
            "an announcement is not an observation": (
                change("monetary_policy", "announcement_or_decision", stage="observation"),
                "an announced or adopted decision, proposal or measure, so its stage is"),
            "a survey names its respondents": (
                change("financial_conditions", "survey_answers", None), "names whose answers it reports"),
            "only a survey has respondents": (
                change("financial_conditions", "reported_observation", "banks"), "Only a survey has respondents"),
            "an official statistic is a form, not a subject": (
                change("official_statistic", "reported_observation"), "is a form of evidence, not a subject"),
            "the form is one of the listed forms": (
                change("financial_conditions", "press_release"), "names the form of its evidence"),
        }
        for name, (what, message) in refused.items():
            with self.subTest(name):
                with self.assertRaisesRegex(AccountsRefused, message):
                    world.save(BANKS, survey("banks", None, change=what))
        legacy = {key: value for key, value in change("financial_conditions", "survey_answers", "banks").items()
                  if key not in ("form", "respondents")}
        with self.assertRaisesRegex(AccountsRefused, "change has exactly"):  # Never upgraded by filling in a form.
            world.save(BANKS, survey("banks", None, change=legacy))

    def test_an_unclear_form_keeps_its_uncertainty_and_admits_no_mechanism(self):
        world = World(self, extra=survey_items(START))
        unclear = change("financial_conditions", "unclear")
        with self.assertRaisesRegex(AccountsRefused, "not on evidence of an unclear form"):
            world.save(BANKS, survey("banks", "bank-lending-survey", change=unclear))
        row = world.save(BANKS, survey("banks", None, change=unclear))  # Its own sources may still state one.
        summary = story_economics.reader_view(row["content"]["economics"], row["content"]["facts"])["summary"]
        self.assertEqual(summary["form_label"], "evidence of an unclear form")


class RespondentsTest(unittest.TestCase):
    """A subject match alone is not enough: a note applies only to the evidence and respondents it describes."""

    def test_bank_and_firm_surveys_stay_distinct(self):
        world = World(self, extra=survey_items(START))
        with self.assertRaisesRegex(AccountsRefused, "“Firms' access to finance” describes the answers of firms, "
                                                     "not of banks"):
            world.save(BANKS, survey("banks", "credit-conditions"))
        self.assertEqual(world.save(BANKS, survey("banks", "bank-lending-survey"))["content"]["economics"]
                         ["channels"][0]["note"], "bank-lending-survey")
        with self.assertRaisesRegex(AccountsRefused, "describes the answers of banks, not of firms"):
            world.save(FIRMS, survey("firms", "bank-lending-survey"))
        self.assertEqual(world.save(FIRMS, survey("firms", "credit-conditions"))["content"]["economics"]
                         ["channels"][0]["note"], "credit-conditions")

    def test_a_survey_or_a_forecast_never_becomes_a_policy_decision(self):
        world = World(self, extra=survey_items(START))
        # A central bank's survey, mislabelled as monetary policy, still never takes the policy mechanism.
        as_policy = change("monetary_policy", "survey_answers", "banks")
        with self.assertRaisesRegex(AccountsRefused, "“How monetary policy reaches the economy” rests on .*not on "
                                                     "respondents' answers in a survey"):
            world.save(BANKS, survey("banks", "monetary-transmission", change=as_policy))
        with self.assertRaisesRegex(AccountsRefused, "“How monetary policy reaches the economy” applies to "
                                                     "monetary policy, not to credit or financing conditions"):
            world.save(BANKS, survey("banks", "monetary-transmission"))  # Credit conditions: not the policy either.
        projected = change("financial_conditions", "forecast_or_scenario", stage="forecast")
        with self.assertRaisesRegex(AccountsRefused, "states the condition under which it would follow"):
            world.save(BANKS, survey("banks", None, change=projected))  # A forecast's channels stay conditional.

    def test_the_applicable_mechanism_is_available_for_each_kind_of_evidence(self):
        notes = econ_framework.framework()["notes"]
        listed = lambda what: [note["id"] for note in econ_classification.applicable(notes, what)]  # noqa: E731
        self.assertEqual(listed(change("financial_conditions", "survey_answers", "banks")), ["bank-lending-survey"])
        self.assertEqual(listed(change("financial_conditions", "survey_answers", "firms")), ["credit-conditions"])
        self.assertEqual(listed(change("inflation", "survey_answers", "households")), ["inflation-expectations"])
        self.assertEqual(set(listed(change("economic_activity", "reported_observation"))),
                         {"official-statistics", "inventory-ratio"})
        self.assertIn("monetary-transmission", listed(change("monetary_policy", "announcement_or_decision",
                                                            stage="decision")))
        self.assertEqual(listed(change("financial_conditions", "unclear")), [])
        reachable = set()
        for subject in econ_framework.SUBJECTS:
            for form in econ_framework.FORMS:
                for respondents in (econ_framework.RESPONDENTS if form == "survey_answers" else (None,)):
                    reachable |= set(listed(change(subject, form, respondents, stage="observation")))
                    reachable |= set(listed(change(subject, form, respondents, stage="decision")))
        self.assertEqual(reachable, set(notes))  # Every note applies to some evidence: none is orphaned.


class NetPercentageTest(unittest.TestCase):
    """A survey's net percentage is the share of respondents reporting one direction minus the share reporting the
    other: not a share, not a change, not a growth rate."""

    SOURCES = {"report:x": {"text": "SYNTHETIC: net percentage of -27% of banks; net percentage of -15% before.",
                            "publisher": "SYNTHETIC", "published": "2026-10-27T00:00:00+00:00", "kind": "report",
                            "as_of": None}}

    def figures(self, *rows) -> list[dict]:
        return econ_calc.checked_figures([{**row, "source": "report:x"} for row in rows], self.SOURCES)

    def test_a_net_percentage_is_its_own_measure_shown_as_what_it_is(self):
        rows = self.figures(net("f1", -27, "net percentage of -27% of banks"))
        self.assertEqual(rows[0]["display"], "−27%")
        self.assertEqual(econ_fidelity.render("SYNTHETIC: demand for housing loans fell ({f1}).", {"f1": rows[0]}),
                         "SYNTHETIC: demand for housing loans fell (−27% (net percentage of respondents)).")
        self.assertEqual(econ_fidelity.render("SYNTHETIC: a net percentage of {f1} of banks.", {"f1": rows[0]}),
                         "SYNTHETIC: a net percentage of −27% of banks.")
        view = economics_view._figure_view(rows[0])
        self.assertEqual(view["statistic_label"], "a net percentage: the share of respondents reporting one direction "
                                                  "minus the share reporting the other")
        self.assertIsNone(view["basis_label"])  # Neither nominal nor real.
        for name, extra, message in (
                ("in percent", {"unit": "percentage points"}, "in percent"),
                ("a summary of answers", {"statistic": "observed"}, "statistic other_summary"),
                ("neither stock nor flow", {"stock_flow": "flow_per_month"}, "neither a stock nor a flow")):
            with self.subTest(name):
                with self.assertRaisesRegex(AccountsRefused, message):
                    self.figures(net("f1", -27, "net percentage of -27% of banks", **extra))

    def test_a_share_lies_between_zero_and_one_hundred_percent(self):
        balance = figure("f1", -27, "net percentage of -27% of banks", measure="share", basis="not_applicable",
                         seasonal="not_applicable", statistic="other_summary")
        with self.assertRaisesRegex(AccountsRefused, "a share lies between 0% and 100%"):
            self.figures(balance)
        legacy = econ_calc.checked_figures([{**balance, "source": "report:x"}], self.SOURCES, version="econ-calc-0.2")
        self.assertEqual(legacy[0]["measure"], "share")  # How the ECB stage was checked then: it still reads so.

    def test_no_calculation_takes_a_net_percentage(self):
        rows = {row["id"]: row for row in self.figures(net("f1", -27, "net percentage of -27% of banks"),
                                                       net("f2", -15, "net percentage of -15% before"))}
        for op in ("difference", "percent_change", "share"):
            with self.subTest(op):
                with self.assertRaisesRegex(AccountsRefused, "no calculation takes one"):
                    econ_calc.computed([{"id": "c1", "op": op, "inputs": ["f1", "f2"], "label": "SYNTHETIC"}], rows)

    def test_a_net_percentage_written_as_a_change_stops_publication(self):
        world = World(self, extra=survey_items(START))
        fell = survey("banks", None, significance={"basis": ["fact:1", "figure:f1"],
                                                   "text": "SYNTHETIC: lending to firms fell by {f1}."})
        self.assertIn("net_percentage_as_change", world.rules(BANKS, fell))
        reported = survey("banks", None, significance={"basis": ["fact:1", "figure:f1"], "text": (
            "SYNTHETIC: more banks reported tighter standards than looser ones ({f1}), which may matter for "
            "borrowers.")})
        self.assertNotIn("net_percentage_as_change", world.rules(BANKS, reported))


class FrameworkTest(unittest.TestCase):
    """econ-framework-0.3: each note says what evidence it assumes; earlier versions stay readable as they were."""

    def test_every_note_states_the_subjects_forms_and_respondents_it_assumes(self):
        for name, note in econ_framework.framework()["notes"].items():
            with self.subTest(note=name):
                self.assertTrue(note["forms"] and set(note["forms"]) <= set(econ_framework.FORMS) - {"unclear"})
                self.assertTrue(set(note["applies_to"]) <= set(econ_framework.SUBJECTS) | {econ_framework.ANY})
                self.assertNotIn("official_statistic", note["applies_to"])  # A form, never a subject.
                self.assertEqual(bool(note["respondents"]), "survey_answers" in note["forms"])
        with self.assertRaisesRegex(econ_framework.FrameworkProblem, "respondents"):
            broken = copy.deepcopy(json.loads(econ_framework.PATH.read_text(encoding="utf-8")))
            next(note for note in broken["notes"] if note["id"] == "bank-lending-survey")["respondents"] = []
            econ_framework.checked(broken)

    def test_the_bank_lending_survey_note_rests_on_the_ecbs_own_documentation(self):
        note = econ_framework.framework()["notes"]["bank-lending-survey"]
        self.assertEqual((note["applies_to"], note["forms"], note["respondents"]),
                         (["financial_conditions"], ["survey_answers"], ["banks"]))
        self.assertTrue(all(row["publisher"] == "European Central Bank" and
                            row["url"].startswith("https://www.ecb.europa.eu/") for row in note["sources"]))
        urls = {row["url"] for row in note["sources"]}
        self.assertIn("https://www.ecb.europa.eu/stats/pdf/bls_user_guide_202604.en.pdf", urls)
        self.assertIn("https://www.ecb.europa.eu/stats/ecb_surveys/bank_lending_survey/html/ecb.bls_glossary.en.html",
                      urls)
        for words in ("senior loan officers", "share of banks reporting a tightening", "whether or not it results"):
            self.assertIn(words, note["mechanism"])
        for words in ("not how large", "not a growth rate", "not an observed fall in lending",
                      "not realised borrowing", "firms' own reports"):
            self.assertIn(words, note["limits"])

    def test_the_firm_note_keeps_its_words_and_now_requires_firms_answers(self):
        earlier = econ_framework.archived(LEGACY_FRAMEWORK)
        self.assertEqual(earlier["framework_version"], "econ-framework-0.2")
        self.assertNotIn("forms", earlier["notes"]["credit-conditions"])  # Read exactly as it was saved.
        now = econ_framework.framework()["notes"]["credit-conditions"]
        for field in ("title", "scope", "mechanism", "limits", "sources"):
            self.assertEqual(now[field], earlier["notes"]["credit-conditions"][field])
        self.assertEqual((now["applies_to"], now["forms"], now["respondents"]),
                         (["financial_conditions"], ["survey_answers"], ["firms"]))
        # Its reasoning is unchanged, so an explanation that used it does not read as revised.
        self.assertEqual(econ_framework.changed({"credit-conditions": earlier["notes"]["credit-conditions"]}), [])
        self.assertIsNotNone(econ_framework.archived(econ_framework.framework()["framework_sha256"]))

    def test_a_request_lists_only_the_notes_that_apply_with_their_limits(self):
        text = brief_drafting.framework_text(change("financial_conditions", "survey_answers", "banks"))
        self.assertIn("- bank-lending-survey (", text)
        for name in ("credit-conditions", "monetary-transmission", "official-statistics"):
            self.assertNotIn(f"- {name} (", text)
        self.assertIn("Limits: ", text)
        self.assertIn("survey_answers of banks", text)
        none = brief_drafting.framework_text(change("financial_conditions", "unclear"))
        self.assertIn("none applies", none)


class EcbCaseTest(unittest.TestCase):
    """The ECB bank lending survey of 27 October: refused under its original contract, and reclassified (a SYNTHETIC
    variation of the saved records) it is offered the bank note and refused the firm note."""

    def test_the_saved_refusal_reproduces_under_its_original_contract(self):
        ecb = case("ecb")
        version = ecb["stage_versions"][1]  # Decoded and assembled under the contract it was sent under.
        decoded = brief_wire.decode(ecb["reply"], brief_stages.stage_2_schema(version=version))
        content = brief_stages.assemble(ecb["first"], decoded, version)
        used = {row["entry_id"] for row in ecb["reports"]}
        with self.assertRaises(AccountsRefused) as refused:
            story_briefs.checked_content(content, used, found("ecb"), analysis_version=LEGACY)
        self.assertEqual(str(refused.exception), ecb["outcome_detail"])
        with self.assertRaises(AccountsRefused):  # Never accepted, or upgraded, under the current contract.
            story_briefs.checked_content(content, used, found("ecb"))

    def test_classified_by_form_and_subject_the_survey_takes_the_bank_note_not_the_firm_note(self):
        ecb = case("ecb")
        version = ecb["stage_versions"][1]
        decoded = brief_wire.decode(ecb["reply"], brief_stages.stage_2_schema(version=version))
        first = copy.deepcopy(ecb["first"])
        first["change"].update(instrument="financial_conditions", form="survey_answers", respondents="banks")
        for row in first["figures"]:
            row["measure"] = "net_percentage"  # Net percentages, as the release calls them; never shares.
        content = brief_stages.assemble(first, decoded, version)
        for row in content["economics"]["alternatives"]:  # Checked now: each cites the release (econ-explanation-0.6).
            row.update(support="event_evidence", assumptions=[])
        used = {row["entry_id"] for row in ecb["reports"]}
        self.assertEqual([row["note"] for row in content["economics"]["channels"]],
                         ["credit-conditions", "monetary-transmission"])
        with self.assertRaisesRegex(AccountsRefused, "describes the answers of firms, not of banks"):
            story_briefs.checked_content(content, used, found("ecb"))
        channels = content["economics"]["channels"]
        channels[0]["note"], channels[1]["note"] = "bank-lending-survey", None
        checked = story_briefs.checked_content(content, used, found("ecb"))
        self.assertEqual([row["note"] for row in checked["economics"]["channels"]], ["bank-lending-survey", None])
        self.assertEqual(checked["economics"]["change"]["stage"], "observation")
        listed = brief_drafting.framework_text(first["change"])
        self.assertIn("- bank-lending-survey (", listed)
        self.assertNotIn("- credit-conditions (", listed)


class CompatibilityTest(unittest.TestCase):
    """Earlier explanations read under the contract and framework they recorded; only those a new rule affects are
    marked for reassessment (news-explanations-0.4)."""

    def brief(self, economics: dict) -> dict:
        return {"content": {"economics": economics}, "material_sha256": "m" * 64, "at": "2026-10-28T00:00:00+00:00",
                "preparation": {"analysis": {"analysis_version": LEGACY, "calc_version": "econ-calc-0.2",
                                             "guard_version": story_economics.GUARD_VERSION,
                                             "framework_version": "econ-framework-0.2",
                                             "framework_sha256": LEGACY_FRAMEWORK}}}

    def legacy(self, note: str, **change_parts) -> dict:
        economics = case("homes")["content"]["economics"]
        economics["change"].update(change_parts)
        economics["channels"][0]["note"] = note
        economics["framework"] = econ_framework.snapshot([note], econ_framework.archived(LEGACY_FRAMEWORK))
        return economics

    def test_an_earlier_explanation_reads_under_its_recorded_contract(self):
        economics = case("homes")["content"]["economics"]
        self.assertEqual(economics["analysis_version"], LEGACY)
        summary = story_economics.reader_view(economics, case("homes")["content"]["facts"])["summary"]
        self.assertEqual(summary["instrument_label"], "an official statistic")
        self.assertIsNone(summary["form_label"])
        self.assertIn("not recorded", summary["classification_note"])  # Legacy, said to be.

    def test_only_explanations_a_new_rule_affects_need_reassessment(self):
        self.assertEqual(news_explanations.reasons(self.brief(case("homes")["content"]["economics"])), [])
        expectations = self.legacy("inflation-expectations")
        self.assertRegex("; ".join(news_explanations.reasons(self.brief(expectations))),
                         "“Households' inflation expectations” .*names no subject")
        balance = self.legacy("official-statistics")
        balance["figures"][2].update(measure="share", unit="percent", value=-0.6)
        self.assertRegex("; ".join(news_explanations.reasons(self.brief(balance))), "f3 is recorded as a share")
        firms = self.legacy("credit-conditions", instrument="financial_conditions")
        self.assertEqual(news_explanations.reasons(self.brief(firms)), [])  # Its respondents were not recorded.
        older = self.brief(case("homes")["content"]["economics"])
        older["content"]["economics"]["analysis_version"] = "econ-explanation-0.2"
        self.assertRegex("; ".join(news_explanations.reasons(older)), "earlier analysis method")


class StageContractTest(unittest.TestCase):
    """brief-evidence-3 and brief-explanation-3 brought the distinction (kept by their successors, brief-stages-0.4);
    earlier contracts stay decodable."""

    def test_the_first_stage_records_form_and_respondents_and_earlier_replies_still_decode(self):
        # brief-evidence-3 and -4 decode with the format they were sent in; the current one keeps form and
        # respondents and each fact's claim (brief-evidence-5), in brief-evidence-5's very format (brief-evidence-6).
        self.assertIs(brief_stages.STAGE_1_SCHEMAS["brief-evidence-3"], brief_stages.STAGE_1_SCHEMAS["brief-evidence-4"])
        self.assertIs(brief_stages.STAGE_1_SCHEMAS["brief-evidence-6"], brief_stages.STAGE_1_SCHEMA)
        self.assertEqual(brief_wire.output_format(brief_stages.STAGE_1_SCHEMAS["brief-evidence-5"]),
                         brief_wire.output_format(brief_stages.STAGE_1_SCHEMA))
        for schema in (brief_stages.STAGE_1_SCHEMA, brief_stages.STAGE_1_SCHEMAS["brief-evidence-3"]):
            self.assertTrue({"change_form", "change_respondents"} <= set(schema["properties"]))
        properties = brief_stages.STAGE_1_SCHEMA["properties"]
        self.assertTrue({"change_form", "change_respondents"} <= set(properties))
        self.assertNotIn("official_statistic", properties["change_instrument"]["enum"])
        self.assertNotIn("change_form", brief_stages.STAGE_1_SCHEMAS["brief-evidence-1"]["properties"])
        self.assertIn("official_statistic",
                      brief_stages.STAGE_1_SCHEMAS["brief-evidence-2"]["properties"]["change_instrument"]["enum"])
        rules = brief_stages.system(1)
        for words in ("change_form", "survey_answers", "change_respondents", "net_percentage",
                      "a central bank publishing a survey is not making a policy decision"):
            self.assertIn(words, rules)

    def test_the_second_stage_states_the_distinctions_and_keeps_its_limited_answers(self):
        rules = brief_stages.system(2)
        for words in ("reported tightening is not an observed fall in lending",
                      "reported demand is not realised borrowing", "a survey result is not a policy action",
                      "a possible channel is not an established effect", "insufficient_explanation"):
            self.assertIn(words, rules)


class ClimateCorrectionTest(unittest.TestCase):
    """The climate draft (unpublished, stopped by "{f1}" in its summary) and its assisted correction."""

    SENTENCE = "It cites estimated climate losses of {f1} a year and adaptation needs of {f2} a year."
    CORRECTED = ("It cites estimated economic losses from climate damages of approximately €200 billion in 2022-2025, "
                 "or €50 billion per year, and adaptation investment needs of around €70 billion per year.")

    def evidence(self) -> dict:
        passages = {key: value for key, value in case("climate")["correction_passages"].items() if key != "about"}
        return found("climate", passages)

    def original(self) -> tuple[dict, dict, set]:
        """(the application-shaped version 1 replayed from its replies, as checked, and the material's report IDs)."""
        climate = case("climate")
        version = climate["stage_versions"][1]
        raw = brief_stages.assemble(climate["first"], brief_wire.decode(
            climate["reply"], brief_stages.stage_2_schema(version=version)), version)
        used = {row["entry_id"] for row in climate["reports"]}
        return raw, story_briefs.checked_content(raw, used, self.evidence(), analysis_version=LEGACY), used

    def test_the_original_keeps_its_stop_and_the_correction_resolves_it_from_the_sources(self):
        raw, content, used = self.original()
        summary = lambda rows: [row for row in rows if row["where"] == "summary"]  # noqa: E731  (the kept passages
        # are only those the figures quote, so other texts' numbers are not all in them)
        self.assertEqual(summary(brief_stages.coherence(content, self.evidence())), case("climate")["saved_findings"])
        self.assertIn("placeholder_in_brief", {row["rule"] for row in econ_fidelity.reference_findings(content)})
        corrected = copy.deepcopy(raw)  # Corrected as the application-shaped input, then checked as version 1 was.
        self.assertEqual(corrected["summary"].count(self.SENTENCE), 1)
        corrected["summary"] = corrected["summary"].replace(self.SENTENCE, self.CORRECTED)
        corrected["themes"][4]["kind"] = "theme"
        checked = story_briefs.checked_content(corrected, used, self.evidence(), analysis_version=LEGACY)
        self.assertEqual(summary(brief_stages.coherence(checked, self.evidence())), [])  # Its numbers are the sources'.
        self.assertEqual(econ_fidelity.reference_findings(checked), [])
        for words in ("approximately €200 billion, or €50 billion per year", "around €70 billion per year"):
            self.assertIn(words, " ".join(self.evidence()["sources"][key]["text"]
                                          for key in self.evidence()["sources"]))
        self.assertNotIn("{", checked["summary"])

    def test_a_correction_is_a_new_assisted_version_and_the_stopped_original_is_kept(self):
        world = World(self)
        economics = tariff_economics()
        story = world.story(TARIFF)
        basis = story_economics.evidence(story["material"], None, None, story["first_at"])
        content = world.brief(TARIFF, economics)
        content["summary"] = "SYNTHETIC: the Synthetic Republic announced a tariff of {f1} on imported steel."
        first, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
            "content": content, "method": "editorial", "based_on": None, "idempotency_key": "climate-like-1"},
            story["material"], "editor-1", START, basis=basis)
        self.assertFalse(first["publishable"])
        corrected = copy.deepcopy(content)
        corrected["summary"] = "SYNTHETIC: the Synthetic Republic announced a 15% tariff on imported steel."
        preparation = story_briefs.assistant_preparation("Claude Code", "claude-opus-5-5", "editor-1",
                                                         "SYNTHETIC: the summary's reference becomes the amount.")
        preparation["correction"] = {"source_version": first["version"], "changes": [{"path": "summary"}],
                                     "additional_provider_requests": 0}
        second, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
            "content": corrected, "method": "assisted", "based_on": first["version"],
            "idempotency_key": "climate-like-2"}, story["material"], "editor-1", START, method="assisted",
            preparation=preparation, basis=basis)
        rows = {row["version"]: row for row in ns.state(world.desk.newsroom)["briefs"][story["story_id"]]}
        self.assertEqual(rows[first["version"]]["guard"]["findings"][0]["rule"], "placeholder_in_brief")
        self.assertTrue(second["publishable"])
        saved = rows[second["version"]]
        self.assertEqual((saved["method"], saved["based_on"]), ("assisted", first["version"]))
        self.assertEqual(saved["preparation"]["assistant"]["tool"], "Claude Code")
        with world.desk.newsroom.reading() as connection:  # No human review is recorded.
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM brief_reviews WHERE story_id = ?",
                                                (story["story_id"],)).fetchone()[0], 0)
        self.assertIsNone(world.story(TARIFF)["brief"])  # Saved, never published.


if __name__ == "__main__":
    unittest.main()
