"""J3 mechanism/transmission readout tests (Mission J, j0-v1 contracts).

J3 is a READOUT layer: it consumes the published, tracked J1B and J2
reports and mechanically applies the frozen J0 node / panel / modifier /
edge rules. Nothing here computes a response, MEMP, calibration, subset,
or any other statistic. Integrity tests run read-only against the real
tracked reports (already-published artifacts); adjudicator tests are pure.

Protected contracts (task manifest): published-evidence integrity 1-8;
node reading 9-14; edge precedence 15-21; M3 symmetry 22-25; context
isolation 26-30; reporting 31-41.
"""

from __future__ import annotations

import itertools
import unittest

from scripts import j3_mechanism_readout as j3


def _real_surfaces():
    if "surfaces" not in _CACHE:
        _CACHE["surfaces"] = j3.load_published_surfaces()
    return _CACHE["surfaces"]


def _real_readout():
    if "readout" not in _CACHE:
        _CACHE["readout"] = j3.assemble_readout(_real_surfaces())
    return _CACHE["readout"]


def _real_report():
    if "report" not in _CACHE:
        _CACHE["report"] = j3.render_j3_report(
            _real_readout(),
            provenance={"head": "deadbeef",
                        "timestamp": "2026-07-10T00:00:00Z"})
    return _CACHE["report"]


_CACHE: dict = {}


# ---------------------------------------------------------------------------
# Published evidence integrity (1-8) - real tracked reports, read-only
# ---------------------------------------------------------------------------


class TestPublishedEvidenceIntegrity(unittest.TestCase):
    def test_1_exact_j1b_12_cell_surface_recognized(self):
        s = _real_surfaces()
        cells = s["j1b"]["cells"]
        self.assertEqual(sorted(cells), list(range(1, 13)))
        self.assertEqual(cells[1]["measurement"], "KRE")
        self.assertEqual(cells[1]["lens"], "rolling_beta_ar")
        self.assertEqual(cells[1]["memp"], "0.664719")
        self.assertEqual(cells[10]["measurement"], "2Y_CMT")
        for no, c in cells.items():
            self.assertEqual(c["state"], "ELEVATED", f"cell {no}")

    def test_2_exact_j2_timing_surface_recognized(self):
        s = _real_surfaces()
        cells = s["j2"]["timing_cells"]
        self.assertEqual(sorted(cells), [13, 14, 15, 16])
        self.assertEqual(
            [cells[n]["state"] for n in (13, 14, 15, 16)],
            ["ORDINARY_UNRESOLVED", "ORDINARY_UNRESOLVED",
             "ELEVATED", "ELEVATED"])
        for n in (13, 14, 15, 16):
            self.assertEqual(cells[n]["available"], "65")
            self.assertEqual(cells[n]["attempted"], "65")
            self.assertEqual(cells[n]["reference_n"], "1427")

    def test_3_published_panel_modifiers_recognized(self):
        s = _real_surfaces()
        panels = s["j1b"]["panels"]
        for role in ("policy_rates_repricing",
                     "balance_sheet_sensitive_second_order",
                     "broad_financial_sector"):
            self.assertEqual(panels[role]["modifier"],
                             "BROAD MEASUREMENT CONSISTENCY", role)
        self.assertEqual(panels["policy_rates_repricing"]["members"],
                         ["2Y_CMT", "SHY"])
        self.assertEqual(
            panels["balance_sheet_sensitive_second_order"]["members"],
            ["KRE", "IAT", "KBE"])
        self.assertEqual(panels["broad_financial_sector"]["members"],
                         ["XLF", "VFH"])

    def test_4_2s10s_stays_outside_the_rates_panel(self):
        for node in j3.GRAPH_NODES:
            self.assertNotIn("2S10S_CMT", node["panel"])
        self.assertEqual(j3.CONTEXTUAL_MEASUREMENT, "2S10S_CMT")
        for node in j3.GRAPH_NODES:
            self.assertNotIn("2S10S_CMT", node.get("route_b_members", ()))

    def test_5_spy_stays_outside_graph_nodes(self):
        for node in j3.GRAPH_NODES:
            self.assertNotIn("SPY", node["panel"])
        self.assertEqual(j3.CONTEXT_BENCHMARK, "SPY")

    def test_6_c1_remains_unadjudicable(self):
        s = _real_surfaces()
        self.assertFalse(s["j2"]["collisions"]["c1_adjudicable"])
        self.assertIn("unadjudicable", s["j2"]["collisions"]["c1_line"])

    def test_7_c2_remains_zero_tagged(self):
        s = _real_surfaces()
        self.assertEqual(s["j2"]["collisions"]["c2_tagged_n"], 0)
        self.assertEqual(s["j2"]["collisions"]["all_n"], 65)
        self.assertEqual(s["j2"]["collisions"]["collision_free_n"], 65)

    def test_8_denominators_survive_into_readout(self):
        r = _real_readout()
        d = r["denominators"]
        self.assertEqual(d["j1b_rolling_beta"], {"available": "64",
                                                 "attempted": "65",
                                                 "reference_n": "1797"})
        self.assertEqual(d["j1b_raw_return"]["reference_n"], "1816")
        self.assertEqual(d["j1b_raw_change"]["reference_n"], "1804")
        self.assertEqual(d["j2_timing"], {"available": "65",
                                          "attempted": "65",
                                          "reference_n": "1427"})

    def test_8b_reconciliation_fails_loud_on_tampered_surface(self):
        import copy
        s = copy.deepcopy(_real_surfaces())
        s["j1b"]["cells"][3]["state"] = "DISCORDANT"
        with self.assertRaises(j3.J3ReconciliationError):
            j3.assemble_readout(s)


