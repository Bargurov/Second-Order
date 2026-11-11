"""QA checks around the QA-7 repair (Admin): the source route's refusals write nothing, and valid sources still count
atomically. Written by the QA chat; SYNTHETIC accounts, limits, feeds (news_fakes) and pages; nothing reaches a
network and no provider is called.

The original QA-7 assertion stays where it was written (test_qa_entry_audit, RefusalsWriteNothing.
test_refused_source_forms_write_nothing, nine refused source values). These checks add what a repair must also keep:

- QA-7, a further subcase found on 15 October while preparing the verification: the same source sent again at the same
  instant (a double submission) is refused 422 invalid_source ("already in your sources"), and on 88e50c6 that refusal
  appends a usage event and its release row. docs/admin-user-contract.md section 9: a refusal below 500 reserved, sent
  and wrote nothing.
- Admin's correction f99490e checks every rule of the capture before reserving: the nine original subcases and this one
  pass unchanged there, and putting the reservation back before the check fails the nine again. Admin names one
  remaining case: a capture found to exist only by the write itself (the same text from another account or the
  operator's form at the same clock instant, between the check and the write) still leaves an event and its release.
- Valid sources sent at once at the daily limit pass exactly up to the limit, with refused invalid ones among them.
- Valid sources sent at once never hold more than the storage limit (the check and the write stay one step).
- A saved source writes one counted usage event, its capture and its owner row, and nothing is released.
- An import confirmation refused at the storage or the daily source limit writes nothing (its claim is gone) and requests
  nothing, and the same preview confirms once the limit allows it.

The write-time collision Admin disclosed with f99490e (CURRENT_DELIVERY_20261015) is reproduced deterministically below:
reader-b, or the operator's intake form, saves the identical source (same text, same clock instant, so the same capture
ID) after reader-a's request has passed its checks and before reader-a's own write. The first capture write waits at
event_intake.save until the other writer has finished; nothing else in the product is replaced. Whoever writes first
keeps the capture; the other is refused, and a refusal still writes nothing (docs/admin-user-contract.md section 9): no
usage event or release row, no owner row and no file. On f99490e reader-a's refusal leaves its event and release rows,
so these two failed there. If a correction serializes the writers so that the other cannot finish inside that gap, the
hook stops waiting after a few seconds, reader-a writes first, and the same rule applies to the other writer's refusal.
The operator's route captures at the wall clock; here it is given the server's injected clock so both writers capture
at one instant.

Verified on Admin's 9a42481 (15 October 2026), which writes the capture inside the reservation's own accounts-store
transaction and rolls the count back when the write refuses: both pass. reader-b now waits on the store while reader-a
writes (the serialized branch: reader-a 201 with one event, reader-b 422 with no row); the operator's form, which does
not use the store, still gets inside the gap and reader-a's 422 invalid_source leaves no event, release, owner row or
file. Writing after the transaction commits (the f99490e shape) fails both again; release rows now carry the server's
clock.
"""
from concurrent.futures import ThreadPoolExecutor
import contextlib
import difflib
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

import httpx

from account_fakes import BASE, USAGE_POLICY, USER_WRITE, World, every_file, source_form
from news_fakes import Pages, fed_link, fed_page, refreshed
from second_order import analysis_flow, event_intake, publication_import, usage

INTAKE_WRITE = {"Origin": BASE, "Content-Type": "application/json", "X-Second-Order-Intake": "1"}
GAP_SECONDS = 3  # Well inside the store's 30-second busy timeout, so a serialized writer only waits.


def policy(**account) -> dict:
    return {"account": {**USAGE_POLICY["account"], **account}, "server": USAGE_POLICY["server"]}


