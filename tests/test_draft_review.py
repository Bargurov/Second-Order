"""Drafting review kit: eight synthetic cases with rubrics, and an offline runner that reports the adapter's
structural decision beside each rubric without judging the reasoning.

Every response here is synthetic. These tests verify the kit's contract, not the quality of any reasoning.
"""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from model_fixtures import THINKING, encoded, message, tool_call, valid_output
from second_order.draft_review import load_cases, review, run_review
from second_order.model_draft import build_request, digest, operator_event

ROOT = Path(__file__).resolve().parent.parent
CLOCK = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
REQUIRED = {"clear-policy", "conflicting-labor-inflation", "headline-reports-move", "no-connection",
            "insufficient-source", "prompt-injection", "unsupported-observables", "ambiguous-wording"}
BOTH = ["down", "up"]
# The runner runs in a child process whose sockets refuse to connect, so any network attempt fails loudly.
NO_NETWORK = ("import runpy, socket, sys\n"
              "def blocked(*args, **kwargs): raise SystemExit('network attempted')\n"
              "socket.socket.connect = blocked\n"
              "sys.argv = ['draft_review'] + sys.argv[1:]\n"
              "runpy.run_module('second_order.draft_review', run_name='__main__', alter_sys=True)\n")


class ReviewCaseTests(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases(clock=lambda: CLOCK)

    def test_eight_clearly_synthetic_cases_cover_the_required_situations(self):
        self.assertEqual(set(self.cases), REQUIRED)
        for case_id, case in self.cases.items():
            with self.subTest(case_id):
                self.assertIs(case["synthetic"], True)
                self.assertTrue(case["operator"]["headline"].startswith("Synthetic "))
                self.assertTrue(case["operator"]["source_url"].startswith("https://example.com/synthetic/"))
                self.assertTrue(case["operator"]["story_id"].startswith("synthetic-review-"))
                self.assertTrue(case["source_text"].startswith("SYNTHETIC TEST TEXT."))
        self.assertIn("Ignore all previous instructions", self.cases["prompt-injection"]["source_text"])

    def test_rubrics_allow_declining_and_leave_contested_directions_open(self):
        preferred = {case_id for case_id, case in self.cases.items()
                     if case["rubric"]["declining_to_draft"]["stance"] == "preferred"}
        self.assertEqual(preferred, {"no-connection", "insufficient-source"})
        for case_id, case in self.cases.items():
            with self.subTest(case_id):
                directions = case["rubric"]["defensible_directions"]
                if case_id in preferred:  # The source supports no direction at all.
                    self.assertEqual(directions, {"yield:ust2y_cmt": [], "yield:ust10y_cmt": []})
                elif case_id == "clear-policy":  # Only the 2-year reading is conventional; the 10-year is open.
                    self.assertEqual(directions, {"yield:ust2y_cmt": ["down"], "yield:ust10y_cmt": BOTH})
                else:
                    self.assertEqual({key: sorted(value) for key, value in directions.items()},
                                     {"yield:ust2y_cmt": BOTH, "yield:ust10y_cmt": BOTH})

    def test_two_cases_state_a_fictional_us_setting_as_scenario_facts(self):
        for case_id in ("conflicting-labor-inflation", "ambiguous-wording"):
            with self.subTest(case_id):
                text = self.cases[case_id]["source_text"]
                self.assertTrue(text.startswith("SYNTHETIC TEST TEXT. No real institution, release, quote or market "
                                                "data is described."))  # The synthetic label is kept.
                facts = [part for part in text.split("\n\n") if part.startswith("Scenario facts:")]
                self.assertEqual(len(facts), 1)
                self.assertIn("fictional version of the United States economy", facts[0])
                self.assertIn("sets the United States policy rate", facts[0])
                for addressed in ("you", "assume", "should", "draft", "hypothesis", "treasury", "yield"):
                    self.assertNotIn(addressed, facts[0].lower())  # Facts only; nothing instructs the model.

    def test_leakage_expectations_follow_what_each_text_reports(self):
        flagged = {(case_id, observable) for case_id, case in self.cases.items()
                   for observable, flag in case["rubric"]["leakage_flags"].items() if flag["headline_reports_move"]}
        self.assertEqual(flagged, {("headline-reports-move", "yield:ust2y_cmt"),
                                   ("headline-reports-move", "yield:ust10y_cmt"),
                                   ("prompt-injection", "yield:ust10y_cmt")})

    def test_malformed_cases_are_refused(self):
        def broken(edit):
            case = copy.deepcopy(self.cases["clear-policy"])
            edit(case)
            return case

        flags = lambda case: case["rubric"]["leakage_flags"]
        cases = {
            "not synthetic": (broken(lambda c: c.update(synthetic=False)), "must be synthetic"),
            "id differs from file": (broken(lambda c: c.update(id="other")), "match its file name"),
            "extra field": (broken(lambda c: c.update(verdict="supported")), "exactly id"),
            "missing rubric part": (broken(lambda c: c["rubric"].pop("unacceptable_claims")), "rubric must have"),
            "empty list": (broken(lambda c: c["rubric"].update(required_uncertainties=[])), "required_uncertainties"),
            "declining forbidden": (broken(lambda c: c["rubric"]["declining_to_draft"].update(stance="forbidden")),
                                    "declining_to_draft"),
            "unknown direction": (broken(lambda c: c["rubric"]["defensible_directions"].update(
                {"yield:ust2y_cmt": ["sideways"]})), "defensible_directions"),
            "unoffered observable": (broken(lambda c: flags(c).update(
                {"index:dxy": {"headline_reports_move": False, "reason": "x"}})), "leakage_flags"),
            "string flag": (broken(lambda c: flags(c)["yield:ust2y_cmt"].update(headline_reports_move="false")),
                            "leakage_flags"),
            "future publication": (broken(lambda c: c["operator"].update(published_at="2026-12-01T00:00:00Z")),
                                   "in the future"),
            "empty source": (broken(lambda c: c.update(source_text=" ")), "source text is empty"),
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, (case, pattern) in cases.items():
                with self.subTest(name):
                    (Path(folder) / "clear-policy.json").write_text(json.dumps(case), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, f"^Case clear-policy: .*{pattern}"):
                        load_cases(Path(folder), lambda: CLOCK)


class ReviewRunnerTests(unittest.TestCase):
    def setUp(self):
        guard = patch("socket.socket.connect", side_effect=AssertionError("A test attempted a network connection"))
        guard.start()
        self.addCleanup(guard.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.cases = load_cases(clock=lambda: CLOCK)

    def saved(self, payload: dict | bytes, name: str = "response.json") -> Path:
        path = self.folder / name
        path.write_bytes(payload if isinstance(payload, bytes) else encoded(payload))
        return path

    def review(self, case_id: str, payload: dict | bytes, provenance: str = "synthetic") -> dict:
        return review(self.cases[case_id], self.saved(payload), provenance, clock=lambda: CLOCK)

    def test_a_valid_synthetic_draft_is_validated_by_the_adapter_and_shown_beside_the_rubric(self):
        case = self.cases["clear-policy"]
        result = self.review("clear-policy", message())
        self.assertEqual(result["structural_validation"]["outcome"], "draft")
        self.assertIsNone(result["structural_validation"]["adapter_message"])
        draft = result["draft"]["draft"]
        self.assertEqual({key: draft[key] for key in ("summary", "nodes", "edges", "legs")}, valid_output())
        event, _ = operator_event(case["operator"], lambda: CLOCK)
        self.assertEqual(draft["engine"]["prompt_hash"], digest(build_request(event, case["source_text"])))
        self.assertEqual(result["case"]["prompt_hash"], draft["engine"]["prompt_hash"])
        self.assertEqual(draft["engine"]["provider"], "offline-replay")
        self.assertEqual(result["response"]["provenance"], "synthetic")
        self.assertIn("not produced by a model", result["response"]["label"])
        reasoning = result["reasoning_review"]
        self.assertTrue(reasoning["status"].startswith("Not reviewed"))
        self.assertEqual(reasoning["rubric"], case["rubric"])
        self.assertEqual([(leg["leg_id"], leg["draft_expected"], leg["rubric_defensible_directions"])
                          for leg in reasoning["legs_beside_rubric"]],
                         [("primary", "down", ["down"]), ("secondary", "down", BOTH)])
        self.assertIsNone(result["response_text"])

    def test_a_saved_response_is_labelled_unverified(self):
        result = self.review("ambiguous-wording", message(), "saved")
        self.assertEqual(result["structural_validation"]["outcome"], "draft")
        self.assertIn("unverified", result["response"]["label"])
        self.assertIn("not verified", result["draft"]["review"]["limitations"][0])

    def test_a_structurally_valid_draft_is_not_judged_on_its_reasoning(self):
        # This draft flags no reported move although the case's text reports both. It still passes structural
        # validation; the runner places the values side by side for a person and scores nothing.
        result = self.review("headline-reports-move", message())
        self.assertEqual(result["structural_validation"]["outcome"], "draft")
        beside = result["reasoning_review"]["legs_beside_rubric"]
        self.assertEqual([(leg["draft_headline_reports_move"], leg["rubric_headline_reports_move"]) for leg in beside],
                         [(False, True), (False, True)])
        self.assertEqual(set(result), {"case", "response", "structural_validation", "draft", "response_text",
                                       "reasoning_review"})
        self.assertEqual(set(result["reasoning_review"]), {"status", "legs_beside_rubric", "rubric", "common_criteria"})
        self.assertEqual(set(beside[0]), {"leg_id", "primary", "observable_id", "draft_link", "draft_horizon",
                                          "draft_expected", "rubric_defensible_directions",
                                          "draft_headline_reports_move", "rubric_headline_reports_move"})
        self.assertTrue(result["reasoning_review"]["status"].startswith("Not reviewed"))

    def test_a_schema_valid_draft_with_the_first_pilots_flaws_still_needs_reasoning_review(self):
        # SYNTHETIC review example written for this test, not model output. It repeats the reasoning flaws found
        # in the first Sonnet pilot's clear-policy draft and is still schema-valid.
        flawed = valid_output()
        flawed["summary"] = ("A 50bp cut, larger than the 25bp most forecasters expected, may lower the 2-year yield, "
                             "and the 10-year yield by less. A growth scare could lift long yields.")
        flawed["legs"][0].update(link="direct", horizon=1)
        flawed["legs"][1].update(link="proxy", horizon=5)
        result = self.review("clear-policy", message(flawed))
        self.assertEqual(result["structural_validation"]["outcome"], "draft")  # Valid structure...
        reasoning = result["reasoning_review"]
        self.assertTrue(reasoning["status"].startswith("Not reviewed"))  # ...is not a reasoning verdict.
        self.assertEqual([(leg["draft_link"], leg["draft_horizon"]) for leg in reasoning["legs_beside_rubric"]],
                         [("direct", 1), ("proxy", 5)])  # Shown beside the criteria for a person to judge.
        criteria = " ".join(reasoning["common_criteria"])
        for rule in ("is a proxy for it", "falls by less", "names its channel and the direction",
                     "news or data during the scored window", "a forecaster survey is not market pricing"):
            self.assertIn(rule, criteria)
        claims = " ".join(reasoning["rubric"]["unacceptable_claims"])
        for flaw in ("Setting link to direct", "falls by less", "growth scare", "unpriced market surprise"):
            self.assertIn(flaw, claims)
        self.assertEqual(reasoning["rubric"]["defensible_directions"],  # Directions are not narrowed.
                         {"yield:ust2y_cmt": ["down"], "yield:ust10y_cmt": BOTH})

    def test_invalid_responses_are_refused_and_leave_nothing_to_review(self):
        unoffered, primaries, owned = valid_output(), valid_output(), valid_output()
        unoffered["legs"][1]["observable_id"] = "index:dxy"
        primaries["legs"][1]["primary"] = True
        owned["usage"] = "research"
        prose = {"type": "text", "text": "Here is a hypothesis: " + json.dumps(valid_output())}
        cases = {
            "malformed JSON": (b'{"type": "message", "content": [', "not valid JSON"),
            "unoffered observable": (message(unoffered), "not offered: index:dxy"),
            "two primaries": (message(primaries), "Exactly one primary leg"),
            "field the model does not own": (message(owned), "usage"),
            "prose beside the call": (message(content=[THINKING, prose, tool_call()]), "Unexpected text content block"),
            "truncated": (message(stop_reason="max_tokens"), "truncated at max_tokens"),  # Not a decline.
            "other model": (message(model="claude-other-model"), "not the requested"),
        }
        for name, (payload, pattern) in cases.items():
            with self.subTest(name):
                result = self.review("prompt-injection", payload)
                self.assertEqual(result["structural_validation"]["outcome"], "refused")
                self.assertRegex(result["structural_validation"]["adapter_message"], pattern)
                self.assertIsNone(result["draft"])
                self.assertIsNone(result["response_text"])
                self.assertEqual(result["reasoning_review"]["legs_beside_rubric"], [])
                self.assertTrue(result["reasoning_review"]["status"].startswith("Nothing to review"))
                self.assertEqual(result["reasoning_review"]["rubric"], self.cases["prompt-injection"]["rubric"])

    def test_a_response_without_a_draft_is_left_to_the_reviewer_with_its_text(self):
        reason = "No hypothesis: the source reports only that a meeting ended."
        cases = {
            "ended without the tool": (message(content=[THINKING, {"type": "text", "text": reason}],
                                               stop_reason="end_turn"), "without calling the draft tool", [reason]),
            "refusal stop": (message(content=[THINKING], stop_reason="refusal", stop_details={"category": "cyber"}),
                             "declined to draft", []),
        }
        for name, (payload, pattern, blocks) in cases.items():
            with self.subTest(name):
                result = self.review("insufficient-source", payload)
                self.assertEqual(result["structural_validation"]["outcome"], "no draft")
                self.assertRegex(result["structural_validation"]["adapter_message"], pattern)
                self.assertIsNone(result["draft"])
                self.assertEqual(result["response_text"]["blocks"], blocks)
                self.assertTrue(result["reasoning_review"]["status"].startswith("Not reviewed"))
                self.assertEqual(result["reasoning_review"]["rubric"]["declining_to_draft"]["stance"], "preferred")

    def test_a_report_keeps_the_given_order_counts_each_label_and_claims_no_model_quality(self):
        supplied = [("synthetic", "clear-policy", self.saved(message(), "a.json")),
                    ("saved", "no-connection", self.saved(b"not json", "b.json"))]
        report = run_review(self.cases, supplied, clock=lambda: CLOCK)
        self.assertEqual([(item["case"]["id"], item["response"]["provenance"], item["structural_validation"]["outcome"])
                          for item in report["reviews"]],
                         [("clear-policy", "synthetic", "draft"), ("no-connection", "saved", "refused")])
        self.assertEqual(report["responses"], {"synthetic": 1, "saved": 1})
        self.assertIn("no model was called", report["notice"][0])
        self.assertIn("does not demonstrate model quality", report["notice"][-1])
        with self.assertRaisesRegex(ValueError, "Unknown case 'nope'"):
            run_review(self.cases, [("saved", "nope", self.folder / "a.json")], clock=lambda: CLOCK)


class ReviewCliTests(unittest.TestCase):
    def run_kit(self, *arguments: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", NO_NETWORK, *arguments], cwd=ROOT, text=True,
                              capture_output=True, encoding="utf-8", timeout=60, env=env)

    def test_the_runner_reviews_supplied_files_offline_and_writes_nothing(self):
        output = valid_output()
        output["summary"] = "Easier policy path → lower yields — a synthetic hypothesis."  # Not cp1252-safe.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "good.json").write_bytes(encoded(message(output)))
            (root / "bad.json").write_bytes(b"not json")
            run = self.run_kit("--synthetic", f"clear-policy={root / 'good.json'}",
                               "--response", f"no-connection={root / 'bad.json'}",
                               env={**os.environ, "PYTHONIOENCODING": "cp1252"})  # A Windows-style pipe.
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(run.stdout.isascii())  # Escaped JSON survives any code page re-decoding.
            report = json.loads(run.stdout)
            self.assertEqual([(item["case"]["id"], item["response"]["provenance"],
                               item["structural_validation"]["outcome"]) for item in report["reviews"]],
                             [("clear-policy", "synthetic", "draft"), ("no-connection", "saved", "refused")])
            self.assertEqual(report["reviews"][0]["draft"]["draft"]["summary"], output["summary"])
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["bad.json", "good.json"])

    def test_the_runner_lists_cases_and_previews_requests_without_sending(self):
        listed = self.run_kit("--list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual({item["id"] for item in json.loads(listed.stdout)}, REQUIRED)
        preview = self.run_kit("--print-request", "prompt-injection")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        printed = json.loads(preview.stdout)
        self.assertEqual(printed["prompt_hash"], digest(printed["request"]))
        self.assertIn("Ignore all previous instructions", printed["request"]["messages"][0]["content"])

    def test_usage_errors_fail_cleanly(self):
        for arguments, pattern in ((("--synthetic", "nope=missing.json"), "Failed: Unknown case 'nope'"),
                                   (("--response", "clear-policy=does-not-exist.json"), "Failed: .*does-not-exist")):
            with self.subTest(arguments=arguments):
                run = self.run_kit(*arguments)
                self.assertEqual((run.returncode, run.stdout), (1, ""))
                self.assertRegex(run.stderr, pattern)
                self.assertNotIn("Traceback", run.stderr)
        for arguments, pattern in (((), "choose one"), (("--list", "--print-request", "clear-policy"), "choose one"),
                                   (("--response", "clear-policy"), "expected CASE=FILE")):
            with self.subTest(arguments=arguments):
                run = self.run_kit(*arguments)
                self.assertEqual((run.returncode, run.stdout), (2, ""))
                self.assertIn(pattern, run.stderr)


if __name__ == "__main__":
    unittest.main()