# ---------------------------------------------------------------------------
# Node reading (9-14) - pure adjudicator
# ---------------------------------------------------------------------------


class TestNodeReading(unittest.TestCase):
    def _read(self, state, m_class, modifier, usable=True):
        return j3.role_reading(primary_state=state, primary_m_class=m_class,
                               primary_usable=usable, modifier=modifier)

    def test_9_usable_m2_primary_state_a_activates_alone(self):
        r = self._read("ELEVATED", "M2", "PROXY-SPECIFIC")
        self.assertEqual(r["reading"], "ACTIVATED")
        self.assertIn("M2", r["rule_path"])

    def test_10_m3_alternate_cannot_replace_failed_m2_primary(self):
        r = self._read("ELEVATED", "M2", "BROAD MEASUREMENT CONSISTENCY",
                       usable=False)
        self.assertEqual(r["reading"], "UNRESOLVED")
        self.assertIn("unusable", r["rule_path"])

    def test_11_m3_primary_a_plus_role_consistent_activates(self):
        for mod in ("ROLE-CONSISTENT", "BROAD MEASUREMENT CONSISTENCY"):
            r = self._read("ELEVATED", "M3", mod)
            self.assertEqual(r["reading"], "ACTIVATED", mod)

    def test_12_single_m3_a_without_corroboration_stays_unresolved(self):
        r = self._read("ELEVATED", "M3", "PROXY-SPECIFIC")
        self.assertEqual(r["reading"], "UNRESOLVED")

    def test_13_blocking_disagreement_stays_unresolved(self):
        r = self._read("ELEVATED", "M3", "MEASUREMENT DISAGREEMENT")
        self.assertEqual(r["reading"], "UNRESOLVED")

    def test_13b_state_b_or_c_reads_not_activated(self):
        for st in ("ORDINARY_UNRESOLVED", "LOWER_MAGNITUDE"):
            for mc in ("M2", "M3"):
                r = self._read(st, mc, "BROAD MEASUREMENT CONSISTENCY")
                self.assertEqual(r["reading"], "NOT ACTIVATED", (st, mc))

    def test_13c_state_d_reads_unresolved(self):
        r = self._read("DISCORDANT", "M2", "BROAD MEASUREMENT CONSISTENCY")
        self.assertEqual(r["reading"], "UNRESOLVED")

    def test_14_reading_preserves_measurement_class(self):
        r = self._read("ELEVATED", "M2", "BROAD MEASUREMENT CONSISTENCY")
        self.assertEqual(r["m_class"], "M2")


