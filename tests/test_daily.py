"""Daily date convention and calendar reconciliation. No network; the SIFMA schedule is local."""
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import tempfile
import unittest
from second_order.anchors import anchors
from second_order.data import DAILY_DATE_CONVENTION, NEW_YORK, Observation, Series, daily_observation_time, ny_date
from second_order.evaluation import evaluate
from second_order.market_calendar import (EXCEPTIONS_PATH, expected_sessions, load_exceptions, observation_grid,
                                          reconcile)
from second_order.schema import Hypothesis

SESSIONS = sorted(expected_sessions(date(2023, 1, 3), date(2025, 12, 31)))


def ny(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=NEW_YORK)


def daily_series(observable="yield:ust10y_cmt", days=None, values=None, open_ended=True):
    days = SESSIONS if days is None else days
    values = [4 + .1 * math.sin(i / 7) for i in range(len(days))] if values is None else values
    points = tuple(Observation(daily_observation_time(day), value) for day, value in zip(days, values))
    return Series(observable, points, "fred:test", "raw", timestamp_basis=DAILY_DATE_CONVENTION, open_ended=open_ended)


def cmt_hypothesis(published, frozen, horizon=5, replay=False, usage="showcase"):
    leg = {"link": "direct", "falsifier": "An unusually large opposite move.", "headline_reports_move": False}
    return Hypothesis.model_validate({
        "event": {"headline": "Synthetic Treasury announcement", "source_url": "https://example.com/event",
                  "published_at": published},
        "frozen_at": frozen, "replay_as_of": published if replay else None,
        "evidence_class": "replay" if replay else "prospective", "usage": usage, "story_id": "cmt-test",
        "engine": {"provider": "manual", "model": "test", "prompt_hash": "b" * 64},
        "summary": "A synthetic hypothesis on two Treasury maturities for lifecycle tests.",
        "nodes": [{"id": "event", "label": "Event", "kind": "event"},
                  {"id": "ten", "label": "10-year CMT", "kind": "observable"},
                  {"id": "two", "label": "2-year CMT", "kind": "observable"}],
        "edges": [{"source": "event", "target": "ten"}, {"source": "event", "target": "two"}],
        "legs": [{**leg, "id": "primary", "node_id": "ten", "primary": True, "channel": "term_premium",
                  "observable_id": "yield:ust10y_cmt", "expected": "up", "horizon": horizon,
                  "rationale": "Long-end repricing."},
                 {**leg, "id": "secondary", "node_id": "two", "primary": False, "channel": "policy_path",
                  "observable_id": "yield:ust2y_cmt", "expected": "up", "horizon": 1,
                  "rationale": "Front-end repricing."}],
    })


def anchor_dates(hyp, data):
    result = anchors(hyp, data)
    return tuple(ny_date(data.observations[i].at) for i in (result.event_index, result.score_index,
                                                              result.reference_end)), result.reason


class DailyAnchorTests(unittest.TestCase):
    def test_publication_date_is_excluded_from_reference_history(self):
        hyp = cmt_hypothesis(ny(2025, 6, 10, 9), ny(2025, 6, 10, 9, 5))
        dates, reason = anchor_dates(hyp, daily_series())
        self.assertEqual(dates, (date(2025, 6, 9), date(2025, 6, 11), date(2025, 6, 9)))
        self.assertEqual(reason, "daily_first_date_after_freeze_date")

    def test_scoring_compares_new_york_dates_not_intraday_times_or_utc_dates(self):
        data = daily_series()
        cases = [
            (ny(2025, 6, 10, 15, 45), date(2025, 6, 11)),  # After 3:30 PM, still the freeze date.
            (datetime(2025, 6, 11, 3, 30, tzinfo=timezone.utc), date(2025, 6, 11)),  # 23:30 New York, June 10.
            (ny(2025, 6, 11, 0, 30), date(2025, 6, 12)),
            (datetime(2025, 3, 10, 3, 30, tzinfo=timezone.utc), date(2025, 3, 10)),  # Sunday night after DST.
        ]
        for frozen, expected in cases:
            with self.subTest(frozen=frozen.isoformat()):
                published = min(frozen, ny(2025, 3, 7, 9))
                dates, _ = anchor_dates(cmt_hypothesis(published, frozen), data)
                self.assertEqual(dates[1], expected)

    def test_replay_scores_from_the_last_date_before_publication(self):
        hyp = cmt_hypothesis(ny(2025, 6, 10, 9), ny(2025, 6, 10, 9, 5), replay=True)
        dates, reason = anchor_dates(hyp, daily_series())
        self.assertEqual(dates, (date(2025, 6, 9),) * 3)
        self.assertEqual(reason, "daily_replay_before_publication_date")

    def test_missing_post_freeze_data_is_pending_when_open_ended_else_unavailable(self):
        hyp = cmt_hypothesis(ny(2025, 6, 10, 9), ny(2025, 6, 10, 9, 5))
        through = [day for day in SESSIONS if day <= date(2025, 6, 10)]
        as_of = ny(2025, 7, 1, 12)
        for open_ended, verdict in ((True, "pending"), (False, "unavailable")):
            with self.subTest(open_ended=open_ended):
                data = daily_series(days=through, open_ended=open_ended)
                leg = evaluate(hyp, {"yield:ust10y_cmt": data}, as_of)["legs"][0]
                self.assertEqual(leg["verdict"], verdict)

    def test_horizon_beyond_the_imported_data_is_pending(self):
        hyp = cmt_hypothesis(ny(2025, 6, 10, 9), ny(2025, 6, 10, 9, 5))
        data = daily_series(days=[day for day in SESSIONS if day <= date(2025, 6, 13)])
        leg = evaluate(hyp, {"yield:ust10y_cmt": data}, ny(2025, 7, 1, 12))["legs"][0]
        self.assertEqual((leg["verdict"], leg["reason"]), ("pending", "The scored horizon is not in the imported data yet"))

    def test_convention_is_recorded_and_the_research_timestamp_gate_is_unchanged(self):
        hyp = cmt_hypothesis(ny(2025, 6, 10, 9), ny(2025, 6, 10, 9, 5))
        data = {"yield:ust10y_cmt": daily_series()}
        leg = evaluate(hyp, data, ny(2025, 7, 1, 12))["legs"][0]
        self.assertIn(leg["verdict"], {"supported", "contradicted", "inconclusive"})
        self.assertIn("no intraday observation time is verified", leg["measurement_convention"])
        research = Hypothesis.model_validate({**hyp.model_dump(), "usage": "research"})
        leg = evaluate(research, data, ny(2025, 7, 1, 12))["legs"][0]
        self.assertEqual((leg["verdict"], leg["reason"]), ("unavailable", "Research requires verified observation timestamps"))

    def test_missing_value_inside_the_scored_window_is_unavailable_and_not_compressed(self):
        hyp = cmt_hypothesis(ny(2025, 6, 10, 9), ny(2025, 6, 10, 9, 5))
        values = [None if day == date(2025, 6, 12) else 4.0 + i / 1000 for i, day in enumerate(SESSIONS)]
        leg = evaluate(hyp, {"yield:ust10y_cmt": daily_series(values=values)}, ny(2025, 7, 1, 12))["legs"][0]
        self.assertEqual(ny_date(datetime.fromisoformat(leg["target_at"])), date(2025, 6, 18))
        self.assertEqual(leg["verdict"], "unavailable")

    def test_a_calendar_holiday_is_not_a_session_in_the_horizon(self):
        hyp = cmt_hypothesis(ny(2025, 6, 17, 9), ny(2025, 6, 17, 9, 5), horizon=1)
        leg = evaluate(hyp, {"yield:ust10y_cmt": daily_series()}, ny(2025, 7, 1, 12))["legs"][0]
        # Score anchor June 18; Juneteenth (June 19) is not a session, so one session later is June 20.
        self.assertEqual(ny_date(datetime.fromisoformat(leg["target_at"])), date(2025, 6, 20))


