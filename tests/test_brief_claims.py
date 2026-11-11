"""Who says what, how and on what condition (brief-claims-0.1, story-brief-0.4, econ-explanation-0.5,
econ-fidelity-0.5, brief-stages-0.5; docs/news-claims-conditions-2026-10-29.md (private; not in the public repository)).

The economic-quality audit of 29 October 2026 found published briefs that lost whose claim something was and on what
condition: an interviewer's conditional premise became a central-bank board member's plan in a headline (2029), an executive
order's conditional duty ("shall, if he determines …") became "directs", a claimed future effect (-45%) and a modelled
scenario (24% of output at risk) were shown like observed figures, an opened safeguard investigation was labelled
"Being put into effect", and "more than $5 billion … for meat and seafood processing" became "$5 billion" for seafood.

Three kinds of evidence, as in test_econ_form_subject. Real cases (tests/claims_cases.json): our published versions
exactly and only the source passages quoted, so each historical wording is checked against the words it came from.
FICTIONAL cases ("northmere" for R01, "keynote" for the scenario of R07 and R08, each marked "fictional": true, with
invented speakers, a fictional central bank and newspaper and example.org links) keep the structure of two audited
interview and speech cases without reusing the authored text. SYNTHETIC variations (marked) give the rest. No story
ID, publisher, title or number decides an outcome here. Passing these checks is not evidence that a brief is right: a
claim recorded with the wrong holder or modality passes, and prose without numbers is not read (the limits are asserted
below, not hidden). Nothing reaches a network."""
import copy
import json
from pathlib import Path
import unittest

from news_desk_fakes import BANKS, START, survey_items
from second_order import (brief_claims, brief_stages, brief_wire, econ_classification, econ_fidelity,
                          news_explanations, newsroom_store as ns, story_briefs, story_economics)
from second_order.accounts import AccountsRefused
from test_news_economics import World, explanation

CASES = json.loads(Path(__file__).with_name("claims_cases.json").read_text(encoding="utf-8"))["cases"]
QUESTION = ("If parliament signs off on the amendment this year, might the old notes be pulled from tills as early as "
            "2029? And who sets the date?")
PILOT = "Our branch staff will try the first notes of the new series in a closed trial during 2027."
SEC_2_CONDITION = ("if he determines that it is in the best interests of the Federal National Mortgage Association and "
                   "the Federal Home Loan Mortgage Corporation (Enterprises) or the Federal Housing Finance Agency "
                   "(FHFA), and the American public")
SEC_2 = (f"(a) The Director of the Federal Housing Finance Agency (Director) shall, {SEC_2_CONDITION}, direct the "
         "Enterprises to establish a pilot program")
SHEET = ("The Order directs the FHFA Director to reduce homeowners’ refinancing costs by expanding the FHFA’s title "
         "insurance waiver pilot into a permanent program")
NOTE = "a stated expectation, plan or scenario, not an observed outcome"


def case(name: str) -> dict:
    return copy.deepcopy(CASES[name])


def evidence(name: str) -> dict:
    return story_economics.evidence({"reports": case(name)["reports"]}, None, None, case(name)["released_at"])


def report(name: str, index: int = 0) -> str:
    return case(name)["reports"][index]["entry_id"]


def claim(cid: str, holder: str, name: str, modality: str, source: str, quote: str, condition: str | None = None):
    return {"id": cid, "holder": holder, "holder_name": name, "modality": modality, "quote": quote,
            "condition": condition, "source": source}


def northmere_claims() -> list[dict]:
    source = f"report:{report('northmere')}"
    return [claim("k1", "interviewer", "Harbour Ledger (interviewer)", "question", source, QUESTION,
                  "If parliament signs off on the amendment this year"),
            claim("k2", "speaker", "Halvard Quennel", "prospective", source, PILOT)]


def housing_claims() -> list[dict]:
    order, sheet = (f"report:{row['entry_id']}" for row in sorted(
        case("housing")["reports"], key=lambda row: "Fact Sheet" in row["title"]))
    return [claim("k1", "operative_text", "The Order, Sec. 2", "conditional", order, SEC_2, SEC_2_CONDITION),
            claim("k2", "issuer", "The fact sheet", "asserted", sheet, SHEET)]


