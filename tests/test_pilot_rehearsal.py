"""A SYNTHETIC rehearsal of one FOMC pilot night on the pilot's own calendar, through the app's own routes.

Not a real case and not a research result. Every value is invented (market_fakes.synthetic_pair, a pattern of the
date), every record says SYNTHETIC in its headline, story ID and authoring statement, and everything lives in temporary
folders: no network is reached and no real store or package is opened.

The dates follow the pilot protocol draft for its first scheduled statement, so the rehearsal exercises the real timing:
- The statement: Wednesday 9 December 2026, 2:00 p.m. New York time (EST, UTC-5).
- The Board posts H.15 on business days at 4:15 p.m. New York time with the previous business day's values. A package
  downloaded at 2:30 p.m. on the 9th therefore states the 7th at most, which freshness policy B refuses; one downloaded
  at 4:30 p.m. states the 8th, the last expected session before the statement day.
- The freeze: 5:00 p.m. on the 9th, the same New York date. Scoring starts at the first observation dated after it (the
  10th); the 5-observation target is Thursday 17 December. Its value is posted on Friday the 18th at 4:15 p.m., so the
  outcome package is downloaded at 4:30 p.m. that day and assessed at 5:00 p.m.

Run with SECOND_ORDER_REHEARSAL_TRANSCRIPT=<path> to also write what each step showed, as JSON, to that path.
"""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import unittest

from market_fakes import synthetic_pair
from second_order.data import NEW_YORK
from test_lifecycle_assessment import AssessmentHarness
from test_lifecycle_freeze import manual

UTC = timezone.utc
PUBLISHED_AT = "2026-12-09T14:00:00-05:00"
FIRST = date(2025, 1, 2)
EARLY = (date(2026, 12, 7), datetime(2026, 12, 9, 19, 30, tzinfo=UTC))  # 2:30 p.m.: before the 4:15 p.m. release.
FRESH = (date(2026, 12, 8), datetime(2026, 12, 9, 21, 30, tzinfo=UTC))  # 4:30 p.m.: after it.
FREEZE_AT = datetime(2026, 12, 9, 22, tzinfo=UTC)  # 5:00 p.m. on the statement day.
OUTCOME = (date(2026, 12, 17), datetime(2026, 12, 18, 21, 30, tzinfo=UTC))  # Friday 4:30 p.m.
ASSESS_AT = datetime(2026, 12, 18, 22, tzinfo=UTC)
TRANSCRIPT = "SECOND_ORDER_REHEARSAL_TRANSCRIPT"


