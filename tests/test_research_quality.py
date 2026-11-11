"""The research-quality rubric (research-quality-0.3) against SYNTHETIC regression cases with explicit expected
findings (tests/quality_cases.py). Each reply is first read by the existing research contract (research_reading.
classify), the "before": it accepts every planted mistake, because every quote is in the source. The rubric, the
"after", must produce exactly each case's expected findings: no flag on the clean replies, the named flag on each
planted mistake, and none on the two recorded known misses, which remain for human review. Fake replies only; no model
is called and nothing is written.
"""
import json
import unittest

from second_order import research_analysis as ra, research_quality, research_reading

from quality_cases import CASES, HEADLINE, SOURCE, UNRESOLVED


def response(submission: dict) -> bytes:
    """A SYNTHETIC reply in the Messages API shape, calling the research tool once."""
    return json.dumps({"id": "msg_synthetic_quality", "type": "message", "role": "assistant", "model": ra.MODEL,
                       "content": [{"type": "tool_use", "id": "toolu_synthetic_quality", "name": ra.TOOL_NAME,
                                    "input": submission}],
                       "stop_reason": "tool_use", "stop_sequence": None,
                       "usage": {"input_tokens": 1000, "output_tokens": 500}}).encode("utf-8")


def read(source: str, submission: dict) -> dict:
    return research_reading.classify(response(submission), ra.MODEL, source)


