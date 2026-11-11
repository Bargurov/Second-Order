"""Stored is not sufficient: readiness runs the scorer's own windows and controls under the active rules."""
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fred_fixtures import FAKE_KEY, FakeFred, datasets
from second_order.fred import import_and_report
from second_order.scoring import Rules
from second_order.snapshots import evaluate_bound, load_snapshot, snapshot_readiness
from second_order.store import freeze, open_store
from test_core import snapshot
from test_daily import cmt_hypothesis
from store_records import stored_before_policy_b
from test_fred import run_import
from test_lifecycle import AS_OF, FROZEN, PUBLISHED, when

ROOT = Path(__file__).resolve().parent.parent


def baseline(store, first: date, hour: int = 22) -> str:
    fake = FakeFred(datasets(date(2025, 5, 30), first=first), date(2025, 6, 2))
    return run_import(store, fake, date(2025, 6, 2), when(date(2025, 6, 2), hour), start=first)["snapshot_id"]


def covering_baseline(store, first: date, hour: int = 12) -> str:
    """Through Monday, June 2, the last session before the June 3 publication (freshness policy B)."""
    fake = FakeFred(datasets(date(2025, 6, 2), first=first), date(2025, 6, 3))
    return run_import(store, fake, date(2025, 6, 3), when(date(2025, 6, 3), hour), start=first)["snapshot_id"]


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.store = open_store()

    def tearDown(self):
        self.store.close()

    def report(self, first: date, hour: int) -> dict:
        fake = FakeFred(datasets(date(2025, 5, 30), first=first), date(2025, 6, 2))
        return import_and_report(self.store, FAKE_KEY, first, date(2025, 6, 2), fake.client(),
                                 lambda: when(date(2025, 6, 2), hour))

    def test_storing_a_snapshot_is_reported_separately_from_sufficient_history(self):
        tiny = self.report(date(2025, 5, 16), 22)
        self.assertTrue(tiny["stored"]["snapshot_id"])
        for series in ("DGS2", "DGS10"):
            entry = tiny["readiness"]["series"][series]
            self.assertEqual(entry["scorable_horizons"], [])
            self.assertEqual(entry["horizons"]["1"]["required_reference_windows"], Rules().min_windows)
            self.assertLess(entry["horizons"]["1"]["reference_windows"], Rules().min_windows)
        full = self.report(date(2023, 1, 2), 23)
        self.assertEqual(full["revisions_since"], tiny["stored"]["snapshot_id"])
        for series in ("DGS2", "DGS10"):
            entry = full["readiness"]["series"][series]
            self.assertEqual(entry["scorable_horizons"], [1, 5, 20])
            for horizon in entry["horizons"].values():
                self.assertEqual(horizon["placebo"]["eligible"], horizon["placebo"]["requested"])

    def test_readiness_counts_are_the_scorers_own(self):
        snapshot_id = baseline(self.store, date(2023, 1, 2))
        # A record frozen before freshness policy B: its baseline ends May 30, as such stored records do.
        identity = stored_before_policy_b(self.store, cmt_hypothesis(PUBLISHED, FROZEN), FROZEN, snapshot_id)
        outcome = run_import(self.store, FakeFred(datasets(date(2025, 6, 18)), date(2025, 6, 20)), date(2025, 6, 20),
                             when(date(2025, 6, 20)))["snapshot_id"]
        legs = {leg["leg_id"]: leg for leg in evaluate_bound(self.store, identity, outcome, AS_OF)["legs"]}
        report = snapshot_readiness(load_snapshot(self.store, snapshot_id), before=PUBLISHED.date())
        primary, secondary = report["series"]["DGS10"]["horizons"]["5"], report["series"]["DGS2"]["horizons"]["1"]
        self.assertEqual(report["series"]["DGS10"]["event_anchor"], "2025-05-30")
        self.assertEqual((primary["reference_windows"], primary["non_overlapping_reference_windows"],
                          primary["placebo"]["eligible"]),
                         (legs["primary"]["reference_windows"], legs["primary"]["non_overlapping_reference_windows"],
                          legs["primary"]["placebo"]["eligible"]))
        self.assertEqual(secondary["reference_windows"], legs["secondary"]["reference_windows"])

    def test_freeze_refuses_insufficient_history_and_accepts_partial_placebo_coverage(self):
        hypothesis = cmt_hypothesis(PUBLISHED, FROZEN)
        with self.assertRaisesRegex(ValueError, "Baseline history is insufficient for yield:ust10y_cmt at horizon 5"):
            freeze(self.store, hypothesis, FROZEN, covering_baseline(self.store, date(2025, 5, 16)))
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM hypotheses").fetchone(), (0,))
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM freeze_bindings").fetchone(), (0,))
        medium = covering_baseline(self.store, date(2024, 3, 18), hour=13)
        five = snapshot_readiness(load_snapshot(self.store, medium), before=PUBLISHED.date())["series"]["DGS10"]["horizons"]["5"]
        self.assertTrue(five["scorable"])
        self.assertLess(five["placebo"]["eligible"], five["placebo"]["requested"])  # Reported, not required.
        self.assertTrue(freeze(self.store, hypothesis, FROZEN, medium))

    def test_source_bound_replays_are_refused(self):
        replay = cmt_hypothesis(PUBLISHED, FROZEN, replay=True)
        with self.assertRaisesRegex(ValueError, "replays are not supported"):
            freeze(self.store, replay, FROZEN, baseline(self.store, date(2023, 1, 2)))

    def test_cli_readiness_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "store.db"
            connection = open_store(str(path))
            snapshot_id = baseline(connection, date(2023, 1, 2))
            connection.close()
            before = snapshot(Path(folder))
            result = subprocess.run([sys.executable, "-m", "second_order", "market", "readiness", "--db", str(path),
                                     "--snapshot", snapshot_id, "--published", "2025-06-03"],
                                    cwd=ROOT, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual((report["series"]["DGS10"]["event_anchor"], report["series"]["DGS10"]["scorable_horizons"]),
                             ("2025-05-30", [1, 5, 20]))
            self.assertEqual(snapshot(Path(folder)), before)


if __name__ == "__main__":
    unittest.main()
