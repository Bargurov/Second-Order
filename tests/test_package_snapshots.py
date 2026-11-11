"""Store snapshots built locally from a kept H.15 release package (SYNTHETIC packages; temporary stores only).

Checks the copied values, their exact text and calendar statuses, coverage and provenance; that the package has no
vintage and its dates are dates only; that a repeated import reuses its snapshot and writes nothing while another
acquisition keeps its own; that unvalidated, refused, corrupted or out-of-range packages and failed writes leave the
store untouched; that legs, baselines and outcomes never cross providers; that the same values measured from the
Board's package and from FRED give identical anchors, windows, ranks and labels; that FRED's import and the model's
observables are unchanged; and that importing, listing and reading make no network call.
"""
from datetime import date, datetime, time, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fred_fixtures import FakeFred
from market_fakes import keep_package, release_data, release_rows, release_zip
from second_order import market_package, market_retrieval
from second_order.data import DAILY_DATE_CONVENTION, NEW_YORK
from second_order.dossier import prepare
from second_order.drafts import freeze_draft
from second_order.evaluation import evaluate
from second_order.model_draft import prospective_observables
from second_order.package_snapshots import PackageImportRefused, import_package
from second_order.schema import Hypothesis
from second_order.snapshots import (evaluate_bound, list_snapshots, load_snapshot, pinned_series, snapshot_readiness,
                                    snapshot_revisions)
from second_order.store import connect_read_only, freeze, open_store, save_evaluation
from test_daily import cmt_hypothesis, ny
from test_drafts import CLOCK, draft_from
from test_fred import run_import

ROOT = Path(__file__).resolve().parent.parent
FIRST = date(2023, 1, 2)  # A SIFMA holiday (New Year's Day observed): the package lists it as ND.
BASELINE_REQUEST = datetime(2025, 6, 2, 22, tzinfo=timezone.utc)  # 18:00 in New York, the day before publication.
OUTCOME_REQUEST = datetime(2025, 6, 20, 22, tzinfo=timezone.utc)
AS_OF = datetime(2025, 6, 22, 12, tzinfo=timezone.utc)
PUBLISHED, FROZEN = ny(2025, 6, 3, 9), ny(2025, 6, 3, 9, 30)  # CLOCK (freeze_draft's) is 09:30 in New York.
H15_IDS = {"yield:ust2y_cmt": "yield:ust2y_cmt_h15", "yield:ust10y_cmt": "yield:ust10y_cmt_h15"}
TWO, TEN = "RIFLGFCY02_N.B", "RIFLGFCY10_N.B"
COUNTED = ("market_snapshots", "market_series", "market_observations")


def h15_hypothesis(published=PUBLISHED, frozen=FROZEN, usage="showcase", mixed=False) -> Hypothesis:
    """The lifecycle tests' synthetic two-maturity hypothesis, bound to the Board's H.15 entries (or one leg of each
    provider, when mixed)."""
    payload = cmt_hypothesis(published, frozen, usage=usage).model_dump(mode="json")
    payload["engine"]["prompt_hash"] = "c" * 64  # Its own request: freeze identity covers event and engine, not legs.
    for number, leg in enumerate(payload["legs"]):
        if not (mixed and number == 1):
            leg["observable_id"] = H15_IDS[leg["observable_id"]]
    return Hypothesis.model_validate(payload)


def snapshot(folder: Path) -> dict:
    """Relative path -> (SHA-256, size, modification time) of every file below a folder, so writes can be ruled out."""
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size,
                                                  path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()}


def counts(connection) -> dict:
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in COUNTED}


class NoNetwork:
    """Refuses every outside connection or name lookup and records each attempt."""

    def __init__(self):
        self.attempts: list = []

    def __enter__(self):
        def refuse(*args, **kwargs):
            self.attempts.append(args[:2])
            raise AssertionError("network access attempted")
        self.patches = [patch("socket.socket.connect", refuse), patch("socket.create_connection", refuse),
                        patch("socket.getaddrinfo", refuse)]
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *exc):
        for item in self.patches:
            item.stop()