def brief(name: str, facts: list[dict], claims: list[dict] | None, headline: str = "SYNTHETIC headline",
          summary: str = "SYNTHETIC: the reports state a development.", economics: dict | None = None) -> dict:
    """A brief over a retained case's material (SYNTHETIC texts unless given), recording ``claims``."""
    content = {"headline": headline, "summary": summary, "facts": facts,
               "implications": [{"text": "SYNTHETIC: it could matter if it applies."}], "themes": [],
               "uncertainties": ["SYNTHETIC: the timing is not stated."], "missing": []}
    if claims is not None:
        content["claims"] = claims
    if economics is not None:
        content["economics"] = economics
    return content


def fact(text: str, name: str, claims: list[str] | None = None, index: int = 0) -> dict:
    row = {"text": text, "reports": [report(name, index)]}
    if claims is not None:
        row["claims"] = claims
    return row


def stops(content: dict, name: str) -> set[tuple[str, str, str]]:
    """The publication stops econ-fidelity records for this content checked against the case's evidence."""
    found = evidence(name)
    checked = story_briefs.checked_content(content, {row["entry_id"] for row in case(name)["reports"]}, found)
    return {(row["where"], row["rule"], row["matched"]) for row in econ_fidelity.findings(checked, found)}


class ClaimRecordTest(unittest.TestCase):
    """K1-K3: a claim quotes its source, its condition is its own words, and every reference resolves."""

    def test_a_claim_is_its_sources_words_with_its_condition_inside_them(self):
        sources = evidence("northmere")["sources"]
        kept = brief_claims.checked(northmere_claims(), sources)
        self.assertEqual([(row["id"], row["modality"], row["condition"]) for row in kept],
                         [("k1", "question", "If parliament signs off on the amendment this year"),
                          ("k2", "prospective", None)])
        refused = {
            "words not in the source": ({"quote": "the old notes will be pulled in 2029"}, "is not in report:"),
            "a condition that is not in the quote": ({"condition": "if the Council agrees"}, "not inside its quote"),
            "a conditional claim gives its condition": ({"modality": "conditional", "condition": None},
                                                        "gives its condition"),
            "a stated claim has no condition": ({"modality": "asserted"}, "only a conditional, prospective"),
            "a holder the evidence does not name": ({"holder_name": "Ottilie Brandvold"}, "is not named"),
            "a source the brief does not hold": ({"source": "report:elsewhere:0000"}, "does not hold"),
            "a holder outside the list": ({"holder": "journalist"}, "names its holder"),
            "an empty condition is not an absent one": ({"condition": ""}, "text of 1 to 400"),
        }
        for label, (change, words) in refused.items():
            with self.subTest(label):
                rows = northmere_claims()
                rows[0].update(change)
                with self.assertRaisesRegex(AccountsRefused, words):
                    brief_claims.checked(rows, sources)
        with self.assertRaisesRegex(AccountsRefused, "ID is k1"):  # Numbered by position, never chosen.
            brief_claims.checked([{**northmere_claims()[1], "id": "k2"}], sources)

    def test_a_version_records_claims_with_every_fact_citing_them_or_keeps_the_earlier_shape(self):
        used, found = {report("northmere")}, evidence("northmere")
        earlier = brief("northmere", [fact("SYNTHETIC: a pilot was described.", "northmere")], None)
        self.assertNotIn("claims", story_briefs.checked_content(earlier, used, found))  # story-brief-0.3, as before.
        recorded = brief("northmere", [fact("SYNTHETIC: a pilot was described.", "northmere", ["k2"])],
                         northmere_claims())
        self.assertEqual(story_briefs.checked_content(recorded, used, found)["facts"][0]["claims"], ["k2"])
        for label, content, words in (
                ("claims without the facts citing them", brief("northmere", earlier["facts"], northmere_claims()),
                 "the claims it rests on"),
                ("facts citing claims the brief does not record", brief("northmere", recorded["facts"], None),
                 "has text and the material reports it rests on"),
                ("a claim the brief does not hold", brief("northmere", [fact("SYNTHETIC.", "northmere", ["k9"])],
                                                          northmere_claims()), "cites only this brief's claims")):
            with self.subTest(label), self.assertRaisesRegex(AccountsRefused, words):
                story_briefs.checked_content(content, used, found)
        with self.assertRaisesRegex(AccountsRefused, "checked against the evidence"):
            story_briefs.checked_content(recorded, used, None)


