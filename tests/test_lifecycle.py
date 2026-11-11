"""One prospective showcase lifecycle on mocked FRED snapshots: baseline bound at freeze, pinned outcome.

The evaluation tests read a record frozen before freshness policy B (its baseline ends on Friday, May 30, before
the last session before the June 3 publication), stored exactly as such records are; the freeze tests use baselines
that cover that session, and the policy's own refusal is tested here too."""
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from fred_fixtures import SESSIONS, FakeFred, datasets
from second_order.data import ny_date
from second_order.evaluation import evaluate
from second_order.schema import Hypothesis
from second_order.snapshots import evaluate_bound, load_snapshot, pinned_series, snapshot_revisions
from second_order.store import freeze, open_store, save_evaluation
from test_core import START, hypothesis as fixture_hypothesis
from test_daily import cmt_hypothesis, ny
from store_records import stored_before_policy_b
from test_fred import run_import

ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2025, 6, 22, 12, tzinfo=timezone.utc)
PUBLISHED, FROZEN = ny(2025, 6, 3, 9), ny(2025, 6, 3, 9, 30)


def when(day: date, hour: int = 22) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.store = open_store()
        self.baseline = run_import(self.store, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)),
                                   date(2025, 6, 2), when(date(2025, 6, 2)))["snapshot_id"]
        self.hypothesis = cmt_hypothesis(PUBLISHED, FROZEN)
        self.identity = stored_before_policy_b(self.store, self.hypothesis, FROZEN, self.baseline)

    def tearDown(self):
        self.store.close()

    def outcome(self, through, overrides=None, vintage=date(2025, 6, 20), retrieved=None):
        retrieved = retrieved or when(vintage)
        return run_import(self.store, FakeFred(datasets(through, overrides), vintage), vintage, retrieved)["snapshot_id"]

    def test_lifecycle_binds_the_baseline_and_records_both_snapshots(self):
        outcome = self.outcome(date(2025, 6, 18))
        first = evaluate_bound(self.store, self.identity, outcome, AS_OF)
        self.assertEqual((first["snapshots"]["baseline"], first["snapshots"]["outcome"]), (self.baseline, outcome))
        primary = first["legs"][0]
        days = {key: ny_date(datetime.fromisoformat(primary[key]))
                for key in ("event_anchor", "reference_end", "score_anchor", "target_at")}
        # The baseline ends May 30; the publication date (June 3) is excluded from history and scoring starts
        # at the first date after the freeze date. June 2 exists only in the outcome, so it is not history.
        self.assertEqual(days, {"event_anchor": date(2025, 5, 30), "reference_end": date(2025, 5, 30),
                                "score_anchor": date(2025, 6, 4), "target_at": date(2025, 6, 11)})
        self.assertIn(primary["verdict"], {"supported", "contradicted", "inconclusive"})
        self.assertIn("no intraday observation time is verified", primary["measurement_convention"])
        self.assertEqual(evaluate_bound(self.store, self.identity, outcome, AS_OF), first)
        saved = {save_evaluation(self.store, self.identity, first, AS_OF) for _ in range(2)}
        self.assertEqual(len(saved), 1)
        self.assertEqual(self.store.execute("SELECT baseline_snapshot_id FROM freeze_bindings").fetchall(),
                         [(self.baseline,)])

    def test_revised_pre_event_history_cannot_change_a_pinned_evaluation(self):
        shifted = {day: f"{4 + .25 * math.sin(day.toordinal() / 9) + 2:.2f}" for day in SESSIONS
                   if date(2025, 5, 1) <= day <= date(2025, 5, 29)}
        revised = self.outcome(date(2025, 6, 18), {"DGS10": shifted})
        clean = self.outcome(date(2025, 6, 18), retrieved=when(date(2025, 6, 20), 23))
        with_revision = evaluate_bound(self.store, self.identity, revised, AS_OF)
        without = evaluate_bound(self.store, self.identity, clean, AS_OF)
        self.assertEqual(with_revision["legs"], without["legs"])
        self.assertEqual(with_revision["data_hash"], without["data_hash"])
        changed = {change["date"] for change in snapshot_revisions(load_snapshot(self.store, self.baseline),
                                                                    load_snapshot(self.store, revised))}
        self.assertIn("2025-05-15", changed)
        # The revision is material: had history come from the revised snapshot, the scorer would have
        # ranked the move against a different reference distribution.
        baseline, outcome = load_snapshot(self.store, self.baseline), load_snapshot(self.store, revised)
        references = {}
        for name, history in (("pinned", baseline), ("unpinned", outcome)):
            series = pinned_series("yield:ust10y_cmt", "DGS10", history, outcome, PUBLISHED.date())
            captured = {}
            evaluate(self.hypothesis, {"yield:ust10y_cmt": series}, AS_OF, references=captured)
            references[name] = captured["primary"]
        self.assertNotEqual(references["pinned"], references["unpinned"])

    def test_an_outcome_revision_may_change_the_result_and_appends_a_new_row(self):
        first = self.outcome(date(2025, 6, 18))
        revised = self.outcome(date(2025, 6, 18), {"DGS10": {date(2025, 6, 11): "7.77"}}, date(2025, 6, 21))
        before, after = (evaluate_bound(self.store, self.identity, snapshot, AS_OF) for snapshot in (first, revised))
        self.assertNotEqual(before["legs"][0]["measured_change"], after["legs"][0]["measured_change"])
        saved = [save_evaluation(self.store, self.identity, payload, AS_OF) for payload in (before, after)]
        self.assertEqual(len(set(saved)), 2)
        stored = [json.loads(row[0]) for row in self.store.execute("SELECT payload FROM evaluations ORDER BY rowid")]
        self.assertEqual([row["snapshots"]["outcome"] for row in stored], [first, revised])

    def test_pending_until_the_outcome_snapshot_covers_the_scored_horizon(self):
        cases = [(date(2025, 6, 3), date(2025, 6, 4), "No observation dated after the freeze date"),
                 (date(2025, 6, 6), date(2025, 6, 9), "The scored horizon is not in the imported data yet")]
        for through, vintage, reason in cases:
            with self.subTest(through=through.isoformat()):
                leg = evaluate_bound(self.store, self.identity, self.outcome(through, vintage=vintage), AS_OF)["legs"][0]
                self.assertEqual(leg["verdict"], "pending")
                self.assertIn(reason, leg["reason"])

    def test_the_evaluation_clock_and_snapshot_order_are_enforced(self):
        outcome = self.outcome(date(2025, 6, 18))
        with self.assertRaisesRegex(ValueError, "after the evaluation clock"):
            evaluate_bound(self.store, self.identity, outcome, when(date(2025, 6, 19)))
        older = self.outcome(date(2025, 5, 29), vintage=date(2025, 6, 1))
        with self.assertRaisesRegex(ValueError, "predates the baseline"):
            evaluate_bound(self.store, self.identity, older, AS_OF)


