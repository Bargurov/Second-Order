"""The H.15 release package: archive safeguards, the protected parser, the data entry's checks, per-series coverage,
the derived index's integrity on every read, and compatibility with earlier CSV retrievals.

Every package here is SYNTHETIC (tests/market_fakes.py: invented values in the format of the Board's H.15 XML package as
inspected in October 2026) and every folder is temporary. An independent reader (regular expressions over the
decompressed bytes, no XML parser) checks the parser's output on the fixtures. The same check runs against a real
retained package only on explicit opt-in: set SECOND_ORDER_H15_PACKAGE to a kept package's folder; that run reads the
folder and writes nothing. Nothing reaches a network.
"""
from datetime import date, datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from market_fakes import (COMMON_XSD, DATASET_OPEN, DISCONTINUED_OPEN, MESSAGE_OPEN, STRUCTURE, keep_package,
                          release_data, release_rows, release_zip, synthetic_pair, target_xml)
from second_order import market_context, market_package, market_retrieval, market_store
from second_order.market_package import ArchiveRefused, DataRefused
from test_event_market_context import NOW, Folders, fingerprint, writable

TWO, TEN = "RIFLGFCY02_N.B", "RIFLGFCY10_N.B"
START, END = date(2026, 9, 1), date(2026, 9, 30)
REQUESTED_ON = date(2026, 10, 9)


def entry(two: str | None = None, ten: str | None = None, before: str = "", after: str = "", discontinued: str = "",
          rows: dict | None = None, header: str = "H15") -> bytes:
    """A data entry assembled from parts, for the checks that change one part."""
    rows = rows or release_rows(START, END)
    two = target_xml(TWO, rows[TWO]) if two is None else two
    ten = target_xml(TEN, rows[TEN]) if ten is None else ten
    text = (MESSAGE_OPEN.format(prepared="2026-10-08T15:40:02").replace("<message:ID>H15<", f"<message:ID>{header}<") +
            DATASET_OPEN + before + two + ten + after + "  </frb:DataSet>\r\n" + DISCONTINUED_OPEN + discontinued +
            "  </frb:DataSet>\r\n</message:MessageGroup>")
    return text.encode("utf-8")


def obs(period: str, status: str = "A", value: str = "1.00") -> tuple[str, str, str]:
    return period, status, value


class Packages(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, data: bytes, name: str = "package.zip") -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def validate(self, data: bytes, requested_on: date = REQUESTED_ON) -> dict:
        return market_package.validate(self.write(data), "p", "sha", datetime(2026, 10, 9, tzinfo=timezone.utc),
                                       requested_on)

    def refused(self, data: bytes) -> str:
        record = self.validate(data)
        self.assertEqual(record["status"], "refused")
        self.assertIsNone(record["rows"])
        return record["detail"]


