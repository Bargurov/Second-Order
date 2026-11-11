"""Retrieval records (inbox_acquisitions): one write-once record per feed request an explicit refresh made, with its
endpoint, times, status, headers and cache validators, body completeness and SHA-256, parser version, item provenance
and how its entries compared with what was held before. On SYNTHETIC feeds through a counting fake network only, in
temporary folders: nothing reaches a network, calls a model or touches data/.
"""
from datetime import datetime, timezone
import json
import os
import stat
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx

from test_event_inbox import (BASE, CPI, EIA, EMPSIT, FED, INBOX_HEADERS, MAX_BYTES, QUIET, WTO, Folder, Network,
                              atom, atom_entry, clock, eia_item, eia_rss, fingerprint, rss, rss_item, standard,
                              wto_item, wto_rss)
from test_headline_triage import FED_LINK, STATEMENT, Provider, Triage, feeds, rich_reply
from second_order import event_inbox, inbox_acquisitions, inbox_archive
from second_order.api import create_app
from second_order.headline_triage import fingerprint as entry_fingerprint, snapshot_item

LATER = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
HEADERS = [("content-type", "text/xml; charset=utf-8"), ("etag", '"feed-v1"'),
           ("last-modified", "Wed, 07 Oct 2026 10:00:00 GMT"), ("cache-control", "max-age=300"),
           ("set-cookie", "session=never-kept"), ("set-cookie", "tracking=never-kept"), ("x-served-by", "cache-1")]


def records(inbox, key: str) -> list[dict]:
    found, bad = inbox_acquisitions.records(inbox, key, event_inbox.SOURCES[key].feed_url)
    assert bad == [], bad
    return found


