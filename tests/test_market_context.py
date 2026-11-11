"""Market context for the case library: daily Treasury yields around a publication date, as description only.

Two kinds of test, kept apart. Most tests use SYNTHETIC rows in the Board's CSV format, in temporary folders: they
check parsing, preparation and the read-time verification, and say nothing about real values. CommittedBundleTests
read the committed bundle of real H.15 downloads and check every served value against the raw source rows with a
separate minimal reader, the windows against the real SIFMA calendar, and the bundle's integrity chain.
"""
import ast
from contextlib import redirect_stderr, redirect_stdout
import csv
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from second_order import context_publish, market_context
from second_order.api import create_app
from second_order.case_library import load_library
from second_order.context_lock import BundleBusy, bundle_write_lock
from second_order.demo import run_demo
from second_order.market_context import (BUNDLE_DIR, CONTEXT_CASES, SERIES, ContextRefused, append, bundle_cases,
                                         event_window, export_url, load_context, parse_h15_csv, prepare, sha256)

ROOT = Path(__file__).resolve().parent.parent
# The served views the frontend tests read; rewritten only when WRITE_FIXTURES is set to 1, otherwise compared.
FRONTEND_FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"
CASE = "empsit-2025-07-03"  # Window 2025-06-19 .. 2025-07-17: Juneteenth, July 4 and four weekends.
TWO, TEN = "RIFLGFCY02_N.B", "RIFLGFCY10_N.B"
JUNETEENTH, JULY_4 = date(2025, 6, 19), date(2025, 7, 4)
WINDOWS = [("fomc-2025-01-29", "2025-01-15", "2025-02-12"), ("fomc-2025-03-19", "2025-03-05", "2025-04-02"),
           ("empsit-2025-04-04", "2025-03-21", "2025-04-18"), ("cpi-2025-04-10", "2025-03-27", "2025-04-24"),
           ("empsit-2025-05-02", "2025-04-18", "2025-05-16"), ("fomc-2025-05-07", "2025-04-23", "2025-05-21"),
           ("cpi-2025-05-13", "2025-04-29", "2025-05-27"), ("empsit-2025-06-06", "2025-05-23", "2025-06-20"),
           ("cpi-2025-06-11", "2025-05-28", "2025-06-25"), ("fomc-2025-06-18", "2025-06-04", "2025-07-02"),
           ("empsit-2025-07-03", "2025-06-19", "2025-07-17"), ("cpi-2025-07-15", "2025-07-01", "2025-07-29")]
RUN_1 = ("fomc-2025-03-19", "empsit-2025-07-03", "cpi-2025-07-15")  # Downloaded 2026-10-07 22:07 UTC.
# The first run's eight files, pinned as first prepared: appending later runs must never change them.
RUN_1_FILES = {
    "manifest.json": "96de3ec7bfba68a696f67b5c458dc2c98c9bec653c2583a4e48a690c18fb2359",
    "fomc-2025-03-19.json": "78845ca056cdea8299307807fb85cfcf03d1bfd0b9720755172475f8af7d29fb",
    "empsit-2025-07-03.json": "87f6f6630930b9bdcd990a46dd56bd2a490de34c5f878267f20126ca26f64d7f",
    "cpi-2025-07-15.json": "395d74dcd3ff196a75696bfb9860457f79b639ab1b8da10865deebb1e97f1aa7",
    "sources/acquisition.json": "0885e87d3c2cf0ea88dc5bc4dfc58c52df6f3b89f0772520b537e3ae01af9b99",
    "sources/fomc-2025-03-19.csv": "4241e742f93cfaeb14e3e49357b8f9af151b4ea2f07de47e161d57b03bc5eabe",
    "sources/empsit-2025-07-03.csv": "19992ed33f85e972ffa16107fee459393ef2824e552f6364b7f5640d32b1c677",
    "sources/cpi-2025-07-15.csv": "6747d3f8211269fa558a9bb7aa3597c2bf98f33319f9e8bb50a800e25d2847c0",
}
REQUESTED = datetime(2026, 10, 7, 22, 7, 4, tzinfo=timezone.utc)
# Publication times recorded in the names of moved-aside folders, given to publication's clock by recorded_times.
T1 = datetime(2026, 10, 8, 9, 15, 0, 123456, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 8, 9, 16, 0, 654321, tzinfo=timezone.utc)
# What a reader is told while a bundle is missing and copies recorded as its own lie beside it: no folder is named.
VIEWER_INTERRUPTED = ("Market context is unavailable: its bundle folder is missing and a moved-aside copy is beside it, "
                      "so a publication may have been interrupted. The operator can run `python -m "
                      "second_order.market_context check` for recovery details")
NOT_PREPARED = "Market context has not been prepared for the case library"
HEADER = [["Series Description", SERIES[TWO]["description"], SERIES[TEN]["description"]],
          ["Unit:", "Percent:_Per_Year", "Percent:_Per_Year"],
          ["Multiplier:", "1", "1"],
          ["Currency:", "NA", "NA"],
          ["Unique Identifier: ", "H15/H15/RIFLGFCY02_N.B", "H15/H15/RIFLGFCY10_N.B"],
          ["Time Period", TWO, TEN]]


def weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def h15_csv(start: date, end: date, values: dict | None = None, skip: frozenset = frozenset(),
            header: list | None = None) -> bytes:
    """A Data Download Program-style CSV: quoted labelled header rows, then one row per weekday, CRLF, no final
    newline. SYNTHETIC values only: 1.00, 1.01, ... for the 2-year and 2.00, 2.01, ... for the 10-year."""
    values = values or {}
    lines = [",".join(f'"{cell}"' for cell in row) for row in (header or HEADER)]
    for i, day in enumerate(weekdays(start, end)):
        if day in skip:
            continue
        two = values.get((TWO, day), f"{1 + i / 100:.2f}")
        ten = values.get((TEN, day), f"{2 + i / 100:.2f}")
        lines.append(f"{day.isoformat()},{two},{ten}")
    return "\r\n".join(lines).encode("ascii")


def download_record(case_id: str, data: bytes, **changes) -> dict:
    _, start, end = event_window(load_case(case_id)["source"]["published_at"])
    record = {"case": case_id, "file": f"{case_id}.csv", "url": export_url(start, end),
              "requested_at": REQUESTED.isoformat(), "received_at": (REQUESTED + timedelta(seconds=1)).isoformat(),
              "http_status": 200, "content_type": "text/csv", "response_date": format_datetime(REQUESTED, usegmt=True),
              "bytes": len(data), "sha256": sha256(data)}
    return {**record, **changes}


def recorded_times(*moments: datetime):
    """The clock publication reads to name a moved-aside folder, giving `moments` in order."""
    queue = list(moments)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return queue.pop(0)
    return patch.object(context_publish, "datetime", Clock)


def sessions_without(*holidays: date):
    """A synthetic session calendar: weekdays except the given holidays."""
    return lambda start, end: {day for day in weekdays(start, end) if day not in holidays}


def load_case(case_id: str) -> dict:
    return next(case for case in load_library()["cases"] if case["id"] == case_id)


