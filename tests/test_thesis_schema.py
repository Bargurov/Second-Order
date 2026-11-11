"""The committed thesis file, its index and the version chain (thesis_schema, thesis_sections).

Runs on the SYNTHETIC versions 1 and 2 (tests/thesis_fakes.py) written into temporary folders. Loading reads content
only; one test also proves that every synthetic figure and passage is found in the synthetic retained sources, which the
view (Task 6) builds on.
"""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import thesis_fakes
from second_order import bis_snapshot, thesis_arithmetic, thesis_schema, thesis_sources
from second_order.thesis_arithmetic import decimal_of, display
from second_order.thesis_rules import ThesisRefused

ROOT = Path(__file__).resolve().parent.parent
ID = thesis_fakes.THESIS_ID
PUBLISHED = ["2026-11-02", None]
# Ruling R12, as thesis_sections words it: what refuses two figures from one edition.
ONE_EDITION = "two figures from one edition compare a later year with an earlier one (period), never one year revised"
READ_BYTES = Path.read_bytes


def find(items: list, item_id: str) -> dict:
    return next(item for item in items if item["id"] == item_id)


def figure(body: dict, figure_id: str) -> dict:
    return find(body["figures"], figure_id)


def objects(value, path=()):
    """Every JSON object in ``value``, with the path of keys and indexes that reaches it."""
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from objects(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from objects(item, path + (index,))


def at(value, path):
    for step in path:
        value = value[step]
    return value


class Theses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="second-order-thesis-schema-"))
        cls.sources = thesis_fakes.write_sources(cls.tmp / "sources")
        cls.v1 = thesis_fakes.thesis_v1(cls.sources)
        cls.v2 = thesis_fakes.thesis_v2(cls.v1, cls.sources)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.content = Path(tempfile.mkdtemp(prefix="second-order-theses-"))
        self.addCleanup(shutil.rmtree, self.content, True)
        self.write([self.v1, self.v2])

    def write(self, versions: list[dict], published: list | None = None) -> None:
        shutil.rmtree(self.content / ID, ignore_errors=True)
        thesis_fakes.write_theses(self.content, versions, PUBLISHED[:len(versions)] if published is None else published)

    def load(self, version: int) -> dict:
        return thesis_schema.load_version(ID, version, self.content)

    def refusal(self, versions: list[dict], published: list | None = None, where: str | None = None) -> str:
        self.write(versions, published)
        with self.assertRaises(ThesisRefused) as caught:
            self.load(len(versions))
        self.assertEqual(caught.exception.status, 500, str(caught.exception))
        if where is not None:
            self.assertIn(f"({where}", str(caught.exception))
        return str(caught.exception)

    def refused(self, change, where: str | None = None) -> str:
        """Version 1 with ``change`` applied, refused (500); ``where`` begins the refusal's place."""
        return self.refusal([thesis_fakes.changed(self.v1, change)], where=where)

    def accepted(self, change) -> dict:
        self.write([thesis_fakes.changed(self.v1, change)])
        return self.load(1)

    def refused_v2(self, change, where: str | None = None, published: list | None = None) -> str:
        return self.refusal([self.v1, thesis_fakes.changed(self.v2, change)], published, where)


