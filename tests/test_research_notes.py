"""The owner's research notes (research_notes): append-only records, their save rules and the verified history. Every
text here is a marked test value, never a view of the owner's."""
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from second_order import research_notes as notes
from second_order.event_chain_records import RecordRefused

SHA = "a" * 64
ACCOUNT = {"user_id": "u1", "username": "owner"}
ACQUISITION = {"approval_id": "fcx-approval-1", "attempt": 1, "url": "https://example.com/10k.htm", "folder": "fcx-10k",
               "name": "10k.htm", "sha256": "d" * 64, "bytes": 1200, "retrieved_at": "2026-11-01T09:00:00+00:00"}
QUOTE = "the mine cut its output by a tenth in the quarter"
ABOUT = {"kind": "comparison", "id": "annual-to-quarter"}
NOW = datetime(2026, 11, 10, 22, 30, tzinfo=timezone.utc)


def clock():
    return NOW


def make_subject(**changes) -> dict:
    subject = {"kind": "comparison", "id": "annual-to-quarter", "sha256": SHA,
               "basis": {"comparison": {"id": "annual-to-quarter", "version": 1, "sha256": SHA},
                         "evidence_sha256": "b" * 64,
                         "documents": [{"ref": "fcx:10k-2025", "acquisition": dict(ACQUISITION)}]},
               "state": "available", "reasons": [], "quotes": [QUOTE]}
    subject.update(changes)
    return subject


def request(**changes) -> bytes:
    fields = {"parent_note_id": None, "about": dict(ABOUT), "subject_sha256": SHA, "follows": None,
              "text": "TEST VALUE: a note in the owner's place.", "expectation": None, "question": None}
    fields.update(changes)
    return json.dumps(fields).encode("utf-8")


class Notes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "notes"
        self.subject = make_subject()

    def save(self, **changes) -> dict:
        return notes.save(self.folder, self.subject, notes.parse(request(**changes)), ACCOUNT, clock)

    def refusal(self, **changes) -> RecordRefused:
        with self.assertRaises(RecordRefused) as caught:
            self.save(**changes)
        return caught.exception

    def files(self) -> list[str]:
        return sorted(path.name for path in self.folder.iterdir()) if self.folder.is_dir() else []


