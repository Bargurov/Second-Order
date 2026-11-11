"""Market-implied rate path (rate_workbook, rate_context): a separate, private event record read from a retained
Atlanta Fed Market Probability Tracker workbook, verified on every read, never fetched or prepared by a page.

SYNTHETIC workbooks (rate_fakes), captures, Inbox origins and research records in temporary folders. Nothing reaches a
network, reads a key or touches data/.
"""
import contextlib
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

import rate_fakes
from market_fakes import capture as save_capture
from test_event_inbox import BASE
from test_event_overview import Overview
from test_headline_triage import FED_LINK, STATEMENT
from test_paid_drafts import every_file
from second_order import __main__ as cli, event_links, rate_context, rate_workbook
from second_order.api import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"  # Explicit opt-in; a default run only compares.
RESEARCH = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Research": "1"}
FIXED = datetime(2026, 10, 13, 12, 30, tzinfo=timezone.utc)
OBTAINED = date(2026, 10, 13)
METHOD = "SYNTHETIC: written by the test suite"
PUBLISHED = "2026-09-16T14:00:00-04:00"
BLS_LINK = "https://www.bls.gov/news.release/archives/empsit_10022026.htm"


def writable(path: Path) -> None:
    path.chmod(stat.S_IWRITE | stat.S_IREAD)


@contextlib.contextmanager
def no_network():
    """Every socket connection fails and is counted; the test asserts none was attempted."""
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise OSError("SYNTHETIC test: no network")
    with patch.object(socket.socket, "connect", refuse), patch.object(socket, "create_connection", refuse):
        yield attempts


