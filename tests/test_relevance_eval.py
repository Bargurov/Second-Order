"""The relevance evaluation sets (content/news-relevance) and their measurement (relevance-eval-0.1): a dev set and a
public, fictional sample set (not a holdout) with provisional labels, a packet without labels, both kinds of error
counted, and the earlier keyword rule measured on the same cases. A private holdout, when its file is present, has its
own checks apart from this file. Nothing here calls a model."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from news_desk_fakes import synthetic_annotation
from second_order import relevance_eval as ev
from second_order.news_registry import PUBLISHERS

NEEDED = {"relevant", "irrelevant", "ambiguous", "similar_vocabulary", "no_financial_terms", "consumer_company"}


def perfect(found: dict) -> dict:
    """Annotations agreeing with every label, each quoting its case's headline."""
    rows = []
    for case in found["cases"]:
        report = case["reports"][0]
        quote = " ".join(report["title"].split()[:3])
        rows.append({"case_id": case["case_id"],
                     "annotation": synthetic_annotation(report["id"], quote, case["label"]["verdict"])})
    return {"set": found["set"], "set_sha256": found["set_sha256"], "annotations": rows}


class SetsTest(unittest.TestCase):
    def test_dev_and_sample_are_separate_varied_and_provisional(self):
        dev, sample = ev.load("dev"), ev.load("sample")
        self.assertFalse({case["case_id"] for case in dev["cases"]} & {case["case_id"] for case in sample["cases"]})
        titles = lambda found: {case["reports"][0]["title"] for case in found["cases"]}  # noqa: E731
        self.assertFalse(titles(dev) & titles(sample))
        pairs = lambda found: {case["pair"] for case in found["cases"] if case["pair"]}  # noqa: E731
        self.assertFalse(pairs(dev) & pairs(sample))  # A pair is never split between the two sets.
        for found in (dev, sample):
            categories = {category for case in found["cases"] for category in case["categories"]}
            self.assertLessEqual(NEEDED, categories, found["set"])
            self.assertEqual(found["cases"] and {case["label"]["status"] for case in found["cases"]}, {"provisional"})
            verdicts = {case["label"]["verdict"] for case in found["cases"]}
            self.assertLessEqual({"relevant", "outside_scope", "insufficient_information"}, verdicts)
            for case in found["cases"]:
                for report in case["reports"]:
                    self.assertTrue(report["synthetic"] or PUBLISHERS[report["source"]].material == "permitted")
                    if report["synthetic"]:
                        self.assertTrue(report["publisher"].startswith("SYNTHETIC"))

    def test_the_packet_carries_the_material_and_rules_but_never_the_labels(self):
        found = ev.load("sample")
        text = json.dumps(ev.packet(found))
        self.assertNotIn("provisional", text)
        self.assertNotIn('"label"', text)
        self.assertNotIn("Claude Code (Claude Opus 5.5), the set's author", text)
        self.assertIn("untrusted text", text)

    def test_the_sample_is_fictional_and_says_it_is_not_a_holdout(self):
        sample = ev.load("sample")
        self.assertEqual(len(sample["cases"]), 24)
        self.assertEqual([case["case_id"] for case in sample["cases"]], [f"sample-s{n:02d}" for n in range(1, 25)])
        self.assertIn("not a held-out set", sample["purpose"])
        for case in sample["cases"]:
            self.assertTrue(case["synthetic"])
            for report in case["reports"]:
                self.assertTrue(report["synthetic"] and report["source"] is None)
                self.assertTrue(report["link"].startswith("https://example.org/"))

    def test_the_holdout_is_private_and_refused_when_it_is_not_there(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict("os.environ"):
            os.environ.pop(ev.HOLDOUT_ENV, None)
            with self.assertRaises(ev.EvalRefused) as raised:
                ev.load("holdout", Path(folder))
            self.assertIn(ev.HOLDOUT_ENV, str(raised.exception))
            os.environ[ev.HOLDOUT_ENV] = str(Path(folder) / "missing.json")
            with self.assertRaises(ev.EvalRefused):
                ev.load("holdout", Path(folder))
            # A file named by the variable is read as the holdout, whatever its place.
            named = Path(folder) / "mine.json"
            sample = json.loads((ev.EVAL_DIR / "sample.json").read_bytes().decode("utf-8"))
            named.write_text(json.dumps({**sample, "set": "holdout"}), encoding="utf-8")
            os.environ[ev.HOLDOUT_ENV] = str(named)
            self.assertEqual(len(ev.load("holdout", Path(folder))["cases"]), 24)
        self.assertEqual(tuple(ev.SETS), ("dev", "sample"))


class MeasureTest(unittest.TestCase):
    def test_agreeing_annotations_count_no_error_and_the_keyword_rule_is_measured_too(self):
        found = ev.load("dev")
        result = ev.measure(found, perfect(found), {"tool": "SYNTHETIC", "model": None})
        self.assertEqual((result["decision"]["irrelevant_admitted"], result["decision"]["excluded"],
                          result["decision"]["held"]), (0, 0, 0))
        self.assertEqual(result["disagreements"], [])
        rows = {row["case_id"]: row for row in result["rows"]}
        self.assertEqual(rows["dev-s01"]["keyword"], "relevant")  # The app roundup, admitted by its publisher's topic.
        self.assertEqual(rows["dev-s07"]["keyword"], "outside_scope")  # A port strike, named by no keyword.
        self.assertGreater(result["keyword_rule"]["irrelevant_admitted"], 0)
        self.assertGreater(result["keyword_rule"]["excluded"], 0)
        self.assertIn("provisional", result["statement"])

    def test_both_kinds_of_error_are_counted_and_listed(self):
        found = ev.load("dev")
        reply = perfect(found)
        flipped = {"dev-s01": "relevant", "dev-s07": "outside_scope"}
        for row in reply["annotations"]:
            if row["case_id"] in flipped:
                case = next(case for case in found["cases"] if case["case_id"] == row["case_id"])
                row["annotation"] = synthetic_annotation(case["reports"][0]["id"],
                                                         " ".join(case["reports"][0]["title"].split()[:3]),
                                                         flipped[row["case_id"]])
        reply["annotations"] = [row for row in reply["annotations"] if row["case_id"] != "dev-s09"]
        result = ev.measure(found, reply, {"tool": "SYNTHETIC", "model": None})
        self.assertEqual((result["decision"]["irrelevant_admitted"], result["decision"]["excluded"],
                          result["decision"]["held"]), (1, 1, 1))
        self.assertEqual({row["case_id"] for row in result["disagreements"]}, {"dev-s01", "dev-s07", "dev-s09"})
        with self.assertRaises(ev.EvalRefused):  # Annotations of another version of the set are refused.
            ev.measure(found, {**reply, "set_sha256": "0" * 64}, {"tool": "SYNTHETIC", "model": None})

    def test_a_measurement_is_kept_write_once(self):
        found = ev.load("dev")
        result = ev.measure(found, perfect(found), {"tool": "SYNTHETIC", "model": None})
        with tempfile.TemporaryDirectory() as folder:
            path = ev.record_run(Path(folder), result, datetime(2026, 10, 25, tzinfo=timezone.utc))
            self.assertTrue(path.name.startswith("reval-"))
            with self.assertRaises(FileExistsError):
                ev.record_run(Path(folder), result, datetime(2026, 10, 25, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