class InterviewTest(unittest.TestCase):
    """R01 (fictional case): the interviewer's premise "as early as 2029" is not the official's plan."""

    PUBLISHED = ("Northmere Reserve Bank's Quennel sets out a 2027 banknote trial and a possible 2029 withdrawal of old "
                 "notes")
    CORRECTED = ("Northmere Reserve Bank's Quennel says a new banknote series will be trialled in 2027 and a withdrawal "
                 "date awaits parliament")

    def test_the_published_headline_states_the_interviewers_premise_and_stops_publication(self):
        self.assertEqual(case("northmere")["content"]["headline"], self.PUBLISHED)
        facts = [fact("SYNTHETIC: a pilot starts in 2027.", "northmere", ["k2"])]
        found = stops(brief("northmere", facts, northmere_claims(), headline=self.PUBLISHED), "northmere")
        self.assertEqual(found, {("headline", "claim_only_number", "2029")})  # 2027 is his own plan: it may lead.
        self.assertEqual(stops(brief("northmere", facts, northmere_claims(), headline=self.CORRECTED), "northmere"),
                         set())

    def test_a_fact_carrying_the_premise_cites_it_so_readers_see_whose_it_is(self):
        published = case("northmere")["content"]["facts"][1]["text"]
        self.assertIn("the interviewer put a possible rollout as early as 2029", published)
        cited = [fact(published, "northmere", ["k1"])]
        self.assertEqual(stops(brief("northmere", cited, northmere_claims()), "northmere"), set())
        uncited = [fact(published, "northmere", ["k2"])]
        self.assertEqual(stops(brief("northmere", uncited, northmere_claims()), "northmere"),
                         {("facts[0]", "claim_only_number", "2029")})
        view = brief_claims.reader_view(brief("northmere", cited, northmere_claims()), case("northmere"))
        first = view["claims"][0]
        self.assertEqual((first["holder_label"], first["modality_label"], first["condition"], first["facts"]),
                         ("The interviewer's question or premise",
                          "A question or premise put to someone, not their statement",
                          "If parliament signs off on the amendment this year", [1]))

    def test_known_limit_the_summary_is_not_read(self):
        """SYNTHETIC: the premise written as his expectation in the summary passes; the record is shown beside it."""
        facts = [fact("SYNTHETIC: a pilot starts in 2027.", "northmere", ["k2"])]
        content = brief("northmere", facts, northmere_claims(),
                        summary="Quennel expects the old notes to be withdrawn by 2029.")
        self.assertEqual(stops(content, "northmere"), set())

    def test_what_changed_never_rests_on_a_question(self):
        facts = [fact("SYNTHETIC: a pilot starts in 2027.", "northmere", ["k2"])]
        economics = explanation(change={"stage": "forecast", "instrument": "other", "form": "statement",
                                        "respondents": None, "basis": ["fact:1", "claim:k1"],
                                        "text": "SYNTHETIC: the old notes are to be withdrawn."},
                                channels=[{**explanation()["channels"][0], "conditions": "If it is issued"}])
        content = brief("northmere", facts, northmere_claims(), economics=economics)
        with self.assertRaisesRegex(AccountsRefused, "never rests on a question"):
            story_briefs.checked_content(content, {report("northmere")}, evidence("northmere"))
        economics["change"]["basis"] = ["fact:1", "claim:k2"]
        self.assertEqual(story_briefs.checked_content(content, {report("northmere")}, evidence("northmere"))
                         ["economics"]["analysis_version"], story_economics.ANALYSIS_VERSION)

    def test_a_fact_citation_cannot_turn_the_interviewers_question_into_a_development(self):
        facts = [fact("SYNTHETIC: the interviewer asks about a possible 2029 rollout.", "northmere", ["k1"]),
                 fact("SYNTHETIC: the speaker describes a pilot starting in 2027.", "northmere", ["k2"])]
        economics = explanation(change={"stage": "forecast", "instrument": "other", "form": "statement",
                                        "respondents": None, "basis": ["fact:1"],
                                        "text": "SYNTHETIC: the old notes are to be withdrawn."},
                                channels=[{**explanation()["channels"][0], "conditions": "If it is issued"}])
        content = brief("northmere", facts, northmere_claims(), economics=economics)
        with self.assertRaisesRegex(AccountsRefused, "never rests on a question"):
            story_briefs.checked_content(content, {report("northmere")}, evidence("northmere"))
        # A question can remain in the report; it must not be the basis of the described development.
        economics["change"]["basis"] = ["fact:2"]
        self.assertEqual(story_briefs.checked_content(content, {report("northmere")}, evidence("northmere"))
                         ["economics"]["change"]["basis"], ["fact:2"])


