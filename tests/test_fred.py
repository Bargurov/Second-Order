"""FRED import on mocked requests: pinned vintages, kept-apart dates, fail-closed contracts, no secrets."""
import ast
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fred_fixtures import FAKE_KEY, FakeFred, datasets
from second_order.fred import ImportRefused, import_snapshot
from second_order.snapshots import list_snapshots, load_snapshot, snapshot_revisions
from second_order.store import open_store
from test_core import snapshot

ROOT = Path(__file__).resolve().parent.parent
RETRIEVED = datetime(2025, 6, 2, 22, tzinfo=timezone.utc)  # 18:00 in New York, June 2.
BASELINE_VINTAGE = date(2025, 6, 2)


def run_import(connection, fake, vintage=BASELINE_VINTAGE, clock=RETRIEVED, key=FAKE_KEY, start=date(2023, 1, 2)):
    return import_snapshot(connection, key, start, vintage, fake.client(), lambda: clock)


def snapshot_rows(connection) -> dict:
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("market_snapshots", "market_series", "market_observations")}


class FredImportTests(unittest.TestCase):
    def setUp(self):
        self.connection = open_store()

    def tearDown(self):
        self.connection.close()

    def test_pinned_snapshot_keeps_observation_vintage_and_retrieval_apart(self):
        fake = FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE)
        result = run_import(self.connection, fake)
        stored = load_snapshot(self.connection, result["snapshot_id"])
        self.assertEqual((stored.payload["vintage_date"], stored.payload["retrieved_at"]),
                         ("2025-06-02", RETRIEVED.isoformat()))
        self.assertEqual(stored.payload["request"]["realtime_start"], stored.payload["request"]["realtime_end"])
        self.assertNotIn("api_key", json.dumps(stored.payload))
        self.assertIn("not the issuer's first publication date", stored.payload["semantics"]["vintage_date"])
        self.assertIn("possession, not first public availability", stored.payload["semantics"]["retrieved_at"])
        self.assertEqual(len(fake.calls), 4)
        for _, params in fake.calls:
            self.assertEqual((params["realtime_start"], params["realtime_end"]), ("2025-06-02", "2025-06-02"))
        self.assertEqual(set(fake.keys), {FAKE_KEY})  # Sent only as the request parameter.
        statuses = {day: status for day, _, status in stored.classified["DGS10"]}
        self.assertEqual(statuses[date(2024, 11, 11)], "calendar_holiday")
        self.assertEqual(statuses[date(2024, 11, 12)], "session_value")
        self.assertEqual(stored.payload["calendar"]["calendar"], "SIFMAUS")

    def test_the_credential_never_reaches_storage_errors_or_listings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "store.db"
            connection = open_store(str(path))
            run_import(connection, FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE))
            listing = json.dumps(list_snapshots(connection))
            failures = [FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE, raise_for="DGS10"),
                        FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE, status={("observations", "DGS2"): 500}),
                        FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE, echo_key=True)]
            for fake in failures:
                with self.assertRaises(ImportRefused) as raised:
                    run_import(connection, fake, clock=datetime(2025, 6, 3, 22, tzinfo=timezone.utc))
                self.assertNotIn(FAKE_KEY, str(raised.exception))
            connection.close()
            self.assertNotIn(FAKE_KEY.encode(), path.read_bytes())
            self.assertNotIn(FAKE_KEY, listing)
        unused = FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE)
        with self.assertRaisesRegex(ImportRefused, "FRED_API_KEY is not set"):
            run_import(self.connection, unused, key="")
        self.assertEqual(unused.calls, [])

    def test_metadata_and_observation_contracts_fail_closed_without_storing(self):
        broken_rows = lambda rows: lambda payload: {**payload, "observations": rows(payload["observations"])}
        cases = {
            "units": {"metadata": {"DGS10": {"units": "Lin"}}},
            "frequency": {"metadata": {"DGS10": {"frequency_short": "W"}}},
            "copyright": {"metadata": {"DGS10": {"notes": "Copyright, 2025, a data owner. All rights reserved."}}},
            "vintage": {"patch_observations": {"DGS10": lambda payload: {**payload, "realtime_start": "2025-06-01"}}},
            "order": {"patch_observations": {"DGS10": broken_rows(lambda rows: rows[::-1])}},
            "value": {"patch_observations": {"DGS10": broken_rows(lambda rows: rows[:-1] + [{**rows[-1], "value": "n/a"}])}},
        }
        for name, options in cases.items():
            with self.subTest(case=name), self.assertRaises(ImportRefused):
                run_import(self.connection, FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE, **options))
        self.assertEqual(snapshot_rows(self.connection), {"market_snapshots": 0, "market_series": 0,
                                                          "market_observations": 0})

    def test_revisions_are_reported_and_never_overwrite_the_earlier_snapshot(self):
        first = run_import(self.connection, FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE))
        revised = datasets(date(2025, 6, 18), {"DGS10": {date(2025, 5, 15): "4.99"}})
        second = run_import(self.connection, FakeFred(revised, date(2025, 6, 20)), date(2025, 6, 20),
                            datetime(2025, 6, 20, 22, tzinfo=timezone.utc))
        old, new = load_snapshot(self.connection, first["snapshot_id"]), load_snapshot(self.connection, second["snapshot_id"])
        changes = snapshot_revisions(old, new)
        self.assertEqual([(change["series"], change["date"], change["after"]["value"]) for change in changes],
                         [("DGS10", "2025-05-15", 4.99)])
        self.assertNotEqual(dict((d, v) for d, v, _ in old.classified["DGS10"])[date(2025, 5, 15)], 4.99)
        self.assertEqual(len(list_snapshots(self.connection)), 2)


class ReadPathTests(unittest.TestCase):
    def test_read_modules_never_import_the_network_adapter(self):
        for module in ("api", "dossier", "evaluation", "snapshots", "store", "demo", "anchors", "scoring"):
            tree = ast.parse((ROOT / "second_order" / f"{module}.py").read_text(encoding="utf-8"))
            imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            with self.subTest(module=module):
                self.assertNotIn("fred", imported)
                self.assertNotIn("httpx", imported)

    def test_cli_refuses_an_import_without_a_key_and_listing_is_read_only(self):
        environment = {key: value for key, value in os.environ.items() if key != "FRED_API_KEY"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "store.db"
            refused = subprocess.run([sys.executable, "-m", "second_order", "market", "import", "--db", str(path),
                                      "--start", "2023-01-02"], cwd=ROOT, env=environment, text=True,
                                     capture_output=True, timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("FRED_API_KEY is not set", refused.stderr)
            self.assertFalse(path.exists())
            connection = open_store(str(path))
            run_import(connection, FakeFred(datasets(date(2025, 5, 30)), BASELINE_VINTAGE))
            connection.close()
            before = snapshot(Path(folder))
            listed = subprocess.run([sys.executable, "-m", "second_order", "market", "snapshots", "--db", str(path)],
                                    cwd=ROOT, env=environment, text=True, capture_output=True, timeout=30)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(json.loads(listed.stdout)[0]["vintage_date"], "2025-06-02")
            self.assertEqual(snapshot(Path(folder)), before)


if __name__ == "__main__":
    unittest.main()