class ReconciliationTests(unittest.TestCase):
    rows = [(date(2024, 11, 8), 4.31), (date(2024, 11, 11), None), (date(2024, 11, 12), 4.43),
            (date(2024, 11, 13), None), (date(2024, 11, 15), 4.44)]

    def test_the_sifma_schedule_is_documentation_for_known_days(self):
        november = expected_sessions(date(2024, 11, 1), date(2024, 11, 30))
        self.assertNotIn(date(2024, 11, 11), november)  # Veterans Day: bond market closed, NYSE open.
        self.assertNotIn(date(2024, 11, 28), november)
        self.assertIn(date(2024, 11, 29), november)  # Early close is still a session.

    def test_explained_holidays_leave_the_grid_and_unexplained_gaps_stay_missing(self):
        sessions = expected_sessions(date(2024, 11, 8), date(2024, 11, 15))
        classified = reconcile("DGS10", self.rows, sessions, {"version": "t", "exceptions": []})
        self.assertEqual({day: status for day, _, status in classified}, {
            date(2024, 11, 8): "session_value", date(2024, 11, 11): "calendar_holiday",
            date(2024, 11, 12): "session_value", date(2024, 11, 13): "session_missing",
            date(2024, 11, 14): "session_absent", date(2024, 11, 15): "session_value"})
        self.assertEqual(observation_grid(classified), [
            (date(2024, 11, 8), 4.31), (date(2024, 11, 12), 4.43), (date(2024, 11, 13), None),
            (date(2024, 11, 14), None), (date(2024, 11, 15), 4.44)])

    def test_discrepancies_are_kept_as_missing_unless_an_issuer_sourced_exception_explains_them(self):
        rows = [(date(2024, 11, 8), 4.31), (date(2024, 11, 11), 4.40), (date(2024, 11, 12), None)]
        sessions = expected_sessions(date(2024, 11, 8), date(2024, 11, 12))
        plain = observation_grid(reconcile("DGS10", rows, sessions, {"version": "t", "exceptions": []}))
        self.assertEqual(plain, [(date(2024, 11, 8), 4.31), (date(2024, 11, 11), None), (date(2024, 11, 12), None)])
        source = "https://home.treasury.gov/example-notice"
        documented = {"version": "t", "exceptions": [
            {"series": "DGS10", "date": "2024-11-11", "kind": "issuer_observation_on_calendar_holiday", "source": source},
            {"series": "*", "date": "2024-11-12", "kind": "issuer_no_observation", "source": source}]}
        self.assertEqual(observation_grid(reconcile("DGS10", rows, sessions, documented)),
                         [(date(2024, 11, 8), 4.31), (date(2024, 11, 11), 4.40)])

    def test_exceptions_are_versioned_and_must_cite_issuer_documentation(self):
        self.assertEqual(load_exceptions()["version"], "1")
        valid = {"series": "DGS10", "date": "2024-11-11", "kind": "issuer_no_observation",
                 "source": "https://home.treasury.gov/example-notice"}
        bad = [{"exceptions": [valid]}, {"version": "2", "exceptions": [{**valid, "source": "http://x"}]},
               {"version": "2", "exceptions": [{**valid, "kind": "guess"}]},
               {"version": "2", "exceptions": [valid, valid]}]
        with tempfile.TemporaryDirectory() as folder:
            for i, payload in enumerate(bad):
                path = Path(folder) / f"{i}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(case=i), self.assertRaises(ValueError):
                    load_exceptions(path)
        self.assertTrue(EXCEPTIONS_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
