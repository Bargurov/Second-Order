"""
tests/test_event_graph.py

Contract tests for the cross-event cascade graph.

Covers:
  1. Empty / degenerate inputs — shaped-empty block.
  2. Nodes — every archive event appears, including isolates (no edges).
  3. Edge construction — at least one component must fire to produce
     an edge.  Non-firing pairs produce no edge.
  4. Component types — family_shared, path_cluster, asset_overlap
     (Jaccard), sector_overlap (Jaccard) each fire independently.
  5. Aggregate weight — max + small bonus per additional component,
     clamped to [0, 1], not sum.
  6. Decay — weight falls with age; beyond the pair window no edge is
     emitted.
  7. Active flag — weight ≥ threshold => active=True; weaker edges
     still emit but flag inactive.
  8. Direction invariant — parent_date < child_date on every edge.
  9. Provenance — components carry the evidence the UI needs to render
     (shared family / signature / tickers / sectors).
 10. Envelope — parameters surfaced so consumers can reason about them.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from event_graph import (
    _ACTIVE_THRESHOLD,
    _HALF_LIFE_DAYS,
    _PAIR_WINDOW_DAYS,
    build_event_graph,
)


def _ev(
    eid: int,
    date: str,
    family: str | None = "tariff",
    *,
    beneficiary_tickers: list[str] | None = None,
    loser_tickers: list[str] | None = None,
    transmission_path: list[dict] | None = None,
) -> dict:
    return {
        "id":                  eid,
        "event_date":          date,
        "headline":            f"Event {eid}",
        "mechanism_family":    family,
        "beneficiary_tickers": json.dumps(beneficiary_tickers or []),
        "loser_tickers":       json.dumps(loser_tickers or []),
        "transmission_path":   json.dumps(transmission_path or []),
    }


def _path(channels: list[str]) -> list[dict]:
    return [
        {"hop": f"step {i}", "channel": c, "actor": f"actor-{i}"}
        for i, c in enumerate(channels)
    ]


def _find_edge(edges: list[dict], parent_id: int, child_id: int) -> dict | None:
    for e in edges:
        if e["parent_id"] == parent_id and e["child_id"] == child_id:
            return e
    return None


# ---------------------------------------------------------------------------
# 1. Empty / degenerate
# ---------------------------------------------------------------------------

class TestEmptyInputs(unittest.TestCase):

    def test_empty_list_returns_shaped_block(self):
        g = build_event_graph([])
        self.assertEqual(g["total_events"], 0)
        self.assertEqual(g["nodes"], [])
        self.assertEqual(g["edges"], [])
        self.assertEqual(g["active_edges"], 0)

    def test_non_dict_rows_filtered(self):
        g = build_event_graph([None, "not a dict", 42])
        self.assertEqual(g["total_events"], 0)

    def test_none_input_is_safe(self):
        g = build_event_graph(None)
        self.assertEqual(g["total_events"], 0)


# ---------------------------------------------------------------------------
# 2. Nodes — every event appears
# ---------------------------------------------------------------------------

class TestNodes(unittest.TestCase):

    def test_every_event_is_a_node(self):
        events = [
            _ev(1, "2026-03-01"),
            _ev(2, "2026-03-02"),
            _ev(3, "2026-03-03"),
        ]
        g = build_event_graph(events)
        ids = {n["id"] for n in g["nodes"]}
        self.assertEqual(ids, {1, 2, 3})

    def test_isolate_event_still_a_node(self):
        """An event that can't form any edge (far date + no overlap)
        still appears as a node — UI may want to render isolates."""
        events = [
            _ev(1, "2026-01-01", "tariff",
                beneficiary_tickers=["CVX"]),
            _ev(2, "2026-06-01", "bank_stress",   # > window
                beneficiary_tickers=["HYG"]),
        ]
        g = build_event_graph(events)
        self.assertEqual({n["id"] for n in g["nodes"]}, {1, 2})
        # No edges — 5-month gap exceeds window.
        self.assertEqual(g["edges"], [])

    def test_node_carries_family_and_date(self):
        events = [_ev(1, "2026-03-01", "supply_shock")]
        g = build_event_graph(events)
        node = g["nodes"][0]
        self.assertEqual(node["id"], 1)
        self.assertEqual(node["mechanism_family"], "supply_shock")
        self.assertIn("2026-03-01", node["event_date"])


# ---------------------------------------------------------------------------
# 3-4. Component construction (individual fires)
# ---------------------------------------------------------------------------

class TestComponents(unittest.TestCase):

    def test_no_component_fires_no_edge(self):
        """Different families, no shared assets, no shared path —
        no edge should form."""
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX"]),
            _ev(2, "2026-03-02", "bank_stress",
                beneficiary_tickers=["HYG"]),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIsNone(edge)

    def test_family_shared_fires(self):
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["AAPL"]),
            _ev(2, "2026-03-02", "tariff",
                beneficiary_tickers=["MSFT"]),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIsNotNone(edge)
        self.assertIn("family_shared", edge["components"])
        self.assertEqual(edge["components"]["family_shared"]["family"], "tariff")

    def test_path_cluster_fires_on_channel_signature(self):
        events = [
            _ev(1, "2026-03-01", "tariff",
                transmission_path=_path(["policy_gate", "supply"])),
            _ev(2, "2026-03-02", "sanction",  # different family
                transmission_path=_path(["policy_gate", "supply"])),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIsNotNone(edge)
        self.assertIn("path_cluster", edge["components"])
        # Must NOT have family_shared since families differ.
        self.assertNotIn("family_shared", edge["components"])

    def test_asset_overlap_uses_jaccard(self):
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX", "XOM"]),
            _ev(2, "2026-03-02", "bank_stress",
                beneficiary_tickers=["CVX", "PBF"]),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIsNotNone(edge)
        self.assertIn("asset_overlap", edge["components"])
        # Shared: 1 (CVX); Union: 3 (CVX, XOM, PBF) → Jaccard = 1/3
        self.assertAlmostEqual(
            edge["components"]["asset_overlap"]["jaccard"], 1/3, places=2,
        )
        self.assertIn("CVX", edge["components"]["asset_overlap"]["shared_tickers"])

    def test_sector_overlap_fires_via_ticker_channels(self):
        """USO (commodities) and HYG (credit) vs USO + GLD (both
        commodities) — the commodities-commodities overlap is full."""
        events = [
            _ev(1, "2026-03-01", "supply_shock",
                beneficiary_tickers=["USO", "HYG"]),
            _ev(2, "2026-03-02", "bank_stress",
                beneficiary_tickers=["USO", "HYG"]),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIsNotNone(edge)
        self.assertIn("sector_overlap", edge["components"])


# ---------------------------------------------------------------------------
# 5. Aggregate weight
# ---------------------------------------------------------------------------

class TestAggregateWeight(unittest.TestCase):

    def test_aggregate_uses_max_not_sum(self):
        """A pair sharing family + path_cluster + assets should not
        exceed 1.0 and should lean toward the strongest component
        (path_cluster at base 0.7), not pile up to >1.0."""
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
            _ev(2, "2026-03-01", "tariff",   # same day → decay = 1.0
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIsNotNone(edge)
        # Weight is at most 1.0 and ≥ path_cluster base (0.7).
        self.assertLessEqual(edge["weight"], 1.0)
        self.assertGreaterEqual(edge["weight"], 0.70)

    def test_bonus_per_additional_component(self):
        """Two events sharing family alone vs family + assets — the
        second pair should score higher thanks to the multi-component
        bonus, but still not double-count."""
        family_only = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX"]),
            _ev(2, "2026-03-01", "tariff",
                beneficiary_tickers=["MSFT"]),
        ]
        family_plus_asset = [
            _ev(3, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX"]),
            _ev(4, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX"]),
        ]
        w_family = _find_edge(build_event_graph(family_only)["edges"], 1, 2)["weight"]
        w_both   = _find_edge(build_event_graph(family_plus_asset)["edges"], 3, 4)["weight"]
        self.assertGreater(w_both, w_family)


# ---------------------------------------------------------------------------
# 6. Decay and pair window
# ---------------------------------------------------------------------------

class TestDecayAndWindow(unittest.TestCase):

    def test_weight_decays_with_age(self):
        same_day = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
            _ev(2, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
        ]
        ten_days = [
            _ev(3, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
            _ev(4, "2026-03-11", "tariff",
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
        ]
        w_fresh = _find_edge(build_event_graph(same_day)["edges"], 1, 2)["weight"]
        w_aged  = _find_edge(build_event_graph(ten_days)["edges"], 3, 4)["weight"]
        self.assertGreater(w_fresh, w_aged)

    def test_beyond_window_no_edge(self):
        events = [
            _ev(1, "2026-01-01", "tariff",
                beneficiary_tickers=["CVX"],
                transmission_path=_path(["policy_gate", "supply"])),
            _ev(2, "2026-06-01", "tariff",  # 5-month gap >> 60 days
                beneficiary_tickers=["CVX"],
                transmission_path=_path(["policy_gate", "supply"])),
        ]
        g = build_event_graph(events)
        self.assertEqual(g["edges"], [])


# ---------------------------------------------------------------------------
# 7. Active flag
# ---------------------------------------------------------------------------

class TestActiveFlag(unittest.TestCase):

    def test_fresh_strong_edge_is_active(self):
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX"],
                transmission_path=_path(["policy_gate", "supply"])),
            _ev(2, "2026-03-02", "tariff",
                beneficiary_tickers=["CVX"],
                transmission_path=_path(["policy_gate", "supply"])),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertTrue(edge["active"])
        self.assertGreaterEqual(edge["weight"], _ACTIVE_THRESHOLD)

    def test_old_weak_edge_emitted_but_inactive(self):
        """A pair sharing only a low-weight component at the edge of
        the window should emit an edge with active=False."""
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["AAPL", "MSFT", "GOOG", "AMZN"]),
            _ev(2, "2026-04-29", "tariff",  # ~59 days → heavy decay
                beneficiary_tickers=["META"]),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIsNotNone(edge)
        self.assertLess(edge["weight"], _ACTIVE_THRESHOLD)
        self.assertFalse(edge["active"])
        self.assertEqual(g["active_edges"], 0)
        self.assertEqual(g["total_edges"], 1)


# ---------------------------------------------------------------------------
# 8. Direction invariant
# ---------------------------------------------------------------------------

class TestDirectionInvariant(unittest.TestCase):

    def test_parent_always_earlier_than_child(self):
        events = [
            _ev(1, "2026-03-05", "tariff", beneficiary_tickers=["CVX"]),
            _ev(2, "2026-03-01", "tariff", beneficiary_tickers=["CVX"]),
            _ev(3, "2026-03-03", "tariff", beneficiary_tickers=["CVX"]),
        ]
        g = build_event_graph(events)
        for edge in g["edges"]:
            self.assertLess(edge["parent_date"], edge["child_date"])


# ---------------------------------------------------------------------------
# 9. Provenance — every component carries evidence
# ---------------------------------------------------------------------------

class TestProvenance(unittest.TestCase):

    def test_family_shared_carries_family_name(self):
        events = [
            _ev(1, "2026-03-01", "commodity_squeeze"),
            _ev(2, "2026-03-02", "commodity_squeeze"),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertEqual(
            edge["components"]["family_shared"]["family"], "commodity_squeeze",
        )

    def test_asset_overlap_carries_shared_tickers(self):
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX", "XOM", "PBF"]),
            _ev(2, "2026-03-02", "tariff",
                beneficiary_tickers=["CVX", "XOM"]),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        shared = edge["components"]["asset_overlap"]["shared_tickers"]
        self.assertIn("CVX", shared)
        self.assertIn("XOM", shared)

    def test_components_list_sorted_by_contribution(self):
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
            _ev(2, "2026-03-02", "tariff",
                beneficiary_tickers=["CVX", "XOM"],
                transmission_path=_path(["policy_gate", "supply"])),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        contribs = [row["contribution"] for row in edge["components_list"]]
        self.assertEqual(contribs, sorted(contribs, reverse=True))

    def test_edge_has_human_rationale(self):
        events = [
            _ev(1, "2026-03-01", "tariff"),
            _ev(2, "2026-03-02", "tariff"),
        ]
        g = build_event_graph(events)
        edge = _find_edge(g["edges"], 1, 2)
        self.assertIn("shared family", edge["rationale"].lower())


# ---------------------------------------------------------------------------
# 10. Envelope — parameters + totals
# ---------------------------------------------------------------------------

class TestEnvelope(unittest.TestCase):

    def test_envelope_surfaces_parameters(self):
        g = build_event_graph([_ev(1, "2026-03-01", "tariff")])
        self.assertEqual(g["decay_half_life_days"], _HALF_LIFE_DAYS)
        self.assertEqual(g["active_threshold"], _ACTIVE_THRESHOLD)
        self.assertEqual(g["pair_window_days"], _PAIR_WINDOW_DAYS)

    def test_total_events_counts_only_dicts(self):
        events = [
            _ev(1, "2026-03-01", "tariff"),
            None,
            _ev(2, "2026-03-02", "tariff"),
        ]
        g = build_event_graph(events)
        self.assertEqual(g["total_events"], 2)

    def test_active_edges_subset_of_total(self):
        events = [
            _ev(1, "2026-03-01", "tariff",
                beneficiary_tickers=["CVX"]),
            _ev(2, "2026-03-02", "tariff",
                beneficiary_tickers=["CVX"]),
            _ev(3, "2026-04-28", "tariff",  # ~58d later: small asset overlap
                beneficiary_tickers=["MSFT"]),
        ]
        g = build_event_graph(events)
        self.assertLessEqual(g["active_edges"], g["total_edges"])


if __name__ == "__main__":
    unittest.main()
