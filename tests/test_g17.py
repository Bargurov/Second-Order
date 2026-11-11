"""Industry divergence and revisions from retained G.17 releases, on SYNTHETIC pages shaped like the Board's (g17_fakes)
in temporary folders: evidence validation, exact comparisons, write-once records, reuse, concurrency, restarts and
read-only reads. No network is reached and no retained local file is read; the committed case library is read only to
check the explicit release links.
"""
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

import g17_fakes
from g17_fakes import DURABLE, MACHINERY, MINING, NONDURABLE, SCENARIO, VEHICLES
from second_order import g17_evidence as evidence, g17_insights, g17_rules as rules
from second_order.api import create_app

BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Insights": "1"}
CHECK = json.dumps({"check_retained_g17": True})
CHEMICALS = NONDURABLE + " / Chemicals"


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
        self.sources, self.insights = self.root / "g17", self.root / "insights"
        self.client = self.app()

    def app(self) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", self.root / "reviews",
                                       self.root / "intake", self.root / "attempts", inbox=self.root / "inbox",
                                       market=self.root / "market", insights_dir=self.insights,
                                       g17_sources=self.sources), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def keep(self, releases=tuple(g17_fakes.RELEASES), overrides=SCENARIO, pages=None):
        g17_fakes.keep(self.sources, releases, overrides, pages)

    def check(self, expect: int = 201, body: str = CHECK) -> dict:
        response = self.client.post("/api/insights/g17/checks", headers=HEADERS, content=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def listing(self) -> dict:
        response = self.client.get("/api/insights/g17")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def records(self) -> dict:
        return tree(self.insights / "g17")

    def extract(self, release: str, overrides=SCENARIO, **pages) -> dict:
        self.keep((release,), overrides, {(release, name): text for name, text in pages.items()})
        return evidence.extract(self.sources, release, evidence.retained(self.sources)[release])


class EvidenceTests(Harness):
    def test_rows_are_paths_and_columns_are_named_months(self):
        extract = self.extract("20260918")
        paths = [row["path"] for row in extract["rows"]]
        self.assertIn("MARKET GROUP / Materials / Non-energy / Paper", paths)
        self.assertIn(NONDURABLE + " / Paper", paths)  # The same label twice, kept apart by its path and code.
        self.assertIn("INDUSTRY GROUP / Manufacturing", paths)
        self.assertIn("INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS)", paths)
        self.assertEqual([m["column"] for m in extract["months"]],
                         [f"Monthly rate / 2026 / {m}" for m in ("Mar.[r]", "Apr.[r]", "May[r]", "June[r]", "July[r]",
                                                                 "Aug.[p]")])
        rows = {row["path"]: row for row in extract["rows"]}
        self.assertEqual(rows[NONDURABLE]["rates"]["2026-08"], ".0")
        self.assertEqual(rows[VEHICLES]["naics"], "3361-3")
        self.assertEqual(extract["release_date_as_stated"], "September 18, 2026")
        self.assertTrue(evidence.verify_extract(extract))
        self.assertEqual([c["equal"] for c in extract["consistency"]], [True] * 4)

    def test_malformed_pages_are_refused(self):
        page = g17_fakes.table1("20260918", SCENARIO)
        cases = {
            "not seasonally adjusted": {"table1.htm": page.replace("Percent change, seasonally adjusted",
                                                                   "Percent change, not seasonally adjusted")},
            "another table": {"table1.htm": page.replace("Market and Industry Group Summary", "Special Aggregates")},
            "swapped month columns": {"table1.htm": page.replace(" Mar.<abbr", " TMP<abbr").replace(
                " Apr.<abbr", " Mar.<abbr").replace(" TMP<abbr", " Apr.<abbr")},
            "a value naming two months": {"table1.htm": page.replace('headers=" hdr4 hdr9 hdr21 ',
                                                                     'headers=" hdr4 hdr9 hdr20 ', 1)},
            "an unmarked month": {"table1.htm": page.replace('Aug.<abbr title="preliminary">[p]</abbr>', "Aug.")},
            "a repeated path": {"table1.htm": page.replace("Wood&nbsp;products", "Machinery")},
            "a class contradicting the path": {"table1.htm": page.replace('class="indent3"', 'class="indent2"', 1)},
            "a value that is not a rate": {"table1.htm": page.replace(">.0</td>", ">n.a.</td>", 1)},
            "a later last update": {"table1.htm": page.replace("Last Update: September 18, 2026",
                                                               "Last Update: October 2, 2026")},
            "another release date": {"table1.htm": page.replace("Release Date: September 18, 2026",
                                                                "Release Date: September 17, 2026")},
            "a summary that disagrees": {"release.html": g17_fakes.summary("20260918", {
                **SCENARIO, (None, "INDUSTRY GROUP / Manufacturing", "2026-08"): "-9.9"})},
        }
        originals = {"table1.htm": page, "release.html": g17_fakes.summary("20260918", SCENARIO)}
        for name, pages in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.assertTrue(all(text != originals[file] for file, text in pages.items()))  # The mutation applied.
                root = Path(tmp)
                g17_fakes.keep(root, ("20260918",), SCENARIO, {("20260918", file): text for file, text in pages.items()})
                with self.assertRaises(evidence.EvidenceRefused):
                    evidence.extract(root, "20260918", evidence.retained(root)["20260918"])

    def test_sources_must_match_their_acquisition_records(self):
        self.keep(("20260918",))
        records = evidence.retained(self.sources)["20260918"]
        path = self.sources / "20260918" / "table1.htm"
        path.write_bytes(path.read_bytes().replace(b"Chemicals", b"Chemical"))
        with self.assertRaisesRegex(evidence.EvidenceRefused, "recorded SHA-256"):
            evidence.extract(self.sources, "20260918", records)
        partial = dict(records, **{"table1.htm": {**records["table1.htm"], "hash_kind": "partial_transfer"}})
        with self.assertRaisesRegex(evidence.EvidenceRefused, "complete response"):
            evidence.extract(self.sources, "20260918", partial)
        (self.sources / "acquisitions" / "g17-release-tables-01" / "outcome-1.json").unlink()
        self.assertEqual(evidence.retained(self.sources), {})  # A release needs both files' records.

    def test_a_blank_is_missing_and_never_compared(self):
        extract = self.extract("20260918", {**SCENARIO, ("20260918", MACHINERY, "2026-04"): ""})
        rows = {row["path"]: row for row in extract["rows"]}
        self.assertIsNone(rows[MACHINERY]["rates"]["2026-04"])
        item = next(c for c in rules.release_comparisons(extract)["comparisons"]
                    if c["row"] == MACHINERY and c["month"] == "2026-04")
        self.assertEqual((item["relation"], item["gap_pp"]), ("unavailable", None))


class RuleTests(Harness):
    def test_release_comparisons_use_paths_codes_and_exact_points(self):
        extract = self.extract("20260818")
        result = rules.release_comparisons(extract)
        pairs = {(c["row"], c["parent"], c["month"]): c for c in result["comparisons"]}
        vehicles = pairs[(VEHICLES, DURABLE, "2026-07")]
        self.assertEqual((vehicles["relation"], vehicles["gap_pp"], vehicles["marker"]), ("opposing", "-2.8", "p"))
        self.assertEqual(vehicles["column"], "Monthly rate / 2026 / July[p]")
        rows = {c["row"] for c in result["comparisons"]}
        self.assertNotIn("MARKET GROUP / Materials / Non-energy / Paper", rows)  # Market groups are out of scope.
        self.assertIn(NONDURABLE + " / Paper", rows)
        groups = {c["row"] for c in result["comparisons"] if c["kind"] == "group_vs_total"}
        self.assertEqual(groups, {"INDUSTRY GROUP / Manufacturing", MINING, "INDUSTRY GROUP / Utilities"})
        self.assertNotIn("INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS)", rows)
        self.assertEqual(len(result["comparisons"]), 6 * (3 + 19))

    def test_a_printed_zero_has_no_direction(self):
        result = rules.release_comparisons(self.extract("20260918"))
        quiet = [c for c in result["comparisons"] if c["parent"] == NONDURABLE and c["month"] == "2026-08"]
        self.assertEqual({(c["relation"], c["printed_zero_or_missing"]) for c in quiet}, {("no_direction", "parent")})
        self.assertEqual(rules.direction("-.0"), 0)
        self.assertEqual(rules.direction(".0"), 0)
        self.assertEqual(rules.pp(rules.Decimal(".1") - rules.Decimal("-.7")), "0.8")

    def test_revisions_compare_the_same_row_and_month(self):
        july = self.extract("20260717")
        august = self.extract("20260818")
        result = rules.revision_comparisons(july, august)
        self.assertEqual(result["months"], ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06"])
        kinds = {(c["row"], c["month"]): c for c in result["comparisons"]}
        machinery = kinds[(MACHINERY, "2026-06")]
        self.assertEqual((machinery["kind"], machinery["revision_pp"]), ("reversal", "0.8"))
        self.assertEqual((machinery["earlier"]["marker"], machinery["later"]["marker"]), ("p", "r"))
        self.assertEqual(kinds[(MINING, "2026-05")]["kind"], "to_printed_zero")
        self.assertEqual(kinds[("Total IP", "2026-03")]["kind"], "unchanged")
        self.assertNotIn(("MARKET GROUP / Materials / Non-energy / Paper", "2026-03"), kinds)
        september = self.extract("20260918")
        later = {(c["row"], c["month"]): c for c in rules.revision_comparisons(august, september)["comparisons"]}
        self.assertEqual(later[(MACHINERY, "2026-06")]["kind"], "same_direction")
        self.assertEqual(later[(MINING, "2026-05")]["kind"], "unchanged")  # ".0" then ".0": equal printed values.
        with self.assertRaises(rules.RulesRefused):
            rules.revision_comparisons(september, august)


class CheckTests(Harness):
    def test_check_repeat_and_reads(self):
        before_get = self.listing()
        self.assertEqual((before_get["state"], before_get["available"]), ("not_checked", []))
        self.keep()
        self.assertEqual(self.listing()["available"], list(g17_fakes.RELEASES))
        self.assertEqual(self.records(), {})  # Reading writes nothing.
        first = self.check()
        self.assertEqual((first["extracts_created"], first["release_results_created"],
                          first["revision_results_created"], first["provider_called"]), (3, 3, 2, False))
        written = self.records()
        again = self.check(200)
        self.assertEqual((again["created"], again["check_id"], again["extracts_created"]), (False, first["check_id"], 0))
        self.assertEqual(self.records(), written)
        listing = self.listing()
        self.assertEqual(listing["state"], "checked")
        cards = listing["divergence"]["shown"]
        vehicles = next(card for card in cards if card["observed"][0]["path"] == VEHICLES)
        self.assertEqual(vehicles["month"], "2026-07")
        self.assertEqual(vehicles["observed"][0]["release"], "20260918")  # The latest estimate of July.
        self.assertEqual([v["release"] for v in vehicles["estimates"]], ["20260818", "20260918"])
        self.assertEqual(vehicles["observed"][0]["url"], "https://www.federalreserve.gov/releases/g17/20260918/table1.htm")
        self.assertIn("(NAICS 3361-3)", vehicles["title"])
        quiet = listing["divergence"]["no_direction_parents"]
        self.assertIn((NONDURABLE, "2026-08", 8), [(q["parent"], q["month"], q["comparisons"]) for q in quiet])
        revisions = listing["revisions"]
        machinery = next(card for card in revisions["shown"] if card["row"] == MACHINERY)
        self.assertEqual([(e["rate"], e["marker"]) for e in machinery["chain"]], [("-.7", "p"), (".1", "r"),
                                                                                  (".4", "r")])
        self.assertEqual((machinery["from"]["release"], machinery["to"]["release"], machinery["revision_pp"]),
                         ("20260717", "20260818", "0.8"))
        zero = [(z["row"], z["kind"]) for z in revisions["printed_zero_transitions"]]
        self.assertIn((MINING, "to_printed_zero"), zero)
        self.assertNotIn(MINING, [card["row"] for card in revisions["shown"]])  # Zero transitions are not reversals.
        self.assertEqual(revisions["counts"]["reversal"], revisions["total"])
        links = [release["library"] for release in listing["releases"]]
        self.assertEqual([link["case_id"] for link in links], ["g17-2026-07-17", "g17-2026-08-18", "g17-2026-09-18"])
        tables = self.client.get("/api/insights/g17/tables").json()
        self.assertEqual(len(tables["releases"]), 3)
        self.assertEqual([len(r["comparisons"]) for r in tables["releases"]], [132, 132, 132])
        self.assertEqual(tables["releases"][0]["library"]["case_id"], "g17-2026-07-17")  # Provenance kept beside.
        self.assertEqual(len(tables["releases"][0]["sources"]), 2)
        machinery_row = next(row for row in tables["revision_rows"] if row["path"] == MACHINERY)
        june = next(cell for cell in machinery_row["cells"] if cell["month"] == "2026-06")
        self.assertEqual(june["steps"], ["reversal", "same_direction"])
        self.assertEqual(self.records(), written)

    def test_a_changed_selection_reuses_unchanged_results(self):
        self.keep()
        self.check()
        before = self.records()
        subset = self.check(201, json.dumps({"check_retained_g17": True, "releases": ["20260717", "20260918"]}))
        self.assertEqual((subset["extracts_created"], subset["release_results_created"],
                          subset["revision_results_created"]), (0, 0, 1))
        after = self.records()
        self.assertTrue(all(after[name] == digest for name, digest in before.items()))
        new = set(after) - set(before)
        self.assertEqual(len([name for name in new if not name.startswith("breadth/")]), 2)  # A pair and a check.
        self.assertEqual(len([name for name in new if name.startswith("breadth/")]), 2)  # Their breadth twins.
        self.assertEqual(self.listing()["check"]["selection"], ["20260717", "20260918"])

    def test_a_new_release_adds_work_without_touching_old_results(self):
        self.keep(("20260717", "20260818"))
        self.check()
        before = self.records()
        self.keep(("20260918",))
        added = self.check()
        self.assertEqual((added["extracts_created"], added["release_results_created"],
                          added["revision_results_created"]), (1, 1, 1))
        after = self.records()
        self.assertTrue(all(after[name] == digest for name, digest in before.items()))

    def test_concurrent_checks_create_each_record_once(self):
        self.keep()
        replies, errors = [], []

        def run():
            try:
                with TestClient(self.client.app, base_url=BASE) as client:
                    response = client.post("/api/insights/g17/checks", headers=HEADERS, content=CHECK)
                    replies.append((response.status_code, response.json()))
            except Exception as exc:  # Reported below.
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual({reply["check_id"] for _, reply in replies}, {replies[0][1]["check_id"]})
        self.assertEqual(sum(1 for _, reply in replies if reply["g17_check_created"]), 1)
        self.assertEqual(sum(1 for _, reply in replies if reply["breadth"]["created"]), 1)
        counts = {kind: len(list((self.insights / "g17" / kind).glob("*.json")))
                  for kind in ("extracts", "releases", "revisions", "checks")}
        self.assertEqual(counts, {"extracts": 3, "releases": 3, "revisions": 2, "checks": 1})

    def test_restart_reads_the_same_without_writing_or_network(self):
        self.keep()
        self.check()
        first = self.listing()
        written = self.records()
        sources = tree(self.sources)

        attempts, original = [], socket.socket.connect

        def local_only(sock, address):  # The event loop's own loopback pair is allowed; nothing else.
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return original(sock, address)
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo",
                                                               side_effect=AssertionError("name lookup")):
            restarted = self.app()
            for path in ("/api/insights/g17", "/api/insights/g17/tables"):
                self.assertEqual(restarted.get(path).status_code, 200)
            self.assertEqual(restarted.get("/api/insights/g17").json()["divergence"], first["divergence"])
        self.assertEqual((attempts, self.records(), tree(self.sources)), ([], written, sources))


class VerificationTests(Harness):
    def tamper(self, kind: str, change) -> None:
        path = next((self.insights / "g17" / kind).glob("*.json"))
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text("utf-8"))
        change(record)
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_records_that_do_not_verify_are_not_shown(self):
        for kind, change in (
                ("releases", lambda r: r["result"]["comparisons"][0].update(relation="opposing")),
                ("extracts", lambda r: r["rows"][0]["rates"].update({next(iter(r["rows"][0]["rates"])): "9.9"})),
                ("revisions", lambda r: r["result"]["comparisons"][0].update(kind="reversal"))):
            with self.subTest(kind):
                self.setUp()
                self.keep()
                self.check()
                self.tamper(kind, change)
                listing = self.listing()
                self.assertEqual(listing["state"], "problem")
                self.assertIsNone(listing["divergence"])
                self.assertEqual(self.client.get("/api/insights/g17/tables").status_code, 409)

    def test_other_definitions_are_kept_but_not_shown(self):
        self.keep()
        self.check()
        written = self.records()
        with patch.object(rules, "DEFINITIONS_SHA256", "0" * 64):
            listing = self.listing()
        self.assertEqual(listing["state"], "problem")
        self.assertIn("other definitions", listing["detail"])
        self.assertEqual(self.records(), written)