class ConditionTest(unittest.TestCase):
    """R02 (real): the order's duty holds only if the Director so determines; the fact sheet says "directs"."""

    def facts(self) -> list[dict]:
        order = next(row["entry_id"] for row in case("housing")["reports"] if "Fact Sheet" not in row["title"])
        return [{"text": "SYNTHETIC: the order provides for a mortgage insurance pilot if the Director so determines.",
                 "reports": [order], "claims": ["k1"]}]

    def economics(self, stage: str, conditions: str | None) -> dict:
        channel = {**explanation()["channels"][0], "basis": ["fact:1"], "conditions": conditions}
        return explanation(change={"stage": stage, "instrument": "housing", "form": "announcement_or_decision",
                                   "respondents": None, "basis": ["fact:1"],
                                   "text": "SYNTHETIC: an order provides for a pilot."}, channels=[channel])

    def test_a_channel_resting_on_a_conditional_claim_states_its_conditions(self):
        used = {row["entry_id"] for row in case("housing")["reports"]}
        content = brief("housing", self.facts(), housing_claims(), economics=self.economics("decision", None))
        with self.assertRaisesRegex(AccountsRefused, r"states the conditions under which it would follow \(K6\)"):
            story_briefs.checked_content(content, used, evidence("housing"))
        content["economics"] = self.economics("decision", "If the Director determines the pilot is in their interests")
        self.assertEqual(story_briefs.checked_content(content, used, evidence("housing"))["economics"]["change"]
                         ["stage"], "decision")

    def test_a_development_resting_only_on_a_condition_is_not_being_put_into_effect(self):
        used = {row["entry_id"] for row in case("housing")["reports"]}
        content = brief("housing", self.facts(), housing_claims(),
                        economics=self.economics("implementation", "If the Director so determines"))
        with self.assertRaisesRegex(AccountsRefused, r"so it is not being put into effect \(K5\)"):
            story_briefs.checked_content(content, used, evidence("housing"))

    def test_known_limit_a_dropped_condition_in_prose_passes_and_the_record_is_shown_beside_it(self):
        published = case("housing")["content"]["summary"]
        self.assertIn("It directs the FHFA to have Fannie Mae and Freddie Mac pilot", published)
        content = brief("housing", self.facts(), housing_claims(), summary=published)
        self.assertEqual(stops(content, "housing"), set())  # No keyword rule: "directs" is not detected.
        view = brief_claims.reader_view(content, case("housing"))
        self.assertEqual([(row["holder_label"], row["modality"], row["condition"]) for row in view["claims"]],
                         [("The text of the order, law or notice itself", "conditional", SEC_2_CONDITION),
                          ("The publisher's own statement", "asserted", None)])


