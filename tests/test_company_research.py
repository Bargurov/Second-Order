"""The FCX company page's server (company_research_view, company_research_api): what is sent when the four retained
documents are verified, missing or changed; the rules on the page's own texts; exact recomputation; access.

The retained documents live under data/company-sources/fcx/, which Git ignores. Tests that need them are skipped where
they are absent; everything else runs on any checkout. No test writes to the committed research folder or to data/:
each change is made to a copy in a temporary folder.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import account_fakes  # noqa: E402

from second_order import company_research_view as crv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "fcx"
DATA = ROOT / "data" / "company-sources" / "fcx"
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FIXTURES"
SOURCES = json.loads((RESEARCH / "sources.json").read_text(encoding="utf-8"))["sources"]
HAVE_DATA = all((DATA / s["folder"] / s["name"]).is_file() for s in SOURCES)
NEEDS_DATA = unittest.skipUnless(HAVE_DATA, "the retained FCX documents are not on this machine (data/ is private)")
FACTS = json.loads((RESEARCH / "facts.json").read_text(encoding="utf-8"))


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()}


def blocks(node, out=None) -> list[dict]:
    """Every resolved text block in the page, however deep."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if "segments" in node and "state" in node:
            out.append(node)
        for value in node.values():
            blocks(value, out)
    elif isinstance(node, list):
        for item in node:
            blocks(item, out)
    return out


