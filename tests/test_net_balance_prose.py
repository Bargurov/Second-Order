"""A survey's net percentage keeps its meaning in every text a reader sees (econ-fidelity-0.4, brief-stages-0.4).

The ECB bank lending survey's first stage of 29 October 2026 (tests/ecb_stage_1_case.json, real) typed its three
balances as net percentages, yet one theme said "Net demand for housing loans fell by 27% net, driven by interest
rates": a balance of banks' answers written as the size of a contraction, and the reason the release reports stated as
an established cause. The stage-1 validator accepted it, assembly copies themes unchanged (so stage 2 cannot repair
it), and no publication check read it, because econ-fidelity-0.2 read only the explanation's {f1} references.

The real reply is the regression case: it must still validate under the contract it was sent under, be refused under
the corrected one, and stop publication wherever it is assembled. SYNTHETIC texts give the variations: other balances
and numbers, valid ways to describe a balance, ordinary growth rates, and what the rule cannot establish. No story ID,
publisher or number decides an outcome. Nothing reaches a network, and passing these checks is not evidence that a
text is economically right."""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from news_desk_fakes import BANKS, START, banks_brief, survey_items, with_report
from second_order import (brief_drafting, brief_stages, brief_wire, econ_fidelity, news_views, newsroom_store as ns,
                          story_briefs, story_economics)
from second_order.accounts import AccountsRefused
from second_order.model_draft import DraftRefused
from test_brief_stages import ACTOR, form
from test_news_economics import World

CASE = json.loads((Path(__file__).with_name("ecb_stage_1_case.json")).read_text(encoding="utf-8"))
BOOKKEEPING = ("draft_id", "request_sha256", "stage_version")
AS_CHANGE, REASON = "net_percentage_as_change", "net_percentage_reason_unattributed"
# A SYNTHETIC second stage whose own texts are neutral, so that any finding comes from the first stage's texts.
NEUTRAL = {"headline": "SYNTHETIC neutral headline", "summary": "SYNTHETIC neutral summary.",
           "implications": ["SYNTHETIC: this may matter."], "uncertainties": ["SYNTHETIC uncertainty."],
           "insufficient_explanation": "", "significance": "SYNTHETIC significance.",
           "significance_basis": ["fact:1"], "main_uncertainty": "SYNTHETIC unknown.", "assumptions": [],
           "channels": [], "second_order": [], "alternatives": [], "watch": []}


def evidence() -> dict:
    return story_economics.evidence({"reports": CASE["reports"]}, None, None, CASE["released_at"])


def checked(stage_version: str) -> dict:
    reply = brief_wire.decode(copy.deepcopy(CASE["reply"]), brief_stages.STAGE_1_SCHEMAS[stage_version])
    return brief_stages.foundations(reply, {"reports": CASE["reports"]}, evidence(), stage_version)


def net(fid: str, value) -> dict:
    """A SYNTHETIC typed net percentage (the share of respondents reporting one direction minus the other)."""
    return {"id": fid, "value": value, "unit": "percent", "measure": "net_percentage"}


def typed(fid: str, value, measure: str) -> dict:
    return {"id": fid, "value": value, "unit": "percent", "measure": measure}


def rules(text: str, rows: list[dict], where: str = "summary") -> list[str]:
    return [row["rule"] for row in econ_fidelity.balance_findings([(where, text)], rows)]