class ClaimedEffectTest(unittest.TestCase):
    """R07 and R08 (a real case and a fictional one): a claimed effect and a scenario are never shown as observed outcomes."""

    def test_a_figure_quoting_a_plan_or_scenario_is_shown_as_one(self):
        for name, quote in (("vdl", "Reducing exports by around 45%."),
                            ("keynote", "could leave as much as 24% of container volume waiting offshore")):
            with self.subTest(name):
                content = case(name)["content"]
                economics, facts = content["economics"], content["facts"]
                figure = economics["figures"][0]
                self.assertEqual(figure["statistic"], "observed")  # As published, typed like an observation.
                passage = next(text for text in case(name)["reports"][0]["excerpt"].split("\n") if quote in text)
                claims = [claim("k1", "speaker", "SYNTHETIC speaker", "prospective",
                                figure["source"], passage)]
                before = story_economics.reader_view(economics, facts)
                after = story_economics.reader_view(economics, facts, None, claims)
                self.assertNotIn("claim_label", before["figures"][0])  # A version without claims: as before.
                self.assertEqual(after["figures"][0]["claim_label"], NOTE)
                self.assertNotIn(NOTE, json.dumps(before))
                self.assertIn(NOTE, json.dumps(after["summary"]) + json.dumps(after["channels"]))

    def test_a_text_writing_a_claimed_figure_cites_it(self):
        content = case("vdl")["content"]
        economics = content["economics"]
        self.assertIn("which she said changes those exports by {f1}", economics["change"]["text"])
        source = economics["figures"][0]["source"]
        claims = [claim("k1", "speaker", "President von der Leyen", "prospective", source,
                        "Reducing exports by around 45%.")]
        facts = [{**row, "claims": []} for row in content["facts"]]
        self.assertIn("reducing exports by around 45%", facts[0]["text"])
        uncited_fact = {**content, "claims": claims, "facts": facts}
        self.assertEqual([(row["where"], row["matched"]) for row in
                          brief_claims.findings(uncited_fact, evidence("vdl")["sources"])], [("facts[0]", "45%")])
        cited = {**uncited_fact, "facts": [{**facts[0], "claims": ["k1"]}, *facts[1:]]}
        self.assertEqual(brief_claims.findings(cited, evidence("vdl")["sources"]), [])  # Its basis cites figure:f1.
        uncited = copy.deepcopy(cited)  # Citing fact 1, which records the claim, cites it; the report alone does not.
        uncited["economics"]["change"]["basis"] = [f"report:{report('vdl')}"]
        self.assertEqual([(row["where"], row["matched"]) for row in
                          brief_claims.findings(uncited, evidence("vdl")["sources"])], [("economics.change", "{f1}")])


class ProcedureTest(unittest.TestCase):
    """R06 (real): an opened investigation or proceeding is a procedure, not a proposal, decision or measure in force."""

    def economics(self, stage: str, form: str, conditions: str | None, version_note: str = "") -> dict:
        channel = {**explanation()["channels"][0], "conditions": conditions}
        return explanation(change={"stage": stage, "instrument": "trade_remedy", "form": form, "respondents": None,
                                   "basis": ["fact:1"], "text": f"SYNTHETIC: an investigation was opened.{version_note}"},
                           channels=[channel])

    def test_each_opened_procedure_takes_the_procedure_stage_with_conditional_channels(self):
        labels = {}
        for name in ("zimbabwe", "philippines", "omya", "booking"):
            with self.subTest(name):
                passage = case(name)["reports"][0]["excerpt"]
                content = brief(name, [fact(f"SYNTHETIC: {passage[:200]}", name)], None,
                                economics=self.economics("procedure", "announcement_or_decision",
                                                         "If a measure follows"))
                checked = story_briefs.checked_content(content, {report(name)}, evidence(name))
                labels[name] = story_economics.reader_view(checked["economics"], checked["facts"])["summary"][
                    "stage_label"]
                content["economics"] = self.economics("procedure", "announcement_or_decision", None)
                with self.assertRaisesRegex(AccountsRefused, "states the condition under which it would follow"):
                    story_briefs.checked_content(content, {report(name)}, evidence(name))
        self.assertEqual(set(labels.values()), {"Procedure opened, no decision on a measure"})
        published = {name: case(name)["content"]["economics"]["change"]["stage"]
                     for name in ("zimbabwe", "philippines", "omya", "booking")}
        self.assertEqual(published, {"zimbabwe": "implementation", "philippines": "proposal", "omya": "decision",
                                     "booking": "decision"})  # One kind of event, three labels, kept as recorded.

    def test_a_procedure_is_never_a_surveys_answers_or_a_forecast_nor_known_to_earlier_versions(self):
        for form in ("survey_answers", "forecast_or_scenario"):
            with self.subTest(form), self.assertRaisesRegex(AccountsRefused, "so its stage is"):
                econ_classification.checked({"stage": "procedure", "instrument": "trade_remedy", "form": form,
                                             "respondents": "firms" if form == "survey_answers" else None})
        change = {"stage": "procedure", "instrument": "trade_remedy", "form": "announcement_or_decision",
                  "respondents": None}
        self.assertEqual(econ_classification.checked(change)["form"], "announcement_or_decision")
        with self.assertRaisesRegex(AccountsRefused, "so its stage is proposal or decision"):
            econ_classification.checked(change, "econ-explanation-0.4")  # 0.4's own table, as it was.

    def test_a_planned_procedure_is_a_forecast(self):
        """Šefčovič: "A safeguard … to be initiated soon" (real): nothing is opened yet."""
        self.assertIn("to be initiated soon", case("sefcovic")["reports"][0]["excerpt"])
        content = brief("sefcovic", [fact("SYNTHETIC: a safeguard is to be initiated soon.", "sefcovic")], None,
                        economics=self.economics("forecast", "statement", "If it is initiated"))
        self.assertEqual(story_briefs.checked_content(content, {report("sefcovic")}, evidence("sefcovic"))
                         ["economics"]["change"]["stage"], "forecast")