class Rubric(unittest.TestCase):
    def test_the_contract_accepts_every_case_and_the_rubric_finds_exactly_what_each_plants(self):
        for name, (headline, source, submission, expected, kind) in CASES.items():
            with self.subTest(name):
                structural = read(source, submission)
                self.assertIn(structural["outcome"], ("analysis", "no additional finding"), structural["problem"])
                found = research_quality.assess(headline, source, structural["analysis"])
                self.assertEqual({(row["check"], row["where"]) for row in found["findings"]}, expected,
                                 json.dumps(found["findings"], indent=1))
                self.assertEqual(found["rejected"], [])
                self.assertTrue(all(row["level"] == "flagged" for row in found["findings"]))

    def test_before_and_after_on_these_cases(self):
        """The counts the report states, pinned: the contract accepted all planted mistakes; the rubric flagged every
        planted mistake at its own location (a flag elsewhere in the reply is not counted as finding it), nothing
        elsewhere in those replies, nothing on the clean replies, and nothing on the two known misses."""
        accepted = at_fault = elsewhere = false_flags = misses = 0
        kinds = {"clean": 0, "planted": 0, "known_miss": 0}
        for headline, source, submission, expected, kind in CASES.values():
            kinds[kind] += 1
            structural = read(source, submission)
            accepted += structural["outcome"] in ("analysis", "no additional finding") and kind != "clean"
            findings = research_quality.assess(headline, source, structural["analysis"])["findings"]
            faults = {where for _, where in expected}
            at_fault += kind == "planted" and any(row["where"] in faults for row in findings)
            elsewhere += sum(row["where"] not in faults for row in findings) if kind == "planted" else 0
            false_flags += kind == "clean" and bool(findings)
            misses += kind == "known_miss" and not findings
        self.assertEqual(kinds, {"clean": 12, "planted": 25, "known_miss": 2})
        self.assertEqual((accepted, at_fault, elsewhere, false_flags, misses), (27, 25, 0, 0, 2))

    def test_a_reply_the_contract_rejects_never_reaches_the_rubric(self):
        structural = read(SOURCE, UNRESOLVED)
        self.assertEqual(structural["outcome"], "refused")
        self.assertIn("not found", structural["problem"])
        self.assertIsNone(structural["analysis"])
        self.assertEqual(research_quality.assess(HEADLINE, SOURCE, None)["findings"], [])

    def test_every_finding_names_its_rule_and_human_review_is_always_listed(self):
        headline, source, submission, _, _ = CASES["a cause the quotes do not hold"]
        found = research_quality.assess(headline, source, read(source, submission)["analysis"])
        (finding,) = found["findings"]
        self.assertEqual(finding["rule"], research_quality.CHECKS["beyond_quotes"])
        self.assertIn("because", finding["detail"])
        self.assertEqual(len(found["human_review"]), 4)
        self.assertEqual(found["rubric_version"], research_quality.RUBRIC_VERSION)
        self.assertNotIn("%", json.dumps({key: value for key, value in found.items() if key != "checks"}))

    def test_a_users_recorded_result_is_assessed_as_served_and_left_unchanged(self):
        """Through the real user flow with SYNTHETIC accounts and the fake provider: the rubric reads the Analysis
        payload; the payload, its result and result_sha256 are byte-identical afterwards, and nothing is written."""
        import tempfile
        from pathlib import Path
        from account_fakes import USER_WRITE, World, every_file, source_form
        with tempfile.TemporaryDirectory() as folder:
            world = World(Path(folder))
            world.standard_terms()
            client = world.client("reader-a")
            source_id = client.post("/api/user/sources", headers=USER_WRITE, json=source_form()).json()["source"]["source_id"]
            analysis_id = client.post("/api/user/analyses", headers=USER_WRITE,
                                      json={"source_id": source_id, "effort": "high"}).json()["analysis"]["analysis_id"]
            self.assertIsNone(research_quality.for_user_analysis(client.get(f"/api/user/analyses/{analysis_id}").json()
                                                                 ["analysis"]))
            quote = client.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={}).json()["quote"]
            client.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE,
                        json={"quote_id": quote["quote_id"], "effort": "high", "credits": quote["credits"],
                              "approve": True})
            served = client.get(f"/api/user/analyses/{analysis_id}").content
            before = every_file(Path(folder))
            found = research_quality.for_user_analysis(json.loads(served)["analysis"])
            self.assertEqual(found["rubric_version"], research_quality.RUBRIC_VERSION)
            self.assertEqual(found["findings"], [])  # The fake reply quotes and restates nothing it lacks.
            self.assertEqual((client.get(f"/api/user/analyses/{analysis_id}").content, every_file(Path(folder))),
                             (served, before))

    def test_the_version_is_0_3(self):
        self.assertEqual(research_quality.RUBRIC_VERSION, "research-quality-0.3")

    def test_words_match_on_five_letters_or_the_whole_of_a_shorter_word(self):
        self.assertTrue(research_quality._meets("rate", {"rates"}))
        self.assertTrue(research_quality._meets("rates", {"rate"}))
        self.assertTrue(research_quality._meets("ease", {"eased"}))
        self.assertTrue(research_quality._meets("raised", {"raise"}))
        self.assertFalse(research_quality._meets("data", {"date"}))
        self.assertFalse(research_quality._meets("fed", {"federal"}))
        self.assertFalse(research_quality._meets("change", {"unchanged"}))

    def test_dates_are_periods_and_figures_carry_their_change_or_level_role(self):
        self.assertEqual(research_quality._periods("On October 2, 2026, in May 2026 and the first quarter."),
                         ["2026", "first quarter", "may", "october 2"])
        figures = research_quality._figures("Stocks rose by 2.3 million on October 2, 2026, to 412.6 million; "
                                            "they fell 1.1 percent and were 7 percent, as statement 2 says.")
        self.assertEqual([(value, role) for _, value, role in figures],
                         [("2.3", "change"), ("412.6", "level"), ("1.1", "change"), ("7", None)])

    def test_a_negation_is_read_as_applying_to_the_next_word_that_is_not_an_auxiliary(self):
        self.assertEqual(research_quality._negated("It did not ease; no reason was given; it hasn't yet risen."),
                         ["ease", "reason", "risen"])
        self.assertEqual(research_quality._negated("Output rose."), [])

    def test_sentences_directions_and_speakers_are_read_as_written(self):
        text = "Output rose 1.2 percent. Jobs were unchanged at 48,200.\n\nThe U.S. office said so"
        self.assertEqual([text[start:end].strip() for start, end in research_quality._sentences(text)],
                         ["Output rose 1.2 percent.", "Jobs were unchanged at 48,200.", "The U.S.", "office said so"])
        self.assertEqual(research_quality._directions("Output did not increase and prices fell; jobs unchanged."),
                         {("up", True), ("down", False), ("flat", False)})
        self.assertEqual(research_quality._directions("Output didn't rise."), {("up", True)})
        self.assertEqual(research_quality._speaker("The central bank reported that output rose."), ["central", "bank"])
        self.assertEqual(research_quality._speaker("Output rose, the statistics office said."), ["statistics", "office"])
        self.assertEqual(research_quality._speaker("According to the Synthetic Board, output rose."),
                         ["synthetic", "board"])
        self.assertEqual(research_quality._speaker("Output rose 1.2 percent."), [])

    def test_figures_match_without_thousands_separators_and_fractions_stay_whole(self):
        numbers = research_quality._numbers("The range is 3-3/4 to 4 percent; 1,250 jobs; 2.1 percentage points.")
        self.assertEqual(numbers, [("3-3/4", None), ("4", "percent"), ("1250", None), ("2.1", "percentage point")])


if __name__ == "__main__":
    unittest.main()
