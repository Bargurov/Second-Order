"""Publication import (publication-import-0.1, publication-retrieval-0.1) from a SYNTHETIC inbox to a SYNTHETIC
account's own source: one bounded request for an allowlisted page (or the retained copy), the release's words with
their provenance and publication time, an explicit confirmation of that exact text, the Inbox origin a later research
request binds, and every refusal leaving nothing behind but the record of what was requested. Pages and feeds are
served by simulated networks; the provider is the fake from account_fakes.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx

from account_fakes import USER_WRITE, World, every_file
from second_order import event_links, publication_import, research_analysis as ra, user_news, user_research
from second_order.accounts import AccountsRefused, Identity

from news_fakes import PAGE_TYPE, Pages, fed_link, fed_page, refreshed, standard_feeds
from test_event_inbox import rss_item


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.world = World(self.root)
        self.world.standard_terms(credits=40, limit=3)
        self.folders = publication_import.Folders(inbox=self.root / "event-inbox", imports=self.root / "imports")
        refreshed(self.folders.inbox)
        self.pages = Pages({fed_link(1): (200, fed_page())})
        self.fetcher = publication_import.PublicationFetcher(self.pages.transport())
        self.context = user_research.UserResearch(self.world.accounts, self.world.folders, self.world.sender(),
                                                  self.world.clock)
        self.a, self.b = self.identity("reader-a"), self.identity("reader-b")

    def identity(self, username: str) -> Identity:
        return Identity(self.world.ids[username], username, f"{username} (synthetic)", "user")

    def news_entry(self, title: str = "Simulated Committee issues synthetic statement", who: Identity | None = None):
        shown = user_news.view(self.folders, who or self.a, [], "all")
        return next(entry for entry in shown["entries"] if entry["title"] == title)

    def prepare(self, who: Identity | None = None, entry: dict | None = None) -> tuple[dict, bool]:
        entry = entry or self.news_entry()
        return publication_import.prepare(self.folders, who or self.a, entry["entry_id"], entry["version_sha256"],
                                          self.fetcher, self.world.clock)

    def confirm(self, preview: dict, who: Identity | None = None, **body) -> tuple[dict, bool]:
        payload = {"text_sha256": preview["proposed_source"]["text_sha256"], "confirm": True} | body
        return publication_import.confirm(self.folders, self.context, who or self.a, preview["import_id"], payload,
                                          self.world.clock)

    def refused(self, call, status: int, code: str) -> AccountsRefused:
        with self.assertRaises(AccountsRefused) as caught:
            call()
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code), str(caught.exception))
        return caught.exception


class Preview(Base):
    def test_a_preview_requests_the_one_page_and_shows_its_words_with_provenance(self):
        entry = self.news_entry()
        self.assertEqual(entry["import"], {"state": "supported", "reason": None, "source_ids": []})
        self.assertTrue(publication_import.needs_fetch(self.folders, entry["entry_id"], entry["version_sha256"]))
        preview, created = self.prepare(entry=entry)
        self.assertTrue(created)
        self.assertEqual([str(request.url) for request in self.pages.requests], [fed_link(1)])
        request = self.pages.requests[0]
        self.assertEqual((request.method, request.headers["accept"]), ("GET", "text/html"))
        self.assertNotIn("contact", request.headers["user-agent"])
        self.assertEqual(preview["state"], "ready")
        proposed = preview["proposed_source"]
        self.assertEqual((proposed["headline"], proposed["source_url"], proposed["published_at"], proposed["paragraphs"]),
                         ("Simulated Committee issues synthetic statement", fed_link(1), "2026-09-16T18:00:00+00:00", 3))
        self.assertIn("Wed, 16 Sep 2026 18:00:00 GMT", proposed["published_basis"])
        self.assertIn("For release at 2:00 p.m. EDT", proposed["published_basis"])
        self.assertEqual(proposed["text_sha256"], hashlib.sha256(proposed["text"].encode("utf-8")).hexdigest())
        self.assertEqual(preview["publication"]["retrieval"], "fetched")
        self.assertEqual(preview["publication"]["sha256"], hashlib.sha256(fed_page()).hexdigest())
        self.assertEqual(preview["publication"]["last_modified"], PAGE_TYPE["last-modified"])
        self.assertEqual(preview["entry"]["attribution"], "Source: Board of Governors of the Federal Reserve System")
        self.assertEqual([row["kind"] for row in preview["left_out"]],
                         ["share_controls", "contact_line", "linked_document", "last_update"])
        self.assertIsNone(preview["source_id"])
        self.assertIn("Nothing has been analysed", preview["statements"][-1])
        self.assertNotIn(self.a.user_id, json.dumps(preview))  # The projection names no account.
        self.assertEqual(self.world.client("reader-a").get("/api/user/sources").json()["sources"], [])

    def test_the_request_and_the_bytes_are_recorded_once_and_reused(self):
        first, _ = self.prepare()
        (record,) = publication_import.retrievals(self.folders)
        self.assertEqual((record["number"], record["outcome"], record["url"], record["requested_by"]),
                         (1, "accepted", fed_link(1), self.a.user_id))
        self.assertEqual(record["request"], {"method": "GET", "redirects_followed": False, "retries": 0,
                                             "user_agent": publication_import.USER_AGENT})
        self.assertEqual((record["response"]["http_status"], record["body"]["state"]), (200, "complete"))
        raw = self.folders.raw / record["kept"]
        self.assertEqual(raw.read_bytes(), fed_page())
        again, created = self.prepare()
        self.assertEqual((again["import_id"], created, len(self.pages.requests)), (first["import_id"], False, 1))
        other, created = self.prepare(self.b)
        self.assertTrue(created)
        self.assertNotEqual(other["import_id"], first["import_id"])
        self.assertEqual((other["publication"]["retrieval"], len(self.pages.requests)), ("reused", 1))
        self.assertEqual(len(publication_import.retrievals(self.folders)), 1)
        entry = self.news_entry()
        self.assertFalse(publication_import.needs_fetch(self.folders, entry["entry_id"], entry["version_sha256"]))

    def test_reading_an_import_writes_nothing_and_another_account_gets_not_found(self):
        preview, _ = self.prepare()
        before = every_file(self.root)
        self.assertEqual(publication_import.read(self.folders, self.a, preview["import_id"], self.world.clock), preview)
        self.assertEqual(every_file(self.root), before)
        self.refused(lambda: publication_import.read(self.folders, self.b, preview["import_id"]), 404, "not_found")
        self.refused(lambda: publication_import.read(self.folders, self.a, "imp-0000000000000000"), 404, "not_found")
        self.refused(lambda: publication_import.read(self.folders, self.a, "../previews"), 404, "not_found")

    def test_a_retained_page_that_changed_is_never_shown_as_this_import(self):
        preview, _ = self.prepare()
        (record,) = publication_import.retrievals(self.folders)
        raw = self.folders.raw / record["kept"]
        raw.chmod(0o600)
        raw.write_bytes(fed_page(paragraphs=("A different synthetic paragraph.",)))
        shown = publication_import.read(self.folders, self.a, preview["import_id"], self.world.clock)
        self.assertEqual((shown["state"], shown["proposed_source"]["text"]), ("unreadable", None))
        self.refused(lambda: self.confirm(preview), 409, "publication_changed")


class Refusals(Base):
    def test_publishers_without_an_extractor_and_entries_without_a_stated_time_are_not_imported(self):
        for title in ("Synthetic trade forecast update", "Synthetic natural gas storage rises"):
            entry = self.news_entry(title)
            self.assertEqual(entry["import"]["state"], "unsupported")
            self.assertIn("paste its text", entry["import"]["reason"])
            error = self.refused(lambda: self.prepare(entry=entry), 409, "import_unsupported")
            self.assertTrue(error.extra["paste_instead"])
        refreshed(self.folders.inbox, standard_feeds(fed_items=[
            rss_item(3, title="Synthetic release without a time", pub="Wed, 16 Sep 2026 18:00:00 XYZ"),
            rss_item(4, title="Synthetic page elsewhere", link="https://www.federalreserve.gov/monetarypolicy.htm")]))
        for title in ("Synthetic release without a time", "Synthetic page elsewhere"):
            self.refused(lambda: self.prepare(entry=self.news_entry(title)), 409, "import_unsupported")
        self.assertEqual((self.pages.requests, publication_import.retrievals(self.folders)), ([], []))

    def test_an_unknown_or_changed_entry_version_is_refused_before_any_request(self):
        entry = self.news_entry()
        self.refused(lambda: publication_import.prepare(self.folders, self.a, entry["entry_id"], "0" * 64, self.fetcher,
                                                        self.world.clock), 409, "entry_changed")
        self.refused(lambda: publication_import.prepare(self.folders, self.a, "nowhere:abc", entry["version_sha256"],
                                                        self.fetcher, self.world.clock), 404, "not_found")
        self.assertEqual(self.pages.requests, [])

    def test_publisher_failures_leave_a_record_and_nothing_imported(self):
        cases = {"HTTP 404": (404, b"missing", {"content-type": "text/html"}),
                 "redirects": (301, b"", {"location": "https://www.federalreserve.gov/elsewhere.htm"}),
                 "the limit is": (200, b"x" * (publication_import.MAX_BYTES + 1), PAGE_TYPE)}
        for number, (words, answer) in enumerate(cases.items(), start=1):
            self.pages.answers[fed_link(1)] = answer
            error = self.refused(self.prepare, 409, "publication_unavailable")
            self.assertIn(words, str(error))
            self.assertTrue(error.extra["paste_instead"])
            record = publication_import.retrievals(self.folders)[-1]
            self.assertEqual((record["number"], record["outcome"], record["kept"]), (number, "failed", None))
        self.assertEqual(len(self.pages.requests), 3)  # One request each: no retry, no redirect followed.
        self.assertFalse(self.folders.previews.exists())

    def test_a_page_that_cannot_be_read_is_kept_as_evidence_and_refused(self):
        for answer, words in (((200, b"%PDF-1.7", {"content-type": "application/pdf"}), "application/pdf"),
                              ((200, b"<html><body><p>Another layout</p></body></html>", PAGE_TYPE), "layout")):
            self.pages.answers[fed_link(1)] = answer
            error = self.refused(self.prepare, 422, "publication_unreadable")
            self.assertIn(words, str(error))
            record = publication_import.retrievals(self.folders)[-1]
            self.assertEqual(record["outcome"], "refused")
        layout = publication_import.retrievals(self.folders)[-1]
        self.assertEqual((self.folders.raw / layout["kept"]).read_bytes(), b"<html><body><p>Another layout</p></body></html>")
        self.assertFalse(self.folders.previews.exists())

    def test_a_kept_page_is_read_again_by_a_later_import_and_never_requested_twice(self):
        """As in the controlled retrieval of 2026-10-14: the first reading failed (there, an extractor defect, since
        fixed); a later import reads the kept bytes again and the publisher is not contacted again."""
        real = publication_import._extract
        calls = []

        def first_fails(raw: bytes, content_type: str) -> dict:
            calls.append(1)
            if len(calls) == 1:
                raise publication_import.fed_publication.Unreadable("A synthetic reading failure")
            return real(raw, content_type)

        with patch.object(publication_import, "_extract", side_effect=first_fails):
            self.refused(self.prepare, 422, "publication_unreadable")
            preview, created = self.prepare()
        self.assertTrue(created)
        self.assertEqual((preview["publication"]["retrieval"], len(self.pages.requests)), ("reused", 1))
        (record,) = publication_import.retrievals(self.folders)
        self.assertEqual((record["outcome"], record["detail"]), ("refused", "A synthetic reading failure"))
        self.pages.answers[fed_link(1)] = (200, b"<html><body><p>Another layout</p></body></html>", PAGE_TYPE)
        other = self.news_entry(who=self.b)
        self.prepare(self.b, other)
        self.assertEqual(len(self.pages.requests), 1)

    def test_a_printed_date_or_time_that_disagrees_with_the_feed_refuses_the_import(self):
        for page in (fed_page(date_line="September 17, 2026"), fed_page(release_line="For release at 2:30 p.m. EDT"),
                     fed_page(release_line="For release at 2:00 p.m. EST")):
            self.pages.answers[fed_link(1)] = (200, page)
            for path in (self.folders.retrievals.iterdir() if self.folders.retrievals.exists() else []):
                path.chmod(0o600)
                path.unlink()  # A fresh retrieval each time, as the page differs.
            self.refused(self.prepare, 409, "publication_time_conflict")
        self.assertFalse(self.folders.previews.exists())

    def test_a_page_without_a_printed_time_uses_the_feeds_stated_time(self):
        self.pages.answers[fed_link(1)] = (200, fed_page(release_line=None))
        preview, _ = self.prepare()
        self.assertEqual(preview["proposed_source"]["published_at"], "2026-09-16T18:00:00+00:00")
        self.assertIn("without a time of day", preview["proposed_source"]["published_basis"])

    def test_every_refused_preview_says_whether_the_publisher_was_contacted(self):
        """For usage counting: `requested` is true exactly when this preview contacted the publisher."""
        def requested(code: str, status: int, call=None) -> bool:
            return self.refused(call or self.prepare, status, code).extra["requested"]

        wto = self.news_entry("Synthetic trade forecast update")
        self.assertFalse(requested("import_unsupported", 409, lambda: self.prepare(entry=wto)))
        entry = self.news_entry()
        self.assertFalse(requested("entry_changed", 409, lambda: publication_import.prepare(
            self.folders, self.a, entry["entry_id"], "0" * 64, self.fetcher, self.world.clock)))
        with publication_import.FETCHING:
            self.assertFalse(requested("import_in_progress", 409))
        self.assertEqual(self.pages.requests, [])
        self.pages.answers[fed_link(1)] = (404, b"missing", {"content-type": "text/html"})
        self.assertTrue(requested("publication_unavailable", 409))
        self.pages.answers[fed_link(1)] = (200, fed_page(date_line="September 17, 2026"))
        self.assertTrue(requested("publication_time_conflict", 409))
        self.assertFalse(requested("publication_time_conflict", 409))  # The kept page is read again.
        minutes = self.news_entry("Synthetic minutes of the Committee")
        self.pages.answers[fed_link(2)] = (200, b"<html><body><p>Another layout</p></body></html>", PAGE_TYPE)
        self.assertTrue(requested("publication_unreadable", 422, lambda: self.prepare(entry=minutes)))
        self.assertFalse(requested("publication_unreadable", 422, lambda: self.prepare(entry=minutes)))
        self.assertEqual([str(request.url) for request in self.pages.requests],
                         [fed_link(1), fed_link(1), fed_link(2)])

    def test_one_retrieval_at_a_time(self):
        with publication_import.FETCHING:
            self.refused(self.prepare, 409, "import_in_progress")
        self.assertEqual(self.pages.requests, [])
        self.prepare()


class Confirmation(Base):
    def test_confirming_saves_exactly_the_previewed_text_as_the_users_own_source_once(self):
        preview, _ = self.prepare()
        self.refused(lambda: self.confirm(preview, text_sha256="0" * 64), 409, "publication_changed")
        self.refused(lambda: self.confirm(preview, confirm=False), 422, "invalid_request")
        self.refused(lambda: self.confirm(preview, who=self.b), 404, "not_found")
        result, created = self.confirm(preview)
        self.assertTrue(created)
        source = result["source"]
        self.assertEqual((source["headline"], source["source_url"], source["published_at_as_supplied"], source["text"]),
                         (preview["proposed_source"]["headline"], fed_link(1), "2026-09-16T18:00:00+00:00",
                          preview["proposed_source"]["text"]))
        self.assertEqual((result["import"]["state"], result["import"]["source_id"]), ("confirmed", source["source_id"]))
        again, created = self.confirm(preview)
        self.assertEqual((created, again["source"]["source_id"]), (False, source["source_id"]))
        mine = self.world.client("reader-a").get("/api/user/sources").json()["sources"]
        self.assertEqual([row["source_id"] for row in mine], [source["source_id"]])
        self.assertEqual(self.world.client("reader-b").get("/api/user/sources").json()["sources"], [])
        self.assertEqual(self.news_entry()["import"], {"state": "imported", "reason": None,
                                                       "source_ids": [source["source_id"]]})
        self.assertEqual(self.news_entry(who=self.b)["import"]["state"], "supported")

    def test_the_entry_version_is_recorded_as_the_sources_origin_and_bound_by_a_research_request(self):
        preview, _ = self.prepare()
        result, _ = self.confirm(preview)
        capture_id = result["source"]["source_id"]
        link = event_links.verified_link(self.world.folders.links, capture_id, self.world.folders.intake)
        self.assertEqual((link["inbox"]["item_id"], link["inbox"]["content_sha256"]),
                         (preview["entry"]["entry_id"], preview["entry"]["version_sha256"]))
        client = self.world.client("reader-a")
        reply = client.post("/api/user/analyses", headers=USER_WRITE, json={"source_id": capture_id, "effort": "high"})
        self.assertEqual(reply.status_code, 201, reply.text)
        analysis_id = reply.json()["analysis"]["analysis_id"]
        origin = ra.verified_request(analysis_id, self.world.folders)["manifest"]["origin"]
        self.assertEqual((origin["state"], origin["item_id"]), ("verified", preview["entry"]["entry_id"]))
        # The existing exact quote, approval and one send apply unchanged (fake provider, synthetic credits).
        quote = client.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        run = client.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE,
                          json={"quote_id": quote["quote_id"], "effort": "high", "credits": quote["credits"],
                                "approve": True})
        self.assertEqual(run.status_code, 201, run.text)
        self.assertEqual(run.json()["analysis"]["state"], "recorded")
        self.assertEqual(len(self.world.provider.requests), 1)

    def test_a_confirmation_is_exclusive_and_an_interrupted_one_is_not_repeated(self):
        preview, _ = self.prepare()
        claim = self.folders.claims / f"{preview['import_id']}.json"
        claim.parent.mkdir(parents=True)
        claim.write_text(json.dumps({"import_id": preview["import_id"], "user_id": self.a.user_id,
                                     "claimed_at": self.world.clock().isoformat()}))
        self.refused(lambda: self.confirm(preview), 409, "import_in_progress")
        self.world.clock.advance(minutes=3)
        self.assertEqual(publication_import.read(self.folders, self.a, preview["import_id"], self.world.clock)["state"],
                         "interrupted")
        self.refused(lambda: self.confirm(preview), 409, "import_interrupted")
        self.assertEqual(self.world.client("reader-a").get("/api/user/sources").json()["sources"], [])

    def test_two_simultaneous_confirmations_make_one_source(self):
        preview, _ = self.prepare()
        start, outcomes = threading.Barrier(2), []

        def confirm():
            start.wait()
            try:
                outcomes.append(self.confirm(preview)[1])
            except AccountsRefused as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # The loser either finds the claim (in progress) or, if the winner already finished, the confirmation.
        self.assertIn(sorted(map(str, outcomes)), (["True", "import_in_progress"], ["False", "True"]))
        self.assertEqual(len(self.world.client("reader-a").get("/api/user/sources").json()["sources"]), 1)
        self.assertEqual(self.confirm(preview)[1], False)

    def test_a_second_retrieval_while_one_is_in_flight_is_refused_not_queued(self):
        refreshed(self.folders.inbox, standard_feeds(fed_items=[
            rss_item(1, title="Simulated Committee issues synthetic statement"),
            rss_item(2, title="Synthetic second statement")]))
        inside, release = threading.Event(), threading.Event()

        def slow(request):
            inside.set()
            release.wait(10)
            return Pages({str(request.url): (200, fed_page())})(request)

        self.fetcher = publication_import.PublicationFetcher(httpx.MockTransport(slow))
        first = threading.Thread(target=self.prepare)
        first.start()
        inside.wait(10)
        try:
            second = self.news_entry("Synthetic second statement")
            self.refused(lambda: self.prepare(entry=second), 409, "import_in_progress")
        finally:
            release.set()
            first.join()
        self.assertEqual(len(publication_import.retrievals(self.folders)), 1)

    def test_a_refused_source_releases_its_claim_and_creates_nothing(self):
        preview, _ = self.prepare()
        refusal = user_research.refused(422, "invalid_source", "Synthetic refusal.")
        with patch.object(user_research, "add_source", side_effect=refusal):
            self.refused(lambda: self.confirm(preview), 422, "invalid_source")
        self.assertFalse((self.folders.claims / f"{preview['import_id']}.json").exists())
        result, created = self.confirm(preview)
        self.assertTrue(created)

    def test_an_entry_version_no_longer_held_cannot_become_an_origin(self):
        preview, _ = self.prepare()
        for path in sorted(self.folders.inbox.rglob("*"), reverse=True):
            if path.is_file():
                path.chmod(0o600)
                path.unlink()
        self.refused(lambda: self.confirm(preview), 409, "entry_changed")
        self.assertFalse((self.folders.claims / f"{preview['import_id']}.json").exists())


if __name__ == "__main__":
    unittest.main()
