"""The Treasury findings pilot through the app's own routes on temporary folders: evidence extraction, event
identity, write-once records, reuse, concurrency, restarts and read-only reads. SYNTHETIC data only.

Packages are SYNTHETIC H.15 release packages (insight_fakes); Inbox entries come from SYNTHETIC feeds and captures from
the Tracker's own capture function. No network is reached and no real record is read or written.
"""
from datetime import date, datetime, timedelta, timezone
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

import insight_fakes
from market_fakes import capture, fill_inbox, inbox_feeds, item_id, keep_package, release_zip
from second_order import insight_evidence, insight_rules, insights
from second_order.api import create_app

UTC = timezone.utc
BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Insights": "1"}
STATEMENT = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"
PROJECTIONS = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916b.htm"
N10, R10 = "RIFLGFCY10_N.B", "RIFLGFCY10_XII_N.B"
CHECK = json.dumps({"check_retained_evidence": True})


def tree(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()} if root.exists() else {}


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


class Harness(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.market, self.inbox, self.intake = self.root / "market", self.root / "inbox", self.root / "intake"
        self.library, self.insights = self.root / "library", self.root / "insights"  # No library is installed.
        self.clock = Clock(datetime(2026, 10, 2, 12, tzinfo=UTC))
        patcher = patch.dict(insights.COMPARISON, {"size": 30})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.app()

    def app(self) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.root / "drafts", self.root / "reviews",
                                       self.intake, self.root / "attempts", inbox=self.inbox, market=self.market,
                                       library=self.library, insights_dir=self.insights,
                                       insights_clock=self.clock), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def folders(self) -> insights.Folders:
        return insights.Folders(insights=self.insights, market=self.market, inbox=self.inbox, intake=self.intake,
                                library=self.library)

    def package(self, requested=datetime(2026, 10, 1, 12, tzinfo=UTC), **changes) -> str:
        return insight_fakes.keep(self.market, date(2026, 9, 30), requested, **changes)

    def events(self):
        """Two captures of one statement, a projections capture is not added here; two FOMC entries with the same
        title; an energy entry; and an entry whose timestamp contradicts its zone."""
        self.captures = [capture(self.intake, "Federal Reserve issues FOMC statement", STATEMENT,
                                 "2026-09-16T14:00:00-04:00", datetime(2026, 9, 17, 9, minute, tzinfo=UTC))
                         for minute in (0, 5)]
        view = fill_inbox(self.inbox, inbox_feeds(
            fed=[("Federal Reserve issues FOMC statement", "Wed, 29 Jul 2026 18:00:00 GMT"),
                 ("Federal Reserve issues FOMC statement", "Wed, 17 Jun 2026 18:00:00 GMT"),
                 ("Minutes of the Federal Open Market Committee", "Wed, 19 Aug 2026 14:00:00 EST")],
            eia=[("U.S. crude oil production", "Mon, 21 Sep 2026 09:00:00 EST")]), lambda: self.clock())
        self.inbox_ids = {title: item_id(view, title) for title in ("Federal Reserve issues FOMC statement",
                                                                     "U.S. crude oil production")}
        self.view = view

    def check(self, expect: int = 201) -> dict:
        response = self.client.post("/api/insights/checks", headers=HEADERS, content=CHECK)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def listing(self) -> dict:
        response = self.client.get("/api/insights")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def results(self) -> list[Path]:
        return sorted((self.insights / "results").glob("*.json"))


