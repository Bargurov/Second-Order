import tempfile
import unittest
from datetime import date
from fractions import Fraction
from pathlib import Path

from second_order import fuels_snapshots


def payload(retrieved="2026-11-06T14:00:00+00:00", value="80.00"):
    return {
        "snapshot_version": fuels_snapshots.SNAPSHOT_VERSION,
        "semantics": fuels_snapshots.SEMANTICS,
        "retrieved_at": retrieved,
        "series": {"SYNTHETIC": {"release_dates": ["2026-11-04"], "observations": [["2026-10-29", value], ["2026-10-30", None]]}},
    }


class FuelsSnapshotsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name) / "snapshots"

    def test_write_once_and_read_back(self):
        first = fuels_snapshots.write(self.folder, payload())
        self.assertTrue(first[1])
        self.assertEqual(fuels_snapshots.write(self.folder, payload()), (first[0], False))
        loaded = fuels_snapshots.load_all(self.folder)
        self.assertEqual((loaded["state"], [s["snapshot_id"] for s in loaded["snapshots"]]), ("verified", [first[0]]))
        self.assertIsNone(loaded["problem"])

    def test_an_edited_file_withholds_everything(self):
        good = fuels_snapshots.write(self.folder, payload())[0]
        other = fuels_snapshots.write(self.folder, payload(value="81.00"))[0]
        path = self.folder / f"{other}.json"
        path.write_bytes(path.read_bytes().replace(b"81.00", b"99.00"))
        loaded = fuels_snapshots.load_all(self.folder)
        self.assertEqual((loaded["state"], loaded["snapshots"]), ("changed", []))
        self.assertIn(other[:12], loaded["problem"])
        self.assertNotIn("99.00", loaded["problem"])
        self.assertNotIn(good[:12], loaded["problem"])

    def test_a_badly_named_or_wrong_version_file_is_changed(self):
        fuels_snapshots.write(self.folder, payload())
        (self.folder / "notes.json").write_text("{}", encoding="utf-8")
        self.assertEqual(fuels_snapshots.load_all(self.folder)["state"], "changed")
        (self.folder / "notes.json").unlink()
        old = payload()
        old["snapshot_version"] = "fuels-snapshot-0.0"
        fuels_snapshots.write(self.folder, old)
        loaded = fuels_snapshots.load_all(self.folder)
        self.assertEqual((loaded["state"], loaded["snapshots"]), ("changed", []))

    def test_no_folder_is_missing(self):
        self.assertEqual(fuels_snapshots.load_all(None)["state"], "missing")
        self.assertIn("fuels refresh", fuels_snapshots.load_all(self.folder / "absent")["problem"])
        self.folder.mkdir()
        self.assertEqual(fuels_snapshots.load_all(self.folder)["state"], "missing")

    def test_same_retrieval_time_orders_by_id(self):
        ids = [fuels_snapshots.write(self.folder, payload(value=f"8{n}.00"))[0] for n in range(4)]
        later = fuels_snapshots.write(self.folder, payload(retrieved="2026-11-07T00:00:00+00:00"))[0]
        earlier = fuels_snapshots.write(self.folder, payload(retrieved="2026-11-05T00:00:00+00:00"))[0]
        expected = [earlier, *sorted(ids), later]
        for _ in range(2):
            got = [s["snapshot_id"] for s in fuels_snapshots.load_all(self.folder)["snapshots"]]
            self.assertEqual(got, expected)

    def test_an_interrupted_write_is_ignored(self):
        first = fuels_snapshots.write(self.folder, payload())[0]
        (self.folder / ("a" * 64 + ".json.tmp")).write_bytes(b"{half")
        self.assertEqual(fuels_snapshots.load_all(self.folder)["state"], "verified")
        second = fuels_snapshots.write(self.folder, payload(value="82.00"))
        self.assertTrue(second[1])
        self.assertEqual(len(fuels_snapshots.load_all(self.folder)["snapshots"]), 2)
        self.assertNotEqual(first, second[0])

    def test_an_observation_days_before_its_release_is_published_at_that_release(self):
        entry = {"release_dates": ["2026-10-28", "2026-11-04"], "observations": [["2026-10-29", "80.00"], ["2026-10-30", None]]}
        self.assertEqual(fuels_snapshots.published_on(entry, date(2026, 10, 29)), date(2026, 11, 4))
        self.assertIsNone(fuels_snapshots.published_on(entry, date(2026, 11, 5)))
        self.assertEqual(fuels_snapshots.values(entry), {date(2026, 10, 29): Fraction("80.00"), date(2026, 10, 30): None})

    def test_an_observation_on_a_release_day_is_published_at_the_next_release(self):
        """A release carries data through the days before it, so a price observed on a release day is not in it."""
        entry = {"release_dates": ["2026-10-28", "2026-11-04"], "observations": [["2026-10-28", "80.00"]]}
        self.assertEqual(fuels_snapshots.published_on(entry, date(2026, 10, 28)), date(2026, 11, 4))
        self.assertIsNone(fuels_snapshots.published_on(entry, date(2026, 11, 4)))

    def test_an_entry_that_lists_no_release_has_no_publication_date(self):
        """EIA's API gives no publication date, so an EIA entry lists no release and none is inferred."""
        entry = {"release_dates": [], "observations": [["2026-10-29", "80.00"]]}
        self.assertIsNone(fuels_snapshots.published_on(entry, date(2026, 10, 29)))
        self.assertIn("never inferred", fuels_snapshots.SEMANTICS["eia_publication_date"])

    def test_semantics_keeps_the_dates_and_the_history_apart(self):
        self.assertEqual(set(fuels_snapshots.SEMANTICS),
                         {"observation_date", "eia_publication_date", "retrieved_at", "history"})
        self.assertIn("not a record of what was known", fuels_snapshots.SEMANTICS["history"])

    def test_a_fred_snapshot_written_before_the_move_still_verifies_and_is_never_rewritten(self):
        import fuels_fakes
        snapshot_id = fuels_fakes.write_fred_snapshot(self.folder)
        path = self.folder / f"{snapshot_id}.json"
        before = path.read_bytes()
        newer = fuels_snapshots.write(self.folder, payload(retrieved="2026-11-07T00:00:00+00:00"))[0]
        loaded = fuels_snapshots.load_all(self.folder)
        self.assertEqual((loaded["state"], [s["snapshot_id"] for s in loaded["snapshots"]]),
                         ("verified", [snapshot_id, newer]))
        self.assertEqual(fuels_snapshots.retrieved_on(loaded["snapshots"][0]), "2026-11-05")  # its vintage date
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