class Preparation(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.staging, self.bundle = self.root / "staging", self.root / "bundle"
        self.staging.mkdir()
        self.records = {}

    def stage(self, case_id: str, values: dict | None = None, skip: frozenset = frozenset(), data: bytes | None = None,
              **record_changes) -> bytes:
        _, start, end = event_window(load_case(case_id)["source"]["published_at"])
        holidays = {(series, day): "ND" for series in (TWO, TEN) for day in (JUNETEENTH, JULY_4)}
        data = h15_csv(start, end, {**holidays, **(values or {})}, skip) if data is None else data
        (self.staging / f"{case_id}.csv").write_bytes(data)
        self.records[case_id] = download_record(case_id, data, **record_changes)
        self.write_record()
        return data

    def write_record(self, **extra) -> None:
        record = {"tool": "synthetic test writer", "downloads": list(self.records.values()), **extra}
        (self.staging / "acquisition.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    def prepared(self, cases=(CASE,), sessions=sessions_without(JUNETEENTH, JULY_4)) -> dict:
        return prepare(self.staging, self.bundle, cases, "Synthetic test rows", sessions=sessions)

    def view(self, case_id: str = CASE) -> dict:
        return json.loads((self.bundle / f"{case_id}.json").read_text(encoding="utf-8"))


class WindowTests(unittest.TestCase):
    def test_windows_are_fourteen_calendar_days_either_side_of_the_new_york_publication_date(self):
        self.assertEqual(event_window("2025-03-19T14:00:00-04:00"), (date(2025, 3, 19), date(2025, 3, 5), date(2025, 4, 2)))
        self.assertEqual(event_window("2025-07-03T08:30:00-04:00"), (date(2025, 7, 3), date(2025, 6, 19), date(2025, 7, 17)))
        self.assertEqual(event_window("2025-07-15T08:30:00-04:00"), (date(2025, 7, 15), date(2025, 7, 1), date(2025, 7, 29)))
        # The New York date, not the UTC date: 22:30 EDT is already the next day in UTC.
        self.assertEqual(event_window("2025-07-15T22:30:00-04:00")[0], date(2025, 7, 15))
        self.assertEqual(event_window("2025-07-16T02:30:00+00:00")[0], date(2025, 7, 15))
        self.assertEqual(event_window("2025-01-29T19:00:00+00:00")[0], date(2025, 1, 29))  # EST in January.
        with self.assertRaises(ContextRefused):
            event_window("2025-07-15T08:30:00")  # No offset: refused rather than assumed.

    def test_every_macro_library_case_declares_context_and_no_sector_case_does(self):
        library = load_library()
        macro = tuple(case["id"] for case in library["cases"] if case["library_version"] == "case-library-0.1")
        self.assertEqual(CONTEXT_CASES, macro)  # All twelve macro cases, in publication order.
        self.assertEqual(tuple(library["collection"]["market_context"]), CONTEXT_CASES)
        sector = {case["id"] for case in library["cases"] if case.get("sectors")}
        self.assertEqual(len(sector), 12)
        self.assertFalse(sector & set(CONTEXT_CASES))  # Treasury yields are not attached to sector cases.

    def test_each_case_has_one_exact_board_download_address_for_its_fixed_window(self):
        self.assertEqual(export_url(date(2025, 3, 5), date(2025, 4, 2)),
                         "https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&series="
                         "aa2b841a39cf82a8a04208d30ba16c2e&lastobs=&from=03/05/2025&to=04/02/2025&filetype=csv"
                         "&label=include&layout=seriescolumn")
        listed = market_context.urls()
        self.assertEqual([(row["case"], row["start"], row["end"]) for row in listed], WINDOWS)
        for row in listed:  # Each window is the New York publication date plus or minus 14 calendar days.
            day = event_window(load_case(row["case"])["source"]["published_at"])[0]
            self.assertEqual((date.fromisoformat(row["start"]), date.fromisoformat(row["end"])),
                             (day - timedelta(days=14), day + timedelta(days=14)))
            self.assertEqual(row["url"], export_url(date.fromisoformat(row["start"]), date.fromisoformat(row["end"])))

    def test_the_series_are_the_boards_two_and_ten_year_constant_maturity_yields_in_percent(self):
        self.assertEqual(list(SERIES), [TWO, TEN])
        for series_id, fred_id in ((TWO, "DGS2"), (TEN, "DGS10")):
            series = SERIES[series_id]
            self.assertEqual((series["unit"], series["units_label"], series["multiplier"], series["frequency"]),
                             ("Percent:_Per_Year", "Percent per year", "1", "Business day"))
            self.assertEqual((series["unique_identifier"], series["fred_equivalent"]), (f"H15/H15/{series_id}", fred_id))


class ParsingTests(unittest.TestCase):
    def test_board_csv_rows_are_kept_exactly_and_no_value_stays_missing(self):
        data = h15_csv(date(2025, 7, 1), date(2025, 7, 8), {(TWO, JULY_4): "ND", (TEN, JULY_4): "ND",
                                                            (TEN, date(2025, 7, 8)): "ND"})
        rows = parse_h15_csv(data)
        self.assertEqual(list(rows), [TWO, TEN])
        self.assertEqual(rows[TWO][:4], [(date(2025, 7, 1), "1.00", 1.0), (date(2025, 7, 2), "1.01", 1.01),
                                         (date(2025, 7, 3), "1.02", 1.02), (JULY_4, "ND", None)])
        self.assertEqual(rows[TEN][-1], (date(2025, 7, 8), "ND", None))
        swapped = [[row[0], row[2], row[1]] for row in HEADER]  # Columns in the other order are matched by identifier.
        text = h15_csv(date(2025, 7, 1), date(2025, 7, 1), header=swapped).decode("ascii")
        self.assertEqual(parse_h15_csv(text.replace("2025-07-01,1.00,2.00", "2025-07-01,2.00,1.00").encode())[TWO],
                         [(date(2025, 7, 1), "1.00", 1.0)])

    def test_another_series_unit_or_shape_is_refused(self):
        def header_with(row: int, column: int, text: str) -> list:
            changed = [list(cells) for cells in HEADER]
            changed[row][column] = text
            return changed

        good = h15_csv(date(2025, 7, 1), date(2025, 7, 3)).decode("ascii")
        bad = {
            "another maturity": h15_csv(date(2025, 7, 1), date(2025, 7, 3), header=header_with(4, 1, "H15/H15/RIFLGFCY05_N.B")),
            "another unit": h15_csv(date(2025, 7, 1), date(2025, 7, 3), header=header_with(1, 2, "Percent")),
            "a multiplier": h15_csv(date(2025, 7, 1), date(2025, 7, 3), header=header_with(2, 1, "1000")),
            "another description": h15_csv(date(2025, 7, 1), date(2025, 7, 3), header=header_with(0, 1, "Federal funds")),
            "a mislabelled column": h15_csv(date(2025, 7, 1), date(2025, 7, 3), header=header_with(5, 1, TEN)),
            "the same series twice": h15_csv(date(2025, 7, 1), date(2025, 7, 3),
                                             header=header_with(4, 2, "H15/H15/RIFLGFCY02_N.B")),
            "no header": "\r\n".join(good.split("\r\n")[6:]).encode(),
            "a header row missing": "\r\n".join(good.split("\r\n")[1:]).encode(),
            "an extra column": good.replace("\r\n2025-07-01,1.00,2.00", "\r\n2025-07-01,1.00,2.00,3.00").encode(),
            "unsorted dates": good.replace("2025-07-02", "2025-06-30").encode(),
            "a repeated date": good.replace("2025-07-02", "2025-07-01").encode(),
            "a text value": good.replace("1.01", "n/a").encode(),
            "a blank value": good.replace("1.01", "").encode(),
            "a non-finite value": good.replace("1.01", "NaN").encode(),
            "an exponent": good.replace("1.01", "1e0").encode(),
            "a bad date": good.replace("2025-07-02", "2025-02-30").encode(),
            "a short date": good.replace("2025-07-02", "2025-7-2").encode(),
            "no data rows": "\r\n".join(good.split("\r\n")[:6]).encode(),
            "a byte-order mark": b"\xef\xbb\xbf" + good.encode(),
            "not text": b"\xff\xfe\x00",
        }
        for name, data in bad.items():
            with self.subTest(name), self.assertRaises(ContextRefused):
                parse_h15_csv(data)


class PrepareTests(Preparation):
    def test_every_calendar_date_is_classified_and_nothing_is_filled(self):
        missing, absent = date(2025, 7, 9), date(2025, 7, 10)
        self.stage(CASE, {(TEN, missing): "ND"}, skip=frozenset({absent}))
        self.prepared()
        view = self.view()
        days = {day["date"]: day for day in view["days"]}
        self.assertEqual((view["window"]["start"], view["window"]["end"], len(days)), ("2025-06-19", "2025-07-17", 29))
        status = lambda day, series: days[day]["observations"][series]["status"]
        value = lambda day, series: days[day]["observations"][series]["value"]
        self.assertEqual(status("2025-06-21", TWO), "not_a_session")  # Saturday: no row, no session.
        self.assertEqual(status("2025-06-19", TWO), "calendar_holiday")  # Juneteenth: an ND row on a holiday.
        self.assertEqual(days["2025-06-19"]["observations"][TWO]["raw"], "ND")
        self.assertEqual(status("2025-07-04", TEN), "calendar_holiday")
        self.assertEqual((status("2025-07-09", TEN), value("2025-07-09", TEN)), ("session_missing", None))
        self.assertEqual((status("2025-07-09", TWO), days["2025-07-09"]["observations"][TWO]["raw"]),
                         ("session_value", "1.14"))  # Only the series without a value is missing.
        for series in (TWO, TEN):  # A missing row: both series absent on an expected session.
            self.assertEqual((status("2025-07-10", series), value("2025-07-10", series),
                              days["2025-07-10"]["observations"][series]["raw"]), ("session_absent", None, None))
        # Neighbours of a gap are unchanged and the gap is not filled.
        self.assertEqual((value("2025-07-08", TEN), value("2025-07-11", TEN)), (2.13, 2.16))
        self.assertTrue(all(day["observations"][series]["value"] is None for day in view["days"]
                            for series in (TWO, TEN) if day["observations"][series]["status"] != "session_value"))

    def test_a_weekend_row_without_a_value_is_a_weekend_and_a_weekend_value_is_not_an_observation(self):
        _, start, end = event_window(load_case(CASE)["source"]["published_at"])
        text = h15_csv(start, end, {(series, day): "ND" for series in (TWO, TEN) for day in (JUNETEENTH, JULY_4)})
        text = text.decode("ascii").replace("\r\n2025-06-23,", "\r\n2025-06-21,ND,ND\r\n2025-06-22,1.50,2.50\r\n2025-06-23,")
        self.stage(CASE, data=text.encode("ascii"))
        self.prepared()
        days = {day["date"]: day["observations"] for day in self.view()["days"]}
        self.assertEqual(days["2025-06-21"][TWO], {"raw": "ND", "value": None, "status": "not_a_session"})
        self.assertEqual(days["2025-06-22"][TEN], {"raw": "2.50", "value": None,
                                                    "status": "unreconciled_value_on_calendar_holiday"})

    def test_the_real_sifma_calendar_explains_juneteenth_and_independence_day(self):
        self.stage(CASE)
        self.prepared(sessions=market_context.expected_sessions)
        days = {day["date"]: day for day in self.view()["days"]}
        for holiday in ("2025-06-19", "2025-07-04"):
            self.assertFalse(days[holiday]["session"], holiday)
            self.assertEqual(days[holiday]["observations"][TWO]["status"], "calendar_holiday")
        self.assertTrue(days["2025-07-03"]["session"])  # An early-close day is still a session.

    def test_sources_the_acquisition_record_and_their_hashes_are_kept_and_bound(self):
        data = self.stage(CASE)
        result = self.prepared()
        manifest = json.loads((self.bundle / "manifest.json").read_text(encoding="utf-8"))
        view_bytes = (self.bundle / f"{CASE}.json").read_bytes()
        self.assertEqual(manifest["contexts"][CASE]["view_sha256"], sha256(view_bytes))
        kept = (self.bundle / "sources" / "acquisition.json").read_bytes()
        self.assertEqual(kept, (self.staging / "acquisition.json").read_bytes())
        self.assertEqual(manifest["acquisition"]["record_sha256"], sha256(kept))
        source = json.loads(view_bytes)["source"]
        self.assertEqual((self.bundle / source["file"]).read_bytes(), data)
        self.assertEqual((source["sha256"], source["bytes"], source["url"]), (sha256(data), len(data),
                                                                              self.records[CASE]["url"]))
        self.assertEqual((source["requested_start"], source["requested_end"]), ("2025-06-19", "2025-07-17"))
        self.assertEqual((source["returned_first"], source["returned_last"], source["rows"]), ("2025-06-19", "2025-07-17", 21))
        self.assertEqual((source["requested_at"], source["http_status"]), ("2026-10-07T22:07:04+00:00", 200))
        self.assertIsNone(manifest["acquisition"]["vintage"])
        self.assertIn("not available", manifest["acquisition"]["vintage_note"])
        self.assertTrue(all("retrieved October 7, 2026 (UTC)" in record["citation"]
                            for record in manifest["series"].values()))
        index = json.loads((self.bundle / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index, {"index_version": market_context.INDEX_VERSION, "runs": [
            {"run": 1, "manifest": "manifest.json",
             "manifest_sha256": sha256((self.bundle / "manifest.json").read_bytes())}]})
        self.assertEqual((result["run"], result["contexts"]), (1, [CASE]))

    def test_incomplete_mismatched_or_unrecorded_sources_are_refused_and_nothing_is_written(self):
        _, start, end = event_window(load_case(CASE)["source"]["published_at"])
        other_url = export_url(start - timedelta(days=1), end)
        refusals = {
            "a different address": dict(url=other_url),
            "an error status": dict(http_status=500),
            "an HTML reply": dict(content_type="text/html"),
            "another file's hash": dict(sha256="0" * 64),
            "a request time without an offset": dict(requested_at="2026-10-07T22:07:04"),
            "a server date an hour away": dict(response_date=format_datetime(REQUESTED + timedelta(hours=1), usegmt=True)),
            "a receipt before the request": dict(received_at=(REQUESTED - timedelta(seconds=5)).isoformat()),
        }
        for name, change in refusals.items():
            with self.subTest(name):
                self.stage(CASE, **change)
                with self.assertRaises(ContextRefused):
                    self.prepared()
                self.assertFalse(self.bundle.exists())
        self.stage(CASE)
        (self.staging / "extra.csv").write_bytes(b"observation_date,DGS2\n")
        with self.assertRaises(ContextRefused):
            self.prepared()
        (self.staging / "extra.csv").unlink()
        self.stage(CASE, data=b"")  # An empty reply.
        with self.assertRaises(ContextRefused):
            self.prepared()
        self.stage(CASE, data=h15_csv(date(2025, 6, 30), date(2025, 7, 17)))  # Starts eleven days into the window.
        with self.assertRaises(ContextRefused):
            self.prepared()
        self.stage(CASE)
        self.records["cpi-2025-07-15"] = dict(self.records[CASE], case="cpi-2025-07-15")
        self.write_record()  # A record for a case that is not being prepared.
        with self.assertRaises(ContextRefused):
            self.prepared()
        del self.records["cpi-2025-07-15"]
        (self.staging / f"{CASE}.csv").unlink()
        self.write_record()
        with self.assertRaises(ContextRefused):
            self.prepared()
        self.assertFalse(self.bundle.exists())

    def test_an_existing_bundle_is_replaced_only_on_request(self):
        self.stage(CASE)
        self.prepared()
        with self.assertRaises(ContextRefused) as caught:
            self.prepared()
        self.assertEqual(caught.exception.status, 409)
        prepare(self.staging, self.bundle, (CASE,), "Synthetic test rows", sessions=sessions_without(JUNETEENTH, JULY_4),
                replace=True)
        self.assertEqual(load_context(CASE, self.bundle)["case_id"], CASE)

    def test_a_destination_filled_while_preparing_is_refused_and_left_as_it_is(self):
        self.stage(CASE)
        write_run, outside = market_context._write_run, b"written meanwhile by a process that ignores the lock"

        def outside_writer(work, *args):
            manifest = write_run(work, *args)
            self.bundle.mkdir(exist_ok=True)
            (self.bundle / "someone-else.txt").write_bytes(outside)
            return manifest

        with patch.object(market_context, "_write_run", outside_writer), self.assertRaises(ContextRefused) as caught:
            self.prepared()
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("was filled by another process while the bundle was prepared; nothing was published",
                      str(caught.exception))
        self.assertEqual({path.name: path.read_bytes() for path in self.bundle.iterdir()}, {"someone-else.txt": outside})
        self.assertEqual(list(self.root.glob(".market-context-*")), [])
        with bundle_write_lock(self.bundle):  # Released: it can be taken again at once.
            pass


class LoaderTests(Preparation):
    def setUp(self):
        super().setUp()
        self.stage(CASE)
        self.prepared()

    def load(self, case_id: str = CASE) -> dict:
        return load_context(case_id, self.bundle)

    def refused(self, status: int, case_id: str = CASE) -> str:
        with self.assertRaises(ContextRefused) as caught:
            self.load(case_id)
        self.assertEqual(caught.exception.status, status)
        return str(caught.exception)

    def rewrite(self, name: str, change) -> bytes:
        """Changes a bundle JSON file and returns its original bytes."""
        path = self.bundle / name
        original = path.read_bytes()
        value = json.loads(original)
        change(value)
        path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        return original

    def rebind(self) -> bytes:
        """Records every manifest's current SHA-256 in the index, as a forger would; returns the index's bytes."""
        return self.rewrite("index.json", lambda index: [run.update(
            manifest_sha256=sha256((self.bundle / run["manifest"]).read_bytes())) for run in index["runs"]])

    def restore(self, files: dict) -> None:
        for name, data in files.items():
            (self.bundle / name).write_bytes(data)

    def test_a_valid_bundle_is_served_with_its_provenance(self):
        view = self.load()
        self.assertEqual(view["view_version"], market_context.VIEW_VERSION)
        self.assertEqual((view["publication"]["new_york_date"], view["window"]["start"], view["window"]["end"]),
                         ("2025-07-03", "2025-06-19", "2025-07-17"))
        self.assertEqual([(series["id"], series["unit"], series["values"], series["no_value_rows"])
                          for series in view["series"]], [(TWO, "Percent:_Per_Year", 19, 2), (TEN, "Percent:_Per_Year", 19, 2)])
        provenance = view["provenance"]
        self.assertEqual(provenance["view_sha256"], sha256((self.bundle / f"{CASE}.json").read_bytes()))
        self.assertEqual(provenance["manifest_sha256"], sha256((self.bundle / "manifest.json").read_bytes()))
        self.assertEqual((provenance["method"], provenance["publisher"], provenance["vintage"]),
                         ("Synthetic test rows", "Board of Governors of the Federal Reserve System", None))
        self.assertIn("public domain", provenance["terms"]["statement"])

    def test_tampered_or_missing_parts_are_refused_honestly(self):
        source = self.bundle / "sources" / f"{CASE}.csv"
        original = source.read_bytes()
        source.write_bytes(original.replace(b"1.01", b"1.02", 1))
        self.assertIn("SHA-256", self.refused(500))
        source.write_bytes(original)
        record = self.bundle / "sources" / "acquisition.json"
        recorded = record.read_bytes()
        record.write_bytes(recorded.replace(b"22:07:04", b"22:07:05", 1))
        self.assertIn("acquisition record", self.refused(500))
        record.write_bytes(recorded)
        view_path = self.bundle / f"{CASE}.json"
        view = view_path.read_bytes()
        view_path.write_bytes(view.replace(b'"value": 1.01', b'"value": 1.5', 1))
        self.refused(500)
        view_path.write_bytes(view)
        self.load()  # Restored byte for byte: valid again.
        manifest = self.rewrite("manifest.json", lambda m: m["acquisition"].update(method="Edited later"))
        self.assertIn("does not match the SHA-256 recorded in index.json", self.refused(500))
        self.restore({"manifest.json": manifest})
        index = self.bundle / "index.json"
        recorded_index = index.read_bytes()
        for change, problem in ((lambda i: i.update(index_version="market-context-index-9"), "list of acquisition runs"),
                                (lambda i: i["runs"][0].update(run=2), "is not run 1"),
                                (lambda i: i["runs"][0].update(manifest="manifest-1.json"), "is not run 1"),
                                (lambda i: i["runs"].append(dict(i["runs"][0])), "is not run 2"),
                                (lambda i: i.update(runs=[]), "list of acquisition runs")):
            self.rewrite("index.json", change)
            self.assertIn(problem, self.refused(500))
            index.write_bytes(recorded_index)
        self.load()
        (self.bundle / "manifest.json").unlink()
        self.assertIn("is missing", self.refused(500))
        self.restore({"manifest.json": manifest})
        index.unlink()
        self.assertIn("not been prepared", self.refused(503))  # No index, no bundle: an old manifest is not read.
        index.write_bytes(recorded_index)
        source.unlink()
        self.refused(500)
        shutil.rmtree(self.bundle)
        self.assertIn("not been prepared", self.refused(503))

    def test_a_view_or_manifest_that_disagrees_is_refused_even_with_matching_hashes(self):
        def rehash(change, problem: str):
            original = self.rewrite(f"{CASE}.json", change)
            manifest = self.rewrite("manifest.json", lambda m: m["contexts"][CASE].update(
                view_sha256=sha256((self.bundle / f"{CASE}.json").read_bytes())))
            index = self.rebind()
            self.assertIn(problem, self.refused(500))
            self.restore({f"{CASE}.json": original, "manifest.json": manifest, "index.json": index})
            self.load()

        def first_value(view):
            day = next(day for day in view["days"] if day["observations"][TEN]["status"] == "session_value")
            day["observations"][TEN]["value"] = 9.99

        def holiday_as_gap(view):
            day = next(day for day in view["days"] if day["date"] == "2025-07-04")
            day["observations"][TWO]["status"] = "session_missing"

        rehash(first_value, "source rows")
        rehash(holiday_as_gap, "source rows")
        rehash(lambda view: view["source"].update(url="https://example.org/yields.csv"), "download record")
        rehash(lambda view: view["source"].update(file="../manifest.json"), "missing")
        rehash(lambda view: view.update(sessions=view["sessions"] + ["2025-07-04"]), "source rows")
        rehash(lambda view: view["window"].update(start="2025-06-20"), "14-day window")

        for change, problem in ((lambda m: m["series"][TWO].update(unit="Percent"), "percent per year"),
                                (lambda m: m["series"][TEN].update(fred_equivalent="DGS5"), "as declared"),
                                (lambda m: m["acquisition"].update(vintage="2025-07-03"), "vintage"),
                                (lambda m: m["series"][TWO].update(citation="Retrieved from FRED."), "citations"),
                                (lambda m: m["terms"].update(url="https://example.org/"), "terms"),
                                (lambda m: m["acquisition"].update(record="sources/acquisition-2.json"),
                                 "own acquisition record")):
            original = self.rewrite("manifest.json", change)
            index = self.rebind()
            self.assertIn(problem, self.refused(500))
            self.restore({"manifest.json": original, "index.json": index})
        self.load()

    def test_cases_without_context_in_the_bundle_are_not_found(self):
        self.refused(404, "no-such-case")
        self.refused(404, "cpi-2025-04-10")  # Declared, but not in this test bundle.
        self.refused(404, "cpi-2025-07-15")


class AppendTests(Preparation):
    """A second acquisition run beside the first: the first run's files never change and both stay verifiable."""

    SECOND = "cpi-2025-07-15"
    CALENDAR = staticmethod(sessions_without(JUNETEENTH, JULY_4))
    ONLY_SECOND = ("only the second case",)  # A marker; None means append's own default (every case still missing).

    def setUp(self):
        super().setUp()
        self.stage(CASE)
        self.prepared()
        self.first = self.files()
        self.staging, self.records = self.root / "staging-2", {}  # A separate staging folder for the next run.
        self.staging.mkdir()

    def files(self) -> dict:
        return {path.relative_to(self.bundle).as_posix(): path.read_bytes()
                for path in self.bundle.rglob("*") if path.is_file()}

    def appended(self, cases=ONLY_SECOND) -> dict:
        return append(self.staging, self.bundle, [self.SECOND] if cases is self.ONLY_SECOND else cases,
                      "Synthetic run 2", sessions=self.CALENDAR)

    def refused(self, cases=ONLY_SECOND) -> str:
        before = self.files()
        with self.assertRaises(ContextRefused) as caught:
            self.appended(cases)
        self.assertEqual(self.files(), before)  # A refused append changes nothing.
        self.assertEqual(list(self.bundle.parent.glob(".market-context-*")), [])
        return str(caught.exception)

    @staticmethod
    def files_of(folder: Path) -> dict:
        return {path.relative_to(folder).as_posix(): path.read_bytes() for path in folder.rglob("*") if path.is_file()}

    def leftovers(self) -> list[str]:
        return sorted(path.name for path in self.bundle.parent.glob(".market-context-*"))

    def lock_is_free(self) -> bool:
        try:
            with bundle_write_lock(self.bundle):
                return True
        except BundleBusy:
            return False

    def renames_failing(self, *steps: str, bundle: Path | None = None):
        """Path.rename, with the named publication steps of `bundle` (default: this test's) refused as the OS would
        refuse them: "aside" (the bundle to its moved-aside folder), "into place" (the working folder to the bundle)
        and "restore" (back again)."""
        rename, bundle = Path.rename, bundle or self.bundle

        def renaming(source, target):
            source, target = Path(source), Path(target)
            step = ("aside" if source == bundle else
                    "restore" if source.name.startswith(".market-context-previous-") and target == bundle else
                    "into place" if source.name.startswith(".market-context-") and target == bundle else None)
            if step in steps:
                raise PermissionError(13, f"Synthetic refusal ({step})", str(source))
            return rename(source, target)
        return patch.object(Path, "rename", renaming)

    def cleanup_refused(self):
        """shutil.rmtree, except that removing a moved-aside folder is refused before anything in it goes."""
        remove = shutil.rmtree

        def stubborn(path, *args, **kwargs):
            if Path(path).name.startswith(".market-context-previous-"):
                raise PermissionError(13, "Synthetic refusal (cleanup)", str(path))
            return remove(path, *args, **kwargs)
        return patch("shutil.rmtree", stubborn)

    def staging_for(self, name: str, case_id: str) -> Path:
        """A new staging folder holding one synthetic download of `case_id`; it becomes this test's staging."""
        self.records, self.staging = {}, self.root / name
        self.staging.mkdir()
        self.stage(case_id)
        return self.staging

    def asides(self) -> list[Path]:
        return sorted(self.root.glob(".market-context-previous-*"))

    def snapshot(self) -> dict:
        """Every name, byte and modification time under the test folder."""
        return {path.relative_to(self.root).as_posix(): (path.read_bytes() if path.is_file() else None,
                                                         path.stat().st_mtime_ns) for path in self.root.rglob("*")}

    def recovery_is_reported(self, newest: Path) -> str:
        """With the bundle missing and copies recorded as its own beside it: append and prepare refuse with one and
        the same report, which names `newest` (its files verify) as the most recent recorded copy and gives the only
        restore instruction; a read says only that a publication may have been interrupted; nothing changes."""
        before = self.snapshot()
        with self.assertRaises(ContextRefused) as appending:
            self.appended()
        with self.assertRaises(ContextRefused) as preparing:
            prepare(self.staging, self.bundle, [self.SECOND], "Synthetic rebuild", sessions=self.CALENDAR)
        with self.assertRaises(ContextRefused) as reading:
            load_context(CASE, self.bundle)
        message = str(appending.exception)
        self.assertEqual((appending.exception.status, preparing.exception.status, str(preparing.exception)),
                         (409, 409, message))
        self.assertTrue(message.startswith(
            f"No bundle is at {self.bundle}. Nothing has been restored, moved or deleted, and no folder is chosen for "
            f"you. Copies recorded as moved aside from {self.bundle.name} are beside it, so a publication may have "
            "been interrupted between its two renames. Newest recorded time first: (1) "), message)
        self.assertIn(f"The most recent recorded copy is {newest}. To restore it, make sure nothing is at {self.bundle}, "
                      f"then rename it to {self.bundle}.", message)
        self.assertEqual(message.count("rename it to"), 1)  # The one instruction, for that copy only.
        self.assertNotIn("use prepare", message)
        self.assertEqual((reading.exception.status, str(reading.exception)), (503, VIEWER_INTERRUPTED))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.bundle.exists())
        return message

    def test_a_second_run_is_added_beside_the_first_without_changing_it(self):
        self.stage(self.SECOND, requested_at=(REQUESTED + timedelta(minutes=41)).isoformat(),
                   received_at=(REQUESTED + timedelta(minutes=41, seconds=1)).isoformat(),
                   response_date=format_datetime(REQUESTED + timedelta(minutes=41), usegmt=True))
        self.assertEqual(self.appended(), {"bundle": str(self.bundle), "run": 2, "contexts": [self.SECOND]})
        after = self.files()
        self.assertEqual({name: data for name, data in after.items() if name in self.first and name != "index.json"},
                         {name: data for name, data in self.first.items() if name != "index.json"})
        self.assertEqual(sorted(set(after) - set(self.first)), sorted([
            "manifest-2.json", "sources/acquisition-2.json", f"sources/{self.SECOND}.csv", f"{self.SECOND}.json"]))
        index = json.loads(after["index.json"])
        self.assertEqual([(run["run"], run["manifest"], run["manifest_sha256"]) for run in index["runs"]],
                         [(1, "manifest.json", sha256(self.first["manifest.json"])),
                          (2, "manifest-2.json", sha256(after["manifest-2.json"]))])
        first, second = load_context(CASE, self.bundle), load_context(self.SECOND, self.bundle)
        self.assertEqual([(view["provenance"]["run"], view["provenance"]["runs"], view["provenance"]["manifest"],
                           view["provenance"]["acquisition_record"], view["provenance"]["run_cases"])
                          for view in (first, second)],
                         [(1, 2, "manifest.json", "sources/acquisition.json", [CASE]),
                          (2, 2, "manifest-2.json", "sources/acquisition-2.json", [self.SECOND])])
        self.assertEqual(first["provenance"]["manifest_sha256"], sha256(self.first["manifest.json"]))
        self.assertEqual((first["source"]["requested_at"], second["source"]["requested_at"]),
                         ("2026-10-07T22:07:04+00:00", "2026-10-07T22:48:04+00:00"))  # Each run keeps its own times.
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2})

    def test_append_refuses_cases_already_held_or_undeclared_and_unmatched_staging(self):
        self.stage(self.SECOND)
        self.assertIn("does not hold yet", self.refused([CASE]))  # Already in run 1.
        self.assertIn("does not hold yet", self.refused(["no-such-case"]))  # Not declared by the collection.
        self.assertIn("exactly one download", self.refused(["empsit-2025-06-06"]))  # Staged files are for another case.
        self.assertIn("exactly one download", self.refused([self.SECOND, "cpi-2025-06-11"]))  # One case not staged.
        self.assertIn("exactly one download", self.refused(None))  # By default, every declared case still missing.
        with self.assertRaises(ContextRefused):
            append(self.staging, self.bundle, [self.SECOND], " ", sessions=self.CALENDAR)  # No method stated.

    def test_append_refuses_a_bundle_that_does_not_verify(self):
        self.stage(self.SECOND)
        source = self.bundle / "sources" / f"{CASE}.csv"
        source.write_bytes(source.read_bytes().replace(b"1.01", b"1.02", 1))
        self.assertIn("does not verify", self.refused())

    def test_a_bundle_from_before_the_index_is_indexed_as_run_one_with_its_manifest_unchanged(self):
        (self.bundle / "index.json").unlink()
        with self.assertRaises(ContextRefused) as caught:
            load_context(CASE, self.bundle)
        self.assertEqual(caught.exception.status, 503)
        self.stage(self.SECOND)
        self.appended()
        runs = json.loads((self.bundle / "index.json").read_text(encoding="utf-8"))["runs"]
        self.assertEqual(runs[0], {"run": 1, "manifest": "manifest.json",
                                   "manifest_sha256": sha256(self.first["manifest.json"])})
        self.assertEqual((self.bundle / "manifest.json").read_bytes(), self.first["manifest.json"])
        self.assertEqual([load_context(case_id, self.bundle)["provenance"]["run"] for case_id in (CASE, self.SECOND)],
                         [1, 2])

    def test_a_bundle_from_before_the_index_is_verified_before_anything_is_appended(self):
        (self.bundle / "index.json").unlink()
        source = self.bundle / "sources" / f"{CASE}.csv"
        source.write_bytes(source.read_bytes().replace(b"1.01", b"1.02", 1))
        self.stage(self.SECOND)
        self.assertIn("does not verify", self.refused())
        self.assertFalse((self.bundle / "index.json").exists())

    def test_discarded_replies_are_recorded_and_shown_but_never_used(self):
        data = self.stage(self.SECOND)
        refused_reply = {**{key: self.records[self.SECOND][key] for key in (
            "case", "url", "requested_at", "received_at", "response_date")},
            "http_status": 200, "content_type": "text/html", "bytes": 0, "sha256": sha256(b""), "reason": "an empty reply"}
        for broken in ({**refused_reply, "case": CASE}, {**refused_reply, "url": "https://example.org/"},
                       {**refused_reply, "case": [self.SECOND]}, {**refused_reply, "sha256": "not a hash"},
                       {key: value for key, value in refused_reply.items() if key != "reason"}, "an empty reply"):
            self.write_record(discarded=[broken])
            self.refused()
        self.write_record(discarded=[refused_reply])
        self.appended()
        provenance = load_context(self.SECOND, self.bundle)["provenance"]
        self.assertEqual(provenance["discarded"], [{"requested_at": refused_reply["requested_at"], "http_status": 200,
                                                    "content_type": "text/html", "bytes": 0, "reason": "an empty reply"}])
        self.assertEqual((self.bundle / f"sources/{self.SECOND}.csv").read_bytes(), data)  # Only the kept reply.
        self.assertEqual(load_context(CASE, self.bundle)["provenance"]["discarded"], [])

    def test_a_run_never_overwrites_an_existing_file(self):
        self.stage(CASE)  # The same case again: its view and source already exist in the bundle.
        with self.assertRaises(ContextRefused) as caught:
            market_context._write_run(self.bundle, 2, self.staging, [CASE], "Synthetic run 2", self.CALENDAR,
                                      {CASE: load_case(CASE)})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual({name: data for name, data in self.files().items() if name in self.first}, self.first)

    def test_append_refuses_if_an_existing_file_changes_while_it_works(self):
        self.stage(self.SECOND)
        write_run = market_context._write_run

        def meddling(work, *args):
            manifest = write_run(work, *args)
            (work / f"{CASE}.json").write_bytes(self.first[f"{CASE}.json"].replace(b'"weekday"', b'"weekday" ', 1))
            return manifest

        with patch.object(market_context, "_write_run", meddling):
            self.refused()  # Refused, and the bundle is exactly as before.

    def test_a_case_listed_by_two_runs_is_refused(self):
        self.stage(self.SECOND)
        self.appended()
        manifest = json.loads((self.bundle / "manifest-2.json").read_text(encoding="utf-8"))
        manifest["contexts"][CASE] = manifest["contexts"][self.SECOND]
        (self.bundle / "manifest-2.json").write_bytes(market_context._json_bytes(manifest))
        index = json.loads((self.bundle / "index.json").read_text(encoding="utf-8"))
        index["runs"][1]["manifest_sha256"] = sha256((self.bundle / "manifest-2.json").read_bytes())
        (self.bundle / "index.json").write_bytes(market_context._json_bytes(index))
        for case_id in (CASE, self.SECOND):
            with self.assertRaises(ContextRefused) as caught:
                load_context(case_id, self.bundle)
            self.assertIn("listed by two acquisition runs", str(caught.exception))

    def test_a_concurrent_append_is_refused_and_can_later_preserve_both_runs(self):
        self.stage(self.SECOND)
        other = Preparation()
        other.setUp()
        self.addCleanup(other.doCleanups)
        third = "fomc-2025-03-19"
        other.stage(third)
        write_run = market_context._write_run
        started = False

        def interleave(work, *args):
            nonlocal started
            manifest = write_run(work, *args)
            if started:
                return manifest
            started = True
            with self.assertRaises(ContextRefused) as caught:
                append(other.staging, self.bundle, [third], "Synthetic concurrent run", sessions=self.CALENDAR)
            self.assertEqual(caught.exception.status, 409)
            with self.assertRaises(ContextRefused) as replacing:
                prepare(other.staging, self.bundle, [third], "Synthetic replacement", sessions=self.CALENDAR,
                        replace=True)
            self.assertEqual(replacing.exception.status, 409)
            return manifest

        with patch.object(market_context, "_write_run", interleave):
            self.appended()
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2})
        append(other.staging, self.bundle, [third], "Synthetic later run", sessions=self.CALENDAR)
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2, third: 3})
        self.assertEqual({name: data for name, data in self.files().items() if name in self.first and name != "index.json"},
                         {name: data for name, data in self.first.items() if name != "index.json"})

    def test_an_append_in_another_process_is_refused_while_the_bundle_is_locked(self):
        self.stage(self.SECOND)
        other = Preparation()
        other.setUp()
        self.addCleanup(other.doCleanups)
        third = "fomc-2025-03-19"
        other.stage(third)
        write_run = market_context._write_run
        child = """import json, sys
from pathlib import Path
from second_order.market_context import append, ContextRefused
try:
    append(Path(sys.argv[1]), Path(sys.argv[2]), [sys.argv[3]], 'Synthetic child run')
except ContextRefused as error:
    print(json.dumps({'status': error.status}))
    sys.exit(42)
"""

        def interleave(work, *args):
            manifest = write_run(work, *args)
            result = subprocess.run([sys.executable, "-B", "-c", child, str(other.staging), str(self.bundle), third],
                                    cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 42, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"status": 409})
            return manifest

        with patch.object(market_context, "_write_run", interleave):
            self.appended()
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2})
        append(other.staging, self.bundle, [third], "Synthetic later run", sessions=self.CALENDAR)
        self.assertEqual(bundle_cases(self.bundle)[third], 3)

    def test_a_live_bundle_change_is_preserved_and_refuses_publication(self):
        self.stage(self.SECOND)
        write_run = market_context._write_run
        name = f"sources/{CASE}.csv"
        changed = self.first[name] + b"\r\n"

        def meddling(work, *args):
            manifest = write_run(work, *args)
            (self.bundle / name).write_bytes(changed)  # An external edit, not a change to the staged copy.
            return manifest

        with patch.object(market_context, "_write_run", meddling), self.assertRaises(ContextRefused) as caught:
            self.appended()
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.files(), {**self.first, name: changed})
        self.assertEqual(list(self.bundle.parent.glob(".market-context-*")), [])

    def test_a_bundle_that_cannot_be_moved_aside_is_unchanged_and_the_refusal_says_so(self):
        self.stage(self.SECOND)
        with self.renames_failing("aside"), self.assertRaises(ContextRefused) as caught:
            self.appended()
        self.assertEqual(caught.exception.status, 500)
        self.assertIn("Publication did not occur: the existing bundle could not be moved aside (PermissionError: "
                      f"Synthetic refusal (aside)). It is unchanged at {self.bundle}", str(caught.exception))
        self.assertEqual((self.files(), self.leftovers(), self.lock_is_free()), (self.first, [], True))

    def test_a_failed_final_rename_restores_the_original_and_says_so(self):
        self.stage(self.SECOND)
        with self.renames_failing("into place"), self.assertRaises(ContextRefused) as caught:
            self.appended()
        self.assertEqual(caught.exception.status, 500)
        self.assertIn("Publication did not occur: the new bundle could not be moved into place (PermissionError: "
                      f"Synthetic refusal (into place)). The original bundle was restored unchanged at {self.bundle}",
                      str(caught.exception))
        self.assertEqual((self.files(), self.leftovers(), self.lock_is_free()), (self.first, [], True))
        self.appended()  # Explicitly trying later works; the failed operation did not leave a held lock.
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2})

    def test_a_published_run_whose_old_copy_cannot_be_removed_succeeds_with_a_warning(self):
        self.stage(self.SECOND)
        remove = shutil.rmtree

        def stubborn(path, *args, **kwargs):
            if Path(path).name.startswith(".market-context-previous-"):
                next(Path(path).rglob("*.csv")).unlink()  # Part of it goes; then the OS refuses the rest.
                raise PermissionError(13, "Synthetic refusal (cleanup)", str(path))
            return remove(path, *args, **kwargs)

        with patch("shutil.rmtree", stubborn):
            result = self.appended()
        leftover = list(self.bundle.parent.glob(".market-context-previous-*"))
        self.assertEqual(len(leftover), 1)
        self.assertEqual({key: value for key, value in result.items() if key != "cleanup_warning"},
                         {"bundle": str(self.bundle), "run": 2, "contexts": [self.SECOND]})
        self.assertEqual(result["cleanup_warning"], (
            "Published, but the replaced bundle could not be fully removed (PermissionError: Synthetic refusal "
            f"(cleanup)). What is left is at {leftover[0]}: an old, possibly partial copy that nothing reads. "
            "Remove it when no process is using it."))
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2})
        for case_id in (CASE, self.SECOND):
            load_context(case_id, self.bundle)
        self.assertEqual({name: data for name, data in self.files().items() if name in self.first and name != "index.json"},
                         {name: data for name, data in self.first.items() if name != "index.json"})
        self.assertTrue(self.lock_is_free())

    def test_the_cli_reports_publication_failures_and_cleanup_warnings_without_a_traceback(self):
        argv = ["prepare", "--staging", str(self.root / "staging"), "--out", str(self.bundle), "--case", CASE,
                "--method", "Synthetic rebuild through the CLI", "--replace"]
        remove = shutil.rmtree

        def stubborn(path, *args, **kwargs):
            if Path(path).name.startswith(".market-context-previous-"):
                raise PermissionError(13, "Synthetic refusal (cleanup)", str(path))
            return remove(path, *args, **kwargs)

        def run(*failing: str, removing=remove) -> tuple[int, str, str]:
            out, err = io.StringIO(), io.StringIO()
            with self.renames_failing(*failing), patch("shutil.rmtree", removing), redirect_stdout(out), \
                    redirect_stderr(err):
                code = market_context.main(argv)
            return code, out.getvalue(), err.getvalue()

        for failing, expected in ((("aside",), "Publication did not occur: the existing bundle could not be moved"),
                                  (("into place",), "The original bundle was restored unchanged")):
            with self.subTest(failing=failing):
                code, out, err = run(*failing)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(expected, json.loads(err)["error"])
                self.assertEqual((self.files(), self.leftovers(), self.lock_is_free()), (self.first, [], True))
        code, out, err = run(removing=stubborn)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["run"], 1)
        self.assertIn("What is left is at", json.loads(err)["warning"])
        self.assertEqual(json.loads(err)["warning"], json.loads(out)["cleanup_warning"])
        self.assertEqual(load_context(CASE, self.bundle)["case_id"], CASE)

    def test_ctrl_c_between_the_renames_is_held_until_the_publication_has_finished(self):
        self.stage(self.SECOND)
        rename, handler = Path.rename, signal.getsignal(signal.SIGINT)

        def interrupted(source, target):
            moved = rename(source, target)
            if Path(source) == self.bundle:  # The original is aside and the new bundle is not yet in place.
                signal.raise_signal(signal.SIGINT)
            return moved

        with patch.object(Path, "rename", interrupted), self.assertRaises(KeyboardInterrupt) as caught:
            self.appended()
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2})
        self.assertIn(f"the new bundle is in place at {self.bundle}", " ".join(getattr(caught.exception, "__notes__", [])))
        self.assertEqual({name: data for name, data in self.files().items() if name in self.first and name != "index.json"},
                         {name: data for name, data in self.first.items() if name != "index.json"})
        self.assertEqual((self.leftovers(), self.lock_is_free()), ([], True))
        self.assertIs(signal.getsignal(signal.SIGINT), handler)

    def test_a_held_ctrl_c_goes_to_the_handler_that_was_there_before(self):
        rename, handler, calls = Path.rename, signal.getsignal(signal.SIGINT), []
        self.addCleanup(signal.signal, signal.SIGINT, handler)

        def interrupted(source, target):
            moved = rename(source, target)
            if Path(source) == self.bundle:
                signal.raise_signal(signal.SIGINT)
            return moved

        for case_id, earlier in ((self.SECOND, signal.SIG_IGN), ("fomc-2025-03-19", lambda *args: calls.append(args[0]))):
            with self.subTest(earlier=earlier):
                self.records, self.staging = {}, self.root / f"staging-{case_id}"
                self.staging.mkdir()
                self.stage(case_id)
                signal.signal(signal.SIGINT, earlier)
                with patch.object(Path, "rename", interrupted):
                    result = self.appended([case_id])  # No KeyboardInterrupt is invented for an ignored signal.
                self.assertEqual(result["contexts"], [case_id])
                self.assertIs(signal.getsignal(signal.SIGINT), earlier)
        self.assertEqual(calls, [signal.SIGINT])  # The custom handler got the held signal once, after publication.
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2, "fomc-2025-03-19": 3})

    def test_publication_outside_the_main_thread_still_works_without_holding_ctrl_c(self):
        self.stage(self.SECOND)
        results = []
        worker = threading.Thread(target=lambda: results.append(self.appended()))
        worker.start()
        worker.join(60)
        self.assertEqual(results, [{"bundle": str(self.bundle), "run": 2, "contexts": [self.SECOND]}])

    def test_a_hard_kill_between_the_renames_leaves_the_original_identified_and_untouched(self):
        self.stage(self.SECOND)
        ready = self.root / "moved-aside"
        child = """import sys, time
from pathlib import Path
from second_order.market_context import append
bundle, ready, rename = Path(sys.argv[2]), Path(sys.argv[3]), Path.rename
def renaming(source, target):
    moved = rename(source, target)
    if Path(source) == bundle:
        ready.write_text("1")
        time.sleep(60)  # Killed here: the original is aside and the new bundle is not yet in place.
    return moved
Path.rename = renaming
append(Path(sys.argv[1]), bundle, [sys.argv[4]], "Synthetic run killed during publication")
"""
        process = subprocess.Popen([sys.executable, "-B", "-c", child, str(self.staging), str(self.bundle), str(ready),
                                    self.SECOND], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 30
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        process.kill()  # Uncatchable: no handler, finally block or cleanup runs.
        _, errors = process.communicate(timeout=15)
        self.assertTrue(ready.exists(), errors.decode(errors="replace"))
        moved = self.asides()
        self.assertEqual(len(moved), 1)
        self.assertRegex(moved[0].name, r"^\.market-context-previous-\d{8}T\d{12}Z-[0-9a-f]{8}-bundle$")  # Its owner.
        self.assertEqual(self.files_of(moved[0]), self.first)
        self.recovery_is_reported(moved[0])

    def test_recovery_never_offers_another_bundles_newer_copy(self):
        """Two bundles with different provenance share a parent: A is left missing, then B leaves a newer copy."""
        other, third = self.root / "market-context-b", "fomc-2025-03-19"
        prepare(self.staging_for("staging-b1", third), other, [third], "Bundle B rows", sessions=self.CALENDAR)
        b_first = self.files_of(other)
        self.staging_for("staging-a2", self.SECOND)
        with recorded_times(T1), self.renames_failing("into place", "restore"), self.assertRaises(ContextRefused):
            self.appended()  # A's original is preserved beside it and A is missing.
        with recorded_times(T2), self.cleanup_refused():
            append(self.staging_for("staging-b2", "cpi-2025-06-11"), other, ["cpi-2025-06-11"], "Bundle B run 2",
                   sessions=self.CALENDAR)  # B is published; its replaced, newer, valid copy is left beside it.
        mine = [path for path in self.asides() if self.files_of(path) == self.first]
        theirs = [path for path in self.asides() if self.files_of(path) == b_first]
        self.assertEqual((len(mine), len(theirs)), (1, 1))
        message = self.recovery_is_reported(mine[0])
        self.assertIn(f"(1) {mine[0]}: moved aside at 2026-10-08T09:15:00.123456Z; its runs: 1 ({CASE}; method: "
                      "Synthetic test rows); its files verify (1 case in 1 acquisition run). The most recent", message)
        self.assertNotIn(str(theirs[0]), message)
        self.assertNotIn("Bundle B", message)
        self.assertIn("Moved-aside folders recorded as other bundles' (market-context-b) are unrelated and not listed.",
                      message)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(market_context, "BUNDLE_DIR", self.bundle), redirect_stdout(out), redirect_stderr(err):
            code = market_context.main(["check"])
        self.assertEqual((code, out.getvalue(), json.loads(err.getvalue())), (1, "", {"error": message}))

    def test_prefix_overlapping_bundle_names_never_share_copies(self):
        near, far = self.root / "market-context", self.root / "market-context-b"
        prepare(self.staging_for("staging-near", CASE), near, [CASE], "Near rows", sessions=self.CALENDAR)
        prepare(self.staging_for("staging-far", "fomc-2025-03-19"), far, ["fomc-2025-03-19"], "Far rows",
                sessions=self.CALENDAR)
        originals = {near: self.files_of(near), far: self.files_of(far)}
        for target, moment, case_id in ((near, T1, self.SECOND), (far, T2, "cpi-2025-06-11")):
            self.staging_for(f"staging-{target.name}-2", case_id)
            with recorded_times(moment), self.renames_failing("into place", "restore", bundle=target), \
                    self.assertRaises(ContextRefused):
                append(self.staging, target, [case_id], "Synthetic run 2", sessions=self.CALENDAR)
        self.assertEqual(sorted(path.name.rsplit("Z-", 1)[1][9:] for path in self.asides()),
                         ["market-context", "market-context-b"])  # Each name records its exact owner.
        for target, moment, unrelated in ((near, "2026-10-08T09:15:00.123456Z", "market-context-b"),
                                          (far, "2026-10-08T09:16:00.654321Z", "market-context")):
            with self.subTest(target=target.name), self.assertRaises(ContextRefused) as caught:
                append(self.staging, target, ["cpi-2025-06-11"], "Retry", sessions=self.CALENDAR)
            message, own = str(caught.exception), next(p for p in self.asides() if self.files_of(p) == originals[target])
            self.assertEqual(caught.exception.status, 409)
            self.assertIn(f"Copies recorded as moved aside from {target.name} are beside it", message)
            self.assertIn(f"Newest recorded time first: (1) {own}: moved aside at {moment}; its runs: 1 (", message)
            self.assertIn(f"The most recent recorded copy is {own}. To restore it, make sure nothing is at {target}, then "
                          f"rename it to {target}.", message)
            self.assertNotIn("(2)", message)
            self.assertIn(f"Moved-aside folders recorded as other bundles' ({unrelated}) are unrelated and not listed.",
                          message)

    def test_the_newest_owned_copy_is_named_even_when_it_does_not_verify(self):
        self.stage(self.SECOND)
        with recorded_times(T1), self.cleanup_refused():
            self.appended()  # Run 2 is published; the replaced one-run copy, which verifies, is left beside it.
        [older] = self.asides()
        source = self.bundle / "sources" / f"{CASE}.csv"
        source.write_bytes(source.read_bytes() + b"\r\n")  # The live two-run bundle no longer verifies.
        two_runs = self.files()
        with recorded_times(T2), self.renames_failing("into place", "restore"), self.assertRaises(ContextRefused):
            prepare(self.root / "staging", self.bundle, (CASE,), "Synthetic replacement", sessions=self.CALENDAR,
                    replace=True)
        [newest] = [path for path in self.asides() if path != older]
        self.assertEqual(self.files_of(newest), two_runs)
        with self.assertRaises(ContextRefused) as caught:
            self.appended()
        message = str(caught.exception)
        self.assertEqual(caught.exception.status, 409)
        self.assertIn(f"(1) {newest}: moved aside at 2026-10-08T09:16:00.654321Z; its runs: 1 ({CASE}; method: "
                      f"Synthetic test rows), 2 ({self.SECOND}; method: Synthetic run 2); its files do not verify: ", message)
        self.assertIn(f"(2) {older}: moved aside at 2026-10-08T09:15:00.123456Z; its runs: 1 ({CASE}; method: Synthetic "
                      "test rows); its files verify (1 case in 1 acquisition run).", message)
        self.assertIn(f"The most recent recorded copy is {newest}, but its files do not verify: it is not safe to "
                      "restore as it is; inspect it before deciding. Older recorded copies are earlier states, not "
                      "replacements: restoring one would drop what was published after it.", message)
        self.assertNotIn("rename it to", message)  # No copy, and certainly not the older one, is offered instead.

    def test_unrelated_leftovers_never_block_or_precede_a_new_destination(self):
        self.stage(self.SECOND)
        with recorded_times(T1), self.cleanup_refused():
            self.appended()  # A copy recorded as this bundle's is left beside it.
        [leftover] = self.asides()
        kept = self.files_of(leftover)
        fresh, missing = self.root / "market-contxt", self.root / "absent"
        self.assertEqual(prepare(self.root / "staging", fresh, (CASE,), "Synthetic new bundle", sessions=self.CALENDAR),
                         {"bundle": str(fresh), "run": 1, "contexts": [CASE]})
        with self.assertRaises(ContextRefused) as appending:
            append(self.staging, missing, [self.SECOND], "Synthetic run", sessions=self.CALENDAR)
        self.assertEqual((appending.exception.status, str(appending.exception)),
                         (422, f"{missing} holds no bundle to append to; use prepare"))
        with self.assertRaises(ContextRefused) as reading:
            load_context(CASE, missing)
        self.assertEqual(str(reading.exception), NOT_PREPARED)
        self.assertEqual((self.asides(), self.files_of(leftover)), ([leftover], kept))

    def test_folders_whose_names_record_no_owner_stay_unattributed(self):
        stamped = self.root / ".market-context-previous-20261008T091500Z-abc12345"  # An earlier version's names.
        untimed = self.root / ".market-context-previous-k3j4h5g6"
        shutil.copytree(self.bundle, stamped)
        self.bundle.rename(untimed)
        legacy = {path: self.files_of(path) for path in (stamped, untimed)}
        self.stage(self.SECOND)
        runs = f"its runs: 1 ({CASE}; method: Synthetic test rows); its files verify (1 case in 1 acquisition run)"
        with self.assertRaises(ContextRefused) as appending:
            self.appended()
        self.assertEqual((appending.exception.status, str(appending.exception)), (422, (
            f"{self.bundle} holds no bundle to append to; use prepare. No bundle is at {self.bundle}. Nothing has been "
            "restored, moved or deleted, and no folder is chosen for you. No moved-aside copy is recorded as bundle's. "
            "Folders whose names record no owner (made by an earlier version) are beside it too; which bundle each came "
            f"from is not known, so none is presented as bundle's: {stamped} (moved aside at 2026-10-08T09:15:00Z; "
            f"{runs}); {untimed} (no recorded time; {runs}). Folders named .market-context-<letters> are unfinished "
            "working copies, not originals.")))
        with self.assertRaises(ContextRefused) as reading:
            load_context(CASE, self.bundle)
        self.assertEqual(str(reading.exception), NOT_PREPARED)
        self.assertEqual(prepare(self.root / "staging", self.bundle, (CASE,), "Synthetic rebuild",
                                 sessions=self.CALENDAR)["run"], 1)  # Not blocked by folders of unknown owner...
        self.assertEqual({path: self.files_of(path) for path in (stamped, untimed)}, legacy)  # ...which stay as they were.

    def test_copies_with_the_same_recorded_time_are_not_ordered(self):
        self.stage(self.SECOND)
        with recorded_times(T1), self.cleanup_refused():
            self.appended()  # Leaves the one-run copy.
        self.staging_for("staging-third", "fomc-2025-03-19")
        with recorded_times(T1), self.cleanup_refused():
            self.appended(["fomc-2025-03-19"])  # Leaves the two-run copy, recorded at the very same time.
        tied = self.asides()
        self.assertEqual(len(tied), 2)
        (tied[0] / "index.json").write_bytes(b"{}")  # One of them no longer verifies: that must not break the tie.
        self.bundle.rename(self.root / "set-aside-by-hand")
        with self.assertRaises(ContextRefused) as caught:
            self.appended()
        message = str(caught.exception)
        self.assertEqual(caught.exception.status, 409)
        for path in tied:
            self.assertIn(f"{path}: moved aside at 2026-10-08T09:15:00.123456Z (the same recorded time as another copy); "
                          "its ", message)
        self.assertIn("2 copies share the most recent recorded time, so which is newest is not known and none is named "
                      "as the most recent; compare their runs before deciding.", message)
        for claim in ("The most recent recorded copy is", "rename it to", "Older recorded copies"):
            self.assertNotIn(claim, message)

    def test_recovery_reads_change_nothing_take_no_lock_and_name_no_folder(self):
        self.stage(self.SECOND)
        with recorded_times(T1), self.renames_failing("into place", "restore"), self.assertRaises(ContextRefused):
            self.appended()  # The bundle is missing; its copy is recorded as its own.
        before, taken, locking = self.snapshot(), [], market_context.bundle_write_lock
        blocked = AssertionError("a read tried to open a network connection")
        with patch.object(market_context, "bundle_write_lock", lambda *args: taken.append(args) or locking(*args)):
            for context, expected in ((self.bundle, VIEWER_INTERRUPTED), (self.root / "never-prepared", NOT_PREPARED)):
                with TestClient(create_app(self.root / "prepared", None, context=context),
                                base_url="http://127.0.0.1:8000") as client, \
                        patch("socket.create_connection", side_effect=blocked), \
                        patch("socket.getaddrinfo", side_effect=blocked):
                    served = client.get(f"/api/case-library/{CASE}/market-context")
                    self.assertEqual(client.get(f"/api/case-library/{CASE}").status_code, 200)
                self.assertEqual((served.status_code, served.json()), (503, {"detail": expected}))
                self.assertNotIn(str(self.root), served.text)
                self.assertNotIn("previous-", served.text)
        self.assertEqual((taken, self.snapshot()), ([], before))

    def test_a_refused_append_to_a_missing_bundle_creates_nothing(self):
        self.stage(self.SECOND)
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        for missing in (self.root / "typo" / "deeper" / "market-context", self.root / "absent"):
            with self.subTest(missing=missing), self.assertRaises(ContextRefused) as caught:
                append(self.staging, missing, [self.SECOND], "Synthetic run", sessions=self.CALENDAR)
            self.assertEqual(caught.exception.status, 422)
            self.assertIn("holds no bundle to append to; use prepare", str(caught.exception))
        self.assertEqual(sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*")), before)

    def test_a_writer_that_exits_without_cleanup_does_not_leave_a_stale_lock(self):
        self.stage(self.SECOND)
        child = """import os, sys
from pathlib import Path
from second_order.context_lock import bundle_write_lock
with bundle_write_lock(Path(sys.argv[1])):
    os._exit(0)
"""
        result = subprocess.run([sys.executable, "-B", "-c", child, str(self.bundle)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.appended()
        self.assertEqual(bundle_cases(self.bundle), {CASE: 1, self.SECOND: 2})

    def test_if_restoration_is_also_blocked_the_original_is_kept_named_and_reported(self):
        self.stage(self.SECOND)
        with self.renames_failing("into place", "restore"), self.assertRaises(ContextRefused) as caught:
            self.appended()
        self.assertEqual(caught.exception.status, 500)
        backups = list(self.bundle.parent.glob(".market-context-previous-*"))
        self.assertEqual(len(backups), 1)
        self.assertIn(f"The original bundle is preserved, unchanged, at {backups[0]}; nothing there was deleted. To "
                      f"restore it, make sure nothing is at {self.bundle}, then rename that folder to {self.bundle}",
                      str(caught.exception))
        self.assertEqual(self.files_of(backups[0]), self.first)
        self.assertTrue(self.lock_is_free())
        self.recovery_is_reported(backups[0])


class ApiTests(Preparation):
    def test_context_is_served_read_only_without_contacting_anyone(self):
        self.stage(CASE)
        self.prepared()
        before = {path: path.read_bytes() for path in self.bundle.rglob("*") if path.is_file()}
        client = TestClient(create_app(self.root / "prepared", None, context=self.bundle), base_url="http://127.0.0.1:8000")
        self.addCleanup(client.close)
        blocked = AssertionError("a read tried to open a network connection")
        with patch("socket.create_connection", side_effect=blocked), patch("socket.getaddrinfo", side_effect=blocked):
            ready = client.get(f"/api/case-library/{CASE}/market-context")
            self.assertEqual(ready.status_code, 200, ready.text)
            self.assertEqual(ready.json(), load_context(CASE, self.bundle))
            self.assertEqual(client.get("/api/case-library/cpi-2025-04-10/market-context").status_code, 404)
            self.assertEqual(client.get("/api/case-library/cpi-2025-07-15/market-context").status_code, 404)
            self.assertEqual(client.post(f"/api/case-library/{CASE}/market-context").status_code, 405)
            case = client.get(f"/api/case-library/{CASE}")
            self.assertEqual((case.status_code, case.json()["market_context"]), (200, True))
            source = self.bundle / "sources" / f"{CASE}.csv"
            original = source.read_bytes()
            source.write_bytes(original + b"\r\n")
            broken = client.get(f"/api/case-library/{CASE}/market-context")
            self.assertEqual(broken.status_code, 500)
            self.assertIn("no context is shown", broken.json()["detail"])
            self.assertEqual(client.get(f"/api/case-library/{CASE}").status_code, 200)  # The case still reads.
            source.write_bytes(original)
        self.assertEqual({path: path.read_bytes() for path in self.bundle.rglob("*") if path.is_file()}, before)
        missing = TestClient(create_app(self.root / "prepared", None, context=self.root / "absent"),
                             base_url="http://127.0.0.1:8000")
        self.addCleanup(missing.close)
        self.assertEqual(missing.get(f"/api/case-library/{CASE}/market-context").status_code, 503)
        self.assertEqual(missing.get(f"/api/case-library/{CASE}").status_code, 200)  # The case itself is unaffected.


class IsolationTests(unittest.TestCase):
    def test_context_depends_on_no_store_scoring_or_network_module(self):
        tree = ast.parse((ROOT / "second_order" / "market_context.py").read_text(encoding="utf-8"))
        absolute = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        absolute |= {node.module.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module}
        relative = {node.module or alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.level > 0 for alias in node.names}
        self.assertLessEqual(absolute, {"argparse", "csv", "datetime", "email", "hashlib", "io", "json", "pathlib",
                                        "re", "shutil", "sys", "tempfile", "zoneinfo"})
        self.assertLessEqual(relative, {"case_library", "market_calendar", "context_lock", "context_publish"})
        for name, allowed in (("context_lock", {"contextlib", "os", "pathlib", "msvcrt", "fcntl"}),
                              ("context_publish", {"contextlib", "datetime", "pathlib", "re", "secrets", "shutil",
                                                   "signal", "tempfile"})):
            helper = ast.parse((ROOT / "second_order" / f"{name}.py").read_text(encoding="utf-8"))
            imports = {alias.name.split(".")[0] for node in ast.walk(helper) if isinstance(node, ast.Import)
                       for alias in node.names}
            imports |= {node.module.split(".")[0] for node in ast.walk(helper) if isinstance(node, ast.ImportFrom)
                        and node.module}
            self.assertLessEqual(imports, allowed, name)

    def test_interrupted_publication_folders_are_ignored_by_git_and_curated_content_is_not(self):
        rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("content/.market-context-*/", rules)  # Working copies and moved-aside originals.
        self.assertIn("content/.market-context.lock", rules)
        self.assertFalse({"content", "content/", "content/*", "content/**", "content/market-context/"} & set(rules))
        with tempfile.TemporaryDirectory() as folder:  # A name publication makes now is still one the rule covers.
            for owner in ("market-context", "market-context-b"):
                name = context_publish._aside_name(Path(folder) / owner).name
                self.assertTrue(name.startswith(".market-context-") and name.endswith(f"-{owner}"), name)
                self.assertEqual((context_publish.OWNED.fullmatch(name).group(8), Path(folder, name).exists()),
                                 (owner, False))

    def test_research_scoreboards_are_unchanged(self):
        before = run_demo()["research_scoreboards"]
        for case_id in CONTEXT_CASES:
            load_context(case_id)
        self.assertEqual(run_demo()["research_scoreboards"], before)

    def test_the_bundle_is_kept_byte_for_byte_by_git(self):
        # Hashes bind the exact bytes (CRLF sources, LF views), so line-ending conversion must never touch them.
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn("/content/market-context/** -text", rules)


def raw_rows(data: bytes) -> dict[str, dict[date, str]]:
    """A deliberately separate minimal reader for the cross-check: column IDs from the sixth row, then date rows."""
    rows = list(csv.reader(io.StringIO(data.decode("ascii"), newline="")))
    columns = rows[5][1:]
    table = {column: {} for column in columns}
    for row in rows[6:]:
        for column, raw in zip(columns, row[1:]):
            table[column][date.fromisoformat(row[0])] = raw
    return table


class CommittedBundleTests(unittest.TestCase):
    """The committed bundle of real H.15 downloads, in two acquisition runs: every served value is its raw source row,
    nothing else is; the first run is exactly as first prepared; the runs stay separate; overlapping windows agree."""

    HOLIDAYS = {  # Weekdays the SIFMA calendar closes, per window; the Board's file marks each ND.
        "fomc-2025-01-29": ["2025-01-20"], "fomc-2025-03-19": [], "empsit-2025-04-04": ["2025-04-18"],
        "cpi-2025-04-10": ["2025-04-18"], "empsit-2025-05-02": ["2025-04-18"], "fomc-2025-05-07": [],
        "cpi-2025-05-13": ["2025-05-26"], "empsit-2025-06-06": ["2025-05-26", "2025-06-19"],
        "cpi-2025-06-11": ["2025-06-19"], "fomc-2025-06-18": ["2025-06-19"],
        "empsit-2025-07-03": ["2025-06-19", "2025-07-04"], "cpi-2025-07-15": ["2025-07-04"]}

    @classmethod
    def setUpClass(cls):
        cls.views = {case_id: load_context(case_id) for case_id in CONTEXT_CASES}
        cls.index = json.loads((BUNDLE_DIR / "index.json").read_text(encoding="utf-8"))
        cls.manifests = {run["run"]: json.loads((BUNDLE_DIR / run["manifest"]).read_text(encoding="utf-8"))
                         for run in cls.index["runs"]}
        cls.records = {number: json.loads((BUNDLE_DIR / manifest["acquisition"]["record"]).read_text(encoding="utf-8"))
                       for number, manifest in cls.manifests.items()}

    def test_every_served_value_is_its_raw_source_row_and_every_row_is_served(self):
        for case_id, view in self.views.items():
            with self.subTest(case_id):
                table = raw_rows((BUNDLE_DIR / view["source"]["file"]).read_bytes())
                self.assertEqual(sorted(table), sorted(SERIES))
                served = {day["date"]: day["observations"] for day in view["days"]}
                for series_id, rows in table.items():
                    self.assertEqual(len(rows), 21)
                    for day, raw in rows.items():  # No source row is dropped or altered.
                        observation = served[day.isoformat()][series_id]
                        self.assertEqual(observation["raw"], raw)
                        self.assertEqual(observation["value"], None if raw == "ND" else float(raw))
                for day in view["days"]:  # No value is shown that the source does not hold.
                    for series_id, observation in day["observations"].items():
                        if observation["value"] is not None:
                            self.assertEqual(float(table[series_id][date.fromisoformat(day["date"])]), observation["value"])
                            self.assertEqual(observation["status"], "session_value")
                        if day["date"] not in {d.isoformat() for d in table[series_id]}:
                            self.assertIsNone(observation["raw"])

    def test_windows_sessions_and_statuses_follow_the_real_calendar(self):
        for case_id, view in self.views.items():
            with self.subTest(case_id):
                day, start, end = event_window(load_case(case_id)["source"]["published_at"])
                self.assertEqual((view["window"]["start"], view["window"]["end"], view["publication"]["new_york_date"]),
                                 (start.isoformat(), end.isoformat(), day.isoformat()))
                self.assertEqual(len(view["days"]), 29)
                sessions = market_context.expected_sessions(start, end)
                stored = json.loads((BUNDLE_DIR / f"{case_id}.json").read_text(encoding="utf-8"))["sessions"]
                self.assertEqual(stored, sorted(d.isoformat() for d in sessions if start <= d <= end))
                for entry in view["days"]:
                    statuses = {o["status"] for o in entry["observations"].values()}
                    raws = {o["raw"] for o in entry["observations"].values()}
                    weekday = date.fromisoformat(entry["date"]).weekday()
                    if weekday >= 5:
                        self.assertEqual((statuses, raws), ({"not_a_session"}, {None}), entry["date"])
                    elif not entry["session"]:  # A SIFMA holiday: the source has the date, marked ND.
                        self.assertEqual((statuses, raws), ({"calendar_holiday"}, {"ND"}), entry["date"])
                    else:  # Every expected session in these windows has both values.
                        self.assertEqual(statuses, {"session_value"}, entry["date"])
        holidays = {case_id: [d["date"] for d in view["days"] if d["weekday"] not in ("Sat", "Sun") and not d["session"]]
                    for case_id, view in self.views.items()}
        self.assertEqual(holidays, self.HOLIDAYS)

    def test_the_first_run_is_byte_for_byte_as_first_prepared(self):
        for name, digest in RUN_1_FILES.items():
            self.assertEqual(sha256((BUNDLE_DIR / name).read_bytes()), digest, name)
        self.assertEqual(self.index["runs"][0], {"run": 1, "manifest": "manifest.json",
                                                 "manifest_sha256": RUN_1_FILES["manifest.json"]})
        for case_id in RUN_1:
            provenance = self.views[case_id]["provenance"]
            self.assertEqual((provenance["run"], provenance["manifest_sha256"], provenance["acquisition_sha256"],
                              provenance["view_sha256"]),
                             (1, RUN_1_FILES["manifest.json"], RUN_1_FILES["sources/acquisition.json"],
                              RUN_1_FILES[f"{case_id}.json"]))

    def test_the_runs_are_separate_and_each_is_complete(self):
        self.assertEqual([(run["run"], run["manifest"]) for run in self.index["runs"]],
                         [(1, "manifest.json"), (2, "manifest-2.json")])
        self.assertEqual(sorted(self.manifests[1]["contexts"]), sorted(RUN_1))
        self.assertEqual(sorted(self.manifests[2]["contexts"]), sorted(set(CONTEXT_CASES) - set(RUN_1)))
        self.assertEqual(bundle_cases(), {case_id: 1 if case_id in RUN_1 else 2 for case_id in CONTEXT_CASES})
        times = {number: [(item["requested_at"], item["received_at"]) for item in record["downloads"]]
                 for number, record in self.records.items()}
        self.assertLess(max(received for _, received in times[1]), min(requested for requested, _ in times[2]))
        for number, manifest in self.manifests.items():
            self.assertEqual(manifest["acquisition"]["record"], market_context.record_name(number))
            self.assertIn("Acquisition run 2" if number == 2 else "Downloaded with curl on 2026-10-07",
                          manifest["acquisition"]["method"])
        for case_id, view in self.views.items():
            provenance = view["provenance"]
            run = 1 if case_id in RUN_1 else 2
            self.assertEqual((provenance["run"], provenance["runs"], provenance["manifest"]),
                             (run, 2, market_context.manifest_name(run)))
            self.assertEqual(view["source"]["requested_at"],
                             next(item["requested_at"] for item in self.records[run]["downloads"] if item["case"] == case_id))
        # Run 1 described its discarded replies in its method text; run 2 records each one.
        self.assertNotIn("discarded", self.records[1])
        discarded = self.records[2]["discarded"]
        self.assertEqual(len(discarded), 6)
        for item in discarded:
            kept = next(entry for entry in self.records[2]["downloads"] if entry["case"] == item["case"])
            self.assertEqual((item["http_status"], item["content_type"], item["bytes"], item["reason"]),
                             (200, "text/html", 0, "an empty reply"))
            self.assertLess(item["received_at"], kept["requested_at"])  # Refused first, then the kept reply.
            self.assertEqual(item["url"], kept["url"])

    def test_the_sources_are_the_boards_downloads_as_recorded(self):
        for number, record in self.records.items():
            for item in record["downloads"]:
                data = (BUNDLE_DIR / "sources" / item["file"]).read_bytes()
                self.assertEqual((item["sha256"], item["bytes"]), (sha256(data), len(data)))
                self.assertTrue(item["url"].startswith("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&"))
                self.assertEqual((item["http_status"], item["content_type"]), (200, "text/csv"))
                header = data.decode("ascii").split("\r\n")[:6]
                self.assertEqual(header[1], '"Unit:","Percent:_Per_Year","Percent:_Per_Year"')
                self.assertEqual(header[4], '"Unique Identifier: ","H15/H15/RIFLGFCY02_N.B","H15/H15/RIFLGFCY10_N.B"')
            acquisition = self.manifests[number]["acquisition"]
            self.assertIsNone(acquisition["vintage"])
            self.assertNotIn("synthetic", acquisition["method"].lower())
            self.assertIn("Data Download Program", acquisition["method"])
            self.assertNotIn("fred.stlouisfed.org", json.dumps(record))
        self.assertEqual(sorted(path.relative_to(BUNDLE_DIR).as_posix() for path in BUNDLE_DIR.rglob("*") if path.is_file()),
                         sorted(["index.json", "manifest.json", "manifest-2.json", "sources/acquisition.json",
                                 "sources/acquisition-2.json"] + [f"{case_id}.json" for case_id in CONTEXT_CASES] +
                                [f"sources/{case_id}.csv" for case_id in CONTEXT_CASES]))

    def test_overlapping_windows_agree_on_every_shared_series_and_date(self):
        tables = {case_id: raw_rows((BUNDLE_DIR / "sources" / f"{case_id}.csv").read_bytes()) for case_id in CONTEXT_CASES}
        shared, across_runs, disagreements = 0, 0, []
        for first in CONTEXT_CASES:
            for second in CONTEXT_CASES:
                if first >= second:
                    continue
                for series_id in SERIES:
                    for day in set(tables[first][series_id]) & set(tables[second][series_id]):
                        shared += 1
                        across_runs += (first in RUN_1) != (second in RUN_1)
                        if tables[first][series_id][day] != tables[second][series_id][day]:
                            disagreements.append((first, second, series_id, day))
        self.assertEqual(disagreements, [])
        self.assertEqual(shared, 340)  # 18 overlapping pairs of windows.
        self.assertGreater(across_runs, 0)  # Run 1 and run 2 overlap too, and agree.

    def test_availability_claims_match_the_validated_content(self):
        library = load_library()
        self.assertEqual(set(library["collection"]["market_context"]), set(bundle_cases()))
        # The twelve macro releases are the case-library-0.1 cases; a 0.3 WTO entry has no sector and no context either.
        self.assertEqual(set(bundle_cases()),
                         {case["id"] for case in library["cases"] if case["library_version"] == "case-library-0.1"})
        self.assertEqual(len(self.views), 12)

    def test_the_frontend_tests_read_exactly_the_views_this_bundle_serves(self):
        for case_id, view in self.views.items():
            name = f"market-context-{case_id}.json"
            if os.environ.get(WRITE_FIXTURES) == "1":
                text = json.dumps(view, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
                (FRONTEND_FIXTURES / name).write_bytes(text.encode("utf-8"))
            committed = json.loads((FRONTEND_FIXTURES / name).read_text(encoding="utf-8"))
            self.assertEqual(view, committed, f"frontend/tests/fixtures/{name} is stale; regenerate it with "
                                              f"{WRITE_FIXTURES}=1 python -m unittest tests.test_market_context")


if __name__ == "__main__":
    unittest.main()