class CheckTests(Harness):
    def test_a_check_measures_each_occasion_once_and_a_repeat_writes_nothing(self):
        self.package()
        self.events()
        before = tree(self.root)
        listed = self.listing()  # Reads write nothing and run nothing.
        self.assertEqual((listed["check"], tree(self.root)), (None, before))
        first = self.check()
        self.assertEqual((first["created"], first["provider_called"]), (True, False))
        occasions = {row["date"]: row for row in self.listing()["occasions"]}
        self.assertEqual(sorted(occasions), ["2026-06-17", "2026-07-29", "2026-09-16"])
        self.assertEqual(len(self.results()), 3)
        self.assertEqual({row["state"] for row in occasions.values()}, {"checked"})
        self.assertEqual({row["checks"] for row in occasions.values()}, {12})
        settled = tree(self.root)
        again = self.check(expect=200)
        self.assertEqual((again["created"], again["results_created"], again["check_id"]),
                         (False, 0, first["check_id"]))
        self.assertEqual(tree(self.root), settled)

    def test_one_event_per_release_recurring_titles_kept_apart_and_problems_visible(self):
        self.package()
        self.events()
        conflict = capture(self.intake, "Federal Reserve issues FOMC statement",
                           next(item["link"] for item in self.view["items"] if "Jul 2026" in item["feed_timestamp"]["raw"]),
                           "2026-07-30T14:00:00-04:00", datetime(2026, 7, 31, 9, tzinfo=UTC))
        self.check()
        events = {event["key"]: event for event in self.listing()["events"]}
        by_capture = {record["origin_id"]: event for event in events.values() for record in event["records"]}
        statement = by_capture[self.captures[0]]
        self.assertIs(by_capture[self.captures[1]], statement)  # Two captures of one release: one event.
        self.assertEqual((statement["date"], [record["basis"] for record in statement["records"]]),
                         ("2026-09-16", ["supplied", "supplied"]))
        same_title = [event for event in events.values() if event["title"] == "Federal Reserve issues FOMC statement"]
        self.assertEqual(len(same_title), 3)  # Same title, different releases: never merged.
        clash = by_capture[conflict]
        self.assertEqual((clash["state"], clash["date"]), ("date_conflict", None))
        self.assertEqual({record["origin"] for record in clash["records"]}, {"capture", "inbox"})
        self.assertIn("2026-07-29", clash["detail"])
        states = {event["state"] for event in events.values()}
        self.assertLessEqual({"unsupported", "no_date", "dated", "date_conflict"}, states)
        energy = next(event for event in events.values() if event["title"] == "U.S. crude oil production")
        self.assertEqual(energy["state"], "unsupported")
        minutes = next(event for event in events.values() if event["title"].startswith("Minutes"))
        self.assertEqual(minutes["state"], "no_date")  # EST in August contradicts the date: no date is invented.
        july = next(event for event in same_title if event["date"] == "2026-06-17")
        self.assertEqual(july["records"][0]["basis"], "feed_timestamp")

    def test_a_newer_package_is_used_only_by_a_check_and_unchanged_inputs_are_reused(self):
        first_package = self.package()
        self.events()
        self.check()
        results = tree(self.insights / "results")
        newer = self.package(requested=datetime(2026, 10, 2, 9, tzinfo=UTC))
        listed = self.listing()
        self.assertEqual(listed["check"]["package"]["package_id"], first_package)  # Nothing ran by itself.
        second = self.check()
        self.assertEqual((second["created"], second["results_created"]), (True, 0))
        self.assertEqual(tree(self.insights / "results"), results)
        view = self.client.get("/api/insights/occasions/2026-09-16").json()
        self.assertEqual(view["provenance"]["computed_from"]["package_id"], first_package)
        self.assertEqual([item["package_id"] for item in view["provenance"]["attested_by"]], [first_package, newer])

    def test_a_changed_observation_makes_a_new_result_for_that_occasion_only(self):
        self.package()
        self.events()
        self.check()
        before = {path.name for path in self.results()}
        self.package(requested=datetime(2026, 10, 2, 9, tzinfo=UTC), overrides={(N10, date(2026, 9, 17)): "5.55"})
        second = self.check()
        self.assertEqual(second["results_created"], 1)
        added = {path.name for path in self.results()} - before
        self.assertEqual([json.loads((self.insights / "results" / name).read_text("utf-8"))["context_date"]
                          for name in added], ["2026-09-16"])

    def test_membership_order_and_timestamps_do_not_change_results(self):
        self.package()
        self.events()
        self.check()
        results = tree(self.insights / "results")
        capture(self.intake, "Federal Reserve Board and FOMC release economic projections", PROJECTIONS,
                "2026-09-16T14:00:00-04:00", datetime(2026, 9, 17, 10, tzinfo=UTC))
        self.clock.moment += timedelta(days=3)
        second = self.check()
        self.assertEqual((second["created"], second["results_created"]), (True, 0))
        self.assertEqual(tree(self.insights / "results"), results)
        view = self.client.get("/api/insights/occasions/2026-09-16").json()
        self.assertEqual(len(view["events"]), 2)  # The co-dated release shares the one measurement.

    def test_concurrent_checks_create_each_record_once(self):
        self.package()
        self.events()
        start, outcomes, errors = threading.Barrier(4), [], []

        def run():
            start.wait()
            try:
                outcomes.append(insights.check(CHECK.encode(), self.folders(), self.clock))
            except Exception as exc:  # noqa: BLE001 - collected and asserted below
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        self.assertEqual(errors, [])
        self.assertEqual(len({outcome["check_id"] for outcome in outcomes}), 1)
        self.assertEqual(len(list((self.insights / "checks").glob("*.json"))), 1)
        self.assertEqual(len(self.results()), 3)
        self.assertEqual(len(list((self.insights / "comparisons").glob("*.json"))), 1)
        self.assertEqual(sorted(outcome["created"] for outcome in outcomes).count(True), 1)

    def test_a_cutoff_keeps_later_rows_out(self):
        self.package()
        self.events()
        result = insights.check(CHECK.encode(), self.folders(), self.clock, cutoff=date(2026, 9, 20))
        record = json.loads(next((self.insights / "checks").glob("*.json")).read_text("utf-8"))
        self.assertEqual((result["package"]["cutoff"], result["package"]["last_date"]), ("2026-09-20", "2026-09-18"))
        self.assertEqual(record["occasions"]["2026-09-16"]["problem"], "window_not_in_data")
        for path in self.results():  # No stored observation is dated after the cutoff.
            stored = json.loads(path.read_text("utf-8"))
            self.assertTrue(all(day <= "2026-09-20" for rows in stored["inputs"].values() for day, _ in rows))