class Folder(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def read(self, rows=None, **options):
        path = self.root / f"book-{len(list(self.root.iterdir()))}.xlsx"
        rate_fakes.write(path, rows, **options)
        return rate_workbook.read(path, frozenset({"2026-09-15"}))

    def refused(self, fragment: str, rows=None, **options):
        with self.assertRaises(rate_workbook.WorkbookRefused) as caught:
            self.read(rows, **options)
        self.assertIn(fragment, str(caught.exception))


# ---------------------------------------------------------------- the reader

class ReaderTests(Folder):
    def test_a_workbook_reads_with_its_license_definitions_dates_and_selected_rows(self):
        summary, collected = self.read()
        self.assertEqual(summary["sheets"], ["LICENSE", "DICTIONARY", "DATA"])
        self.assertEqual(summary["license"]["paragraphs"], [text for text in rate_fakes.LICENSE if text])
        self.assertEqual(summary["dictionary"]["description"], rate_workbook.DESCRIPTION)
        for name, meaning in rate_workbook.DEFINITIONS.items():
            self.assertEqual(summary["dictionary"]["definitions"][name], meaning)
        data = summary["data"]
        self.assertEqual((data["first"], data["last"], data["observation_dates"]),
                         ("2026-09-10", "2026-09-17", list(rate_fakes.OBSERVATIONS)))
        self.assertEqual(data["rows"], len(rate_fakes.standard_rows()))
        self.assertEqual(list(collected), ["2026-09-15"])
        mean = collected["2026-09-15"]["2026-12-16"]["Rate: mean"]
        self.assertEqual((mean["raw"], mean["target_range"], rate_workbook.serial_day(mean["serial"])),
                         (" 315.50", "300bps - 325bps", date(2026, 12, 16)))

    def test_stored_entries_read_like_deflated_ones(self):
        deflated, _ = self.read()
        stored, _ = self.read(compression=zipfile.ZIP_STORED)
        self.assertEqual({key: deflated[key] for key in ("license", "dictionary", "data")},
                         {key: stored[key] for key in ("license", "dictionary", "data")})

    def test_a_definition_that_differs_refuses_the_workbook(self):
        self.refused("definition of 'Rate: mean' differs",
                     definitions={"Rate: mean": "The rate, in percent, of the mean of the distribution"})
        self.refused("definition of 'Prob: hike' differs", definitions={"Prob: hike": None})
        self.refused("description differs", description="A different description.")

    def test_a_statistic_defined_twice_must_say_the_same_both_times(self):
        entries = rate_fakes.dictionary_entries()
        self.assertEqual([name for name, _ in entries].count("Rate: mean"), 2)  # As in the real workbook: accepted.
        self.read(entries=entries + [("Rate: mode", rate_fakes.EXTRA_DEFINITIONS["Rate: mode"])])
        self.refused("defines 'Rate: mode' twice, differently",
                     entries=entries + [("Rate: mode", "SYNTHETIC: a second, different meaning")])
        self.refused("defines 'Rate: mean' twice, differently",
                     entries=entries + [("Rate: mean", "The rate, in percent, of the mean")])
        self.refused("names 'Prob: cut' without a definition",
                     entries=[(name, meaning) for name, meaning in entries if name != "Prob: cut"] + [("Prob: cut", ...)])
        self.refused("definition of 'Prob: cut' differs",
                     entries=[(name, meaning) for name, meaning in entries if name != "Prob: cut"] + [("Prob: cut", "")])

    def test_the_license_statement_is_read_at_paragraph_boundaries_and_required(self):
        summary, _ = self.read(license=("First SYNTHETIC paragraph. It has two sentences.",
                                        rate_workbook.LICENSE_STATEMENT))
        self.assertEqual(summary["license"]["paragraphs"][0], "First SYNTHETIC paragraph. It has two sentences.")
        self.refused("expected use and attribution terms", license=("SYNTHETIC: no terms here.",))
        self.refused("expected use and attribution terms",
                     license=(rate_workbook.LICENSE_STATEMENT.replace("personal and educational", "any"),))

    def test_duplicate_rows_and_missing_columns_or_header_refuse(self):
        rows = rate_fakes.standard_rows()
        self.refused("repeats 'Rate: mean' for observation 2026-09-15", rows + [
            ("2026-09-15", date(2026, 12, 16), "300bps - 325bps", "Rate: mean", " 999.00")])
        self.refused("does not hold exactly the five columns",
                     [rows[0][:4] + (...,)] + rows[1:])
        self.refused("does not start with exactly the header", header=("date", "reference_start", "target_range",
                                                                       "statistic", "value"))
        self.refused("no header or no rows", [])

    def test_values_must_be_plain_decimals(self):
        for bad in ("NaN", "", "  ", "1e3", "abc", "inf", "4,25", "+4.25", "4.25%"):
            with self.subTest(value=bad):
                rows = rate_fakes.standard_rows(changes={("2026-09-11", "2026-12-16", "Prob: cut"): bad})
                self.refused("not a plain decimal", rows)

    def test_dates_units_and_ranges_must_have_the_stated_forms(self):
        rows = rate_fakes.standard_rows()
        first = rows[0]
        self.refused("not YYYY-MM-DD", [("09/15/2026",) + first[1:]] + rows[1:])
        self.refused("not a calendar date", [("2026-02-30",) + first[1:]] + rows[1:])
        self.refused("reference start is not a whole date serial", [first[:1] + ("2026-12-16",) + first[2:]] + rows[1:])
        self.refused("reference start is not a whole date serial", reference_format=0)
        self.refused("not '<n>bps - <m>bps'", [first[:2] + ("3.00% - 3.25%",) + first[3:]] + rows[1:])
        self.refused("not '<n>bps - <m>bps'", [first[:2] + ("325bps - 300bps",) + first[3:]] + rows[1:])
        self.refused("1904 date system", date1904=True)

    def test_structure_and_declarations_are_refused(self):
        self.refused("sheets are", sheets=("LICENSE", "DATA", "DICTIONARY"))
        self.refused("DOCTYPE declaration", doctype=True)
        path = self.root / "not-a-workbook.xlsx"
        path.write_bytes(b"SYNTHETIC: not a ZIP archive")
        with self.assertRaises(rate_workbook.WorkbookRefused):
            rate_workbook.read(path)


# ---------------------------------------------------------------- one event's context, through the app

class ContextTests(Overview):
    """The overview fixture (an inbox with the 16 September statement, the app with every outward transport a counting
    fake) plus a SYNTHETIC workbook kept by the explicit retain step."""

    def setUp(self):
        super().setUp()
        self.folders = rate_context.Folders(self.root / "rate-context", self.root / "intake", self.root / "links")
        self.book = self.root / "input" / "synthetic-mpt.xlsx"
        self.book_sha = rate_fakes.write(self.book)
        self.statement = self.id(STATEMENT, "0916a")

    def retain(self, path: Path | None = None, sha: str | None = None) -> dict:
        return rate_context.retain(path or self.book, sha or self.book_sha, OBTAINED, METHOD, self.folders.rate,
                                   lambda: FIXED)

    def fomc(self, published_at: str = PUBLISHED, origin: bool = True) -> str:
        link = self.item(self.statement)["link"]
        return self.capture(STATEMENT, link, origin=self.statement if origin else None,
                            published_at=published_at)["capture_id"]

    def rate(self, capture_id: str, status: int = 200) -> dict:
        response = self.client.get(f"/api/rate-context/capture/{capture_id}")
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_retain_keeps_the_exact_bytes_read_only_and_refuses_another_file(self):
        with no_network() as attempts:
            kept = self.retain()
        folder = self.folders.rate / "sources" / kept["source_id"]
        self.assertTrue(kept["retained_now"])
        self.assertEqual((folder / "workbook.xlsx").read_bytes(), self.book.read_bytes())
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ["acquisition.json", "validation-mpt-workbook-parser-0.1.json", "workbook.xlsx"])
        for path in folder.iterdir():
            self.assertFalse(os.access(path, os.W_OK), path.name)
        acquisition = json.loads((folder / "acquisition.json").read_text(encoding="utf-8"))
        self.assertEqual((acquisition["http_status"], acquisition["response_headers"], acquisition["publication_time"],
                          acquisition["obtained_on"]), (None, None, None, "2026-10-13"))
        self.assertFalse(self.retain()["retained_now"])  # Repeating it verifies and writes nothing.
        before = every_file(self.folders.rate)
        with self.assertRaises(rate_context.RateRefused) as caught:
            self.retain(sha="0" * 64)
        self.assertIn("nothing was retained", str(caught.exception))
        with self.assertRaises(rate_context.RateRefused) as caught:
            rate_context.retain(self.book, self.book_sha, date(2026, 10, 14), METHOD, self.folders.rate)
        self.assertIn("already retained as obtained on 2026-10-13", str(caught.exception))
        with self.assertRaises(rate_context.RateRefused) as caught:
            rate_context.retain(self.book, self.book_sha, date(2026, 9, 16), METHOD, self.root / "another-rate")
        self.assertIn("after the 2026-09-16 it was said to be obtained", str(caught.exception))
        self.assertEqual(list((self.root / "another-rate" / "sources").iterdir()), [])  # The staging was removed.
        refused = self.root / "input" / "refused.xlsx"
        refused_sha = rate_fakes.write(refused, definitions={"Rate: mean": "SYNTHETIC: another meaning"})
        with self.assertRaises(rate_context.RateRefused):
            self.retain(refused, refused_sha)
        self.assertEqual(every_file(self.folders.rate), before)
        self.assertEqual(attempts, [])

    def test_the_observation_is_the_last_one_before_the_new_york_publication_date(self):
        self.retain()
        capture_id = self.fomc()
        with no_network() as attempts:
            prepared = rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
            shown = self.rate(capture_id)
        self.assertEqual((prepared["saved_now"], prepared["version"], prepared["observation_date"]),
                         (True, 1, "2026-09-15"))
        self.assertEqual(shown["state"], "available")
        selection = shown["selection"]
        self.assertEqual((selection["observation_date"], selection["publication_new_york_date"],
                          selection["calendar_days_before"], selection["same_day_observation"]),
                         ("2026-09-15", "2026-09-16", 1, True))
        self.assertEqual([window["reference_start"] for window in shown["windows"]],
                         ["2026-12-16", "2027-03-17", "2027-06-16", "2027-09-15"])  # The first four of five.
        self.assertEqual(shown["windows_listed"], 5)
        first = shown["windows"][0]["statistics"]
        self.assertEqual({key: (item["bp"], item["percent"]) for key, item in first.items()},
                         {"mean": ("315.50", "3.1550"), "p25": ("296.75", "2.9675"), "p75": ("336.75", "3.3675")})
        self.assertEqual(shown["target_range"], {"raw": "300bps - 325bps", "bps": [300, 325], "percent": ["3.00", "3.25"]})
        self.assertEqual(shown["meeting_specific"]["state"], "unavailable")
        self.assertEqual(shown["origin"]["item_id"], self.statement)
        self.assertEqual((shown["provider_called"], shown["written"]), (False, False))
        self.assertEqual(attempts, [])
        self.no_calls()

    def test_dates_are_compared_in_new_york_not_utc(self):
        self.retain()
        late = self.fomc("2026-09-16T02:30:00+00:00")  # 22:30 on 15 September in New York.
        rate_context.prepare(late, self.folders, clock=lambda: FIXED)
        selection = self.rate(late)["selection"]
        self.assertEqual((selection["publication_new_york_date"], selection["observation_date"],
                          selection["same_day_observation"]), ("2026-09-15", "2026-09-14", True))

    def test_missing_coverage_on_either_side_is_explicit_and_selects_nothing(self):
        self.retain()
        early, late = self.fomc("2026-09-09T14:00:00-04:00"), self.fomc("2026-09-21T14:00:00-04:00")
        for capture_id, reason in ((early, "none_before"), (late, "none_on_or_after")):
            prepared = rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
            shown = self.rate(capture_id)
            self.assertEqual((prepared["state"], shown["state"], shown["selection"]["reason"], shown["windows"],
                              shown["selection"]["observation_date"]), ("no_coverage", "no_coverage", reason, [], None))

    def test_a_missing_value_stays_unavailable_and_no_later_window_moves_up(self):
        rows = rate_fakes.standard_rows(skip={("2026-09-15", "2027-03-17", "Rate: mean")})
        self.book_sha = rate_fakes.write(self.book, rows)
        self.retain()
        capture_id = self.fomc()
        rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
        windows = self.rate(capture_id)["windows"]
        self.assertEqual([window["reference_start"] for window in windows],
                         ["2026-12-16", "2027-03-17", "2027-06-16", "2027-09-15"])
        self.assertIsNone(windows[1]["statistics"]["mean"])
        self.assertEqual(windows[1]["statistics"]["p25"]["percent"], "3.0575")

    def test_fewer_windows_are_shown_as_listed(self):
        self.book_sha = rate_fakes.write(self.book, rate_fakes.standard_rows(starts=rate_fakes.STARTS[:2]))
        self.retain()
        capture_id = self.fomc()
        rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
        shown = self.rate(capture_id)
        self.assertEqual((len(shown["windows"]), shown["windows_listed"]), (2, 2))

    def test_inconsistent_selected_rows_are_refused_and_nothing_is_written(self):
        crossed = {("2026-09-15", "2026-12-16", "Rate: 25th percentile"): " 340.00"}
        ranges = [row if (row[0], row[3]) != ("2026-09-15", "Rate: mode") else row[:2] + ("275bps - 300bps",) + row[3:]
                  for row in rate_fakes.standard_rows()]
        capture_id = self.fomc()
        for number, (rows, fragment) in enumerate(((rate_fakes.standard_rows(changes=crossed),
                                                    "25th percentile is above the 75th"),
                                                   (ranges, "2 different target ranges"))):
            with self.subTest(fragment=fragment):
                folders = rate_context.Folders(self.root / f"rate-{number}", self.folders.intake, self.folders.links)
                book = self.root / "input" / f"inconsistent-{number}.xlsx"
                rate_context.retain(book, rate_fakes.write(book, rows), OBTAINED, METHOD, folders.rate)
                with self.assertRaises(rate_context.RateRefused) as caught:
                    rate_context.prepare(capture_id, folders)
                self.assertIn(fragment, str(caught.exception))
                self.assertFalse((folders.rate / "events").exists())
                self.assertEqual(rate_context.view(capture_id, folders)["state"], "not_prepared")

    def test_other_topics_are_not_prepared_and_their_pages_show_nothing(self):
        self.retain()
        jobs = self.capture("The Employment Situation — September 2026", BLS_LINK)["capture_id"]
        with self.assertRaises(rate_context.RateRefused) as caught:
            rate_context.prepare(jobs, self.folders)
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(self.rate(jobs)["state"], "unsupported")
        self.assertEqual(self.rate("20260101T000000000000Z-000000000000", 404)["detail"].split(":")[0],
                         "This saved event cannot be read")

    def test_reads_never_fetch_prepare_or_write(self):
        capture_id = self.fomc()
        with no_network() as attempts:
            self.assertEqual(self.rate(capture_id)["state"], "not_prepared")
            self.assertFalse(self.folders.rate.exists())  # A read created nothing, not even a folder.
            self.retain()
            self.assertEqual(self.rate(capture_id)["state"], "not_prepared")  # A retained workbook is not a context.
            self.assertFalse((self.folders.rate / "events").exists())
            rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
            before = every_file(self.root)
            first = self.rate(capture_id)
            for _ in range(2):
                self.assertEqual(self.rate(capture_id), first)
            self.client.get(f"/api/events/capture/{capture_id}")
            self.assertEqual(every_file(self.root), before)
        self.assertEqual(attempts, [])
        self.no_calls()

    def test_preparing_again_derives_again_and_compares(self):
        self.retain()
        capture_id = self.fomc()
        rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
        again = rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
        self.assertEqual((again["saved_now"], again["version"]), (False, 1))
        record = self.folders.rate / "events" / f"capture-{capture_id}" / "1.json"
        writable(record)
        record.write_bytes(record.read_bytes().replace(b'" 315.50"', b'" 315.60"'))
        self.assertEqual(self.rate(capture_id)["state"], "available")  # Well formed: a read does not parse the workbook.
        with self.assertRaises(rate_context.RateRefused) as caught:
            rate_context.prepare(capture_id, self.folders)
        self.assertIn("differs from what the same workbook gives again", str(caught.exception))

    def test_another_workbook_is_a_new_version_and_earlier_versions_stay(self):
        self.retain()
        capture_id = self.fomc()
        rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
        second = self.root / "input" / "second.xlsx"
        rows = rate_fakes.standard_rows(changes={("2026-09-15", "2026-12-16", "Rate: mean"): " 316.00"})
        second_sha = rate_fakes.write(second, rows)
        source = self.retain(second, second_sha)["source_id"]
        with self.assertRaises(rate_context.RateRefused) as caught:
            rate_context.prepare(capture_id, self.folders)
        self.assertIn("2 workbooks are retained", str(caught.exception))
        prepared = rate_context.prepare(capture_id, self.folders, source, clock=lambda: FIXED)
        shown = self.rate(capture_id)
        self.assertEqual((prepared["version"], len(shown["versions"]), shown["provenance"]["source_id"],
                          shown["windows"][0]["statistics"]["mean"]["bp"]), (2, 2, source, "316.00"))

    def test_any_change_to_the_bound_records_makes_the_view_unreadable(self):
        self.retain()
        capture_id = self.fomc()
        rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
        source = self.folders.rate / "sources" / f"mpt-{self.book_sha[:16]}"
        record = self.folders.rate / "events" / f"capture-{capture_id}" / "1.json"
        validation = source / "validation-mpt-workbook-parser-0.1.json"
        changes = {
            "workbook bytes": (source / "workbook.xlsx", lambda data: data[:-1] + bytes([data[-1] ^ 1])),
            "validation record": (validation, lambda data: data.replace(b'"2026-09-14"', b'"2026-09-13"')),
            "acquisition record": (source / "acquisition.json", lambda data: data.replace(b'"http_status": null',
                                                                                         b'"http_status": 200')),
            "record field": (record, lambda data: data.replace(b'"calendar_days_before": 1',
                                                              b'"calendar_days_before": 2')),
            "record value form": (record, lambda data: data.replace(b'" 315.50"', b'"3.1550%"')),
            "record selection": (record, lambda data: data.replace(b'"observation_date": "2026-09-15"',
                                                                   b'"observation_date": "2026-09-14"')),
        }
        for name, (path, change) in changes.items():
            with self.subTest(name):
                original = path.read_bytes()
                writable(path)
                path.write_bytes(change(original))
                shown = self.rate(capture_id)
                self.assertEqual((shown["state"], shown["windows"]), ("unreadable", []), name)
                self.assertTrue(shown["problem"])
                path.write_bytes(original)
                self.assertEqual(self.rate(capture_id)["state"], "available")
        extra = source / "notes.txt"
        extra.write_text("SYNTHETIC", encoding="utf-8")
        self.assertEqual(self.rate(capture_id)["state"], "unreadable")
        extra.unlink()
        with patch.object(rate_workbook, "PARSER_VERSION", "mpt-workbook-parser-0.2"):
            self.assertIn("validation record for mpt-workbook-parser-0.2", self.rate(capture_id)["problem"])

    def test_an_origin_or_capture_other_than_the_bound_one_is_unreadable(self):
        self.retain()
        typed = self.fomc(origin=False)
        rate_context.prepare(typed, self.folders, clock=lambda: FIXED)
        self.assertEqual(self.rate(typed)["origin"], {"state": "none"})
        item = self.item(self.statement)
        event_links.record_origin(self.root / "links", typed, self.root / "intake", {
            "item_id": self.statement, "source": "fed-monetary", "content_sha256": item["content_sha256"], "version": 1,
            "versions": 1, "location": "current", "title": item["title"], "link": item["link"],
            "feed_timestamp_raw": item["feed_timestamp"]["raw"]}, lambda: FIXED)
        self.assertIn("Inbox origin differs", self.rate(typed)["problem"])

    def test_existing_records_stay_byte_identical_and_the_measures_stay_apart(self):
        capture_id = self.fomc()
        prepared = self.client.post("/api/research-analyses", content=json.dumps({"capture_id": capture_id}),
                                    headers=RESEARCH).json()
        request_id, request_sha = prepared["request_id"], prepared["request_sha256"]
        mocked = self.client.post(f"/api/research-analyses/{request_id}/mock", headers=RESEARCH,
                                  content=json.dumps({"request_sha256": request_sha, "mock_outcome": "analysis"}))
        self.assertEqual(mocked.status_code, 201, mocked.text)
        shown = self.client.get(f"/api/research-analyses/{request_id}").json()
        review = {"parent_review_id": None, "status": "needs_revision", "notes": "SYNTHETIC review.",
                  "binding": {"result_view_sha256": shown["result_view_sha256"], "request_sha256": request_sha,
                              "response_sha256": shown["result"]["provenance"]["response_sha256"]}}
        saved = self.client.post(f"/api/research-analyses/{request_id}/reviews", content=json.dumps(review),
                                 headers=RESEARCH)
        self.assertEqual(saved.status_code, 201, saved.text)
        overview = self.overview("capture", capture_id)
        research = self.client.get(f"/api/research-analyses/{request_id}").json()
        before = {name: data for name, data in every_file(self.root).items()
                  if not name.startswith(("rate-context", "input"))}
        self.retain()
        rate_context.prepare(capture_id, self.folders, clock=lambda: FIXED)
        after = {name: data for name, data in every_file(self.root).items()
                 if not name.startswith(("rate-context", "input"))}
        self.assertEqual(after, before)  # Capture, origin, request, attempt and review files: byte-identical.
        self.assertEqual(self.overview("capture", capture_id), overview)
        self.assertEqual(self.client.get(f"/api/research-analyses/{request_id}").json(), research)
        rate = self.rate(capture_id)
        self.assertEqual(rate["state"], "available")
        attempt = self.root / "research-analyses" / "attempts" / request_id / "request.json"
        self.assertNotIn(b"SOFR", attempt.read_bytes())  # The analysis request never carried this context.
        self.assertNotIn("SOFR", json.dumps(overview["market"]))
        self.assertFalse({"days", "endpoints", "series", "retrievals"} & set(rate))
        self.assertNotIn("Prob", json.dumps(rate["windows"]))  # Cut and hike probabilities are never carried.
        record = self.folders.rate / "events" / f"capture-{capture_id}" / "1.json"
        self.assertNotIn(b"Prob", record.read_bytes())


