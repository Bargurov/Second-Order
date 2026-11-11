"""Retained copper-thesis sources (thesis_sources, thesis_workbook).

Mechanics run on SYNTHETIC retained files and acquisition records (tests/thesis_fakes.py) written into temporary
folders: verification against the records, the HTML, CSV and XLSX readers and their limits, the per-SHA-256 memo, and
locating a figure or passage. No real retained source is read here.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import thesis_fakes
from second_order import market_package, thesis_arithmetic, thesis_sources, thesis_workbook

ROOT = Path(__file__).resolve().parent.parent
READ_BYTES = Path.read_bytes


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()} if folder.exists() else {}


def writable_rmtree(path: Path) -> None:
    shutil.rmtree(path, onexc=lambda remove, target, _: (os.chmod(target, stat.S_IWRITE), remove(target)))


def rewritten(raw: bytes, change, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """A workbook's archive written again entry by entry, each entry's bytes passed through ``change(name, data)``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(buffer, "w") as target:
        for info in source.infolist():
            target.writestr(info.filename, change(info.filename, source.read(info)), compress_type=compression)
    return buffer.getvalue()


def figure(source: str, value: str, as_shown: str, locator: dict) -> dict:
    return {"id": "synthetic-figure", "source": source, "measure": "Synthetic measure", "unit": "kt", "value": value,
            "as_shown": as_shown, "year": "2025", "period": None, "basis": None, "scenario": None,
            "locator": locator}


def passage(source: str, locator: dict) -> dict:
    return {"id": "synthetic-passage", "source": source, "locator": locator}


SENSITIVITY = ("Based on projected copper sales volumes for 2026, a change of $0.10 per pound in copper prices would "
               "have an approximate $410 million effect on our annual operating cash flows.")
MINE = "World mine production (kt)"