class EcbStageOneTest(unittest.TestCase):
    """The real reply: its historical outcome reproduces, and the corrected checks find its theme."""

    def test_the_saved_reply_still_validates_under_the_contract_it_was_sent_under(self):
        self.assertEqual((CASE["stage_version"], CASE["outcome"]), ("brief-evidence-3", "validated"))
        saved = {key: value for key, value in CASE["foundations"].items() if key not in BOOKKEEPING}
        self.assertEqual(checked("brief-evidence-3"), saved)
        self.assertEqual(saved["themes"][2]["basis"],
                         "Net demand for housing loans fell by 27% net, driven by interest rates.")
        self.assertEqual([row["measure"] for row in saved["figures"]], ["net_percentage"] * 3)

    def test_under_the_corrected_contract_the_same_reply_is_refused_before_stage_two(self):
        corrected = "brief-evidence-4"  # The contract that corrected this reply's defect (brief-stages-0.4).
        self.assertNotEqual(corrected, CASE["stage_version"])
        with self.assertRaisesRegex(DraftRefused, "claim_quote"):  # A later contract's format: never decoded as one.
            checked(brief_stages.STAGE_VERSIONS[1])
        with self.assertRaises(AccountsRefused) as refused:
            checked(corrected)
        message = str(refused.exception)
        self.assertIn("themes[2]", message)
        self.assertIn("“by 27%”", message)
        self.assertIn("driven", message)
        for where in ("facts[0]", "facts[1]", "themes[0]", "themes[1]", "themes[3]", "missing["):
            self.assertNotIn(where, message)  # The valid descriptions of the same balances pass.

    def test_assembled_from_the_saved_foundations_its_theme_stops_publication(self):
        content = brief_stages.assemble(copy.deepcopy(CASE["foundations"]), NEUTRAL)
        self.assertEqual(content["themes"][2], CASE["foundations"]["themes"][2])  # Assembly copies it unchanged.
        found = econ_fidelity.findings(content, evidence())
        stops = {(row["where"], row["rule"]) for row in found}
        self.assertEqual(stops, {("themes[2]", AS_CHANGE), ("themes[2]", REASON)})
        earlier = brief_stages.coherence(content, evidence()) + story_briefs.guard(content)["findings"]
        self.assertEqual([row for row in earlier if row["where"] == "themes[2]"], [])  # What missed it before.

    def test_the_corrected_theme_passes_and_says_whose_answers_and_reason_they_are(self):
        content = brief_stages.assemble(copy.deepcopy(CASE["foundations"]), NEUTRAL)
        content["themes"][2]["basis"] = ("Banks reported a strong net decrease in demand for housing loans (net "
                                         "percentage of -27%); the ECB says increases in interest rates were the main "
                                         "driver.")
        self.assertEqual(econ_fidelity.findings(content, evidence()), [])


