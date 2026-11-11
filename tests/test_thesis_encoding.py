"""A CSV source's declared encoding (ruling R13): the reader decodes with the encoding the source entry declares, strict
UTF-8 or strict Windows-1252, and never guesses; the schema requires the declaration; and a figure in a file written in
Windows-1252 is found when declared so and needs revalidation when the file is declared UTF-8 (ruling R7).

Runs on SYNTHETIC bytes and the synthetic sources and versions (tests/thesis_fakes.py), each in a temporary folder.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import thesis_fakes
from second_order import thesis_schema, thesis_sources, thesis_view
from second_order.thesis_rules import ThesisRefused
from second_order.thesis_sources import Unreadable
from test_thesis_schema import Theses, find

ID = thesis_fakes.THESIS_ID
DASH = b"Section,Value\r\nSalient Statistics\x97United States,1100\r\n"


class ReaderTests(unittest.TestCase):
    def test_the_declared_encodings_are_the_two_named(self):
        self.assertEqual(thesis_sources.CSV_ENCODINGS, ("utf-8", "windows-1252"))

    def test_windows_1252_bytes_read_under_their_declared_encoding_only(self):
        self.assertEqual(thesis_sources.csv_rows(DASH, "windows-1252"),
                         [["Section", "Value"], ["Salient Statistics—United States", "1100"]])
        with self.assertRaises(Unreadable) as caught:
            thesis_sources.csv_rows(DASH, "utf-8")
        self.assertIn("UTF-8", str(caught.exception))
        with self.assertRaises(Unreadable):
            thesis_sources.csv_rows(DASH)  # UTF-8 is the default.

    def test_the_five_undefined_windows_1252_bytes_are_refused(self):
        for byte in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
            with self.subTest(byte=hex(byte)):
                with self.assertRaises(Unreadable) as caught:
                    thesis_sources.csv_rows(b"a,b\r\nx" + bytes([byte]) + b"y,2\r\n", "windows-1252")
                self.assertIn("Windows-1252", str(caught.exception))

    def test_a_utf8_byte_order_mark_is_allowed_under_utf8_and_refused_under_windows_1252(self):
        raw = b"\xef\xbb\xbfa,b\r\n1,2\r\n"
        self.assertEqual(thesis_sources.csv_rows(raw, "utf-8"), [["a", "b"], ["1", "2"]])
        with self.assertRaises(Unreadable) as caught:
            thesis_sources.csv_rows(raw, "windows-1252")
        self.assertIn("UTF-8 byte-order mark", str(caught.exception))
        self.assertIn("Windows-1252", str(caught.exception))

    def test_an_unknown_encoding_is_a_programming_error(self):
        for encoding in ("UTF-8", "latin-1", "cp1252", "", None):
            with self.subTest(encoding=encoding):
                with self.assertRaises(ValueError) as caught:
                    thesis_sources.csv_rows(b"a,b\r\n", encoding)
                self.assertNotIsInstance(caught.exception, Unreadable)


class MemoTests(unittest.TestCase):
    """Bytes valid in both encodings that decode differently: "café" in UTF-8 is "cafÃ©" in Windows-1252."""
    RAW = b"name,value\r\ncaf\xc3\xa9,1\r\n"
    UTF8 = [["name", "value"], ["café", "1"]]
    WIN = [["name", "value"], ["cafÃ©", "1"]]

    def setUp(self):
        thesis_sources._MEMO.clear()
        self.addCleanup(thesis_sources._MEMO.clear)

    def source(self, encoding):
        return {"kind": "csv", "folder": "usgs-2026", "name": "copper.csv", "encoding": encoding}

    def test_the_same_bytes_under_another_encoding_are_read_afresh_in_either_order(self):
        for order in (("utf-8", "windows-1252"), ("windows-1252", "utf-8"), ("utf-8", "windows-1252", "utf-8")):
            thesis_sources._MEMO.clear()
            with self.subTest(order=order):
                for encoding in order:
                    expected = self.UTF8 if encoding == "utf-8" else self.WIN
                    self.assertEqual(thesis_sources.content(self.source(encoding), self.RAW), expected)

    def test_a_refusal_is_kept_per_encoding_too(self):
        with self.assertRaises(Unreadable):
            thesis_sources.content(self.source("windows-1252"), DASH.replace(b"\x97", b"\x81"))
        with self.assertRaises(Unreadable):
            thesis_sources.content(self.source("utf-8"), DASH.replace(b"\x97", b"\x81"))
        raw = b"\xef\xbb\xbfa,b\r\n1,2\r\n"
        with self.assertRaises(Unreadable):
            thesis_sources.content(self.source("windows-1252"), raw)
        self.assertEqual(thesis_sources.content(self.source("utf-8"), raw), [["a", "b"], ["1", "2"]])

    def test_a_repeat_read_under_the_same_encoding_is_served_from_the_memo(self):
        first = thesis_sources.content(self.source("windows-1252"), self.RAW)
        self.assertIs(thesis_sources.content(self.source("windows-1252"), self.RAW), first)


class SchemaTests(Theses):
    WHERE = "sources[usgs-2026].encoding"

    def declare(self, source_id, encoding):
        return lambda b: find(b["sources"], source_id).update(encoding=encoding)

    def test_a_csv_source_may_declare_windows_1252(self):
        loaded = self.accepted(self.declare("usgs-2026", "windows-1252"))
        self.assertEqual(find(loaded["sources"], "usgs-2026")["encoding"], "windows-1252")
        self.assertEqual(find(loaded["sources"], "usgs-2025")["encoding"], "utf-8")

    def test_a_csv_source_declares_exactly_one_of_the_two_encodings(self):
        for value in (None, "UTF-8", "latin-1", "cp1252", "utf-8-sig", "", 1252):
            with self.subTest(value=value):
                self.refused(self.declare("usgs-2026", value), self.WHERE)

    def test_a_source_without_the_encoding_field_is_refused(self):
        message = self.refused(lambda b: find(b["sources"], "usgs-2026").pop("encoding"), "sources[")
        self.assertIn("encoding", message)

    def test_only_a_csv_source_declares_an_encoding(self):
        for source_id in ("iea-2026", "worldbank", "iea-2021", "sec-producer-2025"):
            for value in ("utf-8", "windows-1252"):
                with self.subTest(source=source_id, value=value):
                    message = self.refused(self.declare(source_id, value), f"sources[{source_id}].encoding")
                    self.assertIn("only a CSV source declares an encoding", message)


class EndToEndTests(unittest.TestCase):
    """A synthetic CSV written in Windows-1252 (an em dash, 0x97, in a neighbouring cell) through thesis_view.view."""
    CELL = b"Synthetic USGS Mineral Commodity Summaries 2026"
    AFFECTED = {"balance-side-by-side", "mine-supply-slow", "mine-output-rising"}  # As test_thesis_view's unreadable case.

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="second-order-thesis-encoding-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sources, self.content = self.tmp / "sources", self.tmp / "content"
        thesis_sources._MEMO.clear()
        self.addCleanup(thesis_sources._MEMO.clear)

    def reply(self, encoding):
        thesis_fakes.write_sources(self.sources)
        raw = thesis_fakes.usgs_csv(2026).replace(self.CELL, b"Synthetic\x97USGS", 1)
        self.assertIn(b"\x97", raw)
        thesis_fakes.retain(self.sources, "usgs-2026", raw)
        def declare(body):  # Version 2 re-reads its source entries, so both versions are changed.
            find(body["sources"], "usgs-2026").update(encoding=encoding)
        v1 = thesis_fakes.changed(thesis_fakes.thesis_v1(self.sources), declare)
        v2 = thesis_fakes.changed(thesis_fakes.thesis_v2(v1, self.sources), declare)
        thesis_fakes.write_theses(self.content, [v1, v2], ["2026-11-02", "2026-11-16"])
        return thesis_view.view(ID, None, self.content, self.sources)

    def states(self, reply):
        items = [reply["view"], *reply["balance"]["tables"], *reply["differs"], *reply["reasons"], *reply["risks"],
                 *reply["conditions"], *reply["exposure"]["movers"], *reply["exposure"]["moved"], reply["price_record"]]
        return {item["id"]: item["state"] for item in items}

    def test_a_figure_in_a_windows_1252_file_is_available_when_declared_so(self):
        reply = self.reply("windows-1252")
        self.assertEqual(find(reply["sources"], "usgs-2026")["state"], "verified")
        self.assertEqual({key for key, state in self.states(reply).items() if state != "available"}, set())

    def test_the_same_file_declared_utf8_needs_revalidation_as_an_unreadable_source_does(self):
        reply = self.reply("utf-8")
        self.assertEqual(find(reply["sources"], "usgs-2026")["state"], "verified")
        self.assertEqual({key for key, state in self.states(reply).items() if state != "available"}, self.AFFECTED)
        self.assertEqual({state for key, state in self.states(reply).items() if key in self.AFFECTED},
                         {"needs_revalidation"})
        problem = next(item for item in reply["reasons"] if item["id"] == "mine-supply-slow")["problems"]
        self.assertEqual(problem, ["usgs26-mine-2024: The retained file of usgs-2026 matches its acquisition record "
                                   "but cannot be read (The file is not UTF-8 text)"])

    def test_the_view_does_not_show_the_encoding(self):
        reply = self.reply("windows-1252")
        self.assertTrue(all("encoding" not in source for source in reply["sources"]))


if __name__ == "__main__":
    unittest.main()
