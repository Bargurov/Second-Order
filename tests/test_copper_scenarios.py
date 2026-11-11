"""Write-once copper scenario records (copper_scenarios) on SYNTHETIC sources: ids bound to content, exclusive
creation, verification on read, and the states a changed, missing or tampered input gives."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import copper_fakes
import thesis_fakes
from second_order import bis_snapshot, copper_inputs, copper_scenarios as cs
from second_order.thesis_rules import ThesisRefused

SET_A = {"ev": {"source": "scenario", "scenario": "cps"},
         "networks": {"source": "technology_case", "scenario": "steps"},
         "mine": {"source": "total", "kt": "-294.8350405", "reference": "ptfi-sales-change"}}
FIXED = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


class Records(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = copper_fakes.write_sources(self.base / "sources")
        self.inputs = copper_fakes.write_catalog(self.base / "inputs", copper_fakes.catalog(self.root, "coverage"))
        self.folder = self.base / "scenarios"
        self.load()

    def load(self):
        self.catalog, self.catalog_sha = copper_inputs.load_catalog(self.inputs)
        self.sources, self.states = copper_inputs.check_items(self.catalog, self.root)
        self.values = copper_inputs.verified_values(self.catalog, self.states)

    def build(self, assumptions=SET_A, label="STEPS 2035 with set A"):
        return cs.build(self.catalog, self.catalog_sha, self.values, "steps", "2035", assumptions, label)

    def read(self):
        return cs.read_all(self.folder, self.catalog, self.catalog_sha, self.values, self.states, self.sources)


class WriteOnce(Records):
    def test_a_record_is_bound_to_its_content(self):
        record = self.build()
        self.assertEqual(set(record), cs.RECORD_FIELDS)
        self.assertEqual(cs.record_id(record), cs.record_id(self.build()))
        self.assertEqual(record["result"]["residual"]["value"], "12622.8350405")
        used = {figure["id"] for figure in record["figures"]}
        self.assertIn("fcx-ptfi-sales-guidance-2025", used)
        self.assertIn("iea-demand-total-steps-2035", used)
        self.assertNotEqual(cs.record_id(record), cs.record_id(self.build(label="Another label")))
        self.assertNotEqual(cs.record_id(record), cs.record_id(self.build({"ev": None})))

    def test_save_once_then_unchanged(self):
        record = self.build()
        status, envelope = cs.save(self.folder, record, lambda: FIXED)
        self.assertEqual(status, 201)
        path = self.folder / f"{envelope['id']}.json"
        written = path.read_bytes()
        self.assertEqual(envelope["created_at"], "2026-11-05T12:00:00+00:00")
        status, again = cs.save(self.folder, self.build(), lambda: datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(status, 200)
        self.assertEqual(again["created_at"], envelope["created_at"])
        self.assertEqual(path.read_bytes(), written)
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    def test_a_tampered_file_is_never_overwritten(self):
        record = self.build()
        _, envelope = cs.save(self.folder, record, lambda: FIXED)
        path = self.folder / f"{envelope['id']}.json"
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["record"]["label"] = "edited"
        path.write_text(json.dumps(changed), encoding="utf-8")
        tampered = path.read_bytes()
        with self.assertRaises(ThesisRefused) as raised:
            cs.save(self.folder, record, lambda: FIXED)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(path.read_bytes(), tampered)
        listed = self.read()["records"]
        self.assertEqual([item["state"] for item in listed], ["invalid"])
        self.assertIsNone(listed[0]["result"])

    def test_a_withheld_output_is_not_saved(self):
        values = {key: value for key, value in self.values.items() if key != "iea-demand-total-steps-2035"}
        record = cs.build(self.catalog, self.catalog_sha, values, "steps", "2035", SET_A, "withheld")
        self.assertFalse(cs.complete(record))
        with self.assertRaises(ThesisRefused) as raised:
            cs.save(self.folder, record, lambda: FIXED)
        self.assertEqual(raised.exception.status, 409)
        self.assertFalse(self.folder.exists())

    def test_labels(self):
        for label, fragment in (("", "1 to 80"), (" padded", "1 to 80"), ("x" * 81, "1 to 80"),
                                ("line\nbreak", "1 to 80"), ("This proves a shortage", "claim word"),
                                ("Copper price rises", "price's direction")):
            with self.assertRaises(ThesisRefused) as raised:
                self.build(label=label)
            self.assertEqual(raised.exception.status, 422)
            self.assertIn(fragment, str(raised.exception))
        self.assertEqual(self.build(label="CPS EV copper in STEPS 2035")["label"], "CPS EV copper in STEPS 2035")

    def test_an_invalid_request_is_refused_before_anything(self):
        with self.assertRaises(ThesisRefused):
            cs.build(self.catalog, self.catalog_sha, self.values, "steps", "2035", {"recycling": {"kt": "1"}}, "x")


class OnRead(Records):
    def saved(self):
        _, envelope = cs.save(self.folder, self.build(), lambda: FIXED)
        return envelope

    def test_verified_on_read(self):
        envelope = self.saved()
        listed = self.read()
        self.assertEqual(listed["other_versions"], 0)
        [item] = listed["records"]
        self.assertEqual((item["id"], item["state"], item["problems"]), (envelope["id"], "verified", []))
        self.assertEqual(item["result"]["residual"]["value"], "12622.8350405")
        self.assertTrue(item["catalog_current"])

    def test_a_changed_source_needs_revalidation(self):
        self.saved()
        sheets = copper_fakes.iea_sheets()
        sheets[copper_fakes.S1]["K17"] = "33600"
        copper_fakes.retain(self.root, "iea-synthetic", thesis_fakes.workbook(sheets))
        self.load()  # The committed catalogue still states 33522: the cell is not found, so it is not verified.
        [item] = self.read()["records"]
        self.assertEqual(item["state"], "needs_revalidation")
        self.assertIn("iea-demand-total-steps-2035 is not verified today", item["problems"])
        self.assertIsNone(item["result"])

    def test_a_revised_catalogue_value_needs_revalidation(self):
        self.saved()
        sheets = copper_fakes.iea_sheets()
        sheets[copper_fakes.S1]["K17"] = "33600"
        copper_fakes.retain(self.root, "iea-synthetic", thesis_fakes.workbook(sheets))
        catalog = copper_fakes.catalog(self.root, "coverage")
        for figure in catalog["figures"]:
            if figure["id"] == "iea-demand-total-steps-2035":
                figure["value"], figure["as_shown"] = "33600", "33,600"
        copper_fakes.write_catalog(self.inputs, catalog)
        self.load()
        [item] = self.read()["records"]
        self.assertEqual(item["state"], "needs_revalidation")
        self.assertTrue(any("differs from the value or source" in problem for problem in item["problems"]))
        self.assertFalse(item["catalog_current"])

    def test_a_missing_source_is_unavailable(self):
        self.saved()
        shutil.rmtree(self.root / "fcx-synthetic-2024")
        self.load()
        [item] = self.read()["records"]
        self.assertEqual(item["state"], "unavailable")
        self.assertIsNone(item["result"])

    def test_an_engine_that_no_longer_reproduces_it(self):
        envelope = self.saved()
        path = self.folder / f"{envelope['id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))["record"]
        record["result"]["residual"]["value"] = "12622.835"  # A result the engine does not compute, under a new id.
        identity = cs.record_id(record)
        (self.folder / f"{identity}.json").write_text(json.dumps({"id": identity, "created_at": "2026-11-05T13:00:00"
                                                                  "+00:00", "record": record}), encoding="utf-8")
        states = {item["id"]: item for item in self.read()["records"]}
        self.assertEqual(states[identity]["state"], "needs_revalidation")
        self.assertIn("The engine does not reproduce its result from today's verified figures",
                      states[identity]["problems"])
        self.assertEqual(states[envelope["id"]]["state"], "verified")

    def test_other_versions_are_counted_not_shown(self):
        record = {**self.build(), "record_version": "copper-scenario-0.0"}
        identity = cs.record_id(record)
        self.folder.mkdir(parents=True)
        (self.folder / f"{identity}.json").write_text(json.dumps({"id": identity, "created_at": "2026-11-01T00:00:00"
                                                                  "+00:00", "record": record}), encoding="utf-8")
        listed = self.read()
        self.assertEqual((listed["records"], listed["other_versions"]), ([], 1))

    def test_reading_writes_nothing(self):
        self.saved()
        before = {path: path.read_bytes() for path in self.base.rglob("*") if path.is_file()}
        self.read()
        self.assertEqual(before, {path: path.read_bytes() for path in self.base.rglob("*") if path.is_file()})

    def test_the_file_is_canonical_and_id_named(self):
        envelope = self.saved()
        path = self.folder / f"{envelope['id']}.json"
        loaded = bis_snapshot._strict_json(path.read_bytes().decode("utf-8"), "record")
        self.assertEqual(set(loaded), cs.ENVELOPE_FIELDS)
        self.assertEqual(cs.record_id(loaded["record"]), path.stem)


if __name__ == "__main__":
    unittest.main()
