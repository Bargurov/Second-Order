"""Outcome coverage: missing leading dates must never move the scoring anchor or compress the horizon.

The hypotheses here are records frozen before freshness policy B (their baselines end before the last session before
publication), stored exactly as such records are, so these tests show how existing records evaluate."""
from datetime import date, datetime, timedelta
import unittest
from unittest.mock import patch
from fred_fixtures import FakeFred, datasets
from second_order.data import ny_date
from second_order.snapshots import (Snapshot, evaluate_bound, list_snapshots, load_snapshot, snapshot_readiness,
                                    snapshot_revisions)
from second_order.store import open_store
from store_records import stored_before_policy_b
from test_daily import cmt_hypothesis, ny
from test_fred import run_import
from test_lifecycle import AS_OF, FROZEN, PUBLISHED, when


def days_of(leg: dict) -> dict:
    return {key: ny_date(datetime.fromisoformat(leg[key])) for key in ("score_anchor", "target_at") if key in leg}


class OutcomeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.store = open_store()
        self.baseline = run_import(self.store, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)),
                                   date(2025, 6, 2), when(date(2025, 6, 2)))["snapshot_id"]
        self.hypothesis = cmt_hypothesis(PUBLISHED, FROZEN)
        self.identity = stored_before_policy_b(self.store, self.hypothesis, FROZEN, self.baseline)

    def tearDown(self):
        self.store.close()

    def outcome(self, fake, start=date(2023, 1, 2), vintage=date(2025, 6, 20), hour=22):
        return run_import(self.store, fake, vintage, when(vintage, hour), start=start)["snapshot_id"]

    def test_full_outcome_scores_june_4_to_june_11(self):
        leg = evaluate_bound(self.store, self.identity, self.outcome(FakeFred(datasets(date(2025, 6, 18)),
                                                                              date(2025, 6, 20))), AS_OF)["legs"][0]
        self.assertEqual(days_of(leg), {"score_anchor": date(2025, 6, 4), "target_at": date(2025, 6, 11)})
        self.assertAlmostEqual(leg["measured_change"], -13.0, places=6)

    def test_an_outcome_requested_from_a_late_start_is_refused(self):
        late = self.outcome(FakeFred(datasets(date(2025, 6, 18)), date(2025, 6, 20)), start=date(2025, 6, 10))
        with self.assertRaisesRegex(ValueError, "must start on or before the publication date"):
            evaluate_bound(self.store, self.identity, late, AS_OF)

    def test_missing_leading_sessions_despite_an_early_request_cannot_shift_the_anchor(self):
        drop_early = lambda payload: {**payload, "observations": [row for row in payload["observations"]
                                                                  if row["date"] >= "2025-06-10"]}
        fake = FakeFred(datasets(date(2025, 6, 18)), date(2025, 6, 20),
                        patch_observations={"DGS2": drop_early, "DGS10": drop_early})
        leg = evaluate_bound(self.store, self.identity, self.outcome(fake), AS_OF)["legs"][0]
        self.assertEqual(days_of(leg), {"score_anchor": date(2025, 6, 4), "target_at": date(2025, 6, 11)})
        self.assertEqual(leg["verdict"], "unavailable")

    def test_an_interior_missing_session_is_unavailable_not_compressed(self):
        fake = FakeFred(datasets(date(2025, 6, 18), {"DGS10": {date(2025, 6, 6): "."}}), date(2025, 6, 20))
        leg = evaluate_bound(self.store, self.identity, self.outcome(fake), AS_OF)["legs"][0]
        self.assertEqual(days_of(leg), {"score_anchor": date(2025, 6, 4), "target_at": date(2025, 6, 11)})
        self.assertEqual(leg["verdict"], "unavailable")

    def test_a_holiday_inside_the_outcome_horizon_is_not_a_session(self):
        later = cmt_hypothesis(ny(2025, 6, 17, 9), ny(2025, 6, 17, 9, 30), horizon=1)
        identity = stored_before_policy_b(self.store, later, later.frozen_at, self.baseline)
        fake = FakeFred(datasets(date(2025, 6, 24)), date(2025, 6, 25))
        leg = evaluate_bound(self.store, identity, self.outcome(fake, vintage=date(2025, 6, 25)),
                             when(date(2025, 6, 26)))["legs"][0]
        self.assertEqual(days_of(leg), {"score_anchor": date(2025, 6, 18), "target_at": date(2025, 6, 20)})
        self.assertIn(leg["verdict"], {"supported", "contradicted", "inconclusive"})

    def test_a_not_yet_imported_future_horizon_stays_pending(self):
        fake = FakeFred(datasets(date(2025, 6, 6)), date(2025, 6, 9))
        leg = evaluate_bound(self.store, self.identity, self.outcome(fake, vintage=date(2025, 6, 9)), AS_OF)["legs"][0]
        self.assertEqual(leg["verdict"], "pending")


SCORED = {"supported", "contradicted", "inconclusive"}
drop_dates = lambda keep: (lambda payload: {**payload, "observations": [row for row in payload["observations"]
                                                                         if keep(row["date"])]})


