"""QA fresh research-quality cases: a small SYNTHETIC set written by the QA chat on 15 October 2026, after
research-quality-0.2 was released, and never shown to the rubric's author before it was measured.

QA's original corpus (test_qa_research_quality) informed 0.2's development, so its improved counts are development
evidence. These cases test whether the checks carry over to other sources and other wordings of the same kinds of
mistake: faithful short quotes, unknown reasons against absent facts, numeric periods and units, direction and negation,
speaker attribution and unsupported conclusions. Two invented sources (an energy agency's weekly report and a central
bank's decision; neither is a real publication) and fake replies with one planted fault each, or none.

Kept apart, as in the original corpus:
- GOLD: what each source states or leaves out, checked against its text.
- REPLIES: fake provider replies; their basis labels are the model's own and never used as truth.
- READING: research_reading.classify, which must accept every case here (every quote is genuine), so the rubric sees it.
- RUBRIC: research_quality.assess, which only flags; a flag "at the fault" is one whose location is the planted fault's.

MEASURED records what the rubric did with each case when this file was written. A case that moves is a measured
before/after of the rubric and updates MEASURED in the same commit, naming the cases that moved. These are 20 synthetic
cases, not a model benchmark: they say nothing about how often a real model makes these mistakes.

Each rubric version keeps its own record (MEASURED_BY_VERSION); the version the backend serves must have one. The 20
cases were disclosed to the rubric's author on 15 October 2026, after 0.2 was measured, so they are regression and
development cases from research-quality-0.3 on; QA keeps further undisclosed cases privately, outside the public tree.
"""
import unittest

from second_order import research_analysis as ra, research_quality
from second_order.research_reading import classify
from test_qa_research_quality import message

ENERGY_HEADLINE = "Simulated Energy Agency reports weekly fuel inventories"
ENERGY = (f"October 8, 2026\n\n{ENERGY_HEADLINE}\n\n"
          "The Simulated Energy Agency said commercial crude oil inventories fell by 2.3 million barrels in the week "
          "ending October 2, 2026, to 412.6 million barrels.\n\n"
          "Gasoline inventories increased by 0.8 million barrels, while distillate inventories were unchanged.\n\n"
          "Refinery utilization averaged 91.4 percent, down 1.1 percentage points from the previous week.\n\n"
          "The agency did not give a reason for the change in distillate demand. Its administrator said the agency "
          "does not expect the crude drawdown to continue through the winter.\n\n"
          "SYNTHETIC TEST SOURCE written for the QA fresh research-quality cases.")
BANK_HEADLINE = "Simulated Central Bank holds its policy rate"
BANK = (f"September 30, 2026\n\n{BANK_HEADLINE}\n\n"
        "The Simulated Central Bank left its policy rate unchanged at 4.25 percent on September 30, 2026. "
        "Governor Mara Vell said inflation had eased to 2.9 percent in August from 3.1 percent in July.\n\n"
        "Deputy Governor Ilan Doss said the bank would not raise rates in the fourth quarter unless wage growth "
        "accelerated.\n\n"
        "The bank reported that household lending grew 0.6 percent in the second quarter. It did not say how much "
        "business lending changed.\n\n"
        "SYNTHETIC TEST SOURCE written for the QA fresh research-quality cases.")
SOURCES = {"energy": (ENERGY_HEADLINE, ENERGY), "bank": (BANK_HEADLINE, BANK)}

# What each source states (True) or leaves out (False). Checked against the texts in the first test.
GOLD = {
    "energy": [("crude oil inventories fell by 2.3 million barrels", True), ("to 412.6 million barrels", True),
               ("Gasoline inventories increased by 0.8 million barrels", True),
               ("distillate inventories were unchanged", True), ("averaged 91.4 percent", True),
               ("down 1.1 percentage points", True), ("did not give a reason", True),
               ("does not expect the crude drawdown to continue", True), ("billion", False), ("Cushing", False),
               ("shortage", False), ("hub", False)],
    "bank": [("left its policy rate unchanged at 4.25 percent", True), ("Governor Mara Vell said inflation", True),
             ("eased to 2.9 percent in August from 3.1 percent in July", True),
             ("Deputy Governor Ilan Doss said the bank would not raise rates in the fourth quarter", True),
             ("household lending grew 0.6 percent in the second quarter", True),
             ("did not say how much business lending changed", True), ("third quarter", False), ("ministry", False),
             ("cut", False), ("next meeting", False)],
}


def statement(text: str, quotes: list[str], basis: str = "data") -> dict:
    return {"statement": text, "basis": basis, "quotes": quotes}


