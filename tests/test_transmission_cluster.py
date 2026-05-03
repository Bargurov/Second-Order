"""Tests for transmission_cluster — archive-driven clustering by mechanism path.

Covers signature extraction (mechanism vs market taxonomy, fallback
chain), kind-aware similarity scoring, greedy clustering,
permutation-invariance, and defensive behavior on malformed input.
"""

from __future__ import annotations

import random
import unittest

from transmission_cluster import (
    SIGNATURE_KINDS,
    _FAMILY_CHANNELS_MERGE_THRESHOLD,
    _TRANSMISSION_MERGE_THRESHOLD,
    cluster_events_by_transmission_path,
    transmission_signature,
    transmission_similarity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(
    eid: int,
    family: str = "none",
    tpath=None,
    efoc=None,
    headline: str | None = None,
) -> dict:
    return {
        "id": eid,
        "headline": headline or f"Headline {eid}",
        "event_date": f"2025-01-{eid:02d}",
        "mechanism_family": family,
        "transmission_path": tpath if tpath is not None else [],
        "expected_first_order_channels": efoc if efoc is not None else [],
    }


def _hop(channel: str, actor: str = "Actor") -> dict:
    return {"hop": "hop text", "channel": channel, "actor": actor}


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------

class TestSignature(unittest.TestCase):
    def test_transmission_path_kind_when_hops_present(self):
        ev = _event(1, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")])
        sig = transmission_signature(ev)
        self.assertEqual(sig["kind"], "transmission_path")
        self.assertEqual(sig["family"], "sanction")
        self.assertEqual(sig["channels"], ("sanction", "supply", "pricing_power"))
        self.assertEqual(sig["channel_taxonomy"], "mechanism")

    def test_family_channels_kind_when_no_tpath_but_efoc_present(self):
        ev = _event(1, "tariff", efoc=["commodities", "equities"])
        sig = transmission_signature(ev)
        self.assertEqual(sig["kind"], "family_channels")
        self.assertEqual(sig["family"], "tariff")
        self.assertEqual(sig["channels"], ("commodities", "equities"))
        self.assertEqual(sig["channel_taxonomy"], "market")

    def test_family_channels_falls_back_to_pack_when_efoc_empty(self):
        ev = _event(1, "tariff")
        sig = transmission_signature(ev)
        self.assertEqual(sig["kind"], "family_channels")
        self.assertEqual(sig["family"], "tariff")
        # FAMILY_CHANNEL_PACKS["tariff"]["first"] = commodities,equities,fx
        self.assertEqual(sig["channels"][:3], ("commodities", "equities", "fx"))

    def test_family_only_when_family_has_no_pack_and_no_efoc(self):
        ev = _event(1, "none")  # "none" has empty pack
        sig = transmission_signature(ev)
        self.assertIn(sig["kind"], {"family_only", "thin"})
        # family == "none" should fall through to thin by policy
        self.assertEqual(sig["kind"], "thin")

    def test_thin_when_no_family_and_no_channels(self):
        ev = _event(1, "")
        sig = transmission_signature(ev)
        self.assertEqual(sig["kind"], "thin")
        self.assertEqual(sig["family"], "none")

    def test_tpath_wins_over_efoc(self):
        """Mechanism taxonomy takes priority when both are present."""
        ev = _event(
            1, "sanction",
            tpath=[_hop("sanction"), _hop("supply")],
            efoc=["commodities", "fx"],
        )
        sig = transmission_signature(ev)
        self.assertEqual(sig["kind"], "transmission_path")
        self.assertEqual(sig["channels"], ("sanction", "supply"))

    def test_unknown_channel_values_dropped(self):
        ev = _event(1, "sanction", tpath=[_hop("sanction"), _hop("invented_channel"), _hop("supply")])
        sig = transmission_signature(ev)
        self.assertEqual(sig["channels"], ("sanction", "supply"))

    def test_malformed_hops_skipped(self):
        ev = _event(1, "sanction", tpath=["not a dict", {"channel": "supply"}, None, 42])
        sig = transmission_signature(ev)
        self.assertEqual(sig["channels"], ("supply",))

    def test_none_event_returns_thin(self):
        sig = transmission_signature(None)
        self.assertEqual(sig["kind"], "thin")

    def test_non_dict_event_returns_thin(self):
        sig = transmission_signature("string")
        self.assertEqual(sig["kind"], "thin")

    def test_family_only_when_family_has_pack_but_list_empty(self):
        """Synthetic: family_only kind is reachable via a family whose
        pack is empty and whose stored efoc is also empty."""
        ev = {
            "id": 1,
            "mechanism_family": "synthetic_family_with_no_pack",
            "transmission_path": [],
            "expected_first_order_channels": [],
        }
        sig = transmission_signature(ev)
        self.assertEqual(sig["kind"], "family_only")
        self.assertEqual(sig["channels"], ())


# ---------------------------------------------------------------------------
# Similarity scoring
# ---------------------------------------------------------------------------

class TestSimilarity(unittest.TestCase):
    def test_identical_transmission_chain_scores_high(self):
        a = transmission_signature(_event(1, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")]))
        b = transmission_signature(_event(2, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")]))
        self.assertGreaterEqual(transmission_similarity(a, b), 0.95)

    def test_different_families_penalized(self):
        a = transmission_signature(_event(1, "sanction", tpath=[_hop("sanction"), _hop("supply")]))
        b = transmission_signature(_event(2, "tariff", tpath=[_hop("sanction"), _hop("supply")]))
        # Channels identical, family differs → family weight (0.40) drops
        sim = transmission_similarity(a, b)
        self.assertLess(sim, 0.75)
        self.assertGreater(sim, 0.20)

    def test_different_kinds_never_cluster(self):
        a = transmission_signature(_event(1, "sanction", tpath=[_hop("sanction"), _hop("supply")]))
        b = transmission_signature(_event(2, "sanction", efoc=["commodities", "fx"]))
        self.assertEqual(transmission_similarity(a, b), 0.0)

    def test_family_channels_same_family_same_channels_max_score(self):
        a = transmission_signature(_event(1, "tariff", efoc=["commodities", "equities", "fx"]))
        b = transmission_signature(_event(2, "tariff", efoc=["commodities", "equities", "fx"]))
        self.assertGreaterEqual(transmission_similarity(a, b), 0.95)

    def test_family_only_requires_family_match(self):
        a = {"kind": "family_only", "family": "tariff", "channels": ()}
        b = {"kind": "family_only", "family": "tariff", "channels": ()}
        c = {"kind": "family_only", "family": "sanction", "channels": ()}
        self.assertEqual(transmission_similarity(a, b), 1.0)
        self.assertEqual(transmission_similarity(a, c), 0.0)

    def test_thin_never_matches(self):
        a = {"kind": "thin", "family": "none", "channels": ()}
        b = {"kind": "thin", "family": "none", "channels": ()}
        self.assertEqual(transmission_similarity(a, b), 0.0)

    def test_similarity_non_dict_inputs_safe(self):
        self.assertEqual(transmission_similarity(None, None), 0.0)
        self.assertEqual(transmission_similarity({}, None), 0.0)
        self.assertEqual(transmission_similarity("x", {}), 0.0)

    def test_similarity_clamped_to_unit_interval(self):
        a = transmission_signature(_event(1, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power"), _hop("substitution")]))
        b = transmission_signature(_event(2, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power"), _hop("substitution")]))
        score = transmission_similarity(a, b)
        self.assertLessEqual(score, 1.0)
        self.assertGreaterEqual(score, 0.0)

    def test_ordered_prefix_bonus_applies(self):
        # Same family + same channel set, different orders should
        # still score but lower than same-order.
        a = transmission_signature(_event(1, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")]))
        b = transmission_signature(_event(2, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")]))
        c = transmission_signature(_event(3, "sanction", tpath=[_hop("pricing_power"), _hop("supply"), _hop("sanction")]))
        self.assertGreater(transmission_similarity(a, b), transmission_similarity(a, c))


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

class TestClustering(unittest.TestCase):
    def test_empty_input(self):
        r = cluster_events_by_transmission_path([])
        self.assertFalse(r["available"])
        self.assertEqual(r["clusters"], [])
        self.assertEqual(r["unclustered"], [])

    def test_none_input(self):
        r = cluster_events_by_transmission_path(None)
        self.assertFalse(r["available"])
        self.assertEqual(r["clusters"], [])

    def test_two_matching_transmission_paths_cluster_together(self):
        e1 = _event(1, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")])
        e2 = _event(2, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")])
        r = cluster_events_by_transmission_path([e1, e2])
        self.assertTrue(r["available"])
        self.assertEqual(len(r["clusters"]), 1)
        self.assertEqual(r["clusters"][0]["size"], 2)
        self.assertEqual(r["clusters"][0]["family"], "sanction")
        self.assertEqual(r["clusters"][0]["kind"], "transmission_path")

    def test_different_families_do_not_cluster(self):
        e1 = _event(1, "sanction", tpath=[_hop("sanction"), _hop("supply")])
        e2 = _event(2, "tariff", tpath=[_hop("tariff"), _hop("supply")])
        r = cluster_events_by_transmission_path([e1, e2])
        self.assertEqual(len(r["clusters"]), 2)

    def test_transmission_and_family_channels_never_mix(self):
        e1 = _event(1, "tariff", tpath=[_hop("tariff"), _hop("supply")])
        e2 = _event(2, "tariff", efoc=["commodities", "equities"])
        r = cluster_events_by_transmission_path([e1, e2])
        self.assertEqual(len(r["clusters"]), 2)
        kinds = {c["kind"] for c in r["clusters"]}
        self.assertEqual(kinds, {"transmission_path", "family_channels"})

    def test_thin_events_unclustered(self):
        e1 = _event(1, "")
        e2 = _event(2, "")
        r = cluster_events_by_transmission_path([e1, e2])
        self.assertEqual(len(r["clusters"]), 0)
        self.assertEqual(len(r["unclustered"]), 2)

    def test_mixed_population(self):
        evs = [
            _event(1, "sanction", tpath=[_hop("sanction"), _hop("supply")]),
            _event(2, "sanction", tpath=[_hop("sanction"), _hop("supply")]),
            _event(3, "tariff", efoc=["commodities", "equities"]),
            _event(4, "tariff", efoc=["commodities", "equities"]),
            _event(5, ""),
        ]
        r = cluster_events_by_transmission_path(evs)
        self.assertTrue(r["available"])
        self.assertEqual(len(r["clusters"]), 2)
        self.assertEqual(len(r["unclustered"]), 1)
        sizes = sorted(c["size"] for c in r["clusters"])
        self.assertEqual(sizes, [2, 2])

    def test_basis_distribution_reported(self):
        evs = [
            _event(1, "sanction", tpath=[_hop("sanction")]),
            _event(2, "tariff", efoc=["commodities"]),
            _event(3, ""),
        ]
        r = cluster_events_by_transmission_path(evs)
        self.assertEqual(r["basis_distribution"]["transmission_path"], 1)
        self.assertEqual(r["basis_distribution"]["family_channels"], 1)
        self.assertEqual(r["basis_distribution"]["thin"], 1)

    def test_rationale_non_empty(self):
        evs = [_event(1, "sanction", tpath=[_hop("sanction"), _hop("supply")])]
        r = cluster_events_by_transmission_path(evs)
        self.assertIsInstance(r["rationale"], str)
        self.assertGreater(len(r["rationale"]), 0)


class TestPermutationDeterminism(unittest.TestCase):
    """The greedy cluster algorithm must yield the same clustering
    regardless of input order — enforced via a deterministic pre-sort.
    """

    def _cluster_fingerprint(self, result: dict) -> list:
        """Canonical representation of cluster membership for comparison."""
        fp = []
        for c in result["clusters"]:
            members = sorted(m["event_id"] for m in c["members"])
            fp.append((c["kind"], c["family"], tuple(c["channels"]), tuple(members)))
        fp.sort()
        return fp

    def test_permutation_invariance(self):
        evs = [
            _event(1, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")]),
            _event(2, "sanction", tpath=[_hop("sanction"), _hop("supply"), _hop("pricing_power")]),
            _event(3, "tariff", efoc=["commodities", "equities"]),
            _event(4, "tariff", efoc=["commodities", "equities"]),
            _event(5, "bank_stress", tpath=[_hop("capital_flow"), _hop("pricing_power")]),
            _event(6, "bank_stress", tpath=[_hop("capital_flow"), _hop("pricing_power")]),
            _event(7, ""),
        ]
        base = self._cluster_fingerprint(cluster_events_by_transmission_path(evs))

        rng = random.Random(42)
        for _ in range(10):
            shuffled = list(evs)
            rng.shuffle(shuffled)
            other = self._cluster_fingerprint(cluster_events_by_transmission_path(shuffled))
            self.assertEqual(base, other)


# ---------------------------------------------------------------------------
# Defensive behavior
# ---------------------------------------------------------------------------

class TestDefensive(unittest.TestCase):
    def test_non_dict_events_skipped(self):
        r = cluster_events_by_transmission_path(["nope", None, 42])
        self.assertFalse(r["available"])
        self.assertEqual(r["clusters"], [])
        self.assertEqual(r["unclustered"], [])

    def test_mixed_valid_and_invalid(self):
        evs = [
            _event(1, "sanction", tpath=[_hop("sanction"), _hop("supply")]),
            None,
            "garbage",
            _event(2, "sanction", tpath=[_hop("sanction"), _hop("supply")]),
        ]
        r = cluster_events_by_transmission_path(evs)
        self.assertTrue(r["available"])
        self.assertEqual(len(r["clusters"]), 1)
        self.assertEqual(r["clusters"][0]["size"], 2)

    def test_constants_pinned(self):
        self.assertEqual(SIGNATURE_KINDS, ("transmission_path", "family_channels", "family_only", "thin"))
        self.assertGreater(_TRANSMISSION_MERGE_THRESHOLD, 0.0)
        self.assertLess(_TRANSMISSION_MERGE_THRESHOLD, 1.0)
        self.assertGreater(_FAMILY_CHANNELS_MERGE_THRESHOLD, 0.0)
        self.assertLess(_FAMILY_CHANNELS_MERGE_THRESHOLD, 1.0)

    def test_threshold_override(self):
        """Override arg should force looser / tighter merging."""
        e1 = _event(1, "sanction", tpath=[_hop("sanction")])
        e2 = _event(2, "tariff", tpath=[_hop("sanction")])
        # Default: different families → probably separate clusters
        r_default = cluster_events_by_transmission_path([e1, e2])
        # Forced 0.99 threshold → must separate
        r_tight = cluster_events_by_transmission_path([e1, e2], threshold_override=0.99)
        self.assertGreaterEqual(len(r_tight["clusters"]), len(r_default["clusters"]))


# ---------------------------------------------------------------------------
# find_historical_analogs boost wiring
# ---------------------------------------------------------------------------

class TestAnalogBoostContract(unittest.TestCase):
    """Light check that db.find_historical_analogs accepts the new
    parameter without error.  Full DB-backed analog tests live in
    test_api.py / test_regime_analog_rerank.py.
    """

    def test_signature_parameter_accepted(self):
        from db import find_historical_analogs
        # Calling without a DB connection returns [] gracefully.
        result = find_historical_analogs(
            "some headline",
            current_event_mechanism={
                "mechanism_family": "sanction",
                "transmission_path": [_hop("sanction"), _hop("supply")],
                "expected_first_order_channels": ["commodities"],
            },
        )
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
