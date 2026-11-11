"""The hand-run pilot drill (tests/pilot_drill.py): a SYNTHETIC practice of one FOMC pilot case in a folder of its own.

The drill's app is driven here through the routes the owner's browser uses, on the drill's simulated clock: import the
kept baseline, preview, freeze as fomc-2026-12-09, download the outcome from the fake Board server, import it, preview
and approve the assessment, and read the pilot journal on the drill's copy of the settings. Every database the app opens
lies below the drill folder, no socket is opened, and the approved settings file is only read."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit
from urllib.request import url2pathname

from fastapi.testclient import TestClient

import pilot_drill
from integration_controls import Clock
from test_lifecycle_freeze import BASE, LIFECYCLE, tree
from test_pilot_rehearsal import pilot_form

ROOT = Path(__file__).resolve().parent.parent
APPROVED = ROOT / "content" / "pilot" / "fomc-pilot.json"
UTC = timezone.utc


def drill_form() -> dict:
    return pilot_form(story_id="fomc-2026-12-09",
                      headline="SYNTHETIC drill: FOMC statement of 9 December 2026 (practice, not a real case)")


def opened_file(name: str) -> Path:
    """The file a sqlite3 connection was given: a path, or a read-only URI (file:///C:/...?mode=ro on Windows,
    file:///tmp/...?mode=ro elsewhere) turned back into a path by the platform's own rule."""
    return Path(url2pathname(urlsplit(name).path)) if name.startswith("file:") else Path(name)


class OpenedFileTests(unittest.TestCase):
    def test_a_read_only_uri_names_the_file_store_opens_on_this_platform(self):
        """store.py opens f"{path.resolve().as_uri()}?mode=ro"; that URI turns back into the same path, so the isolation
        check below compares files, not spellings. Nothing is written."""
        path = Path(tempfile.gettempdir()).resolve() / "second-order drill ü" / "research.db"
        self.assertEqual(opened_file(f"{path.as_uri()}?mode=ro"), path)
        self.assertEqual(opened_file(str(path)), path)
        self.assertFalse(opened_file(f"{path.as_uri()}?mode=ro").is_relative_to(path.parent.parent / "drill"))


class Folder(unittest.TestCase):
    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix="second-order-drill-test-"))
        self.addCleanup(pilot_drill.delete_tree, self.parent)
        self.root = self.parent / "drill"