# ---------------------------------------------------------------- the command and the frontend fixtures

def scenario(data: Path) -> dict:
    """A deterministic SYNTHETIC data folder: four FOMC-shaped captures (one with a recorded origin) and a workbook."""
    intake, links = data / "intake", data / "event-links"
    ids = {name: save_capture(intake, STATEMENT, FED_LINK.format(code), published, FIXED)
           for name, code, published in (("available", "20260916a", PUBLISHED),
                                         ("no-coverage", "20260923a", "2026-09-23T14:00:00-04:00"),
                                         ("not-prepared", "20260729a", "2026-07-29T14:00:00-04:00"),
                                         ("unreadable", "20260917a", "2026-09-17T14:00:00-04:00"))}
    event_links.record_origin(links, ids["available"], intake, {
        "item_id": "fed-monetary:0123456789abcdef0123", "source": "fed-monetary", "content_sha256": "a" * 64,
        "version": 1, "versions": 1, "location": "current", "title": STATEMENT, "link": FED_LINK.format("20260916a"),
        "feed_timestamp_raw": "Wed, 16 Sep 2026 18:00:00 GMT"}, lambda: FIXED)
    book = data / "input" / "synthetic-mpt.xlsx"
    return {"ids": ids, "book": book, "sha": rate_fakes.write(book, compression=zipfile.ZIP_STORED)}


