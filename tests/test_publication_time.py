"""The Tracker's publication time: an explicit date, time and UTC offset, kept as supplied and normalized to UTC.

Every expected UTC value below is written out by hand, not computed with the code under test. Records live in
temporary folders.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from second_order.analysis_flow import FlowRefused, capture_from_form, dispatch_mock, preview_capture
from second_order.api import create_app
from second_order.draft_catalog import tracker_dir
from second_order.event_intake import capture_text

BASE = "http://127.0.0.1:8133"
INTAKE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
NOW = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)


def published_line(request: bytes) -> str:
    """The "Published at (UTC)" line of the saved request's single user message."""
    (message,) = json.loads(request)["messages"]
    (line,) = [line for line in message["content"].splitlines() if line.startswith("Published at (UTC): ")]
    return line


def form(published_at: str, headline: str = "Synthetic committee holds its rate") -> bytes:
    return json.dumps({"headline": headline, "source_url": "https://example.com/published-statement",
                       "published_at": published_at, "source_text": "Synthetic published text.\nSecond line."}
                      ).encode("utf-8")


class PublicationTimeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.intake, self.attempts, self.drafts = self.root / "intake", self.root / "attempts", self.root / "drafts"
        self.tick = 0

    def clock(self) -> datetime:
        """A distinct capture time per capture, so identical requests still get their own capture IDs."""
        self.tick += 1
        return NOW + timedelta(seconds=self.tick)

    def capture(self, published_at: str, headline: str = "Synthetic committee holds its rate") -> dict:
        moment = self.clock()
        return capture_from_form(form(published_at, headline), self.intake, lambda: moment)

    def stored(self, preview: dict) -> tuple[dict, bytes]:
        folder = self.intake / preview["capture_id"]
        return (json.loads((folder / "capture.json").read_text(encoding="utf-8")),
                (folder / "request.json").read_bytes())

    def test_offsets_for_the_same_instant_give_the_same_request(self):
        # 18:00 UTC on 4 October 2026, written in five offsets, two of them on the next local calendar day.
        same_instant = ["2026-10-04T14:00:00-04:00", "2026-10-04T23:30:00+05:30", "2026-10-04T18:00:00+00:00",
                        "2026-10-05T02:45:00+08:45", "2026-10-05T07:00:00+13:00"]
        hashes = set()
        for supplied in same_instant:
            with self.subTest(supplied):
                preview = self.capture(supplied)
                manifest, request = self.stored(preview)
                self.assertEqual(manifest["times"]["published_at_as_supplied"], supplied)  # Kept exactly as given.
                self.assertEqual(manifest["times"]["published_at"], "2026-10-04T18:00:00Z")
                self.assertEqual(published_line(request), "Published at (UTC): 2026-10-04T18:00:00Z")
                self.assertEqual((preview["times"]["published_at"], preview["times"]["published_at_as_supplied"]),
                                 ("2026-10-04T18:00:00Z", supplied))
                hashes.add(hashlib.sha256(request).hexdigest())
        self.assertEqual(len(hashes), 1)  # Identical request bytes: only the recorded supplied form differs.

    def test_conversion_across_midnight_month_and_year_changes_the_utc_date(self):
        cases = {
            "2026-10-04T22:30:00-04:00": "2026-10-05T02:30:00Z",  # Evening in New York is the next UTC day.
            "2026-10-05T01:15:00+03:00": "2026-10-04T22:15:00Z",  # After midnight in Jerusalem is the previous day.
            "2024-02-29T23:30:00-01:00": "2024-03-01T00:30:00Z",  # Leap day into March.
            "2025-12-31T21:00:00-05:00": "2026-01-01T02:00:00Z",  # New Year's Eve into the next UTC year.
            "2026-01-01T05:00:00+14:00": "2025-12-31T15:00:00Z",  # New Year's morning at +14:00 is still last year.
        }
        for supplied, expected in cases.items():
            with self.subTest(supplied):
                manifest, request = self.stored(self.capture(supplied, f"Midnight case {supplied}"))
                self.assertEqual((manifest["times"]["published_at_as_supplied"], manifest["times"]["published_at"]),
                                 (supplied, expected))
                self.assertEqual(published_line(request), f"Published at (UTC): {expected}")

    def test_invalid_dates_times_and_offsets_are_refused_and_nothing_is_captured(self):
        refused = {
            "not a leap year": "2026-02-29T10:00:00+00:00",
            "no 30 February": "2026-02-30T10:00:00+00:00",
            "no 31 April": "2026-04-31T10:00:00+00:00",
            "no month 13": "2026-13-01T10:00:00+00:00",
            "hour 24": "2026-10-04T24:00:00+00:00",
            "minute 60": "2026-10-04T23:60:00+00:00",
            "leap second": "2026-10-04T23:59:60+00:00",
            "missing offset": "2026-10-04T14:00:00",
            "Z instead of the explicit offset form": "2026-10-04T14:00:00Z",
            "offset beyond +14:00": "2026-10-04T14:00:00+15:00",
            "offset beyond -12:00": "2026-10-04T14:00:00-12:15",
            "offset off the 15-minute grid": "2026-10-04T14:00:00+05:07",
            "offset minutes above 59": "2026-10-04T14:00:00+05:75",
            "unknown offset -00:00": "2026-10-04T14:00:00-00:00",
            "offset without a colon": "2026-10-04T14:00:00+0400",
            "space separator": "2026-10-04 14:00:00+00:00",
            "no seconds": "2026-10-04T14:00+00:00",
            "fractional seconds": "2026-10-04T14:00:00.5+00:00",
            "a bare Unix time": "1600000000",
            "single-digit day": "2026-10-4T14:00:00+00:00",
            "empty": "",
        }
        for name, supplied in refused.items():
            with self.subTest(name):
                with self.assertRaises(FlowRefused) as caught:
                    self.capture(supplied)
                self.assertEqual(caught.exception.status, 422)
        self.assertFalse(self.intake.exists())

    def test_future_publication_times_are_refused_by_instant_not_by_local_date(self):
        # NOW is 2026-10-05T09:30Z. The same local wall-clock date can be past or future depending on the offset.
        past = self.capture("2026-10-05T13:00:00+14:00")  # 2026-10-04T23:00Z: already published.
        self.assertEqual(past["times"]["published_at"], "2026-10-04T23:00:00Z")
        for supplied in ("2026-10-05T09:00:00-01:00",  # 10:00Z, half an hour ahead.
                         "2026-10-06T00:00:00+00:00"):
            with self.subTest(supplied), self.assertRaisesRegex(FlowRefused, "in the future"):
                self.capture(supplied)

    def test_dispatch_copies_the_saved_bytes_with_the_normalized_time(self):
        preview = self.capture("2026-10-04T22:30:00-04:00")
        _, request = self.stored(preview)
        body = json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": "draft"}).encode()
        result = dispatch_mock(preview["capture_id"], body, self.intake, self.attempts, self.drafts, lambda: NOW)
        self.assertEqual((self.attempts / preview["capture_id"] / "request.json").read_bytes(), request)
        view = json.loads((tracker_dir(self.drafts) / f"draft-{result['draft_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(view["source"]["published_at"], "2026-10-05T02:30:00Z")

    def test_captures_saved_before_this_form_still_verify_and_dispatch_unchanged(self):
        # The earlier form converted in the browser and sent a UTC string with milliseconds; such records stay valid.
        saved = capture_text("Earlier capture", "https://example.com/earlier", "2026-10-04T11:00:00.000Z",
                             "tracker-earlier", "Text captured by the earlier form.", "claude-sonnet-5-5",
                             self.intake, lambda: NOW)
        folder = self.intake / saved["capture_id"]
        before = {path.name: path.read_bytes() for path in folder.iterdir()}
        preview = preview_capture(saved["capture_id"], self.intake)
        self.assertEqual((preview["times"]["published_at_as_supplied"], preview["times"]["published_at"]),
                         ("2026-10-04T11:00:00.000Z", "2026-10-04T11:00:00Z"))
        body = json.dumps({"request_sha256": preview["request_sha256"], "mock_outcome": "no_draft"}).encode()
        dispatch_mock(saved["capture_id"], body, self.intake, self.attempts, self.drafts, lambda: NOW)
        self.assertEqual((self.attempts / saved["capture_id"] / "request.json").read_bytes(), before["request.json"])
        self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir()}, before)  # Never rewritten.

    def test_the_http_route_applies_the_same_rule(self):
        app = create_app(self.root / "no-dossiers", None, self.drafts, self.root / "reviews", self.intake,
                         self.attempts)
        with TestClient(app, base_url=BASE) as client:
            refused = client.post("/api/intake", content=form("2026-10-04T14:00:00"), headers=INTAKE)
            self.assertEqual(refused.status_code, 422)
            self.assertIn("explicit UTC offset", refused.json()["detail"])
            accepted = client.post("/api/intake", content=form("2026-10-04T14:00:00-04:00"), headers=INTAKE)
            self.assertEqual(accepted.status_code, 201, accepted.text)
            self.assertEqual((accepted.json()["times"]["published_at_as_supplied"],
                              accepted.json()["times"]["published_at"]),
                             ("2026-10-04T14:00:00-04:00", "2026-10-04T18:00:00Z"))


if __name__ == "__main__":
    unittest.main()
