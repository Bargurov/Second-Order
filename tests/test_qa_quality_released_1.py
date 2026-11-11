"""QA's research-quality set 1, released (written by the QA chat). It was a held-out set until its release; it is not
a holdout now, but a regression and development set.

Set 1 was written on 15 October 2026, after research-quality-0.2 and the disclosure of the 20 fresh cases, and kept
out of git and from the rubric's author. It was measured on 0.2 and on 0.3 (data ed3a180) with only its counts and the
SHA-256 of its flags recorded (tests/qa_quality_measure.py). Admin adopted 0.3 as the canonical checkpoint at a970fbc, so
by the release protocol the set is released here: tests/qa_quality_released_1.json is byte for byte the file whose
SHA-256 was committed before 0.3 was measured on it. From now on it is a regression and development set like the fresh
cases; a later set, written after this release, stays private.

13 SYNTHETIC cases on two invented sources (a labour office's employment report and a trade ministry's monthly figures;
neither is a real publication): 5 correct replies and 8 with one planted fault each. MEASURED_BY_VERSION keeps what each
rubric version flagged in each case, and its flags give the SHA-256 recorded for that version before the release; the
version the backend serves must have a record. These are counts of a lexical checker on synthetic replies, not a model's
accuracy. A reply without flags is not shown to be correct, and an interpretation the statements do not support is left
to the human review the rubric lists: 0.3 misses that case here, as it misses the fresh corpus's.
"""
import hashlib
import json
from pathlib import Path
import unittest

import qa_quality_measure
from second_order import research_quality

FILE = Path(__file__).resolve().parent / "qa_quality_released_1.json"

NONE: list = []
MEASURED_0_2 = {
    "l_faithful_date_outside_short_quote": [["number_not_in_quotes", "established[1]"],
                                            ["period_not_in_quotes", "established[1]"],
                                            ["period_not_in_quotes", "established[1]"]],
    "t_faithful_level_from_to": NONE,
    "l_faithful_attributed_speaker": NONE,
    "t_faithful_negation_paraphrased": [["beyond_quotes", "established[1]"]],
    "t_level_as_change": NONE,
    "l_negation_added": [["direction_differs", "established[1]"]],
    "t_speaker_swapped_within_source": NONE,
    "l_unsupported_interpretation": NONE,
    "t_period_year_swap": [["number_not_in_quotes", "established[1]"], ["period_not_in_quotes", "established[1]"]],
    "l_unchanged_as_rise": [["direction_differs", "established[1]"]],
    "t_number_on_the_wrong_entity": NONE,
    "l_faithful_unknown_the_source_states": [["absence_contradicted", "missing_information[1]"]],
    "l_present_fact_marked_missing": NONE,
}
# 0.3 (data ed3a180, adopted by Admin at a970fbc): the date outside a short quote is no longer flagged; the level read as
# a change and the swapped speaker are now flagged at the fault (level_change_differs, speaker_differs); the year swap
# keeps one period flag.
MEASURED_0_3 = {**MEASURED_0_2,
                "l_faithful_date_outside_short_quote": NONE,
                "t_level_as_change": [["level_change_differs", "established[1]"]],
                "t_speaker_swapped_within_source": [["speaker_differs", "established[1]"]],
                "t_period_year_swap": [["period_not_in_quotes", "established[1]"]]}
MEASURED_BY_VERSION = {"research-quality-0.2": MEASURED_0_2, "research-quality-0.3": MEASURED_0_3}
# (correct replies with any flag, faulty replies flagged at the fault, faulty replies without a flag there)
COUNTS_BY_VERSION = {
    "research-quality-0.2": (
        ["l_faithful_date_outside_short_quote", "l_faithful_unknown_the_source_states",
         "t_faithful_negation_paraphrased"],
        ["l_negation_added", "l_unchanged_as_rise", "t_period_year_swap"],
        ["l_present_fact_marked_missing", "l_unsupported_interpretation", "t_level_as_change",
         "t_number_on_the_wrong_entity", "t_speaker_swapped_within_source"]),
    "research-quality-0.3": (
        ["l_faithful_unknown_the_source_states", "t_faithful_negation_paraphrased"],
        ["l_negation_added", "l_unchanged_as_rise", "t_level_as_change", "t_period_year_swap",
         "t_speaker_swapped_within_source"],
        ["l_present_fact_marked_missing", "l_unsupported_interpretation", "t_number_on_the_wrong_entity"]),
}


def released() -> bytes:
    return FILE.read_bytes().replace(b"\r\n", b"\n")  # A checkout may write CRLF; the file was fixed with LF.


class ReleasedSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = json.loads(released())
        cls.cases = cls.body["cases"]

    def test_the_released_file_is_the_one_fixed_before_0_3_was_measured(self):
        # The legacy key name stays because the released file's bytes are pinned; the set is not a holdout now.
        self.assertEqual(self.body["holdout"], "qa-quality-holdout-1")
        self.assertEqual(hashlib.sha256(released()).hexdigest(), qa_quality_measure.RELEASED_1_SHA256)
        self.assertEqual(set(self.cases), set(MEASURED_0_2))
        self.assertEqual(sum(1 for case in self.cases.values() if case["fault"]), 8)

    def test_gold_facts_are_what_the_synthetic_sources_say(self):
        for key, facts in self.body["gold"].items():
            for fact, present in facts:
                with self.subTest(key=key, fact=fact):
                    self.assertEqual(fact in self.body["sources"][key]["text"], present)

    def test_each_case_is_flagged_as_measured(self):
        version = research_quality.RUBRIC_VERSION
        self.assertIn(version, MEASURED_BY_VERSION, f"{version} is not measured on released set 1 yet")
        result = qa_quality_measure.measure(self.cases, self.body["sources"])
        self.assertEqual(result["refused_by_reading"], [], "the reading layer must accept every case")
        self.assertEqual({name: row["flags"] for name, row in result["flags"].items()}, MEASURED_BY_VERSION[version])

    def test_each_version_gives_the_counts_and_flags_recorded_before_the_release(self):
        faulty = {name for name, case in self.cases.items() if case["fault"]}
        for version, measured in MEASURED_BY_VERSION.items():
            with self.subTest(version):
                at_fault = sorted(name for name in faulty
                                  if any(where == self.cases[name]["fault"] for _, where in measured[name]))
                clean_flagged = sorted(name for name in set(self.cases) - faulty if measured[name])
                self.assertEqual((clean_flagged, at_fault, sorted(faulty - set(at_fault))),
                                 COUNTS_BY_VERSION[version])
                rows = {name: {"refused": None, "flags": flags} for name, flags in measured.items()}
                recorded = qa_quality_measure.RELEASED_1_BASELINE[version]
                self.assertEqual(hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest(),
                                 recorded["flags_sha256"])
                self.assertEqual((len(clean_flagged), len(at_fault), len(faulty) - len(at_fault)),
                                 (recorded["correct_with_any_flag"], recorded["faulty_flagged_at_fault"],
                                  recorded["faulty_without_flag_at_fault"]))


if __name__ == "__main__":
    unittest.main()
