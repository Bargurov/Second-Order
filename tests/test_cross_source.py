"""Cross-source comparisons, on SYNTHETIC G.17 pages (g17_fakes) and SYNTHETIC EIA Table 7.6 files (electricity_fakes,
from January 2022) in temporary folders: column and row selection through the table structure, period alignment,
complete fourth quarters, signs and printed zeros, release selection, the EIA-only customer breakdown, provenance,
write-once results, reuse, invalidation, tampering, restarts and the absence of network use. The PDF binding is set
to the stand-in PDF for each test's run only.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import electricity_fakes
import g17_fakes
from second_order import (crosssource_insights as insights, crosssource_rules as rules, electricity_evidence,
                          electricity_rules, g17_columns, g17_evidence)
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_FIXTURE = ROOT / "frontend" / "tests" / "fixtures" / "cross-source-view.json"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.
BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Insights": "1"}
CHECK = json.dumps({"check_cross_source": True})
CLOCK = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
MANUFACTURING = "INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS)"
ELECTRIC = "INDUSTRY GROUP / Utilities / Electric"
# G.17: Q4 2025 for manufacturing printed 1.2 in July, 1.4 later (the latest is used); June's 12-month rates in July.
G17 = {(None, MANUFACTURING, "q4:2023"): "-.1", (None, MANUFACTURING, "q4:2024"): "-1.4",
       ("20260717", MANUFACTURING, "q4:2025"): "1.2", (None, MANUFACTURING, "q4:2025"): "1.4",
       ("20260717", MANUFACTURING, "12m"): "-.5", ("20260818", MANUFACTURING, "12m"): "1.3",
       ("20260918", MANUFACTURING, "12m"): "1.0",
       (None, ELECTRIC, "q4:2023"): ".2", (None, ELECTRIC, "q4:2024"): "2.3", (None, ELECTRIC, "q4:2025"): "3.0",
       ("20260717", ELECTRIC, "12m"): "1.3", ("20260818", ELECTRIC, "12m"): "1.3", ("20260918", ELECTRIC, "12m"): "7.0",
       (None, "INDUSTRY GROUP / Mining", "q4:2024"): "9.9", (None, "INDUSTRY GROUP / Mining", "12m"): "9.9"}
# EIA: Q4 2024 sales up 1%, 2% and 3% for residential, commercial and industrial against a flat Q4 2023.
EIA = {**electricity_fakes.CHANGES, **{month: ("1", "2", "3", "0") for month in ("2024-10", "2024-11", "2024-12")}}


def tree(folder: Path) -> dict:
    found = {}
    if folder.exists():
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                found[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


class Harness(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.g17, self.eia, self.insights = self.root / "g17", self.root / "eia-mer", self.root / "insights"
        binding = patch.dict(electricity_evidence.TABLE_DEFINITIONS["transcribed_from"],
                             {"sha256": electricity_fakes.PDF_SHA256})  # This test's run only.
        binding.start()
        self.addCleanup(binding.stop)
        self.client = self.app()

    def app(self) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", self.root / "reviews",
                                       self.root / "intake", self.root / "attempts", inbox=self.root / "inbox",
                                       market=self.root / "market", insights_dir=self.insights,
                                       insights_clock=lambda: CLOCK, g17_sources=self.g17,
                                       electricity_sources=self.eia), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def keep(self, g17=G17, eia=EIA, pages=None, overrides=None):
        g17_fakes.keep(self.g17, overrides={**g17_fakes.SCENARIO, **g17}, pages=pages)
        electricity_fakes.keep(self.eia, csv=electricity_fakes.csv_text(eia, overrides, first="2022-01"))

    def computed(self) -> dict:
        extracts, eia = insights._inputs(insights.Folders(self.g17, self.eia, self.insights / "cross-source"))
        return rules.compute(extracts, eia["values"], eia["coverage"])

    def check(self, expect: int = 201, body: str = CHECK) -> dict:
        response = self.client.post("/api/insights/cross-source/checks", headers=HEADERS, content=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def view(self, client: TestClient | None = None) -> dict:
        response = (client or self.client).get("/api/insights/cross-source")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def records(self) -> dict:
        return tree(self.insights)


class ColumnTests(Harness):
    def test_rows_and_columns_are_resolved_through_the_table_structure(self):
        self.keep()
        july, august, september = g17_columns.load(self.g17)
        manufacturing = july["rows"]["manufacturing"]
        self.assertEqual((manufacturing["path"], manufacturing["naics"]), (MANUFACTURING, "31-33"))
        self.assertEqual({year: cell["value"] for year, cell in manufacturing["fourth_quarter"].items()},
                         {"2023": "-.1", "2024": "-1.4", "2025": "1.2"})
        self.assertEqual(manufacturing["fourth_quarter"]["2024"]["column"], "Fourth quarter to fourth quarter / 2024")
        self.assertEqual(manufacturing["twelve_month"], {"value": "-.5", "period": "2026-06", "marker": "p",
                                                         "column": "June '25 to June '26"})
        self.assertEqual(september["rows"]["electric"]["twelve_month"]["period"], "2026-08")
        self.assertEqual(september["rows"]["electric"]["twelve_month"]["value"], "7.0")
        self.assertEqual(set(july["rows"]), {"manufacturing", "electric"})  # Mining's 9.9 is never read.
        self.assertTrue(all(g17_columns.verify(item) for item in (july, august, september)))
        self.assertEqual(july["source"]["file"], "20260717/table1.htm")

    def test_tables_that_do_not_check_out_are_refused(self):
        page = g17_fakes.table1("20260717", {**g17_fakes.SCENARIO, **G17})
        cases = {
            "another fourth-quarter heading": page.replace("Fourth&nbsp;quarter&nbsp;to<br>fourth&nbsp;quarter",
                                                           "Fourth&nbsp;quarter&nbsp;average"),
            "a 12-month column for another month": page.replace("June&nbsp;'25<br>to", "May&nbsp;'25<br>to"),
            "a 12-month column a year off": page.replace("June&nbsp;'26", "June&nbsp;'27"),
            "a recoded row": page.replace(">2211<", ">2212<", 1),
            "a renamed row": page.replace(">Electric<", ">Electricity<"),
            "a value that is not a rate": page.replace(">-.1</td>",
                                                                                                    ">n.a.</td>", 1),
        }
        for name, text in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.assertNotEqual(text, page)  # The mutation applied.
                g17_fakes.keep(Path(tmp), ("20260717",), {**g17_fakes.SCENARIO, **G17}, {("20260717", "table1.htm"): text})
                with self.assertRaises(g17_columns.ColumnsRefused):
                    g17_columns.load(Path(tmp))

    def test_a_blank_cell_stays_missing(self):
        self.keep(g17={**G17, (None, ELECTRIC, "q4:2023"): ""})
        row = next(item for item in self.computed()["utility_output_and_customers"] if item["period"] == "2023-Q4")
        self.assertEqual((row["g17"]["state"], row["g17"]["value"], row["g17"]["sign"]), ("blank", None, None))


class RuleTests(Harness):
    def test_periods_are_aligned_and_never_substituted(self):
        self.keep()
        result = self.computed()
        self.assertEqual([p["key"] for p in result["periods"]],
                         ["2023-Q4", "2024-Q4", "2025-Q4", "2026-06", "2026-07", "2026-08"])
        rows = {row["period"]: row for row in result["industrial_vs_manufacturing"]}
        june = rows["2026-06"]
        self.assertEqual((june["g17"]["release"], june["g17"]["marker"], june["g17"]["column"]),
                         ("20260717", "p", "June '25 to June '26"))
        self.assertEqual((june["eia"]["months"], june["eia"]["prior_months"]), (["2026-06"], ["2025-06"]))
        for key, release in (("2026-07", "20260818"), ("2026-08", "20260918")):
            self.assertEqual((rows[key]["eia"]["state"], rows[key]["signs"], rows[key]["g17"]["release"]),
                             ("not_covered", "not_covered", release))
            self.assertIn("outside the retained file", rows[key]["eia"]["reason"])

    def test_fourth_quarters_are_complete_october_to_december_totals(self):
        self.keep()
        rows = {row["period"]: row for row in self.computed()["industrial_vs_manufacturing"]}
        q4 = rows["2024-Q4"]["eia"]
        self.assertEqual((q4["months"], q4["prior_months"]), (["2024-10", "2024-11", "2024-12"],
                                                              ["2023-10", "2023-11", "2023-12"]))
        self.assertEqual((q4["current"], q4["prior"], q4["change"], q4["percent"], q4["sign"]),
                         ("247200.000", "240000.000", "7200.000", "3.00", 1))
        self.assertEqual((rows["2023-Q4"]["eia"]["change"], rows["2023-Q4"]["eia"]["sign"], rows["2023-Q4"]["signs"]),
                         ("0.000", 0, "no_direction"))
        cases = {"a missing month": ({("ESICPUS", "202411"): None}, "unavailable", "no 2024-11 row"),
                 "a month not available": ({("ESICPUS", "202312"): "Not Available"}, "unavailable",
                                           "2023-12 not available"),
                 "a zero prior total": ({("ESICPUS", f"2023{m}"): "0.000" for m in ("10", "11", "12")}, "unavailable",
                                        "not a positive denominator")}
        for name, (overrides, state, reason) in cases.items():
            with self.subTest(name):
                self.setUp()
                self.keep(overrides=overrides)
                q4 = next(r for r in self.computed()["industrial_vs_manufacturing"] if r["period"] == "2024-Q4")
                self.assertEqual((q4["eia"]["state"], q4["signs"]), (state, state))
                self.assertIn(reason, q4["eia"]["reason"])

    def test_annual_rows_are_never_used(self):
        self.keep()
        before = self.computed()
        self.setUp()
        self.keep(overrides={("ESICPUS", "202413"): "1.000", ("ESICPUS", "202313"): "999999.000"})
        self.assertEqual(self.computed(), before)

    def test_signs_are_sign_only_and_a_printed_zero_has_no_direction(self):
        self.keep()
        rows = {row["period"]: row for row in self.computed()["industrial_vs_manufacturing"]}
        self.assertEqual(rows["2024-Q4"]["signs"], "opposite_signs")  # EIA +3.00%, G.17 -1.4.
        self.assertEqual(rows["2025-Q4"]["signs"], "opposite_signs")  # EIA down, G.17 +1.4.
        self.assertEqual(rows["2026-06"]["signs"], "same_sign")  # EIA -1.00%, G.17 -0.5: no threshold applies.
        for printed in (".0", "-.0"):
            with self.subTest(printed):
                self.setUp()
                self.keep(g17={**G17, ("20260717", MANUFACTURING, "12m"): printed})
                june = next(r for r in self.computed()["industrial_vs_manufacturing"] if r["period"] == "2026-06")
                self.assertEqual((june["g17"]["sign"], june["signs"]), (0, "no_direction"))
        self.assertEqual(set(rows["2024-Q4"]), {"period", "kind", "eia", "g17", "signs"})  # Nothing combined.

    def test_the_latest_retained_release_is_used_and_every_vintage_listed(self):
        self.keep()
        q4 = next(r for r in self.computed()["industrial_vs_manufacturing"] if r["period"] == "2025-Q4")["g17"]
        self.assertEqual((q4["value"], q4["release"], q4["marker"]), ("1.4", "20260918", None))
        self.assertEqual([(v["release"], v["value"]) for v in q4["vintages"]],
                         [("20260717", "1.2"), ("20260818", "1.4"), ("20260918", "1.4")])
        self.assertTrue(q4["vintages_differ"])

    def test_the_customer_breakdown_decomposes_the_eia_total_only(self):
        self.keep()
        row = next(r for r in self.computed()["utility_output_and_customers"] if r["period"] == "2024-Q4")
        breakdown = row["breakdown"]
        self.assertEqual(breakdown["state"], "computed")
        parts = sum(Decimal(v) for v in breakdown["sectors"].values()) + Decimal(breakdown["residual_change"])
        self.assertEqual(parts, Decimal(breakdown["total_change"]))
        self.assertEqual(breakdown["total_change"], row["eia_total"]["change"])
        self.assertEqual((row["g17"]["value"], row["g17"]["path"]), ("2.3", ELECTRIC))
        self.assertNotIn("signs", row)  # Utility output and EIA sales are shown side by side, not paired.
        total = electricity_fakes.values(EIA, "2022-01")[("ESTCPUS", "2024-11")]
        self.setUp()
        self.keep(overrides={("ESTCPUS", "202411"): format(total + Decimal("0.010"), "f")})
        row = next(r for r in self.computed()["utility_output_and_customers"] if r["period"] == "2024-Q4")
        self.assertEqual((row["eia_total"]["state"], row["breakdown"]["state"]), ("computed", "unavailable"))
        self.assertIn("2024-11", row["breakdown"]["detail"])

    def test_definitions_state_the_rules(self):
        self.assertIn("not the +/-1% categories", rules.DEFINITIONS["signs"])
        self.assertIn("no difference of growth rates", rules.DEFINITIONS["not_computed"])
        self.assertIn("not a decomposition of G.17 output", rules.DEFINITIONS["customer_breakdown"])


class CheckTests(Harness):
    def test_action_repeat_read_and_provenance(self):
        self.assertEqual((self.view()["state"], self.view()["available"]), ("not_checked", False))
        self.keep()
        self.assertEqual(self.records(), {})  # Reading writes nothing.
        first = self.check()
        self.assertEqual((first["created"], first["periods"], first["provider_called"]), (True, 6, False))
        written = self.records()
        self.assertEqual(list(written), [f"cross-source/results/{first['result_id']}.json"])
        again = self.check(200)
        self.assertEqual((again["created"], again["result_id"]), (False, first["result_id"]))
        view = self.view()
        self.assertEqual((view["state"], view["result"]["computed_at"]), ("checked", CLOCK.isoformat()))
        self.assertEqual(self.records(), written)
        row = next(r for r in view["comparisons"]["industrial_vs_manufacturing"] if r["period"] == "2024-Q4")
        self.assertEqual(row["label"], "Q4 2024 vs Q4 2023")
        self.assertEqual((row["g17"]["path"], row["g17"]["naics"], row["g17"]["column"], row["g17"]["release"]),
                         (MANUFACTURING, "31-33", "Fourth quarter to fourth quarter / 2024", "20260918"))
        self.assertEqual(row["g17"]["sha256"], next(s["sha256"] for s in view["sources"]["g17"]
                                                    if s["release"] == "20260918"))
        self.assertEqual((row["eia"]["code"], row["eia"]["months"]), ("ESICPUS", ["2024-10", "2024-11", "2024-12"]))
        self.assertIsNone(view["sources"]["eia"]["edition"])
        self.assertEqual(view["sources"]["eia"]["monthly_last"], "2026-06")
        self.assertEqual(view["comparisons_text"]["utility_output_and_customers"]["differences"][0][:56],
                         "The customer breakdown decomposes EIA total retail sales")

    def test_other_findings_records_are_untouched(self):
        self.keep()
        for path, body in (("/api/insights/g17/checks", {"check_retained_g17": True}),
                           ("/api/insights/electricity/checks", {"check_retained_electricity": True})):
            self.client.post(path, headers=HEADERS, content=json.dumps(body))
        others = {name: tree(self.insights / name) for name in ("g17", "electricity")}
        views = {path: self.client.get(path).json() for path in ("/api/insights/g17", "/api/insights/electricity")}
        self.check()
        self.assertEqual({name: tree(self.insights / name) for name in others}, others)
        self.assertEqual({path: self.client.get(path).json() for path in views}, views)
        self.assertEqual((g17_evidence.EXTRACT_VERSION, electricity_rules.RULES_VERSION),
                         ("g17-extract-0.1", "electricity-rules-0.1"))

    def test_served_view_matches_the_committed_frontend_fixture(self):
        self.keep()
        self.check()
        served = self.view()
        text = json.dumps(served, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
        if os.environ.get(WRITE_FIXTURES) == "1":
            FRONTEND_FIXTURE.write_bytes(text.encode("utf-8"))
        else:
            committed = json.loads(FRONTEND_FIXTURE.read_text(encoding="utf-8"))
            self.assertEqual(served, committed, f"{FRONTEND_FIXTURE.name} is stale; regenerate it with "
                                                f"{WRITE_FIXTURES}=1 python -m unittest discover -s tests "
                                                "-p test_cross_source.py")

    def test_concurrent_actions_create_the_result_once(self):
        self.keep()
        replies, errors = [], []

        def run():
            try:
                with TestClient(self.client.app, base_url=BASE) as client:
                    response = client.post("/api/insights/cross-source/checks", headers=HEADERS, content=CHECK)
                    replies.append(response.json())
            except Exception as exc:  # Reported below.
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sum(1 for reply in replies if reply["created"]), 1)
        self.assertEqual(len(self.records()), 1)

    def test_no_network_during_the_action_reads_and_restart(self):
        self.keep()
        attempts, original = [], socket.socket.connect

        def local_only(sock, address):  # The event loop's own loopback pair is allowed; nothing else.
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return original(sock, address)
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo",
                                                               side_effect=AssertionError("name lookup")):
            self.check()
            first = self.view()
            written, sources = self.records(), (tree(self.g17), tree(self.eia))
            restarted = self.app()
            self.assertEqual(self.view(restarted), first)
            self.assertEqual(restarted.post("/api/insights/cross-source/checks", headers=HEADERS,
                                            content=CHECK).status_code, 200)
        self.assertEqual((attempts, self.records(), (tree(self.g17), tree(self.eia))), ([], written, sources))


class VersionTests(Harness):
    def test_other_versions_or_sources_are_kept_but_not_shown(self):
        self.keep()
        first = self.check()
        written = self.records()
        for target, name, value in ((rules, "DEFINITIONS_SHA256", "0" * 64), (rules, "RULES_VERSION", "x"),
                                    (insights, "RESULT_VERSION", "x"), (g17_columns, "COLUMNS_VERSION", "x"),
                                    (electricity_rules, "RULES_VERSION", "x")):
            with self.subTest(name), patch.object(target, name, value):
                view = self.view()
                self.assertEqual((view["state"], view["kept_results"]), ("not_checked", 1))
                self.assertEqual(self.records(), written)
        self.keep(eia={**EIA, "2026-06": ("2", "2", "2", "0")})
        self.assertEqual(self.view()["state"], "not_checked")
        second = self.check()
        self.assertNotEqual(second["result_id"], first["result_id"])
        self.assertTrue(all(self.records()[name] == digest for name, digest in written.items()))

    def test_a_tampered_result_is_not_shown_or_overwritten(self):
        self.keep()
        first = self.check()
        path = self.insights / "cross-source" / "results" / f"{first['result_id']}.json"
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text("utf-8"))
        record["result"]["industrial_vs_manufacturing"][1]["signs"] = "same_sign"
        path.write_text(json.dumps(record), encoding="utf-8")
        tampered = self.records()
        view = self.view()
        self.assertEqual((view["state"], view["comparisons"]), ("problem", None))
        self.assertIn("not overwritten", self.check(409)["detail"])
        self.assertEqual(self.records(), tampered)

    def test_missing_sources_show_a_problem(self):
        self.keep()
        self.check()
        (self.eia / "table76" / "T07.06.csv").unlink()
        view = self.view()
        self.assertEqual((view["state"], view["available"]), ("problem", False))
        self.assertIn("not accepted", self.check(409)["detail"])


class RefusalTests(Harness):
    def test_bodies_sources_and_origins(self):
        self.assertIn("never downloads", self.check(409)["detail"])
        self.keep()
        for body in (json.dumps({"check": True}), json.dumps({"check_cross_source": True, "extra": 1}), "x"):
            self.check(422, body)
        foreign = self.client.post("/api/insights/cross-source/checks", content=CHECK,
                                   headers={**HEADERS, "Origin": "https://example.com"})
        without = self.client.post("/api/insights/cross-source/checks", content=CHECK,
                                   headers={"Origin": BASE, "Content-Type": "application/json"})
        self.assertEqual((foreign.status_code, without.status_code), (403, 403))
        self.assertEqual(self.records(), {})

    def test_a_malformed_cell_is_a_refusal_that_writes_nothing(self):
        page = g17_fakes.table1("20260918", {**g17_fakes.SCENARIO, **G17}).replace(">7.0</td>", ">n.a.</td>", 1)
        self.keep(pages={("20260918", "table1.htm"): page})
        self.assertIn("not a printed one-decimal rate", self.check(409)["detail"])
        self.assertEqual(self.records(), {})
        self.assertEqual((self.view()["state"], self.view()["available"]), ("not_checked", False))


if __name__ == "__main__":
    unittest.main()