class ReadTests(Harness):
    def test_reads_and_a_restart_write_nothing_and_make_no_outside_connection(self):
        self.package()
        self.events()
        self.check()
        attempts = []
        original = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return original(sock, address)
        before = tree(self.root)
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo",
                                                               side_effect=AssertionError("name lookup")):
            listed = self.listing()
            occasion = self.client.get("/api/insights/occasions/2026-09-16").json()
            band = self.client.get(f"/api/insights/events/capture/{self.captures[0]}").json()
            restarted = self.app()
            again = restarted.get("/api/insights").json()
        self.assertEqual((attempts, tree(self.root)), ([], before))
        self.assertEqual(again["check"], listed["check"])
        self.assertEqual(again["occasions"], listed["occasions"])
        self.assertEqual((band["state"], band["occasion"]["date"]), ("checked", "2026-09-16"))
        self.assertEqual(occasion["result"]["date"], "2026-09-16")

    def test_an_event_overview_band_before_and_after_a_check(self):
        self.package()
        self.events()
        band = self.client.get(f"/api/insights/events/inbox/{self.inbox_ids['U.S. crude oil production']}").json()
        self.assertEqual(band["state"], "not_checked")
        self.check()
        band = self.client.get(f"/api/insights/events/inbox/{self.inbox_ids['U.S. crude oil production']}").json()
        self.assertEqual(band["state"], "unsupported")
        self.assertEqual(self.client.get("/api/insights/events/other/x").status_code, 404)

    def test_findings_are_worded_from_the_stored_numbers_and_zero_findings_are_stated(self):
        flat = {(N10, day): "4.10" for day in (date(2026, 9, 15), date(2026, 9, 17))}
        flat.update({(R10, date(2026, 9, 15)): "1.80", (R10, date(2026, 9, 17)): "2.10"})  # Real +30, breakeven -30.
        self.package(overrides=flat)
        self.events()
        self.check()
        view = self.client.get("/api/insights/occasions/2026-09-16").json()["result"]
        offset = next(item for item in view["findings"] if item["check"] == "R1:10:W1")
        self.assertIn("+30 bp", offset["adds"])
        self.assertIn("-30 bp", offset["adds"])
        self.assertIn("Consistent with", offset["inference"])
        self.assertTrue(offset["alternatives"] and offset["strengthen"] and offset["weaken"])
        self.assertEqual(offset["frequency"]["sessions"], 30)
        self.assertEqual({key for key in offset["observations"]}, {"n10:W1", "r10:W1", "be10:W1"})
        measures = {row["key"]: row for row in view["measures"]}
        self.assertEqual((measures["n10:W1"]["change_bp"], measures["be10:W1"]["change_bp"]), ("0", "-30"))
        quiet = [row for row in self.listing()["occasions"] if row["findings"] == 0]
        self.assertTrue(quiet)  # The synthetic pattern leaves at least one occasion with nothing found.
        for row in quiet:
            shown = self.client.get(f"/api/insights/occasions/{row['date']}").json()["result"]
            self.assertTrue(shown["summary"].startswith("Checked: none of the"))
            self.assertTrue(shown["measures"])  # Quantified context is shown even when nothing is found.

    def test_an_occasion_where_nothing_meets_the_rules_says_so_and_still_shows_its_numbers(self):
        flat = lambda series_id, day: "4.25" if series_id == "RIFSRP_F02_N.B" else f"{insight_fakes.BASE[series_id]:.2f}"  # noqa: E731
        with patch("insight_fakes.pattern", flat):  # Constant yields: every change is 0, every rank 0.5.
            self.package()
        self.events()
        self.check()
        rows = self.listing()["occasions"]
        self.assertEqual({(row["state"], row["findings"]) for row in rows}, {("checked", 0)})
        shown = self.client.get("/api/insights/occasions/2026-09-16").json()["result"]
        self.assertEqual((shown["summary"], shown["findings"]),
                         ("Checked: none of the 12 evaluable rule checks met its conditions.", []))
        self.assertEqual({row["rank"] for row in shown["measures"]}, {"0.5000"})
        self.assertEqual(len(shown["other_checks"]), 12)

    def test_a_tampered_result_is_not_shown(self):
        self.package()
        self.events()
        self.check()
        path = next(path for path in self.results()
                    if json.loads(path.read_text("utf-8"))["context_date"] == "2026-09-16")
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text("utf-8"))
        record["inputs"][N10][-1][1] = "9.99"
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.client.get("/api/insights/occasions/2026-09-16").status_code, 409)
        row = next(row for row in self.listing()["occasions"] if row["date"] == "2026-09-16")
        self.assertEqual(row["state"], "problem")

    def tamper(self, path: Path, change) -> None:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        record = json.loads(path.read_text("utf-8"))
        change(record)
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_a_result_that_does_not_follow_from_its_own_inputs_is_not_shown(self):
        self.package()
        self.events()
        self.check()
        path = next(path for path in self.results()
                    if json.loads(path.read_text("utf-8"))["context_date"] == "2026-07-29")

        def claim_a_finding(record):  # Inputs, and so the ID, intact; one stored outcome the inputs do not give.
            next(item for item in record["evaluation"]["checks"] if item["outcome"] == "not_met")["outcome"] = "met"
        self.tamper(path, claim_a_finding)
        self.assertEqual(self.client.get("/api/insights/occasions/2026-07-29").status_code, 409)
        row = next(row for row in self.listing()["occasions"] if row["date"] == "2026-07-29")
        self.assertEqual(row["state"], "problem")
        self.assertIn("does not follow from its own inputs", row["detail"])
        other = next(path for path in self.results()
                     if json.loads(path.read_text("utf-8"))["context_date"] == "2026-06-17")
        self.tamper(other, lambda record: record.update(policy_changes=[{"date": "2026-06-17", "from": "4.00",
                                                                          "to": "3.75"}]))
        self.assertEqual(self.client.get("/api/insights/occasions/2026-06-17").status_code, 409)

    def test_check_and_comparison_records_that_do_not_verify_are_not_used(self):
        self.package()
        self.events()
        first = self.check()
        forged = json.loads((self.insights / "checks" / f"{first['check_id']}.json").read_text("utf-8"))
        forged["package"] = {**forged["package"], "package_id": "p-forged", "received_at": "2026-10-09T00:00:00+00:00"}
        forged["checked_at"] = "2099-01-01T00:00:00+00:00"  # Newest, but its content no longer hashes to its ID.
        (self.insights / "checks" / "forged.json").write_text(json.dumps(forged), encoding="utf-8")
        self.assertEqual(self.listing()["check"]["check_id"], first["check_id"])
        view = self.client.get("/api/insights/occasions/2026-09-16").json()
        self.assertEqual([item["package_id"] for item in view["provenance"]["attested_by"]],
                         [first["package"]["package_id"]])
        self.assertIsNotNone(self.listing()["comparison"])
        path = next((self.insights / "comparisons").glob("*.json"))
        self.tamper(path, lambda record: record.update(seed="another-seed"))
        self.assertIsNone(self.listing()["comparison"])
        result = self.client.get("/api/insights/occasions/2026-09-16").json()["result"]
        self.assertIsNone(result["comparison"])
        self.assertTrue(all(finding["frequency"] is None for finding in result["findings"]))