class BoundTest(unittest.TestCase):
    """R04 (real): a headline keeps the bound its figure states; B1 reads the headline only (measured)."""

    def content(self, headline: str) -> dict:
        return {**case("seafood")["content"], "headline": headline}

    def rules(self, headline: str) -> list[str]:
        return [row["matched"] for row in econ_fidelity.bound_findings(self.content(headline))]

    def test_the_published_headline_drops_more_than_and_stops_publication(self):
        published = case("seafood")["content"]["headline"]
        self.assertEqual(published, "White House launches an America First Seafood Strategy with $5 billion in USDA "
                                    "loan guarantees")
        self.assertEqual(case("seafood")["content"]["economics"]["figures"][0]["bound"], "lower_bound")
        self.assertEqual(self.rules(published), ["$5"])
        for valid in ("White House launches an America First Seafood Strategy with more than $5 billion in USDA loan "
                      "guarantees for meat and seafood processing",
                      "SYNTHETIC: over $5 billion in USDA loan guarantees for meat and seafood processing"):
            with self.subTest(valid):
                self.assertEqual(self.rules(valid), [])

    def test_known_limits_are_kept_explicit(self):
        # SYNTHETIC: a bound written after the number is refused (a false positive, stated).
        self.assertEqual(self.rules("SYNTHETIC: $5 billion-plus in USDA loan guarantees"), ["$5"])
        # SYNTHETIC: a scope narrowed to seafood keeps the bound and passes (scope is semantic).
        self.assertEqual(self.rules("SYNTHETIC: more than $5 billion in loan guarantees for seafood processing"), [])
        # The same bound dropped outside the headline is not read: applied to every text, B1 would also have stopped
        # correct wordings (a bound governing a coordinated number; "the 24% … figure").
        self.assertIn("the $5 billion in loan guarantees", case("seafood")["content"]["uncertainties"][1])
        self.assertEqual(econ_fidelity.bound_findings(case("seafood")["content"])[0]["where"], "headline")
        self.assertEqual(econ_fidelity.bound_findings(case("tmed")["content"]), [])  # "up to €4.5 billion": kept.

    def test_an_exact_figure_needs_no_bound(self):
        content = self.content("SYNTHETIC: $5 billion in USDA loan guarantees")
        content["economics"]["figures"][0]["bound"] = "exact"
        self.assertEqual(econ_fidelity.bound_findings(content), [])