class FreezeBindingTests(unittest.TestCase):
    def setUp(self):
        self.store = open_store()
        # Covers Monday, June 2, the last session before the June 3 publication (freshness policy B).
        self.baseline = run_import(self.store, FakeFred(datasets(date(2025, 6, 2)), date(2025, 6, 3)),
                                   date(2025, 6, 3), when(date(2025, 6, 3), 12))["snapshot_id"]
        self.hypothesis = cmt_hypothesis(PUBLISHED, FROZEN)

    def tearDown(self):
        self.store.close()

    def test_a_baseline_must_exist_and_be_possessed_before_the_freeze(self):
        for baseline, message in ((None, "need a baseline"), ("0" * 64, "existing market snapshot")):
            with self.subTest(baseline=baseline), self.assertRaisesRegex(ValueError, message):
                freeze(self.store, self.hypothesis, FROZEN, baseline)
        late = run_import(self.store, FakeFred(datasets(date(2025, 6, 2)), date(2025, 6, 3)), date(2025, 6, 3),
                          when(date(2025, 6, 3), 23))["snapshot_id"]
        with self.assertRaisesRegex(ValueError, "retrieved before the freeze"):
            freeze(self.store, self.hypothesis, FROZEN, late)
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM hypotheses").fetchone(), (0,))

    def test_bindings_are_unique_append_only_and_only_for_source_bound_legs(self):
        identity = freeze(self.store, self.hypothesis, FROZEN, self.baseline)
        self.assertEqual(freeze(self.store, self.hypothesis, FROZEN, self.baseline), identity)
        other = run_import(self.store, FakeFred(datasets(date(2025, 6, 2)), date(2025, 6, 3)), date(2025, 6, 3),
                           when(date(2025, 6, 3), 13))["snapshot_id"]
        with self.assertRaisesRegex(ValueError, "different baseline"):
            freeze(self.store, self.hypothesis, FROZEN, other)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.execute("UPDATE freeze_bindings SET baseline_snapshot_id=?", (other,))
        with self.assertRaisesRegex(ValueError, "only to source-bound legs"):
            freeze(self.store, fixture_hypothesis(), START + timedelta(days=800), self.baseline)
        mixed = self.hypothesis.model_dump()
        mixed["legs"][1]["observable_id"] = "index:dxy"
        with self.assertRaisesRegex(ValueError, "cannot mix"):
            freeze(self.store, Hypothesis.model_validate(mixed), FROZEN, self.baseline)

    def test_freshness_policy_b_refuses_a_baseline_that_ends_before_the_required_session(self):
        stale = run_import(self.store, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)), date(2025, 6, 2),
                           when(date(2025, 6, 2)))["snapshot_id"]
        with self.assertRaisesRegex(ValueError, "Freshness policy B: .* classifies DGS(2|10) from 2023-01-02 through "
                                                "2025-05-30, but the last expected session before the publication "
                                                "date 2025-06-03 is 2025-06-02"):
            freeze(self.store, self.hypothesis, FROZEN, stale)
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM hypotheses").fetchone(), (0,))
        self.assertEqual(self.store.execute("SELECT COUNT(*) FROM freeze_bindings").fetchone(), (0,))

    def test_a_required_session_the_source_states_without_a_value_is_covered_and_never_filled(self):
        missing = run_import(self.store, FakeFred(datasets(date(2025, 6, 2), {"DGS10": {date(2025, 6, 2): "."},
                                                                               "DGS2": {date(2025, 6, 2): "."}}),
                                                  date(2025, 6, 3)), date(2025, 6, 3), when(date(2025, 6, 3), 12))
        identity = freeze(self.store, self.hypothesis, FROZEN, missing["snapshot_id"])
        snapshot = load_snapshot(self.store, missing["snapshot_id"])
        self.assertIn((date(2025, 6, 2), None, "session_missing"), snapshot.classified["DGS10"])
        self.assertTrue(identity)