# ---------------------------------------------------------------------------
# Edge precedence (15-21) - pure adjudicator
# ---------------------------------------------------------------------------


def _down(state, m_class="M3", modifier="BROAD MEASUREMENT CONSISTENCY",
          usable=True, route_b=False):
    return {"primary_state": state, "primary_m_class": m_class,
            "primary_usable": usable, "modifier": modifier,
            "route_b_satisfied": route_b}


class TestEdgePrecedence(unittest.TestCase):
    def test_15_upstream_unresolved_always_measurement_unresolved(self):
        for down_state in ("ELEVATED", "ORDINARY_UNRESOLVED",
                           "LOWER_MAGNITUDE", "DISCORDANT"):
            e = j3.edge_state("UNRESOLVED", _down(down_state))
            self.assertEqual(e["state"], "MEASUREMENT UNRESOLVED",
                             down_state)
            self.assertIn("precedence step 1", e["rule_path"])

    def test_16_downstream_unadjudicable_yields_measurement_unresolved(self):
        for up in ("ACTIVATED", "NOT ACTIVATED"):
            e = j3.edge_state(up, _down("DISCORDANT"))
            self.assertEqual(e["state"], "MEASUREMENT UNRESOLVED", up)
            self.assertIn("precedence step 2", e["rule_path"])
            e = j3.edge_state(up, _down("ELEVATED", usable=False))
            self.assertEqual(e["state"], "MEASUREMENT UNRESOLVED", up)

    def test_17_activated_plus_supported_elevated_propagates(self):
        e = j3.edge_state("ACTIVATED", _down("ELEVATED", m_class="M2",
                                             modifier="PROXY-SPECIFIC"))
        self.assertEqual(e["state"], "PROPAGATED")
        e = j3.edge_state("ACTIVATED",
                          _down("ELEVATED", modifier="ROLE-CONSISTENT"))
        self.assertEqual(e["state"], "PROPAGATED")

    def test_18_activated_plus_supported_nonresponse_breaks(self):
        e = j3.edge_state("ACTIVATED", _down("ORDINARY_UNRESOLVED",
                                             m_class="M2",
                                             modifier="PROXY-SPECIFIC"))
        self.assertEqual(e["state"], "TRANSMISSION BREAK")
        e = j3.edge_state("ACTIVATED", _down("LOWER_MAGNITUDE",
                                             route_b=True))
        self.assertEqual(e["state"], "TRANSMISSION BREAK")

    def test_19_not_activated_plus_supported_elevated_is_dwu(self):
        e = j3.edge_state("NOT ACTIVATED",
                          _down("ELEVATED", modifier="ROLE-CONSISTENT"))
        self.assertEqual(e["state"], "DOWNSTREAM WITHOUT UPSTREAM")

    def test_20_not_activated_plus_bc_is_upstream_not_activated(self):
        # Route B support is NOT required here (no break claim considered).
        e = j3.edge_state("NOT ACTIVATED",
                          _down("ORDINARY_UNRESOLVED", route_b=False))
        self.assertEqual(e["state"], "UPSTREAM NOT ACTIVATED")

    def test_21_no_sixth_state_over_exhaustive_sweep(self):
        states = set()
        for up, st, mc, mod, usable, rb in itertools.product(
                ("ACTIVATED", "NOT ACTIVATED", "UNRESOLVED"),
                ("ELEVATED", "ORDINARY_UNRESOLVED", "LOWER_MAGNITUDE",
                 "DISCORDANT"),
                ("M2", "M3"),
                ("PROXY-SPECIFIC", "ROLE-CONSISTENT",
                 "BROAD MEASUREMENT CONSISTENCY",
                 "MEASUREMENT DISAGREEMENT"),
                (True, False), (True, False)):
            e = j3.edge_state(up, _down(st, m_class=mc, modifier=mod,
                                        usable=usable, route_b=rb))
            states.add(e["state"])
            self.assertIn(e["state"], j3.EDGE_STATES)
        self.assertEqual(states, set(j3.EDGE_STATES))