class CoverageBoundaryTests(unittest.TestCase):
    """Coverage is the requested classification boundary, not the first observation date."""

    def setUp(self):
        self.store = open_store()

    def tearDown(self):
        self.store.close()

    def bound(self, published, frozen, baseline_vintage):
        through = baseline_vintage - timedelta(days=1)
        baseline = run_import(self.store, FakeFred(datasets(through), baseline_vintage), baseline_vintage,
                              when(baseline_vintage))["snapshot_id"]
        return stored_before_policy_b(self.store, cmt_hypothesis(published, frozen), frozen, baseline)

    def outcome(self, start, through, vintage, patch=None, hour=22):
        fake = FakeFred(datasets(through), vintage, patch_observations=patch or {})
        return run_import(self.store, fake, vintage, when(vintage, hour), start=start)["snapshot_id"]

    def sunday(self):
        return self.bound(ny(2025, 6, 1, 9), ny(2025, 6, 1, 9, 30), date(2025, 5, 30))

    def test_a_sunday_publication_with_an_outcome_requested_from_that_sunday_is_accepted(self):
        identity = self.sunday()
        leg = evaluate_bound(self.store, identity, self.outcome(date(2025, 6, 1), date(2025, 6, 18), date(2025, 6, 20)),
                             AS_OF)["legs"][0]
        self.assertEqual(days_of(leg), {"score_anchor": date(2025, 6, 2), "target_at": date(2025, 6, 9)})
        self.assertIn(leg["verdict"], SCORED)

    def test_a_holiday_publication_without_a_provider_row_is_accepted(self):
        identity = self.bound(ny(2025, 7, 4, 9), ny(2025, 7, 4, 9, 30), date(2025, 7, 2))
        no_row = drop_dates(lambda day: day != "2025-07-04")
        outcome = self.outcome(date(2025, 7, 4), date(2025, 7, 18), date(2025, 7, 21), {"DGS2": no_row, "DGS10": no_row})
        leg = evaluate_bound(self.store, identity, outcome, when(date(2025, 7, 22)))["legs"][0]
        self.assertEqual(days_of(leg), {"score_anchor": date(2025, 7, 7), "target_at": date(2025, 7, 14)})
        self.assertIn(leg["verdict"], SCORED)

    def test_a_late_start_after_a_weekend_publication_is_still_refused(self):
        identity = self.sunday()
        late = self.outcome(date(2025, 6, 3), date(2025, 6, 18), date(2025, 6, 20))  # Would hide Monday, June 2.
        with self.assertRaisesRegex(ValueError, "must start on or before the publication date"):
            evaluate_bound(self.store, identity, late, AS_OF)

    def test_omitted_leading_sessions_after_a_weekend_publication_stay_unavailable(self):
        identity = self.sunday()
        gap = drop_dates(lambda day: day >= "2025-06-05")
        outcome = self.outcome(date(2025, 6, 1), date(2025, 6, 18), date(2025, 6, 20), {"DGS2": gap, "DGS10": gap})
        leg = evaluate_bound(self.store, identity, outcome, AS_OF)["legs"][0]
        self.assertEqual(days_of(leg), {"score_anchor": date(2025, 6, 2), "target_at": date(2025, 6, 9)})
        self.assertEqual(leg["verdict"], "unavailable")

    def test_the_stored_boundary_is_explicit_and_older_snapshots_fall_back_conservatively(self):
        self.sunday()
        fresh = load_snapshot(self.store, self.outcome(date(2025, 6, 1), date(2025, 6, 18), date(2025, 6, 20)))
        series = fresh.payload["series"]["DGS10"]
        self.assertEqual((series["classified_from"], series["first_date"], series["first_classified_date"]),
                         ("2025-06-01", "2025-06-02", "2025-06-02"))
        classified = {"DGS10": [(date(2025, 6, 2), 4.0, "session_value")]}
        request = {"observation_start": "2025-06-01"}
        snapshots = {
            "fred-1": Snapshot("a", {"adapter_version": "fred-1", "request": request, "series": {"DGS10": {}}}, classified),
            "fred-2": Snapshot("b", {"adapter_version": "fred-2", "request": request, "series": {"DGS10": {}}}, classified),
        }
        self.assertEqual(snapshots["fred-1"].classified_from("DGS10"), date(2025, 6, 2))  # Only what it shows.
        self.assertEqual(snapshots["fred-2"].classified_from("DGS10"), date(2025, 6, 1))  # Classified from request.

    def test_reads_never_fetch_data_or_recompute_calendars(self):
        identity = self.sunday()
        outcome = self.outcome(date(2025, 6, 1), date(2025, 6, 18), date(2025, 6, 20))
        baseline = self.store.execute("SELECT baseline_snapshot_id FROM freeze_bindings").fetchone()[0]
        forbidden = AssertionError("A read path fetched data or recomputed a calendar")
        with patch("second_order.market_calendar.expected_sessions", side_effect=forbidden), \
                patch("second_order.fred.expected_sessions", side_effect=forbidden), \
                patch("pandas_market_calendars.get_calendar", side_effect=forbidden), \
                patch("httpx.Client.send", side_effect=forbidden), \
                patch("socket.socket.connect", side_effect=forbidden):
            self.assertIn(evaluate_bound(self.store, identity, outcome, AS_OF)["legs"][0]["verdict"], SCORED)
            snapshot_readiness(load_snapshot(self.store, baseline), before=date(2025, 6, 1))
            snapshot_revisions(load_snapshot(self.store, baseline), load_snapshot(self.store, outcome))
            self.assertEqual(len(list_snapshots(self.store)), 2)


if __name__ == "__main__":
    unittest.main()