class RefusalTests(Harness):
    def test_no_package_a_wrong_body_or_a_foreign_page_is_refused(self):
        self.events()
        self.assertIn("No accepted H.15", self.check(expect=409)["detail"])
        self.package()
        refused = self.client.post("/api/insights/checks", headers=HEADERS, content=json.dumps({"check": True}))
        self.assertEqual(refused.status_code, 422)
        for headers in ({"Content-Type": "application/json", "X-Second-Order-Insights": "1"},
                        {"Origin": "http://evil.example", "Content-Type": "application/json",
                         "X-Second-Order-Insights": "1"}, {"Origin": BASE, "Content-Type": "application/json"}):
            self.assertEqual(self.client.post("/api/insights/checks", headers=headers, content=CHECK).status_code, 403)
        self.assertFalse(self.insights.exists())

    def test_the_evidence_is_read_strictly(self):
        changed = insight_fakes.keep(self.market, date(2026, 9, 30), datetime(2026, 10, 1, 12, tzinfo=UTC),
                                     attributes={R10: {"UNIT": "Percent"}})
        with self.assertRaisesRegex(insight_evidence.EvidenceRefused, "attributes"):
            insight_evidence.extract(self.market / "packages" / changed)
        missing = insight_fakes.keep(self.market, date(2026, 9, 30), datetime(2026, 10, 1, 13, tzinfo=UTC),
                                     omit=("RIFLGFCM03_N.B",))
        with self.assertRaisesRegex(insight_evidence.EvidenceRefused, "does not contain RIFLGFCM03_N.B"):
            insight_evidence.extract(self.market / "packages" / missing)
        declared = keep_package(self.market, release_zip(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>'
                                                         + insight_fakes.data(date(2026, 1, 2), date(2026, 3, 31))[
                                                             len(b'<?xml version="1.0" encoding="UTF-8" '
                                                                 b'standalone="no"?>'):]),
                                datetime(2026, 10, 1, 14, tzinfo=UTC))
        with self.assertRaises(insight_evidence.EvidenceRefused):  # Not accepted: a declaration in the data entry.
            insight_evidence.extract(self.market / "packages" / declared)


class DocumentationTests(unittest.TestCase):
    def test_the_method_page_states_the_definitions_the_code_uses(self):
        source = (Path(__file__).resolve().parent.parent / "frontend/src/pages/MethodPage.tsx").read_text(encoding="utf-8")
        section = " ".join(source[source.index('<Section id="findings"'):source.index('<Section id="scope"')].split())
        rules, comparison = insight_rules, insights.COMPARISON
        self.assertIn(f"against the {rules.REFERENCE_WINDOWS} windows of the same span that end on or before", section)
        self.assertIn(f"at least {rules.MINIMUM_ELIGIBLE} eligible windows are required", section)
        self.assertEqual(len(rules.CHECKS), 12)
        self.assertIn("twelve rule checks", section)
        self.assertEqual(sorted(rules.RULES), ["R1", "R2", "R3", "R4"])
        self.assertIn(f"{comparison['size']} comparison sessions (drawn by a recorded seed from "
                      f"{comparison['first'].year} to {comparison['last'].year}", section)
        self.assertEqual(len(rules.YIELDS), 6)


if __name__ == "__main__":
    unittest.main()