class BalanceProseTest(unittest.TestCase):
    """SYNTHETIC texts against a version's typed figures."""

    ROWS = [net("f1", -12), net("f2", 9), typed("f3", 2.5, "growth_rate")]

    def test_a_balance_written_as_the_size_of_a_change_stops_publication(self):
        for text, matched in (("SYNTHETIC: demand for loans fell by 12%.", "by 12%"),
                              ("SYNTHETIC: demand fell 12 percent.", "fell 12 percent"),
                              ("SYNTHETIC: housing demand was down 12 points.", "down 12 points"),
                              ("SYNTHETIC: a 12% decline in demand for loans.", "12% decline"),
                              ("SYNTHETIC: demand dropped sharply, by a net 12%.", "by a net 12%"),
                              ("SYNTHETIC: credit standards tightened by 9%.", "by 9%"),
                              ("SYNTHETIC: standards rose 9% this quarter.", "rose 9%"),
                              ("SYNTHETIC: demand fell by −12%.", "by −12%")):
            with self.subTest(text):
                found = econ_fidelity.balance_findings([("facts[0]", text)], self.ROWS)
                self.assertEqual([(row["rule"], row["matched"]) for row in found], [(AS_CHANGE, matched)])

    def test_a_reference_to_a_balance_written_as_a_change_stops_it_too(self):
        for text in ("SYNTHETIC: lending fell by {f1}.", "SYNTHETIC: a {f1} decline in demand.",
                     "SYNTHETIC: demand dropped by a net {f1}."):
            with self.subTest(text):
                self.assertEqual(rules(text, self.ROWS, "economics.significance"), [AS_CHANGE])
        self.assertEqual(rules("SYNTHETIC: loans grew by {f3}.", self.ROWS, "economics.significance"), [])

    def test_a_change_construction_is_read_before_a_following_of(self):
        # 0.3 let any "of" after the number pass before reading what came before it (found by review of 3b31771).
        for text, matched in (("SYNTHETIC: loan demand fell by 12% of last quarter's level.", "by 12%"),
                              ("SYNTHETIC: loan demand fell 12% of its level.", "fell 12%"),
                              ("SYNTHETIC: loan demand dropped by a net 12% of the previous total.", "by a net 12%")):
            with self.subTest(text):
                found = econ_fidelity.balance_findings([("summary", text)], self.ROWS)
                self.assertEqual([(row["rule"], row["matched"]) for row in found], [(AS_CHANGE, matched)])
        reference = "SYNTHETIC: loan demand fell by {f1} of last quarter's level."
        self.assertEqual(rules(reference, self.ROWS, "economics.significance"), [AS_CHANGE])

    def test_valid_descriptions_of_a_balance_pass(self):
        for text in ("SYNTHETIC: a net 12% of banks reported lower demand for loans.",
                     "SYNTHETIC: banks reported a net decrease in demand (net percentage of -12%).",
                     "SYNTHETIC: demand fell slightly (net percentage of -12%).",
                     "SYNTHETIC: the net percentage fell to -12% from -5%.",
                     "SYNTHETIC: tighter standards were cited by a net 9% of banks.",
                     "SYNTHETIC: standards were tightened by a net 9% of banks.",
                     "SYNTHETIC: {f1} of respondents reported lower demand for loans.",
                     "SYNTHETIC: banks reported a net tightening of standards (9%) and weaker demand (-12%).",
                     "SYNTHETIC: banks reported a net decrease in demand ({f1}).",
                     "SYNTHETIC: Banks reported lower demand (-12%), driven mainly by higher interest rates."):
            with self.subTest(text):
                self.assertEqual(rules(text, self.ROWS), [])

    def test_ordinary_growth_rates_of_another_size_pass(self):
        for text in ("SYNTHETIC: loans to firms grew by 2.5%.",  # Typed as a growth rate.
                     "SYNTHETIC: output rose by 4.1% and prices increased 3%.",  # Untyped, of no balance's size.
                     "SYNTHETIC: loans grew by 2.5%, driven by mortgages.",  # The guard's business, not this rule's.
                     "SYNTHETIC: lending fell by 12 billion euros."):  # Not a percentage: never read as a balance.
            with self.subTest(text):
                self.assertEqual(rules(text, self.ROWS), [])

    def test_a_reason_given_for_a_balance_says_who_gives_it(self):
        for text in ("SYNTHETIC: demand for housing loans was -12% (net percentage), driven by interest rates.",
                     "SYNTHETIC: the net tightening (9%) was owing to risk perceptions.",
                     "SYNTHETIC: interest rates were the main drivers of the net decrease (-12%)."):
            with self.subTest(text):
                self.assertEqual(rules(text, self.ROWS), [REASON])
        for text in ("SYNTHETIC: banks report lower demand (net percentage of -12%), owing to interest rates.",
                     "SYNTHETIC: the ECB says interest rates drove the net decrease in demand (-12%).",
                     "SYNTHETIC: according to banks, demand fell (net percentage of -12%) because of rates."):
            with self.subTest(text):
                self.assertEqual(rules(text, self.ROWS), [])

    def test_a_sentence_without_a_balance_is_left_to_the_guard(self):
        for text in ("SYNTHETIC: if the rise is not mainly price-driven, firms' revenue could hold up.",
                     "SYNTHETIC: whether the rise is driven by a few volatile categories.",
                     "SYNTHETIC: demand was driven by interest rates."):
            with self.subTest(text):
                self.assertEqual(rules(text, self.ROWS), [])

    def test_an_untyped_figure_the_size_of_a_balance_is_read_as_it_a_stated_false_positive(self):
        # Only the balance is typed at 12, so a separate figure of that size, even one its source states, is read as
        # the balance: publication stops, and a brief-evidence-4 first stage is refused. The rule cannot tell them
        # apart from words and numbers; within one survey release balances often share a size (euro area and SMEs).
        self.assertEqual(rules("SYNTHETIC: industrial output fell by 12%.", [net("f1", -12)]), [AS_CHANGE])
        # Typed as what it is, the figure makes the size ambiguous, and the rule leaves it alone.
        typed_too = [net("f1", -12), typed("f2", -12, "growth_rate")]
        self.assertEqual(rules("SYNTHETIC: industrial output fell by 12%.", typed_too), [])

    def test_what_the_rule_cannot_establish(self):
        # A magnitude also typed as a change or growth rate is ambiguous, and left alone.
        self.assertEqual(rules("SYNTHETIC: demand fell by 12%.", [net("f1", -12), typed("f2", -12, "change")]), [])
        # A balance the version did not type is not recognised.
        self.assertEqual(rules("SYNTHETIC: demand fell by 15%.", self.ROWS), [])
        # Nor a rounded one, nor words that misstate a balance's direction or size.
        for text in ("SYNTHETIC: demand fell by 10%.", "SYNTHETIC: a net 12% of banks reported higher demand.",
                     "SYNTHETIC: most banks reported lower demand (-12%)."):
            with self.subTest(text):
                self.assertEqual(rules(text, self.ROWS), [])
        # A change verb outside the list, followed by "of", reads as naming who answered (a stated false negative).
        self.assertEqual(rules("SYNTHETIC: lending was cut by 12% of its level.", self.ROWS), [])
        # A version without typed figures (no explanation) gives the rule nothing to read.
        self.assertEqual(rules("SYNTHETIC: demand fell by 12%.", []), [])

    def test_the_rule_reads_every_text_of_a_version(self):
        content = banks_brief("report-x")
        bad = "SYNTHETIC: housing demand fell by 27%."
        content.update(headline=bad, summary=bad, facts=[{"text": bad, "reports": ["report-x"]}],
                       implications=[{"text": "SYNTHETIC: " + bad + " This may matter."}],
                       themes=[{"kind": "sector", "name": "SYNTHETIC housing", "basis": bad}],
                       uncertainties=[bad], missing=[bad])
        content["economics"]["main_uncertainty"] = "SYNTHETIC: whether lending fell by {f2}."
        found = {row["where"] for row in econ_fidelity.balance_findings(econ_fidelity.prose_places(content),
                                                                        econ_fidelity.typed_rows(content))}
        self.assertEqual(found, {"headline", "summary", "facts[0]", "implications[0]", "themes[0]",
                                 "uncertainties[0]", "missing[0]", "economics.main_uncertainty"})


