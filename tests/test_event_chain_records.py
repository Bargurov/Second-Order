import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from second_order import event_chain_records as rec
from second_order.event_chain_records import RecordRefused

SHA = "a" * 64
APPROVAL = "e" * 64
ACCOUNT = {"user_id": "u1", "username": "owner"}
ACQUISITION = {"approval_id": "fcx-approval-1", "attempt": 1, "url": "https://example.com/10k.htm", "folder": "fcx-10k",
               "name": "10k.htm", "sha256": "d" * 64, "bytes": 1200, "retrieved_at": "2026-11-01T09:00:00+00:00"}


def clock():
    return datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def make_current(**changes):
    current = {
        "id": "chain-a", "version": 1, "sha256": SHA,
        "basis": {"chain": {"id": "chain-a", "version": 1, "sha256": SHA}, "evidence_sha256": "b" * 64,
                  "thesis": {"id": "copper", "version": 3, "sha256": "c" * 64},
                  "documents": [{"ref": "fcx:10k-2025", "acquisition": dict(ACQUISITION)}]},
        "target": {"kind": "reason", "id": "r1"}, "state": "available", "reasons": [], "approval_id": APPROVAL,
        "steps": 3, "quotes": ["the mine cut its output by a tenth in the quarter"], "allowed": "10 percent",
    }
    current.update(changes)
    return current


def body(**fields):
    return json.dumps(fields).encode()


def review_body(parent=None, status="approved", notes="Checked step 1.", sha=SHA):
    return body(parent_review_id=parent, chain_sha256=sha, status=status, notes=notes)