ENERGY_FAITHFUL = [
    statement("Commercial crude oil inventories fell by 2.3 million barrels in the week ending October 2, 2026.",
              ["fell by 2.3 million barrels"]),
    statement("Refinery utilization averaged 91.4 percent.", ["averaged 91.4 percent"])]
BANK_FAITHFUL = [
    statement("The central bank did not change its policy rate, keeping it at 4.25 percent.",
              ["left its policy rate unchanged at 4.25 percent"], basis="action"),
    statement("Governor Mara Vell said inflation eased to 2.9 percent in August.",
              ["inflation had eased to 2.9 percent in August"])]
ENERGY_UNKNOWNS = ["Why distillate demand changed is not given.",
                   "Crude inventories at individual storage hubs are not reported."]
BANK_UNKNOWNS = ["How much business lending changed is not stated.",
                 "The date of the bank's next decision is not given."]


def reply(source: str, established: list[dict], interpretation: str | None = None, based_on: list[int] | None = None,
          missing: list[str] | None = None) -> dict:
    energy = source == "energy"
    return {"established": established,
            "interpretation": {"kind": "finding", "based_on": [1] if based_on is None else based_on,
                               "text": interpretation or ("Crude inventories declined in the reported week." if energy
                                                          else "The bank kept its rate while reporting lower "
                                                               "inflation.")},
            "assumptions": ["The weekly survey covers the same reporters as the week before." if energy else
                            "The statement reflects the whole decision."],
            "competing_explanations": [{"explanation": "A temporary import delay." if energy else
                                        "A pause before a later change.",
                                        "would_distinguish": "The following weeks' reports." if energy else
                                        "The next decision."}],
            "missing_information": (ENERGY_UNKNOWNS if energy else BANK_UNKNOWNS) if missing is None else missing,
            "tests": [{"check": "The next weekly report." if energy else "The next decision.",
                       "counts_against_if": "Inventories build again." if energy else "Rates move without wage "
                                                                                       "growth."}]}


# name: (source, reply, where the planted fault is (None: a correct reply), category, what GOLD shows is wrong)
CASES = {
    "e_faithful_short_quotes": ("energy", reply("energy", ENERGY_FAITHFUL, based_on=[1, 2]), None, "faithful", None),
    "e_faithful_synonyms": ("energy", reply("energy", [
        statement("Gasoline stocks rose by 0.8 million barrels.", ["Gasoline inventories increased by 0.8 million "
                                                                   "barrels"]),
        statement("Distillate inventories did not change.", ["distillate inventories were unchanged"])]),
        None, "faithful", None),
    "e_faithful_attributed_forecast": ("energy", reply("energy", [statement(
        "The agency's administrator said the agency does not expect the crude drawdown to continue through the "
        "winter.", ["does not expect the crude drawdown to continue through the winter"], basis="forecast")]),
        None, "faithful", None),
    "e_unknown_reason_kept_apart": ("energy", reply("energy", ENERGY_FAITHFUL, missing=[
        "The agency gives no reason for the change in distillate demand.",
        "Crude inventories at individual storage hubs are not reported."]), None, "unknowns", None),
    "b_faithful_negated_unchanged": ("bank", reply("bank", BANK_FAITHFUL), None, "direction", None),
    "e_present_fact_marked_missing": ("energy", reply("energy", ENERGY_FAITHFUL, missing=[
        "Refinery utilization for the week is not reported.", "Crude inventories at individual storage hubs are not "
                                                              "reported."]),
        "missing_information[1]", "unknowns", "the source reports utilization of 91.4 percent"),
    "e_unit_points_as_percent": ("energy", reply("energy", [statement(
        "Refinery utilization fell 1.1 percent from the previous week.",
        ["down 1.1 percentage points from the previous week"])]),
        "established[1]", "units", "1.1 percentage points, not percent"),
    "e_unit_million_as_billion": ("energy", reply("energy", [statement(
        "Commercial crude oil inventories fell by 2.3 billion barrels.", ["fell by 2.3 million barrels"])]),
        "established[1]", "units", "2.3 million barrels, not billion"),
    "e_direction_synonym_flipped": ("energy", reply("energy", [statement(
        "Gasoline inventories decreased by 0.8 million barrels.",
        ["Gasoline inventories increased by 0.8 million barrels"])]),
        "established[1]", "direction", "gasoline inventories increased"),
    "e_number_from_another_sentence": ("energy", reply("energy", [statement(
        "Commercial crude oil inventories fell to 91.4 million barrels.", ["fell by 2.3 million barrels"])]),
        "established[1]", "numbers", "91.4 is the utilization percentage; inventories were 412.6 million barrels"),
    "e_level_as_change": ("energy", reply("energy", [statement(
        "Commercial crude oil inventories fell by 412.6 million barrels.", ["to 412.6 million barrels"])]),
        "established[1]", "numbers", "412.6 million barrels is the level; the fall was 2.3 million"),
    "e_unsupported_conclusion": ("energy", reply("energy", [statement(
        "The drawdown means winter fuel shortages are likely.", ["fell by 2.3 million barrels"])]),
        "established[1]", "conclusion", "the source says nothing about shortages"),
    "b_period_month_swap": ("bank", reply("bank", [statement(
        "Governor Mara Vell said inflation eased to 2.9 percent in July.",
        ["inflation had eased to 2.9 percent in August"])]),
        "established[1]", "periods", "2.9 percent was August; July was 3.1 percent"),
    "b_period_quarter_not_in_source": ("bank", reply("bank", [statement(
        "Household lending grew 0.6 percent in the third quarter.",
        ["household lending grew 0.6 percent in the second quarter"])]),
        "established[1]", "periods", "the second quarter, not the third"),
    "b_negation_dropped": ("bank", reply("bank", [statement(
        "Deputy Governor Ilan Doss said the bank would raise rates in the fourth quarter.",
        ["the bank would not raise rates in the fourth quarter unless wage growth accelerated"], basis="forecast")]),
        "established[1]", "direction", "he said the bank would not raise rates"),
    "b_negation_added": ("bank", reply("bank", [statement(
        "Governor Mara Vell said inflation did not ease in August.",
        ["inflation had eased to 2.9 percent in August"])]),
        "established[1]", "direction", "inflation eased"),
    "b_rate_raised_not_held": ("bank", reply("bank", [statement(
        "The central bank raised its policy rate to 4.25 percent.", ["left its policy rate unchanged at 4.25 percent"],
        basis="action")]), "established[1]", "direction", "the rate was left unchanged"),
    "b_speaker_swapped_within_source": ("bank", reply("bank", [statement(
        "Deputy Governor Ilan Doss said inflation eased to 2.9 percent in August.",
        ["inflation had eased to 2.9 percent in August"])]),
        "established[1]", "attribution", "the governor said it, not the deputy governor"),
    "b_speaker_not_in_source": ("bank", reply("bank", [statement(
        "The finance ministry said inflation eased to 2.9 percent in August.",
        ["inflation had eased to 2.9 percent in August"])]),
        "established[1]", "attribution", "no ministry is in the source"),
    "b_unsupported_interpretation": ("bank", reply("bank", BANK_FAITHFUL, based_on=[1, 2], interpretation=(
        "The bank is preparing to cut rates before the end of the year.")),
        "interpretation", "conclusion", "nothing in the source supports a coming cut"),
}