class RefusalTests(Harness):
    def test_bodies_sources_and_origins(self):
        self.assertIn("No retained G.17 release", self.check(409)["detail"])
        self.keep()
        self.check(422, json.dumps({"check": True}))
        self.check(422, json.dumps({"check_retained_g17": True, "releases": ["20251216"]}))
        self.check(422, json.dumps({"check_retained_g17": True, "releases": []}))
        self.check(422, json.dumps({"check_retained_g17": True, "extra": 1}))
        foreign = self.client.post("/api/insights/g17/checks", content=CHECK,
                                   headers={**HEADERS, "Origin": "https://example.com"})
        self.assertEqual(foreign.status_code, 403)
        without = self.client.post("/api/insights/g17/checks", content=CHECK,
                                   headers={"Origin": BASE, "Content-Type": "application/json"})
        self.assertEqual(without.status_code, 403)
        self.assertEqual(self.records(), {})

    def test_an_unreadable_acquisition_record_offers_nothing_and_reads_still_answer(self):
        self.keep()
        record = self.sources / "acquisitions" / "g17-industry-tables-01" / "outcome-1.json"
        record.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.listing()["available"], ["20260818", "20260918"])
        self.check(422, json.dumps({"check_retained_g17": True, "releases": ["20260717"]}))

    def test_an_invalid_release_writes_nothing(self):
        page = g17_fakes.table1("20260918", SCENARIO).replace("seasonally adjusted", "not seasonally adjusted")
        self.keep(pages={("20260918", "table1.htm"): page})
        self.assertIn("20260918 release was not accepted", self.check(409)["detail"])
        self.assertEqual(self.records(), {})


if __name__ == "__main__":
    unittest.main()
