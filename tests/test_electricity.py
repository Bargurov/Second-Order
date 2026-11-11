"""Electricity by sector from retained EIA Table 7.6, on SYNTHETIC files shaped like the retained ones
(electricity_fakes) in temporary folders: source and CSV validation, the fixed comparison rules, write-once results,
reuse, version invalidation, concurrency, restarts and read-only reads. No network is reached and no retained local file
is read. The definitions are bound to the stand-in PDF's hash for the duration of each test only.
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

import electricity_fakes as fakes
from second_order import electricity_evidence as evidence, electricity_insights as insights, \
    electricity_rules as rules
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_FIXTURE = ROOT / "frontend" / "tests" / "fixtures" / "electricity-view.json"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.
BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Insights": "1"}
CHECK = json.dumps({"check_retained_electricity": True})
CLOCK = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
D = Decimal


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
        self.sources, self.insights = self.root / "eia-mer", self.root / "insights"
        binding = patch.dict(evidence.TABLE_DEFINITIONS["transcribed_from"], {"sha256": fakes.PDF_SHA256})  # This test only.
        binding.start()
        self.addCleanup(binding.stop)
        self.client = self.app()

    def app(self) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", self.root / "reviews",
                                       self.root / "intake", self.root / "attempts", inbox=self.root / "inbox",
                                       market=self.root / "market", insights_dir=self.insights,
                                       insights_clock=lambda: CLOCK, g17_sources=self.root / "g17",
                                       electricity_sources=self.sources), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def keep(self, **kwargs):
        fakes.keep(self.sources, **kwargs)

    def check(self, expect: int = 201, body: str = CHECK) -> dict:
        response = self.client.post("/api/insights/electricity/checks", headers=HEADERS, content=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def view(self, client: TestClient | None = None) -> dict:
        response = (client or self.client).get("/api/insights/electricity")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def records(self) -> dict:
        return tree(self.insights / "electricity")

    def extract(self, **kwargs) -> dict:
        self.keep(**kwargs)
        return evidence.load(self.sources, rules.window(), rules.CODES)


class EvidenceTests(Harness):
    def test_series_selection_and_monthly_annual_separation(self):
        extract = self.extract()
        self.assertEqual(list(extract["values"]), list(rules.CODES))  # Direct use, end use and EV are not read.
        self.assertEqual(extract["months"], rules.window())
        self.assertEqual((extract["months"][0], extract["months"][-1], len(extract["months"])),
                         ("2024-07", "2026-06", 24))
        self.assertTrue(all(len(key) == 7 and "13" != key[5:] for key in extract["values"]["ESRCPUS"]))
        coverage = extract["coverage"]["ESRCPUS"]
        self.assertEqual((coverage["monthly_first"], coverage["monthly_last"], coverage["monthly_rows"],
                          coverage["annual_first"], coverage["annual_last"], coverage["annual_rows"]),
                         ("2023-01", "2026-06", 42, "2023", "2025", 3))
        self.assertEqual(extract["coverage"]["ESVHPUS"]["monthly_not_available"], 24)
        self.assertEqual([item["code"] for item in extract["series"]], list(evidence.SERIES))
        # An annual total, however odd, never enters a monthly comparison.
        odd = self.extract(csv=fakes.csv_text(overrides={("ESRCPUS", "202513"): "1.000"}))
        self.assertEqual(rules.compute(odd["values"]), rules.compute(extract["values"]))
        self.assertTrue(evidence.verify_extract(extract))

    def test_malformed_csv_is_refused(self):
        good = fakes.csv_text()
        row = "ESRCPUS,202606,101000.000,1,\"Electricity Sales to Ultimate Customers, Residential\",Million Kilowatthours"
        cases = {
            "another header": good.replace("MSN,YYYYMM,Value", "MSN,Month,Value", 1),
            "an unknown series": good + "ESXXPUS,202606,1.000,9,Other,Million Kilowatthours\r\n",
            "another description": good.replace("Customers, Industrial", "Customers, Manufacturing"),
            "another unit": good.replace("Million Kilowatthours", "Billion Kilowatthours", 1),
            "another column order": good.replace(',3,"Electricity Sales to Ultimate Customers, Industrial"',
                                                 ',9,"Electricity Sales to Ultimate Customers, Industrial"', 1),
            "a duplicate date": good + row + "\r\n",
            "a month 14": good + row.replace("202606", "202614") + "\r\n",
            "a dashed date": good.replace("ESRCPUS,202606", "ESRCPUS,2026-06", 1),
            "a missing series": "".join(line + "\r\n" for line in good.split("\r\n") if line
                                        and not line.startswith("ESVHPUS")),
            "a short row": good + "ESRCPUS,202607,1.000\r\n",
            "not UTF-8": None,
        }
        for token in ("NaN", "Infinity", "-Infinity", "1E+3", "", "1,000", "−5", " 5", "+5", "N/A"):
            cases[f"the value {token!r}"] = fakes.csv_text(overrides={("ESCCPUS", "202603"): token})
        for name, text in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                if text is None:
                    fakes.keep(folder)
                    (folder / "table76" / "T07.06.csv").write_bytes(b"\xff\xfe" + good.encode("utf-16-le"))
                    record = folder / "acquisitions" / "eia-mer-table76-01" / "outcome-1.json"
                    data = json.loads(record.read_text("utf-8"))
                    sha = hashlib.sha256((folder / "table76" / "T07.06.csv").read_bytes()).hexdigest()
                    record.write_text(json.dumps({**data, "sha256": sha, "retained_sha256": sha}), encoding="utf-8")
                else:
                    self.assertNotEqual(text, good)  # The mutation applied.
                    fakes.keep(folder, csv=text)
                with self.assertRaises(evidence.EvidenceRefused):
                    evidence.load(folder, rules.window(), rules.CODES)

    def test_sources_must_match_their_acquisition_records(self):
        self.keep()
        csv_path = self.sources / "table76" / "T07.06.csv"
        csv_path.write_bytes(csv_path.read_bytes().replace(b"101000.000", b"101000.001", 1))
        with self.assertRaisesRegex(evidence.EvidenceRefused, "recorded SHA-256"):
            evidence.load(self.sources, rules.window(), rules.CODES)
        for name, change, message in (
                ("T07.06.csv", {"outcome": "oversized"}, "complete response"),
                ("T07.06.csv", {"url": "https://www.eia.gov/other.csv"}, "complete response"),
                ("T07.06.csv", {"content_check": {"state": "unvalidated"}}, "format check"),
                ("sec7_19.pdf", {"http_status": 206}, "complete response")):
            with self.subTest(name=name, change=change), tempfile.TemporaryDirectory() as tmp:
                fakes.keep(Path(tmp), record_changes={name: change})
                with self.assertRaisesRegex(evidence.EvidenceRefused, message):
                    evidence.load(Path(tmp), rules.window(), rules.CODES)
        with tempfile.TemporaryDirectory() as tmp:  # A PDF the definitions were not transcribed from.
            fakes.keep(Path(tmp), pdf=fakes.PDF + b"%")
            with self.assertRaisesRegex(evidence.EvidenceRefused, "not the one the Table 7.6 definitions"):
                evidence.load(Path(tmp), rules.window(), rules.CODES)
        with tempfile.TemporaryDirectory() as tmp:  # The landing page is context only.
            fakes.keep(Path(tmp), landing=None)
            extract = evidence.load(Path(tmp), rules.window(), rules.CODES)
            self.assertIn("no single acquisition record", extract["sources"][2]["unavailable"])

    def test_missing_values_stay_missing(self):
        extract = self.extract(csv=fakes.csv_text(overrides={("ESRCPUS", "202507"): "Not Available",
                                                             ("ESCCPUS", "202408"): None}))
        july, august = (rules.month_result(extract["values"], key) for key in ("2025-07", "2025-08"))
        self.assertEqual((july["comparisons"]["ESRCPUS"]["class"], july["comparisons"]["ESRCPUS"]["reason"]),
                         ("unavailable", "2025-07 not available"))
        self.assertEqual(august["comparisons"]["ESCCPUS"]["reason"], "no 2024-08 row")
        self.assertFalse(august["divergence"]["finding"])  # Commercial was the only one down.
        self.assertEqual(july["reconciliation"][0]["state"], "unavailable")
        self.assertEqual(july["contributions"]["state"], "unavailable")


class RulesTests(unittest.TestCase):
    def test_bounds_are_inclusive_and_exact(self):
        cases = [("101000.000", "100000.000", "up", "1.00"), ("100999.999", "100000.000", "little_changed", "0.99"),
                 ("99000.000", "100000.000", "down", "-1.00"), ("99000.001", "100000.000", "little_changed", "-0.99"),
                 ("3.030", "3.000", "up", "1.00"), ("100000.000", "100000.000", "little_changed", "0.00"),
                 ("99999.999", "100000.000", "little_changed", "0.00")]
        for current, prior, expected, shown in cases:
            with self.subTest(current=current, prior=prior):
                found = rules.compare(D(current), D(prior))
                self.assertEqual((found["class"], found["percent"]), (expected, shown))
                self.assertEqual(found["change"], format(D(current) - D(prior), "f"))

    def test_a_shown_percentage_never_crosses_the_band(self):
        found = rules.compare(D("100999.000"), D("100000.000"))
        self.assertEqual((found["class"], found["percent"]), ("little_changed", "0.99"))  # 0.999 truncated, not 1.00.
        found = rules.compare(D("98999.999"), D("100000.000"))
        self.assertEqual((found["class"], found["percent"]), ("down", "-1.00"))

    def test_invalid_denominators_and_missing_sides(self):
        for prior in ("0.000", "-5.000"):
            found = rules.compare(D("10.000"), D(prior))
            self.assertEqual((found["class"], found["change"], found["percent"]), ("unavailable", None, None))
            self.assertIn("not a positive denominator", found["reason"])
        found = rules.compare(None, D("1.000"), "2026-01 not available")
        self.assertEqual((found["class"], found["reason"]), ("unavailable", "2026-01 not available"))

    def values(self, changes=fakes.CHANGES, overrides=None):
        found = fakes.values(changes)
        for (code, key), value in (overrides or {}).items():
            found[(code, key)] = value
        return {code: {key: None if found.get((code, key)) is None else format(found[(code, key)], "f")
                       for key in rules.window()} for code in rules.CODES}

    def test_the_period_sums_before_growth_and_never_averages(self):
        values = self.values(overrides={
            ("ESRCPUS", "2025-01"): D("150000.000"), ("ESRCPUS", "2025-02"): D("50000.000"),
            ("ESRCPUS", "2026-01"): D("150000.000"), ("ESRCPUS", "2026-02"): D("55000.000"),
            ("ESRCPUS", "2026-03"): D("100000.000"), ("ESRCPUS", "2026-04"): D("100000.000"),
            ("ESRCPUS", "2026-05"): D("100000.000"), ("ESRCPUS", "2026-06"): D("100000.000")})
        period = rules.period_result(values)["comparisons"]["ESRCPUS"]
        # 5,000 on 600,000 is 0.83% (little changed); the mean of the monthly rates (0, 10, 0, 0, 0, 0) is 1.67%.
        self.assertEqual((period["current"], period["prior"], period["change"], period["percent"], period["class"]),
                         ("605000.000", "600000.000", "5000.000", "0.83", "little_changed"))

    def test_a_missing_month_makes_the_period_unavailable(self):
        values = self.values()
        values["ESICPUS"]["2025-03"] = "Not Available"
        period = rules.period_result(values)
        self.assertEqual(period["comparisons"]["ESICPUS"]["class"], "unavailable")
        self.assertIn("2025-03 not available", period["comparisons"]["ESICPUS"]["reason"])
        self.assertEqual(period["contributions"]["state"], "unavailable")

    def test_one_finding_per_month_naming_every_sector(self):
        result = rules.compute(self.values())
        found = {row["month"]: row["divergence"] for row in result["months"]}
        self.assertEqual(sorted(key for key, row in found.items() if row["finding"]), sorted(fakes.FINDING_MONTHS))
        self.assertEqual((found["2026-01"]["up"], found["2026-01"]["down"]), (["ESRCPUS", "ESCCPUS"], ["ESICPUS"]))
        self.assertEqual((found["2025-08"]["up"], found["2025-08"]["down"], found["2025-08"]["little_changed"]),
                         (["ESRCPUS"], ["ESCCPUS"], ["ESICPUS"]))
        self.assertFalse(found["2025-09"]["finding"])
        self.assertTrue(result["period"]["divergence"]["finding"])
        self.assertEqual(result["counts"]["monthly_findings"], 8)
        self.assertNotIn("ESTCPUS", found["2025-07"]["up"] + found["2025-07"]["down"])  # Context never enters.

    def test_zero_findings(self):
        result = rules.compute(self.values(fakes.ALL_UP))
        self.assertEqual((result["counts"]["monthly_findings"], result["counts"]["period_finding"]), (0, False))
        self.assertEqual(result["counts"]["sector_months"]["up"], 36)

    def test_reconciliation_tolerance_and_contributions(self):
        exact = rules.compute(self.values())
        self.assertEqual(exact["reconciliation"]["counts"], {"within_rounding": 24, "beyond_rounding": 0,
                                                             "unavailable": 0})
        july = next(row for row in exact["months"] if row["month"] == "2025-07")["contributions"]
        self.assertEqual(july["state"], "computed")
        parts = sum(D(value) for value in july["sectors"].values()) + D(july["residual_change"])
        self.assertEqual(parts, D(july["total_change"]))
        self.assertEqual(july["analyzed_change"], format(sum(D(july["sectors"][c]) for c in rules.ANALYZED), "f"))
        total = fakes.values()[("ESTCPUS", "2026-01")]
        edge = rules.compute(self.values(overrides={("ESTCPUS", "2026-01"): total + D("0.0025")}))
        self.assertEqual(rules.reconcile(self.values(overrides={("ESTCPUS", "2026-01"): total + D("0.0025")}),
                                         "2026-01")["state"], "within_rounding")
        self.assertEqual(edge["reconciliation"]["counts"]["beyond_rounding"], 0)
        beyond = rules.compute(self.values(overrides={("ESTCPUS", "2026-01"): total + D("0.010")}))
        self.assertEqual(beyond["reconciliation"]["counts"]["beyond_rounding"], 1)
        self.assertEqual(beyond["reconciliation"]["max_abs_residual"], "0.010")
        january = next(row for row in beyond["months"] if row["month"] == "2026-01")
        self.assertEqual((january["reconciliation"][0]["state"], january["reconciliation"][0]["residual"]),
                         ("beyond_rounding", "0.010"))
        self.assertEqual(january["contributions"]["state"], "unavailable")
        self.assertEqual(beyond["period"]["contributions"]["state"], "unavailable")
        self.assertEqual(january["comparisons"]["ESTCPUS"]["current"], format(total + D("0.010"), "f"))  # Shown.

    def test_definitions_state_the_rule(self):
        self.assertEqual(rules.DEFINITIONS["classes"]["up"], "percentage >= +1")
        self.assertEqual(rules.DEFINITIONS["classes"]["down"], "percentage <= -1")
        self.assertIn("not statistical significance", rules.DEFINITIONS["threshold"])
        self.assertEqual(rules.months()[0], "2025-07")
        self.assertEqual(rules.months()[-1], "2026-06")
        self.assertEqual(len(rules.months()), 12)


class CheckTests(Harness):
    def test_check_repeat_and_read(self):
        before = self.view()
        self.assertEqual((before["state"], before["available"], before["findings"]), ("not_checked", False, None))
        self.keep()
        sources = tree(self.sources)
        self.assertEqual(self.view()["state"], "not_checked")
        self.assertEqual(self.records(), {})  # Reading writes nothing.
        first = self.check()
        self.assertEqual((first["created"], first["months"], first["monthly_findings"], first["period_finding"],
                          first["provider_called"]), (True, 12, 8, True, False))
        written = self.records()
        self.assertEqual(list(written), [f"results/{first['result_id']}.json"])
        again = self.check(200)
        self.assertEqual((again["created"], again["result_id"]), (False, first["result_id"]))
        self.assertEqual(self.records(), written)
        view = self.view()
        self.assertEqual((view["state"], view["result"]["result_id"], view["result"]["computed_at"]),
                         ("checked", first["result_id"], CLOCK.isoformat()))
        self.assertEqual((self.records(), tree(self.sources)), (written, sources))
        coverage = view["coverage"]
        self.assertEqual((coverage["compared"]["first_label"], coverage["compared"]["last_label"],
                          coverage["against"]["first_label"], coverage["file"]["monthly_last_label"]),
                         ("July 2025", "June 2026", "July 2024", "June 2026"))
        self.assertEqual(coverage["period"]["label"], "January–June 2026")
        self.assertIn("the CSV has no geography field", coverage["geography"])
        self.assertEqual(len(view["months"]), 12)
        findings = view["findings"]
        self.assertEqual([card["key"] for card in findings["monthly"]], fakes.FINDING_MONTHS)
        self.assertEqual(findings["total"], 9)
        august = next(card for card in findings["monthly"] if card["key"] == "2025-08")
        self.assertEqual(august["title"], "August 2025: residential sales up, commercial sales down from August 2024")
        observed = {row["code"]: row for row in august["observed"]}
        self.assertEqual((observed["ESRCPUS"]["percent"], observed["ESRCPUS"]["class"], observed["ESCCPUS"]["percent"],
                          observed["ESCCPUS"]["class"]), ("1.00", "up", "-1.00", "down"))
        self.assertEqual([row["role"] for row in august["observed"]], ["analyzed"] * 3 + ["context"] * 2)
        self.assertEqual(august["others"]["little_changed"], ["Industrial"])
        self.assertEqual(august["disclosures"], list(insights.text.DISCLOSURES))
        self.assertEqual(len(august["disclosures"]), 6)
        self.assertIn("both have 31 days", august["notes"][0])
        rows = august["contributions"]["rows"]
        self.assertEqual(sum(D(row["change"]) for row in rows) + D(august["contributions"]["residual_change"]),
                         D(august["contributions"]["total_change"]))
        period = findings["period"]
        self.assertEqual(period["title"], "January–June 2026: residential and commercial sales up, industrial sales "
                                          "down from January–June 2025")
        self.assertEqual(period["source"]["sha256"], view["sources"][0]["sha256"])
        sources_by_kind = {item["kind"]: item for item in view["sources"]}
        self.assertIsNone(sources_by_kind["csv"]["edition"])
        self.assertIn("none is assigned", sources_by_kind["csv"]["edition_note"])
        self.assertEqual(sources_by_kind["pdf"]["edition"], evidence.TABLE_DEFINITIONS["edition_printed"])
        self.assertEqual(sources_by_kind["landing"]["statements"]["release_date_as_stated"], "September 29, 2026")
        self.assertEqual(sources_by_kind["csv"]["retrieved_at"], "2026-10-11T21:41:13.000000+00:00")
        self.assertIsNone(sources_by_kind["csv"]["last_modified_header"])
        self.assertEqual({item["code"]: item["role"] for item in view["series"]}["ESVHPUS"], "excluded")
        self.assertEqual(view["reconciliation"]["counts"]["within_rounding"], 24)

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
                                                "-p test_electricity.py")

    def test_zero_findings_are_a_valid_result(self):
        self.keep(csv=fakes.csv_text(fakes.ALL_UP))
        self.assertEqual(self.check()["monthly_findings"], 0)
        view = self.view()
        self.assertEqual((view["state"], view["findings"]["total"], view["findings"]["monthly"],
                          view["findings"]["period"]), ("checked", 0, [], None))
        self.assertEqual(len(view["months"]), 12)

    def test_concurrent_checks_create_the_result_once(self):
        self.keep()
        replies, errors = [], []

        def run():
            try:
                with TestClient(self.client.app, base_url=BASE) as client:
                    response = client.post("/api/insights/electricity/checks", headers=HEADERS, content=CHECK)
                    replies.append((response.status_code, response.json()))
            except Exception as exc:  # Reported below.
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual({reply["result_id"] for _, reply in replies}, {replies[0][1]["result_id"]})
        self.assertEqual(sum(1 for _, reply in replies if reply["created"]), 1)
        self.assertEqual(len(self.records()), 1)

    def test_no_network_during_check_reads_and_restart(self):
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
            written, sources = self.records(), tree(self.sources)
            restarted = self.app()
            self.assertEqual(self.view(restarted), first)
            self.assertEqual(restarted.post("/api/insights/electricity/checks", headers=HEADERS,
                                            content=CHECK).status_code, 200)
        self.assertEqual((attempts, self.records(), tree(self.sources)), ([], written, sources))


class VersionTests(Harness):
    def test_a_new_version_or_scope_invalidates_without_deleting(self):
        self.keep()
        first = self.check()
        written = self.records()
        for target, name, value in ((rules, "DEFINITIONS_SHA256", "0" * 64), (rules, "RULES_VERSION", "x"),
                                    (insights, "RESULT_VERSION", "x"), (evidence, "EXTRACT_VERSION", "x"),
                                    (rules, "SCOPE", {**rules.SCOPE, "months": {"first": "2025-08",
                                                                               "last": "2026-06"}})):
            with self.subTest(name), patch.object(target, name, value):
                view = self.view()
                self.assertEqual((view["state"], view["kept_results"]), ("not_checked", 1))
                self.assertIn("other versions, scope or sources", view["detail"])
                self.assertEqual(self.records(), written)
        with patch.object(rules, "RULES_VERSION", "electricity-rules-0.2"):
            second = self.check()
            self.assertNotEqual(second["result_id"], first["result_id"])
            self.assertEqual(self.view()["state"], "checked")
        after = self.records()
        self.assertEqual(len(after), 2)
        self.assertTrue(all(after[name] == digest for name, digest in written.items()))
        self.assertEqual(self.view()["result"]["result_id"], first["result_id"])  # The original reads again.

    def test_changed_sources_need_a_new_check(self):
        self.keep()
        self.check()
        self.keep(csv=fakes.csv_text(fakes.ALL_UP))
        view = self.view()
        self.assertEqual((view["state"], view["kept_results"]), ("not_checked", 1))
        (self.sources / "table76" / "T07.06.csv").unlink()
        view = self.view()
        self.assertEqual((view["state"], view["available"]), ("problem", False))
        self.assertIn("kept and not shown", view["detail"])
        self.assertIn("not accepted", self.check(409)["detail"])

    def test_a_stored_result_that_does_not_verify_is_not_shown_or_overwritten(self):
        self.keep()
        first = self.check()
        path = self.insights / "electricity" / "results" / f"{first['result_id']}.json"
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text("utf-8"))
        record["result"]["months"][0]["comparisons"]["ESRCPUS"]["class"] = "down"
        path.write_text(json.dumps(record), encoding="utf-8")
        tampered = tree(self.insights)
        view = self.view()
        self.assertEqual((view["state"], view["findings"]), ("problem", None))
        self.assertIn("does not match", view["detail"])
        self.assertIn("not overwritten", self.check(409)["detail"])
        self.assertEqual(tree(self.insights), tampered)


class RefusalTests(Harness):
    def test_bodies_sources_and_origins(self):
        self.assertIn("never downloads", self.check(409)["detail"])
        self.keep()
        for body in (json.dumps({"check": True}), json.dumps({"check_retained_electricity": True, "extra": 1}),
                     json.dumps({"check_retained_electricity": "yes"}), "not json"):
            self.check(422, body)
        foreign = self.client.post("/api/insights/electricity/checks", content=CHECK,
                                   headers={**HEADERS, "Origin": "https://example.com"})
        self.assertEqual(foreign.status_code, 403)
        without = self.client.post("/api/insights/electricity/checks", content=CHECK,
                                   headers={"Origin": BASE, "Content-Type": "application/json"})
        self.assertEqual(without.status_code, 403)
        self.assertEqual(self.records(), {})

    def test_an_invalid_csv_writes_nothing(self):
        self.keep(csv=fakes.csv_text(overrides={("ESICPUS", "202601"): "NaN"}))
        self.assertIn("finite decimal", self.check(409)["detail"])
        self.assertEqual(self.records(), {})
        view = self.view()
        self.assertEqual((view["state"], view["available"]), ("not_checked", False))
        self.assertIn("finite decimal", view["sources_detail"])


if __name__ == "__main__":
    unittest.main()