def ny_day(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(NEW_YORK).date().isoformat()


def pilot_form(**changes) -> dict:
    """The pilot's form: the 2-year leg primary, both legs first order and horizon 5. SYNTHETIC content."""
    form = manual(headline="SYNTHETIC rehearsal: FOMC statement of 9 December 2026 (not a real case)",
                  source_url="https://example.com/synthetic-fomc-statement", published_at=PUBLISHED_AT,
                  story_id="synthetic-rehearsal-fomc-2026-12-09",
                  summary="SYNTHETIC rehearsal text: a statement read as lowering the expected policy path.",
                  authoring="SYNTHETIC: written by the rehearsal test, no AI assistance")
    form["legs"][0].update(channel="First order: expected policy path",
                           rationale="SYNTHETIC: the 2-year yield prices the expected policy rate directly.")
    form["legs"][1].update(channel="First order: expected policy path and term premium",
                           rationale="SYNTHETIC: the 10-year yield prices expected short rates and a term premium.")
    for leg, change in zip(form["legs"], changes.pop("expected", (None, None))):
        if change:
            leg["expected"] = change
    return {**form, **changes}


class PilotRehearsal(AssessmentHarness):
    def setUp(self):
        super().setUp()
        self.transcript: dict = {"label": "SYNTHETIC rehearsal: invented values, temporary folders, not a real case"}

    def note(self, step: str, value) -> None:
        self.transcript[step] = value

    def tearDown(self):
        target = os.environ.get(TRANSCRIPT)
        if target:
            path = Path(target)
            stored = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            stored[self._testMethodName] = self.transcript
            path.write_bytes((json.dumps(stored, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        super().tearDown()

    def research_readiness(self) -> dict:
        response = self.client.get("/api/lifecycle/readiness", params={"published": "2026-12-09"})
        self.assertEqual(response.status_code, 200, response.text)
        return next(item for item in response.json()["providers"] if item["provider"] == "board-h15")

    def kept(self, which, overrides=None) -> str:
        return self.keep(which[0], which[1], overrides)

    def stored_legs(self) -> list[dict]:
        [(_, _, _, payload)] = self.evaluation_rows()
        return json.loads(payload)["legs"]


class NightTests(PilotRehearsal):
    def test_one_synthetic_night_from_readiness_to_assessment(self):
        # 2:30 p.m.: a download before the Board's 4:15 p.m. release states the 7th only.
        self.at(EARLY[1] + timedelta(minutes=5))
        early = self.import_baseline(self.kept(EARLY))["snapshot"]["snapshot_id"]
        waiting = self.research_readiness()
        self.assertEqual(waiting["status"], "needs_baseline")
        self.assertTrue(waiting["action"].startswith("Wait until 2026-12-09 16:15 New York time before downloading"))
        stale = self.preview(self.inputs(early, pilot_form()))
        self.assertFalse(stale["freezable"])
        self.assertIn("Freshness policy B", " ".join(stale["blockers"]))
        self.assertIn("is 2026-12-08", " ".join(stale["blockers"]))
        refused = self.approve(self.inputs(early, pilot_form()), stale)
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(self.counts()["hypotheses"], 0)
        self.note("1_stale_baseline_at_14_35_new_york", {"baseline_through": "2026-12-07", "freezable": False,
                                                         "blockers": stale["blockers"], "readiness": waiting["action"],
                                                         "approval": refused.status_code})
        # 4:30 p.m.: the release posted at 4:15 p.m. states the 8th; the baseline is fresh.
        self.at(FRESH[1] + timedelta(minutes=5))
        imported = self.import_baseline(self.kept(FRESH))["snapshot"]
        baseline = imported["snapshot_id"]
        ready = self.research_readiness()
        self.assertEqual((ready["status"], ready["baselines"]), ("freeze_ready", [baseline]))
        self.note("2_fresh_baseline_at_16_35_new_york", {"snapshot": baseline[:12], "readiness": ready["status"],
                                                         "scorable_horizons": ready["scorable_horizons"]})
        # 5:00 p.m.: preview, then one approval freezes it.
        self.at(FREEZE_AT)
        inputs = self.inputs(baseline, pilot_form())
        shown = self.preview(inputs)
        self.assertEqual((shown["freezable"], shown["blockers"]), (True, []))
        self.assertEqual(shown["freshness"]["required_session"], "2026-12-08")
        self.assertEqual(shown["scoring"]["expected_score_anchor"], "2026-12-10")
        self.assertEqual({leg["expected_target"] for leg in shown["scoring"]["legs"].values()}, {"2026-12-17"})
        self.assertEqual({leg["event_anchor"] for leg in shown["readiness"]["legs"].values()}, {"2026-12-08"})
        frozen = self.approve(inputs, shown)
        self.assertEqual(frozen.status_code, 201, frozen.text)
        hypothesis_id = frozen.json()["hypothesis_id"]
        self.note("3_preview_and_freeze_at_17_00_new_york", {
            "hypothesis": hypothesis_id[:12], "freeze_date_new_york": shown["binding"]["freeze_date_new_york"],
            "usage": shown["binding"]["effective_hypothesis"]["usage"],
            "required_session": shown["freshness"]["required_session"],
            "event_anchor": "2026-12-08", "expected_score_anchor": shown["scoring"]["expected_score_anchor"],
            "expected_targets": {key: leg["expected_target"] for key, leg in shown["scoring"]["legs"].items()},
            "reference_windows": {key: leg["reference_windows"] for key, leg in shown["readiness"]["legs"].items()}})
        self.assertEqual(shown["binding"]["effective_hypothesis"]["usage"], "showcase")
        # The same approval again returns the original freeze; the same request previewed again cannot be frozen.
        again = self.approve(inputs, shown)
        self.assertEqual((again.status_code, again.json()["hypothesis_id"], again.json()["created"]),
                         (200, hypothesis_id, False))
        repeat = self.preview(inputs)
        self.assertFalse(repeat["freezable"])
        self.assertIn("is already frozen as", " ".join(repeat["blockers"]))
        self.assertEqual(self.approve(inputs, repeat).json()["created"], False)  # The same binding: the same action.
        self.at(datetime(2026, 12, 10, 15, tzinfo=UTC))  # The next day: another freeze date, so another binding.
        later = self.preview(inputs)
        self.assertIn("is already frozen as", " ".join(later["blockers"]))
        refused_again = self.approve(inputs, later)
        self.assertEqual(refused_again.status_code, 409, refused_again.text)
        self.assertEqual(self.counts()["hypotheses"], 1)
        self.note("4_freeze_again", {"same_approval": "returns the original freeze, created false",
                                     "same_request_new_preview": repeat["blockers"],
                                     "same_request_next_day": refused_again.status_code})
        # Before the target's value is posted the outcome is not held.
        self.at(datetime(2026, 12, 18, 20, tzinfo=UTC))  # Friday 3 p.m.: the 17th ended but is not yet posted.
        self.assertEqual(self.readiness(hypothesis_id)["state"], "outcome_missing")
        # A kept outcome package whose bytes changed afterwards is refused, and nothing is written.
        self.at(ASSESS_AT)
        damaged = self.kept(OUTCOME)
        archive = self.market / "packages" / damaged / "package.zip"
        os.chmod(archive, stat.S_IWRITE | stat.S_IREAD)
        data = bytearray(archive.read_bytes())
        data[len(data) // 2] ^= 0xFF
        archive.write_bytes(bytes(data))
        counts = self.counts()
        refused = self.import_outcome(hypothesis_id, damaged, expect=409)
        self.assertIn("does not verify", refused["detail"])
        self.assertEqual(self.counts(), counts)
        self.note("5_changed_package", {"import": 409, "detail": refused["detail"]})
        # The intact package, downloaded after the Friday release, is imported and assessed once.
        outcome = self.import_outcome(hypothesis_id, self.kept((OUTCOME[0], OUTCOME[1] + timedelta(minutes=1))))
        snapshot = outcome["snapshot"]["snapshot_id"]
        held = self.readiness(hypothesis_id)
        self.assertEqual(held["state"], "ready")
        previewed = self.assessment_preview(hypothesis_id, snapshot)
        self.assertTrue(previewed["assessable"], previewed["blockers"])
        self.assertNotIn('"verdict"', json.dumps(previewed))
        response = self.assess(previewed)
        self.assertEqual(response.status_code, 201, response.text)
        legs = self.stored_legs()
        for leg in legs:
            # Stored as the end of each New York date, in UTC (the daily date convention's placeholder, not a time).
            self.assertEqual((ny_day(leg["event_anchor"]), ny_day(leg["score_anchor"])), ("2026-12-08", "2026-12-10"))
            self.assertEqual((leg["anchor_policy"], leg["initial_reaction_scored"]),
                             ("daily_first_date_after_freeze_date", False))
            self.assertIn(leg["verdict"], ("supported", "contradicted", "inconclusive"))
            # The measured change is the target's value minus the scoring anchor's, in basis points: the statement
            # day (the 8th to the 9th) and the day after it (the 9th to the 10th) are not in it.
            column = 0 if leg["observable_id"] == "yield:ust2y_cmt_h15" else 1
            start, end = (float(synthetic_pair(day)[column]) for day in (date(2026, 12, 10), date(2026, 12, 17)))
            self.assertAlmostEqual(leg["measured_change"], (end - start) * 100, places=6)
        self.note("6_assessment", {
            "outcome_snapshot": snapshot[:12], "cutoff": previewed["binding"]["cutoff"],
            "legs": [{key: leg[key] for key in ("observable_id", "primary", "horizon", "event_anchor", "score_anchor",
                                                "verdict", "measured_change", "signed_move", "percentile_rank",
                                                "reference_windows", "reason")}
                     | {"event_anchor_new_york": ny_day(leg["event_anchor"]),
                        "score_anchor_new_york": ny_day(leg["score_anchor"])} for leg in legs],
            "counted_as": "one case (the primary 2-year leg); the 10-year leg is a second outcome of the same event"})


class RefusalTests(PilotRehearsal):
    def frozen_case(self) -> str:
        self.at(FRESH[1] + timedelta(minutes=5))
        baseline = self.import_baseline(self.kept(FRESH))["snapshot"]["snapshot_id"]
        self.at(FREEZE_AT)
        inputs = self.inputs(baseline, pilot_form())
        shown = self.preview(inputs)
        response = self.approve(inputs, shown)
        self.assertEqual(response.status_code, 201, response.text)
        self.baseline_id = baseline
        return response.json()["hypothesis_id"]

    def test_a_missing_session_in_the_scored_window_makes_both_legs_unavailable(self):
        hypothesis_id = self.frozen_case()
        self.at(ASSESS_AT)
        package_id = self.kept(OUTCOME, overrides={date(2026, 12, 15): ("ND", "ND")})  # Stated, with no value.
        snapshot = self.import_outcome(hypothesis_id, package_id)["snapshot"]["snapshot_id"]
        shown = self.readiness(hypothesis_id)
        self.assertEqual(shown["state"], "missing_values")
        self.assertEqual(shown["candidates"][0]["legs"][0]["gaps"],
                         [{"date": "2026-12-15", "status": "session_missing"}])
        previewed = self.assessment_preview(hypothesis_id, snapshot)
        self.assertEqual(self.assess(previewed).status_code, 201)
        legs = self.stored_legs()
        self.assertEqual({(leg["verdict"], leg["reason"]) for leg in legs},
                         {("unavailable", "Missing observation inside the required window")})
        self.note("missing_session", {"gap": "2026-12-15 stated as ND", "state": shown["state"],
                                      "legs": [(leg["observable_id"], leg["verdict"], leg["reason"]) for leg in legs]})

    def test_a_changed_form_for_the_same_statement_is_stored_as_another_hypothesis(self):
        hypothesis_id = self.frozen_case()
        inputs = self.inputs(self.baseline_id, pilot_form(expected=("up", "up")))
        shown = self.preview(inputs)
        # The request identity hashes the whole form, so a changed form is a new request: the code does not refuse
        # it. The protocol, not the code, keeps one case per statement (the first freeze of its story group).
        self.assertTrue(shown["freezable"], shown["blockers"])
        second = self.approve(inputs, shown)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(second.json()["hypothesis_id"], hypothesis_id)
        connection = sqlite3.connect(f"{self.store.resolve().as_uri()}?mode=ro", uri=True)
        self.addCleanup(connection.close)
        rows = connection.execute("SELECT payload FROM hypotheses")
        stories = {json.loads(payload)["story_id"] for (payload,) in rows}
        self.assertEqual(stories, {"synthetic-rehearsal-fomc-2026-12-09"})
        self.assertEqual(self.counts()["hypotheses"], 2)
        self.note("changed_form_same_statement", {"second_freeze": second.status_code, "hypotheses": 2,
                                                  "story_ids": sorted(stories)})


if __name__ == "__main__":
    unittest.main()