class Copies(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-company-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def research_copy(self) -> Path:
        target = self.root / "research"
        shutil.copytree(RESEARCH, target)
        return target

    def data_copy(self) -> Path:
        target = self.root / "data"
        shutil.copytree(DATA, target)
        return target

    def edit(self, path: Path, change) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    def refused(self, research: Path, sources: Path | None = None) -> crv.CompanyRefused:
        with self.assertRaises(crv.CompanyRefused) as caught:
            crv.view(research, sources or self.root / "no-data")
        return caught.exception


class CommittedPackage(unittest.TestCase):
    def test_page_json_is_what_the_builder_writes(self):
        spec = importlib.util.spec_from_file_location("build_page", RESEARCH / "tools" / "build_page.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(json.loads((RESEARCH / "page.json").read_text(encoding="utf-8")), module.page(),
                         "page.json is stale; run python -I research/fcx/tools/build_page.py")

    def test_the_facts_checker_passes(self):
        run = subprocess.run([sys.executable, "-I", str(RESEARCH / "tools" / "check_facts.py")], capture_output=True,
                             text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("OK", run.stdout)

    def test_every_source_names_a_committed_acquisition_record(self):
        for source in crv.load_sources(RESEARCH):
            record = RESEARCH / "acquisition" / source["approval_id"] / f"outcome-{source['attempt']}.json"
            self.assertTrue(record.is_file(), record)

    def test_the_committed_files_are_lf(self):
        for name in ("page.json", "sources.json", "facts.json", "tools/build_page.py"):
            self.assertNotIn(b"\r", (RESEARCH / name).read_bytes(), name)


class Withheld(Copies):
    def test_without_the_retained_files_nothing_from_them_is_sent(self):
        reply = crv.view(RESEARCH, self.root / "no-data")
        self.assertEqual([s["state"] for s in reply["sources"]], ["missing"] * 4)
        self.assertEqual(reply["verified"], 0)
        text = json.dumps(reply, ensure_ascii=False)
        for rid, record in reply["records"].items():
            if record["kind"] == "assumption":
                continue
            self.assertEqual(record["state"], "withheld", rid)
            self.assertIsNone(record["value"], rid)
            if record["kind"] == "published":
                self.assertIsNone(record["display"], rid)
                self.assertIsNone(record["quote"], rid)
        for record in FACTS["records"]:
            if record["kind"] == "published" and len(record["quote"]) > 30:
                self.assertNotIn(record["quote"], text, record["id"])
        for passage in FACTS["passages"]:
            self.assertNotIn(passage["quote"], text, passage["id"])
        for block in blocks(reply["page"]):
            names = block["refs"] or block["passages"]
            self.assertEqual(block["state"], "withheld" if names else "available", block["refs"])

    def test_a_wrong_file_is_changed_not_missing(self):
        data = self.root / "data"
        source = SOURCES[3]
        (data / source["folder"]).mkdir(parents=True)
        (data / source["folder"] / source["name"]).write_bytes(b"%PDF not the retained file")
        states = {s["id"]: s["state"] for s in crv.view(RESEARCH, data)["sources"]}
        self.assertEqual(states["news-2026-11-04"], "changed")
        self.assertEqual(states["10k-2025"], "missing")

    def test_a_problem_is_fixed_text_that_carries_no_value(self):
        reply = crv.view(RESEARCH, self.root / "no-data")
        for rid, record in reply["records"].items():
            if record["kind"] == "published":
                self.assertEqual(record["problem"], f"Not shown: it rests on {crv.SHORT_NAMES[record['source']]}, which "
                                                    "is missing on this machine.", rid)
            elif record["kind"] == "computed":
                self.assertRegex(record["problem"], r"^Not shown: it rests on the [A-Za-z0-9 ,-]+, which (is|are) not "
                                                    r"verified on this machine\.$", rid)


ID_FIELDS = {  # what a withheld record may still carry: what it is, where it would come from, and why it is not shown
    "published": {"id", "kind", "metric", "unit", "period", "basis", "source", "page", "printed_page", "location",
                  "rests_on", "state", "problem", "value", "display", "quote"},
    "computed": {"id", "kind", "metric", "unit", "period", "basis", "formula", "inputs", "decimals", "assumptions",
                 "rests_on", "state", "problem", "value"},
    "assumption": {"id", "kind", "used_by", "rests_on", "state", "problem", "statement"},
}
# The assumptions whose statements describe what a document says; each names those documents in rests_on.
DOCUMENT_ASSUMPTIONS = {"a-bagdad-funding-arithmetic": ["news-2026-11-04"],
                        "a-bagdad-scale-reference": ["news-2026-11-04"],
                        "a-q4-2025-same-basis": ["10k-2025", "10q-2026q3", "release-2026q3"],
                        "a-revenue-bridge-grouping": ["10k-2025", "10q-2026q3"]}
BY_ID = {record["id"]: record for record in FACTS["records"]}


def rests_on(rid: str) -> set:
    record = BY_ID[rid]
    if record["kind"] == "published":
        return {record["source"]}
    if record["kind"] == "assumption":
        return set(DOCUMENT_ASSUMPTIONS.get(rid, []))
    return set().union(*(rests_on(used) for used in record["inputs"].values()))


def content_of(record: dict) -> list[str]:
    """The texts a record holds beyond what identifies it: its note, its explanations, its quote or statement (row and
    column labels are checked by field: a shown figure may share them)."""
    texts = [record.get(key) for key in ("note", "basis_mix", "period_mix", "unit_mix", "quote", "statement")]
    return [text for text in texts if isinstance(text, str) and len(text) >= 25]


class WithheldContent(Copies):
    """Nothing that rests on a document that is not verified is sent as content: not a note, not a computation's
    explanation, not an assumption that describes the document, not the words of a line that names it."""

    def assert_nothing_of(self, reply: dict, documents: set) -> None:
        text = json.dumps(reply, ensure_ascii=False)
        # Text that a shown figure or passage carries in its own right (the 10-Q quotes the same cost sentence as the
        # Bagdad release, for one): finding it is not a leak.
        shown = [content for record in reply["records"].values() if record["state"] == "available"
                 for content in content_of(record)]
        shown += [p["quote"] for p in reply["passages"].values() if p["state"] == "available"]
        for rid in BY_ID:
            if rests_on(rid) & documents:
                record = reply["records"][rid]
                self.assertEqual(record["state"], "withheld", rid)
                self.assertLessEqual(set(record), ID_FIELDS[record["kind"]], rid)
                if record["kind"] == "assumption":
                    self.assertIsNone(record["statement"], rid)
                for content in content_of(BY_ID[rid]):
                    if not any(content in other for other in shown):
                        self.assertTrue(content not in text, f"{rid}: {content[:60]}")

    def test_without_the_documents_a_withheld_record_carries_only_what_identifies_it(self):
        reply = crv.view(RESEARCH, self.root / "no-data")
        self.assert_nothing_of(reply, set(crv.SOURCE_IDS))
        self.assertNotIn("note", reply["records"]["r3-ocf-9m-2026"])
        self.assertNotIn("working capital", json.dumps(reply["records"]["r3-ocf-9m-2026"]))

    def test_withheld_lines_send_no_words(self):
        reply = crv.view(RESEARCH, self.root / "no-data")
        for block in blocks(reply["page"]):
            if block["state"] == "withheld":
                self.assertIsNone(block["segments"], block.get("refs"))
                self.assertTrue(block["refs"] or block["passages"])
        self.assertNotIn("ramps up after the September 2025 mud rush", json.dumps(reply, ensure_ascii=False))

    def test_assumptions_name_the_documents_they_describe(self):
        for record in FACTS["records"]:
            if record["kind"] == "assumption":
                self.assertEqual(record.get("rests_on"), DOCUMENT_ASSUMPTIONS.get(record["id"], []), record["id"])

    @NEEDS_DATA
    def test_a_missing_release_sends_nothing_of_it_and_keeps_the_rest(self):
        data = self.data_copy()
        (data / SOURCES[2]["folder"] / SOURCES[2]["name"]).unlink()
        reply = crv.view(RESEARCH, data)
        self.assert_nothing_of(reply, {"release-2026q3"})
        self.assertNotIn("working capital was $0.4 billion", json.dumps(reply, ensure_ascii=False))
        self.assertEqual(reply["records"]["k25-revenues-fy2025"]["note"], BY_ID["k25-revenues-fy2025"]["note"])
        self.assertEqual(reply["records"]["q3-ocf-9m-2025"]["state"], "available")

    @NEEDS_DATA
    def test_a_changed_bagdad_release_sends_nothing_of_it_and_keeps_the_rest(self):
        data = self.data_copy()
        path = data / SOURCES[3]["folder"] / SOURCES[3]["name"]
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(bytes(raw))
        reply = crv.view(RESEARCH, data)
        self.assert_nothing_of(reply, {"news-2026-11-04"})
        self.assertNotIn("$4.5 billion estimate", json.dumps(reply, ensure_ascii=False))
        self.assertIsNone(reply["records"]["a-bagdad-funding-arithmetic"]["statement"])
        self.assertEqual(reply["records"]["r3-ocf-9m-2026"]["note"], BY_ID["r3-ocf-9m-2026"]["note"])
        self.assertEqual(reply["records"]["a-price-volume-split"]["statement"], BY_ID["a-price-volume-split"]["statement"])


GRASBERG = ("r3-cu-grasberg-q3-2026-production", "r3-cu-grasberg-q3-2025-production", "r3-cu-grasberg-q3-2026-sales",
            "r3-cu-grasberg-q3-2025-sales")
OWNERSHIP = "48.76"  # FCX's share of PTFI as the documents print it: a figure from them, never part of a name
PERCENT = re.compile(r"\d\s*%")


def names_of(record: dict) -> dict:
    """What names a figure and is sent even when it is withheld: its name, unit, basis, location and period label."""
    named = {key: record[key] for key in ("metric", "unit", "basis", "location") if isinstance(record.get(key), str)}
    return {**named, "period.label": record["period"]["label"]}


class OwnershipNotInNames(Copies):
    """An ownership share is a figure from a document, not a neutral name. It is in no figure's name, so a withheld
    figure's name (and the accessible label the page builds from it) carries none; a share is shown by its own record,
    and only when that record's document is verified."""

    def assert_withheld_names_clean(self, reply: dict, state: str) -> None:
        release = next(s for s in reply["sources"] if s["id"] == "release-2026q3")
        self.assertEqual(release["state"], state)
        for rid in GRASBERG:
            record = reply["records"][rid]
            self.assertEqual((record["state"], record["value"], record["quote"]), ("withheld", None, None), rid)
            self.assertEqual(record["metric"], "Copper volumes: Grasberg minerals district", rid)
            self.assertNotIn(OWNERSHIP, json.dumps(record, ensure_ascii=False), rid)
        for rid, record in reply["records"].items():
            if record["state"] == "withheld" and record["kind"] != "assumption":
                for field, text in names_of(record).items():
                    self.assertIsNone(PERCENT.search(text), f"{rid}.{field} carries a percentage")

    def test_no_figure_is_named_with_a_percentage(self):
        for record in FACTS["records"]:
            if record["kind"] != "assumption":
                for field, text in names_of(record).items():
                    self.assertIsNone(PERCENT.search(text), f"{record['id']}.{field}: {text}")

    def test_a_missing_release_leaves_no_share_in_a_withheld_name(self):
        reply = crv.view(RESEARCH, self.root / "no-data")
        self.assert_withheld_names_clean(reply, "missing")
        self.assertNotIn(OWNERSHIP, json.dumps(reply, ensure_ascii=False))  # nothing is verified: the share is nowhere

    def test_a_changed_release_leaves_no_share_in_a_withheld_name(self):
        data = self.root / "data"
        source = SOURCES[2]
        (data / source["folder"]).mkdir(parents=True)
        (data / source["folder"] / source["name"]).write_bytes(b"%PDF not the retained file")
        self.assert_withheld_names_clean(crv.view(RESEARCH, data), "changed")

    @NEEDS_DATA
    def test_with_the_release_missing_the_share_is_shown_only_by_a_verified_record(self):
        data = self.data_copy()
        (data / SOURCES[2]["folder"] / SOURCES[2]["name"]).unlink()
        reply = crv.view(RESEARCH, data)
        self.assert_withheld_names_clean(reply, "missing")
        self.assertEqual(reply["records"]["r3-ptfi-ownership"]["state"], "withheld")
        self.assertEqual((reply["records"]["k25-ownership-ptfi"]["state"], reply["records"]["k25-ownership-ptfi"]["display"]),
                         ("available", OWNERSHIP))

    @NEEDS_DATA
    def test_with_the_release_changed_the_share_is_shown_only_by_a_verified_record(self):
        data = self.data_copy()
        path = data / SOURCES[2]["folder"] / SOURCES[2]["name"]
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(bytes(raw))
        reply = crv.view(RESEARCH, data)
        self.assert_withheld_names_clean(reply, "changed")
        self.assertEqual(reply["records"]["k25-ownership-ptfi"]["state"], "available")
        for block in blocks(reply["page"]):  # the page's ownership lines name the release's record: withheld whole
            if "r3-ptfi-ownership" in block["refs"]:
                self.assertEqual((block["state"], block["segments"]), ("withheld", None))

    def test_a_percentage_in_a_name_is_refused_naming_the_field_not_the_figure(self):
        research = self.research_copy()

        def change(facts):
            next(r for r in facts["records"] if r["id"] == "r3-cu-sales-q3-2026")["metric"] = "Copper sales (48.76%)"
        self.edit(research / "facts.json", change)
        error = self.refused(research)
        self.assertEqual(error.status, 500)
        self.assertIn("facts.json[r3-cu-sales-q3-2026].metric", str(error))
        self.assertNotIn(OWNERSHIP, str(error))

    def test_a_measure_definition_in_a_name_stays(self):
        names = [record["metric"] for record in FACTS["records"] if record["kind"] != "assumption"]
        self.assertIn("Change in operating cash flows per $0.10/lb change in average copper price", names)

    def test_the_facts_checker_flags_a_percentage_in_a_name(self):
        folder = self.root / "checkout" / "research" / "fcx"  # data/ is absent beside this copy: source checks skip
        shutil.copytree(RESEARCH, folder, ignore=shutil.ignore_patterns("__pycache__"))
        self.edit(folder / "facts.json", lambda facts: next(r for r in facts["records"] if r["id"] ==
                                                            "r3-cu-sales-q3-2026").update(metric="Copper sales (48.76%)"))
        run = subprocess.run([sys.executable, "-I", str(folder / "tools" / "check_facts.py")], capture_output=True,
                             text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("FAIL: r3-cu-sales-q3-2026: metric carries a percentage", run.stdout)


@NEEDS_DATA
class Verified(Copies):
    def test_all_four_verified_and_every_record_shown(self):
        before = (tree(RESEARCH), tree(DATA))
        reply = crv.view()
        self.assertEqual(reply["verified"], 4)
        self.assertEqual({r["state"] for r in reply["records"].values()}, {"available"})
        self.assertEqual({b["state"] for b in blocks(reply["page"])}, {"available"})
        self.assertFalse(reply["provider_called"])
        self.assertEqual((tree(RESEARCH), tree(DATA)), before, "a read changed a file")

    def test_every_computed_figure_recomputes_exactly(self):
        records = crv.view()["records"]
        self.assertEqual(records["c-bagdad-funding-2028-high"]["value"], "1.575")
        self.assertEqual(records["c-bagdad-capex-estimate-change"]["value"], "28.6")
        self.assertEqual(records["c-rev-bridge-closes-q3-2026"]["value"], "0")
        self.assertEqual(crv.quantize(crv.evaluate("a / b * 100", {"a": crv.Decimal(1), "b": crv.Decimal(8)}), 1),
                         crv.Decimal("12.5"))  # half-even: 12.5 stays 12.5 at one place
        self.assertEqual(crv.quantize(crv.Decimal("0.125"), 2), crv.Decimal("0.12"))

    def test_one_changed_byte_withholds_only_what_rests_on_that_document(self):
        data = self.data_copy()
        path = data / SOURCES[3]["folder"] / SOURCES[3]["name"]
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(bytes(raw))
        reply = crv.view(RESEARCH, data)
        states = {s["id"]: s["state"] for s in reply["sources"]}
        self.assertEqual(states, {"10k-2025": "verified", "10q-2026q3": "verified", "release-2026q3": "verified",
                                  "news-2026-11-04": "changed"})
        records = reply["records"]
        for rid, record in records.items():
            if rid.startswith("nr-"):
                self.assertEqual((record["state"], record["value"], record["quote"]), ("withheld", None, None), rid)
        for rid in ("c-bagdad-funding-2027", "c-bagdad-cu-increment-share-fy2025", "c-bagdad-capex-estimate-change"):
            self.assertEqual(records[rid]["state"], "withheld", rid)
            self.assertIn("the Bagdad release of 4 November 2026, which is not verified", records[rid]["problem"])
        self.assertEqual(records["r3-cu-sales-q3-2026"]["state"], "available")
        self.assertEqual(records["q3-bagdad-capex-estimate"]["state"], "available")
        summary = reply["page"]["summary"]
        self.assertEqual([b["state"] for b in summary], ["available", "available", "withheld"])
        text = json.dumps(reply, ensure_ascii=False)
        for passage in FACTS["passages"]:
            if passage["source"] == "news-2026-11-04":
                self.assertNotIn(passage["quote"], text, passage["id"])

    def test_a_missing_release_withholds_its_figures_and_the_tiles_on_them(self):
        data = self.data_copy()
        (data / SOURCES[2]["folder"] / SOURCES[2]["name"]).unlink()
        reply = crv.view(RESEARCH, data)
        self.assertEqual(reply["verified"], 3)
        records = reply["records"]
        for tile in reply["page"]["tiles"]:  # every tile's figure rests on the release
            self.assertEqual(records[tile["value"]]["state"], "withheld", tile["id"])
        self.assertEqual(records["k25-revenues-fy2025"]["state"], "available")
        self.assertIn("is missing on this machine", records["r3-cu-sales-q3-2026"]["problem"])

    def test_an_acquisition_record_that_disagrees_withholds_its_document(self):
        research = self.research_copy()
        quarterly = next(s for s in SOURCES if s["id"] == "10q-2026q3")
        self.edit(research / "acquisition" / quarterly["approval_id"] / f"outcome-{quarterly['attempt']}.json",
                  lambda record: record.update(sha256="0" * 64))
        reply = crv.view(research, DATA)
        source = next(s for s in reply["sources"] if s["id"] == "10q-2026q3")
        self.assertEqual(source["state"], "changed")
        self.assertIn("sha256", source["detail"])
        self.assertEqual(reply["records"]["q3-ocf-9m-2025"]["state"], "withheld")

    def test_a_computed_figure_that_does_not_recompute_is_withheld_with_what_names_it(self):
        research = self.research_copy()

        def change(facts):
            next(r for r in facts["records"] if r["id"] == "c-yoy-revenues-q3-2026")["value"] = 8.3
        self.edit(research / "facts.json", change)
        reply = crv.view(research, DATA)
        record = reply["records"]["c-yoy-revenues-q3-2026"]
        self.assertEqual((record["state"], record["value"]), ("withheld", None))
        self.assertIn("does not recompute", record["problem"])
        revenue = next(c for c in reply["page"]["changes"] if c["id"] == "revenue")
        self.assertEqual(revenue["state"], "withheld")

    def test_a_printed_figure_that_does_not_read_as_its_value_is_withheld(self):
        research = self.research_copy()

        def change(facts):
            next(r for r in facts["records"] if r["id"] == "r3-cu-sales-q3-2026")["value"] = 750
        self.edit(research / "facts.json", change)
        record = crv.view(research, DATA)["records"]["r3-cu-sales-q3-2026"]
        self.assertEqual((record["state"], record["display"]), ("withheld", None))
        self.assertNotIn("749", record["problem"])

    def test_a_computed_input_withheld_withholds_the_chain(self):
        research = self.research_copy()

        def change(facts):
            next(r for r in facts["records"] if r["id"] == "r3-capex-9m-2026")["value"] = 1
        self.edit(research / "facts.json", change)
        records = crv.view(research, DATA)["records"]
        self.assertEqual(records["c-ocf-less-capex-9m-2026"]["state"], "withheld")
        self.assertIn("r3-capex-9m-2026", records["c-ocf-less-capex-9m-2026"]["problem"])


class PageRules(Copies):
    def page_change(self, change) -> crv.CompanyRefused:
        research = self.research_copy()
        self.edit(research / "page.json", change)
        return self.refused(research)

    def test_a_typed_number_in_prose_is_refused(self):
        error = self.page_change(lambda page: page["summary"][0].update(text="Copper was three quarters, 75 percent."))
        self.assertEqual(error.status, 500)
        self.assertIn("summary[0].text", str(error))
        self.assertIn("no digits", str(error))

    def test_years_and_form_names_are_allowed(self):
        research = self.research_copy()
        self.edit(research / "page.json",
                  lambda page: page["summary"][0].update(text="The 10-Q and the 10-K of 2026 agree."))
        crv.view(research, self.root / "no-data")

    def test_an_unknown_placeholder_is_refused(self):
        error = self.page_change(lambda page: page["summary"][0].update(text="Copper was {{r3-no-such-record}}."))
        self.assertIn("unknown record", str(error))

    def test_causal_and_forecast_phrasing_is_refused(self):
        error = self.page_change(lambda page: page["changes"][0].update(text="Prices rose due to demand."))
        self.assertIn("causal and forecast", str(error))

    def test_valuation_words_are_refused(self):
        error = self.page_change(lambda page: page["summary"][0].update(text="Our target price is high."))
        self.assertIn("valuation", str(error))

    def test_a_number_in_page_json_is_refused(self):
        error = self.page_change(lambda page: page["tiles"][0].update(extra=12))
        self.assertIn("holds no numbers", str(error))

    def test_an_unknown_passage_is_refused(self):
        error = self.page_change(lambda page: page["summary"][1].update(passages=["r3-p-no-such-passage"]))
        self.assertIn("unknown passage", str(error))

    def test_an_unknown_tile_record_is_refused(self):
        error = self.page_change(lambda page: page["tiles"][0].update(value="r3-no-such-record"))
        self.assertIn("tiles[0].value", str(error))

    def test_missing_files_are_503_and_malformed_ones_500(self):
        research = self.research_copy()
        (research / "page.json").unlink()
        self.assertEqual(self.refused(research).status, 503)
        shutil.copy(RESEARCH / "page.json", research / "page.json")
        (research / "facts.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.refused(research).status, 500)
        shutil.copy(RESEARCH / "facts.json", research / "facts.json")
        self.edit(research / "sources.json", lambda data: data["sources"].reverse())
        self.assertIn("four FCX documents", str(self.refused(research)))


class Access(Copies):
    def setUp(self):
        super().setUp()
        self.accounts = account_fakes.World(self.root / "accounts")

    def client(self, user):
        return self.accounts.client(user, company_research_dir=RESEARCH, company_sources_dir=DATA)

    def test_admins_only(self):
        self.assertEqual(self.client("admin").get("/api/companies/fcx").status_code, 200)
        reader = self.client("reader-a").get("/api/companies/fcx")
        self.assertEqual(reader.status_code, 403)
        self.assertNotIn("Grasberg", reader.text)
        self.assertEqual(self.client(None).get("/api/companies/fcx").status_code, 401)

    def test_it_is_a_read_only_route(self):
        app = self.accounts.app(company_research_dir=RESEARCH, company_sources_dir=DATA)
        methods = {method for route in app.routes if getattr(route, "path", "") == "/api/companies/fcx"
                   for method in route.methods}
        self.assertEqual(methods, {"GET"})

    def test_a_refusal_keeps_its_status_and_names_no_path(self):
        research = self.research_copy()
        (research / "page.json").unlink()
        reply = self.accounts.client("admin", company_research_dir=research,
                                     company_sources_dir=DATA).get("/api/companies/fcx")
        self.assertEqual(reply.status_code, 503)
        self.assertNotIn(str(self.root), reply.text)


def fixture_subset(reply: dict) -> dict:
    """The parts of a reply the frontend tests need: the page, the sources and every record and passage the page names,
    with the inputs of computed figures and the assumptions they use."""
    wanted, cited = set(), set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in crv.REF_KEYS and isinstance(value, str):
                    wanted.add(value)
                elif key == "ids":
                    wanted.update(item for item in value if item)
                elif key == "passages":
                    cited.update(value)
                elif key == "refs":
                    wanted.update(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(reply["page"])
    records = reply["records"]
    queue = list(wanted)
    while queue:
        record = records[queue.pop()]
        for used in list(record.get("inputs", {}).values()) + record.get("assumptions", []):
            if used not in wanted:
                wanted.add(used)
                queue.append(used)
    return {**reply, "records": {rid: rec for rid, rec in records.items() if rid in wanted},
            "passages": {pid: p for pid, p in reply["passages"].items() if pid in cited}}


class Fixtures(Copies):
    """The captured company-page replies. They are built from the package as the public tree holds it: a temporary
    copy of research/fcx without the earlier investor-relations acquisitions (fcx-filings-01, fcx-news-02; private, not
    in the public repository), which the export leaves out. The live private app still lists their requests; no
    committed fixture does."""

    def public_research(self) -> Path:
        target = self.root / "public-research"
        private = shutil.ignore_patterns("fcx-filings-*", "fcx-news-*")  # the private acquisitions
        shutil.copytree(RESEARCH, target, ignore=private)
        return target

    def check(self, name: str, reply: dict) -> None:
        reply = fixture_subset(reply)
        text = json.dumps(reply, ensure_ascii=False)
        self.assertNotIn(str(self.root), text, name)
        path = FIXTURES / name
        if os.environ.get(WRITE_FIXTURES) == "1":
            path.write_bytes((json.dumps(reply, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        else:
            self.assertEqual(reply, json.loads(path.read_text(encoding="utf-8")),
                             f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover -s "
                             "tests -p test_company_research.py")

    def test_the_unavailable_fixture(self):
        self.check("company-fcx-unavailable.json", crv.view(self.public_research(), self.root / "no-data"))

    @NEEDS_DATA
    def test_the_verified_and_changed_fixtures(self):
        research = self.public_research()
        self.check("company-fcx-view.json", crv.view(research, DATA))
        data = self.data_copy()
        path = data / SOURCES[3]["folder"] / SOURCES[3]["name"]
        raw = bytearray(path.read_bytes())
        raw[100] ^= 1
        path.write_bytes(bytes(raw))
        self.check("company-fcx-news-changed.json", crv.view(research, data))


if __name__ == "__main__":
    unittest.main()