# ---------------------------------------------------------------------------
# M3 symmetry (22-25)
# ---------------------------------------------------------------------------


class TestM3Symmetry(unittest.TestCase):
    def test_22_single_elevated_m3_cannot_propagate(self):
        e = j3.edge_state("ACTIVATED",
                          _down("ELEVATED", modifier="PROXY-SPECIFIC"))
        self.assertEqual(e["state"], "MEASUREMENT UNRESOLVED")

    def test_23_single_elevated_m3_cannot_create_dwu(self):
        e = j3.edge_state("NOT ACTIVATED",
                          _down("ELEVATED", modifier="PROXY-SPECIFIC"))
        self.assertEqual(e["state"], "MEASUREMENT UNRESOLVED")

    def test_24_m3_failure_without_route_b_cannot_break(self):
        e = j3.edge_state("ACTIVATED",
                          _down("ORDINARY_UNRESOLVED", route_b=False))
        self.assertEqual(e["state"], "MEASUREMENT UNRESOLVED")
        self.assertIn("Route B", e["rule_path"])

    def test_25_symmetric_measurement_governance(self):
        pos = j3.edge_state("ACTIVATED",
                            _down("ELEVATED", modifier="PROXY-SPECIFIC"))
        neg = j3.edge_state("ACTIVATED",
                            _down("LOWER_MAGNITUDE", route_b=False))
        self.assertEqual(pos["state"], "MEASUREMENT UNRESOLVED")
        self.assertEqual(neg["state"], "MEASUREMENT UNRESOLVED")
        self.assertIn("governance", pos["rule_path"].lower())
        self.assertIn("governance", neg["rule_path"].lower())


# ---------------------------------------------------------------------------
# Context isolation (26-30)
# ---------------------------------------------------------------------------


class TestContextIsolation(unittest.TestCase):
    def test_26_27_28_2s10s_is_not_an_adjudication_input(self):
        import inspect
        sig = inspect.signature(j3.role_reading)
        self.assertNotIn("contextual", sig.parameters)
        sig = inspect.signature(j3.edge_state)
        self.assertNotIn("contextual", sig.parameters)
        for node in j3.GRAPH_NODES:
            self.assertNotIn("2S10S_CMT", node["panel"])
            self.assertNotIn("2S10S_CMT", node.get("route_b_members", ()))
        r = _real_readout()
        self.assertEqual(r["contextual"]["measurement"], "2S10S_CMT")
        self.assertIn("context", r["contextual"]["note"].lower())

    def test_29_j2_timing_does_not_rewrite_j1b_node_state(self):
        import copy
        s = copy.deepcopy(_real_surfaces())
        base = j3.assemble_readout(s)
        # Hypothetically flip every J2 timing state; node readings and
        # edge states must be identical (timing is a qualifier only).
        for n in s["j2"]["timing_cells"]:
            s["j2"]["timing_cells"][n]["state"] = "LOWER_MAGNITUDE"
        alt = j3.assemble_readout(s, reconcile=False)
        self.assertEqual([n["reading"] for n in base["nodes"]],
                         [n["reading"] for n in alt["nodes"]])
        self.assertEqual([e["state"] for e in base["edges"]],
                         [e["state"] for e in alt["edges"]])
        self.assertNotEqual(base["timing_qualifier"],
                            alt["timing_qualifier"])

    def test_30_collision_qualifiers_do_not_rewrite_edge_state(self):
        import copy
        s = copy.deepcopy(_real_surfaces())
        base = j3.assemble_readout(s)
        s["j2"]["collisions"]["c2_tagged_n"] = 7
        s["j2"]["collisions"]["collision_free_n"] = 58
        alt = j3.assemble_readout(s, reconcile=False)
        self.assertEqual([e["state"] for e in base["edges"]],
                         [e["state"] for e in alt["edges"]])
        self.assertNotEqual(base["collision_qualifier"],
                            alt["collision_qualifier"])


