"""QA research-quality cases: what the current reading of a research reply proves, on SYNTHETIC sources with known facts
and fake replies that each carry one known defect (or none).

This is a quality regression layer, not the forecasting evaluation: nothing is frozen, scored against market outcomes
or added to an evidence pool, and no paid request is made. Three things are kept apart:

- GOLD: the facts each synthetic source states or leaves out, written by QA and checked against the source text below.
- REPLIES: fake provider replies. Their own labels (a statement's basis, the interpretation's kind) are the model's
  self-rating and are never used as truth.
- VERDICT: what the reading layer (research_reading.classify, research-result-view-0.1) does with each reply.

The reading layer proves that every quote occurs in the source text (exactly, or after plain quotes, dashes and
whitespace) and that the reply's structure and references are valid; a reply failing either is refused as a whole. It
does not compare a statement with its quote. So a correct quote under a wrong number, period, attribution or direction,
an unsupported cause, a stated fact listed as missing, a forecast labelled as data, a headline taken for a publication
and a truncated text all pass: those still need a human reviewer. BASELINE records each verdict; a change to the reading
layer that moves any case is a measured before/after and updates BASELINE in the same commit, naming the cases that
moved. The user is told only what is checked (the outcome note), and that is asserted end to end over HTTP.

RUBRIC: the data owner's research-quality rubric (research_quality.assess) only flags; it refuses nothing and changes no
result. RUBRIC_0_2 records what research-quality-0.2 flags on each case the reading layer accepts, and FAULT_AT where
each planted fault is, so flags at the fault, flags on correct replies and misses are counted apart from the reading
layer's refusals. This corpus was shared with the rubric's author and informed 0.2, so these counts are development
evidence, not an unseen benchmark; test_qa_quality_fresh holds cases written after 0.2.
"""
import json
from pathlib import Path
import tempfile
import unittest

from account_fakes import USER_WRITE, World, source_form
from model_fixtures import THINKING
from second_order import research_analysis as ra, research_quality, user_research
from second_order.research_reading import classify

HEADLINE = "Simulated statistics office reports third-quarter output"
SOURCE = (f"October 13, 2026\n\n{HEADLINE}\n\n"
          "The Simulated Statistics Office said output in the surveyed sector rose 1.2 percent in the third quarter of "
          "2026, after a 0.4 percent decline in the second quarter.\n\n"
          "Employment in the sector was unchanged at 48,200 jobs in September.\n\n"
          "The office said it expects to revise the third-quarter estimate in November, when late survey responses "
          "arrive.\n\nSYNTHETIC TEST SOURCE written for the QA research-quality cases.")
TRUNCATED = SOURCE[:SOURCE.index("1.2 percent") + len("1.2 per")]  # Cut mid-word, as a broken import might.

# What each source states, and what it does not: (text, present). Checked against the source in the first test.
GOLD_FACTS = {
    "output": [("rose 1.2 percent in the third quarter of 2026", True), ("0.4 percent decline in the second quarter",
                                                                        True)],
    "employment": [("unchanged at 48,200 jobs in September", True)],
    "attribution": [("The Simulated Statistics Office said", True), ("central bank", False)],
    "forecast": [("expects to revise the third-quarter estimate in November", True)],
    "absent": [("because", False), ("export", False), ("recession", False), ("seasonally adjusted", False)],
}

GOOD_QUOTE = "rose 1.2 percent in the third quarter of 2026"
EMPLOYMENT_QUOTE = "Employment in the sector was unchanged at 48,200 jobs in September."
FORECAST_QUOTE = "it expects to revise the third-quarter estimate in November"
HONEST_UNKNOWNS = ["Why output rose is not stated.", "Figures for other sectors are not given."]


def statement(text: str, quotes: list[str], basis: str = "data") -> dict:
    return {"statement": text, "basis": basis, "quotes": quotes}


def reply(established: list[dict], kind: str = "finding", based_on: list[int] | None = None,
          interpretation: str = "Output recovered in the third quarter after a second-quarter decline.",
          missing: list[str] | None = None) -> dict:
    return {"established": established,
            "interpretation": {"kind": kind, "based_on": [1] if based_on is None else based_on, "text": interpretation},
            "assumptions": ["The survey covers the sector as the office defines it."],
            "competing_explanations": [{"explanation": "A one-off rebound after the decline.",
                                        "would_distinguish": "The fourth-quarter figure."}],
            "missing_information": HONEST_UNKNOWNS if missing is None else missing,
            "tests": [{"check": "The revised estimate in November.", "counts_against_if": "It is revised below zero."}]}