class VersionFileTests(Theses):
    def test_the_vocabularies_and_places_are_as_specified(self):
        self.assertEqual((thesis_schema.THESIS_VERSION, thesis_schema.INDEX_VERSION, thesis_schema.CATALOG_VERSION),
                         ("thesis-0.1", "thesis-index-0.1", "thesis-catalog-0.1"))
        self.assertEqual(thesis_schema.THESES_DIR, ROOT / "content" / "theses")
        self.assertEqual(thesis_schema.MAX_FILE_BYTES, 2_000_000)
        self.assertEqual(thesis_schema.UNITS, ("kt", "million_t", "t", "kg", "kg_per_unit", "usd_per_tonne",
                                               "usd_per_lb", "usd_cents_per_lb", "usd", "usd_million",
                                               "percent", "count"))
        self.assertEqual(thesis_fakes.INDEX_VERSION, thesis_schema.INDEX_VERSION)

    def test_the_synthetic_versions_load(self):
        self.assertEqual(self.load(1), self.v1)
        self.assertEqual(self.load(2), self.v2)
        index = thesis_schema.load_index(ID, self.content)
        self.assertEqual([(entry["version"], entry["file"], entry["published_on"]) for entry in index["versions"]],
                         [(1, "v1.json", "2026-11-02"), (2, "v2.json", None)])
        for entry, version in zip(index["versions"], (self.v1, self.v2)):
            self.assertEqual(entry["sha256"], bis_snapshot.sha256(bis_snapshot.canonical(version)))
        v1 = self.v1
        elements = (1 + len(v1["balance"]["tables"]) + len(v1["differs"]) + len(v1["reasons"]) + len(v1["risks"])
                    + len(v1["conditions"]) + len(v1["exposure"]["movers"]) + len(v1["exposure"]["moved"]) + 1)
        self.assertEqual(elements, 18)
        self.assertEqual([table["gap"] for table in v1["balance"]["tables"]], ["computed", "not_computed"])
        first = v1["balance"]["tables"][0]["rows"][0]
        self.assertEqual((figure(v1, first["demand_total"])["as_shown"], figure(v1, first["supply_total"])["as_shown"]),
                         ("26,500", "26,000"))
        self.assertEqual([risk["measure"] is None for risk in v1["risks"]], [False, False, True])
        # One reason compares two years within one edition (ruling R12); every other measure compares two editions.
        self.assertEqual([(claim["id"], claim["measure"]["compare"]) for claim in v1["reasons"] + v1["risks"]
                          if claim["measure"] is not None and figure(v1, claim["measure"]["latest"])["source"]
                          == figure(v1, claim["measure"]["previous"])["source"]], [("total-demand-rising", "period")])
        self.assertEqual([(item["side"], item["amount"]["kind"]) for item in v1["exposure"]["moved"]],
                         [("producer", "stated"), ("consumer", "stated"), ("consumer", "computed")])
        self.assertEqual([entry["kind"] for entry in v1["log"]], ["opened"])
        self.assertEqual((self.v2["confidence"]["level"], [entry["kind"] for entry in self.v2["log"]]),
                         ("high", ["opened", "status", "confidence"]))
        self.assertEqual(v1["confidence"]["level"], "medium")

    def test_every_synthetic_figure_and_passage_is_found_in_the_synthetic_sources(self):
        # What the view (Task 6) builds on: every element available, and these computed values.
        sources = {entry["id"]: entry for entry in self.v1["sources"]}
        thesis_sources._MEMO.clear()
        self.addCleanup(thesis_sources._MEMO.clear)
        for item in self.v1["figures"] + self.v1["passages"]:
            with self.subTest(item=item["id"]):
                source = sources[item["source"]]
                state, raw = thesis_sources.verify(source, self.sources)
                self.assertEqual(state["state"], "verified", state["detail"])
                sheets = (item["locator"]["sheet"],) if source["kind"] == "xlsx" else ()
                self.assertEqual(thesis_sources.locate(item, source, thesis_sources.content(source, raw, sheets)), [])

        def value(figure_id):
            return decimal_of(figure(self.v1, figure_id)["value"])
        states = [thesis_arithmetic.reason_state(value(m["previous"]), value(m["latest"]), m["supports_when"],
                                                 decimal_of(m["material_change_pct"]))
                  for m in (reason["measure"] for reason in self.v1["reasons"])]
        self.assertEqual(states, ["strengthening", "unchanged", "weakening", "strengthening"])
        row = self.v1["balance"]["tables"][0]["rows"][0]
        gap = thesis_arithmetic.balance(value(row["supply_total"]), value(row["demand_total"]))
        self.assertEqual((display(gap["gap"], 0), gap["label"], display(gap["weeks"], 1)), ("-500", "deficit", "1.0"))
        amount = self.v1["exposure"]["moved"][2]["amount"]
        cost = thesis_arithmetic.per_unit_cost(value(amount["per_unit"]), value(amount["price"]))
        self.assertEqual((display(cost, 0), display(thesis_arithmetic.share_pct(cost, value(amount["unit_price"])), 1)),
                         ("505", "1.1"))
        self.assertEqual([figure(self.v1, amount[key])["as_shown"] for key in ("per_unit", "price", "unit_price")],
                         ["53.2", "9,500", "$45,000"])

    def test_every_top_level_and_section_field_is_required_and_none_is_defaulted(self):
        shapes = set()
        for path, found in objects(self.v1):
            shape = (tuple("*" if isinstance(step, int) else step for step in path), frozenset(found))
            if shape in shapes:
                continue
            shapes.add(shape)
            for key in [*found, None]:
                with self.subTest(path=path, removed=key):
                    def change(body, path=path, key=key):
                        if key is None:
                            at(body, path)["synthetic_extra"] = "Synthetic"
                        else:
                            del at(body, path)[key]
                    self.assertIn("expected exactly the fields", self.refused(change))
        self.assertEqual(len(shapes), 38)  # every kind of object, locators and amounts of each kind included
        self.assertEqual(len(self.v1), 24)
        index_path = self.content / ID / "index.json"
        written = json.loads(index_path.read_text(encoding="utf-8"))
        for path in ((), ("versions", 0)):
            for key in [*at(written, path), None]:
                with self.subTest(index=path, removed=key):
                    index = json.loads(json.dumps(written))
                    if key is None:
                        at(index, path)["synthetic_extra"] = "Synthetic"
                    else:
                        del at(index, path)[key]
                    index_path.write_text(json.dumps(index), encoding="utf-8")
                    with self.assertRaises(ThesisRefused) as caught:
                        thesis_schema.load_index(ID, self.content)
                    self.assertEqual(caught.exception.status, 500)
                    self.assertIn("expected exactly the fields", str(caught.exception))

    def test_a_shown_value_must_equal_its_value(self):
        def setting(figure_id, **values):
            return lambda body: figure(body, figure_id).update(values)
        self.refused(setting("usgs26-mine-2024", value="23001", as_shown="23,000"),
                     "figures[usgs26-mine-2024].as_shown")
        for as_shown in ("23 million", "1.2e3", "23,00", "", 22900, None):
            with self.subTest(as_shown=as_shown):
                self.refused(setting("usgs26-mine-2024", as_shown=as_shown), "figures[usgs26-mine-2024].as_shown")
        for value in ("22,900", "2.29e4", 22900, None, "+22900"):
            with self.subTest(value=value):
                self.refused(setting("usgs26-mine-2024", value=value), "figures[usgs26-mine-2024].value")
        # On a page or a transcribed PDF the figure must be printed inside its own quote.
        self.refused(setting("maker-price-2025", value="46000", as_shown="$46,000"),
                     "figures[maker-price-2025].locator")
        self.refused(setting("iea21-ev-copper", value="53.3", as_shown="53.3"), "figures[iea21-ev-copper].locator")
        loaded = self.accepted(setting("usgs26-mine-2024", value="22900.0"))  # equal values, exactly
        self.assertEqual(figure(loaded, "usgs26-mine-2024")["value"], "22900.0")

    def test_text_figures_must_come_from_what_it_cites(self):
        cases = [
            (lambda b: b["view"].update(text=b["view"]["text"] + " Synthetic: 31,800 kt in 2035."), "view.text"),
            (lambda b: b["reasons"][0]["statement"].update(text="Synthetic reading: demand in 2035."),
             "reasons[clean-tech-demand].statement.text"),
            (lambda b: b["reasons"][0].update(title="Synthetic demand in 2035"), "reasons[clean-tech-demand].title"),
            (lambda b: b["conditions"][0].update(text="Synthetic: supply above 30,000 kt."),
             "conditions[supply-above].text"),
            (lambda b: b["exposure"]["movers"][0].update(through="Synthetic: sales of 5,000 million pounds."),
             "exposure.movers[0].through"),
            (lambda b: b["differs"][0]["others"][0].update(label="Synthetic edition of 2026"),
             "differs[differs-earlier-edition].others[0].label"),
            (lambda b: b["exposure"]["moved"][2]["how"].update(text="Synthetic reading: about 506 USD a vehicle."),
             "exposure.moved[2].how.text"),
            (lambda b: b["balance"]["tables"][0].update(title="Synthetic gap of 650 kt"),
             "balance.tables[balance-steps].title"),
            (lambda b: b["balance"]["tables"][1].update(why_not="Synthetic: two bases, 2 publications."),
             "balance.tables[balance-side-by-side].why_not"),
            (lambda b: b["balance"]["tables"][0]["rows"][0]["lines"][0].update(label="Synthetic clean 2030"),
             "balance.tables[balance-steps].rows[0].lines[0].label"),
            (lambda b: figure(b, "usgs26-mine-2024").update(measure="Synthetic mine production, 2023"),
             "figures[usgs26-mine-2024].measure"),
            (lambda b: b["view"].update(status="not_stated", cites=[], text="Synthetic: 29,500 kt."), "view.text"),
            (lambda b: b.update(title="Synthetic copper 2026"), "title"),
            (lambda b: b["confidence"].update(basis="Synthetic: 2 of 3 reasons hold."), "confidence.basis"),
            (lambda b: b["provenance"].update(method="Synthetic: written on 2 November."), "provenance.method"),
        ]
        for change, where in cases:
            with self.subTest(where=where):
                self.refused(change, where)
        accepted = [  # the same kinds of text, now held to what they cite or compute
            lambda b: b["view"].update(text=b["view"]["text"] + " Synthetic: 31,800 kt in 2035.",
                                       cites=b["view"]["cites"] + ["iea26-demand-2035"]),
            # Computed outputs only: the 2035 gap in weeks, the reason's change, the vehicle's cost and share.
            lambda b: b["balance"]["tables"][0].update(title="Synthetic gap of about 2.6 weeks of demand in 2035"),
            lambda b: b["reasons"][0].update(title="Synthetic demand revised by 7.4 percent"),
            # A view that cites nothing is refused by ruling R15 (test_thesis_rulings.CitesSomethingTests).
            lambda b: b["exposure"]["moved"][2]["how"].update(text="Synthetic reading: about 505 USD, 1.1 percent."),
            lambda b: b["conditions"][0].update(text="Synthetic: above 29500 kt, or 29,500 kt as printed."),
        ]
        for number, change in enumerate(accepted):
            with self.subTest(accepted=number):
                self.accepted(change)

    def test_a_computed_gap_needs_one_source_basis_scenario_and_unit(self):
        for field, value in [("source", "usgs-2026"), ("basis", "Synthetic refined"), ("scenario", "Synthetic APS"),
                             ("unit", "mt")]:
            with self.subTest(field=field):  # change one figure of the computed table -> refused
                self.refused(lambda b: figure(b, "iea26-other-2025").update({field: value}))
        for field, value in [("source", "iea-2025"), ("basis", "Synthetic refined"), ("scenario", "Synthetic APS"),
                             ("unit", "million_t")]:
            with self.subTest(table_rule=field):  # each change is a valid figure; only the table rule refuses it
                message = self.refused(lambda b: figure(b, "iea26-other-2025").update({field: value}),
                                       "balance.tables[balance-steps]")
                self.assertIn(f"one {field}", message)
        self.refused(lambda b: b["balance"]["tables"][0].update(why_not="Synthetic: not needed."),
                     "balance.tables[balance-steps].why_not")
        self.refused(lambda b: b["balance"]["tables"][1].update(why_not=None),
                     "balance.tables[balance-side-by-side].why_not")
        self.refused(lambda b: b["balance"]["tables"][1].update(gap="computed", why_not=None),
                     "balance.tables[balance-side-by-side]")

    def test_balance_rows_keep_their_years_kinds_and_totals(self):
        cases = [
            (lambda b: b["balance"]["tables"][0]["rows"].reverse(), "balance.tables[balance-steps].rows[1].year"),
            (lambda b: b["balance"]["tables"][1]["rows"][0].update(kind="projection"),
             "balance.tables[balance-side-by-side].rows[0]"),  # a projection row with a figure without a scenario
            (lambda b: b["balance"]["tables"][0]["rows"][0].update(kind="estimate"),
             "balance.tables[balance-steps].rows[0].kind"),
            (lambda b: b["balance"]["tables"][0]["rows"][0].update(year="2030"),
             "balance.tables[balance-steps].rows[0]"),  # its figures are of 2025
            (lambda b: b["balance"]["tables"][0]["rows"][0].update(supply_total="iea26-demand-2025"),
             "balance.tables[balance-steps].rows[0]"),  # one figure twice
            (lambda b: figure(b, "iea26-demand-2025").update(value="0", as_shown="0"),
             "balance.tables[balance-steps].rows[0].demand_total"),
            (lambda b: figure(b, "iea26-demand-2025").update(value="-26500", as_shown="-26,500"),
             "balance.tables[balance-steps].rows[0].demand_total"),
            (lambda b: b["balance"]["tables"][0]["rows"][0].update(demand_total="absent"),
             "balance.tables[balance-steps].rows[0].demand_total"),
            (lambda b: b["balance"].update(tables=[]), "balance.tables"),
            (lambda b: b["balance"]["tables"][1].update(id="balance-steps"), "balance.tables[1].id"),
            (lambda b: b["balance"]["tables"][0].update(gap="estimated"), "balance.tables[balance-steps].gap"),
        ]
        for change, where in cases:
            with self.subTest(where=where):
                self.refused(change, where)
        # A negative figure (a deficit as published, say) is a value like any other; only demand must be positive.
        self.accepted(lambda b: figure(b, "usgs26-refinery-2024").update(value="-400", as_shown="-400"))

    def test_reason_editions_must_be_one_series_in_order(self):
        def sources(body):
            return {entry["id"]: entry for entry in body["sources"]}

        def swap_dates(body):
            new, old = sources(body)["iea-2026"], sources(body)["iea-2025"]
            new["edition_date"], old["edition_date"] = old["edition_date"], new["edition_date"]
        # One year in one edition, as a revision: R12 refuses it, since it would compare a figure with itself.
        self.assertIn(ONE_EDITION, self.refused(lambda b: figure(b, "iea25-clean-2030").update(source="iea-2026"),
                                                "reasons[clean-tech-demand].measure.compare"))
        cases = [
            ("swapped dates", swap_dates),
            ("other series", lambda b: sources(b)["iea-2025"].update(series="synthetic-other-series")),
            ("other measure", lambda b: figure(b, "iea25-clean-2030").update(measure="Synthetic other measure")),
            ("other unit", lambda b: figure(b, "iea25-clean-2030").update(unit="t")),
            ("other basis", lambda b: figure(b, "iea25-clean-2030").update(basis="Synthetic refined")),
            ("other scenario", lambda b: figure(b, "iea25-clean-2030").update(scenario="Synthetic APS")),
            ("one figure twice", lambda b: b["reasons"][0]["measure"].update(previous="iea26-clean-2030")),
        ]
        for case, change in cases:
            with self.subTest(case=case):
                self.refused(change, "reasons[clean-tech-demand].measure")
        self.refused(lambda b: b["reasons"][1]["measure"].update(compare="period"),
                     "reasons[mine-supply-slow].measure.compare")  # one year in two editions is a revision
        self.refused(lambda b: b["risks"][0]["measure"].update(compare="revision"),
                     "risks[mine-output-rising].measure.compare")  # a later year is a period comparison
        others = [
            (lambda b: b["reasons"][0]["measure"].update(material_change_pct="0"), "material_change_pct"),
            (lambda b: b["reasons"][0]["measure"].update(material_change_pct="-1"), "material_change_pct"),
            (lambda b: b["reasons"][0]["measure"].update(material_change_pct=5), "material_change_pct"),
            (lambda b: b["reasons"][0]["measure"].update(supports_when="up"), "supports_when"),
            (lambda b: b["reasons"][0]["measure"].update(compare="edition"), "compare"),
        ]
        for change, field in others:
            with self.subTest(field=field):
                self.refused(change, f"reasons[clean-tech-demand].measure.{field}")
        for count in (2, 6):
            with self.subTest(reasons=count):
                def resize(body, count=count):
                    extra = [dict(body["reasons"][0], id=f"synthetic-extra-{n}") for n in range(3)]
                    body["reasons"] = (body["reasons"] + extra)[:count]
                self.refused(resize, "reasons")
        self.refused(lambda b: b["reasons"][0].update(measure=None), "reasons[clean-tech-demand].measure")
        self.refused(lambda b: b.update(risks=[]), "risks")
        self.refused(lambda b: b["risks"][0]["measure"].update(supports_when="higher"),
                     "risks[mine-output-rising].measure")

    # Ruling R12 (two years within one edition) and year order: tests/test_thesis_measures.py.

    def test_a_zero_previous_value_is_refused(self):
        message = self.refused(lambda b: figure(b, "iea25-clean-2030").update(value="0", as_shown="0"),
                               "reasons[clean-tech-demand].measure.previous")
        self.assertIn("0", message)
        self.refused(lambda b: figure(b, "iea25-primary-2035").update(value="0.00", as_shown="0.00"),
                     "risks[primary-supply-projections].measure.previous")
        # A negative previous value is a value: the change divides by its magnitude.
        def negative(body):
            figure(body, "iea25-primary-2035").update(value="-400", as_shown="-400")
            body["risks"][1]["statement"].update(text="Synthetic reading: the newer edition puts primary supply in "
                                                      "2035 at 24,600 kt, against -400 kt in the earlier edition.")
        self.accepted(negative)

    def test_plain_notes_and_log_entries_state_no_figures(self):
        cases = [
            (lambda b: b["plain"].update(view="Synthetic: the view reads the 2030 balance."), "plain.view"),
            (lambda b: b["plain"].update(price="Synthetic: a record of 2 months."), "plain.price"),
            (lambda b: b["reasons"][0].update(plain="Synthetic: demand grows by 7 percent."),
             "reasons[clean-tech-demand].plain"),
            (lambda b: b["risks"][2].update(plain="Synthetic: since 2025."), "risks[construction-slowdown].plain"),
            (lambda b: b["log"][0].update(text="Synthetic: opened with 3 reasons."), "log[0].text"),
        ]
        for change, where in cases:
            with self.subTest(where=where):
                self.refused(change, where)
        self.refused(lambda b: b["plain"].pop("price"), "plain")
        self.refused(lambda b: b["plain"].update(extra="Synthetic"), "plain")

    def test_price_phrasing_is_allowed_only_in_not_claimed(self):
        phrase = "Synthetic: copper prices will rise."
        places = [
            (lambda b, p: b["view"].update(text=p), "view.text"),
            (lambda b, p: b.update(title=p), "title"),
            (lambda b, p: b["reasons"][0].update(title=p), "reasons[clean-tech-demand].title"),
            (lambda b, p: b["risks"][0]["statement"].update(text=p), "risks[mine-output-rising].statement.text"),
            (lambda b, p: b["plain"].update(price=p), "plain.price"),
            (lambda b, p: b["log"][0].update(text=p), "log[0].text"),
            (lambda b, p: b["conditions"][0].update(text=p), "conditions[supply-above].text"),
            (lambda b, p: b["differs"][0]["others"][0].update(label=p), "differs[differs-earlier-edition].others[0]"),
            (lambda b, p: b["exposure"]["movers"][0].update(through=p), "exposure.movers[0].through"),
            (lambda b, p: b["balance"]["tables"][1].update(why_not=p), "balance.tables[balance-side-by-side].why_not"),
            (lambda b, p: b["confidence"].update(basis=p), "confidence.basis"),
            (lambda b, p: figure(b, "usgs26-mine-2024").update(measure=p), "figures[usgs26-mine-2024].measure"),
        ]
        for words in (phrase, "Synthetic: this confirms the view."):
            for change, where in places:
                with self.subTest(words=words, where=where):
                    self.refused(lambda b, change=change, words=words: change(b, words), where)
            loaded = self.accepted(lambda b, words=words: b["not_claimed"].append(words))
            self.assertEqual(loaded["not_claimed"][-1], words)
        # Naming whose expectation a cited figure is may say "forecast"; no other claim word passes.
        self.accepted(lambda b: b["differs"][0]["others"][0].update(label="Synthetic World Bank forecast"))
        self.refused(lambda b: b["differs"][0]["others"][0].update(label="Synthetic World Bank signal"),
                     "differs[differs-earlier-edition].others[0].label")

    def test_sources_figures_and_passages_keep_their_shapes(self):
        def source(body, source_id):
            return find(body["sources"], source_id)
        cases = [
            (lambda b: source(b, "worldbank").update(url="http://example.org/synthetic/pink.xlsx"),
             "sources[worldbank].url"),
            (lambda b: source(b, "worldbank").update(url="https://someone@example.org/x"), "sources[worldbank].url"),
            (lambda b: source(b, "usgs-2025").update(id="usgs-2026"), "sources[1].id"),
            (lambda b: source(b, "usgs-2025").update(id="USGS-2025"), "sources[1].id"),
            (lambda b: source(b, "usgs-2025").update(kind="docx"), "sources[usgs-2025].kind"),
            (lambda b: source(b, "usgs-2025").update(origin="post"), "sources[usgs-2025].origin"),
            (lambda b: source(b, "usgs-2025").update(transcription={"pages": [1], "method": "transcribed from the "
                                                                                           "page image"}),
             "sources[usgs-2025].transcription"),
            (lambda b: source(b, "iea-2021").update(transcription=None), "sources[iea-2021].transcription"),
            (lambda b: source(b, "iea-2021")["transcription"].update(method="read by a library"),
             "sources[iea-2021].transcription.method"),
            (lambda b: source(b, "usgs-2025").update(bytes=0), "sources[usgs-2025].bytes"),
            (lambda b: source(b, "usgs-2025").update(bytes=True), "sources[usgs-2025].bytes"),
            (lambda b: source(b, "usgs-2025").update(attempt=0), "sources[usgs-2025].attempt"),
            (lambda b: source(b, "usgs-2025").update(sha256="A" * 64), "sources[usgs-2025].sha256"),
            (lambda b: source(b, "usgs-2025").update(retrieved_at="2026-11-02T09:02:00"),
             "sources[usgs-2025].retrieved_at"),
            (lambda b: source(b, "usgs-2025").update(retrieved_at="2026-11-03T09:02:00+00:00"),
             "sources[usgs-2025].retrieved_at"),  # after the day the version was prepared
            (lambda b: source(b, "usgs-2025").update(edition_date="2025-13-01"), "sources[usgs-2025].edition_date"),
            (lambda b: source(b, "usgs-2025").update(folder="../usgs-2025"), "sources[usgs-2025].folder"),
            (lambda b: source(b, "usgs-2025").update(name="a/copper.csv"), "sources[usgs-2025].name"),
            (lambda b: source(b, "usgs-2025").update(name=".."), "sources[usgs-2025].name"),
            (lambda b: source(b, "usgs-2025").update(approval_id="Synthetic approval"),
             "sources[usgs-2025].approval_id"),
            (lambda b: source(b, "usgs-2025").update(folder="usgs-2026"), "sources"),  # one retained file twice
            (lambda b: source(b, "usgs-2025").update(attempt=1), "sources"),  # one acquisition attempt twice
            (lambda b: source(b, "usgs-2025")["terms"].update(licence=""), "sources[usgs-2025].terms.licence"),
            (lambda b: b.update(sources=[]), "sources"),
            (lambda b: figure(b, "usgs26-mine-2024").update(source="absent"), "figures[usgs26-mine-2024].source"),
            (lambda b: figure(b, "usgs26-mine-2024").update(unit="mt"), "figures[usgs26-mine-2024].unit"),
            (lambda b: figure(b, "usgs26-mine-2024").update(year="24"), "figures[usgs26-mine-2024].year"),
            (lambda b: figure(b, "wb-copper-2026m10").update(period="2025M10"), "figures[wb-copper-2026m10].period"),
            (lambda b: figure(b, "wb-copper-2026m10").update(period="2026M13"), "figures[wb-copper-2026m10].period"),
            (lambda b: figure(b, "usgs26-mine-2025").update(id="usgs26-mine-2024"), "figures[25].id"),
            (lambda b: b["passages"][0].update(id="usgs26-mine-2024"), "passages[0].id"),  # one namespace
            (lambda b: b["view"].update(cites=["absent"]), "view.cites"),
            (lambda b: b["view"].update(cites=["iea26-demand-2030", "iea26-demand-2030"]), "view.cites"),
            (lambda b: b["view"].update(cites=[]), "view.cites"),
            (lambda b: b["view"].update(status="not_stated"), "view.cites"),
            (lambda b: b["view"].update(status="claimed"), "view.status"),
            (lambda b: b.update(id="copper"), "id"),
            (lambda b: b.update(version=2), "version"),
            (lambda b: b.update(previous_version=0), "previous_version"),
            (lambda b: b.update(thesis_version="thesis-0.2"), "thesis_version"),
            (lambda b: b.update(prepared_on="2026-11-01"), "prepared_on"),
            (lambda b: b.update(opened_on="2026-11-31"), "opened_on"),
            (lambda b: b["confidence"].update(level="certain"), "confidence.level"),
            (lambda b: b["provenance"].update(ai_assisted="true"), "provenance.ai_assisted"),
            (lambda b: b["provenance"].update(human_review="reviewed"), "provenance.human_review"),
            (lambda b: b.update(not_claimed=[]), "not_claimed"),
            (lambda b: b["not_claimed"].append("Synthetic\nsecond line"), "not_claimed[3]"),
        ]
        for change, where in cases:
            with self.subTest(where=where):
                self.refused(change, where)

    def test_a_pdf_transcription_names_exactly_the_pages_it_cites(self):
        # Ruling R6: a PDF source's transcription lists, ascending and once each, exactly the pages its figures and
        # passages cite, so the sources footer never names a page the thesis does not use (or misses one it does).
        where = "sources[iea-2021].transcription.pages"

        def transcribed(*pages, **extra):
            return lambda body: find(body["sources"], "iea-2021").update(
                transcription={"pages": list(pages), "method": thesis_schema.TRANSCRIBED, **extra})
        cited = sorted({item["locator"]["page"] for item in self.v1["figures"] + self.v1["passages"]
                        if item["source"] == "iea-2021"})
        self.assertEqual(cited, [1, 2])  # the figure on page 1, the passage on page 2
        for version in (self.v1, self.v2):  # the corrected fixture
            self.assertEqual(find(version["sources"], "iea-2021")["transcription"],
                             {"pages": [1, 2], "method": "transcribed from the page image"})
        self.assertEqual(self.load(2), self.v2)
        mismatched = [("a cited page missing", transcribed(1)), ("the other cited page missing", transcribed(2)),
                      ("a page nothing cites", transcribed(1, 2, 3))]
        for case, change in mismatched:
            with self.subTest(case=case):
                self.assertIn("expected exactly the pages its figures and passages cite: [1, 2]",
                              self.refused(change, where))
        malformed = [("unsorted", transcribed(2, 1)), ("duplicated", transcribed(1, 1, 2)), ("no pages", transcribed()),
                     ("page zero", transcribed(0, 1, 2)), ("a page as text", transcribed("1", 2)),
                     ("a page as true", transcribed(True, 2)), ("a page as a fraction", transcribed(1.0, 2)),
                     ("pages not a list", lambda body: find(body["sources"], "iea-2021")["transcription"].update(
                         pages="1, 2"))]
        for case, change in malformed:
            with self.subTest(case=case):
                self.assertIn("ascending, each once", self.refused(change, where))

        def old_shape(body):
            find(body["sources"], "iea-2021").update(transcription={"page": 1, "method": thesis_schema.TRANSCRIBED})
        for case, change in (("the old shape", old_shape), ("a page key beside the pages", transcribed(1, 2, page=1))):
            with self.subTest(case=case):
                self.assertIn("expected exactly the fields", self.refused(change, "sources[iea-2021].transcription"))
        # The pages follow what is cited: the passage moved to page 3 needs pages [1, 3].
        def moved(body):
            find(body["passages"], "iea21-construction")["locator"].update(page=3)
        self.assertIn("cite: [1, 3]", self.refused(moved, where))
        self.assertEqual(find(self.accepted(lambda body: (moved(body), transcribed(1, 3)(body)))["sources"],
                              "iea-2021")["transcription"]["pages"], [1, 3])

    def test_locators_are_checked_at_load(self):
        def locator(figure_id, **values):
            return lambda body: figure(body, figure_id)["locator"].update(values)
        cases = [
            (locator("maker-price-2025", quote="$45,000"), "figures[maker-price-2025].locator.quote"),  # too short
            (locator("maker-price-2025", quote="<p>was $45,000 in 2025.</p>"),
             "figures[maker-price-2025].locator.quote"),
            (locator("maker-price-2025", quote="| was $45,000 in 2025 |"), "figures[maker-price-2025].locator.quote"),
            (locator("maker-price-2025", quote="# was $45,000 in 2025."), "figures[maker-price-2025].locator.quote"),
            (locator("maker-price-2025", quote="was $45,000 " + "x" * 320), "figures[maker-price-2025].locator.quote"),
            (locator("maker-price-2025", paragraph=0), "figures[maker-price-2025].locator.paragraph"),
            (locator("maker-price-2025", paragraph="3"), "figures[maker-price-2025].locator.paragraph"),
            (locator("iea21-ev-copper", page=0), "figures[iea21-ev-copper].locator.page"),
            (locator("usgs26-mine-2024", row=1), "figures[usgs26-mine-2024].locator.row"),
            (locator("usgs26-mine-2024", label_column="World mine production (kt)"),
             "figures[usgs26-mine-2024].locator.label_column"),
            (locator("iea26-demand-2025", cell="d5"), "figures[iea26-demand-2025].locator.cell"),
            (locator("iea26-demand-2025", label_cell="D5"), "figures[iea26-demand-2025].locator.label_cell"),
            (locator("iea26-demand-2025", sheet=""), "figures[iea26-demand-2025].locator.sheet"),
            # The locator's kind must be its source's: an xlsx locator on a csv source, a page on an html source.
            (lambda b: figure(b, "iea26-demand-2025").update(source="usgs-2026"), "figures[iea26-demand-2025].locator"),
            (lambda b: figure(b, "maker-price-2025").update(locator={"page": 3, "quote": "was $45,000 in 2025."}),
             "figures[maker-price-2025].locator"),
            # Passages quote an HTML page or a PDF only.
            (lambda b: b["passages"][0].update(source="usgs-2026", locator={"row": 2, "column": "Year",
                                                                            "label_column": "Source", "label": "x"}),
             "passages[producer-sales-2025].source"),
            (lambda b: b["passages"][0]["locator"].update(quote="sales"),
             "passages[producer-sales-2025].locator.quote"),
        ]
        for change, where in cases:
            with self.subTest(where=where):
                self.refused(change, where)

    def test_sections_keep_their_rules(self):
        cases = [
            (lambda b: b["differs"][0].update(differs="true"), "differs[differs-earlier-edition].differs"),
            (lambda b: b["differs"][0].update(others=[]), "differs[differs-earlier-edition].others"),
            (lambda b: b.update(differs=[]), "differs"),
            (lambda b: b["differs"][0]["others"][1].update(cite="iea25-supply-2030"),
             "differs[differs-earlier-edition].others"),
            (lambda b: b.update(conditions=[]), "conditions"),
            (lambda b: b["conditions"][0].update(comparator="equal"), "conditions[supply-above].comparator"),
            (lambda b: b["conditions"][0].update(threshold="29,500"), "conditions[supply-above].threshold"),
            (lambda b: b["conditions"][0].update(id="mine-supply-slow"), "conditions[0].id"),  # ids are distinct
            (lambda b: b["exposure"]["movers"][0].update(moves="mine-output-rising"), "exposure.movers[0].moves"),
            (lambda b: b["exposure"]["movers"][0].update(cites=[]), "exposure.movers[0].cites"),
            (lambda b: b["exposure"].update(movers=[]), "exposure.movers"),
            (lambda b: b["exposure"]["moved"][0].update(side="investor"), "exposure.moved[0].side"),
            (lambda b: b["exposure"]["moved"][0]["amount"].update(kind="estimated"), "exposure.moved[0].amount.kind"),
            (lambda b: b["exposure"]["moved"][2]["amount"].update(per_unit="wb-copper-2026m10",
                                                                  price="iea21-ev-copper"),
             "exposure.moved[2].amount.per_unit"),
            (lambda b: b["exposure"]["moved"][2]["amount"].update(unit_price="maker-purchases-2025"),
             "exposure.moved[2].amount.unit_price"),
            (lambda b: b["exposure"]["moved"][0].update(company=""), "exposure.moved[0].company"),
            (lambda b: b["log"][0].update(kind="note"), "log[0].kind"),
            (lambda b: b["log"][0].update(date="2026-11-01"), "log[0].date"),
            (lambda b: b["log"].append(dict(b["log"][0])), "log[1].kind"),  # only the first entry is the opening
            (lambda b: b["log"].append({"date": "2026-11-02", "kind": "status", "text": "Synthetic: a status.",
                                        "refs": []}), "log[1].refs"),
            (lambda b: b["log"].append({"date": "2026-11-02", "kind": "note", "text": "Synthetic: a note.",
                                        "refs": ["supply-above"]}), "log[1].refs"),  # a condition, not a reason or risk
            (lambda b: b["log"].append({"date": "2026-11-03", "kind": "note", "text": "Synthetic: a note.",
                                        "refs": []}), "log[1].date"),  # after the day the version was prepared
            (lambda b: b["log"].append({"date": "2026-11-02", "kind": "verdict", "text": "Synthetic: a note.",
                                        "refs": []}), "log[1].kind"),
            (lambda b: b["price_record"].update(opening="wb-copper-2026m10", latest="wb-copper-2026m08"),
             "price_record"),
            (lambda b: b["price_record"].update(opening="maker-price-2025"), "price_record.opening"),
            (lambda b: figure(b, "wb-copper-2026m08").update(period=None), "price_record"),
            (lambda b: figure(b, "wb-copper-2026m08").update(source="iea-2026"), "price_record"),  # two sources
            (lambda b: figure(b, "wb-copper-2026m10").update(value="0", as_shown="0"), "exposure.moved[2].amount"),
            (lambda b: b["price_record"].update(series=""), "price_record.series"),
            (lambda b: b["figures"].append(dict(figure(b, "iea26-demand-2030"), id="synthetic-unused")), "figures"),
            (lambda b: b["passages"].append(dict(b["passages"][0], id="synthetic-unused")), "passages"),
        ]
        for change, where in cases:
            with self.subTest(where=where):
                self.refused(change, where)

        def unused_source(body):
            body["sources"].append(dict(find(body["sources"], "usgs-2025"), id="synthetic-unused", folder="unused",
                                        attempt=99))
        self.refused(unused_source, "sources")
        self.accepted(lambda b: b["exposure"]["moved"][2]["amount"].update(unit_price=None))
        self.accepted(lambda b: (b["price_record"].update(opening="wb-copper-2026m10"),  # opened in the latest month
                                 b["figures"].remove(figure(b, "wb-copper-2026m08"))))
        self.accepted(lambda b: b["differs"][0].update(differs=False))