class DraftingTest(unittest.TestCase):
    """The corrected first stage, over the SYNTHETIC bank survey and a simulated provider: a reply whose own texts write
    a balance as a change is refused before any second stage is prepared; a valid one goes on as before."""

    def world(self, theme: str) -> tuple[World, str]:
        world = World(self, model=True, extra=survey_items(START))
        story_id = world.story_id(BANKS)
        world.model.economics = lambda ids: with_report(banks_brief(ids[0])["economics"], ids[0])
        world.model.brief_reply = lambda answer: {**answer, "themes": [
            {"kind": "sector", "name": "SYNTHETIC lending to firms", "basis": theme}]}
        return world, story_id

    def run_first(self, world: World, story_id: str) -> tuple[dict, dict]:
        def now(name):
            return news_views.world(world.desk, START)["stories"][name]
        view = brief_drafting.preview(world.desk, now(story_id))
        self.assertEqual(view["stages"][0]["stage_version"], brief_stages.STAGE_VERSIONS[1])
        done, sent = brief_drafting.approve(world.desk, view["draft_id"], form(view), now, ACTOR, world.clock)
        self.assertTrue(sent)
        return done, brief_drafting.preview(world.desk, now(story_id))

    def test_a_balance_written_as_a_change_is_refused_and_nothing_more_is_prepared(self):
        world, story_id = self.world("SYNTHETIC: credit standards for loans to firms tightened by 9%.")
        done, after = self.run_first(world, story_id)
        self.assertEqual(done["attempt"]["state"], "invalid")
        self.assertIn("themes[0]", done["attempt"]["detail"])
        self.assertEqual((after["state"], after["stages"][1]["draft_id"]), ("stopped", None))
        self.assertEqual(world.model.stages(), [1])

    def test_a_balance_kept_as_respondents_answers_is_validated_and_stage_two_prepared(self):
        world, story_id = self.world("SYNTHETIC: a net 9% of banks reported tighter standards for loans to firms.")
        done, after = self.run_first(world, story_id)
        self.assertEqual(done["attempt"]["state"], "validated")
        self.assertEqual((after["state"], after["stages"][1]["stage_version"]),
                         ("awaiting_stage_2", brief_stages.STAGE_VERSIONS[2]))


