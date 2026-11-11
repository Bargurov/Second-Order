"""FCX stage 2, the Scenarios tab's server (company_scenarios; POST /api/companies/fcx/scenario): the two calculations
on the company's Q4 2026 assumptions, exact; the input rules and units; a missing or changed source blocking what rests
on it, with the explanations that name it; access; and that nothing is written, stored or fetched.

The retained documents live under data/company-sources/fcx/, which Git ignores. Tests that need them are skipped where
they are absent. No test writes to the committed research folder or to data/: each change is made to a copy.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import account_fakes  # noqa: E402

from second_order import company_research_view as crv, company_scenarios as cs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "fcx"
DATA = ROOT / "data" / "company-sources" / "fcx"
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FIXTURES"
SOURCES = {s["id"]: s for s in json.loads((RESEARCH / "sources.json").read_text(encoding="utf-8"))["sources"]}
HAVE_DATA = all((DATA / s["folder"] / s["name"]).is_file() for s in SOURCES.values())
NEEDS_DATA = unittest.skipUnless(HAVE_DATA, "the retained FCX documents are not on this machine (data/ is private)")
FACTS = json.loads((RESEARCH / "facts.json").read_text(encoding="utf-8"))
BY_ID = {record["id"]: record for record in FACTS["records"]}
ROUTE = "/api/companies/fcx/scenario"
HEADERS = {"Origin": account_fakes.BASE, "x-second-order-scenario": "1", "Content-Type": "application/json"}


def pv(price: str, volume: str) -> dict:
    return {"mode": "price_volume", "price": price, "volume": volume}


def cf(price: str) -> dict:
    return {"mode": "cash_flow", "price": price}


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()}


def blocks(node, out=None) -> list[dict]:
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


def named_records(node, out=None) -> set:
    """Every record a part of the page names with a "record" key."""
    out = set() if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("record"), str):
            out.add(node["record"])
        for value in node.values():
            named_records(value, out)
    elif isinstance(node, list):
        for item in node:
            named_records(item, out)
    return out


class Copies(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-scenarios-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def data_without(self, sid: str) -> Path:
        target = self.root / "data"
        shutil.copytree(DATA, target)
        source = SOURCES[sid]
        (target / source["folder"] / source["name"]).unlink()
        return target

    def data_changed(self, sid: str) -> Path:
        target = self.root / "data"
        shutil.copytree(DATA, target)
        source = SOURCES[sid]
        path = target / source["folder"] / source["name"]
        raw = bytearray(path.read_bytes())
        raw[100] ^= 1
        path.write_bytes(bytes(raw))
        return target

    def refused(self, body, sources: Path = DATA) -> cs.ScenarioRefused:
        with self.assertRaises(cs.ScenarioRefused) as caught:
            cs.compute(body, RESEARCH, sources)
        return caught.exception


class Records(unittest.TestCase):
    def test_the_base_is_the_company_assumptions_for_q4_2026_in_the_october_release(self):
        price, volume = BY_ID[cs.PRICE], BY_ID[cs.VOLUME]
        self.assertEqual((price["display"], price["unit"], price["source"], price["page"]),
                         ("6.50", "USD per pound", "release-2026q3", 10))
        self.assertIn("$6.50 per pound of copper", price["quote"])
        self.assertEqual((volume["display"], volume["unit"], volume["source"]), ("875", "million pounds", "release-2026q3"))
        for record in (price, volume):
            self.assertEqual(record["period"]["label"], "Q4 2026 outlook (2026-10-27)", record["id"])
            self.assertEqual(record["kind"], "published", record["id"])

    def test_the_sensitivity_and_its_step_come_from_the_october_release_only(self):
        sensitivity, step = BY_ID[cs.SENSITIVITY], BY_ID[cs.STEP]
        self.assertEqual((sensitivity["display"], sensitivity["unit"], sensitivity["source"]),
                         ("75", "USD millions", "release-2026q3"))
        self.assertEqual((step["display"], step["unit"], step["source"], step["page"]),
                         ("0.10", "USD per pound", "release-2026q3", 10))
        self.assertIn("for each $0.10 per pound change in the average price of copper", step["quote"])
        used = {rid for ids in cs.USES.values() for rid in ids.values()}
        self.assertFalse(any(rid.startswith("k25-") or rid.startswith("q3-") for rid in used), used)
        self.assertNotIn(cs.VOLUME, cs.USES["cash_flow"].values(), "the cash flow calculation takes no volume")

    def test_the_base_sales_value_is_a_computed_record_on_the_two_assumptions(self):
        base = BY_ID["c-q4-cu-sales-value-base"]
        self.assertEqual((base["kind"], base["formula"], base["inputs"], base["value"]),
                         ("computed", "p * v", {"p": cs.PRICE, "v": cs.VOLUME}, 5687.5))
        self.assertEqual(base["unit"], "USD millions")
        self.assertIn("a-scenario-sales-value", base["assumptions"])

    def test_the_worked_example_takes_its_step_from_the_record_the_page_names(self):
        per_step = BY_ID["c-q4-copper-revenue-per-10c"]
        self.assertEqual((per_step["formula"], per_step["inputs"]), ("v * s", {"v": cs.VOLUME, "s": cs.STEP}))
        self.assertEqual(BY_ID[cs.STEP]["period"]["label"], BY_ID[cs.VOLUME]["period"]["label"])

    def test_the_cost_explanation_lists_no_item_that_could_read_as_the_gap(self):
        page = json.loads((RESEARCH / "page.json").read_text(encoding="utf-8"))["scenarios"]
        for block in page["price_volume"]["costs"]:
            for word in ("royalt", "tax"):
                self.assertNotIn(word, block["text"].lower(), block["text"])

    def test_page_json_names_exactly_the_records_each_calculation_uses(self):
        page = json.loads((RESEARCH / "page.json").read_text(encoding="utf-8"))["scenarios"]
        for mode, ids in cs.USES.items():
            self.assertEqual({item["record"] for item in page[mode]["base"]}, set(ids.values()), mode)


class Inputs(unittest.TestCase):
    def test_a_price_is_dollars_per_pound_to_the_cent(self):
        for text, value in (("6.50", "6.50"), ("6.5", "6.5"), ("0.01", "0.01"), ("12", "12"), ("100", "100"),
                            ("100.00", "100.00")):
            self.assertEqual(cs.price_of(text), Decimal(value), text)
        for bad in ("", "0", "0.00", "-1", "+6.50", "6.505", "1e2", "6,50", " 6.50", "6.50 ", "abc", "100.01", ".5",
                    "6.", 6.5, None, True, ["6.50"]):
            with self.assertRaises(cs.ScenarioRefused, msg=repr(bad)) as caught:
                cs.price_of(bad)
            self.assertEqual(caught.exception.status, 422)

    def test_a_price_far_too_high_is_refused_with_its_unit(self):
        for per_tonne in ("14330", "650", "101"):
            with self.assertRaises(cs.ScenarioRefused) as caught:
                cs.price_of(per_tonne)
            self.assertIn("per pound", str(caught.exception))
            self.assertIn("tonne", str(caught.exception))

    def test_a_volume_is_million_pounds_sold_with_one_decimal_at_most(self):
        for text in ("875", "875.5", "0.1", "5000", "1000"):
            self.assertEqual(cs.volume_of(text), Decimal(text), text)
        for bad in ("", "0", "0.0", "-5", "875.25", "5000.1", "875000", "1,000", "8e2", 875, None):
            with self.assertRaises(cs.ScenarioRefused, msg=repr(bad)) as caught:
                cs.volume_of(bad)
            self.assertEqual(caught.exception.status, 422)
            self.assertIn("million pounds", str(caught.exception))

    def test_a_request_holds_exactly_its_mode_fields(self):
        for body in ({"mode": "price_volume", "price": "6.50"}, {"mode": "cash_flow", "price": "6.50", "volume": "875"},
                     {"mode": "cash_flow"}, {"mode": "valuation", "price": "6.50"}, {"price": "6.50"},
                     {"mode": ["price_volume"], "price": "6.50"}, {"mode": {"cash_flow": 1}, "price": "6.50"},
                     {**pv("6.50", "875"), "label": "x"}, ["price_volume"], "price_volume", None):
            with self.assertRaises(cs.ScenarioRefused, msg=repr(body)) as caught:
                cs.request_of(body)
            self.assertEqual(caught.exception.status, 422)


@NEEDS_DATA
class Calculation(unittest.TestCase):
    def run_pv(self, price, volume):
        reply = cs.compute(pv(price, volume), RESEARCH, DATA)
        self.assertEqual(reply["inputs"], {"price": price, "volume": volume})
        return reply["result"]

    def run_cf(self, price):
        reply = cs.compute(cf(price), RESEARCH, DATA)
        self.assertEqual(reply["inputs"], {"price": price})
        return reply["result"]

    def test_the_base_unchanged(self):
        self.assertEqual(self.run_pv("6.50", "875"), {"value": "5687.5", "base": "5687.5", "change": "0",
                                                      "price_effect": "0", "volume_effect": "0"})
        self.assertEqual(self.run_cf("6.50"), {"price_change": "0", "steps": "0", "change": "0"})

    def test_a_higher_price(self):
        self.assertEqual(self.run_pv("6.60", "875"), {"value": "5775", "base": "5687.5", "change": "87.5",
                                                      "price_effect": "87.5", "volume_effect": "0"})
        self.assertEqual(self.run_cf("6.60"), {"price_change": "0.1", "steps": "1", "change": "75"})
        self.assertEqual(self.run_cf("7"), {"price_change": "0.5", "steps": "5", "change": "375"})

    def test_a_lower_price(self):
        self.assertEqual(self.run_pv("6.40", "875"), {"value": "5600", "base": "5687.5", "change": "-87.5",
                                                      "price_effect": "-87.5", "volume_effect": "0"})
        self.assertEqual(self.run_cf("6.40"), {"price_change": "-0.1", "steps": "-1", "change": "-75"})
        self.assertEqual(self.run_cf("6.37"), {"price_change": "-0.13", "steps": "-1.3", "change": "-97.5"})

    def test_a_volume_change(self):
        self.assertEqual(self.run_pv("6.50", "900"), {"value": "5850", "base": "5687.5", "change": "162.5",
                                                      "price_effect": "0", "volume_effect": "162.5"})
        self.assertEqual(self.run_pv("6.50", "850"), {"value": "5525", "base": "5687.5", "change": "-162.5",
                                                      "price_effect": "0", "volume_effect": "-162.5"})

    def test_price_and_volume_together_split_in_the_stated_order(self):
        # volume effect (900 - 875) x 6.50 = 162.5; price effect (6.60 - 6.50) x 900 = 90
        self.assertEqual(self.run_pv("6.60", "900"), {"value": "5940", "base": "5687.5", "change": "252.5",
                                                      "price_effect": "90", "volume_effect": "162.5"})

    def test_the_split_always_adds_up_exactly(self):
        for price in ("0.01", "3.17", "6.49", "6.51", "9.99", "100"):
            for volume in ("0.1", "613.7", "875", "1234.5", "5000"):
                result = self.run_pv(price, volume)
                parts = Decimal(result["price_effect"]) + Decimal(result["volume_effect"])
                self.assertEqual(parts, Decimal(result["change"]), (price, volume))
                self.assertEqual(Decimal(result["value"]), Decimal(price) * Decimal(volume), (price, volume))
                self.assertEqual(Decimal(result["value"]) - Decimal(result["base"]), Decimal(result["change"]))
                for text in result.values():
                    self.assertNotIn("E", text)
                    self.assertLessEqual(len(text.partition(".")[2]), 3, (price, volume, text))

    def test_the_worked_example_gives_two_different_measures(self):
        self.assertEqual(self.run_pv("6.60", "875")["change"], "87.5")
        self.assertEqual(self.run_cf("6.60")["change"], "75")
        self.assertEqual(BY_ID["c-q4-copper-revenue-per-10c"]["value"], 87.5)

    def test_a_reply_names_its_records_and_stores_nothing(self):
        reply = cs.compute(pv("6.60", "875"), RESEARCH, DATA)
        self.assertEqual(reply["view_version"], cs.SCENARIO_VERSION)
        self.assertEqual(reply["mode"], "price_volume")
        self.assertEqual(reply["uses"], {"price": {"record": cs.PRICE, "value": "6.5"},
                                         "volume": {"record": cs.VOLUME, "value": "875"}})
        self.assertEqual((reply["unit"], reply["rests_on"], reply["stored"], reply["provider_called"]),
                         ("USD millions", ["release-2026q3"], False, False))
        flow = cs.compute(cf("6.60"), RESEARCH, DATA)
        self.assertEqual(flow["uses"], {"price": {"record": cs.PRICE, "value": "6.5"},
                                        "sensitivity": {"record": cs.SENSITIVITY, "value": "75"},
                                        "step": {"record": cs.STEP, "value": "0.1"}})

    def test_bad_inputs_are_refused_before_any_record_is_read(self):
        for body in (pv("6.505", "875"), pv("6.50", "-1"), cf("14330"), {"mode": "cash_flow", "price": 6.6}):
            with self.assertRaises(cs.ScenarioRefused) as caught:
                cs.compute(body, RESEARCH, Path(tempfile.gettempdir()) / "no-such-folder-for-scenarios")
            self.assertEqual(caught.exception.status, 422, body)


@NEEDS_DATA
class Blocked(Copies):
    def test_a_missing_release_blocks_both_calculations_naming_the_document_not_a_value(self):
        data = self.data_without("release-2026q3")
        for body in (pv("6.60", "875"), cf("6.60")):
            refusal = self.refused(body, data)
            self.assertEqual(refusal.status, 409)
            self.assertIn("results release", str(refusal))
            self.assertIn("missing", str(refusal))
            for value in ("6.5", "875", "75", "0.1"):
                self.assertNotIn(value, str(refusal).replace("2026", ""))

    def test_a_changed_release_blocks_both_calculations(self):
        data = self.data_changed("release-2026q3")
        for body in (pv("6.60", "875"), cf("6.60")):
            refusal = self.refused(body, data)
            self.assertEqual(refusal.status, 409)
            self.assertIn("changed", str(refusal))

    def test_a_document_neither_calculation_rests_on_blocks_nothing(self):
        for data in (self.data_changed("news-2026-11-04"),):
            self.assertEqual(cs.compute(cf("6.60"), RESEARCH, data)["result"]["change"], "75")
        shutil.rmtree(self.root / "data")
        data = self.data_without("10k-2025")
        self.assertEqual(cs.compute(pv("6.60", "875"), RESEARCH, data)["result"]["change"], "87.5")

    def test_with_the_release_missing_the_explanations_that_name_it_are_withheld(self):
        reply = crv.view(RESEARCH, self.data_without("release-2026q3"))
        scenarios = reply["page"]["scenarios"]
        for rid in named_records(scenarios):
            self.assertEqual(reply["records"][rid]["state"], "withheld", rid)
        found = blocks(scenarios)
        rests = {rid for rid, record in reply["records"].items() if "release-2026q3" in record.get("rests_on", [])}
        cited = {pid for pid, passage in reply["passages"].items() if passage["source"] == "release-2026q3"}
        names_release = [block for block in found if set(block["refs"]) & rests or set(block["passages"]) & cited]
        self.assertGreaterEqual(len(names_release), 3)
        for block in names_release:
            self.assertEqual(block["state"], "withheld", block["refs"])
            self.assertIsNone(block["segments"])
        text = json.dumps(scenarios, ensure_ascii=False)
        for value in ("6.50", "875", "$75"):
            self.assertNotIn(value, text)

    def test_with_the_release_missing_what_stays_fixed_is_withheld_with_it(self):
        scenarios = crv.view(RESEARCH, self.data_without("release-2026q3"))["page"]["scenarios"]
        for block in (scenarios["cash_flow"]["held"], scenarios["cash_flow"]["linear"],
                      scenarios["cash_flow"]["definition"], scenarios["cash_flow"]["versus"]):
            self.assertEqual(block["state"], "withheld", block["refs"] or block["passages"])

    def test_with_the_10k_missing_no_line_that_restates_it_is_sent(self):
        scenarios = crv.view(RESEARCH, self.data_without("10k-2025"))["page"]["scenarios"]
        found = blocks(scenarios)
        self.assertGreaterEqual(sum(1 for block in found if block["state"] == "withheld"), 3)
        for block in found:
            if block["state"] == "available":
                words = "".join(part.get("text", "") for part in block["segments"])
                self.assertNotIn("10-K", words, words)

    def test_with_the_release_changed_the_scenario_lines_send_no_words(self):
        reply = crv.view(RESEARCH, self.data_changed("release-2026q3"))
        for block in blocks(reply["page"]["scenarios"]):
            if block["refs"] or block["passages"]:
                if block["state"] == "withheld":
                    self.assertIsNone(block["segments"])


class Api(Copies):
    def setUp(self):
        super().setUp()
        self.accounts = account_fakes.World(self.root / "accounts")

    def client(self, user, sources: Path = DATA):
        return self.accounts.client(user, company_research_dir=RESEARCH, company_sources_dir=sources)

    def post(self, client, body, headers=None):
        return client.post(ROUTE, content=json.dumps(body), headers=HEADERS if headers is None else headers)

    def test_administrators_only(self):
        self.assertEqual(self.post(self.client(None), pv("6.60", "875")).status_code, 401)
        reader = self.post(self.client("reader-a"), pv("6.60", "875"))
        self.assertEqual(reader.status_code, 403)
        self.assertNotIn("5775", reader.text)

    def test_only_same_origin_json_with_the_action_header(self):
        client = self.client("admin")
        no_header = {key: value for key, value in HEADERS.items() if key != "x-second-order-scenario"}
        self.assertEqual(self.post(client, pv("6.60", "875"), no_header).status_code, 403)
        self.assertEqual(self.post(client, pv("6.60", "875"), {**HEADERS, "Origin": "http://elsewhere.test"}).status_code,
                         403)
        self.assertEqual(self.post(client, pv("6.60", "875"), {**HEADERS, "Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(client.post(ROUTE, content=b"{not json", headers=HEADERS).status_code, 400)
        self.assertEqual(client.post(ROUTE, content=b'{"mode": "cash_flow", "price": "6.60", "price": "7"}',
                                     headers=HEADERS).status_code, 400)
        self.assertEqual(self.post(client, ["cash_flow"]).status_code, 422)
        self.assertEqual(client.post(ROUTE, content=b" " * 20_000, headers=HEADERS).status_code, 413)

    def test_a_post_route_only(self):
        app = self.accounts.app(company_research_dir=RESEARCH, company_sources_dir=DATA)
        methods = {method for route in app.routes if getattr(route, "path", "") == ROUTE for method in route.methods}
        self.assertEqual(methods, {"POST"})

    @NEEDS_DATA
    def test_an_administrator_gets_the_exact_calculation_and_nothing_is_written(self):
        before = (tree(RESEARCH), tree(DATA))
        client = self.client("admin")
        reply = self.post(client, pv("6.60", "900"))
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json(), cs.compute(pv("6.60", "900"), RESEARCH, DATA))
        flow = self.post(client, cf("6.40"))
        self.assertEqual((flow.status_code, flow.json()["result"]["change"]), (200, "-75"))
        bad = self.post(client, pv("6.505", "875"))
        self.assertEqual(bad.status_code, 422)
        self.assertIn("to the cent", bad.json()["detail"])
        self.assertEqual((tree(RESEARCH), tree(DATA)), before)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["accounts"])

    @NEEDS_DATA
    def test_a_missing_release_is_409_naming_no_path(self):
        data = self.data_without("release-2026q3")
        reply = self.post(self.client("admin", data), cf("6.60"))
        self.assertEqual(reply.status_code, 409)
        self.assertIn("results release", reply.json()["detail"])
        self.assertNotIn(str(self.root), reply.text)


@NEEDS_DATA
class Fixtures(Copies):
    """Replies captured for the frontend tests (frontend/tests/fixtures/company-fcx-scenario-*.json)."""

    def check(self, name: str, reply: dict) -> None:
        path = FIXTURES / name
        if os.environ.get(WRITE_FIXTURES) == "1":
            path.write_bytes((json.dumps(reply, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        else:
            self.assertEqual(reply, json.loads(path.read_text(encoding="utf-8")),
                             f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover -s "
                             "tests -p test_company_scenarios.py")

    def test_the_scenario_fixtures(self):
        self.check("company-fcx-scenario-price-volume.json", cs.compute(pv("6.60", "900"), RESEARCH, DATA))
        self.check("company-fcx-scenario-cash-flow.json", cs.compute(cf("6.37"), RESEARCH, DATA))


if __name__ == "__main__":
    unittest.main()