# ---------------------------------------------------------------------------
# Reporting (31-41)
# ---------------------------------------------------------------------------


class TestReporting(unittest.TestCase):
    def test_31_every_node_appears(self):
        text = _real_report()
        for token in ("policy_rates_repricing",
                      "balance_sheet_sensitive_second_order",
                      "broad_financial_sector", "fomc_decision"):
            self.assertIn(token, text)

    def test_32_every_panel_member_appears(self):
        text = _real_report()
        for token in ("2Y_CMT", "SHY", "KRE", "IAT", "KBE", "XLF", "VFH"):
            self.assertIn(token, text)

    def test_33_every_edge_appears(self):
        text = _real_report()
        for token in ("E1", "E2", "E3"):
            self.assertIn(token, text)

    def test_34_every_denominator_appears(self):
        text = _real_report()
        for token in ("64 / 65", "65 / 65", "1797", "1816", "1804", "1427"):
            self.assertIn(token, text)

    def test_35_unresolved_paths_appear(self):
        text = _real_report()
        self.assertIn("measurement-limited", text)
        self.assertIn("M1", text)
        self.assertIn("unadjudicable", text)

    def test_36_timing_qualifier_appears(self):
        text = _real_report()
        self.assertIn("timing evidence is lens-dependent under daily "
                      "measurement", text)

    def test_37_collision_qualifier_appears(self):
        text = _real_report()
        self.assertIn("outside known-register collisions", text)
        self.assertNotIn("free of competing events", text)
        self.assertNotIn("all 65 events are clean", text)

    def test_38_no_ranking_language(self):
        text = _real_report().lower()
        for token in ("best", "strongest", "winner", "ranked", "ranking",
                      "top-"):
            self.assertNotIn(token, text)

    def test_39_no_significance_language(self):
        text = _real_report().lower()
        for token in ("signific", "p-value", "hypothesis test",
                      "confidence interval"):
            self.assertNotIn(token, text)

    def test_40_no_causal_predictive_trading_language(self):
        text = _real_report()
        for token in ("mechanism confirmed", "causal chain proven",
                      "transmitted because", "market knew beforehand",
                      "insider", "leak"):
            self.assertNotIn(token, text)
        # Single-word claim tokens may appear ONLY inside the frozen
        # non-claims section (negated), never in the claim surface.
        claims_part = text.split("## 9.")[0].lower()
        for token in ("alpha", "forecast", " signal", "leak"):
            self.assertNotIn(token, claims_part)

    def test_41_deterministic_report(self):
        a = _real_report()
        b = j3.render_j3_report(
            j3.assemble_readout(j3.load_published_surfaces()),
            provenance={"head": "deadbeef",
                        "timestamp": "2026-07-10T00:00:00Z"})
        self.assertEqual(a, b)

    def test_41b_no_new_statistics_and_gate_banner(self):
        import inspect
        src = inspect.getsource(j3)
        for banned in ("numpy", "default_rng", "mid_rank", "memp(",
                       "calibration_percentile", "rolling_beta_response",
                       "raw_return_response"):
            self.assertNotIn(banned, src)
        self.assertEqual(
            j3.PRERUN_GATE_BANNER,
            "J3 PRE-RUN GATE PASSED — FROZEN MECHANISM READOUT AUTHORIZED")

    def test_41c_real_readout_edges_carry_explanation_paths(self):
        r = _real_readout()
        self.assertEqual(len(r["edges"]), 3)
        for e in r["edges"]:
            self.assertIn(e["state"], j3.EDGE_STATES)
            self.assertTrue(e["rule_path"])
            self.assertTrue(e["upstream_reading"])

    def test_41d_five_edge_states_enumerated(self):
        self.assertEqual(j3.EDGE_STATES, (
            "PROPAGATED", "TRANSMISSION BREAK", "UPSTREAM NOT ACTIVATED",
            "DOWNSTREAM WITHOUT UPSTREAM", "MEASUREMENT UNRESOLVED"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
