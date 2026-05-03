"""Tests for cohort_research — batch research across event cohorts."""

from __future__ import annotations

import unittest

from cohort_research import (
    SCENARIO_PACKS,
    REPRICING_LABELS,
    _DEEP_SIZE,
    _HOLD_THRESHOLD_PCT,
    _THIN_SIZE,
    _TYPICAL_SHARE,
    run_batch_research,
    select_cohort,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _ticker(symbol: str, role: str, r5: float | None, r20: float | None) -> dict:
    return {"symbol": symbol, "role": role, "return_5d": r5, "return_20d": r20}


def _event(
    eid: int,
    family: str = "none",
    stage: str = "confirmed",
    persistence: str = "medium",
    tickers=None,
    date: str | None = None,
) -> dict:
    return {
        "id": eid,
        "headline": f"Headline {eid}",
        "event_date": date or f"2025-01-{eid:02d}",
        "mechanism_family": family,
        "stage": stage,
        "persistence": persistence,
        "market_tickers": tickers or [],
    }


# ---------------------------------------------------------------------------
# Cohort selection
# ---------------------------------------------------------------------------

class TestSelectCohort(unittest.TestCase):
    def test_empty_input(self):
        r = select_cohort([])
        self.assertEqual(r["size"], 0)
        self.assertEqual(r["members"], [])

    def test_none_input(self):
        r = select_cohort(None)
        self.assertEqual(r["size"], 0)

    def test_select_by_single_family(self):
        evs = [_event(1, "tariff"), _event(2, "sanction"), _event(3, "tariff")]
        r = select_cohort(evs, mechanism_family="tariff")
        self.assertEqual(r["size"], 2)
        self.assertEqual({m["id"] for m in r["members"]}, {1, 3})

    def test_select_by_multiple_families(self):
        evs = [_event(1, "tariff"), _event(2, "sanction"), _event(3, "bank_stress")]
        r = select_cohort(evs, mechanism_family={"tariff", "sanction"})
        self.assertEqual(r["size"], 2)

    def test_select_by_scenario_pack(self):
        evs = [
            _event(1, "supply_shock"),
            _event(2, "commodity_squeeze"),
            _event(3, "sanction"),
        ]
        r = select_cohort(evs, scenario_pack="supply_squeeze")
        self.assertEqual(r["size"], 2)
        self.assertIn("supply_squeeze", r["filter"]["scenario_pack"])

    def test_scenario_pack_unknown_is_ignored(self):
        evs = [_event(1, "tariff")]
        # Unknown pack name falls through; no filter applied, so all pass
        r = select_cohort(evs, scenario_pack="not_a_pack")
        self.assertEqual(r["size"], 1)

    def test_select_by_transmission_cluster(self):
        evs = [
            _event(1, "tariff"),
            _event(2, "tariff"),
            _event(3, "tariff"),
        ]
        cluster = {
            "cluster_id": 0, "kind": "family_channels", "family": "tariff",
            "size": 2,
            "members": [
                {"event_id": 1, "headline": "Headline 1"},
                {"event_id": 3, "headline": "Headline 3"},
            ],
        }
        r = select_cohort(evs, transmission_cluster=cluster)
        self.assertEqual(r["size"], 2)
        self.assertEqual({m["id"] for m in r["members"]}, {1, 3})

    def test_cluster_matches_by_headline_when_id_missing(self):
        evs = [_event(1, "tariff"), _event(2, "tariff")]
        cluster = {
            "cluster_id": 0, "kind": "family_channels", "family": "tariff",
            "members": [{"event_id": None, "headline": "Headline 2"}],
        }
        r = select_cohort(evs, transmission_cluster=cluster)
        self.assertEqual(r["size"], 1)
        self.assertEqual(r["members"][0]["id"], 2)

    def test_compose_family_and_stage(self):
        evs = [
            _event(1, "tariff", stage="confirmed"),
            _event(2, "tariff", stage="anticipated"),
            _event(3, "sanction", stage="confirmed"),
        ]
        r = select_cohort(evs, mechanism_family="tariff", stage="confirmed")
        self.assertEqual(r["size"], 1)
        self.assertEqual(r["members"][0]["id"], 1)

    def test_compose_with_persistence(self):
        evs = [
            _event(1, "tariff", persistence="persistent"),
            _event(2, "tariff", persistence="transient"),
        ]
        r = select_cohort(evs, mechanism_family="tariff", persistence="persistent")
        self.assertEqual(r["size"], 1)

    def test_date_range_filter(self):
        evs = [
            _event(1, "tariff", date="2025-03-10"),
            _event(2, "tariff", date="2025-04-20"),
            _event(3, "tariff", date="2025-06-01"),
        ]
        r = select_cohort(evs, mechanism_family="tariff",
                          date_range=("2025-04-01", "2025-05-31"))
        self.assertEqual(r["size"], 1)
        self.assertEqual(r["members"][0]["id"], 2)

    def test_non_dict_events_skipped(self):
        evs = [_event(1, "tariff"), None, "garbage", 42, _event(2, "tariff")]
        r = select_cohort(evs, mechanism_family="tariff")
        self.assertEqual(r["size"], 2)


# ---------------------------------------------------------------------------
# Batch scoring — persistence
# ---------------------------------------------------------------------------

class TestPersistenceScoring(unittest.TestCase):
    def test_all_held(self):
        evs = [
            _event(i, "tariff", tickers=[_ticker("AAA", "beneficiary", 2.0, 4.0)])
            for i in range(1, 5)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["persistence"]["distribution"]["held"], 4)
        self.assertEqual(r["persistence"]["distribution"]["faded"], 0)
        self.assertEqual(r["persistence"]["hold_rate"], 1.0)

    def test_all_faded(self):
        evs = [
            _event(i, "tariff", tickers=[_ticker("AAA", "beneficiary", 0.1, 0.2)])
            for i in range(1, 4)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["persistence"]["distribution"]["held"], 0)
        self.assertEqual(r["persistence"]["distribution"]["faded"], 3)
        self.assertEqual(r["persistence"]["hold_rate"], 0.0)

    def test_mixed_persistence(self):
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)]),
            _event(2, "tariff", tickers=[_ticker("A", "beneficiary", 0.1, 0.2)]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["persistence"]["hold_rate"], 0.5)

    def test_unknown_when_no_return_data(self):
        evs = [_event(1, "tariff", tickers=[])]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["persistence"]["distribution"]["unknown"], 1)
        self.assertEqual(r["persistence"]["hold_rate"], 0.0)

    def test_mean_and_median_20d_reported(self):
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)]),
            _event(2, "tariff", tickers=[_ticker("A", "beneficiary", 1.0, 2.0)]),
            _event(3, "tariff", tickers=[_ticker("A", "beneficiary", 3.0, 6.0)]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["persistence"]["mean_20d"], 4.0)
        self.assertEqual(r["persistence"]["median_abs_20d"], 4.0)