FAITHFUL = [statement("The office said output in the surveyed sector rose 1.2 percent in the third quarter of 2026.",
                      [GOOD_QUOTE]),
            statement("Employment in the sector was unchanged at 48,200 jobs in September.", [EMPLOYMENT_QUOTE])]

# name: (source, reply, defect, layer). layer: "none" (a correct reply), "quote" (the reading layer refuses it),
# "semantic" (the statement or unknowns misstate a correctly quoted source) or "input" (the source text itself is
# not the publication). The defect names what GOLD shows to be wrong.
CASES = {
    "faithful": (SOURCE, reply(FAITHFUL), None, "none"),
    "honest_no_additional_finding": (SOURCE, reply(FAITHFUL[:1], kind="no_additional_finding", based_on=[],
                                                   interpretation="Nothing beyond what the office states."),
                                     None, "none"),
    "wrong_number": (SOURCE, reply([statement("Output in the surveyed sector rose 2.1 percent in the third quarter.",
                                              [GOOD_QUOTE])]), "the statement says 2.1 percent; the source 1.2",
                     "semantic"),
    "wrong_period": (SOURCE, reply([statement("Output rose 1.2 percent in the second quarter of 2026.",
                                              [GOOD_QUOTE])]), "the rise was in the third quarter, not the second",
                     "semantic"),
    "wrong_attribution": (SOURCE, reply([statement("The central bank reported that output rose 1.2 percent.",
                                                   [GOOD_QUOTE])]), "the statistics office reported it",
                          "semantic"),
    "contradiction": (SOURCE, reply([statement("Output fell in the third quarter of 2026.", [GOOD_QUOTE])]),
                      "the source says output rose", "semantic"),
    "level_as_change": (SOURCE, reply([statement("Employment rose by 48,200 jobs in September.",
                                                 [EMPLOYMENT_QUOTE])]), "48,200 is the level; it was unchanged",
                        "semantic"),
    "unsupported_cause": (SOURCE, reply([statement("Output rose because export orders recovered.", [GOOD_QUOTE])]),
                          "the source gives no cause", "semantic"),
    "present_fact_marked_missing": (SOURCE, reply(FAITHFUL, missing=["The size of the second-quarter change is not "
                                                                     "stated."]),
                                    "the source states a 0.4 percent decline", "semantic"),
    "forecast_labelled_as_data": (SOURCE, reply([statement("The third-quarter estimate will be revised in November.",
                                                           [FORECAST_QUOTE], basis="data")]),
                                  "an attributed plan, stated as fact and labelled data", "semantic"),
    "unsupported_interpretation": (SOURCE, reply(FAITHFUL, interpretation="The sector is entering a recession."),
                                   "nothing in the source supports a recession", "semantic"),
    "headline_only_source": (HEADLINE, reply([statement("Output rose 1.2 percent in the third quarter.",
                                                        ["reports third-quarter output"])], missing=[]),
                             "the source is a headline; it states no figure", "input"),
    "truncated_source": (TRUNCATED, reply([statement("Output rose 1.2 percent in the third quarter.",
                                                     ["rose 1.2 per"])], missing=[]),
                         "the text was cut mid-word and the rest is unseen", "input"),
    "fabricated_quote": (SOURCE, reply([statement("Output rose 2.1 percent.", ["output rose 2.1 percent overall"])]),
                         "the quote is not in the source", "quote"),
    "altered_quote_number": (SOURCE, reply([statement("Output rose 2.1 percent in the third quarter.",
                                                      ["rose 2.1 percent in the third quarter of 2026"])]),
                             "the quote's number was changed", "quote"),
    "quote_too_short": (SOURCE, reply([statement("Output rose 1.2 percent.", ["1.2"])]),
                        "a three-character quote locates nothing reliably", "quote"),
    "reference_out_of_range": (SOURCE, reply(FAITHFUL, based_on=[3]),
                               "the interpretation names a statement that does not exist", "quote"),
}

# The reading layer's verdict on each case today (research-result-view-0.1): "accepted" or "refused".
BASELINE = {name: "refused" if layer == "quote" else "accepted" for name, (_, _, _, layer) in CASES.items()}
ACCEPTED = ("analysis", "no additional finding")