def run_cli(*argv: str) -> tuple[int, dict | str]:
    out, err = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", ["second_order", *argv]), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = cli.main()
    return code, json.loads(out.getvalue()) if code == 0 else err.getvalue()


class CommandAndFixtureTests(Folder):
    def test_the_commands_retain_prepare_and_show_locally(self):
        built = scenario(self.root)
        capture_id = built["ids"]["available"]
        with no_network() as attempts:
            code, kept = run_cli("rate-context", "retain", "--workbook", str(built["book"]), "--sha256", built["sha"],
                                 "--obtained-on", "2026-10-13", "--method", METHOD, "--data-dir", str(self.root))
            self.assertEqual((code, kept["retained_now"]), (0, True))
            code, done = run_cli("rate-context", "prepare", "--capture", capture_id, "--data-dir", str(self.root))
            self.assertEqual((code, done["saved_now"], done["observation_date"]), (0, True, "2026-09-15"))
            code, shown = run_cli("rate-context", "show", "--capture", capture_id, "--data-dir", str(self.root))
            self.assertEqual((code, shown["state"], shown["origin"]["state"]), (0, "available", "verified"))
            code, problem = run_cli("rate-context", "retain", "--workbook", str(built["book"]), "--sha256", "f" * 64,
                                    "--obtained-on", "2026-10-13", "--method", METHOD, "--data-dir", str(self.root))
            self.assertEqual(code, 1)
            self.assertIn("nothing was retained", problem)
        self.assertEqual(attempts, [])

    def test_served_views_match_the_committed_frontend_fixtures(self):
        built = scenario(self.root)
        folders = rate_context.folders_in(self.root)
        # The validation record names the parser library's version; pinned here so the fixtures do not depend on the
        # expat that this machine's Python ships.
        with patch.dict(rate_workbook.PARSER, {"library": "expat (pinned for the frontend fixtures)"}):
            rate_context.retain(built["book"], built["sha"], OBTAINED, METHOD, folders.rate, lambda: FIXED)
        for name in ("available", "no-coverage", "unreadable"):
            rate_context.prepare(built["ids"][name], folders, clock=lambda: FIXED)
        record = folders.rate / "events" / f"capture-{built['ids']['unreadable']}" / "1.json"
        writable(record)
        record.write_bytes(record.read_bytes().replace(b'"calendar_days_before": 1', b'"calendar_days_before": 0'))
        app = create_app(self.root / "prepared", None, self.root / "drafts", self.root / "reviews",
                         self.root / "intake", self.root / "attempts", links=self.root / "event-links",
                         market=self.root / "market", context=self.root / "no-bundle", inbox=self.root / "inbox")
        with TestClient(app, base_url=BASE) as client:
            for name, capture_id in built["ids"].items():
                served = client.get(f"/api/rate-context/capture/{capture_id}").json()
                self.assertEqual(served["state"], name.replace("-", "_"))
                path = FIXTURES / f"rate-path-{name}.json"
                text = json.dumps(served, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
                if os.environ.get(WRITE_FIXTURES) == "1":
                    path.write_bytes(text.encode("utf-8"))
                else:
                    self.assertEqual(served, json.loads(path.read_text(encoding="utf-8")),
                                     f"{path.name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest "
                                     "discover -s tests -p test_rate_context.py")


if __name__ == "__main__":
    unittest.main()