class FileTests(Theses):
    def test_a_crlf_checkout_still_matches_its_index_hash(self):
        path = self.content / thesis_fakes.THESIS_ID / "v1.json"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(thesis_schema.load_version(thesis_fakes.THESIS_ID, 1, self.content)["version"], 1)
        index = self.content / ID / "index.json"
        index.write_bytes(index.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.load(2)["version"], 2)

    def test_a_changed_version_file_no_longer_matches_its_index(self):
        path = self.content / ID / "v1.json"
        raw = path.read_bytes()
        edited = raw.replace(b"so the physical balance runs short", b"so the physical balance runs thin", 1)
        self.assertNotEqual(edited, raw)
        path.write_bytes(edited)
        for version in (1, 2):  # version 2's chain holds version 1, so both are refused
            with self.subTest(version=version):
                with self.assertRaises(ThesisRefused) as caught:
                    self.load(version)
                self.assertEqual(caught.exception.status, 500)
                self.assertIn("(v1.json: does not match the SHA-256 its index records", str(caught.exception))
        # The edited text is itself valid: only the hash refuses it.
        self.write([thesis_fakes.changed(self.v1, lambda b: b["view"].update(
            text=b["view"]["text"].replace("runs short", "runs thin")))])
        self.assertEqual(self.load(1)["version"], 1)

    def test_the_files_are_strict_json_within_their_size(self):
        path = self.content / ID / "v1.json"
        for case, data in (("repeated key", b'{"id": "a", "id": "b"}'), ("not utf-8", b'{"id": "caf\xe9"}'),
                           ("byte-order mark", b"\xef\xbb\xbf" + path.read_bytes()), ("NaN", b'{"id": NaN}')):
            with self.subTest(case=case):
                path.write_bytes(data)
                with self.assertRaises(ThesisRefused) as caught:
                    self.load(1)
                self.assertEqual(caught.exception.status, 500)
        self.write([self.v1, self.v2])
        with patch.object(thesis_schema, "MAX_FILE_BYTES", path.stat().st_size - 1):
            with self.assertRaisesRegex(ThesisRefused, "larger than a thesis file may be"):
                self.load(1)
        (self.content / ID / "v2.json").unlink()
        with self.assertRaisesRegex(ThesisRefused, r"\(v2.json: the index names a version file that is not there"):
            self.load(2)

    def test_version_two_must_extend_the_log_without_rewriting_it(self):
        self.refused_v2(lambda b: b["log"][0].update(text="Synthetic: the thesis opened, rewritten."), "log")
        self.refused_v2(lambda b: b["log"][0].update(refs=["clean-tech-demand"]), "log")
        self.refused_v2(lambda b: b.update(log=b["log"][:1], confidence=dict(b["confidence"], level="medium")), "log")
        # Dropping an earlier entry: version 1 with an opening and a note, version 2 without the note.
        note = {"date": "2026-11-02", "kind": "note", "text": "Synthetic: an early note.", "refs": []}
        v1 = thesis_fakes.changed(self.v1, lambda b: b["log"].append(note))
        v2 = thesis_fakes.changed(self.v2, lambda b: None)
        self.write([v1, thesis_fakes.changed(v2, lambda b: b["log"].insert(1, dict(note)))])
        self.assertEqual(self.load(2)["log"][1], note)  # the kept prefix loads
        self.assertIn("(log", self.refusal([v1, v2]))
        # A new entry dated before version 1 was published.
        self.refused_v2(lambda b: None, "log[1].date", published=["2026-11-20", None])
        self.refused_v2(lambda b: b.update(opened_on="2026-11-01") or b["log"][0].update(date="2026-11-01"),
                        "opened_on")
        self.refused_v2(lambda b: b.update(previous_version=None), "previous_version")

    def test_a_changed_view_or_confidence_needs_its_log_entry(self):
        self.refused_v2(lambda b: b["log"].pop(), "log")  # confidence raised, its entry dropped
        changed_view = ("Synthetic reading: in the Synthetic STEPS projection, demand of 29,500 kt in 2030 exceeds "
                        "supply.")
        self.refused_v2(lambda b: b["view"].update(text=changed_view), "log")
        view_entry = {"date": thesis_fakes.V2_ON, "kind": "view", "text": "Synthetic: the view was reworded.",
                      "refs": []}
        self.write([self.v1, thesis_fakes.changed(self.v2, lambda b: (b["view"].update(text=changed_view),
                                                                      b["log"].append(view_entry)))])
        self.assertEqual(self.load(2)["view"]["text"], changed_view)
        # A changed basis with the same level needs no confidence entry.
        self.write([self.v1, thesis_fakes.changed(self.v2, lambda b: b.update(confidence=dict(
            self.v1["confidence"], basis="Synthetic: read again, with the same level.")) or b["log"].pop())])
        self.assertEqual(self.load(2)["confidence"]["level"], "medium")

    def test_only_the_last_version_may_be_a_draft(self):
        for published in ([None, "2026-11-16"], [None, None], ["2026-11-20", "2026-11-16"]):
            with self.subTest(published=published):
                self.write([self.v1, self.v2], published)
                with self.assertRaises(ThesisRefused) as caught:
                    thesis_schema.load_index(ID, self.content)
                self.assertEqual(caught.exception.status, 500)
                self.assertIn("(index.versions[", str(caught.exception))
        for published in (["2026-11-02", None], ["2026-11-02", "2026-11-16"], ["2026-11-16", "2026-11-16"]):
            with self.subTest(published=published):
                self.write([self.v1, self.v2], published)
                self.assertEqual(self.load(2)["version"], 2)
        # A version cannot be published before the day it was prepared.
        self.refusal([self.v1, self.v2], ["2026-11-02", "2026-11-15"], "index.versions[1].published_on")
        self.refusal([self.v1], ["2026-11-01"], "index.versions[0].published_on")
        index_path = self.content / ID / "index.json"
        for change, where in ((lambda i: i["versions"][1].update(version=3), "index.versions[1].version"),
                              (lambda i: i["versions"][1].update(file="v3.json"), "index.versions[1].file"),
                              (lambda i: i["versions"][1].update(published_on="16 November 2026"),
                               "index.versions[1].published_on"),
                              (lambda i: i["versions"][1].update(sha256="F" * 64), "index.versions[1].sha256"),
                              (lambda i: i.update(versions=[]), "index.versions"),
                              (lambda i: i.update(id="copper"), "index.id"),
                              (lambda i: i.update(index_version="thesis-index-0.2"), "index.index_version")):
            with self.subTest(where=where):
                self.write([self.v1, self.v2])
                index = json.loads(index_path.read_text(encoding="utf-8"))
                change(index)
                index_path.write_text(json.dumps(index), encoding="utf-8")
                with self.assertRaises(ThesisRefused) as caught:
                    thesis_schema.load_index(ID, self.content)
                self.assertEqual(caught.exception.status, 500)
                self.assertIn(f"({where}", str(caught.exception))

    def test_unknown_and_malformed_ids_and_versions_are_not_found(self):
        for thesis_id in ("../x", "Copper", "", "synthetic copper", "copper", "synthetic-copper/", None, 5):
            with self.subTest(thesis_id=thesis_id):
                for load in (lambda: thesis_schema.load_index(thesis_id, self.content),
                             lambda: thesis_schema.load_version(thesis_id, 1, self.content)):
                    with self.assertRaises(ThesisRefused) as caught:
                        load()
                    self.assertEqual((caught.exception.status, str(caught.exception)), (404, "No thesis has this id"))
        for version in (0, 3, -1, True, "1", 1.0, None):
            with self.subTest(version=version):
                with self.assertRaises(ThesisRefused) as caught:
                    self.load(version)
                self.assertEqual((caught.exception.status, str(caught.exception)),
                                 (404, "This thesis has no such version"))
        with self.assertRaises(ThesisRefused) as caught:
            thesis_schema.load_version(ID, 1, self.content / "absent")
        self.assertEqual(caught.exception.status, 404)