def reading_body(parent=None, approval=APPROVAL, short="supports", long="not_sure", line="Plain owner words.",
                 sha=SHA):
    return body(parent_reading_id=parent, chain_sha256=sha, approval_id=approval, short_term=short,
                long_term=long, line=line)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.records = Path(self.tmp.name)
        self.current = make_current()

    def files(self, kind):
        folder = self.records / kind / "chain-a"
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def refusal(self, call, *args):
        with self.assertRaises(RecordRefused) as caught:
            call(self.records, self.current, *args, ACCOUNT, clock)
        return caught.exception

    def test_review_then_reading_append_000001_files_with_basis_and_account(self):
        review = rec.save_review(self.records, self.current, review_body(), ACCOUNT, clock)
        reading = rec.save_reading(self.records, self.current, reading_body(), ACCOUNT, clock)
        self.assertEqual(self.files("reviews"), ["000001.json"])
        self.assertEqual(self.files("readings"), ["000001.json"])
        self.assertEqual(review["basis"], self.current["basis"])
        self.assertEqual(reading["account"], ACCOUNT)
        self.assertEqual(reading["saved_at"], "2026-11-10T09:00:00+00:00")
        self.assertEqual(reading["target"], self.current["target"])
        self.assertEqual(rec.history(self.records, "readings", "chain-a"), [reading])
        raw = (self.records / "reviews" / "chain-a" / "000001.json").read_bytes()
        self.assertNotIn(b"\r", raw)
        extra = json.loads(reading_body())
        extra["target"] = {"kind": "risk", "id": "x"}
        self.assertEqual(self.refusal(rec.save_reading, json.dumps(extra).encode()).status, 422)

    def test_body_fields_exact(self):
        extra = json.loads(review_body())
        extra["more"] = 1
        self.assertEqual(self.refusal(rec.save_review, json.dumps(extra).encode()).status, 422)
        missing = json.loads(review_body())
        del missing["notes"]
        self.assertEqual(self.refusal(rec.save_review, json.dumps(missing).encode()).status, 422)
        self.assertEqual(self.refusal(rec.save_reading, review_body()).status, 422)

    def test_parent_must_be_latest(self):
        first = rec.save_review(self.records, self.current, review_body(), ACCOUNT, clock)
        error = self.refusal(rec.save_review, review_body(notes="Other notes."))
        self.assertEqual((error.status, error.latest), (409, first["review_id"]))
        rec.save_review(self.records, self.current, review_body(parent=first["review_id"], notes="Next."),
                        ACCOUNT, clock)
        self.assertEqual(self.files("reviews"), ["000001.json", "000002.json"])

    def test_chain_sha_must_be_latest(self):
        self.assertEqual(self.refusal(rec.save_review, review_body(sha="f" * 64)).status, 409)
        self.assertEqual(self.files("reviews"), [])

    def test_not_available_refuses(self):
        self.current = make_current(state="evidence_changed", reasons=["a document changed"])
        error = self.refusal(rec.save_review, review_body(status="needs_revision"))
        self.assertEqual(error.status, 409)
        self.assertIn("a document changed", error.message)
        self.assertEqual(self.files("reviews"), [])

    def test_reading_needs_current_approval(self):
        self.assertEqual(self.refusal(rec.save_reading, reading_body(approval="0" * 64)).status, 409)
        self.current = make_current(approval_id=None)
        self.assertEqual(self.refusal(rec.save_reading, reading_body()).status, 409)
        self.assertEqual(self.files("readings"), [])

    def test_text_rules_422(self):
        self.assertEqual(self.refusal(rec.save_reading, reading_body(line="This adds 999 units.")).status, 422)
        self.assertEqual(self.refusal(rec.save_reading, reading_body(short="maybe")).status, 422)
        self.assertEqual(self.refusal(rec.save_review, review_body(notes="x" * 1001)).status, 422)
        self.assertEqual(self.refusal(rec.save_review, review_body(status="done")).status, 422)
        self.assertEqual(self.files("readings") + self.files("reviews"), [])

    def test_identical_reading_refused(self):
        first = rec.save_reading(self.records, self.current, reading_body(), ACCOUNT, clock)
        error = self.refusal(rec.save_reading, reading_body(parent=first["reading_id"]))
        self.assertEqual(error.status, 422)
        rec.save_reading(self.records, self.current, reading_body(parent=first["reading_id"], long="refutes"),
                         ACCOUNT, clock)

    def test_two_saves_with_one_parent_write_one_record(self):
        results = []

        def go(notes):
            try:
                results.append(rec.save_review(self.records, self.current, review_body(notes=notes), ACCOUNT, clock))
            except RecordRefused as error:
                results.append(error)

        threads = [threading.Thread(target=go, args=(n,)) for n in ("First notes.", "Second notes.")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(type(r).__name__ for r in results), ["RecordRefused", "dict"])
        self.assertEqual([r.status for r in results if isinstance(r, RecordRefused)], [409])
        self.assertEqual(self.files("reviews"), ["000001.json"])

    def test_edited_record_makes_history_invalid_and_refuses_saves(self):
        rec.save_reading(self.records, self.current, reading_body(), ACCOUNT, clock)
        path = self.records / "readings" / "chain-a" / "000001.json"
        path.write_bytes(path.read_bytes().replace(b"Plain", b"Plait"))
        with self.assertRaises(RecordRefused) as caught:
            rec.history(self.records, "readings", "chain-a")
        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(self.refusal(rec.save_reading, reading_body(line="Other words.")).status, 500)
        self.assertEqual(self.files("readings"), ["000001.json"])

    def forge(self, kind, number, change):
        """Edit a saved record and recompute its id, as a hand edit that knows the digest would."""
        path = self.records / kind / "chain-a" / f"{number:06d}.json"
        record = json.loads(path.read_bytes())
        change(record)
        record[rec.KINDS[kind]["id"]] = rec.record_id(kind, record)
        path.write_bytes(json.dumps(record).encode("utf-8"))
        return record

    def test_a_forged_record_of_the_wrong_shape_makes_the_history_unverifiable_and_refuses_saves(self):
        forgeries = {
            "notes missing": ("reviews", lambda record: record.pop("notes")),
            "acquisition sha256 a number": ("reviews", lambda record: record["basis"]["documents"][0]["acquisition"]
                                            .update(sha256=5)),
            "acquisition field missing": ("reviews", lambda record: record["basis"]["documents"][0]["acquisition"]
                                          .pop("url")),
            "document ref not a reference": ("reviews", lambda record: record["basis"]["documents"][0]
                                             .update(ref="doc1")),
            "no documents": ("reviews", lambda record: record["basis"].update(documents=[])),
            "chain version a string": ("reviews", lambda record: record["basis"]["chain"].update(version="1")),
            "thesis of another id": ("reviews", lambda record: record["basis"]["thesis"].update(id="lithium")),
            "account without a name": ("reviews", lambda record: record["account"].pop("username")),
            "an extra field": ("reviews", lambda record: record.update(extra=1)),
            "sequence a boolean": ("reviews", lambda record: record.update(sequence=True)),
            "approval not a review id": ("readings", lambda record: record.update(approval_id="appr1")),
            "target a string": ("readings", lambda record: record.update(target="r1")),
            "judgment unknown": ("readings", lambda record: record.update(short_term="maybe")),
            "line a number": ("readings", lambda record: record.update(line=5)),
        }
        for name, (kind, change) in forgeries.items():
            with self.subTest(name):
                self.tmp.cleanup()
                self.records.mkdir(parents=True)
                save = rec.save_review if kind == "reviews" else rec.save_reading
                first = save(self.records, self.current, review_body() if kind == "reviews" else reading_body(),
                             ACCOUNT, clock)
                forged = self.forge(kind, 1, change)
                with self.assertRaises(RecordRefused) as caught:
                    rec.history(self.records, kind, "chain-a")
                self.assertEqual(caught.exception.status, 500)
                self.assertIn("cannot be verified", caught.exception.message)
                next_body = (review_body(parent=forged["review_id"], notes="Next.") if kind == "reviews"
                             else reading_body(parent=forged["reading_id"], long="refutes"))
                error = self.refusal(save, next_body)
                self.assertEqual(error.status, 500)
                self.assertIn("cannot be verified", error.message)
                self.assertEqual(self.files(kind), ["000001.json"])
                self.assertNotEqual(forged[rec.KINDS[kind]["id"]], first[rec.KINDS[kind]["id"]])

    def test_a_record_on_a_version_after_the_latest_makes_the_history_unverifiable(self):
        rec.save_review(self.records, self.current, review_body(), ACCOUNT, clock)
        forged = self.forge("reviews", 1, lambda record: record["basis"]["chain"].update(version=2))
        self.assertEqual(len(rec.history(self.records, "reviews", "chain-a")), 1)  # Without the version count.
        with self.assertRaises(RecordRefused) as caught:
            rec.history(self.records, "reviews", "chain-a", versions=1)
        self.assertEqual(caught.exception.status, 500)
        self.assertIn("version 2", caught.exception.message)
        error = self.refusal(rec.save_review, review_body(parent=forged["review_id"], notes="Next."))
        self.assertEqual((error.status, self.files("reviews")), (500, ["000001.json"]))

    def test_stray_tmp_file_is_ignored_but_a_gap_is_invalid(self):
        rec.save_review(self.records, self.current, review_body(), ACCOUNT, clock)
        folder = self.records / "reviews" / "chain-a"
        (folder / ".tmp-abc").write_bytes(b"partial")
        self.assertEqual(len(rec.history(self.records, "reviews", "chain-a")), 1)
        (folder / "000003.json").write_bytes(b"{}")
        with self.assertRaises(RecordRefused) as caught:
            rec.history(self.records, "reviews", "chain-a")
        self.assertEqual(caught.exception.status, 500)


if __name__ == "__main__":
    unittest.main()