class Sources(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-thesis-sources-"))
        self.addCleanup(writable_rmtree, self.root)
        self.sources = thesis_fakes.write_sources(self.root / "sources")
        self.entries = {entry["id"]: entry for entry in thesis_fakes.source_entries(self.sources)}
        thesis_sources._MEMO.clear()  # Each test starts as a fresh process would.
        self.addCleanup(thesis_sources._MEMO.clear)

    def verify(self, source_id: str, entry: dict | None = None) -> tuple[dict, bytes | None]:
        return thesis_sources.verify(entry or self.entries[source_id], self.sources)

    def file(self, source_id: str) -> Path:
        entry = self.entries[source_id]
        return self.sources / entry["folder"] / entry["name"]

    def change_record(self, source_id: str, **changes) -> None:
        path = thesis_fakes.record_path(self.sources, source_id)
        record = {**json.loads(path.read_text(encoding="utf-8")), **changes}
        thesis_fakes.write_record(self.sources, source_id, {key: value for key, value in record.items()
                                                            if value is not ...})

    def held(self, source_id: str, sheets=()) -> object:
        state, raw = self.verify(source_id)
        self.assertEqual(state["state"], "verified")
        return thesis_sources.content(self.entries[source_id], raw, sheets=sheets)


# ---------------------------------------------------------------- verification against the acquisition record

class VerifyTests(Sources):
    def test_the_sources_folder_and_vocabularies_are_as_specified(self):
        self.assertEqual(thesis_sources.SOURCES_DIR, ROOT / "data" / "sector-sources" / "copper")
        self.assertEqual(thesis_sources.SOURCES_REL, "data/sector-sources/copper")
        self.assertEqual(thesis_sources.KINDS, ("html", "xlsx", "csv", "pdf"))
        self.assertEqual(thesis_sources.ORIGINS, ("get", "owner_download"))
        self.assertEqual((thesis_sources.MAX_PARAGRAPHS, thesis_sources.MAX_CHARS), (60_000, 8_000_000))
        self.assertEqual((thesis_workbook.MAX_ENTRIES, thesis_workbook.MAX_ENTRY, thesis_workbook.MAX_TOTAL,
                          thesis_workbook.MAX_RATIO), (400, 256 * 1024 * 1024, 1024 * 1024 * 1024, 200))

    def test_every_synthetic_source_verifies(self):
        self.assertEqual(list(self.entries), ["usgs-2026", "usgs-2025", "iea-2026", "iea-2025", "worldbank",
                                              "iea-2021", "sec-producer-2025", "sec-producer-2024", "sec-maker-2025"])
        for source_id, entry in self.entries.items():
            with self.subTest(source=source_id):
                self.assertEqual(tuple(entry), thesis_fakes.SOURCE_FIELDS)
                self.assertEqual(entry["id"], entry["folder"])
                state, raw = self.verify(source_id)
                self.assertEqual(state["state"], "verified", state["detail"])
                self.assertTrue(state["detail"])
                self.assertEqual(raw, self.file(source_id).read_bytes())
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (entry["bytes"], entry["sha256"]))
        self.assertEqual(self.entries["iea-2021"]["transcription"],
                         {"pages": [1, 2], "method": "transcribed from the page image"})
        self.assertEqual([entry["id"] for entry in self.entries.values() if entry["transcription"] is not None],
                         ["iea-2021"])
        owner = {(e["approval_id"], e["attempt"]) for e in self.entries.values() if e["origin"] == "owner_download"}
        self.assertEqual(owner, {("synthetic-copper-owner-01", 1), ("synthetic-copper-owner-01", 2)})
        got = sorted(e["attempt"] for e in self.entries.values() if e["origin"] == "get")
        self.assertEqual(got, list(range(1, 8)))
        self.assertTrue(all(e["approval_id"] == "synthetic-copper-01" for e in self.entries.values()
                            if e["origin"] == "get"))
        for later, earlier in (("usgs-2026", "usgs-2025"), ("iea-2026", "iea-2025"),
                               ("sec-producer-2025", "sec-producer-2024")):
            with self.subTest(series=later):
                self.assertEqual(self.entries[later]["series"], self.entries[earlier]["series"])
                self.assertLess(self.entries[earlier]["edition_date"], self.entries[later]["edition_date"])

    def test_a_missing_record_or_file_is_missing(self):
        cases = {"file": lambda: self.file("usgs-2025").unlink(),
                 "folder": lambda: writable_rmtree(self.sources / "usgs-2025"),
                 "record": lambda: thesis_fakes.record_path(self.sources, "usgs-2025").unlink(),
                 "acquisitions": lambda: writable_rmtree(self.sources / "acquisitions")}
        for case, remove in cases.items():
            with self.subTest(case=case):
                thesis_fakes.write_sources(self.sources)
                remove()
                state, raw = self.verify("usgs-2025")
                self.assertEqual(state["state"], "missing")
                self.assertIsNone(raw)
                self.assertTrue(state["detail"])
        state, raw = thesis_sources.verify(self.entries["usgs-2025"], self.root / "absent")
        self.assertEqual((state["state"], raw), ("missing", None))

    def test_changed_bytes_or_a_disagreeing_record_is_changed(self):
        original = thesis_fakes.source_bytes("sec-producer-2025")
        flipped = original.replace(b"$410", b"$411", 1)
        self.assertEqual(len(flipped), len(original))
        cases = {
            "size": (lambda: self.file("sec-producer-2025").write_bytes(original + b" "), None),
            "sha256 of the file": (lambda: self.file("sec-producer-2025").write_bytes(flipped), None),
            "url": (lambda: self.change_record("sec-producer-2025", url="https://example.org/other"), "url"),
            "retained": (lambda: self.change_record("sec-producer-2025",
                                                    retained="data/sector-sources/copper/other/10k.htm"), "retained"),
            "outcome": (lambda: self.change_record("sec-producer-2025", outcome="failed"), "outcome"),
            "status": (lambda: self.change_record("sec-producer-2025", http_status=500), "http_status"),
            "status as text": (lambda: self.change_record("sec-producer-2025", http_status="200"), "http_status"),
            "approval": (lambda: self.change_record("sec-producer-2025", approval_id="other-01"), "approval_id"),
            "record sha256": (lambda: self.change_record("sec-producer-2025", sha256="0" * 64), "sha256"),
            "record bytes": (lambda: self.change_record("sec-producer-2025", bytes=len(original) + 1), "bytes"),
            "hash kind": (lambda: self.change_record("sec-producer-2025", hash_kind="partial"), "hash_kind"),
            "origin": (lambda: self.change_record("sec-producer-2025", origin="owner_download"), "origin"),
            "not strict JSON": (lambda: thesis_fakes.record_path(self.sources, "sec-producer-2025").write_text(
                '{"outcome": "complete", "outcome": "complete"}', encoding="utf-8"), None),
            "not an object": (lambda: thesis_fakes.record_path(self.sources, "sec-producer-2025").write_text(
                "[]", encoding="utf-8"), None),
        }
        for case, (change, field) in cases.items():
            with self.subTest(case=case):
                thesis_fakes.write_sources(self.sources)
                change()
                with patch.object(Path, "read_bytes", autospec=True, side_effect=READ_BYTES) as read:
                    state, raw = self.verify("sec-producer-2025")
                self.assertEqual(state["state"], "changed")
                self.assertIsNone(raw)
                if field:
                    self.assertIn(field, state["detail"])
                if case == "size":  # A file of the wrong size is refused from its size alone, unread.
                    self.assertEqual(state["detail"], "The retained file's size differs from its acquisition record; "
                                                      "it is not read.")
                    read.assert_not_called()
        thesis_fakes.write_sources(self.sources)
        for field, value in (("sha256", "0" * 64), ("bytes", 1), ("url", "https://example.org/other")):
            with self.subTest(entry=field):  # The thesis entry disagrees with a record and file that agree.
                state, raw = self.verify("sec-producer-2025", {**self.entries["sec-producer-2025"], field: value})
                self.assertEqual((state["state"], raw), ("changed", None))

    def test_an_owner_download_needs_its_own_record_shape(self):
        self.assertEqual(self.verify("iea-2026")[0]["state"], "verified")
        cases = {"http_status": 200, "hash_kind": "complete_response", "origin": ..., "url": "https://example.org/x"}
        for field, value in cases.items():
            with self.subTest(field=field):
                thesis_fakes.write_sources(self.sources)
                self.change_record("iea-2026", **{field: value})
                state, raw = self.verify("iea-2026")
                self.assertEqual((state["state"], raw), ("changed", None))
                self.assertIn(field, state["detail"])
        with self.subTest(case="a GET record for an owner download"):
            thesis_fakes.write_sources(self.sources)
            self.change_record("iea-2026", origin=..., http_status=200, hash_kind="complete_response")
            self.assertEqual(self.verify("iea-2026")[0]["state"], "changed")

    def test_the_attempt_and_the_retrieval_time_are_bound_to_the_record(self):
        later = "2026-11-02T10:00:00+00:00"
        cases = [("sec-producer-2025", {"n": 99}, "n"), ("sec-producer-2025", {"n": "5"}, "n"),
                 ("sec-producer-2025", {"n": ...}, "n"),
                 ("sec-producer-2025", {"body_completed_at": later}, "body_completed_at"),
                 ("sec-producer-2025", {"body_completed_at": ...}, "body_completed_at"),
                 ("iea-2026", {"recorded_at": later}, "recorded_at"), ("iea-2026", {"recorded_at": ...}, "recorded_at"),
                 ("iea-2026", {"n": 2}, "n")]
        for source_id, change, field in cases:
            with self.subTest(source=source_id, change=change):
                thesis_fakes.write_sources(self.sources)
                self.change_record(source_id, **change)
                state, raw = self.verify(source_id)
                self.assertEqual((state["state"], raw), ("changed", None))
                self.assertIn(f"on {field};", state["detail"])
        thesis_fakes.write_sources(self.sources)
        for source_id, field in (("sec-producer-2025", "body_completed_at"), ("iea-2026", "recorded_at")):
            with self.subTest(entry=source_id):  # The thesis entry states another retrieval time than its record.
                state, raw = self.verify(source_id, {**self.entries[source_id], "retrieved_at": later})
                self.assertEqual((state["state"], raw), ("changed", None))
                self.assertIn(f"on {field};", state["detail"])

    def test_an_entry_that_names_no_single_retained_file_is_refused(self):
        for field, value in (("folder", ".."), ("name", "../copper.csv"), ("name", "a\\b"), ("approval_id", ""),
                             ("attempt", 0), ("attempt", True), ("origin", "post")):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.verify("usgs-2025", {**self.entries["usgs-2025"], field: value})