# Where each planted semantic or input fault is, in the rubric's own location names (statements count from 1).
FAULT_AT = {"wrong_number": "established[1]", "wrong_period": "established[1]", "wrong_attribution": "established[1]",
            "contradiction": "established[1]", "level_as_change": "established[1]",
            "unsupported_cause": "established[1]", "present_fact_marked_missing": "missing_information[1]",
            "forecast_labelled_as_data": "established[1]", "unsupported_interpretation": "interpretation",
            "headline_only_source": "source", "truncated_source": "source"}
# What research-quality-0.2 flagged on each accepted case (check, where), sorted; measured by QA on 15 October 2026.
RUBRIC_0_2 = {
    "faithful": [], "honest_no_additional_finding": [],
    "wrong_number": [("number_not_in_source", "established[1]")],
    "wrong_period": [("period_not_in_quotes", "established[1]")],
    "wrong_attribution": [("speaker_not_in_source", "established[1]")],
    "contradiction": [("direction_differs", "established[1]")],
    "level_as_change": [("direction_differs", "established[1]")],
    "unsupported_cause": [("beyond_quotes", "established[1]")],
    "present_fact_marked_missing": [("absence_contradicted", "missing_information[1]")],
    "forecast_labelled_as_data": [("basis_mismatch", "established[1]")],
    "unsupported_interpretation": [],
    "headline_only_source": [("number_not_in_source", "established[1]"), ("period_not_in_source", "established[1]"),
                             ("source_may_be_cut", "source"), ("source_too_short", "source")],
    "truncated_source": [("beyond_quotes", "established[1]"), ("period_not_in_source", "established[1]"),
                         ("source_may_be_cut", "source"), ("source_too_short", "source")],
}


def message(output: dict, tool: bool = True) -> bytes:
    """A fake Messages API reply carrying the analysis (SYNTHETIC): one call of the research tool (research-prompt-1),
    or with ``tool=False`` the response's text in the JSON output format (research-prompt-2)."""
    block = {"type": "tool_use", "id": "toolu_qa_quality", "name": ra.TOOL_NAME, "input": output} if tool else         {"type": "text", "text": json.dumps(output)}
    return json.dumps({"id": "msg_qa_quality", "type": "message", "role": "assistant", "model": ra.MODEL,
                       "content": [dict(THINKING), block], "stop_reason": "tool_use" if tool else "end_turn",
                       "stop_sequence": None, "usage": {"input_tokens": 2100, "output_tokens": 700}}).encode("utf-8")


def verdict(name: str) -> dict:
    source, output, _, _ = CASES[name]
    return classify(message(output), ra.MODEL, source)


class ReadingLayer(unittest.TestCase):
    def test_gold_facts_are_what_the_synthetic_source_says(self):
        for topic, facts in GOLD_FACTS.items():
            for text, present in facts:
                with self.subTest(topic=topic, text=text):
                    self.assertEqual(text in SOURCE, present)
        self.assertNotIn("2.1", SOURCE)
        self.assertNotIn("1.2", HEADLINE)
        self.assertTrue(TRUNCATED.endswith("1.2 per") and SOURCE.startswith(TRUNCATED))

    def test_correct_replies_are_accepted_with_every_quote_located_exactly(self):
        for name in ("faithful", "honest_no_additional_finding"):
            with self.subTest(name):
                result = verdict(name)
                self.assertIn(result["outcome"], ACCEPTED, result["problem"])
                quotes = [quote for item in result["analysis"]["established"] for quote in item["quotes"]]
                self.assertTrue(quotes and all(quote["match"] == "exact" for quote in quotes))
                for quote in quotes:
                    self.assertEqual(SOURCE[quote["start"]:quote["end"]], quote["source_passage"])

    def test_quote_and_structure_defects_are_refused_as_a_whole(self):
        for name, (_, _, defect, layer) in CASES.items():
            if layer != "quote":
                continue
            with self.subTest(name, defect=defect):
                result = verdict(name)
                self.assertEqual((result["outcome"], result["analysis"]), ("refused", None))
                self.assertTrue(result["problem"])

    def test_each_verdict_matches_the_recorded_baseline(self):
        """A moved case is a measured before/after of the reading layer: update BASELINE with it, never silently."""
        observed = {name: "accepted" if verdict(name)["outcome"] in ACCEPTED else "refused" for name in CASES}
        self.assertEqual(observed, BASELINE)

    def test_the_baseline_detects_no_semantic_or_input_defect(self):
        """Stated plainly: of the cases whose quotes are all genuine, the reading layer refuses none."""
        missed = sorted(name for name, (_, _, _, layer) in CASES.items()
                        if layer in ("semantic", "input") and BASELINE[name] == "accepted")
        caught = sorted(name for name, (_, _, _, layer) in CASES.items() if layer == "quote" and
                        BASELINE[name] == "refused")
        self.assertEqual(len(missed), 11, missed)
        self.assertEqual(len(caught), 4, caught)