# What research-quality-0.2 flagged for each case when this file was written: (check, where) pairs, sorted.
# ENERGY_FAITHFUL's first statement repeats the week's date ("October 2, 2026"), which its short quote leaves out
# though the quoted sentence holds it: 2 and 2026 as numbers, October and 2026 as periods.
DATE_OUTSIDE_SHORT_QUOTE = [("number_not_in_quotes", "established[1]")] * 2 + \
    [("period_not_in_quotes", "established[1]")] * 2
MEASURED = {
    "e_faithful_short_quotes": DATE_OUTSIDE_SHORT_QUOTE,
    "e_faithful_synonyms": [],
    "e_faithful_attributed_forecast": [],
    "e_unknown_reason_kept_apart": DATE_OUTSIDE_SHORT_QUOTE,
    "b_faithful_negated_unchanged": [],
    "e_present_fact_marked_missing": [("absence_contradicted", "missing_information[1]")] + DATE_OUTSIDE_SHORT_QUOTE,
    "e_unit_points_as_percent": [("unit_differs", "established[1]")],
    "e_unit_million_as_billion": [("unit_differs", "established[1]")],
    "e_direction_synonym_flipped": [("direction_differs", "established[1]")],
    "e_number_from_another_sentence": [("number_not_in_quotes", "established[1]")],
    "e_level_as_change": [],
    "e_unsupported_conclusion": [("beyond_quotes", "established[1]")],
    "b_period_month_swap": [("period_not_in_quotes", "established[1]")],
    "b_period_quarter_not_in_source": [("period_not_in_source", "established[1]")],
    "b_negation_dropped": [("direction_differs", "established[1]")],
    "b_negation_added": [],
    "b_rate_raised_not_held": [("direction_differs", "established[1]")],
    "b_speaker_swapped_within_source": [],
    "b_speaker_not_in_source": [("speaker_not_in_source", "established[1]")],
    "b_unsupported_interpretation": [],
}
MEASURED_0_2 = MEASURED
# What research-quality-0.3 (data ed3a180) flags, measured by QA on 15 October 2026 after these cases were disclosed:
# six cases moved. The date outside a short quote is no longer flagged; a level stated as a change, an added negation
# and a speaker swapped within the source are flagged at the fault. The unsupported interpretation is still a miss.
MEASURED_0_3 = MEASURED_0_2 | {
    "e_faithful_short_quotes": [],
    "e_unknown_reason_kept_apart": [],
    "e_present_fact_marked_missing": [("absence_contradicted", "missing_information[1]")],
    "e_level_as_change": [("level_change_differs", "established[1]")],
    "b_negation_added": [("negation_differs", "established[1]")],
    "b_speaker_swapped_within_source": [("speaker_differs", "established[1]")],
}
MEASURED_BY_VERSION = {"research-quality-0.2": MEASURED_0_2, "research-quality-0.3": MEASURED_0_3}
# What each record says: (faults flagged at the fault, faults missed), the missed cases, the correct replies flagged.
COUNTS_BY_VERSION = {
    "research-quality-0.2": ((11, 4), ["b_negation_added", "b_speaker_swapped_within_source",
                                       "b_unsupported_interpretation", "e_level_as_change"],
                             ["e_faithful_short_quotes", "e_unknown_reason_kept_apart"]),
    "research-quality-0.3": ((14, 1), ["b_unsupported_interpretation"], []),
}


