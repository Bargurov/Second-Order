"""Raw feed copies (inbox_raw): each accepted feed response is kept privately during an explicit refresh, as received,
on SYNTHETIC fake feed responses only. Covers byte and hash integrity, the WTO feed's full-article content element, one
shared file for identical bytes, no copy for failed or refused retrievals, older retrievals without copies, a failure to
keep the copy, a copy that no longer matches its record, and unchanged items and triage fingerprints.
"""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from test_event_inbox import CPI, EIA, EMPSIT, FED, QUIET, WTO, Network, atom, clock, rss, rss_item, wto_item, wto_rss
from second_order import event_inbox, headline_triage, inbox_acquisitions, inbox_raw

ARTICLE = "<p>Full synthetic article body, with a <a href='/english/x_e.htm'>link</a>.</p>"


def answers(wto_body: bytes | None = None, wto_status: int = 200) -> dict:
    body = wto_body if wto_body is not None else wto_rss([wto_item(1, "Synthetic trade news", content=ARTICLE),
                                                         wto_item(2, "Synthetic committee news")])
    return {FED: [(200, rss([rss_item(1)]))], EMPSIT: [(200, atom([]))], CPI: [(200, atom([]))],
            EIA: QUIET[EIA], WTO: [(wto_status, body)]}


class RawCopyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.inbox = Path(folder.name) / "inbox"
        self.moment = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)

    def refresh(self, feeds: dict) -> dict:
        self.moment = self.moment.replace(hour=self.moment.hour + 1)
        return event_inbox.refresh(self.inbox, Network(feeds).fetcher(), clock(self.moment))

    def records(self, key: str) -> list[dict]:
        found, bad = inbox_acquisitions.records(self.inbox, key, event_inbox.SOURCES[key].feed_url)
        self.assertEqual(bad, [])
        return found

    def test_the_wto_response_is_kept_exactly_and_named_by_its_retrieval_record(self):
        body = answers()[WTO][0][1]
        self.refresh(answers())
        (record,) = self.records("wto-news")
        data = (inbox_raw.raw_dir(self.inbox, "wto-news") / record["body"]["kept"]).read_bytes()
        self.assertEqual(data, body)
        self.assertIn(ARTICLE.encode("utf-8"), data)  # The full-article content element, as received and unread.
        self.assertEqual((record["body"]["sha256"], record["body"]["bytes"], record["body"]["state"]),
                         (hashlib.sha256(body).hexdigest(), len(body), "complete"))
        self.assertEqual(inbox_raw.kept_state(self.inbox, "wto-news", record["body"]["kept"], record["body"]["sha256"]),
                         "verified")
        for path in inbox_raw.raw_dir(self.inbox, "wto-news").iterdir():
            self.assertFalse(os.stat(path).st_mode & stat.S_IWRITE)

    def test_every_accepted_source_keeps_a_copy_and_failed_ones_keep_none(self):
        self.refresh(answers(wto_body=b"Service unavailable", wto_status=503))
        self.assertEqual(sorted(p.name for p in (self.inbox / "raw").iterdir()),
                         ["bls-cpi", "bls-empsit", "eia-todayinenergy", "fed-monetary"])
        (failed,) = self.records("wto-news")
        self.assertEqual((failed["outcome"], failed["body"]["state"], failed["body"]["kept"]),
                         ("failed", "not_read", None))
        self.refresh(answers())
        self.assertEqual(len(list((self.inbox / "raw" / "wto-news").glob("*.xml"))), 1)

    def test_identical_bytes_share_one_file_and_each_retrieval_is_recorded(self):
        self.refresh(answers())
        self.refresh(answers())
        other = wto_rss([wto_item(1, "Synthetic trade news", content=ARTICLE + "<p>Updated.</p>")])
        self.refresh(answers(wto_body=other))
        kept = self.records("wto-news")
        self.assertEqual(len(kept), 3)
        self.assertEqual(len({row["body"]["kept"] for row in kept}), 2)
        self.assertEqual(len(list(inbox_raw.raw_dir(self.inbox, "wto-news").glob("*.xml"))), 2)

    def test_items_and_triage_fingerprints_are_unchanged_by_keeping_the_copy(self):
        self.refresh(answers())
        kept_view = event_inbox.inbox_view(self.inbox)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        plain = Path(folder.name) / "inbox"
        unkept = {key: event_inbox.Source(**{**source.__dict__, "keep_raw": False})
                  for key, source in event_inbox.SOURCES.items()}
        with patch.dict(event_inbox.SOURCES, unkept):
            event_inbox.refresh(plain, Network(answers()).fetcher(), clock(self.moment))
        self.assertFalse((plain / "raw").exists())
        plain_view = event_inbox.inbox_view(plain)
        prints = lambda view: sorted(headline_triage.fingerprint(headline_triage.snapshot_item(item))  # noqa: E731
                                     for item in view["items"])
        self.assertEqual(prints(kept_view), prints(plain_view))
        self.assertEqual([{k: v for k, v in item.items() if k != "first_seen_at"} for item in kept_view["items"]],
                         [{k: v for k, v in item.items() if k != "first_seen_at"} for item in plain_view["items"]])

    def test_older_retrievals_without_a_copy_stay_valid_and_none_is_reconstructed(self):
        unkept = {key: event_inbox.Source(**{**source.__dict__, "keep_raw": False})
                  for key, source in event_inbox.SOURCES.items()}
        with patch.dict(event_inbox.SOURCES, unkept):
            self.refresh(answers())
        before = event_inbox.inbox_view(self.inbox)
        self.assertEqual([record["body"]["kept"] for record in self.records("wto-news")], [None])
        self.assertEqual(before["items"], event_inbox.inbox_view(self.inbox)["items"])  # Reading creates nothing.
        self.assertFalse((self.inbox / "raw").exists())
        self.refresh(answers())
        self.assertEqual([bool(record["body"]["kept"]) for record in self.records("wto-news")], [False, True])

    def test_a_copy_that_cannot_be_kept_is_a_note_not_a_failed_refresh(self):
        with patch("second_order.inbox_raw.keep_bytes", side_effect=PermissionError("denied")):
            result = self.refresh(answers())
        outcome = next(row for row in result["refreshed"] if row["source"] == "wto-news")
        self.assertEqual(outcome["outcome"], "ok")
        self.assertIn("could not be kept privately (PermissionError)", outcome["detail"])
        self.assertIsNone(outcome["acquisition"]["body"]["kept"])
        self.assertEqual(len(event_inbox.inbox_view(self.inbox)["items"]), 3)  # 1 Fed + 2 WTO.

    def test_a_file_named_for_other_bytes_is_refused_and_a_changed_copy_is_reported(self):
        folder = inbox_raw.raw_dir(self.inbox, "wto-news")
        folder.mkdir(parents=True)
        body = answers()[WTO][0][1]
        digest = hashlib.sha256(body).hexdigest()
        (folder / f"{digest}.xml").write_bytes(b"tampered")
        with self.assertRaises(OSError):
            inbox_raw.keep_bytes(self.inbox, "wto-news", body)
        self.assertEqual(inbox_raw.kept_state(self.inbox, "wto-news", f"{digest}.xml", digest), "differs")
        self.assertEqual(inbox_raw.kept_state(self.inbox, "wto-news", f"{'0' * 64}.xml", "0" * 64), "missing")


if __name__ == "__main__":
    unittest.main()