# ---------------------------------------------------------------- the readers

class ReaderTests(unittest.TestCase):
    def test_html_paragraphs_drop_markup_and_hidden_text(self):
        paragraphs = thesis_sources.html_paragraphs(thesis_fakes.producer_html(2025))
        self.assertEqual(paragraphs[:4], [
            "Synthetic Producer Corp.",
            "Annual report on Form 10-K for the fiscal year ended December 31, 2025. Synthetic: every number in this "
            "document is made up.",
            "Synthetic copper sales were 4,120 million pounds in 2025.", SENSITIVITY])
        self.assertEqual(paragraphs[4:], ["Synthetic sensitivity", "Change", "Effect", "Copper", "$0.10 per pound",
                                          "$410 million"])
        self.assertFalse(any("hidden" in text or "margin" in text or "Form 10-K 2025" in text for text in paragraphs))

    def test_html_beyond_the_limits_is_unreadable_not_cut(self):
        raw = ("<p>Synthetic</p>" * 60_001).encode()
        with self.assertRaises(thesis_sources.Unreadable):
            thesis_sources.html_paragraphs(raw)
        whole = thesis_sources.html_paragraphs(("<p>Synthetic</p>" * 60_000).encode())
        self.assertEqual(len(whole), 60_000)  # At the limit everything is read; nothing is cut.
        over = f"<p>{'S' * 4_000_000}</p><p>{'y' * 4_000_001}</p>".encode()
        with self.assertRaises(thesis_sources.Unreadable):
            thesis_sources.html_paragraphs(over)
        exact = thesis_sources.html_paragraphs(f"<p>{'S' * 4_000_000}</p><p>{'y' * 4_000_000}</p>".encode())
        self.assertEqual([len(text) for text in exact], [4_000_000, 4_000_000])

    def test_html_that_is_not_utf8_or_not_readable_markup_is_unreadable(self):
        for raw in ("<p>Synthetic café</p>".encode("latin-1"), b"<p>Synthetic</p><![bogus[x]]>"):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(thesis_sources.Unreadable):
                    thesis_sources.html_paragraphs(raw)
        self.assertEqual(thesis_sources.html_paragraphs("﻿<p>Synthetic</p>".encode()), ["Synthetic"])

    def test_csv_rows_are_strict_utf8_and_allow_a_byte_order_mark(self):
        raw = thesis_fakes.usgs_csv(2026)
        rows = thesis_sources.csv_rows(raw)
        self.assertEqual(rows[0], list(thesis_fakes.USGS_COLUMNS))
        self.assertEqual(rows[5], ["Synthetic USGS Mineral Commodity Summaries 2026", "Copper", "2025", "23,300",
                                   "28,000"])
        self.assertEqual(len(rows), 6)
        self.assertEqual(thesis_sources.csv_rows(b"\xef\xbb\xbf" + raw), rows)
        for bad in ("Synthetic,café\r\n".encode("latin-1"), b'Synthetic,"unclosed\r\n', b'Synthetic,"a"b\r\n'):
            with self.subTest(bad=bad):
                with self.assertRaises(thesis_sources.Unreadable):
                    thesis_sources.csv_rows(bad)


