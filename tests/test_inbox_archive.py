"""Event Inbox archive: entries the explicit refreshes retrieved stay available locally after they leave their feed, and
a meaningful change keeps the earlier version. Retrieval time alone never makes a version; reads never write; an
unreadable archive is reported and left alone.

Synthetic feed bytes only, through an injected MockTransport, in temporary folders.
"""
from datetime import datetime, timezone
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from test_event_inbox import CPI, EMPSIT, FED, QUIET, Network, atom, atom_entry, clock, fingerprint, rss, rss_item
from second_order import event_inbox, inbox_archive
from second_order.event_inbox import inbox_view, refresh

DAY_ONE, DAY_TWO, DAY_THREE = (datetime(2026, 10, day, 9, 0, tzinfo=timezone.utc) for day in (8, 9, 10))


def feeds(fed_items: list[str]) -> dict:
    return {FED: [(200, rss(fed_items))],
            EMPSIT: [(200, atom([atom_entry(1, published="2026-10-02T08:30:00-04:00")]))],
            CPI: [(200, atom([atom_entry(1, "cpi", published="2026-09-11T08:30:00-04:00")]))], **QUIET}


ONE = rss_item(1, "Synthetic statement", pub="Wed, 16 Sep 2026 18:00:00 GMT", description="The first text.")
TWO = rss_item(2, "Synthetic minutes", pub="Wed, 07 Oct 2026 18:00:00 GMT")
ONE_EDITED = rss_item(1, "Synthetic statement (corrected)", pub="Wed, 16 Sep 2026 18:00:00 GMT",
                      description="The first text.")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.inbox = Path(folder.name) / "event-inbox"

    def refresh(self, fed_items: list[str], when: datetime, answers: dict | None = None) -> dict:
        return refresh(self.inbox, Network(answers or feeds(fed_items)).fetcher(), clock(when))

    def archive(self, key: str = "fed-monetary") -> dict:
        return json.loads((self.inbox / "archive" / f"{key}.json").read_text(encoding="utf-8"))

    def entry(self, title_prefix: str) -> dict:
        return next(entry for entry in self.archive()["entries"]
                    if entry["versions"][0]["title"].startswith(title_prefix))

    def test_a_departed_entry_stays_available_as_retained_history(self):
        self.refresh([ONE, TWO], DAY_ONE)
        view = self.refresh([TWO], DAY_TWO)
        self.assertEqual([item["title"] for item in view["items"] if item["source"] == "fed-monetary"],
                         ["Synthetic minutes"])
        (kept,) = view["retained"]
        self.assertEqual((kept["title"], kept["history"], kept["last_seen_at"], kept["retrieved_at"], kept["position"]),
                         ("Synthetic statement", True, "2026-10-08T09:00:01+00:00", "2026-10-08T09:00:01+00:00", None))
        self.assertEqual(kept["id"], inbox_archive.entry_id("fed-monetary", ONE.split("<guid><![CDATA[")[1].split("]")[0]))
        self.assertEqual(next(source for source in view["sources"] if source["key"] == "fed-monetary")["archive"],
                         {"state": "ok", "problem": None, "entries": 2, "versions": 2, "retained": 1})
        later = self.refresh([TWO], DAY_THREE)  # Nothing expires: it is still there a refresh later.
        self.assertEqual([item["title"] for item in later["retained"]], ["Synthetic statement"])

    def test_an_unchanged_refresh_makes_no_new_version_and_only_moves_last_seen(self):
        self.refresh([ONE, TWO], DAY_ONE)
        before = self.archive()
        self.refresh([ONE, TWO], DAY_TWO)
        after = self.archive()
        self.assertEqual([len(entry["versions"]) for entry in after["entries"]], [1, 1])
        for old, new in zip(before["entries"], after["entries"]):
            self.assertEqual({key: value for key, value in old["versions"][0].items() if key != "last_seen_at"},
                             {key: value for key, value in new["versions"][0].items() if key != "last_seen_at"})
            self.assertEqual(new["versions"][0]["last_seen_at"], "2026-10-09T09:00:01+00:00")

    def test_a_meaningful_change_keeps_the_earlier_version_and_a_revert_is_a_new_version(self):
        self.refresh([ONE], DAY_ONE)
        original = self.entry("Synthetic statement")["versions"][0]
        self.refresh([ONE_EDITED], DAY_TWO)
        versions = self.entry("Synthetic statement")["versions"]
        self.assertEqual([version["title"] for version in versions],
                         ["Synthetic statement", "Synthetic statement (corrected)"])
        self.assertEqual(versions[0], original)  # Never overwritten.
        self.assertEqual(versions[1]["first_seen_at"], "2026-10-09T09:00:01+00:00")
        self.refresh([ONE], DAY_THREE)
        self.assertEqual([version["title"] for version in self.entry("Synthetic statement")["versions"]],
                         ["Synthetic statement", "Synthetic statement (corrected)", "Synthetic statement"])
        current = next(item for item in inbox_view(self.inbox)["items"] if item["source"] == "fed-monetary")
        self.assertEqual(current["title"], "Synthetic statement")

    def test_a_failed_refresh_and_every_read_leave_the_archive_untouched(self):
        self.refresh([ONE, TWO], DAY_ONE)
        before = fingerprint(self.inbox / "archive")
        failed = Network({**feeds([ONE]), FED: [(500, b"down", {"content-type": "text/plain"})]})
        refresh(self.inbox, failed.fetcher(), clock(DAY_TWO))
        archive_after_failure = fingerprint(self.inbox / "archive")
        self.assertEqual(archive_after_failure["fed-monetary.json"], before["fed-monetary.json"])
        for _ in range(3):
            inbox_view(self.inbox)
        self.assertEqual(fingerprint(self.inbox / "archive"), archive_after_failure)

    def test_a_missing_archive_starts_from_the_existing_record(self):
        self.refresh([ONE, TWO], DAY_ONE)
        shutil.rmtree(self.inbox / "archive")  # As for a cache written before the archive existed.
        self.assertEqual(inbox_view(self.inbox)["retained"], [])
        self.refresh([TWO], DAY_TWO)
        archive = self.archive()
        self.assertEqual(sorted(entry["versions"][0]["title"] for entry in archive["entries"]),
                         ["Synthetic minutes", "Synthetic statement"])
        statement = self.entry("Synthetic statement")["versions"][0]
        self.assertEqual((statement["first_seen_at"], statement["last_seen_at"]),
                         ("2026-10-08T09:00:01+00:00", "2026-10-08T09:00:01+00:00"))

    def test_an_unreadable_archive_is_reported_and_never_written_over(self):
        self.refresh([ONE, TWO], DAY_ONE)
        path = self.inbox / "archive" / "fed-monetary.json"
        tampered = json.loads(path.read_text(encoding="utf-8"))  # Valid JSON whose content no longer matches its hash.
        tampered["entries"][0]["versions"][0]["title"] = "Tampered"
        for broken in (b'{"archive_version": "event-inbox-archive-0.1"', json.dumps(tampered).encode("utf-8")):
            path.write_bytes(broken)
            view = inbox_view(self.inbox)
            fed = next(source for source in view["sources"] if source["key"] == "fed-monetary")
            self.assertEqual(fed["archive"]["state"], "unreadable")
            self.assertEqual([item for item in view["retained"] if item["source"] == "fed-monetary"], [])
            result = self.refresh([TWO], DAY_TWO)
            outcome = next(row for row in result["refreshed"] if row["source"] == "fed-monetary")
            self.assertEqual(outcome["outcome"], "ok")  # The feed itself still refreshes.
            self.assertIn("cannot be read", outcome["detail"])
            self.assertEqual(path.read_bytes(), broken)  # Not repaired, not replaced.

    def test_records_hold_no_retrieval_only_changes_and_reads_create_nothing(self):
        view = inbox_view(self.inbox)
        self.assertEqual((view["retained"], self.inbox.exists()), ([], False))
        self.refresh([ONE], DAY_ONE)
        sha = inbox_archive.content_sha256(self.entry("Synthetic statement")["versions"][0])
        moved = {**self.entry("Synthetic statement")["versions"][0], "first_seen_at": "2030-01-01T00:00:00+00:00",
                 "last_seen_at": "2030-01-01T00:00:00+00:00"}
        self.assertEqual(inbox_archive.content_sha256(moved), sha)
        self.assertEqual(event_inbox.SOURCES["fed-monetary"].feed_url, self.archive()["feed_url"])


if __name__ == "__main__":
    unittest.main()