# ---------------------------------------------------------------------------
# Batch scoring — repricing path
# ---------------------------------------------------------------------------

class TestRepricingPath(unittest.TestCase):
    def test_typical_holding(self):
        # Holding decay: 5d magnitude = 40–80% of 20d magnitude
        # e.g., r5=2.0, r20=4.0 → r5/r20 = 0.5 → Holding
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])
            for i in range(1, 6)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["repricing_path"]["typical"], "holding")
        self.assertGreater(r["repricing_path"]["typical_share"], 0.5)

    def test_typical_fading(self):
        # Fading: abs5 < 40% of abs20.  r5=0.5, r20=4.0 → 0.125 → Fading
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", 0.5, 4.0)])
            for i in range(1, 5)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["repricing_path"]["typical"], "fading")

    def test_typical_reversed(self):
        # Both above noise, sign flip → Reversed
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", -2.0, 4.0)])
            for i in range(1, 5)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["repricing_path"]["typical"], "reversed")

    def test_mixed_when_no_clear_mode(self):
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)]),   # Holding
            _event(2, "tariff", tickers=[_ticker("A", "beneficiary", 0.5, 4.0)]),   # Fading
            _event(3, "tariff", tickers=[_ticker("A", "beneficiary", -2.0, 4.0)]),  # Reversed
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        # 1/3 share < 0.5 → mixed
        self.assertEqual(r["repricing_path"]["typical"], "mixed")

    def test_all_reprice_labels_pinned(self):
        self.assertIn("Accelerating", REPRICING_LABELS)
        self.assertIn("Holding", REPRICING_LABELS)
        self.assertIn("Fading", REPRICING_LABELS)
        self.assertIn("Reversed", REPRICING_LABELS)
        self.assertIn("Negligible", REPRICING_LABELS)
        self.assertIn("Unknown", REPRICING_LABELS)


# ---------------------------------------------------------------------------
# Batch scoring — falsification
# ---------------------------------------------------------------------------

class TestFalsification(unittest.TestCase):
    def test_beneficiary_down_is_contradiction(self):
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "beneficiary", -2.0, -4.0)]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["falsification"]["failed_events"], 1)
        self.assertEqual(r["falsification"]["ticker_contradictions"], 1)
        self.assertEqual(r["falsification"]["ticker_failure_rate"], 1.0)

    def test_loser_up_is_contradiction(self):
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "loser", 2.0, 4.0)]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["falsification"]["ticker_contradictions"], 1)

    def test_aligned_tickers_not_counted(self):
        evs = [
            _event(1, "tariff", tickers=[
                _ticker("A", "beneficiary", 2.0, 4.0),
                _ticker("B", "loser", -2.0, -4.0),
            ]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["falsification"]["ticker_contradictions"], 0)
        self.assertEqual(r["falsification"]["failed_events"], 0)

    def test_partial_contradiction_not_event_failure(self):
        evs = [
            _event(1, "tariff", tickers=[
                _ticker("A", "beneficiary", 2.0, 4.0),
                _ticker("B", "beneficiary", -2.0, -4.0),
                _ticker("C", "beneficiary", 2.0, 4.0),
            ]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        # 1/3 contradicted — below 0.5 share → not a wholesale failure
        self.assertEqual(r["falsification"]["failed_events"], 0)
        self.assertEqual(r["falsification"]["ticker_contradictions"], 1)

    def test_tickers_below_hold_threshold_not_counted_as_contradiction(self):
        # Beneficiary with r20 = -0.2 (below HOLD_THRESHOLD 0.5) is just
        # noise, not a contradiction.
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "beneficiary", -0.1, -0.2)]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["falsification"]["ticker_contradictions"], 0)

    def test_unscorable_tickers_skipped(self):
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "beneficiary", None, None)]),
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["falsification"]["scored_events"], 0)
        self.assertEqual(r["falsification"]["scored_tickers"], 0)