class StageOneTest(unittest.TestCase):
    """brief-evidence-5: each fact records its claim, flat; the application finds its source."""

    def reply(self, fact_text: str, *more: dict, **claim_fields) -> dict:
        """A SYNTHETIC first-stage reply over the real interview: one fact with these claim fields, then ``more``."""
        fields = {name: "" for name in brief_stages.CLAIM_FIELDS} | claim_fields
        return {"insufficient_material": "", "facts": [{"text": fact_text, "reports": [report("northmere")],
                                                         **fields}, *more],
                "themes": [], "missing": [], "insufficient_evidence": "SYNTHETIC: no figures to explain.",
                "change_stage": "", "change_instrument": "", "change_form": "", "change_respondents": "",
                "change_text": "", "change_basis": [], "figures": [], "calculations": []}

    def foundations(self, reply: dict) -> dict:
        decoded = brief_wire.decode(reply, brief_stages.STAGE_1_SCHEMA)
        return brief_stages.foundations(decoded, {"reports": case("northmere")["reports"]}, evidence("northmere"))

    def test_a_fact_records_the_claim_it_rests_on_and_its_source_is_found_not_given(self):
        record = self.foundations(self.reply(
            "SYNTHETIC: the interviewer put a possible rollout as early as 2029.", claim_holder="interviewer",
            claim_holder_name="Harbour Ledger (interviewer)", claim_modality="question", claim_quote=QUESTION,
            claim_condition="If parliament signs off on the amendment this year"))
        self.assertEqual((record["status"], record["facts"][0]["claims"]), ("insufficient_evidence", ["k1"]))
        self.assertEqual(record["claims"][0]["source"], f"report:{report('northmere')}")
        text = brief_stages.foundations_text(record, "brief-s1-synthetic")
        self.assertIn("claim:k1: the interviewer's question or premise, Harbour Ledger (interviewer)", text)
        self.assertIn("rests on claim k1", text)
        content = brief_stages.assemble_brief_only(record, {"headline": "SYNTHETIC", "summary": "SYNTHETIC.",
                                                            "implications": ["SYNTHETIC: it could matter."],
                                                            "uncertainties": []})
        self.assertEqual(content["claims"], record["claims"])

    def test_a_kept_fact_writing_a_claim_only_number_without_its_claim_is_refused_before_stage_two(self):
        premise = {"text": "SYNTHETIC: the interviewer raised a rollout if the regulation is approved this year.",
                   "reports": [report("northmere")], "claim_holder": "interviewer",
                   "claim_holder_name": "Harbour Ledger (interviewer)", "claim_modality": "question",
                   "claim_quote": QUESTION, "claim_condition": "If parliament signs off on the amendment this year"}
        with self.assertRaisesRegex(AccountsRefused, r"kept in the brief unchanged.*facts\[0\].*only inside the "
                                                     r"claims k2.*“2029”"):
            self.foundations(self.reply("SYNTHETIC: a rollout could come as early as 2029.", premise,
                                        claim_holder="speaker", claim_holder_name="Halvard Quennel",
                                        claim_modality="prospective", claim_quote=PILOT))
        # Known limit: K7 reads the record. With the question recorded nowhere, the same fact passes.
        record = self.foundations(self.reply("SYNTHETIC: a rollout could come as early as 2029."))
        self.assertEqual(record["claims"], [])

    def test_half_a_claim_or_words_from_elsewhere_are_refused(self):
        for label, fields, words in (
                ("a quote with no holder", {"claim_quote": PILOT}, "names its holder"),
                ("fields without a quote", {"claim_holder": "speaker"}, "every claim field is"),
                ("words not in the fact's reports", {"claim_holder": "speaker", "claim_holder_name": "Halvard Quennel",
                                                     "claim_modality": "asserted",
                                                     "claim_quote": "SYNTHETIC words nobody wrote"},
                 "not in the reports the fact cites")):
            with self.subTest(label), self.assertRaisesRegex(AccountsRefused, words):
                self.foundations(self.reply("SYNTHETIC: a pilot.", **fields))