class CatalogTests(Theses):
    def test_the_catalog_reads_content_only(self):
        listed = {"id": ID, "title": self.v2["title"], "topic": self.v2["topic"], "latest_version": 2,
                  "published_on": None, "href": "/theses/synthetic-copper"}
        (self.content / "notes").mkdir()  # a folder without an index is not a thesis
        read = []

        def recording(path):
            read.append(Path(path))
            return READ_BYTES(path)
        failing = AssertionError("the catalog read a retained source")
        with patch.object(thesis_sources, "verify", side_effect=failing), \
                patch.object(thesis_sources, "content", side_effect=failing), \
                patch.object(thesis_sources, "locate", side_effect=failing), \
                patch.object(Path, "read_bytes", autospec=True, side_effect=recording):
            catalog = thesis_schema.catalog(self.content)
        self.assertEqual(catalog, {"view_version": "thesis-catalog-0.1", "theses": [listed], "provider_called": False})
        self.assertTrue(read)
        self.assertTrue(all(path.is_relative_to(self.content) for path in read), read)  # never self.sources
        self.write([self.v1, self.v2], ["2026-11-02", "2026-11-16"])
        self.assertEqual(thesis_schema.catalog(self.content)["theses"], [dict(listed, published_on="2026-11-16")])
        self.assertEqual(thesis_schema.catalog(self.content / "absent")["theses"], [])

    def test_the_catalog_refuses_an_invalid_thesis(self):
        self.write([self.v1, thesis_fakes.changed(self.v2, lambda b: b["log"].pop())])
        with self.assertRaises(ThesisRefused) as caught:
            thesis_schema.catalog(self.content)
        self.assertEqual(caught.exception.status, 500)
        self.write([self.v1, self.v2])
        shutil.copytree(self.content / ID, self.content / "Copper")
        with self.assertRaises(ThesisRefused) as caught:
            thesis_schema.catalog(self.content)
        self.assertEqual(caught.exception.status, 500)


if __name__ == "__main__":
    unittest.main()