class PrepareTests(Folder):
    def test_prepare_writes_only_below_the_drill_folder_and_copies_the_approved_settings(self):
        approved = (APPROVED.read_bytes(), APPROVED.stat().st_mtime_ns)
        content, had_data = tree(ROOT / "content"), (ROOT / "data").exists()
        pilot_drill.prepare(self.root)
        self.assertEqual((APPROVED.read_bytes(), APPROVED.stat().st_mtime_ns), approved)
        self.assertEqual(tree(ROOT / "content"), content)
        self.assertEqual((ROOT / "data").exists(), had_data)
        self.assertEqual((self.root / "pilot" / "fomc-pilot.json").read_bytes(), approved[0])
        state = json.loads((self.root / "drill.json").read_text(encoding="utf-8"))
        self.assertTrue(state["label"].startswith("SYNTHETIC"))
        self.assertEqual(state["now"], "2026-12-09T21:35:00+00:00")  # 4:35 p.m. in New York, 11:35 p.m. in Israel

    def test_the_kept_baseline_is_synthetic_validated_and_from_the_statement_night(self):
        pilot_drill.prepare(self.root)
        [folder] = list((self.root / "market-store" / "packages").iterdir())
        record = json.loads((folder / "acquisition.json").read_text(encoding="utf-8"))
        self.assertIn("SYNTHETIC", record["acquisition_method"])
        self.assertEqual(record["requested_at"], "2026-12-09T21:30:00.000000+00:00")
        [validation] = [json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("validation-*.json")]
        self.assertEqual(validation["status"], "accepted")

    def test_a_folder_that_is_not_new_or_lies_in_a_checkout_is_refused(self):
        self.root.mkdir()
        (self.root / "something.txt").write_text("kept", encoding="utf-8")
        with self.assertRaisesRegex(pilot_drill.DrillRefused, "new or empty"):
            pilot_drill.prepare(self.root)
        with self.assertRaisesRegex(pilot_drill.DrillRefused, "outside every checkout"):
            pilot_drill.prepare(ROOT / "drill-inside-the-checkout")
        self.assertFalse((ROOT / "drill-inside-the-checkout").exists())

    def test_port_8000_is_refused(self):
        for ports in ((8000, 8766), (8765, 8000), (8765, 8765)):
            with self.assertRaises(pilot_drill.DrillRefused):
                pilot_drill.check_ports(*ports)
        pilot_drill.check_ports(8765, 8766)

    def test_the_named_steps_and_moving_the_clock_while_stopped(self):
        self.assertEqual(pilot_drill.STEPS["night"], datetime(2026, 12, 9, 21, 35, tzinfo=UTC))
        self.assertEqual(pilot_drill.STEPS["outcome-early"], datetime(2026, 12, 18, 20, tzinfo=UTC))
        self.assertEqual(pilot_drill.STEPS["outcome"], datetime(2026, 12, 18, 21, 35, tzinfo=UTC))
        pilot_drill.prepare(self.root)
        moved = pilot_drill.move_clock(self.root, "outcome")
        self.assertEqual(moved["now"], "2026-12-18T21:35:00+00:00")
        self.assertIn("16:35 New York", moved["text"])
        self.assertIn("23:35 Israel", moved["text"])
        self.assertEqual(json.loads((self.root / "drill.json").read_text(encoding="utf-8"))["now"],
                         "2026-12-18T21:35:00+00:00")

    def test_remove_deletes_only_a_drill_folder(self):
        other = self.parent / "other"
        other.mkdir()
        (other / "drill.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(pilot_drill.DrillRefused):
            pilot_drill.remove(other)
        self.assertTrue(other.exists())
        pilot_drill.prepare(self.root)
        pilot_drill.remove(self.root)
        self.assertFalse(self.root.exists())


class InstructionsTests(unittest.TestCase):
    def test_the_hebrew_steps_name_the_drills_own_commands_and_never_the_active_store(self):
        text = (ROOT / "docs" / "pilot" / "fomc-pilot-drill.he.md").read_text(encoding="utf-8")
        for command in ("python tests/pilot_drill.py start", "python tests/pilot_drill.py ledger",
                        "python tests/pilot_drill.py remove", *(f"python tests/pilot_drill.py clock {step}"
                                                               for step in ("outcome-early", "outcome"))):
            self.assertIn(command, text)
        self.assertIn(f"127.0.0.1:{pilot_drill.PORT}", text)
        self.assertIn("fomc-2026-12-09", text)
        self.assertNotIn("data/real", text)
        self.assertNotIn("--db", text)


class WholeCaseTests(Folder):
    def setUp(self):
        super().setUp()
        pilot_drill.prepare(self.root)
        self.clock = Clock(pilot_drill.STEPS["night"])
        self.clock.set(pilot_drill.STEPS["night"], frozen=True)
        self.opened: list[str] = []
        connect = sqlite3.connect

        def recorded(path, *args, **kwargs):
            self.opened.append(str(path))
            return connect(path, *args, **kwargs)

        def no_network(*args, **kwargs):
            raise AssertionError("the drill opened a network connection")

        for patcher in (mock.patch("sqlite3.connect", recorded),
                        mock.patch.object(socket, "create_connection", no_network)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.release = pilot_drill.fake_board(self.clock)
        self.client = TestClient(pilot_drill.app(self.root, self.clock, self.release.fetcher(), static=None),
                                 base_url=BASE)
        self.addCleanup(self.client.close)

    def post(self, path: str, body: dict, expect: int) -> dict:
        response = self.client.post(path, headers=LIFECYCLE, content=json.dumps(body))
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def at(self, step: str) -> None:
        self.clock.set(pilot_drill.STEPS[step], frozen=True)

    def ledger_row(self) -> dict:
        result = pilot_drill.ledger(self.root, self.clock())
        return next(row for row in result["statements"] if row["date"] == "2026-12-09")

    def test_one_synthetic_case_from_the_kept_baseline_to_the_assessment(self):
        readiness = self.client.get("/api/lifecycle/readiness", params={"published": "2026-12-09"}).json()
        board = next(item for item in readiness["providers"] if item["provider"] == "board-h15")
        self.assertEqual(board["status"], "needs_baseline")
        [package] = [p.name for p in (self.root / "market-store" / "packages").iterdir()]
        baseline = self.post("/api/lifecycle/baselines", {"package_id": package, "start": "2025-01-02"}, 201)
        readiness = self.client.get("/api/lifecycle/readiness", params={"published": "2026-12-09"}).json()
        board = next(item for item in readiness["providers"] if item["provider"] == "board-h15")
        self.assertEqual(board["status"], "freeze_ready")
        inputs = {"origin": "manual", "manual": drill_form(), "draft_id": None,
                  "baseline_snapshot_id": baseline["snapshot"]["snapshot_id"]}
        shown = self.post("/api/lifecycle/preview", {"inputs": inputs}, 200)
        self.assertEqual((shown["freezable"], shown["blockers"]), (True, []))
        self.assertEqual(shown["freshness"]["required_session"], "2026-12-08")
        self.assertEqual(shown["scoring"]["expected_score_anchor"], "2026-12-10")
        frozen = self.post("/api/lifecycle/freezes", {
            "inputs": inputs, "preview_sha256": shown["preview_sha256"], "approve_freeze": True,
            "previewed_binding": shown["binding"]}, 201)
        hypothesis = frozen["hypothesis_id"]
        row = self.ledger_row()
        self.assertEqual((row["state"], row["case"]), ("pending", hypothesis))

        self.at("outcome-early")  # Friday 3 p.m. in New York: the target, the 17th, is not posted until 4:15 p.m.
        waiting = self.post("/api/lifecycle/retrieval-preview", {"hypotheses": [hypothesis]}, 200)
        self.assertEqual(waiting["awaiting_release"], [{"session": "2026-12-17",
                                                        "obtainable_from": "2026-12-18 16:15 New York time"}])
        self.assertEqual(self.release.calls, [])

        self.at("outcome")
        plan = self.post("/api/lifecycle/retrieval-preview", {"hypotheses": [hypothesis]}, 200)
        self.assertEqual(plan["requests"], 1)
        sent = self.post("/api/lifecycle/retrievals", {"plan_sha256": plan["plan_sha256"], "hypotheses": [hypothesis],
                                                       "attempt": plan["next_attempt"]}, 201)
        self.assertEqual((sent["outcome"], sent["validation"]), ("saved", "accepted"))
        self.assertEqual(len(self.release.calls), 1)
        outcome = self.post("/api/lifecycle/outcome-imports", {"hypothesis_id": hypothesis,
                                                               "package_id": sent["package_id"]}, 201)
        previewed = self.post("/api/lifecycle/assessment-preview", {"inputs": {
            "hypothesis_id": hypothesis, "outcome_snapshot_id": outcome["snapshot"]["snapshot_id"]}}, 200)
        self.assertTrue(previewed["assessable"], previewed["blockers"])
        bound = previewed["binding"]
        self.post("/api/lifecycle/assessments", {
            "inputs": {"hypothesis_id": hypothesis, "outcome_snapshot_id": bound["outcome_snapshot_id"]},
            "preview_sha256": previewed["preview_sha256"], "approve_assessment": True,
            "reassessment": bound["reassessment"], "previewed_binding": bound}, 201)
        self.assertEqual(self.ledger_row()["state"], "assessed")

        drill = self.root.resolve()
        self.assertTrue(self.opened)
        for path in self.opened:  # A read-only connection names its file as a URI (see opened_file).
            self.assertTrue(path == ":memory:" or opened_file(path).resolve().is_relative_to(drill), path)

    def test_a_download_before_the_friday_release_lacks_the_target_as_the_boards_would(self):
        """The fake Board server keeps the posting time: at 3 p.m. New York on the 18th the 17th is not posted yet."""
        [package] = [p.name for p in (self.root / "market-store" / "packages").iterdir()]
        baseline = self.post("/api/lifecycle/baselines", {"package_id": package, "start": "2025-01-02"}, 201)
        inputs = {"origin": "manual", "manual": drill_form(), "draft_id": None,
                  "baseline_snapshot_id": baseline["snapshot"]["snapshot_id"]}
        shown = self.post("/api/lifecycle/preview", {"inputs": inputs}, 200)
        hypothesis = self.post("/api/lifecycle/freezes", {
            "inputs": inputs, "preview_sha256": shown["preview_sha256"], "approve_freeze": True,
            "previewed_binding": shown["binding"]}, 201)["hypothesis_id"]
        self.at("outcome-early")
        plan = self.post("/api/lifecycle/retrieval-preview", {"hypotheses": [hypothesis]}, 200)
        sent = self.post("/api/lifecycle/retrievals", {"plan_sha256": plan["plan_sha256"], "hypotheses": [hypothesis],
                                                       "attempt": plan["next_attempt"]}, 201)
        self.post("/api/lifecycle/outcome-imports", {"hypothesis_id": hypothesis, "package_id": sent["package_id"]},
                  201)
        state = self.client.get(f"/api/lifecycle/hypotheses/{hypothesis}/readiness").json()["state"]
        self.assertEqual(state, "outcome_missing")
        self.at("outcome")  # After 4:15 p.m. the plan asks for one more download, for the 17th.
        again = self.post("/api/lifecycle/retrieval-preview", {"hypotheses": [hypothesis]}, 200)
        self.assertEqual((again["requests"], again["missing_sessions"]), (1, ["2026-12-17"]))

    def test_the_ledger_reads_the_drill_copy_at_the_simulated_time(self):
        result = pilot_drill.ledger(self.root, self.clock())
        self.assertEqual(result["phase"]["phase"], "running")
        self.assertEqual(self.ledger_row()["state"], "open")  # the statement night, New York date
        self.assertIn("SYNTHETIC pilot drill", pilot_drill.ledger_text(self.root, self.clock()))


if __name__ == "__main__":
    unittest.main()
