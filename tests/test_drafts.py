"""Freeze helper: stamps the real time, validates strictly, never restamps or writes the draft."""
import copy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pydantic import ValidationError
from fred_fixtures import FakeFred, datasets
from second_order.data import ny_date
from second_order.drafts import freeze_draft
from second_order.store import open_store
from test_daily import cmt_hypothesis, ny
from test_fred import run_import
from test_lifecycle import when

ROOT = Path(__file__).resolve().parent.parent
CLOCK = datetime(2025, 6, 3, 13, 30, tzinfo=timezone.utc)  # 09:30 in New York.


def draft_from(hypothesis) -> dict:
    payload = hypothesis.model_dump(mode="json")
    for field in ("frozen_at", "replay_as_of", "supersedes"):
        payload.pop(field)
    return payload


class FreezeDraftTests(unittest.TestCase):
    def setUp(self):
        self.store = open_store()
        # Covers Monday, June 2, the last session before the June 3 publication (freshness policy B).
        self.baseline = run_import(self.store, FakeFred(datasets(date(2025, 6, 2)), date(2025, 6, 3)), date(2025, 6, 3),
                                   when(date(2025, 6, 3), 12))["snapshot_id"]
        self.draft = draft_from(cmt_hypothesis(ny(2025, 6, 3, 9), ny(2025, 6, 3, 9)))

    def tearDown(self):
        self.store.close()

    def stored(self) -> int:
        return self.store.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0]

    def test_stamps_the_current_time_and_binds_the_baseline_atomically(self):
        original = copy.deepcopy(self.draft)
        result = freeze_draft(self.store, self.draft, self.baseline, lambda: CLOCK)
        self.assertEqual((result["frozen_at"], result["recorded_at"], result["bound_at"]), (CLOCK.isoformat(),) * 3)
        self.assertEqual(result["baseline_snapshot_id"], self.baseline)
        payload = json.loads(self.store.execute("SELECT payload FROM hypotheses WHERE id=?",
                                                (result["hypothesis_id"],)).fetchone()[0])
        self.assertEqual(datetime.fromisoformat(payload["frozen_at"]), CLOCK)
        self.assertEqual(self.draft, original)

    def test_only_manual_prospective_showcase_drafts_are_accepted(self):
        cases = {
            "frozen_at": ({"frozen_at": CLOCK.isoformat()}, ValueError, "must not carry frozen_at"),
            "replay_as_of": ({"replay_as_of": None}, ValueError, "must not carry replay_as_of"),
            "supersedes": ({"supersedes": "a" * 64}, ValueError, "must not carry supersedes"),
            "replay": ({"evidence_class": "replay"}, ValueError, "prospective showcase"),
            "research": ({"usage": "research"}, ValueError, "research intake is closed"),
            "model": ({"engine": {**self.draft["engine"], "provider": "anthropic"}}, ValueError, "manual drafts"),
            "unknown": ({"verdict": "supported"}, ValidationError, "verdict"),
            "future": ({"event": {**self.draft["event"], "published_at": "2025-06-04T13:00:00Z"}}, ValidationError,
                       "Freeze cannot precede publication"),
        }
        for name, (change, error, message) in cases.items():
            with self.subTest(case=name), self.assertRaisesRegex(error, message):
                freeze_draft(self.store, {**self.draft, **change}, self.baseline, lambda: CLOCK)
        with self.assertRaisesRegex(ValueError, "need a baseline"):
            freeze_draft(self.store, self.draft, None, lambda: CLOCK)
        self.assertEqual(self.stored(), 0)

    def test_a_frozen_draft_is_never_restamped(self):
        first = freeze_draft(self.store, self.draft, self.baseline, lambda: CLOCK)
        with self.assertRaisesRegex(ValueError, f"already frozen as {first['hypothesis_id']}"):
            freeze_draft(self.store, self.draft, self.baseline, lambda: CLOCK + timedelta(hours=1))
        self.assertEqual(self.stored(), 1)

    def test_readiness_and_possession_checks_still_apply(self):
        tiny = run_import(self.store, FakeFred(datasets(date(2025, 6, 2), first=date(2025, 5, 16)), date(2025, 6, 3)),
                          date(2025, 6, 3), when(date(2025, 6, 3), 13), start=date(2025, 5, 16))["snapshot_id"]
        with self.assertRaisesRegex(ValueError, "Baseline history is insufficient"):
            freeze_draft(self.store, self.draft, tiny, lambda: CLOCK)
        later = run_import(self.store, FakeFred(datasets(date(2025, 6, 2)), date(2025, 6, 3)), date(2025, 6, 3),
                           when(date(2025, 6, 3), 23))["snapshot_id"]
        with self.assertRaisesRegex(ValueError, "retrieved before the freeze"):
            freeze_draft(self.store, self.draft, later, lambda: CLOCK)
        self.assertEqual(self.stored(), 0)

    def test_the_cli_freezes_at_the_current_time_and_leaves_the_draft_file_untouched(self):
        retrieved = datetime.now(timezone.utc) - timedelta(minutes=5)
        vintage = ny_date(retrieved)
        with tempfile.TemporaryDirectory() as folder:
            path, draft_path = Path(folder) / "store.db", Path(folder) / "draft.json"
            connection = open_store(str(path))
            # Through today: it covers the last session before any publication date up to today (policy B).
            baseline = run_import(connection, FakeFred(datasets(vintage), vintage), vintage, retrieved)["snapshot_id"]
            connection.close()
            published = datetime.now(timezone.utc) - timedelta(hours=1)
            draft_path.write_text(json.dumps(draft_from(cmt_hypothesis(published, published))), encoding="utf-8")
            before = draft_path.read_bytes()
            command = [sys.executable, "-m", "second_order", "freeze-draft", str(draft_path), "--db", str(path),
                       "--baseline", baseline]
            started = datetime.now(timezone.utc)
            frozen = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            result = json.loads(frozen.stdout)
            self.assertLessEqual(started, datetime.fromisoformat(result["frozen_at"]))
            self.assertLessEqual(datetime.fromisoformat(result["frozen_at"]), datetime.now(timezone.utc))
            self.assertEqual(result["recorded_at"], result["frozen_at"])
            again = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn("already frozen", again.stderr)
            self.assertEqual(draft_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