class RecordTests(Folder):
    def test_an_accepted_request_records_endpoint_status_validators_body_parser_and_items(self):
        answers = standard()
        answers[FED] = [(200, rss([rss_item(1), rss_item(2, title="T" * 400)]), HEADERS)]
        result = event_inbox.refresh(self.inbox, Network(answers).fetcher(), clock())
        (record,) = records(self.inbox, "fed-monetary")
        self.assertEqual((record["number"], record["endpoint"], record["outcome"], record["request"]),
                         (1, FED, "accepted", {"method": "GET", "conditional": False, "redirects_followed": False,
                                               "retries": 0, "contact_sent": True}))
        response = record["response"]
        self.assertEqual((response["http_status"], response["validators"]),
                         (200, {"etag": '"feed-v1"', "last_modified": "Wed, 07 Oct 2026 10:00:00 GMT"}))
        self.assertEqual((response["headers"]["cache-control"], response["set_cookie_count"],
                          response["other_header_names"]), ("max-age=300", 2, ["x-served-by"]))
        self.assertNotIn("never-kept", json.dumps(record))  # Set-Cookie values are never kept.
        success = json.loads((self.inbox / "fed-monetary.json").read_text(encoding="utf-8"))["last_success"]
        self.assertEqual((record["body"]["state"], record["body"]["bytes"], record["body"]["sha256"]),
                         ("complete", success["bytes"], success["sha256"]))
        self.assertEqual(record["body"]["kept"], f"{success['sha256']}.xml")
        self.assertEqual((record["parser"]["version"], record["parser"]["listed"], record["parser"]["retained"]),
                         (event_inbox.PARSER_VERSION, 2, 2))
        self.assertEqual([(row["position"], row["content_sha256"], row["text"]) for row in record["items"]],
                         [(item["position"], inbox_archive.content_sha256(item), {
                             "title": "shortened" if item["title_truncated"] else "as_supplied", "excerpt": "none"})
                          for item in success["items"]])
        self.assertEqual(record["changes"]["basis"], "none")
        self.assertEqual(len(record["changes"]["new"]), 2)
        fed = next(row for row in result["refreshed"] if row["source"] == "fed-monetary")
        self.assertEqual((fed["acquisition"]["counts"]["new"], fed["acquisition"]["kept_copy"]), (2, "verified"))
        path = inbox_acquisitions.folder(self.inbox, "fed-monetary") / "000001.json"
        self.assertFalse(os.stat(path).st_mode & stat.S_IWRITE)  # Written once, read-only.

    def test_failures_are_recorded_with_what_did_arrive_and_never_retried(self):
        cases = {
            "an error status": ((503, b"busy", {"content-type": "text/plain", "retry-after": "120"}),
                                "failed", "not_read", 503),
            "a redirect": ((301, b"", {"location": "https://mirror.example.org/feed.xml"}), "failed", "not_read", 301),
            "no response": (httpx.ConnectTimeout("simulated"), "failed", "none", None),
            "an oversize body": ((200, iter([b"x" * (MAX_BYTES // 4)] * 5), {"content-type": "text/xml"}),
                                 "failed", "partial", 200),
            "a web page": ((200, b"<html>Access denied</html>", {"content-type": "text/html"}), "refused", "complete",
                           200),
        }
        for name, (answer, outcome, body_state, status) in cases.items():
            with self.subTest(name):
                inbox = self.root / name.replace(" ", "-")
                network = Network({**standard(), FED: [answer]})
                event_inbox.refresh(inbox, network.fetcher(), clock())
                self.assertEqual(network.urls().count(FED), 1)  # One request, no retry, no redirect followed.
                (record,) = records(inbox, "fed-monetary")
                self.assertEqual((record["outcome"], record["body"]["state"], (record["response"] or {}).get(
                    "http_status"), record["body"]["kept"], record["items"]), (outcome, body_state, status, None, []))
                self.assertTrue(record["detail"])
                self.assertFalse((inbox / "raw" / "fed-monetary").exists())
                if body_state == "partial":
                    self.assertGreater(record["body"]["bytes"], MAX_BYTES)
                    self.assertTrue(record["body"]["sha256"])
                if name == "a redirect":
                    self.assertEqual(record["response"]["headers"]["location"], "https://mirror.example.org/feed.xml")
                # A failed source never stops the independent sources from being recorded.
                self.assertEqual([row["outcome"] for row in records(inbox, "eia-todayinenergy")], ["accepted"])
                self.assertEqual([row["outcome"] for row in records(inbox, "wto-news")], ["accepted"])

    def test_a_source_that_was_not_requested_has_no_record(self):
        network = Network(standard())
        event_inbox.refresh(self.inbox, network.fetcher(contact=None), clock())
        self.assertNotIn(CPI, network.urls())
        self.assertEqual(records(self.inbox, "bls-cpi"), [])
        self.assertEqual([row["outcome"] for row in records(self.inbox, "fed-monetary")], ["accepted"])
        source = next(row for row in event_inbox.inbox_view(self.inbox)["sources"] if row["key"] == "bls-cpi")
        self.assertEqual((source["state"], source["acquisitions"]["count"]), ("not_requested", 0))

    def test_a_record_that_cannot_be_written_is_a_note_not_a_failed_refresh(self):
        with patch("second_order.inbox_acquisitions.keep", side_effect=PermissionError("denied")):
            result = event_inbox.refresh(self.inbox, Network(standard()).fetcher(), clock())
        fed = next(row for row in result["refreshed"] if row["source"] == "fed-monetary")
        self.assertEqual((fed["outcome"], fed["acquisition"]), ("ok", None))
        self.assertIn("retrieval record could not be written (PermissionError)", fed["detail"])
        self.assertEqual(len(event_inbox.inbox_view(self.inbox)["items"]), 4)

    def test_a_damaged_record_is_reported_never_used_or_rewritten(self):
        event_inbox.refresh(self.inbox, Network(standard()).fetcher(), clock())
        event_inbox.refresh(self.inbox, Network(standard()).fetcher(), clock(LATER))
        newest = inbox_acquisitions.folder(self.inbox, "fed-monetary") / "000002.json"
        os.chmod(newest, stat.S_IREAD | stat.S_IWRITE)
        newest.write_text("{not json", encoding="utf-8")
        before = fingerprint(self.inbox)
        found, bad = inbox_acquisitions.records(self.inbox, "fed-monetary", FED)
        self.assertEqual(([row["number"] for row in found], [row["file"] for row in bad]), ([1], ["000002.json"]))
        source = next(row for row in event_inbox.inbox_view(self.inbox)["sources"] if row["key"] == "fed-monetary")
        self.assertEqual((source["acquisitions"]["latest"]["number"], len(source["acquisitions"]["unreadable_newer"])),
                         (1, 1))
        self.assertEqual(fingerprint(self.inbox), before)  # Reading repairs and writes nothing.
        event_inbox.refresh(self.inbox, Network(standard()).fetcher(),
                            clock(datetime(2026, 10, 10, tzinfo=timezone.utc)))
        self.assertEqual(newest.read_text(encoding="utf-8"), "{not json")  # A new number; the damaged one stays.
        self.assertEqual([row["number"] for row in records_ok(self.inbox)], [1, 3])


def records_ok(inbox) -> list[dict]:
    return inbox_acquisitions.records(inbox, "fed-monetary", FED)[0]


class ChangeTests(Folder):
    def refresh(self, answers: dict, moment: datetime) -> dict:
        result = event_inbox.refresh(self.inbox, Network(answers).fetcher(), clock(moment))
        return {row["source"]: row for row in result["refreshed"]}

    def test_an_unchanged_refresh_reuses_every_entry_and_its_fingerprints(self):
        self.refresh(standard(), datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
        view = event_inbox.inbox_view(self.inbox)
        prints = {item["id"]: (item["content_sha256"], entry_fingerprint(snapshot_item(item)), item["first_seen_at"])
                  for item in view["items"]}
        archive = fingerprint(self.inbox / "archive")
        second = self.refresh(standard(), LATER)
        self.assertEqual(second["fed-monetary"]["acquisition"]["counts"],
                         {"new": 0, "changed": 0, "unchanged": 2, "no_longer_listed": 0, "skipped": 0, "duplicates": 0,
                          "not_retained": 0, "basis": "archive"})
        again = event_inbox.inbox_view(self.inbox)
        self.assertEqual({item["id"]: (item["content_sha256"], entry_fingerprint(snapshot_item(item)),
                                       item["first_seen_at"]) for item in again["items"]}, prints)
        self.assertTrue(all(item["retrieved_at"].startswith("2026-10-09") for item in again["items"]))  # Moved on.
        versions = [len(entry["versions"]) for entry in json.loads(
            (self.inbox / "archive" / "fed-monetary.json").read_text(encoding="utf-8"))["entries"]]
        self.assertEqual((versions, len(again["items"])), ([1, 1], 4))  # No duplicate entry or version.
        self.assertNotEqual(fingerprint(self.inbox / "archive"), archive)  # Only last-seen times moved.
        self.assertEqual(len(list((self.inbox / "raw" / "fed-monetary").glob("*.xml"))), 1)  # One shared copy.

    def test_reordering_the_feed_changes_positions_only(self):
        self.refresh(standard(), datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
        swapped = standard()
        swapped[FED] = [(200, rss([rss_item(2, pub="Wed, 29 Jul 2026 18:00:00 GMT"),
                                   rss_item(1, pub="Wed, 16 Sep 2026 18:00:00 GMT")]))]
        second = self.refresh(swapped, LATER)
        self.assertEqual((second["fed-monetary"]["acquisition"]["counts"]["unchanged"],
                          second["fed-monetary"]["acquisition"]["counts"]["changed"]), (2, 0))
        (first, latest) = records(self.inbox, "fed-monetary")
        by_id = lambda record: {row["id"]: row for row in record["items"]}  # noqa: E731
        for item_id, row in by_id(first).items():
            self.assertEqual(row["content_sha256"], by_id(latest)[item_id]["content_sha256"])
            self.assertNotEqual(row["position"], by_id(latest)[item_id]["position"])

    def test_one_new_old_dated_item_is_new_to_the_archive_not_newly_published(self):
        self.refresh(standard(), datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
        added = standard()
        added[FED] = [(200, rss([rss_item(1, pub="Wed, 16 Sep 2026 18:00:00 GMT"),
                                 rss_item(2, pub="Wed, 29 Jul 2026 18:00:00 GMT"),
                                 rss_item(3, pub="Wed, 18 Jun 2025 18:00:00 GMT")]))]
        counts = self.refresh(added, LATER)["fed-monetary"]["acquisition"]["counts"]
        self.assertEqual((counts["new"], counts["unchanged"]), (1, 2))
        view = event_inbox.inbox_view(self.inbox)
        old = next(item for item in view["items"] if "2026091" + "3" in item["link"])
        self.assertEqual((old["feed_timestamp"]["raw"], old["feed_timestamp"]["instant_utc"], old["first_seen_at"]),
                         ("Wed, 18 Jun 2025 18:00:00 GMT", "2025-06-18T18:00:00+00:00", "2026-10-09T09:00:01+00:00"))
        self.assertEqual(view["items"][-1]["id"], old["id"])  # Ordered by its feed date, not by when it was retrieved.

    def test_changed_content_is_a_new_version_with_its_own_retrieval_provenance(self):
        self.refresh(standard(), datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
        before = next(item for item in event_inbox.inbox_view(self.inbox)["items"] if item["source"] == "fed-monetary"
                      and item["position"] == 1)
        edited = standard()
        edited[FED] = [(200, rss([rss_item(1, title="Synthetic Fed release 1 (corrected)",
                                           pub="Wed, 16 Sep 2026 18:00:00 GMT"),
                                  rss_item(2, pub="Wed, 29 Jul 2026 18:00:00 GMT")]))]
        counts = self.refresh(edited, LATER)["fed-monetary"]["acquisition"]["counts"]
        self.assertEqual((counts["changed"], counts["unchanged"], counts["new"]), (1, 1, 0))
        after = next(item for item in event_inbox.inbox_view(self.inbox)["items"] if item["id"] == before["id"])
        first, second = records(self.inbox, "fed-monetary")
        shas = lambda record: {row["id"]: row["content_sha256"] for row in record["items"]}  # noqa: E731
        self.assertEqual((shas(first)[before["id"]], shas(second)[before["id"]]),
                         (before["content_sha256"], after["content_sha256"]))
        self.assertEqual(second["changes"]["changed"], [before["id"]])
        (entry,) = [entry for entry in json.loads((self.inbox / "archive" / "fed-monetary.json").read_text(
            encoding="utf-8"))["entries"] if entry["id"] == before["id"]]
        self.assertEqual([version["content_sha256"] for version in entry["versions"]],
                         [before["content_sha256"], after["content_sha256"]])
        self.assertNotEqual(entry_fingerprint(snapshot_item(before)), entry_fingerprint(snapshot_item(after)))

    def test_same_titles_with_different_identities_stay_two_entries(self):
        same = standard()
        same[FED] = [(200, rss([rss_item(1, title="Federal Reserve issues FOMC statement"),
                                rss_item(2, title="Federal Reserve issues FOMC statement")]))]
        counts = self.refresh(same, datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))["fed-monetary"]["acquisition"]
        self.assertEqual(counts["counts"]["new"], 2)
        self.assertEqual(len({item["id"] for item in event_inbox.inbox_view(self.inbox)["items"]
                              if item["source"] == "fed-monetary"}), 2)

    def test_skipped_and_repeated_entries_are_counted_as_refused(self):
        bad = standard()
        bad[FED] = [(200, rss([rss_item(1), rss_item(2, link="https://example.org/x.htm", guid="x"),
                               rss_item(3, guid="dup"), rss_item(4, guid="dup")]))]
        counts = self.refresh(bad, datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))["fed-monetary"]["acquisition"]
        self.assertEqual((counts["counts"]["new"], counts["counts"]["skipped"], counts["counts"]["duplicates"]),
                         (2, 1, 1))


class ProcessingSeparationTests(Triage):
    def test_refreshes_never_classify_and_one_new_item_leaves_saved_results_reusable(self):
        provider = Provider(rich_reply)
        ids = [item["id"] for item in self.items]
        self.process(*ids, provider=provider)
        self.assertEqual(len(provider.requests), 1)
        triage = fingerprint(self.triage)
        added = feeds()
        added[FED] = [(added[FED][0][0], added[FED][0][1].replace(
            b"</channel>", rss_item(9, "Synthetic Fed release 9", FED_LINK.format("20261008z"),
                                    pub="Wed, 07 Oct 2026 18:00:00 GMT").encode("utf-8") + b"</channel>"))]
        with patch("second_order.triage_flow.dispatch", side_effect=AssertionError("a refresh must not triage")), \
                patch("second_order.headline_triage.build_request", side_effect=AssertionError("no request")):
            self.refresh(added, LATER)
        self.assertEqual((fingerprint(self.triage), len(provider.requests)), (triage, 1))  # Nothing was processed.
        new = self.id("Synthetic Fed release 9")
        view = self.view(*ids, new)
        self.assertEqual({row["input"]["id"]: row["status"] for row in view["items"]},
                         {**{item_id: "reuse" for item_id in ids}, new: "process"})
        self.assertEqual(view["plan"]["entries"], [new])  # Only the missing work would be requested.

    def test_reopening_and_restarting_read_the_same_records_without_any_request(self):
        statement = self.id(STATEMENT, "0916a")
        feeds_seen = Network({})
        app = lambda: create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",  # noqa: E731
                                 self.root / "intake", self.root / "attempts", inbox=self.inbox,
                                 feeds=feeds_seen.fetcher(), triage=self.triage, links=self.root / "links",
                                 market=self.root / "market", context=self.root / "no-bundle")
        before = fingerprint(self.root)
        pages = []
        for _ in range(2):  # Two server starts over the same folders.
            with TestClient(app(), base_url=BASE) as client:
                pages.append((client.get("/api/inbox").json(), client.get(f"/api/events/inbox/{statement}").json(),
                              client.get("/api/events/processing").json()))
        self.assertEqual(pages[0], pages[1])
        inbox, overview, index = pages[0]
        fed = next(source for source in inbox["sources"] if source["key"] == "fed-monetary")
        self.assertEqual((fed["acquisitions"]["count"], fed["acquisitions"]["latest"]["outcome"]), (1, "accepted"))
        self.assertEqual((overview["history"]["state"], overview["history"]["summary"]["retrievals"]),
                         ("not_processed", 1))
        self.assertEqual(index["items"], {})
        self.assertEqual((feeds_seen.requests, fingerprint(self.root)), ([], before))

    def test_the_refresh_route_returns_each_sources_counts(self):
        network = Network(feeds())
        app = create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                         self.root / "intake", self.root / "attempts", inbox=self.inbox, feeds=network.fetcher(),
                         triage=self.triage)
        with TestClient(app, base_url=BASE) as client:
            reply = client.post("/api/inbox/refresh", headers=INBOX_HEADERS, content="{}").json()
        rows = {row["source"]: row for row in reply["refreshed"]}
        self.assertEqual(rows["fed-monetary"]["acquisition"]["counts"]["unchanged"],
                         len([item for item in self.items if item["source"] == "fed-monetary"]))
        self.assertEqual(rows["fed-monetary"]["acquisition"]["number"], 2)
        self.assertEqual(network.urls().count(FED), 1)


class ViewTests(Folder):
    def test_entries_say_which_texts_were_supplied_and_whether_they_were_shortened(self):
        answers = {**standard(), EIA: [(200, eia_rss([eia_item(1, description="E" * 1300)]))],
                   WTO: [(200, wto_rss([wto_item(1, description="Synthetic trade news 1")]))],
                   EMPSIT: [(200, atom([atom_entry(1, content=None)]))]}
        event_inbox.refresh(self.inbox, Network(answers).fetcher(), clock())
        view = event_inbox.inbox_view(self.inbox)
        texts = {item["source"]: item["text"] for item in view["items"]}
        self.assertEqual(texts["eia-todayinenergy"], {"title": "as_supplied", "excerpt": "shortened"})
        self.assertEqual(texts["wto-news"], {"title": "as_supplied", "excerpt": "repeats_title"})
        self.assertEqual(texts["bls-empsit"], {"title": "as_supplied", "excerpt": "none"})
        self.assertEqual(texts["bls-cpi"], {"title": "as_supplied", "excerpt": "as_supplied"})
        sources = {source["key"]: source for source in view["sources"]}
        self.assertEqual((sources["wto-news"]["full_text_element"], sources["fed-monetary"]["full_text_element"]),
                         (True, False))
        latest = sources["eia-todayinenergy"]["acquisitions"]["latest"]
        self.assertEqual((latest["outcome"], latest["parser_version"], latest["kept_copy"], latest["counts"]["new"]),
                         ("accepted", event_inbox.PARSER_VERSION, "verified", 1))

    def test_an_empty_cache_reads_no_acquisitions_and_creates_nothing(self):
        view = event_inbox.inbox_view(self.inbox)
        self.assertEqual({source["acquisitions"]["count"] for source in view["sources"]}, {0})
        self.assertFalse(self.inbox.exists())
        self.assertEqual(QUIET.keys(), {EIA, WTO})
