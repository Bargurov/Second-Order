"""The copper tools' inputs catalogue (copper_inputs): its strict schema, and every figure and passage verified against
SYNTHETIC retained sources (copper_fakes) on read, with tampered, re-recorded and missing files refused item by item."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import copper_fakes
import thesis_fakes
from second_order import copper_inputs, copper_tools_view
from second_order.thesis_rules import ThesisRefused

COMMITTED = Path(__file__).resolve().parent.parent / "content" / "tools" / "copper-coverage"


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = copper_fakes.write_sources(Path(self.temp.name) / "sources")
        self.catalog = copper_inputs.check_catalog(copper_fakes.catalog(self.root))

    def states(self, catalog=None):
        return copper_inputs.check_items(catalog or self.catalog, self.root)

    def retain_sheets(self, change):
        sheets = copper_fakes.iea_sheets()
        change(sheets)
        copper_fakes.retain(self.root, "iea-synthetic", thesis_fakes.workbook(sheets))
        catalog = copper_fakes.catalog(self.root)  # Re-bound to the re-recorded file, so the source verifies.
        return copper_inputs.check_catalog(catalog)


class VerifiesSynthetic(Synthetic):
    def test_every_item_verifies(self):
        sources, states = self.states()
        self.assertEqual({state["state"] for state in sources.values()}, {"verified"})
        self.assertEqual(len(states), len(self.catalog["figures"]) + len(self.catalog["passages"]))
        self.assertEqual({state["state"] for state in states.values()}, {"verified"})
        values = copper_inputs.verified_values(self.catalog, states)
        self.assertEqual(str(values["iea-demand-total-steps-2035"]), "33522")
        self.assertEqual(str(values["iea-demand-hydrogen-2025"]), "0.00585")
        self.assertEqual(str(values["fcx-id-unit-net-2025"]), "-0.55")  # "(0.55)": negative, as accounts print it.

    def test_coverage_part_verifies(self):
        catalog = copper_inputs.check_catalog(copper_fakes.catalog(self.root, "coverage"))
        _, states = self.states(catalog)
        self.assertEqual({state["state"] for state in states.values()}, {"verified"})
        self.assertEqual(len(catalog["passages"]), 2)

    def test_reads_change_nothing(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.states()
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})


class TamperedWorkbook(Synthetic):
    def test_a_changed_cell_is_not_found_and_has_no_value(self):
        catalog = self.retain_sheets(lambda sheets: sheets[copper_fakes.S1].update(K17="33523"))
        _, states = self.states(catalog)
        self.assertEqual(states["iea-demand-total-steps-2035"]["state"], "not_found")
        problem = states["iea-demand-total-steps-2035"]["problem"]
        self.assertIn("cell K17", problem)
        self.assertNotIn("33522", problem)  # A problem names the place, never the value looked for.
        self.assertNotIn("iea-demand-total-steps-2035", copper_inputs.verified_values(catalog, states))
        self.assertEqual(states["iea-demand-total-cps-2035"]["state"], "verified")

    def test_a_changed_column_header_refuses_the_column(self):
        catalog = self.retain_sheets(lambda sheets: sheets[copper_fakes.S1].update(K5="2036"))
        _, states = self.states(catalog)
        column = [item["id"] for item in catalog["figures"] if item["locator"].get("sheet") == copper_fakes.S1
                  and item["locator"]["cell"].startswith("K")]
        self.assertEqual(len(column), 10)
        self.assertEqual({states[figure]["state"] for figure in column}, {"not_found"})
        self.assertEqual(states["iea-demand-total-steps-2030"]["state"], "verified")

    def test_the_header_checks_are_what_refuse_it(self):
        """Mutation: without the further-cell checks, the same moved column header would pass."""
        catalog = self.retain_sheets(lambda sheets: sheets[copper_fakes.S1].update(K5="2036"))
        unchecked = copy.deepcopy(catalog)
        for item in unchecked["figures"]:
            item["checks"] = []
        _, states = self.states(unchecked)
        self.assertEqual(states["iea-demand-total-steps-2035"]["state"], "verified")

    def test_a_changed_block_or_scenario_label_refuses(self):
        catalog = self.retain_sheets(lambda sheets: sheets[copper_fakes.S1].update(J4="Synthetic other scenario"))
        _, states = self.states(catalog)
        self.assertEqual(states["iea-demand-ev-steps-2035"]["state"], "not_found")
        self.assertEqual(states["iea-demand-ev-hd-2035"]["state"], "verified")
        catalog = self.retain_sheets(lambda sheets: sheets[copper_fakes.S2].update(G6="Copper - Synthetic"))
        _, states = self.states(catalog)
        self.assertEqual(states["iea-refining-total-2035"]["state"], "not_found")
        self.assertEqual(states["iea-mine-total-2035"]["state"], "verified")

    def test_a_changed_note_is_not_found(self):
        catalog = self.retain_sheets(lambda sheets: sheets[copper_fakes.S2].update(A72="Synthetic: reworded."))
        _, states = self.states(catalog)
        self.assertEqual(states["iea-supply-note-pipeline"]["state"], "not_found")
        self.assertEqual(states["iea-supply-note-base-case"]["state"], "verified")

    def test_a_file_changed_without_its_record_is_refused_whole(self):
        path = self.root / "iea-synthetic" / "dataset.xlsx"
        path.write_bytes(path.read_bytes() + b"x")
        sources, states = self.states()
        self.assertEqual(sources["iea-synthetic"]["state"], "changed")
        iea = [item["id"] for item in [*self.catalog["figures"], *self.catalog["passages"]]
               if item["source"] == "iea-synthetic"]
        self.assertEqual({states[item]["state"] for item in iea}, {"source_changed"})
        self.assertEqual(states["fcx-us-unit-net-2025"]["state"], "verified")

    def test_a_missing_folder_is_missing(self):
        for path in sorted((self.root / "scco-synthetic-2024").iterdir()):
            path.unlink()
        (self.root / "scco-synthetic-2024").rmdir()
        sources, states = self.states()
        self.assertEqual(sources["scco-synthetic-2024"]["state"], "missing")
        self.assertEqual(states["scco-tia-maria-budget-2024"]["state"], "source_missing")
        self.assertEqual(states["scco-tia-maria-budget-2025"]["state"], "verified")


class TableCells(Synthetic):
    def page(self, change):
        page, figures, passages = copper_fakes.fcx_2025()
        raw = page.html().decode("utf-8")
        copper_fakes.retain(self.root, "fcx-synthetic-2025", change(raw).encode("utf-8"))
        return copper_inputs.check_catalog(copper_fakes.catalog(self.root))

    def test_a_changed_cell_label_or_header_is_not_found(self):
        catalog = self.page(lambda raw: raw.replace("<td>3.05</td>", "<td>3.06</td>", 1))
        _, states = self.states(catalog)
        self.assertEqual(states["fcx-us-unit-net-2025"]["state"], "not_found")
        self.assertIn("a table cell", states["fcx-us-unit-net-2025"]["problem"])
        catalog = self.page(lambda raw: raw.replace("<td>Treatment charges</td>", "<td>Synthetic charges</td>", 1))
        _, states = self.states(catalog)
        self.assertEqual(states["fcx-us-treatment-2025"]["state"], "not_found")
        catalog = self.page(lambda raw: raw.replace("<td>2025</td>", "<td>2026</td>", 1))
        _, states = self.states(catalog)
        self.assertEqual(states["fcx-us-revenue-2025"]["state"], "not_found")
        self.assertEqual(states["fcx-sa-revenue-2025"]["state"], "verified")

    def test_a_shifted_column_is_not_found(self):
        """An extra number cell before the figure moves it to the next column: the n-th number cell is no longer it."""
        catalog = self.page(lambda raw: raw.replace("<td>Unit net cash costs, co-product</td><td>3.05</td>",
                                                    "<td>Unit net cash costs, co-product</td><td>9.99</td><td>3.05</td>",
                                                    1))
        _, states = self.states(catalog)
        self.assertEqual(states["fcx-us-co-product-2025"]["state"], "not_found")

    def test_the_column_count_is_what_refuses_it(self):
        """Mutation: with the column count ignored, an inserted cell would go unnoticed."""
        catalog = self.page(lambda raw: raw.replace("<td>Unit net cash costs, co-product</td><td>3.05</td>",
                                                    "<td>Unit net cash costs, co-product</td><td>3.22</td><td>3.05</td>",
                                                    1))
        for item in catalog["figures"]:
            if item["id"] == "fcx-us-co-product-2025":
                item["locator"]["paragraph"] -= 1  # The inserted cell now reads as the figure, in column 1.
        _, states = self.states(catalog)
        self.assertEqual(states["fcx-us-co-product-2025"]["state"], "not_found")
        with mock.patch.object(copper_inputs, "_is_cell_figure", lambda text: False):
            original = copper_inputs._in_cell

            def without_count(item, paragraphs):
                locator = item["locator"]
                text = paragraphs[locator["paragraph"] - 1]
                return " ".join(text.split()) == item["as_shown"]
            with mock.patch.object(copper_inputs, "_in_cell", without_count):
                _, states = self.states(catalog)
            self.assertEqual(states["fcx-us-co-product-2025"]["state"], "verified")
            self.assertIsNotNone(original)

    def test_cell_values(self):
        self.assertEqual(str(copper_inputs.cell_value("(0.59)")), "-0.59")
        self.assertEqual(str(copper_inputs.cell_value("1,301")), "1301")
        self.assertEqual(str(copper_inputs.cell_value("2,035.6")), "2035.6")
        for text in ("$", "a", "—", "(", "(0.5", "0.59)", "-(0.59)"):
            with self.assertRaises(ValueError):
                copper_inputs.cell_value(text)


class Schema(Synthetic):
    def refused(self, change, fragment):
        broken = copy.deepcopy(copper_fakes.catalog(self.root))
        change(broken)
        with self.assertRaises(ThesisRefused) as raised:
            copper_inputs.check_catalog(broken)
        self.assertEqual(raised.exception.status, 500)
        self.assertIn(fragment, str(raised.exception))

    def figure(self, catalog, figure_id):
        return next(item for item in catalog["figures"] if item["id"] == figure_id)

    def test_refusals(self):
        self.refused(lambda c: c.update(catalog_version="copper-inputs-0.2"), "catalog_version")
        self.refused(lambda c: c.update(extra=1), "expected exactly the fields")
        self.refused(lambda c: self.figure(c, "iea-demand-ev-2025").update(unit="kg"), "unit")
        self.refused(lambda c: self.figure(c, "iea-demand-ev-2025").update(as_shown="795"), "does not print")
        self.refused(lambda c: self.figure(c, "iea-demand-ev-2025").update(measure="This confirms demand"),
                     "confirms")
        self.refused(lambda c: self.figure(c, "iea-demand-ev-2025").update(measure="Copper price rises"),
                     "price's direction")
        self.refused(lambda c: self.figure(c, "fcx-mud-rush-2025").update(checks=[{"cell": "A1", "text": "x"}]),
                     "only a workbook figure")
        self.refused(lambda c: self.figure(c, "iea-demand-ev-2025")["checks"].append({"cell": "B11", "text": "794"}),
                     "own cell")
        self.refused(lambda c: self.figure(c, "fcx-us-revenue-2025")["locator"].update(paragraph=10_000),
                     "at most 40 paragraphs")
        self.refused(lambda c: self.figure(c, "fcx-us-revenue-2025").update(as_shown="(4.91)"), "does not print")
        self.refused(lambda c: c["figures"].append(copy.deepcopy(c["figures"][0])), "distinct")
        self.refused(lambda c: c.update(figures=[f for f in c["figures"] if f["source"] != "scco-synthetic-2024"]),
                     "every listed source is cited")

    def test_committed_catalog_loads(self):
        catalog, digest = copper_inputs.load_catalog(COMMITTED)
        self.assertEqual(catalog["catalog_version"], copper_inputs.CATALOG_VERSION)
        self.assertRegex(digest, "^[0-9a-f]{64}$")
        raw = json.loads((COMMITTED / "inputs.json").read_text(encoding="utf-8"))
        self.assertEqual(raw, catalog)

    def test_committed_catalog_against_no_sources_is_missing(self):
        catalog, _ = copper_inputs.load_catalog(COMMITTED)
        with tempfile.TemporaryDirectory() as empty:
            sources, states = copper_inputs.check_items(catalog, Path(empty))
        self.assertEqual({state["state"] for state in sources.values()}, {"missing"})
        self.assertEqual({state["state"] for state in states.values()}, {"source_missing"})
        self.assertEqual(copper_inputs.verified_values(catalog, states), {})

    def test_a_missing_or_invalid_catalogue(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(ThesisRefused) as raised:
                copper_inputs.load_catalog(Path(empty))
            self.assertEqual(raised.exception.status, 503)
            (Path(empty) / "inputs.json").write_text('{"catalog_version": 1, "catalog_version": 2}', encoding="utf-8")
            with self.assertRaises(ThesisRefused) as raised:
                copper_inputs.load_catalog(Path(empty))
            self.assertIn("copper inputs catalogue is invalid", str(raised.exception))


class CommittedUnchanged(unittest.TestCase):
    """The Bagdad refresh reads its new figures from the FCX research and never changes the catalogue, so every saved
    scenario record keeps its catalogue digest."""

    def test_the_catalogue_is_byte_identical_to_87425ba(self):
        raw = (copper_inputs.INPUTS_DIR / copper_inputs.INPUTS_FILE).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "0b44a3cd1db346fe7b294704dbbce218e4a15b42e63b9f57bcd9d0a79f25ff21")
        catalog, digest = copper_inputs.load_catalog(copper_inputs.INPUTS_DIR)
        self.assertEqual(digest, "d4501e7fc54b34bfb708fd27ff582bf9a461b21e3e4dc4ee6aee300dfff1dabd")
        self.assertEqual((len(catalog["figures"]), len(catalog["passages"])), (199, 24))
        copper_tools_view.required(catalog)  # Raises if the tools read anything else.


if __name__ == "__main__":
    unittest.main()
