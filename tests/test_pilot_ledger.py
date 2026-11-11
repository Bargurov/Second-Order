"""The FOMC pilot's ledger: one case per scheduled statement, by its first freeze, counted the same whatever later
versions say. SYNTHETIC hypotheses frozen through the app's routes on temporary folders; nothing real is read, frozen or
assessed, and nothing reaches a network.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest

from second_order.pilot_ledger import (DEFINITION, NO_FREEZE, DefinitionRefused, conformity, freeze_window, ledger,
                                       load_definition, table)
from second_order.store import open_store
from test_lifecycle_freeze import LIFECYCLE
from test_pilot_rehearsal import FREEZE_AT, FRESH, OUTCOME, PilotRehearsal, pilot_form

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent.parent
SCHEDULED = ["2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15",
             "2027-10-27"]
START = "2026-12-01T00:00:00+00:00"  # The start of the tests' approved copies.
APPROVED_START = "2026-12-01T00:00:00+00:00"  # The owner's approved start (2026-11-07), in the committed definition.
TWO, TEN = "yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"
GOOD_LEGS = [{"id": "two-year", "observable_id": TWO, "primary": True, "expected": "down", "horizon": 5},
             {"id": "ten-year", "observable_id": TEN, "primary": False, "expected": "down", "horizon": 5}]


def at(moment: datetime):
    return lambda: moment


def case_form(**changes) -> dict:
    """The rehearsal's SYNTHETIC form under the statement's own story ID, as a real case would carry it."""
    return pilot_form(**{"story_id": "fomc-2026-12-09", **changes})


class LedgerHarness(PilotRehearsal):
    def definition(self, start: str | None = START, **statements) -> Path:
        """A copy of the committed definition with a start and per-date changes, in the temporary folder."""
        value = json.loads(DEFINITION.read_text(encoding="utf-8"))
        value["start_utc"], value["status"] = start, "approved" if start else "proposed"
        for entry in value["statements"]:
            entry.update(statements.get(entry["date"], {}))
        path = self.root / "fomc-pilot.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def read(self, moment: datetime, path: Path | None = None) -> dict:
        return ledger(load_definition(path or self.definition()), self.store, at(moment))

    def baseline_for_night(self) -> str:
        self.at(FRESH[1] + timedelta(minutes=5))
        return self.import_baseline(self.keep(*FRESH))["snapshot"]["snapshot_id"]

    def freeze_form(self, baseline: str, form: dict, moment: datetime) -> str:
        self.at(moment)
        inputs = self.inputs(baseline, form)
        shown = self.preview(inputs)
        self.assertTrue(shown["freezable"], shown["blockers"])
        response = self.approve(inputs, shown)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["hypothesis_id"]

    def assess_case(self, hypothesis_id: str, package_id: str) -> None:
        snapshot = self.import_outcome(hypothesis_id, package_id, expect=None)["snapshot"]["snapshot_id"]
        shown = self.assessment_preview(hypothesis_id, snapshot)
        self.assertTrue(shown["assessable"], shown["blockers"])
        self.assertEqual(self.assess(shown).status_code, 201)

    def import_outcome(self, hypothesis_id: str, package_id: str, expect: int | None = 201) -> dict:
        response = self.client.post("/api/lifecycle/outcome-imports", headers=LIFECYCLE,
                                    content=json.dumps({"hypothesis_id": hypothesis_id, "package_id": package_id}))
        self.assertIn(response.status_code, (200, 201) if expect is None else (expect,), response.text)
        return response.json()

    @staticmethod
    def row(result: dict, day: str) -> dict:
        return next(row for row in result["statements"] if row["date"] == day)

    def reconciled(self, result: dict) -> dict:
        """The counts agree with each other and with the rows; returns them."""
        counts = result["counts"]
        self.assertEqual(counts["scheduled"], counts["not_held"] + counts["not_started"] + counts["before_start"] +
                         counts["upcoming"] + counts["included"])
        self.assertEqual(counts["included"], counts["frozen"] + counts["missed"])
        self.assertEqual(counts["frozen"], counts["pending"] + counts["assessed"] + counts["nonconforming"])
        self.assertEqual(counts["summary_cases"], counts["assessed"])
        self.assertEqual(sum(counts["primary_labels"].values()), counts["assessed"])
        self.assertEqual(counts["summary_cases"], sum(row["in_summary"] for row in result["statements"]))
        return counts

    def crafted(self, story_id: str, published: str, frozen: str, legs=None, verdicts: dict | None = None) -> str:
        """A SYNTHETIC record written straight into the temporary store, for leg sets and times the freeze route
        cannot make (it binds exactly the two H.15 legs). Only the fields the ledger reads are set."""
        self.store.parent.mkdir(parents=True, exist_ok=True)
        connection = open_store(str(self.store))
        payload = {"story_id": story_id, "event": {"published_at": published}, "frozen_at": frozen,
                   "evidence_class": "prospective", "usage": "showcase", "legs": legs or GOOD_LEGS}
        identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with connection:
            connection.execute("INSERT INTO hypotheses VALUES (?,?,?,?)", (identity, identity, frozen,
                                                                          json.dumps(payload)))
            if verdicts:
                legs_out = [{"observable_id": key, "primary": key == TWO, "verdict": value}
                            for key, value in verdicts.items()]
                connection.execute("INSERT INTO evaluations VALUES (?,?,?,?)",
                                   ("e" + identity[1:], identity, frozen, json.dumps({"legs": legs_out})))
        connection.close()
        return identity


class DefinitionTests(LedgerHarness):
    def test_the_committed_definition_is_the_approved_one(self):
        definition = load_definition()
        self.assertEqual([entry["date"] for entry in definition["statements"]], SCHEDULED)
        self.assertEqual((definition["status"], definition["start_utc"]), ("approved", APPROVED_START))
        self.assertEqual((definition["primary"], definition["secondary"]),
                         ({"observable_id": "yield:ust2y_cmt_h15", "horizon": 5},
                          {"observable_id": "yield:ust10y_cmt_h15", "horizon": 5}))
        self.assertTrue((ROOT / definition["protocol"]).is_file())
        # Before its start, with no case: every statement is scheduled and nothing is included.
        before = ledger(definition, None, at(datetime(2026, 11, 7, 22, tzinfo=UTC)))
        self.assertEqual({row["state"] for row in before["statements"]}, {"scheduled"})
        self.assertEqual(before["phase"], {"phase": "approved_not_started", "text": (
            "Approved; starts at 2026-12-01T00:00:00+00:00, in the future: nothing is counted before then")})
        self.assertIn("Phase: Approved; starts at 2026-12-01T00:00:00+00:00, in the future", table(before))
        self.assertEqual(ledger(definition, None, at(datetime(2026, 12, 1, tzinfo=UTC)))["phase"]["phase"], "running")
        self.assertEqual((self.reconciled(before)["upcoming"], before["counts"]["included"]), (8, 0))
        # Long after the last statement, with no case: every statement is missed, none silently dropped.
        after = ledger(definition, None, at(datetime(2027, 12, 1, tzinfo=UTC)))
        self.assertEqual({(row["state"], row["reason"]) for row in after["statements"]}, {("missed", NO_FREEZE)})
        self.assertEqual(after["phase"]["phase"], "intake_ended")
        self.assertEqual((self.reconciled(after)["included"], after["counts"]["missed"]), (8, 8))

    def test_a_proposed_copy_starts_nothing_and_an_approved_copy_counts_from_its_start(self):
        moment = datetime(2026, 12, 10, 15, tzinfo=UTC)
        proposed = ledger(load_definition(self.definition(start=None)), None, at(moment))
        self.assertEqual((proposed["status"], proposed["start_utc"], proposed["phase"]["phase"]),
                         ("proposed", None, "proposed"))
        self.assertEqual(self.reconciled(proposed)["not_started"], 8)
        approved = ledger(load_definition(self.definition("2026-11-20T08:00:00+00:00")), None, at(moment))
        self.assertEqual((approved["status"], self.row(approved, "2026-12-09")["state"]), ("approved", "missed"))
        self.assertEqual((self.reconciled(approved)["upcoming"], approved["counts"]["missed"]), (7, 1))

    def test_a_malformed_definition_is_refused(self):
        value = json.loads(DEFINITION.read_text(encoding="utf-8"))
        cases = {
            "unsorted": lambda v: v["statements"].reverse(),
            "story": lambda v: v["statements"][0].update(story_id="fomc-2026-12-9"),
            "field": lambda v: v["statements"][0].update(extra=1),
            "start": lambda v: v.update(start_utc="2026-12-01T00:00:00"),
            "start after the first statement": lambda v: v.update(start_utc="2026-12-09T23:00:00+00:00"),
            "horizon": lambda v: v["primary"].update(horizon=3),
            "version": lambda v: v.update(pilot_version="fomc-pilot-9"),
            "approved without a start": lambda v: v.update(status="approved", start_utc=None),
            "a start while proposed": lambda v: v.update(status="proposed"),
            "one observable twice": lambda v: v["secondary"].update(observable_id=TWO),
        }
        for name, change in cases.items():
            broken = json.loads(json.dumps(value))
            change(broken)
            path = self.root / f"{name}.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(DefinitionRefused, msg=name):
                load_definition(path)

    def test_the_freeze_window_is_set_in_new_york_and_converted_to_israel_time_per_date(self):
        december = freeze_window(date(2026, 12, 9))
        self.assertEqual(december["new_york"], {"baseline_obtainable_from": "2026-12-09 16:15 New York time",
                                                "closes": "2026-12-10 00:00 New York time"})
        self.assertEqual(december["israel"], {"baseline_obtainable_from": "2026-12-09 23:15",
                                              "closes": "2026-12-10 07:00"})
        march = freeze_window(date(2027, 3, 17))  # New York on daylight time, Israel not yet.
        self.assertEqual(march["israel"], {"baseline_obtainable_from": "2027-03-17 22:15",
                                           "closes": "2027-03-18 06:00"})
        october = freeze_window(date(2027, 10, 27))
        self.assertEqual(october["israel"], {"baseline_obtainable_from": "2027-10-27 23:15",
                                             "closes": "2027-10-28 07:00"})

    def test_the_protocol_checklist_and_journal_agree_with_the_definition_and_the_window_rule(self):
        definition = load_definition()
        protocol = (ROOT / definition["protocol"]).read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "pilot" / "fomc-night-checklist.he.md").read_text(encoding="utf-8")
        journal = (ROOT / "docs" / "pilot" / "fomc-pilot-journal.he.md").read_text(encoding="utf-8")
        for entry in definition["statements"]:
            window = freeze_window(date.fromisoformat(entry["date"]))["israel"]
            opens, closes = window["baseline_obtainable_from"], window["closes"]
            self.assertIn(f"{opens} to {closes}", protocol, entry["date"])
            self.assertIn(f"`{entry['story_id']}`", protocol)
            self.assertIn(f"`{entry['story_id']}`", journal)
            hours = f"{opens[11:]} עד {closes[11:]}"  # "HH:MM until HH:MM" in Hebrew.
            self.assertIn(hours, journal, entry["date"])
            self.assertIn(hours, checklist, entry["date"])
        self.assertIn(f"| Start timestamp (UTC) | `{definition['start_utc']}`", protocol)
        self.assertIn("**Status: approved by the project owner on 2026-11-07, as a showcase pilot.", protocol)
        self.assertIn(f"`{definition['start_utc']}`", journal)
        self.assertIn(f"`{definition['start_utc']}`", checklist)


class CountTests(LedgerHarness):
    def test_one_case_per_statement_whatever_later_versions_say(self):
        baseline = self.baseline_for_night()
        case = self.freeze_form(baseline, case_form(), FREEZE_AT)
        first = self.read(datetime(2026, 12, 10, 15, tzinfo=UTC))
        self.assertEqual((self.row(first, "2026-12-09")["state"], self.row(first, "2026-12-09")["case"]),
                         ("pending", case))
        # Later versions of the same statement: both directions flipped, then another horizon.
        flipped = self.freeze_form(baseline, case_form(expected=("up", "up")), FREEZE_AT + timedelta(hours=1))
        legs = [{**leg, "horizon": 1} for leg in case_form()["legs"]]
        shorter = self.freeze_form(baseline, case_form(legs=legs, summary="SYNTHETIC: a third version"),
                                   FREEZE_AT + timedelta(hours=2))
        later = self.read(datetime(2026, 12, 10, 15, tzinfo=UTC))
        row = self.row(later, "2026-12-09")
        self.assertEqual((row["state"], row["case"], row["extra_freezes"]), ("pending", case, 2))
        self.assertEqual([(item["hypothesis_id"], item["role"]) for item in row["versions"]],
                         [(case, "case"), (flipped, "extra"), (shorter, "extra")])
        self.assertEqual(row["versions"][2]["nonconforming"],
                         ["yield:ust2y_cmt_h15 has horizon 1, not 5", "yield:ust10y_cmt_h15 has horizon 1, not 5"])
        self.reconciled(later)
        unchanged = {key: value for key, value in later["counts"].items() if key != "extra_freezes"}
        self.assertEqual(unchanged, {key: value for key, value in first["counts"].items() if key != "extra_freezes"})
        self.assertEqual((later["counts"]["frozen"], later["counts"]["included"], later["counts"]["extra_freezes"]),
                         (1, 1, 2))
        # An assessment of a later version is listed under it, never counted; the case stays pending.
        self.at(OUTCOME[1] + timedelta(minutes=30))
        package_id = self.keep(*OUTCOME)
        self.assess_case(flipped, package_id)
        mid = self.read(OUTCOME[1] + timedelta(minutes=40))
        row = self.row(mid, "2026-12-09")
        self.assertEqual((row["state"], mid["counts"]["assessed"]), ("pending", 0))
        self.assertEqual(len(row["versions"][1]["evaluations"]), 1)
        # The case's own assessment labels the statement.
        self.assess_case(case, package_id)
        done = self.read(OUTCOME[1] + timedelta(minutes=50))
        row = self.row(done, "2026-12-09")
        self.assertEqual((row["state"], row["case"], done["counts"]["assessed"], done["counts"]["frozen"]),
                         ("assessed", case, 1, 1))
        self.assertIn(row["labels"]["primary"], ("supported", "contradicted", "inconclusive"))
        self.assertEqual(row["labels"]["primary"], row["versions"][0]["evaluations"][0]["primary"])
        self.assertEqual((done["counts"]["eligible"], row["in_summary"]), (1, True))
        self.reconciled(done)
        # The same store read again gives the same ledger.
        self.assertEqual(self.read(OUTCOME[1] + timedelta(minutes=50)), done)

    def test_missed_not_held_late_and_unmatched_statements(self):
        baseline = self.baseline_for_night()
        # The only freeze of 9 December is made after New York midnight: the case is missed, and nothing repairs it.
        late = self.freeze_form(baseline, case_form(), datetime(2026, 12, 10, 5, 30, tzinfo=UTC))
        typo = self.freeze_form(baseline, pilot_form(story_id="fomc-2026-12-9", summary="SYNTHETIC: typo story ID"),
                                datetime(2026, 12, 10, 5, 40, tzinfo=UTC))
        path = self.definition(**{"2027-01-27": {"not_held": "SYNTHETIC: the meeting was cancelled"}})
        result = self.read(datetime(2027, 2, 1, 15, tzinfo=UTC), path)
        december = self.row(result, "2026-12-09")
        self.assertEqual(december["state"], "missed")
        self.assertIn("frozen on 2026-12-10 (New York), not on the statement date", december["reason"])
        self.assertEqual(december["versions"][0]["role"], "first_outside_rules")
        self.assertEqual(self.row(result, "2027-01-27")["state"], "not_held")
        self.assertEqual(self.row(result, "2027-03-17")["state"], "scheduled")
        unmatched = "Published on a statement date under another story ID: not counted"
        self.assertEqual(result["unmatched"], [{"hypothesis_id": typo, "story_id": "fomc-2026-12-9",
                                                "published_date": "2026-12-09", "reason": unmatched}])
        self.assertEqual((result["counts"]["included"], result["counts"]["missed"], result["counts"]["not_held"],
                          result["counts"]["frozen"]), (1, 1, 1, 0))
        self.assertNotEqual(late, typo)
        # With no freeze at all, the owner's reason is shown, else the default.
        self.assertEqual(self.row(self.read(datetime(2027, 1, 28, 15, tzinfo=UTC),
                                            self.definition()), "2027-01-27")["reason"], NO_FREEZE)
        noted = self.definition(**{"2027-01-27": {"missed_reason": "SYNTHETIC: the release was late"}})
        self.assertEqual(self.row(self.read(datetime(2027, 1, 28, 15, tzinfo=UTC), noted), "2027-01-27")["reason"],
                         "SYNTHETIC: the release was late")
        self.assertEqual(self.row(self.read(datetime(2027, 1, 27, 15, tzinfo=UTC)), "2027-01-27")["state"], "open")

    def test_before_the_start_nothing_is_included_and_the_ledger_reads_only(self):
        baseline = self.baseline_for_night()
        self.freeze_form(baseline, case_form(), FREEZE_AT)
        unstarted = self.read(datetime(2026, 12, 10, 15, tzinfo=UTC), self.definition(start=None))
        self.assertEqual((self.row(unstarted, "2026-12-09")["state"], unstarted["counts"]["frozen"],
                          self.row(unstarted, "2026-12-09")["extra_freezes"]), ("not_started", 0, 1))
        self.assertEqual(self.reconciled(unstarted)["not_started"], 8)
        before = hashlib.sha256(self.store.read_bytes()).hexdigest()
        path = self.definition()
        shown = subprocess.run([sys.executable, "-m", "second_order", "pilot-ledger", "--db", str(self.store),
                                "--definition", str(path), "--table"], cwd=ROOT, capture_output=True, text=True,
                               timeout=120)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        # The command reads the real clock: the seven later statements are still upcoming.
        self.assertIn("Scheduled 8 = not held 0 + not started 0 + before start 0 + upcoming 7 + included 1",
                      shown.stdout)
        self.assertEqual(hashlib.sha256(self.store.read_bytes()).hexdigest(), before)
        self.assertIn("2026-12-09", table(self.read(datetime(2026, 12, 10, 15, tzinfo=UTC), path)))


class ConformityTests(LedgerHarness):
    """A case with other legs, roles or horizons than the definition stays the case, is covered and shown with its
    reasons, and never enters the summary; a later conforming version does not replace it."""

    def test_a_first_freeze_with_horizon_1_is_covered_but_never_in_the_summary(self):
        baseline = self.baseline_for_night()
        legs = [{**leg, "horizon": 1} for leg in case_form()["legs"]]
        first = self.freeze_form(baseline, case_form(legs=legs), FREEZE_AT)
        conforming = self.freeze_form(baseline, case_form(summary="SYNTHETIC: a conforming later version"),
                                      FREEZE_AT + timedelta(hours=1))
        self.at(datetime(2026, 12, 14, 21, 30, tzinfo=UTC))  # Horizon 1: the target is 11 December.
        package_id = self.keep(date(2026, 12, 11), datetime(2026, 12, 14, 21, 20, tzinfo=UTC))
        self.assess_case(first, package_id)
        result = self.read(datetime(2026, 12, 14, 22, tzinfo=UTC))
        row = self.row(result, "2026-12-09")
        self.assertEqual((row["state"], row["case"], row["in_summary"], row["extra_freezes"]),
                         ("nonconforming", first, False, 1))
        self.assertEqual(row["reason"], "Not in the summary of results: yield:ust2y_cmt_h15 has horizon 1, not 5; "
                                        "yield:ust10y_cmt_h15 has horizon 1, not 5")
        self.assertIn(row["labels"]["primary"], ("supported", "contradicted", "inconclusive"))  # Shown, kept.
        self.assertEqual([(item["hypothesis_id"], item["role"]) for item in row["versions"]],
                         [(first, "case"), (conforming, "extra")])
        counts = self.reconciled(result)
        self.assertEqual((counts["frozen"], counts["nonconforming"], counts["assessed"], counts["eligible"],
                          counts["included"]), (1, 1, 0, 0, 1))
        self.assertEqual(counts["headline"], "0 of 0 eligible primary legs had observations consistent with the "
                                             "frozen hypothesis")
        self.assertIn("nonconforming 1", table(result))

    def test_the_primary_leg_is_the_definition_s_observable_not_the_record_s_flag(self):
        baseline = self.baseline_for_night()
        form = case_form()
        form["legs"][0]["primary"], form["legs"][1]["primary"] = False, True  # The 10-year marked primary.
        case = self.freeze_form(baseline, form, FREEZE_AT)
        self.at(OUTCOME[1] + timedelta(minutes=30))
        self.assess_case(case, self.keep(*OUTCOME))
        result = self.read(OUTCOME[1] + timedelta(minutes=40))
        row = self.row(result, "2026-12-09")
        self.assertEqual(row["state"], "nonconforming")
        self.assertEqual(row["versions"][0]["nonconforming"],
                         ["yield:ust2y_cmt_h15 is marked secondary; the definition makes it the primary leg",
                          "yield:ust10y_cmt_h15 is marked primary; the definition makes it the secondary leg"])
        [(payload,)] = self.evaluation_payloads()
        verdicts = {leg["observable_id"]: leg["verdict"] for leg in json.loads(payload)["legs"]}
        self.assertEqual(row["labels"], {"primary": verdicts[TWO], "secondary": verdicts[TEN]})
        self.assertEqual(self.reconciled(result)["eligible"], 0)

    def evaluation_payloads(self) -> list:
        connection = sqlite3.connect(f"{self.store.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return list(connection.execute("SELECT payload FROM evaluations"))
        finally:
            connection.close()

    def test_missing_extra_and_duplicate_legs(self):
        definition = load_definition()
        record = lambda legs: {"legs": legs}  # noqa: E731
        fred = {"id": "fred", "observable_id": "yield:ust2y_cmt", "primary": False, "expected": "down", "horizon": 5}
        self.assertEqual(conformity(record(GOOD_LEGS), definition), [])
        self.assertEqual(conformity(record(GOOD_LEGS[:1]), definition), ["no secondary leg on yield:ust10y_cmt_h15"])
        self.assertEqual(conformity(record(GOOD_LEGS + [fred]), definition), ["an extra leg on yield:ust2y_cmt"])
        self.assertEqual(conformity(record([{**GOOD_LEGS[0], "observable_id": "yield:ust2y_cmt"}, GOOD_LEGS[1]]),
                                    definition),
                         ["no primary leg on yield:ust2y_cmt_h15", "an extra leg on yield:ust2y_cmt"])
        self.assertIn("an observable appears in more than one leg",
                      conformity(record(GOOD_LEGS + [GOOD_LEGS[1]]), definition))
        # Through the ledger: a missing and an extra leg, each assessed as supported, stay out of the summary.
        self.crafted("fomc-2027-01-27", "2027-01-27T14:00:00-05:00", "2027-01-27T22:00:00+00:00", GOOD_LEGS[:1],
                     {TWO: "supported"})
        self.crafted("fomc-2027-03-17", "2027-03-17T14:00:00-04:00", "2027-03-17T21:00:00+00:00",
                     GOOD_LEGS + [fred], {TWO: "supported", TEN: "supported", "yield:ust2y_cmt": "supported"})
        self.crafted("fomc-2027-04-28", "2027-04-28T14:00:00-04:00", "2027-04-28T21:00:00+00:00", GOOD_LEGS,
                     {TWO: "supported", TEN: "inconclusive"})
        result = self.read(datetime(2027, 5, 20, 15, tzinfo=UTC))
        self.assertEqual(self.row(result, "2027-01-27")["reason"],
                         "Not in the summary of results: no secondary leg on yield:ust10y_cmt_h15")
        self.assertEqual(self.row(result, "2027-03-17")["reason"],
                         "Not in the summary of results: an extra leg on yield:ust2y_cmt")
        self.assertEqual((self.row(result, "2027-04-28")["state"], self.row(result, "2027-04-28")["in_summary"]),
                         ("assessed", True))
        counts = self.reconciled(result)
        self.assertEqual((counts["nonconforming"], counts["assessed"], counts["eligible"],
                          counts["primary_labels"]["supported"]), (2, 1, 1, 1))


class StartTests(LedgerHarness):
    """The start is a UTC instant before the first statement's expected publication, and publication times are compared
    with it as instants, whatever their offsets: a case published before it is never included afterwards."""

    def test_the_start_must_be_a_utc_instant_before_the_first_statement(self):
        for start, accepted in (("2026-12-09T23:00:00+00:00", False), ("2026-12-09T19:00:00+00:00", False),
                                ("2026-12-09T18:59:59+00:00", True), ("2026-12-01T02:00:00+02:00", False),
                                ("2026-12-01T00:00:00", False), ("2026-11-20T08:00:00+00:00", True)):
            path = self.definition(start)
            if accepted:
                self.assertEqual(load_definition(path)["start_utc"], start)
            else:
                with self.assertRaises(DefinitionRefused, msg=start):
                    load_definition(path)
        limit = r"2026-12-09 14:00 New York time \(2026-12-09T19:00:00\+00:00\)"
        with self.assertRaisesRegex(DefinitionRefused, limit):
            load_definition(self.definition("2026-12-09T23:00:00+00:00"))

    def test_publication_before_the_start_on_the_same_day_is_never_included(self):
        start = "2026-12-09T18:00:00+00:00"  # 1 p.m. in New York on the statement day.
        early = self.crafted("fomc-2026-12-09", "2026-12-09T12:30:00-05:00", "2026-12-09T18:30:00+00:00")
        result = self.read(datetime(2026, 12, 10, 15, tzinfo=UTC), self.definition(start))
        row = self.row(result, "2026-12-09")
        self.assertEqual((row["state"], row["case"], row["extra_freezes"]), ("before_start", None, 1))
        self.assertIn("2026-12-09T12:30:00-05:00, before 2026-12-09T18:00:00+00:00", row["reason"])
        counts = self.reconciled(result)
        self.assertEqual((counts["before_start"], counts["included"], counts["frozen"]), (1, 0, 0))
        # A later version published after the start does not include the statement afterwards.
        self.crafted("fomc-2026-12-09", "2026-12-09T14:00:00-05:00", "2026-12-09T22:00:00+00:00")
        again = self.row(self.read(datetime(2026, 12, 10, 15, tzinfo=UTC), self.definition(start)), "2026-12-09")
        self.assertEqual((again["state"], again["versions"][0]["hypothesis_id"]), ("before_start", early))

    def test_publication_after_the_start_on_the_same_day_counts_whatever_the_offset(self):
        start = "2026-12-09T18:00:00+00:00"
        # 9 p.m. Israel time (UTC+2) is 2 p.m. in New York: after the start, though written in another zone.
        case = self.crafted("fomc-2026-12-09", "2026-12-09T21:00:00+02:00", "2026-12-09T22:00:00+00:00")
        row = self.row(self.read(datetime(2026, 12, 10, 15, tzinfo=UTC), self.definition(start)), "2026-12-09")
        self.assertEqual((row["state"], row["case"]), ("pending", case))

    def test_publication_written_in_another_zone_before_the_start_is_before_the_start(self):
        start = "2026-12-09T18:00:00+00:00"
        self.crafted("fomc-2026-12-09", "2026-12-09T19:30:00+02:00", "2026-12-09T22:00:00+00:00")  # 17:30 UTC.
        result = self.read(datetime(2026, 12, 10, 15, tzinfo=UTC), self.definition(start))
        self.assertEqual(self.row(result, "2026-12-09")["state"], "before_start")
        self.assertEqual(self.reconciled(result)["frozen"], 0)


if __name__ == "__main__":
    unittest.main()
