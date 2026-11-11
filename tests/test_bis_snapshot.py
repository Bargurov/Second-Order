"""The retained BIS snapshot (bis_snapshot) and its explicit import into the Event Inbox (inbox_imports, snapshot_api).

Three input layers stay apart. Mechanics run on SYNTHETIC snapshots (tests/bis_snapshot_fakes.py) written into
temporary folders, with temporary indexes and inboxes, so a default run never reads the maintainer's retained page or
real Inbox. One opt-in test (SECOND_ORDER_BIS_SNAPSHOT_SOURCES=<the retained BIS folder>) extracts the real retained
page, read-only, and proves nothing in that folder changed.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import bis_snapshot_fakes as fakes
from test_event_inbox import EIA, FED, WTO, CPI, EMPSIT, Network, atom, clock, eia_item, eia_rss, rss, rss_item, wto_item, \
    wto_rss
from second_order import (bis_snapshot, event_inbox, event_links, headline_triage, inbox_archive, inbox_imports,
                          snapshot_api, triage_plan)
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"
REAL_SOURCES = "SECOND_ORDER_BIS_SNAPSHOT_SOURCES"  # Explicit opt-in: the maintainer's retained BIS folder, read-only.
BASE = "http://127.0.0.1:8137"
HEADERS = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Inbox": "1"}
CLOCK = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
CHIPS = "/press-release/synthetic-tightens-controls-advanced-computing-chips"
IMPLANTERS = "/press-release/synthetic-settlement-ion-implanters"


def key_of(path: str) -> str:
    return hashlib.sha256(f"https://www.bis.gov{path}".encode()).hexdigest()[:20]


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


def writable_rmtree(path: Path) -> None:
    shutil.rmtree(path, onexc=lambda remove, target, _: (os.chmod(target, stat.S_IWRITE), remove(target)))


class Folders(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-bis-snapshot-"))
        self.addCleanup(writable_rmtree, self.root)
        self.sources = fakes.write_snapshot(self.root / "sources", releases=fakes.standard_releases())
        self.index_dir = self.root / "index"
        self.inbox = self.root / "inbox"

    def opened(self, sources: Path | None = None) -> dict:
        return bis_snapshot.open_index(sources or self.sources, self.index_dir, lambda: CLOCK)[0]

    def record(self, index: dict, path: str) -> dict:
        return next(record for record in index["records"] if record["document"]["path"] == path)

    def do_import(self, keys, decisions=None, index=None) -> dict:
        return inbox_imports.run_import(index or self.opened(), {"keys": keys, "decisions": decisions or {}},
                                        self.inbox, lambda: CLOCK)


# ---------------------------------------------------------------- the retained package

class PackageTests(Folders):
    def test_the_page_is_located_through_its_acquisition_record_and_verified(self):
        package, raw, releases = bis_snapshot.locate(self.sources)
        self.assertEqual((package["url"], package["approval_id"], package["attempt"], package["bytes"]),
                         (fakes.PAGE_URL, fakes.APPROVAL, 1, len(raw)))
        self.assertEqual(package["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(sorted(releases), [f"https://www.bis.gov{path}" for path in sorted(fakes.standard_releases())])

    def test_a_tampered_page_is_refused_and_never_parsed(self):
        page = self.sources / "news-updates" / "source.html"
        data = bytearray(page.read_bytes())
        data[100] ^= 1
        page.write_bytes(bytes(data))  # Same size, one bit different.
        with patch.object(bis_snapshot, "extract", side_effect=AssertionError("parsed")):
            with self.assertRaises(bis_snapshot.SnapshotRefused) as caught:
                bis_snapshot.open_index(self.sources, self.index_dir)
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("SHA-256", str(caught.exception))
        view = snapshot_api.view(self.inbox, self.sources, self.index_dir)
        self.assertEqual((view["state"], view["rows"]), ("refused", []))
        self.assertFalse(self.index_dir.exists())

    def test_an_acquisition_record_that_does_not_describe_a_complete_html_retrieval_is_refused(self):
        changes = ({"outcome": "oversized"}, {"http_status": 206}, {"hash_kind": "partial_transfer"},
                   {"named_headers": {"content-type": "text/html; charset=utf-8", "content-encoding": "gzip"}},
                   {"named_headers": {"content-type": "application/json", "content-encoding": None}},
                   {"retained": "data/sector-sources/bis/elsewhere/source.html"}, {"sha256": "0" * 64},
                   {"bytes": 3}, {"body_completed_at": "2026-10-12T14:47:42"})
        for change in changes:
            with self.subTest(change=change):
                sources = fakes.write_snapshot(self.root / f"s{len(json.dumps(change))}-{id(change)}", **change)
                with self.assertRaises(bis_snapshot.SnapshotRefused) as caught:
                    bis_snapshot.locate(sources)
                self.assertEqual(caught.exception.status, 409)

    def test_a_missing_snapshot_is_reported_unavailable(self):
        view = snapshot_api.view(self.inbox, self.root / "no-sources", self.index_dir)
        self.assertEqual(view["state"], "unavailable")
        self.assertIn("not on this machine", view["problem"])

    def test_two_acquisition_records_for_the_page_are_refused(self):
        run = self.sources / "acquisitions" / fakes.APPROVAL
        record = json.loads((run / "outcome-1.json").read_text(encoding="utf-8"))
        (run / "outcome-9.json").write_text(json.dumps({**record, "n": 9}), encoding="utf-8")
        with self.assertRaises(bis_snapshot.SnapshotRefused):
            bis_snapshot.locate(self.sources)


# ---------------------------------------------------------------- extraction

class ExtractionTests(Folders):
    def test_records_are_unique_addresses_and_unusable_entries_say_why(self):
        index = self.opened()
        paths = [record["document"]["path"] for record in index["records"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(index["listed"], 17)
        reasons = {entry["position"]: " ".join(entry["reasons"]) for entry in index["unusable"]}
        self.assertIn("duplicate copy of the record at position 9", reasons[10])
        self.assertIn("listed 2 times with different content", reasons[11])
        self.assertIn("listed 2 times with different content", reasons[12])
        self.assertIn("no title", reasons[13])
        self.assertIn("no usable press-release address", reasons[14])
        self.assertIn("does not mark it as published", reasons[15])
        self.assertEqual(sorted(reasons), [10, 11, 12, 13, 14, 15])
        kept = self.record(index, "/press-release/synthetic-duplicate-copy")
        self.assertEqual(kept["position"], 9)
        self.assertIn("identical content", " ".join(kept["notes"]))

    def test_text_becomes_plain_paragraphs_and_no_markup_or_script_survives(self):
        record = self.record(self.opened(), "/press-release/synthetic-markup-test")
        text = record["text"]["paragraphs"]
        self.assertEqual(text, ["Plain & safe <b> text", "a link's words stay as words"])
        joined = json.dumps(record)
        for hidden in ("alert", "color:red", "hidden", "javascript:", "example.invalid", "onclick"):
            self.assertNotIn(hidden, joined)
        self.assertEqual(record["publisher"]["summary"], "Synthetic summary")

    def test_the_same_title_on_different_addresses_stays_two_documents(self):
        index = self.opened()
        first = self.record(index, "/press-release/synthetic-repeated-title")
        second = self.record(index, "/press-release/synthetic-repeated-title-0")
        self.assertNotEqual(first["key"], second["key"])
        self.assertEqual([(item["key"], item["relation"]) for item in first["same_title"]],
                         [(second["key"], "different text")])
        rows = self.do_import([first["key"], second["key"]])["rows"]
        self.assertEqual([row["outcome"] for row in rows], ["added", "added"])
        self.assertEqual(len(inbox_imports.items(self.inbox)[0]), 2)

    def test_listing_dates_are_kept_as_stated_and_never_filled_from_cms_times(self):
        index = self.opened()
        listed = self.record(index, CHIPS)["listing"]
        self.assertEqual((listed["published"]["state"], listed["published"]["time"], listed["published"]["date"]),
                         ("listed", "2026-09-30T16:00:00+00:00", "2026-09-30"))
        self.assertEqual(listed["created"]["field"], "CMS creation time")
        missing = self.record(index, "/press-release/synthetic-record-without-listing-date")
        self.assertEqual((missing["listing"]["published"]["state"], missing["listing"]["created"]["state"]),
                         ("missing", "listed"))
        timestamp = inbox_imports.feed_timestamp(missing)
        self.assertEqual((timestamp["raw"], timestamp["instant_utc"], timestamp["suggestion"]), (None, None, None))
        self.assertIn("CMS creation and update times are not publication times", timestamp["problem"])
        ambiguous = self.record(index, "/press-release/synthetic-ambiguous-date")["listing"]["published"]
        self.assertEqual((ambiguous["state"], ambiguous["time"]), ("ambiguous", None))
        self.assertIn("epoch seconds and its time disagree", ambiguous["problem"])
        stated = inbox_imports.feed_timestamp(self.record(index, CHIPS))
        self.assertEqual((stated["raw"], stated["suggestion"]), ("2026-09-30T16:00:00+00:00", None))

    def test_other_zones_or_malformed_times_are_ambiguous(self):
        cases = ({"timestamp": 0, "timezone": "America/New_York", "offset": "-04:00", "time": "1970-01-01T00:00:00-04:00"},
                 {"timestamp": 0, "timezone": "UTC", "offset": "+00:00", "time": "2026-03-03"},
                 {"time": "2026-03-03T10:00:00+00:00"}, "2026-03-03")
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(bis_snapshot.listing_time(value, "publication time")["state"], "ambiguous")

    def test_addresses_and_outside_links_are_validated(self):
        for path in ("/press-release/../secrets", "/press-release/UPPER", "/press-release/a?b=1", "/news/x",
                     "press-release/x", "/press-release/", None, 7):
            self.assertIsNone(bis_snapshot.official_address(path), path)
        self.assertEqual(bis_snapshot.official_address("/press-release/st.-lucia-0"),
                         "https://www.bis.gov/press-release/st.-lucia-0")
        for url in ("http://justice.gov/x", "https://user:pw@justice.gov/x", "https://justice.gov:8443/x",
                    "javascript:alert(1)", "https://justice.gov/a b"):
            self.assertEqual(bis_snapshot.outside_link({"url": url})[0], None, url)
        index = self.opened()
        plain = self.record(index, "/press-release/synthetic-plain-http-link")
        self.assertIsNone(plain["publisher"]["external_link"])
        self.assertIn("not a plain https address", " ".join(plain["notes"]))
        self.assertEqual(self.record(index, "/press-release/synthetic-firearms-exporter-sentenced")
                         ["publisher"]["external_link"]["host"], "www.justice.gov")

    def test_text_completeness_is_checked_only_where_a_release_page_was_retained(self):
        index = self.opened()
        checked, differs = self.record(index, CHIPS), self.record(index, IMPLANTERS)
        self.assertEqual((checked["completeness"], checked["check"]["result"], checked["check"]["dateline"]),
                         ("checked", "identical", "September 30, 2026"))
        self.assertEqual((differs["completeness"], differs["check"]["result"]), ("checked_differs", "differs"))
        title_only = self.record(index, "/press-release/synthetic-firearms-exporter-sentenced")
        self.assertEqual((title_only["completeness"], title_only["check"]), ("title_only", None))
        self.assertEqual(self.record(index, "/press-release/synthetic-markup-test")["completeness"], "listing_text")

    def test_keyword_filters_are_fixed_word_lists(self):
        index = self.opened()
        chips = self.record(index, CHIPS)["filters"]
        self.assertTrue(chips["semiconductors"]["matched"] and chips["export_controls"]["matched"])
        self.assertEqual(chips["semiconductors"]["in"], ["text", "title"])
        self.assertFalse(self.record(index, "/press-release/synthetic-firearms-exporter-sentenced")
                         ["filters"]["semiconductors"]["matched"])

    def test_bounded_parsing_refuses_malformed_or_oversized_data(self):
        cases = {"two data blocks": fakes.page(fakes.records(), blocks=2),
                 "no data block": b"<html><body>No data</body></html>",
                 "not JSON": fakes.page([], data="{not json"),
                 "a repeated key": fakes.page([], data='{"props": {}, "props": {}}'),
                 "a NaN constant": fakes.page([], data='{"props": NaN}'),
                 "deep nesting": fakes.page([], data="[" * 100000 + "]" * 100000),
                 "no record list": fakes.page([], data='{"props": {"pageProps": {}}}'),
                 "too many records": fakes.page([{}] * (bis_snapshot.MAX_RECORDS + 1)),
                 "not UTF-8": b"\xff\xfe" + fakes.page([])}
        for name, data in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(bis_snapshot.SnapshotRefused) as caught:
                    bis_snapshot.extract(data)
                self.assertEqual(caught.exception.status, 422)

    def test_long_or_unreadable_text_is_bounded_and_said_so(self):
        many = "".join(f"<p>Paragraph {n}</p>" for n in range(bis_snapshot.MAX_PARAGRAPHS + 5))
        teasers = [fakes.teaser(1, "Synthetic Long", "/press-release/synthetic-long", body=many),
                   fakes.teaser(2, "Synthetic Huge", "/press-release/synthetic-huge",
                                body="<p>" + "x" * (bis_snapshot.MAX_BODY_HTML + 1) + "</p>"),
                   fakes.teaser(3, "Synthetic Odd", "/press-release/synthetic-odd", body="<p>a</p><![bogus[ x")]
        records = {record["key"]: record for record in bis_snapshot.extract(fakes.page(teasers))["records"]}
        long_, huge, odd = (records[key_of(f"/press-release/synthetic-{name}")] for name in ("long", "huge", "odd"))
        self.assertEqual((len(long_["text"]["paragraphs"]), long_["text"]["truncated"]),
                         (bis_snapshot.MAX_PARAGRAPHS, True))
        self.assertEqual((huge["text"]["state"], huge["text"]["paragraphs"]), ("unreadable", []))
        self.assertIn(odd["text"]["state"], ("unreadable", "listing_text"))


# ---------------------------------------------------------------- the index

class IndexTests(Folders):
    def test_open_builds_once_and_every_later_open_and_restart_reuses_it(self):
        index, state = bis_snapshot.open_index(self.sources, self.index_dir, lambda: CLOCK)
        self.assertEqual(state, "built")
        written = tree(self.index_dir)
        self.assertEqual(list(written), [f"{index['package']['sha256'][:16]}-{bis_snapshot.EXTRACTOR_VERSION}.json"])
        with patch.object(bis_snapshot, "extract", side_effect=AssertionError("rebuilt")):
            again, state = bis_snapshot.open_index(self.sources, self.index_dir)  # A later open, or a restart.
            self.assertEqual((state, again["content_sha256"]), ("reused", index["content_sha256"]))
            with self.app() as client:  # A new server process reads the same index.
                self.assertEqual(client.get("/api/inbox/snapshots/bis").json()["state"], "open")
        self.assertEqual(tree(self.index_dir), written)

    def app(self) -> TestClient:
        return TestClient(create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                                     self.root / "intake", self.root / "attempts", inbox=self.inbox,
                                     triage=self.root / "triage", links=self.root / "links",
                                     market=self.root / "market", related_records=self.root / "related",
                                     related_sources=self.root / "rs", enrichment_sources=self.root / "es",
                                     snapshot_sources=self.sources, snapshot_index=self.index_dir,
                                     snapshot_clock=lambda: CLOCK), base_url=BASE)

    def test_reading_never_builds_or_writes(self):
        before = tree(self.root)
        self.assertEqual(snapshot_api.view(self.inbox, self.sources, self.index_dir)["state"], "not_opened")
        self.assertEqual(tree(self.root), before)

    def test_an_index_that_does_not_verify_is_refused_and_left_as_it_is(self):
        self.opened()
        (path,) = self.index_dir.iterdir()
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.write_text(path.read_text(encoding="utf-8").replace("Synthetic second paragraph",
                                                                 "Synthetic altered paragraph"), encoding="utf-8")
        before = tree(self.index_dir)
        for action in (lambda: bis_snapshot.open_index(self.sources, self.index_dir),
                       lambda: bis_snapshot.read_index(self.sources, self.index_dir)):
            with self.assertRaises(bis_snapshot.SnapshotRefused) as caught:
                action()
            self.assertIn("left as it is", str(caught.exception))
        self.assertEqual(tree(self.index_dir), before)

    def test_a_new_extractor_version_builds_a_new_index_without_touching_imported_entries(self):
        index = self.opened()
        self.do_import([self.record(index, CHIPS)["key"]], index=index)
        imported = tree(self.inbox)
        with patch.object(bis_snapshot, "EXTRACTOR_VERSION", "bis-snapshot-extract-9.9"):
            newer, state = bis_snapshot.open_index(self.sources, self.index_dir, lambda: CLOCK)
        self.assertEqual((state, len(list(self.index_dir.iterdir()))), ("built", 2))
        self.assertEqual(tree(self.inbox), imported)
        preview = inbox_imports.preview(newer, {"keys": [self.record(newer, CHIPS)["key"]]}, self.inbox)
        self.assertEqual(preview["rows"][0]["state"], "existing")  # Same source version: reused, not re-imported.


# ---------------------------------------------------------------- preview and import

class ImportTests(Folders):
    def test_preview_sorts_the_selection_and_writes_nothing(self):
        index = self.opened()
        before = tree(self.root)
        keys = [self.record(index, CHIPS)["key"], key_of("/press-release/synthetic-unpublished"), "0" * 20]
        rows = inbox_imports.preview(index, {"keys": keys}, self.inbox)["rows"]
        self.assertEqual([row["state"] for row in rows], ["new", "unusable", "unusable"])
        self.assertIn("does not mark it as published", " ".join(rows[1]["reasons"]))
        self.assertIn("not a record of this snapshot", " ".join(rows[2]["reasons"]))
        self.assertEqual(tree(self.root), before)

    def test_an_import_adds_once_and_a_repeat_reuses_without_writing(self):
        index = self.opened()
        keys = [self.record(index, CHIPS)["key"], self.record(index, IMPLANTERS)["key"]]
        first = self.do_import(keys, index=index)
        self.assertEqual(([row["outcome"] for row in first["rows"]], first["written"]), (["added", "added"], True))
        after = tree(self.inbox)
        self.assertEqual(sum(name.startswith("imports/bis-snapshot/records/") for name in after), 1)
        repeat = self.do_import(keys, index=index)
        self.assertEqual(([row["outcome"] for row in repeat["rows"]], repeat["written"], repeat["import_id"]),
                         (["reused", "reused"], False, None))
        self.assertEqual(tree(self.inbox), after)

    def test_concurrent_imports_create_each_entry_exactly_once(self):
        index = self.opened()
        keys = [self.record(index, CHIPS)["key"], self.record(index, IMPLANTERS)["key"]]
        barrier, outcomes = threading.Barrier(4), []

        def run():
            barrier.wait()
            outcomes.extend(row["outcome"] for row in self.do_import(keys, index=index)["rows"])
        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["added", "added"] + ["reused"] * 6)
        entries = [name for name in tree(self.inbox) if "/entries/" in name]
        self.assertEqual(len(entries), 2)

    def test_racing_writers_in_other_processes_never_overwrite(self):
        index = self.opened()
        key = self.record(index, CHIPS)["key"]
        original = inbox_imports._write_once

        def lose_the_race(path, data):  # Another process created the same version a moment earlier.
            original(path, data)
            return False
        with patch.object(inbox_imports, "_write_once", lose_the_race):
            rows = self.do_import([key], index=index)["rows"]
        self.assertEqual(rows[0]["outcome"], "reused")

    def test_a_changed_source_version_needs_an_explicit_decision_and_never_replaces(self):
        index = self.opened()
        key = self.record(index, CHIPS)["key"]
        self.do_import([key], index=index)
        first_entry = tree(self.inbox)
        (item,) = inbox_imports.items(self.inbox)[0]
        teasers = fakes.records()
        teasers[0] = {**teasers[0], "body": {**teasers[0]["body"],
                                             "processed": "<p>Synthetic: a revised text.</p><p>###</p>"}}
        changed_sources = fakes.write_snapshot(self.root / "sources-2", teasers)
        newer = bis_snapshot.open_index(changed_sources, self.root / "index-2", lambda: CLOCK)[0]
        row = inbox_imports.preview(newer, {"keys": [key]}, self.inbox)["rows"][0]
        self.assertEqual((row["state"], row["changed"]), ("changed", ["text"]))
        with self.assertRaises(inbox_imports.ImportRefused) as caught:
            self.do_import([key], index=newer)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(tree(self.inbox), first_entry)
        kept = self.do_import([key], {key: "keep"}, index=newer)
        self.assertEqual((kept["rows"][0]["outcome"], kept["written"]), ("kept", False))
        self.assertEqual(tree(self.inbox), first_entry)
        added = self.do_import([key], {key: "add_version"}, index=newer)
        self.assertEqual((added["rows"][0]["outcome"], added["rows"][0]["version"]), ("version_added", 2))
        self.assertTrue(set(first_entry.items()) <= set(tree(self.inbox).items()))  # Version 1 is untouched.
        (latest,) = inbox_imports.items(self.inbox)[0]
        self.assertEqual((latest["imported"]["version"], latest["imported"]["versions"]), (2, 2))
        held = inbox_imports.versions(self.inbox, item["id"])
        self.assertEqual([version["content_sha256"] for version in held],
                         [item["content_sha256"], latest["content_sha256"]])
        self.assertEqual(event_links.check_origin({"item_id": item["id"], "content_sha256": item["content_sha256"]},
                                                  self.inbox)["version"], 1)  # A capture of version 1 still binds.

    def test_selections_are_bounded_and_decisions_checked(self):
        index = self.opened()
        key = self.record(index, CHIPS)["key"]
        for keys in ([], [key, key], ["X" * 20], [f"{n:020x}" for n in range(inbox_imports.MAX_SELECTION + 1)], key):
            with self.assertRaises(inbox_imports.ImportRefused):
                inbox_imports.preview(index, {"keys": keys}, self.inbox)
        for decisions in ({key: "replace"}, {"0" * 20: "keep"}):
            with self.assertRaises(inbox_imports.ImportRefused):
                self.do_import([key], decisions, index=index)
        with self.assertRaises(inbox_imports.ImportRefused):
            inbox_imports.run_import(index, {"keys": [key]}, self.inbox)

    def test_an_entry_that_does_not_verify_is_reported_and_never_overwritten(self):
        index = self.opened()
        key = self.record(index, CHIPS)["key"]
        self.do_import([key], index=index)
        (path,) = [path for path in self.inbox.rglob("1.json")]
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.write_text(path.read_text(encoding="utf-8").replace("Synthetic second", "Altered second"), encoding="utf-8")
        before = tree(self.inbox)
        items, summary = inbox_imports.items(self.inbox)
        self.assertEqual((items, [row["key"] for row in summary["unreadable"]]), ([], [key]))
        rows = self.do_import([key], index=index)["rows"]
        self.assertEqual(rows[0]["outcome"], "unusable")
        self.assertEqual(tree(self.inbox), before)


# ---------------------------------------------------------------- the Inbox and its consumers

class InboxIntegrationTests(Folders):
    def setUp(self):
        super().setUp()
        answers = {FED: [(200, rss([rss_item(1, "Federal Reserve issues FOMC statement",
                                             "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm",
                                             pub="Wed, 16 Sep 2026 18:00:00 GMT")]))],
                   EIA: [(200, eia_rss([eia_item(1, "Synthetic energy article")]))],
                   WTO: [(200, wto_rss([wto_item(1, "Synthetic trade news")]))],
                   EMPSIT: [(200, atom([]))], CPI: [(200, atom([]))]}
        event_inbox.refresh(self.inbox, Network(answers).fetcher(), clock(datetime(2026, 10, 9, 9, tzinfo=timezone.utc)))
        self.index = self.opened()

    def test_feed_entries_their_fingerprints_and_other_stores_are_unchanged(self):
        before_view = event_inbox.inbox_view(self.inbox)
        prints = {item["id"]: headline_triage.fingerprint(headline_triage.snapshot_item(item))
                  for item in before_view["items"]}
        outside = {name: digest for name, digest in tree(self.inbox).items() if not name.startswith("imports/")}
        self.do_import([self.record(self.index, CHIPS)["key"]], index=self.index)
        view = event_inbox.inbox_view(self.inbox)
        self.assertEqual((view["items"], view["retained"]), (before_view["items"], before_view["retained"]))
        self.assertEqual({item["id"]: headline_triage.fingerprint(headline_triage.snapshot_item(item))
                          for item in view["items"]}, prints)
        self.assertEqual({name: digest for name, digest in tree(self.inbox).items()
                          if not name.startswith("imports/")}, outside)
        self.assertEqual(len(view["imported"]), 1)
        self.assertNotIn(view["imported"][0]["id"], triage_plan.inbox_entries(self.inbox))  # Never offered for triage.
        self.assertEqual([source for source, _ in headline_triage.SOURCE_KINDS], list(event_inbox.SOURCES))

    def test_an_imported_entry_shows_its_provenance_and_a_bounded_excerpt(self):
        self.do_import([self.record(self.index, CHIPS)["key"]], index=self.index)
        (item,) = event_inbox.inbox_view(self.inbox)["imported"]
        self.assertEqual((item["source"], item["kind"], item["position"], item["link"]),
                         ("bis-snapshot", "Press release", None, f"https://www.bis.gov{CHIPS}"))
        self.assertEqual(item["content_sha256"], inbox_archive.content_sha256(item))
        provenance = item["imported"]
        self.assertEqual((provenance["snapshot"]["package"]["sha256"], provenance["snapshot"]["extractor_version"]),
                         (self.index["package"]["sha256"], bis_snapshot.EXTRACTOR_VERSION))
        self.assertTrue(provenance["import_id"] and provenance["record"]["text"]["paragraphs"])
        self.assertIn("not a live feed", provenance["label"])
        self.assertEqual(inbox_imports.MAX_EXCERPT, event_inbox.MAX_EXCERPT)

    def test_overview_related_research_and_capture_origins_treat_it_as_an_inbox_entry(self):
        uae = self.record(self.index, fakes.UAE_PATH)
        self.do_import([uae["key"], self.record(self.index, CHIPS)["key"]], index=self.index)
        with IndexTests.app(self) as client:
            overview = client.get(f"/api/events/inbox/bis-snapshot:{uae['key']}").json()
            self.assertEqual((overview["triage"]["state"], overview["source"]["location"]), ("not_offered", "imported"))
            self.assertIn("retained BIS snapshot", overview["source"]["note"])
            self.assertEqual(overview["market"]["state"], "unsupported")  # Outside the market-context families.
            research = client.get(f"/api/related-research/events/inbox/bis-snapshot:{uae['key']}").json()
            self.assertEqual([(link["relation"], link["target"]["id"]) for link in research["links"]],
                             [("same_event", "bis-2026-07-10")])  # Same address and date as the case: no rule changed.
            self.assertEqual(research["event"]["date_label"], "listing timestamp (retained snapshot)")
            chips = client.get(f"/api/related-research/events/inbox/bis-snapshot:{self.record(self.index, CHIPS)['key']}")
            self.assertEqual(chips.status_code, 200)
            self.assertNotIn("same_event", [link["relation"] for link in chips.json()["links"]])
            item = next(item for item in client.get("/api/inbox").json()["imported"] if item["id"].endswith(uae["key"]))
        origin = event_links.check_origin({"item_id": item["id"], "content_sha256": item["content_sha256"]}, self.inbox)
        self.assertEqual(origin["location"], "imported")


# ---------------------------------------------------------------- the API, and nothing outside this machine

class ApiTests(Folders):
    def client(self) -> TestClient:
        return IndexTests.app(self)

    def test_the_whole_workflow_makes_no_outside_request_and_no_model_call(self):
        calls = []
        connect = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                calls.append(("connect", address))
                raise AssertionError("an outside connection was attempted")
            return connect(sock, address)

        def counted(name):
            def call(*args, **kwargs):
                calls.append((name, None))
                raise AssertionError(f"{name} was called")
            return call
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo", counted("name lookup")), \
                patch.object(event_inbox.FeedFetcher, "fetch", counted("feed fetch")), \
                patch.object(headline_triage, "build_request", counted("model request")), \
                patch("second_order.triage_flow.dispatch", counted("triage dispatch")), self.client() as client:
            self.assertEqual(client.get("/api/inbox/snapshots/bis").json()["state"], "not_opened")
            opened = client.post("/api/inbox/snapshots/bis/open", headers=HEADERS, content="{}").json()
            key = next(row["key"] for row in opened["rows"] if row["link"].endswith(CHIPS))
            self.assertEqual(client.get(f"/api/inbox/snapshots/bis/records/{key}").status_code, 200)
            preview = client.post("/api/inbox/snapshots/bis/preview", headers=HEADERS, content=json.dumps({"keys": [key]}))
            self.assertEqual(preview.json()["counts"]["new"], 1)
            done = client.post("/api/inbox/snapshots/bis/import", headers=HEADERS,
                               content=json.dumps({"keys": [key], "decisions": {}}))
            again = client.post("/api/inbox/snapshots/bis/import", headers=HEADERS,
                                content=json.dumps({"keys": [key], "decisions": {}}))
            self.assertEqual((done.status_code, again.status_code, again.json()["counts"]["reused"]), (201, 200, 1))
            self.assertEqual(len(client.get("/api/inbox").json()["imported"]), 1)
            client.get(f"/api/events/inbox/bis-snapshot:{key}")
            client.get(f"/api/related-research/events/inbox/bis-snapshot:{key}")
            client.get(f"/api/related-cases/events/inbox/bis-snapshot:{key}")
        self.assertEqual(calls, [])

    def test_writes_need_this_page_its_header_and_strict_json(self):
        with self.client() as client:
            self.assertEqual(client.post("/api/inbox/snapshots/bis/open", content="{}",
                                         headers={**HEADERS, "X-Second-Order-Inbox": ""}).status_code, 403)
            self.assertEqual(client.post("/api/inbox/snapshots/bis/open", content="{}",
                                         headers={**HEADERS, "Origin": "https://example.invalid"}).status_code, 403)
            self.assertEqual(client.post("/api/inbox/snapshots/bis/open", headers=HEADERS,
                                         content='{"rebuild": true}').status_code, 422)
            self.assertEqual(client.post("/api/inbox/snapshots/bis/preview", headers=HEADERS,
                                         content=json.dumps({"keys": ["0" * 20]})).status_code, 409)  # Not opened.
            client.post("/api/inbox/snapshots/bis/open", headers=HEADERS, content="{}")
            self.assertEqual(client.post("/api/inbox/snapshots/bis/preview", headers=HEADERS,
                                         content='{"keys": ["a"], "keys": ["b"]}').status_code, 422)
            self.assertEqual(client.get("/api/inbox/snapshots/bis/records/not-a-key").status_code, 404)
            self.assertEqual(client.post("/api/inbox/snapshots/bis/import", headers=HEADERS,
                                         content="x" * (snapshot_api.MAX_BODY + 1)).status_code, 413)

    def test_served_views_match_the_committed_frontend_fixtures(self):
        with self.client() as client:
            opened = client.post("/api/inbox/snapshots/bis/open", headers=HEADERS, content="{}").json()
            keys = [row["key"] for row in opened["rows"] if row["link"].endswith((CHIPS, IMPLANTERS))]
            unusable = key_of("/press-release/synthetic-unpublished")
            preview = client.post("/api/inbox/snapshots/bis/preview", headers=HEADERS,
                                  content=json.dumps({"keys": keys + [unusable]})).json()
            done = client.post("/api/inbox/snapshots/bis/import", headers=HEADERS,
                               content=json.dumps({"keys": keys, "decisions": {}})).json()
            served = {"bis-snapshot-view.json": client.get("/api/inbox/snapshots/bis").json(),
                      "bis-snapshot-record.json": client.get(f"/api/inbox/snapshots/bis/records/{keys[0]}").json(),
                      "bis-snapshot-preview.json": preview, "bis-snapshot-import.json": done,
                      "bis-snapshot-inbox.json": client.get("/api/inbox").json()}
        for name, body in served.items():
            path = FIXTURES / name
            if os.environ.get(WRITE_FIXTURES) == "1":
                path.write_bytes((json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"))
            else:
                self.assertEqual(body, json.loads(path.read_text(encoding="utf-8")),
                                 f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                                 "-s tests -p test_bis_snapshot.py")


@unittest.skipUnless(os.environ.get(REAL_SOURCES), f"opt-in: set {REAL_SOURCES} to the retained BIS folder")
class RetainedSnapshotTests(unittest.TestCase):
    """The real retained page, extracted in memory. Read-only: nothing is written anywhere."""

    def test_the_retained_page_extracts_as_documented(self):
        folder = Path(os.environ[REAL_SOURCES])
        before = tree(folder)
        index = bis_snapshot.build(folder)
        counts = bis_snapshot.counts(index)
        self.assertEqual((counts["listed"], counts["usable"], counts["unusable"]), (435, 435, 0))
        self.assertEqual((counts["completeness"]["checked"], counts["dates"]["missing"]), (2, 3))
        checked = {record["document"]["path"]: record["check"]["dateline"] for record in index["records"]
                   if record["check"]}
        self.assertEqual(checked, {"/press-release/department-commerce-eases-export-controls-uae": "July 10, 2026",
                                   "/press-release/applied-materials-pay-252-million-penalty-bis-illegally-exporting-"
                                   "semiconductor-manufacturing-equipment": "February 12, 2026"})
        self.assertEqual(tree(folder), before)


if __name__ == "__main__":
    unittest.main()