class Packages(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.market, self.db = self.root / "market", str(self.root / "store.db")

    def keep(self, through: date, requested: datetime, overrides: dict | None = None, data: bytes | None = None,
             validate: bool = True) -> str:
        package = release_zip(data if data is not None else release_data(FIRST, through, overrides))
        package_id = keep_package(self.market, package, requested)
        if validate:
            market_retrieval.validate_packages(self.market, lambda: requested + timedelta(minutes=5))
        return package_id

    def run_package(self, package_id: str, start: date = FIRST, moment: datetime | None = None) -> dict:
        connection = open_store(self.db)
        try:
            return import_package(connection, package_id, start, self.market,
                                  lambda: moment or datetime(2025, 6, 30, 12, tzinfo=timezone.utc))
        finally:
            connection.close()

    def folder(self, package_id: str) -> Path:
        return self.market / "packages" / package_id

    def writable(self, path: Path) -> Path:
        path.chmod(0o600)  # Kept records are read-only; a test that corrupts one must unlock it first.
        return path


class ImportTests(Packages):
    def test_values_text_statuses_coverage_and_provenance_are_copied_exactly(self):
        overrides = {date(2024, 3, 5): ("ND", "4.10"),  # A session without a 2-year value: missing, never filled.
                     date(2024, 3, 6): ("3.50", "4.20"),  # Decimal text with a trailing zero, kept as written.
                     date(2024, 3, 7): (None, "4.30"),  # No 2-year row at all on a session: absent.
                     date(2024, 5, 27): ("3.60", "ND")}  # Memorial Day: a 2-year value on a SIFMA holiday.
        package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST, overrides)
        acquisition = json.loads((self.folder(package_id) / "acquisition.json").read_text(encoding="utf-8"))
        validation_path = self.folder(package_id) / market_package.validation_name()
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        before = snapshot(self.folder(package_id))
        stored = self.run_package(package_id, date(2024, 1, 2))
        self.assertEqual(snapshot(self.folder(package_id)), before)  # The package folder is only read.
        self.assertTrue(stored["created"])
        connection = connect_read_only(self.db)
        try:
            column = connection.execute("SELECT provider, vintage_date, retrieved_at FROM market_snapshots").fetchone()
            loaded = load_snapshot(connection, stored["snapshot_id"])
            rows = {(series, day): (value, raw, status) for series, day, value, raw, status, start, end in
                    connection.execute("SELECT series_id, date, value, raw_value, status, fred_realtime_start, "
                                       "fred_realtime_end FROM market_observations")}
            realtime = connection.execute("SELECT COUNT(*) FROM market_observations WHERE fred_realtime_start IS NOT "
                                          "NULL OR fred_realtime_end IS NOT NULL").fetchone()[0]
            kept = {series: json.loads(gzip.decompress(blob)) for series, blob in
                    connection.execute("SELECT series_id, observations_gzip FROM market_series")}
        finally:
            connection.close()
        payload = loaded.payload
        # Possession is the package's receipt; there is no vintage, and the column holds a token, never a date.
        self.assertEqual(column, ("board-h15", "none", payload["retrieved_at"]))
        self.assertIsNone(payload["vintage_date"])
        self.assertEqual(datetime.fromisoformat(payload["retrieved_at"]), datetime.fromisoformat(acquisition["received_at"]))
        self.assertEqual(payload["created_at"], "2025-06-30T12:00:00+00:00")
        self.assertIn("not a historical vintage", payload["semantics"]["vintage_date"])
        self.assertIn("not an observation or possession time", payload["semantics"]["source_prepared"])
        # The source's prepared time is kept exactly as stated (no zone) and used for nothing else.
        self.assertEqual(payload["validation"]["header"]["prepared_as_stated"], "2026-10-08T15:40:02")
        self.assertNotIn("2026-10-08T15:40:02", (payload["retrieved_at"], payload["created_at"]))
        self.assertEqual({key: payload["source"][key] for key in ("package_id", "url", "package_sha256")},
                         {"package_id": package_id, "url": market_package.PACKAGE_URL,
                          "package_sha256": acquisition["sha256"]})
        self.assertEqual(payload["validation"]["record_sha256"], hashlib.sha256(validation_path.read_bytes()).hexdigest())
        self.assertEqual((payload["validation"]["parser_version"], payload["validation"]["rows_sha256"]),
                         (market_package.PARSER_VERSION, validation["rows_sha256"]))
        self.assertEqual(payload["calendar"]["calendar"], "SIFMAUS")
        for series_id in (TWO, TEN):
            entry = payload["series"][series_id]
            self.assertEqual((entry["metadata"]["unit"], entry["metadata"]["short_description"]),
                             ("Percent:_Per_Year", f"{int(series_id[8:10])}-year Treasury constant maturity"))
            self.assertEqual(entry["classified_from"], "2024-01-02")
            self.assertEqual((entry["first_date"], entry["last_date"]), ("2024-01-02", "2025-06-02"))
            self.assertEqual(entry["package_coverage"]["first"], "2023-01-02")
            # The copied rows are the package's rows from the start, byte for byte, with their SHA-256.
            expected = {period: text for period, text in validation["rows"][series_id].items() if period >= "2024-01-02"}
            self.assertEqual(kept[series_id], expected)
            self.assertEqual(entry["observations_sha256"],
                             hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":"),
                                                       ensure_ascii=False).encode()).hexdigest())
        self.assertEqual(rows[(TWO, "2024-03-05")], (None, "ND", "session_missing"))
        self.assertEqual(rows[(TWO, "2024-03-06")], (3.5, "3.50", "session_value"))
        self.assertEqual(rows[(TWO, "2024-03-07")], (None, None, "session_absent"))
        self.assertEqual(rows[(TEN, "2024-03-07")], (4.3, "4.30", "session_value"))
        self.assertEqual(rows[(TWO, "2024-05-27")], (3.6, "3.60", "unreconciled_value_on_calendar_holiday"))
        self.assertEqual(rows[(TEN, "2024-05-27")], (None, "ND", "calendar_holiday"))
        self.assertEqual(realtime, 0)  # FRED's real-time period does not exist here; nothing is invented for it.
        # The grid keeps the missing and absent sessions as missing and drops the explained holiday.
        grid = dict(loaded.grid(TWO))
        self.assertIsNone(grid[date(2024, 3, 5)])
        self.assertIsNone(grid[date(2024, 3, 7)])
        self.assertIsNone(grid[date(2024, 5, 27)])
        self.assertNotIn(date(2024, 5, 27), dict(loaded.grid(TEN)))

    def test_observations_are_dates_only_and_cannot_enter_research(self):
        package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        stored = self.run_package(package_id)
        connection = connect_read_only(self.db)
        try:
            loaded = load_snapshot(connection, stored["snapshot_id"])
        finally:
            connection.close()
        series = pinned_series("yield:ust2y_cmt_h15", TWO, loaded, loaded, date(2025, 6, 3))
        self.assertEqual(series.timestamp_basis, DAILY_DATE_CONVENTION)
        self.assertEqual(series.source, "board-h15:RIFLGFCY02_N.B")
        # A date-only value is ordered at the end of its New York date, a placeholder rather than an observed time.
        self.assertTrue(all(point.at.astimezone(NEW_YORK).time() == time(23, 59, 59) for point in series.observations))
        # With an outcome covering every horizon, the research gate (unchanged) still refuses date-only observations.
        outcome_id = self.run_package(self.keep(date(2025, 6, 20), OUTCOME_REQUEST))["snapshot_id"]
        connection = connect_read_only(self.db)
        try:
            outcome = load_snapshot(connection, outcome_id)
        finally:
            connection.close()
        research = h15_hypothesis(usage="research")
        result = evaluate(research, {leg.observable_id: pinned_series(leg.observable_id, H15_IDS_SERIES[leg.observable_id],
                                                                     loaded, outcome, date(2025, 6, 3))
                                     for leg in research.legs}, AS_OF)
        self.assertEqual({leg["verdict"] for leg in result["legs"]}, {"unavailable"})
        self.assertEqual({leg["reason"] for leg in result["legs"]}, {"Research requires verified observation timestamps"})

    def test_a_repeated_import_reuses_the_snapshot_and_writes_nothing(self):
        package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        first = self.run_package(package_id)
        before = snapshot(self.root)
        second = self.run_package(package_id, moment=datetime(2025, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(snapshot(self.root), before)  # Same bytes, same size, same modification time.
        self.assertEqual((second["snapshot_id"], second["created"], second["created_at"]),
                         (first["snapshot_id"], False, first["created_at"]))
        connection = connect_read_only(self.db)
        try:
            self.assertEqual(counts(connection)["market_snapshots"], 1)
        finally:
            connection.close()
        # A different start is a different snapshot of the same acquisition.
        third = self.run_package(package_id, date(2024, 1, 2))
        self.assertNotEqual(third["snapshot_id"], first["snapshot_id"])
        self.assertEqual(third["retrieved_at"], first["retrieved_at"])

    def test_separate_acquisitions_of_identical_bytes_keep_their_own_possession(self):
        data = release_data(FIRST, date(2025, 6, 2))
        early = self.keep(date(2025, 6, 2), BASELINE_REQUEST, data=data)
        late = self.keep(date(2025, 6, 2), BASELINE_REQUEST + timedelta(hours=1), data=data)
        one, two = self.run_package(early), self.run_package(late)
        self.assertNotEqual(one["snapshot_id"], two["snapshot_id"])
        self.assertEqual(one["source"]["package_sha256"], two["source"]["package_sha256"])
        self.assertEqual(datetime.fromisoformat(two["retrieved_at"]) - datetime.fromisoformat(one["retrieved_at"]),
                         timedelta(hours=1))
        connection = connect_read_only(self.db)
        try:
            listed = list_snapshots(connection)
        finally:
            connection.close()
        self.assertEqual([row["built_from"]["package_id"] for row in listed], [early, late])
        self.assertEqual({row["vintage_date"] for row in listed}, {None})

    def test_unvalidated_refused_corrupted_and_out_of_range_packages_write_nothing(self):
        good = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        unvalidated = self.keep(date(2025, 6, 2), BASELINE_REQUEST + timedelta(hours=1), validate=False)
        connection = open_store(self.db)  # An existing, empty store, so its file can be shown to be untouched.
        connection.close()
        cases = {"an unknown package": ("p20250602T220000000000Z-000000000000", FIRST, "No kept package"),
                 "not a package ID": ("../packages", FIRST, "is not a package ID"),
                 "acquired but not validated": (unvalidated, FIRST, "not validated"),
                 "a start before the package's first observation": (good, date(2022, 12, 30), "would leave"),
                 "a start after its common coverage": (good, date(2025, 6, 3), "only through 2025-06-02")}
        for name, (package_id, start, message) in cases.items():
            with self.subTest(name):
                stored = snapshot(self.root)
                with self.assertRaises(PackageImportRefused) as caught:
                    self.run_package(package_id, start)
                self.assertIn(message, str(caught.exception))
                self.assertEqual(snapshot(self.root), stored)

        # A package its validation refused (here: an empty data entry) is never used.
        refused = self.keep(date(2025, 6, 2), BASELINE_REQUEST + timedelta(hours=2), data=b"")
        verdict = json.loads((self.folder(refused) / market_package.validation_name()).read_text(encoding="utf-8"))
        self.assertEqual(verdict["status"], "refused")
        stored = snapshot(self.root)
        with self.assertRaisesRegex(PackageImportRefused, "was refused by its validation"):
            self.run_package(refused)
        self.assertEqual(snapshot(self.root), stored)

        # Changed package bytes, a changed validation row, or a record of another parser version only.
        tampered = {}  # Each case on its own package, kept at its own time.
        for name in ("bytes", "row", "parser"):
            package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST + timedelta(hours=3 + len(tampered)))
            folder = self.folder(package_id)
            record = folder / market_package.validation_name()
            if name == "bytes":
                with self.writable(folder / "package.zip").open("ab") as handle:
                    handle.write(b"\x00")
            elif name == "row":  # One row's text changed, the record otherwise intact and well formed.
                changed = json.loads(record.read_text(encoding="utf-8"))
                changed["rows"][TWO]["2025-06-02"] = "9.99"
                self.writable(record).write_bytes((json.dumps(changed, indent=2, ensure_ascii=False) + "\n").encode())
            else:
                self.writable(record).rename(folder / "validation-h15-release-xml-parser-0.0.json")
            tampered[name] = package_id
        reasons = {"bytes": "does not match its package's size and SHA-256", "row": "rows do not match their SHA-256",
                   "parser": "not validated"}
        for name, package_id in tampered.items():
            with self.subTest(name):
                stored = snapshot(self.root)
                with self.assertRaisesRegex(PackageImportRefused, reasons[name]):
                    self.run_package(package_id)
                self.assertEqual(snapshot(self.root), stored)
        connection = connect_read_only(self.db)
        try:
            self.assertEqual(counts(connection), {table: 0 for table in COUNTED})
        finally:
            connection.close()

    def test_a_failure_while_writing_publishes_nothing(self):
        package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        connection = open_store(self.db)
        try:
            # The second series' rows are refused mid-transaction, after the snapshot and first series are inserted.
            connection.execute(f"CREATE TEMP TRIGGER refuse BEFORE INSERT ON main.market_observations "
                               f"WHEN NEW.series_id = '{TEN}' BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                import_package(connection, package_id, FIRST, self.market,
                               lambda: datetime(2025, 6, 30, tzinfo=timezone.utc))
            self.assertEqual(counts(connection), {table: 0 for table in COUNTED})
        finally:
            connection.close()


H15_IDS_SERIES = {"yield:ust2y_cmt_h15": TWO, "yield:ust10y_cmt_h15": TEN}


def fred_rows(through: date) -> dict:
    """The same SYNTHETIC values as the package, in FRED's format ("." for no value)."""
    return {fred: [(date.fromisoformat(period), "." if status == "ND" else value)
                   for period, status, value in release_rows(FIRST, through)[board]]
            for fred, board in (("DGS2", TWO), ("DGS10", TEN))}


class LifecycleTests(Packages):
    """Synthetic freezes and evaluations on a temporary store, to prove compatibility; nothing real is frozen."""

    def setUp(self):
        super().setUp()
        self.baseline_package = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        self.outcome_package = self.keep(date(2025, 6, 20), OUTCOME_REQUEST)
        self.h15_baseline = self.run_package(self.baseline_package, moment=BASELINE_REQUEST + timedelta(hours=1))
        connection = open_store(self.db)
        try:
            self.fred_baseline = run_import(connection, FakeFred(fred_rows(date(2025, 6, 2)), date(2025, 6, 2)),
                                            date(2025, 6, 2), BASELINE_REQUEST)["snapshot_id"]
        finally:
            connection.close()
        self.h15_baseline = self.h15_baseline["snapshot_id"]

    def freeze_both(self, connection) -> tuple[str, str]:
        h15 = freeze_draft(connection, draft_from(h15_hypothesis()), self.h15_baseline, lambda: CLOCK)["hypothesis_id"]
        fred = freeze_draft(connection, draft_from(cmt_hypothesis(PUBLISHED, FROZEN)), self.fred_baseline,
                            lambda: CLOCK)["hypothesis_id"]
        return h15, fred

    def test_bindings_never_cross_providers(self):
        connection = open_store(self.db)
        try:
            frozen = CLOCK
            with self.assertRaisesRegex(ValueError, "comes from fred, but the legs are bound to board-h15"):
                freeze(connection, h15_hypothesis(frozen=frozen), frozen, self.fred_baseline)
            with self.assertRaisesRegex(ValueError, "comes from board-h15, but the legs are bound to fred"):
                freeze(connection, cmt_hypothesis(PUBLISHED, frozen), frozen, self.h15_baseline)
            for baseline in (self.h15_baseline, self.fred_baseline):
                with self.assertRaisesRegex(ValueError, "cannot mix market data providers"):
                    freeze(connection, h15_hypothesis(frozen=frozen, mixed=True), frozen, baseline)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0], 0)
            h15, fred = self.freeze_both(connection)
            fred_outcome = run_import(connection, FakeFred(fred_rows(date(2025, 6, 20)), date(2025, 6, 20)),
                                      date(2025, 6, 20), OUTCOME_REQUEST)["snapshot_id"]
            h15_outcome = import_package(connection, self.outcome_package, FIRST, self.market,
                                         lambda: OUTCOME_REQUEST + timedelta(hours=1))["snapshot_id"]
            with self.assertRaisesRegex(ValueError, "outcome snapshot comes from fred, but leg primary is bound to "
                                                    "board-h15"):
                evaluate_bound(connection, h15, fred_outcome, AS_OF)
            with self.assertRaisesRegex(ValueError, "outcome snapshot comes from board-h15, but leg primary is bound "
                                                    "to fred"):
                evaluate_bound(connection, fred, h15_outcome, AS_OF)
            with self.assertRaisesRegex(ValueError, "different providers"):
                snapshot_revisions(load_snapshot(connection, self.fred_baseline), load_snapshot(connection, h15_outcome))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0], 0)
        finally:
            connection.close()

    def test_the_same_values_from_the_board_and_from_fred_are_measured_identically(self):
        connection = open_store(self.db)
        try:
            h15, fred = self.freeze_both(connection)
            fred_outcome = run_import(connection, FakeFred(fred_rows(date(2025, 6, 20)), date(2025, 6, 20)),
                                      date(2025, 6, 20), OUTCOME_REQUEST)["snapshot_id"]
            h15_outcome = import_package(connection, self.outcome_package, FIRST, self.market,
                                         lambda: OUTCOME_REQUEST + timedelta(hours=1))["snapshot_id"]
            board = evaluate_bound(connection, h15, h15_outcome, AS_OF)
            reference = evaluate_bound(connection, fred, fred_outcome, AS_OF)
            readiness = {provider: snapshot_readiness(load_snapshot(connection, snapshot_id), before=date(2025, 6, 3))
                         for provider, snapshot_id in (("board", self.h15_baseline), ("fred", self.fred_baseline))}
        finally:
            connection.close()
        compared = ("verdict", "event_anchor", "score_anchor", "reference_end", "target_at", "measured_change",
                    "signed_move", "percentile_rank", "reference_windows", "non_overlapping_reference_windows",
                    "placebo", "anchor_policy", "measurement_convention")
        self.assertEqual(board["verdict"], reference["verdict"])
        for mine, theirs in zip(board["legs"], reference["legs"]):
            self.assertEqual(mine["observable_id"], H15_IDS[theirs["observable_id"]])
            self.assertEqual({key: mine.get(key) for key in compared}, {key: theirs.get(key) for key in compared})
            self.assertIn(mine["verdict"], {"supported", "contradicted", "inconclusive"})
        self.assertEqual((board["rules_hash"], board["snapshots"]["history_from"]),
                         (reference["rules_hash"], reference["snapshots"]["history_from"]))
        self.assertNotEqual(board["data_hash"], reference["data_hash"])  # The source labels differ, as they should.
        strip = lambda report: {series["observable_id"].replace("_h15", ""): series["horizons"]  # noqa: E731
                                for series in report["series"].values()}
        self.assertEqual(strip(readiness["board"]), strip(readiness["fred"]))

    def test_the_dossier_labels_and_cites_the_board_with_no_vintage(self):
        connection = open_store(self.db)
        try:
            h15, fred = self.freeze_both(connection)
            for identity, outcome in ((h15, import_package(connection, self.outcome_package, FIRST, self.market,
                                                           lambda: OUTCOME_REQUEST + timedelta(hours=1))["snapshot_id"]),
                                      (fred, run_import(connection, FakeFred(fred_rows(date(2025, 6, 20)),
                                                                             date(2025, 6, 20)),
                                                        date(2025, 6, 20), OUTCOME_REQUEST)["snapshot_id"])):
                save_evaluation(connection, identity, evaluate_bound(connection, identity, outcome, AS_OF), AS_OF)
        finally:
            connection.close()
        out = self.root / "prepared"
        before = snapshot(self.root)
        prepare(out, db=self.db)
        self.assertEqual({name: value for name, value in snapshot(self.root).items() if not name.startswith("prepared/")},
                         before)  # Preparation reads the store and the packages; it writes only the prepared views.
        board = json.loads((out / f"{h15}.json").read_text(encoding="utf-8"))
        fred_view = json.loads((out / f"{fred}.json").read_text(encoding="utf-8"))
        provenance = board["data_provenance"]
        self.assertEqual(provenance["provider"], "Federal Reserve Board H.15")
        self.assertIn("Board of Governors of the Federal Reserve System", provenance["attribution"])
        self.assertEqual((provenance["baseline"]["vintage_date"], provenance["outcome"]["vintage_date"]), (None, None))
        self.assertNotIn("FRED", json.dumps(board))  # No FRED label or attribution anywhere on the Board's case.
        self.assertTrue(all("no vintage; package received" in leg["series"]["caption"] for leg in board["legs"]))
        self.assertIn("no historical vintage", next(item["text"] for item in board["limitations"]
                                                    if item["title"] == "Pinned snapshots"))
        self.assertEqual(fred_view["data_provenance"]["provider"], "FRED")
        self.assertIn("FRED® API", fred_view["data_provenance"]["attribution"])