def read(name: str) -> dict:
    source_key, output, _, _, _ = CASES[name]
    return classify(message(output), ra.MODEL, SOURCES[source_key][1])


def assessed(name: str) -> dict:
    headline, text = SOURCES[CASES[name][0]]
    return research_quality.assess(headline, text, read(name)["analysis"])


def flags(name: str) -> list[tuple[str, str]]:
    return sorted((finding["check"], finding["where"]) for finding in assessed(name)["findings"])


class FreshCases(unittest.TestCase):
    def test_gold_facts_are_what_the_synthetic_sources_say(self):
        for key, facts in GOLD.items():
            text = SOURCES[key][1]
            for fact, present in facts:
                with self.subTest(source=key, fact=fact):
                    self.assertEqual(fact in text, present)

    def test_the_reading_layer_accepts_every_case_with_every_quote_located_exactly(self):
        """Every fault here is behind genuine quotes, so quote and structure validation alone passes each one."""
        for name, (source_key, _, _, _, _) in CASES.items():
            with self.subTest(name):
                result = read(name)
                self.assertEqual(result["outcome"], "analysis", result["problem"])
                text = SOURCES[source_key][1]
                for item in result["analysis"]["established"]:
                    for quote in item["quotes"]:
                        self.assertEqual(quote["match"], "exact")
                        self.assertEqual(text[quote["start"]:quote["end"]], quote["source_passage"])

    def test_each_case_is_flagged_as_measured(self):
        """A moved case is a measured before/after of the rubric: a new version adds its own record, never silently."""
        version = research_quality.RUBRIC_VERSION
        self.assertIn(version, MEASURED_BY_VERSION, f"{version} is not measured on these cases yet")
        self.assertEqual({name: flags(name) for name in CASES}, MEASURED_BY_VERSION[version])

    def test_counts_at_the_fault_on_clean_replies_and_misses(self):
        """Stated plainly, from each version's record: flags at each planted fault, flags on correct replies, and the
        faults left without a flag at their location (flags elsewhere in a faulty reply do not count as finding its
        fault)."""
        self.assertEqual(sum(1 for _, _, where, _, _ in CASES.values() if not where), 5)
        for version, measured in MEASURED_BY_VERSION.items():
            with self.subTest(version):
                at_fault = sorted(name for name, (_, _, where, _, _) in CASES.items()
                                  if where and any(place == where for _, place in measured[name]))
                missed = sorted(name for name, (_, _, where, _, _) in CASES.items() if where and name not in at_fault)
                clean_flagged = sorted(name for name, (_, _, where, _, _) in CASES.items()
                                       if not where and measured[name])
                self.assertEqual(((len(at_fault), len(missed)), missed, clean_flagged), COUNTS_BY_VERSION[version])

    def test_the_rubric_only_flags_and_lists_the_human_review(self):
        for name in CASES:
            with self.subTest(name):
                found = assessed(name)
                self.assertEqual(found["rubric_version"], research_quality.RUBRIC_VERSION)
                self.assertIn(found["rubric_version"], MEASURED_BY_VERSION)
                self.assertEqual(found["rejected"], [])
                self.assertTrue(all(finding["level"] == "flagged" for finding in found["findings"]))
                self.assertEqual(len(found["human_review"]), 4)


if __name__ == "__main__":
    unittest.main()