class WorkbookTests(unittest.TestCase):
    def test_cells_resolve_shared_and_inline_strings_and_keep_numbers_as_stored(self):
        cells = {"A1": "Synthetic label", "B1": "9342.5", "C1": "-0.25", "A2": "2026M10", "AA2": "26,500"}
        for inline in (False, True):
            with self.subTest(inline=inline):
                raw = thesis_fakes.workbook({"Other": {"A1": "Synthetic"}, "Data": cells}, inline=inline)
                self.assertEqual(thesis_workbook.sheet_cells(raw, "Data"), cells)
                self.assertEqual(thesis_workbook.sheet_cells(raw, "Other"), {"A1": "Synthetic"})

    def test_number_cells_are_marked_and_text_cells_are_not(self):
        raw = rewritten(thesis_fakes.workbook({"Data": {"A1": "Synthetic", "B1": "9500", "C1": "1.2E-3",
                                                        "D1": "1.5", "E1": "7"}}),
                        lambda name, data: data.replace(b'<c r="D1"><v>1.5</v></c>',
                                                        b'<c r="D1" t="str"><f>B1</f><v>1.5</v></c>').replace(
                                                            b'<c r="E1"><v>7</v></c>',
                                                            b'<c r="E1" t="inlineStr"><is><t>7</t></is></c>'))
        cells = thesis_workbook.sheet_cells(raw, "Data")
        self.assertEqual(cells, {"A1": "Synthetic", "B1": "9500", "C1": "1.2E-3", "D1": "1.5", "E1": "7"})
        self.assertEqual({reference for reference, text in cells.items() if isinstance(text, thesis_workbook.Number)},
                         {"B1", "C1"})
        self.assertTrue(all(isinstance(text, str) for text in cells.values()))  # Still {cell: text}.

    def test_a_workbook_with_many_sheets_is_read(self):
        raw = thesis_fakes.workbook({f"S{n}": {"A1": "Synthetic"} for n in range(60)})  # more than 50 entries
        self.assertEqual(thesis_workbook.sheet_cells(raw, "S59"), {"A1": "Synthetic"})

    def test_more_entries_than_the_limit_are_refused(self):
        at_limit = thesis_fakes.workbook({f"S{n}": {"A1": "Synthetic"} for n in range(395)})
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(at_limit)).infolist()), 400)
        self.assertEqual(thesis_workbook.sheet_cells(at_limit, "S394"), {"A1": "Synthetic"})
        over = thesis_fakes.workbook({f"S{n}": {"A1": "Synthetic"} for n in range(396)})
        with self.assertRaises(thesis_workbook.WorkbookRefused):
            thesis_workbook.sheet_cells(over, "S0")

    def test_a_workbook_with_a_doctype_is_refused(self):
        raw = thesis_fakes.workbook({"Copper": {"A1": "Synthetic"}}, doctype=True)
        with self.assertRaises(thesis_workbook.WorkbookRefused) as refused:
            thesis_workbook.sheet_cells(raw, "Copper")
        self.assertEqual(str(refused.exception),
                         "xl/sharedStrings.xml has a DOCTYPE declaration, which the parser policy refuses")

    def test_an_entry_that_expands_too_far_is_refused(self):
        # The expanding entry is a sheet nobody asks for: only the read-through of every entry can refuse it, and this
        # module's own limit holds even where market_package's would allow more.
        raw = thesis_fakes.workbook({"Copper": {"A1": "Synthetic"}, "Notes": {"A1": "1" * 3_000_000}})
        for package_ratio in (market_package.MAX_RATIO, 10 ** 9):
            with self.subTest(market_package_ratio=package_ratio), \
                    patch.object(market_package, "MAX_RATIO", package_ratio):
                with self.assertRaisesRegex(thesis_workbook.WorkbookRefused, "expands more than 200:1"):
                    thesis_workbook.sheet_cells(raw, "Copper")

    def test_size_limits_are_this_modules_own_and_read_at_call_time(self):
        raw = thesis_fakes.workbook({"Copper": {"A1": "Synthetic"}})
        largest = max(info.file_size for info in zipfile.ZipFile(io.BytesIO(raw)).infolist())
        total = sum(info.file_size for info in zipfile.ZipFile(io.BytesIO(raw)).infolist())
        for limit, value, message in (("MAX_ENTRY", largest - 1, "declares"), ("MAX_TOTAL", total - 1, "in all")):
            with self.subTest(limit=limit), patch.object(thesis_workbook, limit, value):
                with self.assertRaisesRegex(thesis_workbook.WorkbookRefused, message):
                    thesis_workbook.sheet_cells(raw, "Copper")
        for limit, value in (("MAX_ENTRY", largest), ("MAX_TOTAL", total)):
            with self.subTest(at_limit=limit), patch.object(thesis_workbook, limit, value):
                self.assertEqual(thesis_workbook.sheet_cells(raw, "Copper"), {"A1": "Synthetic"})

    def test_unsafe_entries_are_refused(self):
        raw = thesis_fakes.workbook({"Copper": {"A1": "Synthetic"}})

        def extra(info: zipfile.ZipInfo, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
            buffer = io.BytesIO(raw)
            with warnings.catch_warnings(), zipfile.ZipFile(buffer, "a") as archive:
                warnings.simplefilter("ignore", UserWarning)  # zipfile warns of the repeated name it is asked for.
                archive.writestr(info, b"Synthetic", compress_type=compression)
            return buffer.getvalue()

        def encrypted() -> bytes:  # writestr clears the flag, so it is set in the central directory afterwards.
            data = bytearray(extra(zipfile.ZipInfo("xl/locked.xml")))
            header = data.rfind(b"PK\x01\x02", 0, data.rfind(b"xl/locked.xml"))
            data[header + 8] |= 0x1
            self.assertTrue(zipfile.ZipFile(io.BytesIO(bytes(data))).getinfo("xl/locked.xml").flag_bits & 0x1)
            return bytes(data)
        link = zipfile.ZipInfo("xl/link.xml")
        link.external_attr = 0o120777 << 16
        cases = {"unsafe entry path": extra(zipfile.ZipInfo("../outside.xml")),
                 "unsafe entry path '/": extra(zipfile.ZipInfo("/root.xml")),
                 "symbolic link": extra(link), "Workbook entry 'xl/locked.xml' is encrypted": encrypted(),
                 "unsupported compression": extra(zipfile.ZipInfo("xl/other.xml"), zipfile.ZIP_BZIP2),
                 "same name": extra(zipfile.ZipInfo("xl/workbook.xml"))}
        for message, data in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(thesis_workbook.WorkbookRefused, re.escape(message)):
                    thesis_workbook.sheet_cells(data, "Copper")

    def test_package_absolute_relationship_targets_name_the_same_parts(self):
        raw = thesis_fakes.workbook({"Other": {"A1": "Synthetic"}, "Copper": {"A1": "Synthetic copper", "B1": "9500"}})
        absolute = rewritten(raw, lambda name, data: data.replace(b'Target="xl/', b'Target="/xl/').replace(
            b'Target="worksheets/', b'Target="/xl/worksheets/').replace(b'Target="sharedStrings', b'Target="/xl/'
                                                                                          b'sharedStrings'))
        self.assertNotEqual(absolute, raw)
        self.assertEqual(thesis_workbook.sheet_cells(absolute, "Copper"), {"A1": "Synthetic copper", "B1": "9500"})

    def test_a_missing_sheet_or_a_broken_archive_is_refused(self):
        raw = thesis_fakes.workbook({"Copper": {"A1": "Synthetic"}, "Notes": {"A1": "777"}})
        stored = rewritten(raw, lambda name, data: data, zipfile.ZIP_STORED)
        # The CRC of the Notes sheet, which is never parsed, no longer matches: the read-through refuses it.
        corrupted = stored.replace(b"<v>777</v>", b"<v>778</v>")
        self.assertNotEqual(corrupted, stored)
        self.assertEqual(thesis_workbook.sheet_cells(stored, "Copper"), {"A1": "Synthetic"})
        for case, data, sheet in (("absent sheet", raw, "Absent"), ("not an archive", b"Synthetic", "Copper"),
                                  ("CRC", corrupted, "Copper")):
            with self.subTest(case=case):
                with self.assertRaises(thesis_workbook.WorkbookRefused):
                    thesis_workbook.sheet_cells(data, sheet)


# ---------------------------------------------------------------- content, memoized per SHA-256

class ContentTests(Sources):
    def test_content_is_memoized_per_sha256_and_never_written(self):
        before = tree(self.sources)
        sheets = {"iea-2026": ("Copper",), "iea-2025": ("Copper",), "worldbank": ("Monthly Prices",)}
        with patch("socket.socket", side_effect=AssertionError("a read opened a socket")):
            first = {source_id: self.held(source_id, sheets.get(source_id, ())) for source_id in self.entries}
            with patch.object(thesis_sources, "html_paragraphs", side_effect=AssertionError("re-read")), \
                    patch.object(thesis_sources, "csv_rows", side_effect=AssertionError("re-read")), \
                    patch.object(thesis_workbook, "read_sheets", side_effect=AssertionError("re-read")):
                again = {source_id: self.held(source_id, sheets.get(source_id, ())) for source_id in self.entries}
        for source_id, held in first.items():
            with self.subTest(source=source_id):
                kind = self.entries[source_id]["kind"]
                if kind == "pdf":
                    self.assertIsNone(held)
                elif kind == "xlsx":
                    self.assertEqual(list(held), list(sheets[source_id]))
                    self.assertIs(again[source_id][sheets[source_id][0]], held[sheets[source_id][0]])
                else:
                    self.assertIs(again[source_id], held)
        self.assertEqual(tree(self.sources), before)
        entry = self.entries["sec-producer-2025"]
        raw = self.file("sec-producer-2025").read_bytes()
        newer = thesis_sources.content(entry, raw + b"<p>Synthetic addition</p>")
        self.assertEqual(newer[-1], "Synthetic addition")
        self.assertIsNot(thesis_sources.content(entry, raw), first["sec-producer-2025"])  # The old SHA-256 was dropped.
        self.assertEqual(thesis_sources.content(entry, raw), first["sec-producer-2025"])
        self.assertEqual(tree(self.sources), before)

    def test_a_workbook_reads_only_the_sheets_figures_name(self):
        held = self.held("iea-2026", ("Copper",))
        self.assertEqual(list(held), ["Copper"])
        self.assertEqual(held["Copper"]["D5"], "26500")
        self.assertEqual(self.held("iea-2026", ("Copper", "Absent")), {"Copper": held["Copper"]})
        self.assertEqual(self.held("iea-2026", ("Notes",)),
                         {"Notes": {"A1": "Synthetic: every number in this workbook is made up."}})
        self.assertEqual(self.held("iea-2026"), {})

    def test_a_refusal_never_depends_on_the_order_of_reads(self):
        entry = self.entries["iea-2026"]
        both = rewritten(thesis_fakes.workbook({"Good": {"A1": "Synthetic"}, "Bad": {"A1": "Synthetic"}}),
                         lambda name, data: data.replace(b'<row r="1">', b'<row r="x">')
                         if name == "xl/worksheets/sheet2.xml" else data)  # Only the Bad sheet's own part fails.
        with self.assertRaises(thesis_workbook.WorkbookRefused):
            thesis_workbook.sheet_cells(both, "Bad")
        for order in (("Bad", "Good"), ("Good", "Bad")):
            with self.subTest(order=order):
                thesis_sources._MEMO.clear()
                for sheet in order:
                    if sheet == "Bad":
                        with self.assertRaisesRegex(thesis_sources.Unreadable, "Sheet “Bad” cannot be read"):
                            thesis_sources.content(entry, both, sheets=("Bad",))
                    else:
                        self.assertEqual(thesis_sources.content(entry, both, sheets=("Good",)),
                                         {"Good": {"A1": "Synthetic"}})
                with self.assertRaises(thesis_sources.Unreadable):
                    thesis_sources.content(entry, both, sheets=("Good", "Bad"))
                self.assertEqual(thesis_sources.content(entry, both), {})
        # An archive-wide refusal holds for every request, whatever was asked first.
        doctype = thesis_fakes.workbook({"Copper": {"A1": "Synthetic"}}, doctype=True)
        for order in (((), ("Absent",), ("Copper",)), (("Copper",), ("Absent",), ())):
            with self.subTest(order=order):
                thesis_sources._MEMO.clear()
                for sheets in order:
                    with self.assertRaisesRegex(thesis_sources.Unreadable, "DOCTYPE"):
                        thesis_sources.content(entry, doctype, sheets=sheets)

    def test_an_unreadable_source_is_refused_whole(self):
        entry = self.entries["sec-producer-2025"]
        over = ("<p>Synthetic</p>" * 60_001).encode()
        with self.assertRaises(thesis_sources.Unreadable):
            thesis_sources.content(entry, over)
        with patch.object(thesis_sources, "html_paragraphs", side_effect=AssertionError("re-read")):
            with self.assertRaisesRegex(thesis_sources.Unreadable, "more than 60000 paragraphs"):
                thesis_sources.content(entry, over)  # The refusal is kept for these bytes too; nothing is re-read.
        with self.assertRaises(thesis_sources.Unreadable):
            thesis_sources.content(self.entries["iea-2026"], b"Synthetic, not an archive", sheets=("Copper",))
        with self.assertRaises(thesis_sources.Unreadable):
            thesis_sources.content(self.entries["usgs-2026"], "Synthetic,café".encode("latin-1"))


# ---------------------------------------------------------------- locating a figure or passage

class LocateTests(Sources):
    def problems(self, item: dict) -> list[str]:
        source = self.entries[item["source"]]
        sheets = (item["locator"]["sheet"],) if source["kind"] == "xlsx" else ()
        return thesis_sources.locate(item, source, self.held(item["source"], sheets))

    def test_figures_and_passages_are_found_in_each_kind(self):
        items = [
            figure("sec-producer-2025", "410", "410", {"paragraph": 4, "quote": SENSITIVITY}),
            passage("sec-producer-2025", {"paragraph": 3, "quote": "copper sales were 4,120 million pounds"}),
            figure("sec-maker-2025", "45000", "$45,000", {"paragraph": 3, "quote": "selling price of our Synthetic "
                                                                                  "vehicles was $45,000 in 2025"}),
            figure("iea-2021", "53.2", "53.2", {"page": 1, "quote": "Synthetic: an electric car uses 53.2 kg of copper"}),
            passage("iea-2021", {"page": 7, "quote": "Synthetic transcribed passage"}),
            figure("iea-2026", "26500", "26,500", {"sheet": "Copper", "cell": "D5", "label_cell": "C5",
                                                   "label": "Total demand"}),
            figure("worldbank", "9500", "9,500", {"sheet": "Monthly Prices", "cell": "B8", "label_cell": "A8",
                                                  "label": "2026M10"}),
            figure("worldbank", "9342.50", "9,342.50", {"sheet": "Monthly Prices", "cell": "B7", "label_cell": "A7",
                                                        "label": "2026M09"}),
            figure("usgs-2026", "23300", "23,300", {"row": 6, "column": MINE, "label_column": "Year",
                                                    "label": "2025"}),
        ]
        for item in items:
            with self.subTest(source=item["source"], locator=item["locator"]):
                self.assertEqual(self.problems(item), [])

    def test_what_is_not_found_is_named(self):
        cell = {"sheet": "Copper", "cell": "D5", "label_cell": "C5", "label": "Total demand"}
        row = {"row": 6, "column": MINE, "label_column": "Year", "label": "2025"}
        cases = [
            (figure("sec-producer-2025", "410", "410", {"paragraph": 99, "quote": SENSITIVITY}),
             "Paragraph 99 is not in the retained page, which has 10 paragraphs"),
            (figure("sec-producer-2025", "410", "410", {"paragraph": 3, "quote": SENSITIVITY}),
             "Paragraph 3 no longer holds the quoted passage “Based on projected copper sales volumes for 2026, a "
             "change o…”"),
            (figure("sec-producer-2025", "411", "411", {"paragraph": 4, "quote": SENSITIVITY}),
             "The quoted passage does not show “411”"),
            (figure("iea-2026", "26500", "26,500", {**cell, "sheet": "Absent"}),
             "Sheet “Absent” is not in the retained workbook"),
            (figure("iea-2026", "26500", "26,500", {**cell, "label": "Total supply"}),
             "Cell C5 on sheet Copper no longer reads “Total supply”"),
            (figure("iea-2026", "26500", "26,500", {**cell, "label_cell": "Z5"}),
             "Cell Z5 on sheet Copper is empty; it should read “Total demand”"),
            (figure("iea-2026", "26501", "26,501", cell), "Cell D5 on sheet Copper no longer holds 26501"),
            (figure("iea-2026", "26500", "26,500", {**cell, "cell": "Z9"}),
             "Cell Z9 on sheet Copper is empty; it should hold 26500"),
            (figure("iea-2026", "26500", "26,500", {**cell, "cell": "C5"}),
             "Cell C5 on sheet Copper no longer holds a number"),
            (figure("usgs-2026", "23300", "23,300", {**row, "column": "Absent"}),
             "Row 1 does not name the column “Absent”"),
            (figure("usgs-2026", "23300", "23,300", {**row, "row": 7}),
             "Row 7 is not in the retained file, which has 6 rows"),
            (figure("usgs-2026", "23300", "23,300", {**row, "row": 1}), "Row 1 is not a data row"),
            (figure("sec-producer-2025", "410", "410", {"paragraph": 0, "quote": SENSITIVITY}),
             "Paragraph 0 is not in the retained page, which has 10 paragraphs"),
            (figure("usgs-2026", "23300", "23,300", {**row, "label": "2024"}),
             "Row 6, column Year no longer reads “2024”"),
            (figure("usgs-2026", "23301", "23,301", row), f"Row 6, column {MINE} no longer holds 23301"),
            (passage("iea-2026", {"sheet": "Copper", "cell": "C5"}),
             "A passage quotes an HTML page or a PDF; iea-2026 is neither"),
            (passage("usgs-2026", {"row": 6, "column": MINE}),
             "A passage quotes an HTML page or a PDF; usgs-2026 is neither"),
        ]
        for item, problem in cases:
            with self.subTest(problem=problem):
                self.assertEqual(self.problems(item), [problem])

    def test_a_stored_number_matches_its_figure_at_the_figures_precision(self):
        stored = {"B1": "9123.4500000000007", "B2": "1.2E-3", "B3": "9123.46", "B4": "9123.4", "B5": "1.2E-3",
                  "B6": "9123.4500000000007", "B7": "9123.445", "B8": "9123.455", "B9": "1000"}
        raw = rewritten(thesis_fakes.workbook({"Data": {**{f"A{n}": f"Synthetic {n}" for n in range(1, 10)}, **stored}}),
                        lambda name, data: data.replace(  # B5 a text cell, B6 a formula's string result.
                            b'<c r="B5"><v>1.2E-3</v></c>', b'<c r="B5" t="inlineStr"><is><t>1.2E-3</t></is></c>'
                        ).replace(b'<c r="B6"><v>9123.4500000000007</v></c>',
                                  b'<c r="B6" t="str"><f>B1</f><v>9123.4500000000007</v></c>'
                                  ).replace(b"<v>1000</v>", b"<v>1_000</v>"))  # Python's Decimal would read it.
        held = {"Data": thesis_workbook.sheet_cells(raw, "Data")}
        cases = [("B1", "9123.45", []), ("B2", "0.0012", []),
                 ("B3", "9123.45", ["Cell B3 on sheet Data no longer holds 9123.45"]), ("B4", "9123.40", []),
                 ("B5", "0.0012", ["Cell B5 on sheet Data no longer holds a number"]),
                 ("B6", "9123.45", ["Cell B6 on sheet Data no longer holds 9123.45"]),
                 ("B7", "9123.44", []), ("B8", "9123.46", []),  # ROUND_HALF_EVEN, both ways.
                 ("B7", "9123.45", ["Cell B7 on sheet Data no longer holds 9123.45"]),
                 ("B9", "1000", ["Cell B9 on sheet Data no longer holds a number"])]
        for cell, value, problems in cases:
            with self.subTest(cell=cell, value=value):
                item = figure("iea-2026", value, value, {"sheet": "Data", "cell": cell, "label_cell": f"A{cell[1]}",
                                                         "label": f"Synthetic {cell[1]}"})
                self.assertEqual(thesis_sources.locate(item, self.entries["iea-2026"], held), problems)
        with self.assertRaises(ValueError):  # Exponent form is a stored number's, never a printed figure's.
            thesis_arithmetic.shown_value("1.2E-3")

    def test_a_malformed_value_or_locator_is_a_problem_not_an_error(self):
        cell = {"sheet": "Copper", "cell": "D5", "label_cell": "C5", "label": "Total demand"}
        row = {"row": 6, "column": MINE, "label_column": "Year", "label": "2025"}
        for source_id, locator in (("iea-2026", cell), ("usgs-2026", row),
                                   ("sec-producer-2025", {"paragraph": 4, "quote": SENSITIVITY}),
                                   ("iea-2021", {"page": 1, "quote": "Synthetic: an electric car uses 53.2 kg"})):
            for value in ("nine thousand", "26,500", "1.2E3", 26500, None):
                with self.subTest(source=source_id, value=value):
                    self.assertEqual(self.problems(figure(source_id, value, "26,500", locator)),
                                     [f"The figure's value “{value}” is not a plain decimal"])
        for source_id, locator in (("sec-producer-2025", {"paragraph": 4}), ("usgs-2026", "row 6"),
                                   ("iea-2026", {"sheet": "Copper", "cell": "D5"})):
            with self.subTest(locator=locator):
                held = self.held(source_id, ("Copper",) if source_id == "iea-2026" else ())
                self.assertEqual(thesis_sources.locate(figure(source_id, "1", "1", locator), self.entries[source_id],
                                                       held),
                                 ["The locator of “synthetic-figure” cannot be read"])

    def test_every_failure_is_its_own_problem(self):
        item = figure("iea-2026", "1", "1", {"sheet": "Copper", "cell": "D5", "label_cell": "C5", "label": "Other"})
        self.assertEqual(self.problems(item), ["Cell C5 on sheet Copper no longer reads “Other”",
                                               "Cell D5 on sheet Copper no longer holds 1"])
        rows = [["Year", "Value", "Value"], ["2025", "1"]]
        item = figure("usgs-2026", "1", "1", {"row": 2, "column": "Value", "label_column": "Month", "label": "x"})
        self.assertEqual(thesis_sources.locate(item, self.entries["usgs-2026"], rows),
                         ["Row 1 does not name the column “Month”", "Row 1 names the column “Value” 2 times"])
        self.assertEqual(thesis_sources.locate(item, self.entries["usgs-2026"], []),
                         ["The retained file has no header row"])


if __name__ == "__main__":
    unittest.main()
