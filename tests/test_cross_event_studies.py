"""
tests/test_cross_event_studies.py

Contract tests for archive-native cross-event correlation studies.

Covers:
  1. Empty archive — shaped-empty block, not {}.
  2. Family co-occurrence — 7d window, singleton filter, top-N cap,
     event_ids provenance.
  3. Sector clusters — pair co-occurrence over ticker-derived sectors,
     singleton filter, top-N cap.
  4. Path clusters — channel-only signatures, singleton filter,
     family distribution per cluster.
  5. Combination outcomes — family × sector hit rates, minimum-sample
     floor, signal-strength sort order.
  6. Output discipline — every row carries event_ids; empty archive
     stays shaped; timestamp format.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from cross_event_studies import (
    _COOCCURRENCE_WINDOW_DAYS,
    _MAX_EVENT_IDS_PER_ROW,
    _MIN_COMBO_COUNT,
    _MIN_PAIR_COUNT,
    _TOP_N_COOCCURRENCE_PAIRS,
    _TOP_N_SECTOR_PAIRS,
    _TOP_N_PATH_CLUSTERS,
    compute_cross_event_studies,
)


def _event(
    eid: int,
    date: str,
    family: str,
    *,
    beneficiary_tickers: list[str] | None = None,
    loser_tickers: list[str] | None = None,
    transmission_path: list[dict] | None = None,
    market_tickers: list[dict] | None = None,
) -> dict:
    return {
        "id":                   eid,
        "event_date":           date,
        "mechanism_family":     family,
        "beneficiary_tickers":  json.dumps(beneficiary_tickers or []),
        "loser_tickers":        json.dumps(loser_tickers or []),
        "transmission_path":    json.dumps(transmission_path or []),
        "market_tickers":       json.dumps(market_tickers or []),
        "revisit_snapshots":    json.dumps([]),
    }


# ---------------------------------------------------------------------------
# 1. Empty-archive behavior
# ---------------------------------------------------------------------------

class TestEmptyArchive(unittest.TestCase):

    def test_empty_list_returns_shaped_block(self):
        block = compute_cross_event_studies([])
        self.assertEqual(block["total_events"], 0)
        self.assertEqual(block["family_cooccurrence"], [])
        self.assertEqual(block["sector_clusters"], [])
        self.assertEqual(block["path_clusters"], [])
        self.assertEqual(block["combination_outcomes"], [])
        self.assertEqual(block["window_days"], _COOCCURRENCE_WINDOW_DAYS)

    def test_non_dict_rows_are_filtered(self):
        block = compute_cross_event_studies([None, "not a dict", 42])
        self.assertEqual(block["total_events"], 0)

    def test_none_input_is_safe(self):
        block = compute_cross_event_studies(None)
        self.assertEqual(block["total_events"], 0)


# ---------------------------------------------------------------------------
# 2. Family co-occurrence
# ---------------------------------------------------------------------------

class TestFamilyCooccurrence(unittest.TestCase):

    def test_two_distinct_families_within_window_coalesce(self):
        events = [
            _event(1, "2026-03-01", "tariff"),
            _event(2, "2026-03-03", "sanction"),
            _event(3, "2026-03-04", "tariff"),
            _event(4, "2026-03-05", "sanction"),
        ]
        block = compute_cross_event_studies(events)
        pairs = block["family_cooccurrence"]
        self.assertTrue(pairs, "expected a family-pair row")
        top = pairs[0]
        self.assertEqual(
            tuple(sorted((top["family_a"], top["family_b"]))),
            ("sanction", "tariff"),
        )
        self.assertGreaterEqual(top["count"], _MIN_PAIR_COUNT)

    def test_events_outside_window_not_coupled(self):
        events = [
            _event(1, "2026-01-01", "tariff"),
            _event(2, "2026-04-01", "sanction"),  # 90d apart
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["family_cooccurrence"], [])

    def test_same_family_pairs_not_surfaced(self):
        """Same-family co-occurrence is just frequency, not co-occurrence —
        the study must filter it out."""
        events = [
            _event(1, "2026-03-01", "tariff"),
            _event(2, "2026-03-02", "tariff"),
            _event(3, "2026-03-03", "tariff"),
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["family_cooccurrence"], [])

    def test_singleton_pairs_filtered(self):
        events = [
            _event(1, "2026-03-01", "tariff"),
            _event(2, "2026-03-02", "sanction"),  # one pair, below MIN
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["family_cooccurrence"], [])

    def test_each_pair_has_event_ids(self):
        events = [
            _event(1, "2026-03-01", "tariff"),
            _event(2, "2026-03-02", "sanction"),
            _event(3, "2026-03-03", "tariff"),
            _event(4, "2026-03-04", "sanction"),
        ]
        block = compute_cross_event_studies(events)
        for row in block["family_cooccurrence"]:
            self.assertIn("event_ids", row)
            self.assertGreater(len(row["event_ids"]), 0)
            self.assertLessEqual(len(row["event_ids"]), _MAX_EVENT_IDS_PER_ROW)

    def test_window_days_exposed_on_row(self):
        events = [
            _event(1, "2026-03-01", "tariff"),
            _event(2, "2026-03-02", "sanction"),
            _event(3, "2026-03-03", "tariff"),
            _event(4, "2026-03-04", "sanction"),
        ]
        block = compute_cross_event_studies(events)
        for row in block["family_cooccurrence"]:
            self.assertEqual(row["window_days"], _COOCCURRENCE_WINDOW_DAYS)


# ---------------------------------------------------------------------------
# 3. Sector clusters
# ---------------------------------------------------------------------------

class TestSectorClusters(unittest.TestCase):

    def test_commodity_plus_credit_etfs_cluster(self):
        events = [
            _event(1, "2026-03-01", "bank_stress",
                    beneficiary_tickers=["HYG", "USO"]),
            _event(2, "2026-03-05", "supply_shock",
                    beneficiary_tickers=["HYG", "USO"]),
        ]
        block = compute_cross_event_studies(events)
        pairs = block["sector_clusters"]
        self.assertTrue(pairs)
        pair = tuple(sorted((pairs[0]["sector_a"], pairs[0]["sector_b"])))
        self.assertEqual(pair, ("commodities", "credit"))
        self.assertGreaterEqual(pairs[0]["count"], _MIN_PAIR_COUNT)

    def test_single_sector_event_yields_no_pair(self):
        events = [
            _event(1, "2026-03-01", "supply_shock",
                    beneficiary_tickers=["USO", "GLD"]),  # both → commodities
            _event(2, "2026-03-02", "supply_shock",
                    beneficiary_tickers=["USO", "GLD"]),
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["sector_clusters"], [])

    def test_singleton_pair_filtered(self):
        events = [
            _event(1, "2026-03-01", "bank_stress",
                    beneficiary_tickers=["HYG", "USO"]),
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["sector_clusters"], [])

    def test_sector_pairs_are_capped(self):
        # Forge a universe with many pairs to test the cap.
        events = []
        # Build 3 co-occurrences of 4 sectors
        for i in range(3):
            events.append(_event(
                100 + i, f"2026-03-0{i+1}", "supply_shock",
                beneficiary_tickers=["HYG", "USO", "TLT", "GLD"],
            ))
        block = compute_cross_event_studies(events)
        self.assertLessEqual(len(block["sector_clusters"]), _TOP_N_SECTOR_PAIRS)


# ---------------------------------------------------------------------------
# 4. Path clusters — channel-only signatures
# ---------------------------------------------------------------------------

class TestPathClusters(unittest.TestCase):

    def _path(self, channels: list[str]) -> list[dict]:
        return [{"hop": f"step {i}", "channel": c, "actor": f"actor-{i}"}
                for i, c in enumerate(channels)]

    def test_recurring_signature_clusters(self):
        events = [
            _event(1, "2026-03-01", "tariff",
                    transmission_path=self._path(["policy_gate", "supply", "pricing_power"])),
            _event(2, "2026-03-15", "tariff",
                    transmission_path=self._path(["policy_gate", "supply", "pricing_power"])),
        ]
        block = compute_cross_event_studies(events)
        clusters = block["path_clusters"]
        self.assertEqual(len(clusters), 1)
        cluster = clusters[0]
        self.assertEqual(cluster["signature"],
                         ["policy_gate", "supply", "pricing_power"])
        self.assertEqual(cluster["count"], 2)
        # Family distribution attached so cross-family path reuse is visible.
        self.assertIn("tariff", cluster["families"])

    def test_actor_differences_do_not_fragment_signature(self):
        """Channel-only signature — actors differ but the cluster holds."""
        events = [
            _event(1, "2026-03-01", "tariff", transmission_path=[
                {"hop": "x", "channel": "policy_gate", "actor": "US Treasury"},
                {"hop": "y", "channel": "supply",      "actor": "Chevron"},
            ]),
            _event(2, "2026-03-05", "tariff", transmission_path=[
                {"hop": "x", "channel": "policy_gate", "actor": "US Commerce"},
                {"hop": "y", "channel": "supply",      "actor": "ASML"},
            ]),
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(len(block["path_clusters"]), 1)

    def test_single_hop_paths_are_skipped(self):
        events = [
            _event(1, "2026-03-01", "tariff", transmission_path=[
                {"hop": "x", "channel": "policy_gate", "actor": "a"},
            ]),
            _event(2, "2026-03-02", "tariff", transmission_path=[
                {"hop": "x", "channel": "policy_gate", "actor": "b"},
            ]),
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["path_clusters"], [])

    def test_path_clusters_are_capped(self):
        events = []
        for i in range(_TOP_N_PATH_CLUSTERS + 5):
            # Different unique signatures, each repeated twice
            chans = [f"ch_{i}_a", f"ch_{i}_b"]
            events.append(_event(
                10 * i, f"2026-03-{(i%28)+1:02d}", "tariff",
                transmission_path=self._path(chans),
            ))
            events.append(_event(
                10 * i + 1, f"2026-03-{(i%28)+1:02d}", "tariff",
                transmission_path=self._path(chans),
            ))
        block = compute_cross_event_studies(events)
        self.assertLessEqual(len(block["path_clusters"]), _TOP_N_PATH_CLUSTERS)


# ---------------------------------------------------------------------------
# 5. Combination outcomes — family × sector hit rates
# ---------------------------------------------------------------------------

class TestCombinationOutcomes(unittest.TestCase):

    def _mt(self, support: int, contradict: int) -> list[dict]:
        """Build a market_tickers list that scores to the given outcome.
        _score_directions looks at direction_tag."""
        rows = []
        for i in range(support):
            rows.append({"symbol": f"S{i}", "direction_tag": "supports thesis",
                          "return_5d": 1.0})
        for i in range(contradict):
            rows.append({"symbol": f"C{i}", "direction_tag": "contradicts thesis",
                          "return_5d": -1.0})
        return rows

    def test_family_sector_combos_get_hit_rates(self):
        events = [
            _event(1, "2026-03-01", "supply_shock",
                    beneficiary_tickers=["USO"],
                    market_tickers=self._mt(2, 0)),
            _event(2, "2026-03-02", "supply_shock",
                    beneficiary_tickers=["USO"],
                    market_tickers=self._mt(2, 0)),
            _event(3, "2026-03-03", "supply_shock",
                    beneficiary_tickers=["USO"],
                    market_tickers=self._mt(2, 0)),
        ]
        block = compute_cross_event_studies(events)
        combos = block["combination_outcomes"]
        self.assertTrue(combos)
        row = combos[0]
        self.assertEqual(row["mechanism_family"], "supply_shock")
        self.assertEqual(row["sector"], "commodities")
        self.assertEqual(row["hit_rate"], 1.0)

    def test_small_samples_filtered(self):
        events = [
            _event(1, "2026-03-01", "supply_shock",
                    beneficiary_tickers=["USO"],
                    market_tickers=self._mt(2, 0)),
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["combination_outcomes"], [])

    def test_combos_sorted_by_signal_strength(self):
        """Combos with hit_rate far from 0.5 rank above middling ones."""
        events = []
        # A: family=supply_shock / sector=commodities → 3 validated (hit=1.0)
        for i in range(3):
            events.append(_event(
                100 + i, f"2026-03-0{i+1}", "supply_shock",
                beneficiary_tickers=["USO"],
                market_tickers=self._mt(2, 0),
            ))
        # B: family=bank_stress / sector=credit → mixed (hit ≈ 0.5)
        for i in range(3):
            events.append(_event(
                200 + i, f"2026-03-1{i}", "bank_stress",
                beneficiary_tickers=["HYG"],
                market_tickers=self._mt(1, 1),
            ))
        block = compute_cross_event_studies(events)
        combos = block["combination_outcomes"]
        self.assertGreaterEqual(len(combos), 2)
        # High-signal combo (hit=1.0) must rank above the mid-signal one.
        first = combos[0]
        self.assertEqual(first["hit_rate"], 1.0)

    def test_combo_count_capped(self):
        """Top-N limit is enforced regardless of number of unique combos."""
        events = []
        # Build many distinct family×sector combos
        sectors_tickers = {"commodities": "USO", "credit": "HYG",
                            "rates": "TLT"}
        families = ["supply_shock", "bank_stress", "tariff", "sanction",
                     "policy_surprise", "commodity_squeeze"]
        for fam in families:
            for sec, tk in sectors_tickers.items():
                for i in range(3):
                    events.append(_event(
                        hash((fam, sec, i)) & 0xFFFF,
                        f"2026-03-{(i % 28)+1:02d}", fam,
                        beneficiary_tickers=[tk],
                        market_tickers=self._mt(2, 0),
                    ))
        block = compute_cross_event_studies(events)
        from cross_event_studies import _TOP_N_COMBINATIONS
        self.assertLessEqual(len(block["combination_outcomes"]),
                             _TOP_N_COMBINATIONS)


# ---------------------------------------------------------------------------
# 6. Output discipline
# ---------------------------------------------------------------------------

class TestOutputDiscipline(unittest.TestCase):

    def test_generated_at_is_iso_format(self):
        block = compute_cross_event_studies([])
        self.assertIn("generated_at", block)
        # Parseable with fromisoformat
        from datetime import datetime
        datetime.fromisoformat(block["generated_at"].replace("Z", "+00:00"))

    def test_total_events_counts_only_dicts(self):
        events = [
            _event(1, "2026-03-01", "tariff"),
            None,
            _event(2, "2026-03-02", "sanction"),
            "not a dict",
        ]
        block = compute_cross_event_studies(events)
        self.assertEqual(block["total_events"], 2)

    def test_event_ids_present_on_every_cluster_row(self):
        events = [
            _event(1, "2026-03-01", "tariff",
                    beneficiary_tickers=["HYG", "USO"]),
            _event(2, "2026-03-02", "sanction",
                    beneficiary_tickers=["HYG", "USO"]),
            _event(3, "2026-03-03", "tariff",
                    beneficiary_tickers=["HYG", "USO"]),
            _event(4, "2026-03-04", "sanction",
                    beneficiary_tickers=["HYG", "USO"]),
        ]
        block = compute_cross_event_studies(events)
        for row in (
            block["family_cooccurrence"]
            + block["sector_clusters"]
            + block["path_clusters"]
            + block["combination_outcomes"]
        ):
            self.assertIn("event_ids", row)

    def test_malformed_event_date_skipped_not_raised(self):
        events = [
            _event(1, "not-a-date", "tariff"),
            _event(2, "2026-03-01", "sanction"),
            _event(3, "2026-03-03", "tariff"),
            _event(4, "2026-03-04", "sanction"),
        ]
        # Must not raise; event 1 is simply skipped from co-occurrence.
        block = compute_cross_event_studies(events)
        self.assertEqual(block["total_events"], 4)


if __name__ == "__main__":
    unittest.main()