class CompatibilityTests(Packages):
    def test_fred_import_and_the_model_contract_are_unchanged(self):
        package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        self.run_package(package_id)
        fake = FakeFred(fred_rows(date(2025, 6, 2)), date(2025, 6, 2))
        connection = open_store(self.db)
        try:
            from second_order.fred import import_and_report
            first = import_and_report(connection, "abcdefghijklmnopqrstuvwxyz012345", FIRST, date(2025, 6, 2),
                                      fake.client(), lambda: BASELINE_REQUEST)
            later = FakeFred(fred_rows(date(2025, 6, 3)), date(2025, 6, 3))
            second = import_and_report(connection, "abcdefghijklmnopqrstuvwxyz012345", FIRST, date(2025, 6, 3),
                                       later.client(), lambda: BASELINE_REQUEST + timedelta(days=1))
        finally:
            connection.close()
        self.assertEqual({params["series_id"] for _, params in fake.calls}, {"DGS2", "DGS10"})  # Never a Board ID.
        self.assertNotIn("revisions_since", first)  # The Board's snapshot is not a FRED revision baseline.
        self.assertEqual(second["revisions_since"], first["stored"]["snapshot_id"])
        self.assertEqual(sorted(first["readiness"]["series"]), ["DGS10", "DGS2"])
        self.assertEqual(prospective_observables(), ("yield:ust10y_cmt", "yield:ust2y_cmt"))

    def test_the_network_adapter_is_never_imported_by_the_package_import(self):
        source = (ROOT / "second_order" / "package_snapshots.py").read_text(encoding="utf-8")
        self.assertNotIn("httpx", source)
        self.assertNotIn("from .fred", source)

    def test_importing_listing_and_reading_make_no_network_call(self):
        package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        with NoNetwork() as guard:
            stored = self.run_package(package_id)
            self.run_package(package_id)
            for _ in range(2):
                connection = connect_read_only(self.db)
                try:
                    list_snapshots(connection)
                    snapshot_readiness(load_snapshot(connection, stored["snapshot_id"]), before=date(2025, 6, 3))
                finally:
                    connection.close()
        self.assertEqual(guard.attempts, [])

    def test_the_cli_imports_lists_and_reports_readiness(self):
        package_id = self.keep(date(2025, 6, 2), BASELINE_REQUEST)
        environment = {key: value for key, value in os.environ.items() if key != "FRED_API_KEY"}

        def cli(*args):
            run = subprocess.run([sys.executable, "-m", "second_order", "market", *args], cwd=ROOT, env=environment,
                                 text=True, capture_output=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr)
            return json.loads(run.stdout)

        imported = cli("import-package", "--db", self.db, "--package", package_id, "--start", "2024-01-02",
                       "--packages-dir", str(self.market))
        self.assertTrue(imported["stored"]["created"])
        self.assertEqual(sorted(imported["readiness"]["series"]), [TWO, TEN])
        before = snapshot(self.root)
        again = cli("import-package", "--db", self.db, "--package", package_id, "--start", "2024-01-02",
                    "--packages-dir", str(self.market))
        listed = cli("snapshots", "--db", self.db)
        ready = cli("readiness", "--db", self.db, "--snapshot", imported["stored"]["snapshot_id"],
                    "--published", "2025-06-03")
        self.assertEqual(snapshot(self.root), before)  # The repeat and the reads wrote nothing.
        self.assertFalse(again["stored"]["created"])
        self.assertEqual((listed[0]["provider"], listed[0]["vintage_date"], listed[0]["built_from"]["package_id"]),
                         ("board-h15", None, package_id))
        self.assertEqual(ready["series"][TWO]["event_anchor"], "2025-06-02")
        refused = subprocess.run([sys.executable, "-m", "second_order", "market", "import-package", "--db", self.db,
                                  "--package", "p20250602T220000000000Z-000000000000", "--start", "2024-01-02",
                                  "--packages-dir", str(self.market)], cwd=ROOT, env=environment, text=True,
                                 capture_output=True, timeout=120)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("No kept package", refused.stderr)


if __name__ == "__main__":
    unittest.main()