class ArchiveTests(Packages):
    def test_the_same_synthetic_data_makes_the_same_package_at_any_time(self):
        """Tests that keep identical data twice rely on identical bytes, so the fake's zip entries carry a fixed time
        rather than the clock's (whose 2-second steps would otherwise split them now and then)."""
        data = release_data(START, END)
        with patch("time.time", return_value=1_791_000_000.0):
            first = release_zip(data)
        with patch("time.time", return_value=1_791_000_007.0):
            second = release_zip(data)
        self.assertEqual(first, second)

    def test_the_boards_layout_passes_and_doctype_markers_are_recorded_not_refused(self):
        entries, findings = market_package.check_archive(self.write(release_zip(release_data(START, END))))
        self.assertEqual([item["name"] for item in entries], ["H15_discontinued.xsd", "H15_H15.xsd", "H15_data.xml",
                                                               "H15_struct.xml", "frb_common.xsd"])
        self.assertTrue(all(item["crc_checked"] and len(item["sha256"]) == 64 for item in entries))
        self.assertEqual((findings["total"], findings["omitted"]), (2, 0))
        self.assertEqual([(item["entry"], item["marker"], item["uncompressed_offset"]) for item in findings["recorded"]],
                         [("H15_struct.xml", "<!DOCTYPE", 22), ("frb_common.xsd", "<!DOCTYPE", 22)])
        self.assertTrue(all(item["marker"] in item["context_untrusted"] and item["context_bytes"] <= 200
                            for item in findings["recorded"]))
        self.assertIn("does not distinguish a declaration from text inside a comment", findings["note"])

    def test_markers_are_found_once_at_exact_offsets_across_reads_and_excerpts_are_bounded(self):
        size = 64 * 6
        text = bytearray(b"-" * size)
        positions = [0, 64 - 4, 3 * 64 - 9, size - 9]  # At the start, straddling two reads, at the end.
        for position in positions:
            text[position:position + 9] = b"<!DOCTYPE"
        many = b"".join(b"<!ENTITY e%d 'x'>" % n for n in range(30))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("a.xml", bytes(text))
            archive.writestr("b.xml", many)
        with patch.object(market_package, "CHUNK", 64):
            entries, findings = market_package.check_archive(self.write(buffer.getvalue()))
        self.assertEqual([item["uncompressed_offset"] for item in findings["recorded"] if item["entry"] == "a.xml"],
                         positions)
        self.assertEqual(entries[1]["marker_hits"], {"<!DOCTYPE": 0, "<!ENTITY": 30})
        self.assertEqual((findings["total"], len(findings["recorded"]), findings["omitted"]), (34, 20, 14))
        self.assertTrue(all(item["context_bytes"] <= 200 for item in findings["recorded"]))

    def test_unsafe_entries_are_refused(self):
        def archive(name, mode=None, compress=zipfile.ZIP_DEFLATED):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as handle:
                info = zipfile.ZipInfo(name)
                info.compress_type = compress
                if mode is not None:
                    info.external_attr = mode << 16
                handle.writestr(info, b"<x/>")
            return buffer.getvalue()

        def flagged(data):  # The central directory's general-purpose flag: bit 0 says "encrypted".
            at = data.index(b"PK\x01\x02") + 8
            return data[:at] + bytes([data[at] | 1]) + data[at + 1:]

        cases = {"../outside.xml": archive("../outside.xml"), "/absolute.xml": archive("/absolute.xml"),
                 "C:drive.xml": archive("C:drive.xml"), "control": archive("a\x01.xml"),
                 "symbolic link": archive("link.xml", 0o120777), "encrypted": flagged(archive("secret.xml")),
                 "bzip2": archive("packed.xml", compress=zipfile.ZIP_BZIP2)}
        for label, data in cases.items():
            with self.subTest(label=label), self.assertRaises(ArchiveRefused) as refused:
                market_package.check_archive(self.write(data))
            self.assertEqual(refused.exception.outcome, "unsafe_archive")
        self.assertFalse(market_package._entry_name_safe("folder\\inside.xml"))  # Windows readers convert it to "/".
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as handle, self.assertWarns(UserWarning):
            handle.writestr("twice.xml", b"<a/>")
            handle.writestr("twice.xml", b"<b/>")
        with self.assertRaises(ArchiveRefused) as duplicate:
            market_package.check_archive(self.write(buffer.getvalue()))
        self.assertIn("same name", str(duplicate.exception))

    def test_counts_sizes_ratios_and_integrity_are_checked_on_the_actual_bytes(self):
        def archive(files, compress=zipfile.ZIP_DEFLATED):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compress) as handle:
                for name, content in files:
                    handle.writestr(name, content)
            return buffer.getvalue()

        stored = archive([("a.xml", b"<abcdefgh/>" * 50)], zipfile.ZIP_STORED)
        at = stored.index(b"<abcdefgh/>") + 3
        cases = [
            ("archive_limit", "51 entries; 1 to 50 are allowed", archive([(f"e{n}.xml", b"<x/>") for n in range(51)]), {}),
            ("archive_limit", "0 entries", archive([]), {}),
            ("archive_limit", "expands more than 200:1", archive([("bomb.xml", b"\0" * (50 * 1024 * 1024))]), {}),
            ("archive_limit", "declares 2000 bytes", archive([("big.xml", os.urandom(2000))]), {"MAX_ENTRY": 1000}),
            ("archive_limit", "passed the limit", archive([("a.xml", os.urandom(2000)), ("b.xml", os.urandom(2000))]),
             {"MAX_TOTAL": 3000}),
            ("malformed_archive", "Bad CRC-32", stored[:at] + b"Z" + stored[at + 1:], {}),
            ("malformed_archive", "could not be read", stored[:len(stored) // 2], {}),
            ("malformed_archive", "could not be read", b"not a zip archive", {}),
        ]
        for outcome, words, data, limits in cases:
            with self.subTest(words=words), patch.multiple(market_package, **limits) if limits else \
                    patch.object(market_package, "MAX_ENTRIES", 50), self.assertRaises(ArchiveRefused) as refused:
                market_package.check_archive(self.write(data))
            self.assertEqual(refused.exception.outcome, outcome)
            self.assertIn(words, str(refused.exception))


class ParserTests(Packages):
    def test_the_two_series_are_read_with_their_metadata_and_exact_text(self):
        overrides = {date(2026, 9, 15): ("3.94", "4.125"), date(2026, 9, 16): ("4.10", "ND")}
        record = self.validate(release_zip(release_data(START, END, overrides)))
        self.assertEqual((record["status"], record["detail"], record["parser_version"]),
                         ("accepted", None, "h15-release-xml-parser-0.1"))
        rows = record["rows"]
        self.assertEqual((rows[TWO]["2026-09-15"], rows[TEN]["2026-09-15"]), ("3.94", "4.125"))
        self.assertEqual((rows[TWO]["2026-09-16"], rows[TEN]["2026-09-16"]), ("4.10", "ND"))  # Text kept: 4.10.
        self.assertEqual(rows[TWO]["2026-09-07"], "ND")  # Labor Day: listed with ND and -9999 in the package.
        self.assertEqual(rows[TWO]["2026-09-08"], synthetic_pair(date(2026, 9, 8))[0])
        self.assertNotIn("2026-09-05", rows[TWO])  # A Saturday: never listed.
        two = record["series"][TWO]
        self.assertEqual(two["attributes"], {"CURRENCY": "NA", "FREQ": "9", "INSTRUMENT": "TCMNOM", "MATURITY": "Y2",
                                             "SERIES_NAME": TWO, "UNIT": "Percent:_Per_Year", "UNIT_MULT": "1"})
        self.assertEqual((two["first"], two["last"], two["observations"], two["no_value"], two["missing_weekdays"]),
                         ("2026-09-01", "2026-09-30", 22, 1, 0))
        self.assertEqual(record["series"][TEN]["no_value"], 2)
        self.assertEqual(record["header"], {"id": "H15", "name": "H.15 Selected Interest Rates",
                                            "prepared": "2026-10-08T15:40:02"})
        self.assertEqual(record["coverage"], {"first": "2026-09-01", "last": "2026-09-30"})
        self.assertEqual(record["data_entry"]["name"], "H15_data.xml")
        self.assertIn("DOCTYPE declarations refused", record["parser"]["protections"])

    def test_coverage_is_per_series_and_only_their_common_dates_are_stated(self):
        rows = release_rows(START, END)
        rows[TWO] = [row for row in rows[TWO] if row[0] >= "2026-09-08"]  # The 2-year series starts later...
        rows[TEN] = [row for row in rows[TEN] if row[0] <= "2026-09-25"]  # ...and the 10-year one ends earlier.
        record = self.validate(release_zip(entry(rows=rows)))
        self.assertEqual((record["series"][TWO]["first"], record["series"][TEN]["last"]), ("2026-09-08", "2026-09-25"))
        self.assertEqual(record["coverage"], {"first": "2026-09-08", "last": "2026-09-25"})
        held = market_package.held(record)
        self.assertEqual((held.first, held.last), (date(2026, 9, 8), date(2026, 9, 25)))

    def test_a_missing_weekday_is_no_row_and_is_counted(self):
        record = self.validate(release_zip(release_data(START, END, {date(2026, 9, 17): (None, "4.00")})))
        self.assertNotIn("2026-09-17", record["rows"][TWO])
        self.assertEqual(record["rows"][TEN]["2026-09-17"], "4.00")
        self.assertEqual((record["series"][TWO]["missing_weekdays"], record["series"][TEN]["missing_weekdays"]), (1, 0))

    def test_the_data_entry_is_parsed_with_every_declaration_and_external_resource_refused(self):
        secret = self.root / "local-file.txt"
        secret.write_text("never read", encoding="utf-8")
        declaration = {
            "a bare DOCTYPE": '<!DOCTYPE message:MessageGroup>',
            "an internal entity": '<!DOCTYPE m [<!ENTITY e "expanded">]>',
            "a local file": f'<!DOCTYPE m [<!ENTITY e SYSTEM "{secret.as_uri()}">]>',
            "an external DTD": '<!DOCTYPE m SYSTEM "https://example.invalid/h15.dtd">',
            "nested entities": '<!DOCTYPE m [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;">]>',
            "a parameter entity": '<!DOCTYPE m [<!ENTITY % p SYSTEM "https://example.invalid/p.ent"> %p;]>',
        }
        for label, text in declaration.items():
            with self.subTest(label=label):
                data = entry().replace(b"?>\r\n", f"?>\r\n{text}\r\n".encode(), 1).replace(
                    b"<message:Name>H.15 Selected", b"<message:Name>&e; H.15 Selected", 1 if "entity" in label else 0)
                detail = self.refused(release_zip(data))
                self.assertIn("H15_data.xml has a DOCTYPE declaration, which the parser policy refuses", detail)
        undefined = entry().replace(b"<message:Name>H.15", b"<message:Name>&undefined; H.15", 1)
        self.assertIn("not well-formed XML (undefined entity", self.refused(release_zip(undefined)))
        commented = entry().replace(b"  <message:Header", b"  <!-- <!DOCTYPE in a comment -->\r\n  <message:Header", 1)
        record = self.validate(release_zip(commented))  # A byte pattern alone refuses nothing; the parser decides.
        self.assertEqual(record["status"], "accepted")
        self.assertIn("H15_data.xml", {item["entry"] for item in record["archive"]["marker_findings"]["recorded"]})

    def test_unexpected_metadata_or_observations_refuse_the_package(self):
        rows = release_rows(START, END)
        two = rows[TWO]

        def with_rows(changed):
            return target_xml(TWO, changed)

        cases = {
            "has the attributes": [entry(two=target_xml(TWO, two, {"UNIT": "Percent"})),
                                   entry(two=target_xml(TWO, two, {"FREQ": "21"})),
                                   entry(two=target_xml(TWO, two, {"UNIT_MULT": "100"})),
                                   entry(two=target_xml(TWO, two, {"CURRENCY": "USD"})),
                                   entry(two=target_xml(TWO, two, {"MATURITY": "Y3"})),
                                   entry(two=target_xml(TWO, two, {"EXTRA": "1"})),
                                   entry(two=with_rows([obs("2026-09-01")])
                                         .replace('TIME_PERIOD="2026-09-01"', 'TIME_PERIOD="2026-09-01" OBS_CONF="F"'))],
            "short description": [entry(two=target_xml(TWO, two, short="2-year Treasury bill"))],
            "long description": [entry(two=target_xml(TWO, two, long="Market yield on a different series"))],
            "does not contain RIFLGFCY02_N.B": [entry(two="")],
            "appears more than once": [entry(after=target_xml(TWO, two))],
            "outside the H15 dataset": [entry(discontinued=target_xml(TWO, two)), entry(two="", discontinued=target_xml(TWO, two))],
            "status 'NA'": [entry(two=with_rows([obs("2026-09-01", "NA", "-9999")]))],
            "status 'ND' with value '0'": [entry(two=with_rows([obs("2026-09-01", "ND", "0")]))],
            "not a plain decimal": [entry(two=with_rows([obs("2026-09-01", "A", value)]))
                                    for value in ("4,10", "", "4.1e2", "4", " 4.10", "NaN")],
            "a duplicate observation": [entry(two=with_rows([obs("2026-09-01"), obs("2026-09-01")]))],
            "observations out of order": [entry(two=with_rows([obs("2026-09-02"), obs("2026-09-01")]))],
            "on a weekend": [entry(two=with_rows([obs("2026-09-05")]))],
            "not a calendar date": [entry(two=with_rows([obs(period)])) for period in ("2026-02-30", "2026/09/01", "")],
            "header does not name": [entry(header="H16")],
            "not an SDMX message group": [entry().replace(b"message:MessageGroup", b"message:Other")],
            "outside a series": [entry(before='      <frb:Obs OBS_STATUS="A" OBS_VALUE="1.00" TIME_PERIOD="2026-09-02" />\r\n')],
            "no dates in common": [entry(rows={TWO: release_rows(START, date(2026, 9, 10))[TWO],
                                               TEN: release_rows(date(2026, 9, 21), END)[TEN]})],
            "has no observations": [entry(two=with_rows([]))],
            "not well-formed": [entry()[:-40]],
        }
        for words, datas in cases.items():
            for n, data in enumerate(datas):
                with self.subTest(words=words, n=n):
                    self.assertIn(words, self.refused(release_zip(data)))
        self.assertIn("has no H15_data.xml entry", self.refused(release_zip(b"", {"H15_data.xml": None})))
        self.assertIn("after the day the package was requested (2026-09-20)",
                      self.validate(release_zip(entry()), date(2026, 9, 20))["detail"])
        for limit, value, words in (("MAX_OBSERVATIONS", 5, "more than 5 observations"),
                                    ("MAX_TEXT", 10, "longer than 10 characters"),
                                    ("MAX_DEPTH", 3, "nests elements more than 3 deep")):
            with self.subTest(limit=limit), patch.object(market_package, limit, value):
                self.assertIn(words, self.refused(release_zip(entry())))

    def test_unused_entries_with_a_doctype_do_not_refuse_the_data(self):
        record = self.validate(release_zip(release_data(START, END), {"H15_struct.xml": STRUCTURE,
                                                                       "frb_common.xsd": COMMON_XSD}))
        self.assertEqual(record["status"], "accepted")
        self.assertEqual(record["archive"]["marker_findings"]["total"], 2)


# ---------------------------------------------------------------- the independent reader

TAG = re.compile(rb'<frb:DataSet ([^>]*)>|<kf:Series ([^>]*)>|<frb:Obs ([^>]*?)/>|</kf:Series>')
ATTRIBUTE = re.compile(rb'([A-Za-z_:]+)="([^"]*)"')


def independent_rows(package: Path) -> dict:
    """A second reader of the data entry, sharing no code with the parser: regular expressions over the decompressed
    bytes, read in chunks and cut at a tag's end. It keeps the two series' observations in the H15 dataset, in
    document order, ND for status ND with -9999."""
    rows, dataset, current, pending = {TWO: {}, TEN: {}}, None, None, b""
    with zipfile.ZipFile(package) as archive, archive.open("H15_data.xml") as stream:
        while chunk := stream.read(1 << 20):
            pending += chunk
            cut = pending.rfind(b">") + 1
            text, pending = pending[:cut], pending[cut:]
            for match in TAG.finditer(text):
                if match.group(1) is not None:
                    dataset = dict(ATTRIBUTE.findall(match.group(1))).get(b"id")
                elif match.group(2) is not None:
                    name = dict(ATTRIBUTE.findall(match.group(2))).get(b"SERIES_NAME", b"").decode()
                    current = name if name in rows and dataset == b"H15" else None
                elif match.group(3) is not None and current:
                    fields = {key.decode(): value.decode() for key, value in ATTRIBUTE.findall(match.group(3))}
                    status, value = fields["OBS_STATUS"], fields["OBS_VALUE"]
                    rows[current][fields["TIME_PERIOD"]] = "ND" if (status, value) == ("ND", "-9999") else \
                        value if status == "A" else f"{status}:{value}"
                else:
                    current = None
    return rows


class IndependentReaderTests(Packages):
    def test_the_independent_reader_and_the_parser_agree_on_the_fixtures(self):
        overrides = {date(2026, 9, 15): ("3.94", "4.125"), date(2026, 9, 17): None}
        path = self.write(release_zip(release_data(date(2026, 1, 2), END, overrides)))
        rows = market_package.parse_data(path)["rows"]
        self.assertEqual(rows, independent_rows(path))
        self.assertEqual(list(rows[TWO]), list(independent_rows(path)[TWO]))  # The same order, too.

    @unittest.skipUnless(os.environ.get("SECOND_ORDER_H15_PACKAGE"), "set SECOND_ORDER_H15_PACKAGE to a kept package's "
                         "folder to compare a real retained package (read-only)")
    def test_a_real_retained_package_read_independently(self):
        folder = Path(os.environ["SECOND_ORDER_H15_PACKAGE"])
        if not market_package.PACKAGE_ID.fullmatch(folder.name) or not (folder / "package.zip").is_file() or \
                not (folder / "acquisition.json").is_file():
            self.fail(f"{folder} is not a kept package's folder")
        before = fingerprint(folder)
        record = json.loads((folder / "acquisition.json").read_text(encoding="utf-8"))
        self.assertEqual(market_package.file_sha256(folder / "package.zip"), (record["bytes"], record["sha256"]))
        parsed = market_package.parse_data(folder / "package.zip")
        rows = independent_rows(folder / "package.zip")
        self.assertEqual(parsed["rows"], rows)
        self.assertGreater(min(len(series) for series in rows.values()), 10_000)
        found, problems = market_store.retrievals(self.root / "empty-store", market_context.BUNDLE_DIR)
        self.assertEqual(problems, [])
        compared = 0
        for retrieval in found:
            for series_id, series_rows in retrieval.rows.items():
                for day, raw in series_rows.items():
                    self.assertEqual(rows[series_id].get(day.isoformat()), raw, (retrieval.id, series_id, day))
                    compared += 1
        self.assertGreater(compared, 500)  # Every committed CSV statement matches the package's text.
        validation = folder / market_package.validation_name()
        if validation.is_file():
            self.assertEqual(json.loads(validation.read_text(encoding="utf-8"))["rows"], rows)
        self.assertEqual(fingerprint(folder), before)


# ---------------------------------------------------------------- the derived index and earlier records

class IndexTests(Folders):
    def keep(self, start=date(2026, 1, 2), end=date(2026, 10, 8), overrides=None, requested=NOW - timedelta(hours=20),
             validate=True) -> Path:
        package_id = keep_package(self.store, release_zip(release_data(start, end, overrides)), requested)
        if validate:
            market_retrieval.validate_packages(self.store, self.clock)
        return self.store / "packages" / package_id

    def problems(self) -> list[str]:
        return [item["problem"] for item in market_store.retrievals(self.store, None)[1]]

    def edit_validation(self, folder: Path, change) -> None:
        path = folder / market_package.validation_name()
        record = json.loads(path.read_text(encoding="utf-8"))
        change(record)
        writable(path)
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_an_accepted_index_is_used_and_verified_again_on_every_read(self):
        folder = self.keep()
        found, problems = market_store.retrievals(self.store, None)
        self.assertEqual(([item.id for item in found], problems), ([f"package:{folder.name}"], []))
        self.assertEqual(found[0].rows[TWO][date(2026, 9, 15)], synthetic_pair(date(2026, 9, 15))[0])
        self.assertEqual((found[0].requested_end, found[0].last_row), (date(2026, 10, 8), date(2026, 10, 8)))
        self.edit_validation(folder, lambda record: record["rows"][TWO].update({"2026-09-15": "9.99"}))
        before = fingerprint(self.store)
        self.assertIn("rows do not match their SHA-256", self.problems()[0])
        self.assertEqual(market_store.retrievals(self.store, None)[0], [])
        self.assertEqual(fingerprint(self.store), before)  # Reported, not repaired.

    def test_counts_that_do_not_match_the_rows_are_refused(self):
        folder = self.keep()
        self.edit_validation(folder, lambda record: record["series"][TWO].update({"no_value": 0}))
        self.assertIn("does not match its rows or the expected series", self.problems()[0])

    def test_an_index_of_other_bytes_or_another_parser_version_is_not_used(self):
        first, second = self.keep(), self.keep(end=date(2026, 10, 7), requested=NOW - timedelta(hours=19))
        name = market_package.validation_name()
        writable(second / name)
        (second / name).unlink()
        shutil.copy(first / name, second / name)  # An index that belongs to the other package.
        self.assertIn(f"belongs to another package ({first.name})", " ".join(self.problems()))
        writable(second / name)
        self.edit_validation(second, lambda record: record.update(package_id=second.name))  # Same ID, other bytes.
        self.assertIn("was derived from other package bytes", " ".join(self.problems()))
        writable(second / name)
        (second / name).rename(second / "validation-h15-release-xml-parser-0.0.json")
        _, problems, packages = market_store.local_data(self.store, None)
        state = next(item for item in packages if item["package_id"] == second.name)
        self.assertEqual((state["status"], state["other_validations"]),
                         ("acquired_unvalidated", ["validation-h15-release-xml-parser-0.0.json"]))
        self.assertEqual(problems, [])
        self.assertEqual([item.id for item in market_store.retrievals(self.store, None)[0]], [f"package:{first.name}"])

    def test_a_changed_package_or_acquisition_record_is_reported_and_not_used(self):
        folder = self.keep()
        before_problems = self.problems()
        writable(folder / "package.zip")
        (folder / "package.zip").write_bytes((folder / "package.zip").read_bytes() + b"\0")
        self.assertIn("does not match its package's size and SHA-256", self.problems()[0])
        self.assertEqual(before_problems, [])
        other = self.keep(requested=NOW - timedelta(hours=18), validate=False)
        writable(other / "acquisition.json")
        record = json.loads((other / "acquisition.json").read_text(encoding="utf-8"))
        (other / "acquisition.json").write_text(json.dumps({**record, "url": "https://example.com/h15.zip"}),
                                                encoding="utf-8")
        self.assertIn("does not have the expected fields and values", " ".join(self.problems()))
        self.assertEqual(market_store.retrievals(self.store, None)[0], [])

    def test_a_refusal_is_listed_with_its_reason_and_kept(self):
        data = release_data(date(2026, 1, 2), date(2026, 10, 8)).replace(b"?>\r\n", b"?>\r\n<!DOCTYPE m>\r\n", 1)
        package_id = keep_package(self.store, release_zip(data), NOW - timedelta(hours=20))
        results = market_retrieval.validate_packages(self.store, self.clock)
        self.assertEqual([(item["package"], item["result"]) for item in results], [(package_id, "refused")])
        _, problems, packages = market_store.local_data(self.store, None)
        self.assertEqual((packages[0]["status"], problems), ("refused", []))
        self.assertIn("DOCTYPE declaration", packages[0]["detail"])
        self.assertTrue((self.store / "packages" / package_id / "package.zip").is_file())


class LegacyTests(Folders):
    def test_csv_retrievals_and_packages_that_agree_are_combined_and_both_named(self):
        self.confirm("FOMC statement", "2026-09-16")
        csv = self.put_retrieval(date(2026, 9, 2), date(2026, 9, 30), NOW - timedelta(days=5))
        package_id = keep_package(self.store, release_zip(release_data(date(2026, 1, 2), date(2026, 10, 8))),
                                  NOW - timedelta(hours=20))
        market_retrieval.validate_packages(self.store, self.clock)
        view = self.page("inbox", self.id("FOMC statement"))["view"]
        self.assertEqual(view["conflicts"], [])
        self.assertTrue(view["complete"])
        self.assertEqual(self.day(view, "2026-09-15")["observations"][TWO]["retrievals"],
                         sorted([f"package:{package_id}", f"private:{csv}"]))
        self.assertEqual({item["origin"] for item in view["retrievals"]}, {"private", "package"})

    def test_a_revision_between_a_csv_and_a_package_stays_a_conflict(self):
        self.confirm("FOMC statement", "2026-09-16")
        csv = self.put_retrieval(date(2026, 9, 2), date(2026, 9, 30), NOW - timedelta(days=5),
                                 {date(2026, 9, 15): ("3.99", synthetic_pair(date(2026, 9, 15))[1])})
        package_id = keep_package(self.store, release_zip(release_data(date(2026, 1, 2), date(2026, 10, 8))),
                                  NOW - timedelta(hours=20))
        market_retrieval.validate_packages(self.store, self.clock)
        view = self.page("inbox", self.id("FOMC statement"))["view"]
        self.assertEqual(view["conflicts"], [{"date": "2026-09-15", "series": TWO, "versions": [
            {"raw": "3.99", "retrievals": [f"private:{csv}"]},
            {"raw": synthetic_pair(date(2026, 9, 15))[0], "retrievals": [f"package:{package_id}"]}]}])
        changes = {(change["series"], change["horizon"]): change for change in view["endpoints"]["changes"]}
        self.assertIn("retrieval versions disagree", changes[(TWO, 1)]["unavailable"])
        self.assertIsNotNone(changes[(TEN, 1)]["change_bp"])

    def test_earlier_csv_attempts_are_read_unchanged_beside_new_ones(self):
        plan_sha = "b" * 64
        started = {"attempt_version": "market-retrieval-attempt-0.1", "plan_sha256": plan_sha, "number": 1,
                   "events": ["capture-x"], "source": market_store.SOURCE_ID,
                   "url": market_context.export_url(date(2026, 9, 2), date(2026, 9, 30)),
                   "requested_start": "2026-09-02", "requested_end": "2026-09-30", "missing_sessions": 20,
                   "started_at": "2026-10-09T15:00:00+00:00", "client": {"user_agent": "u", "transport": "t"},
                   "note": "Recorded before the request was sent."}
        market_store.write_exclusive(market_store.started_path(self.store, plan_sha, 1), started)
        before = fingerprint(self.store)
        attempts = market_store.read_attempts(self.store)
        self.assertEqual([(item["started"], item["outcome"], item["problem"]) for item in attempts],
                         [(started, None, None)])
        self.assertEqual(fingerprint(self.store), before)


if __name__ == "__main__":
    unittest.main()