# ---------------------------------------------------------------------------
# Confidence basis
# ---------------------------------------------------------------------------

class TestConfidenceBasis(unittest.TestCase):
    def test_thin_when_small(self):
        evs = [_event(1, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["confidence_basis"], "thin")

    def test_medium_between_thresholds(self):
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])
            for i in range(1, 6)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["confidence_basis"], "medium")

    def test_deep_when_large(self):
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])
            for i in range(1, 15)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["confidence_basis"], "deep")

    def test_thin_when_members_but_no_scored_returns(self):
        evs = [_event(i, "tariff", tickers=[]) for i in range(1, 15)]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["confidence_basis"], "thin")


# ---------------------------------------------------------------------------
# Summary prose
# ---------------------------------------------------------------------------

class TestSummary(unittest.TestCase):
    def test_summary_mentions_size(self):
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])
            for i in range(1, 6)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertIn("5 events", r["summary"])

    def test_thin_summary_warns(self):
        evs = [_event(1, "tariff")]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertIn("too few", r["summary"].lower())

    def test_empty_cohort_summary(self):
        r = run_batch_research([], mechanism_family="tariff")
        self.assertEqual(r["size"], 0)
        self.assertIn("no events", r["summary"].lower())

    def test_summary_emits_typical_path(self):
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])
            for i in range(1, 6)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertIn("holding", r["summary"].lower())


# ---------------------------------------------------------------------------
# End-to-end shape + scenarios
# ---------------------------------------------------------------------------

class TestTopLevel(unittest.TestCase):
    def test_full_report_shape(self):
        evs = [
            _event(i, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])
            for i in range(1, 6)
        ]
        r = run_batch_research(evs, mechanism_family="tariff")
        for key in [
            "cohort_label", "filter", "size", "members",
            "persistence", "repricing_path", "falsification",
            "confidence_basis", "summary", "rationale",
        ]:
            self.assertIn(key, r, f"missing key: {key}")
        self.assertEqual(r["size"], 5)
        self.assertEqual(len(r["members"]), 5)

    def test_scenario_pack_label(self):
        evs = [_event(i, "supply_shock",
                      tickers=[_ticker("A", "beneficiary", 2.0, 4.0)])
               for i in range(1, 6)]
        r = run_batch_research(evs, scenario_pack="supply_squeeze")
        self.assertEqual(r["cohort_label"], "supply_squeeze")

    def test_transmission_cluster_input(self):
        evs = [
            _event(1, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)]),
            _event(2, "tariff", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)]),
            _event(3, "sanction", tickers=[_ticker("A", "beneficiary", 2.0, 4.0)]),
        ]
        cluster = {
            "cluster_id": 0, "kind": "family_channels", "family": "tariff",
            "members": [
                {"event_id": 1, "headline": "Headline 1"},
                {"event_id": 2, "headline": "Headline 2"},
            ],
        }
        r = run_batch_research(evs, transmission_cluster=cluster)
        self.assertEqual(r["size"], 2)

    def test_scenario_packs_pinned(self):
        for key in ("tariff_cycle", "supply_squeeze", "funding_squeeze"):
            self.assertIn(key, SCENARIO_PACKS)

    def test_constants_pinned(self):
        self.assertEqual(_HOLD_THRESHOLD_PCT, 0.5)
        self.assertEqual(_THIN_SIZE, 3)
        self.assertEqual(_DEEP_SIZE, 10)
        self.assertEqual(_TYPICAL_SHARE, 0.5)


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------

class TestDefensive(unittest.TestCase):
    def test_event_with_no_tickers_key(self):
        evs = [{"id": 1, "mechanism_family": "tariff", "stage": "confirmed"}]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["size"], 1)
        self.assertEqual(r["persistence"]["distribution"]["unknown"], 1)

    def test_malformed_tickers_list(self):
        evs = [{
            "id": 1, "mechanism_family": "tariff",
            "market_tickers": ["not a dict", None, {"role": "beneficiary"}],
        }]
        r = run_batch_research(evs, mechanism_family="tariff")
        self.assertEqual(r["size"], 1)

    def test_none_events_input(self):
        r = run_batch_research(None, mechanism_family="tariff")
        self.assertEqual(r["size"], 0)
        self.assertEqual(r["confidence_basis"], "thin")


if __name__ == "__main__":
    unittest.main()