class CompatibilityTest(unittest.TestCase):
    """History reads as recorded: 0.4 explanations are current, earlier stages stay theirs, nothing is relabelled."""

    def test_an_explanation_saved_under_0_4_is_current_and_shows_nothing_new(self):
        content = case("safe")["content"]
        self.assertEqual(content["economics"]["analysis_version"], "econ-explanation-0.4")
        brief_row = {"content": content, "material_sha256": "m", "at": "2026-10-28T22:42:32+00:00",
                     "preparation": {"analysis": {"calc_version": "econ-calc-0.3", "guard_version": "econ-guard-0.3",
                                                  "framework_sha256": content["economics"]["framework"][
                                                      "framework_sha256"], "context": None}}}
        self.assertEqual(news_explanations.reasons(brief_row, "m"), [])
        view = story_economics.reader_view(content["economics"], content["facts"])
        self.assertTrue(all("claim_label" not in row for row in view["figures"]))
        self.assertIsNone(brief_claims.reader_view(content, case("safe")))

    def test_revalidating_a_0_4_version_keeps_its_analysis_version(self):
        world = World(self, extra=survey_items(START))
        story = world.story(BANKS)
        content = world.brief(BANKS, explanation(
            change={"stage": "observation", "instrument": "financial_conditions", "form": "survey_answers",
                    "respondents": "banks", "basis": ["fact:1"], "text": "SYNTHETIC: banks reported tighter standards."},
            channels=[{**explanation()["channels"][0], "conditions": None}],
            # Saved under 0.4: its alternatives record no support (econ-explanation-0.6 added it).
            alternatives=[{key: row[key] for key in ("kind", "text", "basis")}
                          for row in explanation()["alternatives"]]))
        basis = story_economics.evidence(story["material"], None, None, story["first_at"])
        old, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
            "content": content, "method": "editorial", "based_on": None, "idempotency_key": "claims-old-0001"},
            story["material"], "editor-1", START, basis=basis, analysis_version="econ-explanation-0.4")
        saved = ns.state(world.desk.newsroom)["briefs"][story["story_id"]][-1]
        self.assertEqual(saved["content"]["economics"]["analysis_version"], "econ-explanation-0.4")
        new, created = story_briefs.revalidate_version(world.desk.newsroom, story["story_id"], {
            "version": old["version"], "content": content, "reason": "SYNTHETIC: rechecked under the current guards",
            "idempotency_key": "claims-revalidate-0001"}, story["material"], "editor-1", START, basis=basis)
        latest = ns.state(world.desk.newsroom)["briefs"][story["story_id"]][-1]
        self.assertTrue(created)
        self.assertEqual((latest["content_sha256"], latest["content"]["economics"]["analysis_version"],
                          latest["preparation"]["analysis"]["analysis_version"]),
                         (saved["content_sha256"], "econ-explanation-0.4", "econ-explanation-0.4"))

    def test_earlier_replies_and_contracts_keep_their_own_tables(self):
        self.assertEqual(econ_classification.STAGES_OF["econ-explanation-0.4"],
                         ("proposal", "decision", "implementation", "observation", "forecast"))
        self.assertNotIn("procedure",
                         brief_stages.STAGE_1_SCHEMAS["brief-evidence-4"]["properties"]["change_stage"]["enum"])
        self.assertIn("procedure", brief_stages.STAGE_1_SCHEMA["properties"]["change_stage"]["enum"])
        self.assertEqual(story_economics.ANALYSES["econ-explanation-0.4"], "econ-calc-0.3")


class OrdinaryClaimsTest(unittest.TestCase):
    """SYNTHETIC: what is ordinarily right keeps passing."""

    def test_a_publishers_stated_figures_and_a_speakers_own_plan_lead_a_headline(self):
        source = f"report:{report('northmere')}"
        stated = [claim("k1", "speaker", "Halvard Quennel", "asserted", source, PILOT)]
        content = brief("northmere", [fact("SYNTHETIC: a pilot starts in 2027.", "northmere", ["k1"])], stated,
                        headline="SYNTHETIC: Reserve Bank trial to start in 2027")
        self.assertEqual(stops(content, "northmere"), set())
        unrecorded = brief("northmere", [fact("SYNTHETIC: a possible rollout in 2029 was raised.", "northmere")],
                           None, headline="SYNTHETIC: rollout in 2029?")
        self.assertEqual(stops(unrecorded, "northmere"), set())  # A version without claims is checked as before.


if __name__ == "__main__":
    unittest.main()
