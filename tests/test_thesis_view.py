"""The served thesis (thesis_view): sources verified on this machine, each element's state, what is withheld, the
computed numbers and the counts.

Runs on the SYNTHETIC sources and versions 1 and 2 (tests/thesis_fakes.py), written into a fresh temporary folder for
every test, so a test may remove, change or re-record a retained file. Every view here is built from those synthetic
folders only. One test, test_reading_writes_nothing, also reads the bytes of every file under the committed
content/theses (thesis_schema.THESES_DIR) and under the real retained-sources folder (thesis_sources.SOURCES_DIR,
data/sector-sources/copper, when it is on the machine: tens of MB, the 10-Ks included), hashing each before and after
the reads, because those are the view's default folders and a read must write nothing there either; it never verifies,
parses or serves those files.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import thesis_fakes
from second_order import (policy_research, thesis_arithmetic, thesis_rules, thesis_schema, thesis_sections,
                          thesis_sources, thesis_view)
from second_order.thesis_rules import ThesisRefused

ROOT = Path(__file__).resolve().parent.parent
ID = thesis_fakes.THESIS_ID
PUBLISHED = ["2026-11-02", "2026-11-16"]
SENSITIVITY_QUOTE = thesis_fakes.SENSITIVITY_QUOTE

# What a withheld element still shows: its frame. Everything else is null, a condition's threshold included (M4).
FRAME = {"id", "title", "plain", "gap", "company", "moves", "side", "series", "items", "sources", "state", "problems",
         "not_found"}
CHECK = {"items", "sources", "state", "problems", "not_found"}
ITEM = {"id", "source"}
FIGURE = {"id", "value", "as_shown", "unit", "year", "period", "basis", "scenario", "source", "where", "measure",
          "quote"}
PASSAGE = {"id", "source", "quote", "where"}
STATEMENT = {"status", "text", "cites", "figures", "passages"}
SHAPES = {
    "view": {"id", "statement"},
    "table": {"id", "title", "gap", "why_not", "rows"},
    "differs": {"id", "about", "others", "differs"},
    "reason": {"id", "title", "plain", "statement", "measure", "status", "change_pct", "moved_by"},
    "condition": {"id", "comparator", "text", "figure", "threshold", "threshold_value", "status"},
    "mover": {"id", "company", "moves", "through", "cites", "figures", "passages"},
    "moved": {"id", "company", "side", "how", "amount", "usd_per_unit", "share_pct"},
    "price_record": {"id", "series", "opening", "latest"},
}
TOP = {"view_version", "thesis_version", "id", "version", "versions", "draft", "title", "topic", "opened_on",
       "prepared_on", "published_on", "confidence", "provider_called", "labels", "sources", "view", "balance",
       "differs", "reasons", "risks", "conditions", "exposure", "price_record", "log", "plain", "not_claimed",
       "provenance", "counts"}
SOURCE = {"id", "publisher", "title", "edition", "edition_date", "url", "kind", "origin", "terms", "transcription",
          "retrieved_at", "sha256", "state", "detail"}
# Author text in an element, and the values its digits must come from (the figures-held-to-sources rule).
TEXTS = {"text", "title", "why_not", "through", "label", "measure"}
ALLOWED = {"as_shown", "value", "year", "period", "quote", "gap", "weeks", "change_pct", "threshold", "usd_per_unit",
           "share_pct"}
IEA_2026 = {"view", "balance-steps", "balance-side-by-side", "differs-earlier-edition", "clean-tech-demand",
            "recycling-limited", "total-demand-rising", "primary-supply-projections", "supply-above"}
AVAILABLE_LABEL = ("Checked: every figure and passage it cites was found where cited in retained sources that match "
                   "their acquisition records; a figure or passage transcribed from a PDF is bound to the PDF by its "
                   "SHA-256 only.")
CONDITION_LABELS = {
    "happened": "Happened: the figure it names is past the threshold in the stated direction (a figure equal to the "
                "threshold is not past it)",
    "not_happened": "Not happened: the figure it names is not past the threshold in the stated direction (a figure "
                    "equal to the threshold is not past it)"}


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


def rewritten(raw: bytes, change) -> bytes:
    """A workbook's archive written again entry by entry, each entry's bytes passed through ``change(name, data)``;
    each entry keeps its time, so the same change makes the same bytes on every platform and every run."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(buffer, "w") as target:
        for info in source.infolist():
            target.writestr(thesis_fakes.zip_entry(info.filename, info.date_time),
                            change(info.filename, source.read(info)), compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def elements(reply: dict) -> list[dict]:
    """Every element of a reply, in the reply's order."""
    return [reply["view"], *reply["balance"]["tables"], *reply["differs"], *reply["reasons"], *reply["risks"],
            *reply["conditions"], *reply["exposure"]["movers"], *reply["exposure"]["moved"], reply["price_record"]]


def find(items: list, item_id: str) -> dict:
    return next(item for item in items if item["id"] == item_id)


def derived(reply: dict, element: dict) -> str:
    """The state an element's sources and not_found give: missing, then changed or not found, then available."""
    states = {source["id"]: source["state"] for source in reply["sources"]}
    found = {states[name] for name in element["sources"]}
    if "missing" in found:
        return "unavailable"
    return "needs_revalidation" if "changed" in found or element["not_found"] else "available"


def strings(value, keys: set[str] | None, found: list[str], key: str | None = None) -> list[str]:
    """Every string in ``value`` held under one of ``keys`` (None: every string)."""
    if isinstance(value, dict):
        for name, item in value.items():
            strings(item, keys, found, name)
    elif isinstance(value, list):
        for item in value:
            strings(item, keys, found, key)
    elif isinstance(value, str) and (keys is None or key in keys):
        found.append(value)
    return found


def file_elements(thesis: dict) -> dict:
    """Each element of a version file, by the id its reply element carries."""
    found = {"view": thesis["view"], "price-record": thesis["price_record"]}
    for section in (thesis["balance"]["tables"], thesis["differs"], thesis["reasons"], thesis["risks"],
                    thesis["conditions"]):
        found.update({item["id"]: item for item in section})
    found.update({f"mover-{n}": item for n, item in enumerate(thesis["exposure"]["movers"], start=1)})
    found.update({f"moved-{n}": item for n, item in enumerate(thesis["exposure"]["moved"], start=1)})
    return found


def named(value, ids: set[str], found: list[str]) -> list[str]:
    """The figure and passage ids that a version file's element names, in file order, each once."""
    if isinstance(value, dict):
        for item in value.values():
            named(item, ids, found)
    elif isinstance(value, list):
        for item in value:
            named(item, ids, found)
    elif isinstance(value, str) and value in ids and value not in found:
        found.append(value)
    return found


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="second-order-thesis-view-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sources = self.tmp / "sources"
        self.content = self.tmp / "content"
        self.fresh()

    def fresh(self) -> None:
        """Every synthetic source retained as recorded, and versions 1 and 2 bound to them."""
        shutil.rmtree(self.sources, ignore_errors=True)
        thesis_fakes.write_sources(self.sources)
        self.write()

    def write(self, published: list | None = None, change=None) -> None:
        v1 = thesis_fakes.thesis_v1(self.sources)
        if change is not None:
            v1 = thesis_fakes.changed(v1, change)
        shutil.rmtree(self.content / ID, ignore_errors=True)
        thesis_fakes.write_theses(self.content, [v1, thesis_fakes.thesis_v2(v1, self.sources)],
                                  PUBLISHED if published is None else published)

    def rerecord(self, folder: str, data: bytes) -> None:
        """Retain new bytes with a matching record, and bind the versions to them, as an author re-binding would."""
        thesis_fakes.retain(self.sources, folder, data)
        self.write()

    def view(self, version=None) -> dict:
        return thesis_view.view(ID, version, self.content, self.sources)

    def withheld(self, element: dict) -> None:
        self.assertNotEqual(element["state"], "available", element["id"])
        self.assertTrue(element["problems"], element["id"])
        for key, value in element.items():
            if key not in FRAME:
                self.assertIsNone(value, f"{element['id']}.{key} is shown")

    def states(self, reply: dict) -> dict:
        return {element["id"]: element["state"] for element in elements(reply)}

    def reconciled(self, reply: dict) -> None:
        """Every element's items, sources, not_found, state and problems agree with each other and with the version
        file it was served from."""
        thesis = thesis_schema.load_version(ID, reply["version"], self.content)
        ids, files = {item["id"] for item in thesis["figures"] + thesis["passages"]}, file_elements(thesis)
        for element in elements(reply):
            listed = [item["id"] for item in element["items"]]
            self.assertEqual(listed, named(files[element["id"]], ids, []), element["id"])  # File order, each once.
            for item in element["items"]:
                self.assertEqual(set(item), ITEM)
            self.assertTrue(set(element["not_found"]) <= set(listed), element["id"])
            self.assertEqual(element["sources"], sorted({item["source"] for item in element["items"]}), element["id"])
            self.assertEqual(element["state"], derived(reply, element), element["id"])
            self.assertEqual(element["state"] == "available", not element["problems"], element["id"])

    # ------------------------------------------------------------ everything found

    def test_every_element_is_available_and_its_numbers_are_computed(self):
        v = self.view()
        self.assertEqual(v["counts"]["elements"], {"available": 18, "needs_revalidation": 0, "unavailable": 0})
        row = v["balance"]["tables"][0]["rows"][0]
        self.assertEqual((row["gap"], row["label"], row["weeks"]), ("-500", "deficit", "1.0"))
        ev = v["exposure"]["moved"][2]
        self.assertEqual((ev["usd_per_unit"], ev["share_pct"]), ("505", "1.1"))
        self.assertEqual([r["status"] for r in v["reasons"]],
                         ["strengthening", "unchanged", "weakening", "strengthening"])

        self.assertEqual(v["counts"]["sources"], {"verified": 9, "changed": 0, "missing": 0})
        self.assertEqual([(row["year"], row["gap"], row["label"], row["weeks"]) for row in v["balance"]["tables"][0]["rows"]],
                         [("2025", "-500", "deficit", "1.0"), ("2030", "-800", "deficit", "1.4"),
                          ("2035", "-1,600", "deficit", "2.6")])
        self.assertEqual({(row["gap"], row["label"], row["weeks"]) for row in v["balance"]["tables"][1]["rows"]},
                         {(None, None, None)})  # Not computed: two publications on different bases.
        self.assertEqual([r["change_pct"] for r in v["reasons"]], ["7.4", "0.9", "11.6", "7.8"])
        self.assertEqual([(r["status"], r["change_pct"]) for r in v["risks"]],
                         [("materialising", "2.6"), ("receding", "-2.0"), ("not_tracked", None)])
        condition = v["conditions"][0]
        self.assertEqual((condition["comparator"], condition["threshold"], condition["threshold_value"],
                          condition["status"]), ("above", "29,500", "29500", "not_happened"))
        self.assertEqual(condition["items"], [{"id": "iea26-supply-2030", "source": "iea-2026"}])
        self.reconciled(v)
        self.assertEqual(condition["figure"]["as_shown"], "28,700")
        self.assertEqual(v["reasons"][0]["moved_by"], {"source": "iea-2026", "publisher": "Synthetic IEA",
                                                       "edition": "2026", "edition_date": "2026-07-15"})
        self.assertEqual(v["reasons"][1]["moved_by"]["source"], "usgs-2026")
        measure = v["reasons"][0]["measure"]
        self.assertEqual((measure["latest"]["value"], measure["previous"]["value"], measure["compare"],
                          measure["supports_when"], measure["material_change_pct"]),
                         ("10100", "9400", "revision", "higher", "5"))
        self.assertEqual(v["risks"][0]["measure"]["grows_when"], "higher")
        self.assertEqual([(m["usd_per_unit"], m["share_pct"]) for m in v["exposure"]["moved"]],
                         [(None, None), (None, None), ("505", "1.1")])
        self.assertEqual([m["amount"]["kind"] for m in v["exposure"]["moved"]], ["stated", "stated", "computed"])
        self.assertEqual([m["id"] for m in v["exposure"]["movers"] + v["exposure"]["moved"]],
                         ["mover-1", "mover-2", "moved-1", "moved-2", "moved-3"])
        self.assertEqual((v["price_record"]["opening"]["as_shown"], v["price_record"]["latest"]["as_shown"]),
                         ("9,180.25", "9,500"))
        self.assertIs(v["differs"][0]["differs"], True)
        for element in elements(v):
            self.assertEqual((element["state"], element["problems"], element["not_found"]), ("available", [], []),
                             element["id"])
        self.assertEqual(v["view"]["sources"], ["iea-2026"])
        self.assertEqual(v["exposure"]["moved"][2]["sources"], ["iea-2021", "sec-maker-2025", "worldbank"])

    def test_the_reply_has_the_documented_shape(self):
        for scenario in ("found", "missing"):
            with self.subTest(scenario=scenario):
                if scenario == "missing":
                    shutil.rmtree(self.sources)
                v = self.view()
                self.assertEqual(json.loads(json.dumps(v)), v)  # Plain JSON: numbers travel as strings.
                self.assertEqual(set(v), TOP)
                self.assertEqual((v["view_version"], v["thesis_version"], v["id"], v["provider_called"]),
                                 ("thesis-view-0.1", "thesis-0.1", ID, False))
                self.assertEqual(thesis_view.VIEW_VERSION, "thesis-view-0.1")
                self.assertEqual(set(v["balance"]), {"tables"})
                self.assertEqual(set(v["exposure"]), {"movers", "moved"})
                self.assertEqual(set(v["counts"]), {"sources", "elements"})
                for source in v["sources"]:
                    self.assertEqual(set(source), SOURCE)
                sections = [("view", [v["view"]]), ("table", v["balance"]["tables"]), ("differs", v["differs"]),
                            ("reason", v["reasons"] + v["risks"]), ("condition", v["conditions"]),
                            ("mover", v["exposure"]["movers"]), ("moved", v["exposure"]["moved"]),
                            ("price_record", [v["price_record"]])]
                for name, items in sections:
                    for element in items:
                        self.assertEqual(set(element), SHAPES[name] | CHECK, element["id"])
        self.fresh()
        v = self.view()
        figures = strings(elements(v), {"figure", "demand_total", "supply_total", "latest", "previous", "opening",
                                        "per_unit", "price", "unit_price"}, [])
        self.assertEqual(figures, [])  # Figures are objects, never bare ids.
        for statement in [v["view"]["statement"], v["differs"][0]["about"], *(r["statement"] for r in v["reasons"]),
                          *(r["statement"] for r in v["risks"]), *(m["how"] for m in v["exposure"]["moved"])]:
            self.assertEqual(set(statement), STATEMENT)
            shown = [item["id"] for item in statement["figures"]], [item["id"] for item in statement["passages"]]
            self.assertEqual(shown, ([cite for cite in statement["cites"] if cite in shown[0]],
                                     [cite for cite in statement["cites"] if cite in shown[1]]))
            self.assertEqual(sorted(shown[0] + shown[1]), sorted(statement["cites"]))
            for item in statement["figures"]:
                self.assertEqual(set(item), FIGURE)
            for item in statement["passages"]:
                self.assertEqual(set(item), PASSAGE)
        row = v["balance"]["tables"][0]["rows"][0]
        self.assertEqual(set(row), {"year", "kind", "demand_total", "supply_total", "lines", "gap", "label", "weeks"})
        self.assertEqual(set(row["lines"][0]), {"label", "figure"})
        self.assertEqual(set(v["differs"][0]["others"][0]), {"cite", "label", "figure", "passage"})
        self.assertEqual(set(v["reasons"][0]["measure"]),
                         {"latest", "previous", "compare", "supports_when", "material_change_pct"})
        self.assertEqual(set(v["risks"][0]["measure"]),
                         {"latest", "previous", "compare", "grows_when", "material_change_pct"})
        self.assertEqual(set(v["reasons"][0]["moved_by"]), {"source", "publisher", "edition", "edition_date"})
        self.assertEqual(set(v["exposure"]["moved"][0]["amount"]), {"kind", "figure"})
        self.assertEqual(set(v["exposure"]["moved"][2]["amount"]), {"kind", "per_unit", "price", "unit_price"})

    def test_each_figure_and_passage_says_where_it_is_found(self):
        v = self.view()
        self.assertEqual(v["reasons"][0]["measure"]["latest"]["where"], "sheet Copper, cell E3")
        latest = v["reasons"][1]["measure"]["latest"]
        self.assertEqual((latest["where"], latest["as_shown"], latest["quote"], latest["basis"]),
                         ("row 5, column World mine production (kt)", "22,900", None, "Synthetic mine output"))
        stated = v["exposure"]["moved"][0]["amount"]["figure"]
        self.assertEqual((stated["where"], stated["quote"], stated["source"]),
                         ("paragraph 4", SENSITIVITY_QUOTE, "sec-producer-2025"))
        per_unit = v["exposure"]["moved"][2]["amount"]["per_unit"]
        self.assertEqual((per_unit["where"], per_unit["value"], per_unit["unit"]),
                         ("page 1 (transcribed from the PDF)", "53.2", "kg_per_unit"))
        passage = v["risks"][2]["statement"]["passages"][0]
        self.assertEqual((passage["id"], passage["where"], passage["source"]),
                         ("iea21-construction", "page 2 (transcribed from the PDF)", "iea-2021"))
        self.assertEqual(v["price_record"]["latest"]["where"], "sheet Monthly Prices, cell B8")
        self.assertEqual(v["price_record"]["latest"]["period"], "2026M10")
        pdf = find(v["sources"], "iea-2021")
        self.assertEqual((pdf["state"], pdf["transcription"]),
                         ("verified", {"pages": [1, 2], "method": "transcribed from the page image"}))
        self.assertIsNone(find(v["sources"], "iea-2026")["transcription"])
        entry = thesis_fakes.source_entries(self.sources)[0]
        self.assertEqual({key: v["sources"][0][key] for key in SOURCE - {"state", "detail"}},
                         {key: entry[key] for key in SOURCE - {"state", "detail"}})
        self.assertEqual([source["id"] for source in v["sources"]], list(thesis_fakes.SOURCES))

    def test_numbers_in_the_text_agree_with_the_numbers_in_the_reply(self):
        v = self.view()
        moved = v["exposure"]["moved"][2]
        self.assertIn(f"about {moved['usd_per_unit']} USD", moved["how"]["text"])
        self.assertIn(v["conditions"][0]["threshold"], v["conditions"][0]["text"])
        for element in elements(v):
            texts, allowed = strings(element, TEXTS, []), strings(element, ALLOWED, [])
            extra = policy_research._figures(" ".join(texts)) - policy_research._figures(" ".join(allowed))
            self.assertEqual(extra, set(), element["id"])
            self.assertTrue(texts, element["id"])

    def test_the_labels_name_every_state_and_make_no_claim(self):
        labels = self.view()["labels"]
        self.assertEqual({name: set(values) for name, values in labels.items()}, {
            "statuses": set(thesis_rules.STATEMENT_STATUSES), "source_states": set(thesis_rules.SOURCE_STATES),
            "element_states": set(thesis_rules.ELEMENT_STATES), "reason_states": set(thesis_rules.REASON_STATES),
            "risk_states": set(thesis_rules.RISK_STATES), "condition_states": set(thesis_rules.CONDITION_STATES),
            "sides": set(thesis_sections.SIDES), "units": set(thesis_schema.UNITS)})
        for name, values in labels.items():
            for key, text in values.items():
                self.assertIsNone(thesis_rules.BANNED.search(text), f"{name}.{key}")
                self.assertIsNone(thesis_rules.PRICE_DIRECTION.search(text), f"{name}.{key}")
        self.assertIn("less than", labels["reason_states"]["unchanged"])
        # A PDF item is bound by the PDF's SHA-256 only (locate reads nothing in a PDF), and a condition tests the one
        # figure it names, not a "latest" one.
        self.assertEqual(labels["element_states"]["available"], AVAILABLE_LABEL)
        self.assertEqual(labels["condition_states"], CONDITION_LABELS)
        # A measure compares two editions or two years of one edition (ruling R12): the labels name the latest and
        # previous figures, never editions, so they hold for both kinds.
        for name in ("reason_states", "risk_states"):
            for key, text in labels[name].items():
                self.assertNotIn("edition", text, f"{name}.{key}")
        self.assertIn("the latest figure differs from the previous one", labels["reason_states"]["strengthening"])

    # ------------------------------------------------------------ sources missing or changed

    def test_a_missing_previous_edition_makes_its_reason_unavailable_not_unchanged(self):
        shutil.rmtree(self.sources / "usgs-2025")
        reason = next(r for r in self.view()["reasons"] if "usgs-2025" in r["sources"])
        self.assertEqual((reason["state"], reason["status"], reason["statement"]), ("unavailable", None, None))

        v = self.view()
        self.assertEqual((reason["id"], reason["sources"]), ("mine-supply-slow", ["usgs-2025", "usgs-2026"]))
        self.withheld(reason)
        self.assertEqual((reason["title"], reason["plain"]), ("Synthetic mine supply responds slowly",
                                                              "Synthetic: if mines add output slowly, supply stays "
                                                              "behind demand for longer."))
        self.assertTrue(any(problem.startswith("usgs-2025: ") and "not on this machine" in problem
                            for problem in reason["problems"]), reason["problems"])
        self.assertEqual(find(v["sources"], "usgs-2025")["state"], "missing")
        self.assertEqual(find(v["risks"], "mine-output-rising")["state"], "unavailable")
        self.assertEqual(v["counts"]["elements"], {"available": 16, "needs_revalidation": 0, "unavailable": 2})

    def test_a_reason_within_one_edition_rests_on_that_edition_alone(self):  # Ruling R12.
        reason = find(self.view()["reasons"], "total-demand-rising")
        measure = reason["measure"]
        self.assertEqual([(measure[key]["source"], measure[key]["year"], measure[key]["as_shown"])
                          for key in ("latest", "previous")],
                         [("iea-2026", "2035", "31,800"), ("iea-2026", "2030", "29,500")])
        self.assertEqual((measure["compare"], measure["supports_when"], reason["status"], reason["change_pct"],
                          reason["sources"]), ("period", "higher", "strengthening", "7.8", ["iea-2026"]))
        self.assertEqual(reason["moved_by"], {"source": "iea-2026", "publisher": "Synthetic IEA", "edition": "2026",
                                              "edition_date": "2026-07-15"})
        shutil.rmtree(self.sources / "iea-2025")  # No previous edition on this machine: the reason reads unchanged.
        v = self.view()
        self.assertEqual(find(v["reasons"], "total-demand-rising"), reason)
        self.assertEqual(find(v["reasons"], "clean-tech-demand")["state"], "unavailable")
        (self.sources / "iea-2026" / "dataset.xlsx").write_bytes(b"Synthetic")  # Its one edition changed.
        changed = find(self.view()["reasons"], "total-demand-rising")
        self.assertEqual((changed["state"], changed["status"]), ("needs_revalidation", None))
        self.withheld(changed)

    def test_a_changed_source_needs_revalidation_and_withholds_numbers(self):
        dataset = self.sources / "iea-2026" / "dataset.xlsx"

        def later_record():
            path = thesis_fakes.record_path(self.sources, "iea-2026")
            record = json.loads(path.read_text(encoding="utf-8"))
            thesis_fakes.write_record(self.sources, "iea-2026", {**record, "recorded_at": "2026-11-02T08:59:00+00:00"})
        for name, change in (("the file", lambda: dataset.write_bytes(dataset.read_bytes() + b"\0")),
                             ("the record", later_record)):
            with self.subTest(changed=name):
                self.fresh()
                change()
                v = self.view()
                self.assertEqual(find(v["sources"], "iea-2026")["state"], "changed")
                self.assertEqual(v["counts"]["sources"], {"verified": 8, "changed": 1, "missing": 0})
                self.assertEqual({key for key, state in self.states(v).items() if state != "available"}, IEA_2026)
                for element in elements(v):
                    if element["id"] in IEA_2026:
                        self.assertEqual(element["state"], "needs_revalidation")
                        self.withheld(element)
                        self.assertTrue(any(problem.startswith("iea-2026: ") for problem in element["problems"]))
                        self.assertEqual(element["not_found"], [])
                self.assertEqual(v["counts"]["elements"], {"available": 9, "needs_revalidation": 9, "unavailable": 0})
                table = find(v["balance"]["tables"], "balance-steps")
                self.assertEqual((table["rows"], table["why_not"], table["gap"]), (None, None, "computed"))

    def test_a_quote_or_cell_no_longer_found_needs_revalidation(self):
        sheets = thesis_fakes.iea_sheets(2026)
        sheets["Copper"]["E3"] = "10200"
        cases = {
            "cell": ("iea-2026", thesis_fakes.workbook(sheets), {"balance-steps", "clean-tech-demand"},
                     "clean-tech-demand", "iea26-clean-2030: not found where cited (sheet Copper, cell E3)"),
            "row": ("usgs-2026", thesis_fakes.usgs_csv(2026).replace(b'"22,900"', b'"22,950"'),
                    {"balance-side-by-side", "mine-supply-slow"}, "mine-supply-slow",
                    "usgs26-mine-2024: not found where cited (row 5, column World mine production (kt))"),
            "paragraph": ("sec-maker-2025", thesis_fakes.maker_html().replace(b"210,000", b"220,000"), {"mover-2"},
                          "mover-2", "maker-deliveries-2025: not found where cited (paragraph 5)"),
        }  # The place only: the value or quote not found is withheld with the element.
        for name, (folder, data, affected, checked, problem) in cases.items():
            with self.subTest(changed=name):
                self.fresh()
                self.rerecord(folder, data)
                v = self.view()
                self.assertEqual(find(v["sources"], folder)["state"], "verified")
                self.assertEqual({key for key, state in self.states(v).items() if state != "available"}, affected)
                element = find(elements(v), checked)
                self.assertEqual(element["state"], "needs_revalidation")
                self.withheld(element)
                self.assertEqual(element["not_found"], [problem.split(":")[0]])
                self.assertEqual(element["problems"], [problem])
                self.assertEqual(v["counts"]["elements"],
                                 {"available": 18 - len(affected), "needs_revalidation": len(affected),
                                  "unavailable": 0})

    def test_a_verified_file_that_cannot_be_read_keeps_its_state_and_its_figures_need_revalidation(self):
        self.rerecord("usgs-2026", "Synthetic,café\r\n".encode("latin-1"))  # Recorded bytes that are not UTF-8.
        v = self.view()
        self.assertEqual(find(v["sources"], "usgs-2026")["state"], "verified")
        affected = {"balance-side-by-side", "mine-supply-slow", "mine-output-rising"}
        self.assertEqual({key for key, state in self.states(v).items() if state != "available"}, affected)
        reason = find(v["reasons"], "mine-supply-slow")
        self.assertEqual(reason["not_found"], ["usgs26-mine-2024"])
        self.assertEqual(reason["problems"], ["usgs26-mine-2024: The retained file of usgs-2026 matches its acquisition "
                                              "record but cannot be read (The file is not UTF-8 text)"])
        self.withheld(reason)

    def test_a_withheld_element_shows_no_value_or_quote_of_what_it_uses(self):
        sheets = thesis_fakes.iea_sheets(2026)
        sheets["Copper"]["E3"] = "10200"
        dataset = self.sources / "iea-2026" / "dataset.xlsx"
        scenarios = {
            "source changed": lambda: dataset.write_bytes(dataset.read_bytes() + b"\0"),
            "cell not found": lambda: self.rerecord("iea-2026", thesis_fakes.workbook(sheets)),
            "row not found": lambda: self.rerecord("usgs-2026", thesis_fakes.usgs_csv(2026).replace(b'"22,900"',
                                                                                                    b'"22,950"')),
            "passage not found": lambda: self.rerecord("sec-maker-2025", thesis_fakes.maker_html().replace(
                b"210,000", b"220,000")),
            "page figure not found": lambda: self.rerecord("sec-producer-2025", thesis_fakes.producer_html(2025).replace(
                b"<b>$410</b>", b"<b>$420</b>")),
            "unreadable": lambda: self.rerecord("usgs-2026", "Synthetic,café\r\n".encode("latin-1")),
            "source missing": lambda: shutil.rmtree(self.sources / "usgs-2025"),
            "nothing retained": lambda: shutil.rmtree(self.sources)}
        swept = set()  # The scenarios that withhold a condition, whose threshold is searched for too.
        for name, change in scenarios.items():
            with self.subTest(scenario=name):
                self.fresh()
                change()
                v = self.view()
                self.reconciled(v)  # Each element's items are the ids its version-file element names.
                thesis = thesis_schema.load_version(ID, 2, self.content)
                items = {item["id"]: item for item in thesis["figures"] + thesis["passages"]}
                files = file_elements(thesis)
                withheld = [element for element in elements(v) if element["state"] != "available"]
                self.assertTrue(withheld)
                if any("threshold" in files[element["id"]] for element in withheld):
                    swept.add(name)
                for element in withheld:
                    shown = strings(element, None, [])  # Every string the reply serves for the element.
                    numbers, quotes = [], []
                    for item in (items[entry["id"]] for entry in element["items"]):
                        numbers += [item["value"], item["as_shown"]] if "value" in item else []
                        quote = item["locator"].get("quote")
                        quotes += [quote, quote[:24]] if quote else []  # Whole, or cut short as locate shows it.
                    threshold = files[element["id"]].get("threshold")  # A condition's, as written and shown (M4).
                    if threshold is not None:
                        exact = thesis_arithmetic.decimal_of(threshold)
                        numbers += [threshold, thesis_arithmetic.display(exact, thesis_sections.places(exact))]
                    for text in shown:
                        for number in numbers:
                            self.assertIsNone(re.search(rf"(?<!\d){re.escape(number)}(?!\d)", text),
                                              f"{element['id']} shows {number!r}: {text!r}")
                        for part in quotes:
                            self.assertNotIn(part, text, f"{element['id']} shows a quote: {text!r}")
        self.assertTrue({"source changed", "nothing retained"} <= swept, swept)  # The condition's threshold is swept.

    def test_one_unreadable_sheet_withholds_only_the_figures_on_it(self):
        raw = rewritten(thesis_fakes.workbook({"Copper": {"C3": "Synthetic clean technologies", "E3": "10100"},
                                               "Notes": {"A1": "Synthetic", "B1": "5"}}),
                        lambda name, data: data.replace(b'<row r="1">', b'<row r="x">')
                        if name == "xl/worksheets/sheet2.xml" else data)  # Only the Notes sheet's own part fails.
        source = {**thesis_fakes.source_entries(self.sources)[2], "folder": "synthetic-one-bad-sheet"}
        good = {"id": "good", "source": source["id"], "value": "10100",
                "locator": {"sheet": "Copper", "cell": "E3", "label_cell": "C3", "label": "Synthetic clean technologies"}}
        bad = {"id": "bad", "source": source["id"], "value": "5",
               "locator": {"sheet": "Notes", "cell": "B1", "label_cell": "A1", "label": "Synthetic"}}
        for order in ([good, bad], [bad, good]):
            with self.subTest(first=order[0]["id"]):
                thesis_sources._MEMO.clear()
                problems = thesis_view._problems(source, raw, order)
                self.assertEqual(problems["good"], [])
                self.assertEqual(len(problems["bad"]), 1)
                self.assertIn("Sheet “Notes” cannot be read", problems["bad"][0])

    def test_a_differs_entry_is_checked_against_what_it_compares_with(self):
        def newer_only(body):
            body["differs"][0]["about"] = {
                "status": "interpretation", "cites": ["iea26-demand-2030", "iea26-supply-2030"],
                "text": "Synthetic reading: the newer edition puts demand of 29,500 kt above supply of 28,700 kt in 2030."}
            body["differs"][0]["others"].append({"cite": "iea21-construction", "label": "Synthetic earlier report"})
        self.write(change=newer_only)
        differs = self.view()["differs"][0]
        self.assertEqual((differs["state"], differs["sources"]), ("available", ["iea-2021", "iea-2025", "iea-2026"]))
        self.assertEqual([(other["cite"], other["figure"] and other["figure"]["source"],
                           other["passage"] and other["passage"]["where"]) for other in differs["others"]],
                         [("iea25-supply-2030", "iea-2025", None), ("iea25-demand-2030", "iea-2025", None),
                          ("iea21-construction", None, "page 2 (transcribed from the PDF)")])
        shutil.rmtree(self.sources / "iea-2025")
        differs = self.view()["differs"][0]
        self.assertEqual((differs["state"], differs["about"], differs["others"], differs["differs"]),
                         ("unavailable", None, None, None))

    def test_an_untracked_risk_shows_no_status_or_figure(self):
        risk = self.view()["risks"][2]
        self.assertEqual((risk["id"], risk["state"], risk["status"], risk["measure"], risk["change_pct"],
                          risk["moved_by"]), ("construction-slowdown", "available", "not_tracked", None, None, None))
        self.assertEqual((risk["sources"], risk["statement"]["figures"]), (["iea-2021"], []))
        self.assertEqual([passage["id"] for passage in risk["statement"]["passages"]], ["iea21-construction"])
        shutil.rmtree(self.sources / "iea-2021")
        risk = self.view()["risks"][2]
        self.assertEqual((risk["state"], risk["status"]), ("unavailable", None))
        self.withheld(risk)

    def test_a_title_or_series_that_states_a_figure_is_withheld_with_its_element(self):  # Ruling R9.
        title = "Synthetic clean-technology demand reaches 10,100 kt in 2030"
        series = "Synthetic monthly copper price, 2026 US dollars per tonne"

        def figured(body):
            body["reasons"][0]["title"] = title
            body["price_record"]["series"] = series
        self.write(change=figured)
        v = self.view()
        self.assertEqual((v["reasons"][0]["title"], v["price_record"]["series"]), (title, series))
        shutil.rmtree(self.sources / "iea-2025")
        shutil.rmtree(self.sources / "worldbank")
        v = self.view()
        self.assertEqual([(r["state"], r["title"]) for r in v["reasons"]],
                         [("unavailable", None), ("available", "Synthetic mine supply responds slowly"),
                          ("unavailable", "Synthetic recycling adds little supply"),
                          ("available", "Synthetic total demand keeps rising through the projection")])
        self.assertEqual((v["price_record"]["state"], v["price_record"]["series"]), ("unavailable", None))
        self.withheld(v["price_record"])
        self.fresh()  # A series without a figure stays shown beside the withheld record.
        shutil.rmtree(self.sources / "worldbank")
        record = self.view()["price_record"]
        self.assertEqual((record["state"], record["series"]),
                         ("unavailable", "Synthetic monthly copper price, nominal US dollars per tonne"))

    def test_without_any_sources_every_element_is_unavailable(self):
        shutil.rmtree(self.sources)
        v = self.view()
        self.assertEqual(v["counts"], {"sources": {"verified": 0, "changed": 0, "missing": 9},
                                       "elements": {"available": 0, "needs_revalidation": 0, "unavailable": 18}})
        for element in elements(v):
            self.assertEqual(element["state"], "unavailable")
            self.withheld(element)
        for source in v["sources"]:
            self.assertEqual(source["state"], "missing")
            self.assertIn("not on this machine", source["detail"])
        thesis = thesis_schema.load_version(ID, 2, self.content)
        for key in ("title", "topic", "opened_on", "prepared_on", "confidence", "log", "plain", "not_claimed",
                    "provenance"):
            self.assertEqual(v[key], thesis[key], key)
        self.assertEqual([r["title"] for r in v["reasons"]], [r["title"] for r in thesis["reasons"]])
        self.assertEqual([r["plain"] for r in v["risks"]], [r["plain"] for r in thesis["risks"]])
        self.assertEqual(v["price_record"]["series"], thesis["price_record"]["series"])
        condition = v["conditions"][0]  # Its threshold is the kind of figure it is withheld with (final review M4).
        self.assertEqual((condition["threshold"], condition["threshold_value"], condition["items"]),
                         (None, None, [{"id": "iea26-supply-2030", "source": "iea-2026"}]))
        self.reconciled(v)

    def test_counts_reconcile_with_states(self):
        scenarios = {"found": lambda: None,
                     "previous edition missing": lambda: shutil.rmtree(self.sources / "usgs-2025"),
                     "dataset changed": lambda: (self.sources / "iea-2026" / "dataset.xlsx").write_bytes(b"Synthetic"),
                     "page not found": lambda: self.rerecord("sec-maker-2025", thesis_fakes.maker_html().replace(
                         b"210,000", b"220,000")),
                     "nothing retained": lambda: shutil.rmtree(self.sources)}
        for name, change in scenarios.items():
            with self.subTest(scenario=name):
                self.fresh()
                change()
                v = self.view()
                found = elements(v)
                self.assertEqual(len(found), 18)
                self.assertEqual(v["counts"]["elements"],
                                 {state: sum(1 for e in found if e["state"] == state)
                                  for state in ("available", "needs_revalidation", "unavailable")})
                self.assertEqual(v["counts"]["sources"],
                                 {state: sum(1 for s in v["sources"] if s["state"] == state)
                                  for state in ("verified", "changed", "missing")})
                self.assertEqual(sum(v["counts"]["sources"].values()), 9)
                listed = {source["id"] for source in v["sources"]}
                for element in found:
                    self.assertEqual(element["state"], derived(v, element), element["id"])
                    self.assertEqual(element["sources"], sorted(set(element["sources"])))
                    self.assertTrue(set(element["sources"]) <= listed)
                    self.assertEqual(element["not_found"], sorted(set(element["not_found"])))
                    self.assertEqual(element["state"] == "available", not element["problems"], element["id"])
                    if element["state"] != "available":
                        self.withheld(element)
                self.reconciled(v)

    # ------------------------------------------------------------ passages for other pages

    def test_passages_are_checked_as_the_view_checks_them(self):
        """thesis_view.passages: the passages among the ids asked for, each checked as view checks it and named by its
        source entry (title, publisher, edition, edition date) in any state; one that is not verified has no quote and
        the one problem the view gives for it."""
        def passages(*ids):
            return thesis_view.passages(ID, list(ids), self.content, self.sources)
        verified = {"id": "maker-deliveries-2025", "source": "sec-maker-2025",
                    "title": "Synthetic annual report on Form 10-K, fiscal 2025", "publisher": "Synthetic Maker Inc.",
                    "edition": "Fiscal 2025", "edition_date": "2026-01-29",
                    "quote": "We delivered 210,000 Synthetic vehicles in 2025.", "where": "paragraph 5",
                    "state": "verified", "problem": None}
        got = passages("iea21-construction", "maker-deliveries-2025", "iea26-clean-2030", "no-such-passage",
                       "maker-deliveries-2025")
        self.assertEqual(list(got), ["iea21-construction", "maker-deliveries-2025"])  # A figure or unknown id: left out.
        self.assertEqual(got["maker-deliveries-2025"], verified)
        self.assertEqual({key: got["iea21-construction"][key] for key in ("title", "where", "state", "problem")},
                         {"title": "Synthetic report on minerals in clean energy transitions",
                          "where": "page 2 (transcribed from the PDF)", "state": "verified", "problem": None})
        maker, dataset = self.sources / "sec-maker-2025" / "10k.htm", self.sources / "iea-2026" / "dataset.xlsx"
        scenarios = {  # name -> (change, state, problem: None for the source's own detail, or how it starts)
            "another source changed": (lambda: dataset.write_bytes(dataset.read_bytes() + b"\0"), "verified", None),
            "changed": (lambda: maker.write_bytes(maker.read_bytes() + b"\n"), "changed", None),
            "missing": (lambda: shutil.rmtree(self.sources / "sec-maker-2025"), "missing", None),
            "not found": (lambda: self.rerecord("sec-maker-2025", thesis_fakes.maker_html().replace(b"210,000",
                                                                                                   b"220,000")),
                          "not_found", "maker-deliveries-2025: not found where cited (paragraph 5)"),
            "unreadable": (lambda: self.rerecord("sec-maker-2025", "Synthetic,café\r\n".encode("latin-1")), "not_found",
                           "maker-deliveries-2025: The retained file of sec-maker-2025 matches its acquisition record "
                           "but cannot be read")}
        for name, (change, state, problem) in scenarios.items():
            with self.subTest(name):
                self.fresh()
                change()
                got = passages("maker-deliveries-2025")["maker-deliveries-2025"]
                if state == "verified":
                    self.assertEqual(got, verified)
                    continue
                self.assertEqual({**got, "problem": None}, {**verified, "quote": None, "state": state})
                v = self.view()
                if problem is None:
                    problem = "sec-maker-2025: " + find(v["sources"], "sec-maker-2025")["detail"]
                self.assertTrue(got["problem"].startswith(problem), got["problem"])
                self.assertIn(got["problem"], find(v["exposure"]["movers"], "mover-2")["problems"])  # The view's own.
                shown = json.dumps(got, ensure_ascii=False)
                self.assertNotIn(verified["quote"][:24], shown)
                self.assertNotIn("210,000", shown)

    # ------------------------------------------------------------ versions

    def test_the_latest_version_and_an_older_version_are_both_readable(self):
        self.assertEqual(self.view()["version"], 2)
        self.assertEqual(self.view(version=1)["version"], 1)

        latest, first = self.view(), self.view(version=1)
        versions = [{"version": 1, "published_on": "2026-11-02"}, {"version": 2, "published_on": "2026-11-16"}]
        self.assertEqual((latest["versions"], first["versions"]), (versions, versions))
        self.assertEqual((latest["published_on"], first["published_on"]), ("2026-11-16", "2026-11-02"))
        self.assertEqual((latest["draft"], first["draft"]), (False, False))
        self.assertEqual((latest["confidence"]["level"], first["confidence"]["level"]), ("high", "medium"))
        self.assertEqual((len(latest["log"]), len(first["log"])), (3, 1))
        self.assertEqual(latest["log"][:1], first["log"])
        self.assertEqual((latest["prepared_on"], first["prepared_on"], latest["opened_on"]),
                         ("2026-11-16", "2026-11-02", "2026-11-02"))
        self.assertEqual(self.view(version=2), latest)
        for version in (0, 3, -1, True, "1", 1.0):
            with self.subTest(version=version), self.assertRaises(ThesisRefused) as caught:
                self.view(version)
            self.assertEqual(caught.exception.status, 404)
        for thesis_id in ("copper", "../synthetic-copper", "Synthetic-Copper"):
            with self.subTest(thesis_id=thesis_id), self.assertRaises(ThesisRefused) as caught:
                thesis_view.view(thesis_id, None, self.content, self.sources)
            self.assertEqual(caught.exception.status, 404)

    def test_a_draft_is_marked(self):
        self.write(["2026-11-02", None])
        latest, first = self.view(), self.view(version=1)
        self.assertEqual((latest["version"], latest["draft"], latest["published_on"]), (2, True, None))
        self.assertEqual((first["version"], first["draft"], first["published_on"]), (1, False, "2026-11-02"))
        self.assertEqual(latest["versions"], [{"version": 1, "published_on": "2026-11-02"},
                                              {"version": 2, "published_on": None}])

    def test_an_invalid_version_file_refuses_the_whole_thesis(self):
        path = self.content / ID / "v2.json"
        path.write_text(path.read_text(encoding="utf-8").replace("Synthetic test author", "Synthetic other author"),
                        encoding="utf-8", newline="\n")
        with self.assertRaises(ThesisRefused) as caught:
            self.view()
        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(self.view(version=1)["version"], 1)

    # ------------------------------------------------------------ reads only

    def test_reading_writes_nothing(self):
        calls = []

        def refused(name):
            def call(*args, **kwargs):
                calls.append(name)
                raise AssertionError(f"{name} was called")
            return call
        watched = [self.content, self.sources, thesis_schema.THESES_DIR, thesis_sources.SOURCES_DIR]
        before = [tree(folder) for folder in watched]
        with patch("socket.socket.connect", refused("connect")), patch("socket.getaddrinfo", refused("name lookup")):
            thesis_sources._MEMO.clear()
            first = self.view()
            self.assertEqual(self.view(), first)
            self.view(version=1)
            thesis_view.passages(ID, ["maker-deliveries-2025", "iea21-construction"], self.content, self.sources)
        self.assertEqual(calls, [])
        self.assertEqual([tree(folder) for folder in watched], before)
        self.assertEqual(sorted(path.name for path in self.tmp.iterdir()), ["content", "sources"])


if __name__ == "__main__":
    unittest.main()