class SourceWrites(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.world = World(self.root)
        self.world.standard_terms()
        refreshed(self.root / "event-inbox")
        self.pages = Pages({fed_link(1): (200, fed_page())})
        self.fetcher = publication_import.PublicationFetcher(httpx.MockTransport(self.pages))
        self.user = self.client()

    def client(self):
        client = self.world.client("reader-a", publication_fetcher=self.fetcher)
        self.addCleanup(client.close)
        return client

    def limit(self, **account) -> None:
        usage.add_policy(self.world.accounts, policy(**account), self.world.ids["admin"], "SYNTHETIC limits",
                         self.world.clock())

    def records(self) -> dict:
        connection = sqlite3.connect(self.world.store_path)
        try:
            rows = list(connection.iterdump())
        finally:
            connection.close()
        files = {name: data for name, data in every_file(self.root).items()
                 if not Path(name).name.startswith("accounts.db")}
        return {"rows": rows, "files": files, "pages": len(self.pages.requests),
                "sent": len(self.world.provider.requests)}

    def assert_same(self, label: str, before: dict) -> None:
        after = self.records()
        if after != before:
            rows = [line for line in difflib.unified_diff(before["rows"], after["rows"], lineterm="", n=0)
                    if line[:1] in "+-" and not line.startswith(("+++", "---"))]
            files = sorted(set(after["files"]) ^ set(before["files"]) |
                           {name for name in before["files"] if after["files"].get(name) != before["files"][name]})
            self.fail(f"{label} changed records: rows {rows[:6]}, files {files}, "
                      f"pages {before['pages']}->{after['pages']}, sent {before['sent']}->{after['sent']}")

    def table(self, query: str, parameters: tuple = ()) -> list[tuple]:
        connection = sqlite3.connect(self.world.store_path)
        try:
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

    def counted(self, user: str | None = None) -> int:
        """Today's source events that were not released (of one account when `user` is given)."""
        return self.table("SELECT COUNT(*) FROM usage_events e LEFT JOIN usage_releases r ON r.event_id = e.event_id "
                          "WHERE e.operation = 'source' AND r.event_id IS NULL AND e.user_id LIKE ?",
                          (self.world.ids[user] if user else "%",))[0][0]

    def saved(self) -> list[dict]:
        return self.user.get("/api/user/sources").json()["sources"]

    def at_once(self, sends: list) -> list:
        start = threading.Barrier(len(sends))

        def send(index: int):
            start.wait(10)
            return sends[index]()
        with ThreadPoolExecutor(len(sends)) as pool:
            return list(pool.map(send, range(len(sends))))

    def post(self, form: dict):
        return lambda: self.user.post("/api/user/sources", headers=USER_WRITE, json=form)

    # ---------------------------------------------------------------- QA-7

    def test_the_same_source_sent_again_at_the_same_instant_is_refused_and_writes_nothing(self):
        form = source_form(headline="Synthetic double submission")
        first = self.user.post("/api/user/sources", headers=USER_WRITE, json=form)
        self.assertEqual(first.status_code, 201, first.text[:300])
        before = self.records()
        again = self.user.post("/api/user/sources", headers=USER_WRITE, json=form)  # The clock has not moved.
        self.assertEqual((again.status_code, again.json().get("code")), (422, "invalid_source"), again.text[:300])
        self.assertIn("contract", again.json())
        self.assert_same("the repeated source", before)

    def collide(self, form: dict, other) -> tuple:
        """reader-a sends `form`; `other()` saves the identical source after reader-a's checks and before its write.
        Returns reader-a's reply, other's outcome and whether other finished inside that gap."""
        arrived, done, gap = threading.Event(), threading.Event(), {"paused": False, "inside": False}
        original = event_intake.save

        def save(*args, **kwargs):
            if not gap["paused"]:  # reader-a's write: the other writer goes first.
                gap["paused"] = True
                arrived.set()
                gap["inside"] = done.wait(GAP_SECONDS)
            return original(*args, **kwargs)
        modules = [module for name, module in list(sys.modules.items())
                   if name.split(".")[0] == "second_order" and getattr(module, "save", None) is original]
        with contextlib.ExitStack() as stack:
            for module in modules:
                stack.enter_context(mock.patch.object(module, "save", save))
            with ThreadPoolExecutor(1) as pool:
                mine = pool.submit(self.post(form))
                outcome = other() if arrived.wait(10) else None
                done.set()
                reply = mine.result(60)
        return reply, outcome, gap["inside"]

    def check_collision(self, label: str, other, other_user: str | None) -> None:
        """reader-a meets `other(form)`, which returns (status, capture ID or None); `other_user` is the account it
        writes for (None: the operator, whose captures carry no owner row)."""
        a = self.world.ids["reader-a"]
        form = source_form(headline=f"Synthetic collision with {label}")
        before, mine_before = self.records(), self.saved()
        reply, outcome, inside = self.collide(form, lambda: other(form))
        self.assertIsNotNone(outcome, "reader-a never reached a capture write, so the race was not constructed")
        after = self.records()
        changed = [line for line in difflib.unified_diff(before["rows"], after["rows"], lineterm="", n=0)
                   if line[:1] in "+-" and not line.startswith(("+++", "---"))]
        new = sorted(set(after["files"]) - set(before["files"]))
        capture_ids = {Path(name).parts[1] for name in new}
        self.assertEqual(len(capture_ids), 1, new)
        (capture_id,) = capture_ids
        self.assertTrue(all(Path(name).parts[0] == "intake" for name in new), new)
        self.assertEqual([name for name in before["files"] if after["files"].get(name) != before["files"][name]], [])
        self.assertEqual((after["pages"], after["sent"]), (before["pages"], before["sent"]))
        self.assertFalse([line for line in changed if "usage_releases" in line],
                         f"a refusal left release rows: {changed}")
        if inside:  # The other writer kept the capture: reader-a's refusal writes nothing.
            self.assertEqual(outcome, (201, capture_id))
            self.assertTrue(400 <= reply.status_code < 500 and reply.json().get("code"), reply.text[:300])
            self.assertIn("contract", reply.json())
            self.assertFalse([line for line in changed if a in line], f"reader-a's refusal wrote {changed}")
            self.assertEqual(self.counted("reader-a"), 0)
            self.assertEqual(self.saved(), mine_before)
            self.assertEqual(self.user.get(f"/api/user/sources/{capture_id}").status_code, 404)
            owners = self.table("SELECT user_id FROM record_owners WHERE kind = 'capture' AND record_id = ?",
                                (capture_id,))
            self.assertEqual(owners, [(self.world.ids[other_user],)] if other_user else [])
            self.world.clock.advance(seconds=1)  # reader-a may send the source again: it counts once.
            again = self.post(form)()
            self.assertEqual(again.status_code, 201, again.text[:300])
            self.assertEqual(self.counted("reader-a"), 1)
            self.assertFalse(self.table("SELECT * FROM usage_releases"))
        else:  # Serialized: reader-a wrote first, and the other writer's refusal writes nothing.
            self.assertEqual(reply.status_code, 201, reply.text[:300])
            self.assertEqual(reply.json()["source"]["source_id"], capture_id)
            self.assertTrue(400 <= outcome[0] < 500 and outcome[1] is None, outcome)
            if other_user:
                self.assertFalse([line for line in changed if self.world.ids[other_user] in line],
                                 f"{other_user}'s refusal wrote {changed}")
            self.assertEqual(self.counted("reader-a"), 1)

    def test_another_account_saving_the_same_source_before_this_write_leaves_this_refusal_writing_nothing(self):
        other = self.world.client("reader-b")
        self.addCleanup(other.close)

        def reader_b(form: dict):
            reply = other.post("/api/user/sources", headers=USER_WRITE, json=form)
            return reply.status_code, reply.json()["source"]["source_id"] if reply.status_code == 201 else None
        self.check_collision("reader-b", reader_b, "reader-b")

    def test_the_operator_saving_the_same_source_before_this_write_leaves_this_refusal_writing_nothing(self):
        operator = self.world.client("admin")
        self.addCleanup(operator.close)
        defaults = analysis_flow.capture_from_form.__defaults__
        self.assertEqual(defaults, (analysis_flow.INTAKE_DIR, analysis_flow.now),
                         "the operator's capture no longer takes its clock as before; review this test")

        def operator_form(form: dict):
            with mock.patch.object(analysis_flow.capture_from_form, "__defaults__",
                                   (analysis_flow.INTAKE_DIR, self.world.clock)):
                reply = operator.post("/api/intake", headers=INTAKE_WRITE, json=form)
            return reply.status_code, reply.json()["capture_id"] if reply.status_code == 201 else None
        self.check_collision("the operator", operator_form, None)

    # ---------------------------------------------------------------- what a repair keeps

    def test_valid_sources_sent_at_once_at_the_daily_limit_pass_exactly_up_to_it(self):
        self.limit(sources_per_day=4)
        self.assertEqual(self.post(source_form(headline="Synthetic source 0"))().status_code, 201)
        valid = [self.post(source_form(headline=f"Synthetic concurrent source {n}")) for n in range(6)]
        invalid = [self.post(source_form(headline="")) for _ in range(3)]
        replies = self.at_once(valid + invalid)
        valid_codes = sorted((reply.status_code, reply.json().get("code")) for reply in replies[:6])
        self.assertEqual(valid_codes, [(201, None)] * 3 + [(409, "usage_limit_reached")] * 3)
        for reply in replies[6:]:  # Refused either way; which refusal comes first is the route's order to choose.
            self.assertIn((reply.status_code, reply.json().get("code")),
                          {(422, "invalid_source"), (409, "usage_limit_reached")}, reply.text[:300])
        self.assertEqual((len(self.saved()), self.counted()), (4, 4))
        limits = self.user.get("/api/user/limits").json()["limits"]
        self.assertEqual(next(row["used"] for row in limits["operations"] if row["operation"] == "source"), 4)

    def test_valid_sources_sent_at_once_never_hold_more_than_the_storage_limit(self):
        self.assertEqual(self.post(source_form(headline="Synthetic source 0"))().status_code, 201)
        held = usage.stored(self.world.accounts, self.root / "intake", self.world.ids["reader-a"])
        text = "Synthetic storage text that is long enough to be accepted as a source here. " * 4
        size = len(text.encode("utf-8"))
        self.limit(max_source_bytes=held["source_bytes"] + 2 * size + size // 2)
        replies = self.at_once([self.post(source_form(headline=f"Synthetic stored source {n}", text=text))
                                for n in range(5)])
        codes = sorted((reply.status_code, reply.json().get("code")) for reply in replies)
        self.assertEqual(codes, [(201, None)] * 2 + [(409, "storage_limit_reached")] * 3)
        for reply in replies:
            if reply.status_code == 409:
                self.assertEqual((reply.json()["storage"]["measure"], reply.json()["storage"]["adding"]),
                                 ("source_bytes", size))
        now = usage.stored(self.world.accounts, self.root / "intake", self.world.ids["reader-a"])
        self.assertEqual((now["sources"], now["source_bytes"]), (3, held["source_bytes"] + 2 * size))
        self.assertEqual(self.counted(), 3)

    def test_a_saved_source_writes_one_counted_event_its_capture_and_its_owner(self):
        before = self.records()
        reply = self.post(source_form(headline="Synthetic counted source"))()
        self.assertEqual(reply.status_code, 201, reply.text[:300])
        source_id = reply.json()["source"]["source_id"]
        after = self.records()
        added = [line for line in difflib.unified_diff(before["rows"], after["rows"], lineterm="", n=0)
                 if line.startswith("+INSERT")]
        self.assertEqual(sum('INTO "usage_events"' in line and "'source'" in line for line in added), 1, added)
        self.assertFalse([line for line in added if 'INTO "usage_releases"' in line], added)
        self.assertEqual(sum('INTO "record_owners"' in line and source_id in line for line in added), 1, added)
        new_files = sorted(set(after["files"]) - set(before["files"]))
        self.assertTrue(new_files and all(Path(name).parts[:2] == ("intake", source_id) for name in new_files),
                        new_files)
        self.assertEqual((after["pages"], after["sent"]), (before["pages"], before["sent"]))

    def test_an_import_confirmation_refused_at_a_limit_writes_and_requests_nothing(self):
        news = self.user.get("/api/user/news?scope=all").json()["news"]
        entry = next(row for row in news["entries"] if row["link"] == fed_link(1))
        preview = self.user.post("/api/user/news/imports", headers=USER_WRITE, json={
            "entry_id": entry["entry_id"], "version_sha256": entry["version_sha256"]})
        self.assertEqual(preview.status_code, 201, preview.text[:300])
        proposed = preview.json()["import"]
        confirm = lambda: self.user.post(  # noqa: E731
            f"/api/user/news/imports/{proposed['import_id']}/confirmation", headers=USER_WRITE,
            json={"text_sha256": proposed["proposed_source"]["text_sha256"], "confirm": True})
        held = usage.stored(self.world.accounts, self.root / "intake", self.world.ids["reader-a"])
        self.assertEqual(self.post(source_form(headline="Synthetic pasted source"))().status_code, 201)
        for label, limits, code in (
                ("the storage limit", {"max_source_bytes": held["source_bytes"] + 10}, "storage_limit_reached"),
                ("the daily source limit", {"sources_per_day": 1}, "usage_limit_reached")):
            with self.subTest(label):
                self.limit(**limits)
                before = self.records()
                refused = confirm()
                self.assertEqual((refused.status_code, refused.json().get("code")), (409, code), refused.text[:300])
                self.assert_same(f"a confirmation refused at {label}", before)
        self.limit()
        accepted = confirm()
        self.assertEqual((accepted.status_code, accepted.json()["created"]), (201, True), accepted.text[:300])
        self.assertEqual(len(self.saved()), 2)


if __name__ == "__main__":
    unittest.main()