class CompatibilityTest(unittest.TestCase):
    """History is read under the contracts and checks it was recorded with; nothing is reinterpreted silently."""

    def test_the_contracts_are_versioned_and_their_output_formats_unchanged(self):
        # Current since 1 November 2026 (time, scope and an alternative's support, then how long a flow lasts, then a
        # holder's name as written and plain text; test_econ_consistency, test_plain_names).
        self.assertEqual(brief_stages.VERSION, "brief-stages-0.8")
        self.assertEqual(brief_stages.STAGE_VERSIONS, {1: "brief-evidence-8", 2: "brief-explanation-6"})
        self.assertEqual(brief_drafting.PROMPT_VERSION, "brief-prompt-16")
        self.assertEqual(econ_fidelity.FIDELITY_VERSION, "econ-fidelity-0.6")
        # Each first-stage contract keeps the rule version it has checked replies with; a later rule needs its own
        # first-stage decision (econ-fidelity-0.6 adds only a publication stop, so brief-evidence-8 keeps 0.5's).
        self.assertEqual(brief_stages.RETAINED_CHECKED, {"brief-evidence-4": "econ-fidelity-0.4",
                                                         "brief-evidence-5": "econ-fidelity-0.5",
                                                         "brief-evidence-6": "econ-fidelity-0.5",
                                                         "brief-evidence-7": "econ-fidelity-0.5",
                                                         "brief-evidence-8": "econ-fidelity-0.5"})
        # The provider accepted brief-evidence-3's format live on 29 October, which brief-evidence-4 kept byte for
        # byte: it is still how their replies decode. Their second stage's format is brief-explanation-4's, which
        # brief-explanation-5 kept (brief-explanation-6 adds an alternative's support: test_econ_consistency).
        historical = {1: brief_stages.STAGE_1_SCHEMAS["brief-evidence-4"],
                      2: brief_stages.stage_2_schema(version="brief-explanation-4")}
        for stage, schema in historical.items():
            sent = {"type": "json_schema", "schema": brief_wire.output_format(schema)}  # As a request carries it.
            self.assertEqual(ns.sha256_of(sent), CASE["format_sha256"][str(stage)])
        self.assertIs(brief_stages.STAGE_1_SCHEMAS["brief-evidence-3"], brief_stages.STAGE_1_SCHEMAS["brief-evidence-4"])
        current = {"type": "json_schema", "schema": brief_stages.output_format(1)}
        self.assertNotEqual(ns.sha256_of(current), CASE["format_sha256"]["1"])  # brief-evidence-5's and -6's.
        # Replies are checked under the analysis and stages versions their contract was written for, never "the
        # current one" (pinned literally since econ-explanation-0.5).
        self.assertEqual((brief_stages.ANALYSIS_OF["brief-evidence-4"], brief_stages.STAGES_OF["brief-evidence-4"]),
                         ("econ-explanation-0.4", "brief-stages-0.4"))
        self.assertEqual((brief_stages.ANALYSIS_OF["brief-evidence-5"], brief_stages.STAGES_OF["brief-evidence-5"]),
                         ("econ-explanation-0.5", "brief-stages-0.5"))
        self.assertEqual(brief_stages.ANALYSIS_OF["brief-evidence-6"], "econ-explanation-0.6")
        self.assertEqual(brief_stages.ANALYSIS_OF["brief-evidence-7"], "econ-explanation-0.6")
        self.assertEqual(brief_stages.ANALYSIS_OF["brief-evidence-8"], story_economics.ANALYSIS_VERSION)

    def test_both_stages_state_the_rule_the_checks_apply(self):
        first, second = brief_stages.system(1), brief_stages.system(2)
        self.assertIn("never as the size of a change in what they were asked about", first)
        self.assertIn("credit a reason given for it to whoever gives it", first)
        self.assertIn("a survey's net percentage stays a balance of respondents' answers, never the size of a change",
                      second)
        for rules_, text in ((brief_stages.STAGE_1_RULES, first), (brief_stages.STAGE_2_RULES, second)):
            self.assertTrue(text.startswith(rules_[:60]))

    def test_the_prepared_second_stage_of_an_earlier_contract_is_superseded_never_sent(self):
        prepared = {"stage": 2, **{key: CASE["stage_2"][key] for key in ("stage_version", "stages_version")}}
        reason = brief_drafting.superseded(prepared)
        self.assertIn("brief-explanation-3", reason)
        self.assertIn(brief_stages.STAGE_VERSIONS[2], reason)
        earlier = {"stage": 1, "stage_version": CASE["stage_version"], "stages_version": CASE["stages_version"]}
        self.assertIsNotNone(brief_drafting.superseded(earlier))

    def test_a_version_saved_before_keeps_its_recorded_findings_until_revalidated(self):
        world = World(self, extra=survey_items(START))
        story = world.story(BANKS)
        content = banks_brief(story["material"]["reports"][0]["entry_id"])
        content["themes"][0]["basis"] = "SYNTHETIC: demand for housing loans fell by 27%."
        basis = story_economics.evidence(story["material"], None, None, story["first_at"])
        earlier = {"econ-fidelity-0.2": lambda content_, found: econ_fidelity.reference_findings(content_)}
        with mock.patch.object(econ_fidelity, "FIDELITY_VERSION", "econ-fidelity-0.2"), \
                mock.patch.object(econ_fidelity, "findings", earlier["econ-fidelity-0.2"]):
            old, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
                "content": content, "method": "editorial", "based_on": None, "idempotency_key": "balance-old-0001"},
                story["material"], "editor-1", START, basis=basis)
        self.assertTrue(old["publishable"])  # As it was checked then; its record is not rewritten.
        new, _ = story_briefs.revalidate_version(world.desk.newsroom, story["story_id"], {
            "version": old["version"], "content": content, "reason": "SYNTHETIC: recheck under the current rule",
            "idempotency_key": "balance-recheck-0001"}, story["material"], "editor-1", START, basis=basis)
        self.assertFalse(new["publishable"])
        self.assertEqual(new["guard"]["fidelity_version"], econ_fidelity.FIDELITY_VERSION)
        self.assertIn(("themes[0]", AS_CHANGE), {(row["where"], row["rule"]) for row in new["guard"]["findings"]})
        saved = {row["version"]: row for row in ns.state(world.desk.newsroom)["briefs"][story["story_id"]]}
        self.assertEqual(saved[old["version"]]["guard"]["fidelity_version"], "econ-fidelity-0.2")
        self.assertEqual(saved[old["version"]]["guard"]["findings"], [])
        self.assertEqual(saved[old["version"]]["content"], saved[new["version"]]["content"])


if __name__ == "__main__":
    unittest.main()