class Saving(Notes):
    def test_a_note_is_one_new_file_with_the_servers_time_the_account_and_the_basis(self):
        record = self.save(expectation={"text": "TEST VALUE: prices will rise by year end.", "check_by": "2027-02-28"},
                           question="TEST VALUE: what does the next annual report say?")
        self.assertEqual(self.files(), ["000001.json"])
        self.assertEqual(json.loads((self.folder / "000001.json").read_bytes().decode("utf-8")), record)
        self.assertEqual((record["sequence"], record["parent_note_id"], record["saved_at"]),
                         (1, None, "2026-11-10T22:30:00+00:00"))
        self.assertEqual((record["account"], record["about"], record["basis"]),
                         (ACCOUNT, ABOUT, self.subject["basis"]))
        self.assertEqual(record["note_id"], notes.note_id(record))
        # The owner's own words hold a view on a price's direction: no word list applies to them.
        self.assertEqual(record["expectation"], {"text": "TEST VALUE: prices will rise by year end.",
                                                 "check_by": "2027-02-28"})
        second = self.save(parent_note_id=record["note_id"], follows=record["note_id"])
        self.assertEqual((second["sequence"], second["parent_note_id"], second["follows"]),
                         (2, record["note_id"], record["note_id"]))
        self.assertEqual(self.files(), ["000001.json", "000002.json"])
        self.assertEqual([item["note_id"] for item in notes.history(self.folder)],
                         [record["note_id"], second["note_id"]])

    def test_the_saving_time_is_never_taken_from_the_request(self):
        body = json.loads(request())
        body["saved_at"] = "2026-01-01T00:00:00+00:00"
        with self.assertRaises(RecordRefused) as caught:
            notes.parse(json.dumps(body).encode("utf-8"))
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(self.files(), [])

    def test_a_check_by_date_is_a_real_day_not_before_the_saving_day(self):
        for check_by in ("2026-11-09", "2026-02-30", "soon", 20270101):
            error = self.refusal(expectation={"text": "TEST VALUE.", "check_by": check_by})
            self.assertEqual(error.status, 422)
            self.assertIn("check-by date", error.message)
        self.save(expectation={"text": "TEST VALUE.", "check_by": "2026-11-10"})
        self.assertEqual(self.files(), ["000001.json"])

    def test_409_for_a_stale_parent_a_changed_subject_and_a_subject_not_available(self):
        first = self.save()
        stale = self.refusal(parent_note_id=None)
        self.assertEqual((stale.status, stale.latest), (409, first["note_id"]))
        changed = self.refusal(parent_note_id=first["note_id"], subject_sha256="0" * 64)
        self.assertEqual((changed.status, changed.latest), (409, first["note_id"]))
        self.subject = make_subject(state="needs_revalidation", reasons=["The document fcx:10k-2025 differs"])
        closed = self.refusal(parent_note_id=first["note_id"])
        self.assertEqual(closed.status, 409)
        self.assertIn("The document fcx:10k-2025 differs", closed.message)
        self.assertEqual(self.files(), ["000001.json"])

    def test_text_rules_422(self):
        cases = {
            "the note must be 1 to 2000 characters": {"text": "x" * 2001},
            "the note must be text": {"text": 7},
            "the note repeats 6 words of a source": {"text": "TEST VALUE: " + QUOTE},
            "the note holds the digit": {"text": "TEST VALUE: see ٠3"},
            "the expectation must be 1 to 500 characters": {"expectation": {"text": "", "check_by": None}},
            "the expectation must be null": {"expectation": {"text": "TEST VALUE."}},
            "the question must be 1 to 280 characters": {"question": "x" * 281},
            "follows must name an earlier note about the same subject": {"follows": "f" * 64},
        }
        for message, changes in cases.items():
            with self.subTest(message=message):
                error = self.refusal(**changes)
                self.assertEqual(error.status, 422)
                self.assertIn(message, error.message)
        self.assertEqual(self.files(), [])

    def test_a_followed_note_must_be_about_the_same_subject(self):
        first = self.save()
        self.subject = make_subject(kind="thesis", id="copper", basis={
            "thesis": {"id": "copper", "version": 1, "sha256": SHA},
            "documents": [{"ref": "fcx:10k-2025", "acquisition": dict(ACQUISITION)}]})
        error = self.refusal(parent_note_id=first["note_id"], about={"kind": "thesis", "id": "copper"},
                             follows=first["note_id"])
        self.assertEqual(error.status, 422)

    def test_the_request_is_exact(self):
        for body in (b"[]", b"{", request()[:-1] + b', "extra": 1}',
                     request(about={"kind": "company", "id": "fcx"}), request(about={"kind": "chain", "id": "A B"})):
            with self.subTest(body=body[:30]), self.assertRaises(RecordRefused) as caught:
                notes.parse(body)
            self.assertEqual(caught.exception.status, 422)

    def test_two_saves_with_one_parent_write_one_record(self):
        results = []

        def go(text):
            try:
                results.append(self.save(text=text))
            except RecordRefused as error:
                results.append(error)

        threads = [threading.Thread(target=go, args=(f"TEST VALUE {n}.",)) for n in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        saved = [item for item in results if isinstance(item, dict)]
        refused = [item for item in results if isinstance(item, RecordRefused)]
        self.assertEqual((len(saved), len(refused)), (1, 1))
        self.assertEqual((refused[0].status, refused[0].latest), (409, saved[0]["note_id"]))
        self.assertEqual(self.files(), ["000001.json"])


class History(Notes):
    def rewrite(self, name: str, change) -> None:
        path = self.folder / name
        record = json.loads(path.read_bytes().decode("utf-8"))
        change(record)
        path.write_bytes((json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"))

    def test_an_edited_note_a_gap_and_a_forged_shape_refuse_reads_and_saves(self):
        first = self.save()
        self.save(parent_note_id=first["note_id"])
        original = (self.folder / "000002.json").read_bytes()
        self.rewrite("000002.json", lambda record: record.update(text="TEST VALUE: edited later."))
        self.assertEqual(self.refusal_of_history().status, 500)
        self.assertEqual(self.refusal(parent_note_id="x").status, 500)

        def forged(record):  # A record with a valid id but a field this version does not write.
            record["saved_on"] = "2026-01-01"
            record["note_id"] = notes.note_id(record)

        (self.folder / "000002.json").write_bytes(original)
        self.rewrite("000002.json", forged)
        self.assertIn("cannot be verified", self.refusal_of_history().message)
        (self.folder / "000002.json").write_bytes(original)
        (self.folder / "000004.json").write_bytes(original)
        self.assertIn("unexpected file", self.refusal_of_history().message)

    def test_a_hand_edited_note_with_a_valid_id_but_an_unreadable_form_is_unverifiable(self):
        """The page's reader refuses a whole reply over an empty text or a time it cannot read, so such a file must
        make the history unverifiable here, where the page shows it as that."""
        self.save(expectation={"text": "TEST VALUE.", "check_by": None}, question="TEST VALUE?")
        original = (self.folder / "000001.json").read_bytes()
        changes = (lambda record: record.update(saved_at="yesterday"),
                   lambda record: record.update(saved_at="2026-11-10T09:00:00"),  # No offset.
                   lambda record: record.update(text="  "),
                   lambda record: record.update(question=""),
                   lambda record: record["expectation"].update(text=""))
        for change in changes:
            def forged(record, change=change):
                change(record)
                record["note_id"] = notes.note_id(record)
            (self.folder / "000001.json").write_bytes(original)
            self.rewrite("000001.json", forged)
            self.assertIn("cannot be verified", self.refusal_of_history().message)

    def test_a_stray_file_is_reported_without_its_name(self):
        self.save()
        (self.folder / "→ anything.json").write_bytes(b"{}")
        message = self.refusal_of_history().message
        self.assertIn("unexpected file", message)
        self.assertNotIn("→", message)
        self.assertNotIn("anything", message)

    def test_a_save_that_loses_the_race_for_the_file_is_409_with_the_note_that_won(self):
        """Two saves that both passed the parent check: the file is created exclusively, so the second is refused."""
        from unittest import mock
        first = self.save()
        real = notes.history
        calls = []

        def stale_then_real(folder):  # The first read is the one a racing save made before the other wrote.
            calls.append(folder)
            return [] if len(calls) == 1 else real(folder)

        with mock.patch.object(notes, "history", side_effect=stale_then_real):
            error = self.refusal(text="TEST VALUE: the save that lost the race.")
        self.assertEqual((error.status, error.latest), (409, first["note_id"]))
        self.assertIn("at the same time", error.message)
        self.assertEqual(self.files(), ["000001.json"])
        self.assertEqual(json.loads((self.folder / "000001.json").read_bytes().decode("utf-8")), first)

    def refusal_of_history(self) -> RecordRefused:
        with self.assertRaises(RecordRefused) as caught:
            notes.history(self.folder)
        return caught.exception


if __name__ == "__main__":
    unittest.main()