class CliLifecycleTests(unittest.TestCase):
    def test_cli_binds_a_baseline_skips_without_an_outcome_and_records_pending(self):
        retrieved = datetime.now(timezone.utc) - timedelta(minutes=5)
        vintage = ny_date(retrieved)
        with tempfile.TemporaryDirectory() as folder:
            path, spec = Path(folder) / "store.db", Path(folder) / "hypothesis.json"
            connection = open_store(str(path))
            # Through today: it covers the last session before any publication date up to today (policy B).
            baseline = run_import(connection, FakeFred(datasets(vintage), vintage), vintage, retrieved)["snapshot_id"]
            connection.close()
            now = datetime.now(timezone.utc)
            spec.write_text(cmt_hypothesis(now - timedelta(hours=1), now).model_dump_json(), encoding="utf-8")
            run = lambda *arguments: subprocess.run([sys.executable, "-m", "second_order", *arguments, "--db", str(path)],
                                                    cwd=ROOT, text=True, capture_output=True, timeout=60)
            frozen = run("freeze", str(spec), "--baseline", baseline)
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            as_of = datetime.now(timezone.utc).isoformat()
            skipped = run("evaluate", "--as-of", as_of)
            self.assertEqual(skipped.returncode, 0, skipped.stderr)
            self.assertIn("pass --outcome", json.loads(skipped.stdout)[0]["skipped"])
            pending = run("evaluate", "--as-of", as_of, "--outcome", baseline)
            self.assertEqual(pending.returncode, 0, pending.stderr)
            self.assertEqual(json.loads(pending.stdout)[0]["legs"][0]["verdict"], "pending")


if __name__ == "__main__":
    unittest.main()