class Rubric(unittest.TestCase):
    """research-quality-0.2 on the same cases, kept apart from the reading layer's verdict."""

    def flags(self, name: str) -> list[tuple[str, str]]:
        source, _, _, _ = CASES[name]
        found = research_quality.assess(HEADLINE, source, verdict(name)["analysis"])
        self.assertEqual(found["rejected"], [])  # It only flags.
        return sorted((finding["check"], finding["where"]) for finding in found["findings"])

    def test_every_case_the_reading_layer_accepts_is_flagged_as_measured(self):
        """A moved case is a measured before/after of the rubric: update RUBRIC_0_2 with it, never silently."""
        accepted = [name for name in CASES if BASELINE[name] == "accepted"]
        self.assertEqual({name: self.flags(name) for name in accepted}, RUBRIC_0_2)
        self.assertEqual(sorted(FAULT_AT), sorted(name for name, (_, _, _, layer) in CASES.items()
                                                  if layer in ("semantic", "input")))

    def test_counts_at_the_fault_on_correct_replies_and_misses_apart_from_refusals(self):
        refused = sorted(name for name in CASES if BASELINE[name] == "refused")
        at_fault = sorted(name for name, where in FAULT_AT.items()
                          if any(place == where for _, place in RUBRIC_0_2[name]))
        missed = sorted(set(FAULT_AT) - set(at_fault))
        clean_flagged = sorted(name for name, (_, _, _, layer) in CASES.items() if layer == "none" and
                               RUBRIC_0_2[name])
        self.assertEqual(len(refused), 4)  # Quote and structure faults: refused before the rubric reads anything.
        self.assertEqual((len(at_fault), len(FAULT_AT)), (10, 11))
        self.assertEqual(missed, ["unsupported_interpretation"])
        self.assertEqual(clean_flagged, [])


class WhatTheUserIsTold(unittest.TestCase):
    """The wrong-number reply over the real user routes (temporary store, fake provider): it is recorded as an
    analysis, and the outcome note claims only that the quotes were found."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.standard_terms(credits=40, limit=3)
        self.world.provider.handler = self.answer
        self.user = self.world.client("reader-a")
        self.addCleanup(self.user.close)

    def answer(self, request):
        import httpx
        self.world.provider.requests.append(request.content)
        tool = "tools" in json.loads(request.content)  # Answer in the shape the saved request asks for.
        return httpx.Response(200, content=message(CASES["wrong_number"][1], tool),
                              headers={"content-type": "application/json", "request-id": "req_qa_quality"})

    def test_a_correctly_quoted_wrong_number_is_shown_with_a_note_that_claims_only_the_quotes(self):
        source = self.user.post("/api/user/sources", headers=USER_WRITE,
                                json=source_form(headline=HEADLINE, text=SOURCE)).json()["source"]["source_id"]
        analysis = self.user.post("/api/user/analyses", headers=USER_WRITE,
                                  json={"source_id": source, "effort": "high"}).json()["analysis"]
        quote = self.user.post(f"/api/user/analyses/{analysis['analysis_id']}/quotes", headers=USER_WRITE,
                               json={}).json()["quote"]
        ran = self.user.post(f"/api/user/analyses/{analysis['analysis_id']}/runs", headers=USER_WRITE, json={
            "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"], "approve": True})
        self.assertEqual(ran.status_code, 201, ran.text[:300])
        result = ran.json()["analysis"]["result"]
        self.assertEqual(result["outcome"], "analysis")
        shown = result["analysis"]["established"][0]
        self.assertIn("2.1 percent", shown["statement"])
        self.assertEqual(shown["quotes"][0]["source_passage"], GOOD_QUOTE)
        self.assertEqual(result["note"], user_research.NOTES["analysis"])
        self.assertIn("for you to judge", result["note"])
        for claim in ("correct", "accurate", "verified", "confirmed", "true"):
            self.assertNotIn(claim, result["note"].lower())
        self.assertEqual(len(self.world.provider.requests), 1)


if __name__ == "__main__":
    unittest.main()
