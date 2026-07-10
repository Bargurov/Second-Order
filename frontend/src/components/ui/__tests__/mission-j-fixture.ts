/**
 * Contract-shaped Mission J fixture (mirrors GET /evidence/mission-j,
 * contract mission-j-evidence-v1).  Values mirror the tracked published
 * record; this fixture is the only place test values live.  Not a test
 * file — imported by the component and page suites.
 */
import type { MissionJEvidenceSummary } from "@/lib/api";

const J1B_CELLS: MissionJEvidenceSummary["j1b"]["cells"] = [
  { cell: 1, measurement: "KRE", lens: "rolling_beta_ar", role: "balance_sheet_sensitive_second_order", m_class: "M3", evidence_class: "A instrument; B statistic", attempted_event_n: 65, available_event_n: 64, unavailable_events: [["2018-01-31", "insufficient_history_252_20"]], reference_n: 1797, memp: "0.664719", calibration_percentile: "0.998000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/64", f3_reference_n: 1797, f3_canonical_n: 917, f3_memp: "0.655398", f3_sign_flip: false },
  { cell: 2, measurement: "IAT", lens: "rolling_beta_ar", role: "balance_sheet_sensitive_second_order", m_class: "M3", evidence_class: "B instrument; B statistic", attempted_event_n: 65, available_event_n: 64, unavailable_events: [["2018-01-31", "insufficient_history_252_20"]], reference_n: 1797, memp: "0.691987", calibration_percentile: "1.000000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/64", f3_reference_n: 1797, f3_canonical_n: 917, f3_memp: "0.691930", f3_sign_flip: false },
  { cell: 3, measurement: "KBE", lens: "rolling_beta_ar", role: "balance_sheet_sensitive_second_order", m_class: "M3", evidence_class: "B instrument; B statistic", attempted_event_n: 65, available_event_n: 64, unavailable_events: [["2018-01-31", "insufficient_history_252_20"]], reference_n: 1797, memp: "0.629382", calibration_percentile: "0.983000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/64", f3_reference_n: 1797, f3_canonical_n: 917, f3_memp: "0.621047", f3_sign_flip: false },
  { cell: 4, measurement: "XLF", lens: "rolling_beta_ar", role: "broad_financial_sector", m_class: "M3", evidence_class: "A instrument; B statistic", attempted_event_n: 65, available_event_n: 64, unavailable_events: [["2018-01-31", "insufficient_history_252_20"]], reference_n: 1797, memp: "0.658319", calibration_percentile: "0.996000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/64", f3_reference_n: 1797, f3_canonical_n: 917, f3_memp: "0.654308", f3_sign_flip: false },
  { cell: 5, measurement: "VFH", lens: "rolling_beta_ar", role: "broad_financial_sector", m_class: "M3", evidence_class: "B instrument; B statistic", attempted_event_n: 65, available_event_n: 64, unavailable_events: [["2018-01-31", "insufficient_history_252_20"]], reference_n: 1797, memp: "0.696717", calibration_percentile: "0.999000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/64", f3_reference_n: 1797, f3_canonical_n: 917, f3_memp: "0.695202", f3_sign_flip: false },
  { cell: 6, measurement: "IAT", lens: "raw_return", role: "balance_sheet_sensitive_second_order", m_class: "M3", evidence_class: "B instrument; B statistic", attempted_event_n: 65, available_event_n: 65, unavailable_events: [], reference_n: 1816, memp: "0.655837", calibration_percentile: "0.997000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1816, f3_canonical_n: 927, f3_memp: "0.645092", f3_sign_flip: false },
  { cell: 7, measurement: "KBE", lens: "raw_return", role: "balance_sheet_sensitive_second_order", m_class: "M3", evidence_class: "B instrument; B statistic", attempted_event_n: 65, available_event_n: 65, unavailable_events: [], reference_n: 1816, memp: "0.669604", calibration_percentile: "0.999500", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1816, f3_canonical_n: 927, f3_memp: "0.665588", f3_sign_flip: false },
  { cell: 8, measurement: "XLF", lens: "raw_return", role: "broad_financial_sector", m_class: "M3", evidence_class: "A instrument; B statistic", attempted_event_n: 65, available_event_n: 65, unavailable_events: [], reference_n: 1816, memp: "0.645925", calibration_percentile: "0.995500", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1816, f3_canonical_n: 927, f3_memp: "0.635383", f3_sign_flip: false },
  { cell: 9, measurement: "VFH", lens: "raw_return", role: "broad_financial_sector", m_class: "M3", evidence_class: "B instrument; B statistic", attempted_event_n: 65, available_event_n: 65, unavailable_events: [], reference_n: 1816, memp: "0.670705", calibration_percentile: "0.999000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1816, f3_canonical_n: 927, f3_memp: "0.656958", f3_sign_flip: false },
  { cell: 10, measurement: "2Y_CMT", lens: "raw_change", role: "policy_rates_repricing", m_class: "M2", evidence_class: "B statistic", attempted_event_n: 65, available_event_n: 65, unavailable_events: [], reference_n: 1804, memp: "0.615576", calibration_percentile: "0.981500", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1804, f3_canonical_n: 920, f3_memp: "0.611957", f3_sign_flip: false },
  { cell: 11, measurement: "2S10S_CMT", lens: "raw_change", role: "curve_shape_contextual_layer", m_class: "M2", evidence_class: "B statistic (underlying series A as a state)", attempted_event_n: 65, available_event_n: 65, unavailable_events: [], reference_n: 1804, memp: "0.652716", calibration_percentile: "0.996000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1804, f3_canonical_n: 920, f3_memp: "0.638587", f3_sign_flip: false },
  { cell: 12, measurement: "SHY", lens: "raw_return", role: "policy_rates_repricing", m_class: "M3", evidence_class: "B instrument; B statistic", attempted_event_n: 65, available_event_n: 65, unavailable_events: [], reference_n: 1816, memp: "0.579295", calibration_percentile: "0.934000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1816, f3_canonical_n: 927, f3_memp: "0.580367", f3_sign_flip: false },
];

export function missionJFixture(): MissionJEvidenceSummary {
  return {
    contract_version: "mission-j-evidence-v1",
    provenance: {
      sources: {
        j1b: { artifact: "J1B_FOMC_ROBUSTNESS_RESULTS.md", sha256: "c82c259b1cdd", bytes: 14476 },
        j2: { artifact: "J2_TIMING_COLLISION_RESULTS.md", sha256: "f51e58e37059", bytes: 18563 },
        j3: { artifact: "J3_MECHANISM_TRANSMISSION_READOUT.md", sha256: "41e73b5cbe82", bytes: 12175 },
      },
      publication_status:
        "Mission J is published and closed: constitution (J0), frozen data substrate (J1A), asset/benchmark challenge (J1B), timing and exact-window collision challenge (J2), and frozen mechanism/transmission readout (J3).",
      no_recompute_statement:
        "This endpoint exposes published results and computes no research statistic: no return, no median-of-percentiles estimand, no placement position, no subset, and no node or edge re-adjudication; the final published J3 states are parsed from the tracked J3 publication.",
    },
    j1b: {
      window: "[t, t+1]",
      cells: J1B_CELLS,
      panels: [
        { role: "balance_sheet_sensitive_second_order", members: ["KRE", "IAT", "KBE"], primary: "KRE", states: { KRE: "ELEVATED", IAT: "ELEVATED", KBE: "ELEVATED" }, modifier: "BROAD MEASUREMENT CONSISTENCY" },
        { role: "broad_financial_sector", members: ["XLF", "VFH"], primary: "XLF", states: { XLF: "ELEVATED", VFH: "ELEVATED" }, modifier: "BROAD MEASUREMENT CONSISTENCY" },
        { role: "policy_rates_repricing", members: ["2Y_CMT", "SHY"], primary: "2Y_CMT", states: { "2Y_CMT": "ELEVATED", SHY: "ELEVATED" }, modifier: "BROAD MEASUREMENT CONSISTENCY" },
      ],
      contextual_2s10s: {
        measurement: "2S10S_CMT",
        state: "ELEVATED",
        isolation_note:
          "curve-shape contextual layer: state-bearing and contextual; outside the rates-repricing proxy panel, outside role modifiers, outside edge adjudication; context only, never a substitute for short-rate repricing",
      },
      measurement_limited: {
        statement:
          "measurement-limited: the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates-role reading rests on an M2 official series plus an M3 investable proxy, and the 2Y CMT blends policy expectations with term premium",
      },
      correlated_views_disclosure:
        "the frozen cells are correlated robustness views over overlapping events, assets, benchmarks, and reference structures - not independent replications and not independent statistical tests",
      non_claims: [
        "causality;",
        "prediction;",
        "tradeability;",
        "alpha;",
        "independent historical confirmation;",
        "mechanism proof (edge adjudication belongs to J3 under the frozen five-state rules; no edge state is asserted here);",
        "intraday timing;",
        "graph propagation;",
        "any hypothesis-test conclusion (calibration percentiles are placement positions, not test outcomes).",
      ],
    },
    j2: {
      window: "[-5, -1]",
      state_bearing: [
        { cell: 13, metric: "raw_return", window: "[-5, -1]", attempted_event_n: 65, available_event_n: 65, reference_n: 1427, memp: "0.491240", calibration_percentile: "0.424500", node_state: "ORDINARY_UNRESOLVED", loyo: "4/8", loeo: "32/65", f3_reference_n: 1427, f3_canonical_n: 297, f3_memp: "0.464646", f3_sign_flip: false },
        { cell: 14, metric: "spy_relative_ar", window: "[-5, -1]", attempted_event_n: 65, available_event_n: 65, reference_n: 1427, memp: "0.537491", calibration_percentile: "0.716500", node_state: "ORDINARY_UNRESOLVED", loyo: "1/8", loeo: "0/65", f3_reference_n: 1427, f3_canonical_n: 297, f3_memp: "0.518519", f3_sign_flip: false },
        { cell: 15, metric: "sector_relative_ar", window: "[-5, -1]", attempted_event_n: 65, available_event_n: 65, reference_n: 1427, memp: "0.609671", calibration_percentile: "0.970000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1427, f3_canonical_n: 297, f3_memp: "0.589226", f3_sign_flip: false },
        { cell: 16, metric: "sar", window: "[-5, -1]", attempted_event_n: 65, available_event_n: 65, reference_n: 1427, memp: "0.572530", calibration_percentile: "0.889000", node_state: "ELEVATED", loyo: "0/8", loeo: "0/65", f3_reference_n: 1427, f3_canonical_n: 297, f3_memp: "0.548822", f3_sign_flip: false },
      ],
      diagnostics: [
        { id: "D1", metric: "raw_return", window: "[-20, -1]", available_event_n: 65, attempted_event_n: 65, median_response: "0.003612", median_abs_response: "0.050052", direction: "positive", descriptive_only: true, status_wording: "descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure" },
        { id: "D2", metric: "spy_relative_ar", window: "[-20, -1]", available_event_n: 65, attempted_event_n: 65, median_response: "-0.003032", median_abs_response: "0.039001", direction: "negative", descriptive_only: true, status_wording: "descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure" },
        { id: "D3", metric: "sector_relative_ar", window: "[-20, -1]", available_event_n: 65, attempted_event_n: 65, median_response: "-0.001372", median_abs_response: "0.028352", direction: "negative", descriptive_only: true, status_wording: "descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure" },
        { id: "D4", metric: "sar", window: "[-20, -1]", available_event_n: 65, attempted_event_n: 65, median_response: "-0.071910", median_abs_response: "0.616683", direction: "negative", descriptive_only: true, status_wording: "descriptive timing diagnostic only; no ordinary-reference state is assigned under the frozen procedure" },
      ],
      timing_interpretation: [
        "cell 13 (raw_return): pre-event state ORDINARY_UNRESOLVED beside the published post-anchor ELEVATED surface - the result is more concentrated around the official anchor under daily measurement.",
        "cell 14 (spy_relative_ar): pre-event state ORDINARY_UNRESOLVED beside the published post-anchor ELEVATED surface - the result is more concentrated around the official anchor under daily measurement.",
        "cell 15 (sector_relative_ar): pre-event state ELEVATED beside the published post-anchor ELEVATED surface - the daily data do not isolate whether the response began before or continued through the official event window.",
        "cell 16 (sar): pre-event state ELEVATED beside the published post-anchor ELEVATED surface - the daily data do not isolate whether the response began before or continued through the official event window.",
      ],
      raw_cell_fragility: {
        metric: "raw_return",
        loyo: "4/8",
        loeo: "32/65",
        note: "the raw-return pre-event cell is knife-edge: the direction of its median-percentile reading flips under the published leave-one-out perturbations while its assigned state is unchanged",
      },
      collisions: {
        interval: "[t, t+1]",
        primary_n: 65,
        collision_free_n: 65,
        c2: { register: "opec-known-date-exclusion-register@i0-v1", register_dates: 41, tagged_n: 0, of: 65, subset_n: 0, subset_status: "insufficient subset under the frozen procedure" },
        c1: { status: "unadjudicable", families: "BLS CPI and BLS Employment Situation", reason: "no source-pinned BLS release register covers the frozen era; the C1 CPI / Employment Situation branch is unadjudicable in this execution and no substitute calendar is fetched." },
        fomc_self: { min_anchor_spacing: 8, violations: 0 },
        limitation: "events are described as outside known-register collisions only; no stronger clean-window claim exists, and the C1 branch above is unadjudicable in the published execution",
      },
    },
    j3: {
      nodes: [
        { node: "N0", role: "fomc_decision", panel: [], m_class: null, modifier: null, reading: "ACTIVATED", rule_path: "activation definitional: all 65 frame-complete decisions occurred (J0 section 12.1); event occurrence only, no market claim", limitation: "event trigger; activation definitional (the decision occurred); no market claim" },
        { node: "N1", role: "policy_rates_repricing", panel: [{ member: "2Y_CMT", primary: true, m_class: "M2", state: "ELEVATED" }, { member: "SHY", primary: false, m_class: "M3", state: "ELEVATED" }], m_class: "M2", modifier: "BROAD MEASUREMENT CONSISTENCY", reading: "ACTIVATED", rule_path: "usable M2 primary at State A stands alone -> ACTIVATED (J0 section 5)", limitation: "measurement-limited: the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable; the 2Y CMT blends policy expectations with term premium (J0 section 8)" },
        { node: "N2", role: "balance_sheet_sensitive_second_order", panel: [{ member: "KRE", primary: true, m_class: "M3", state: "ELEVATED" }, { member: "IAT", primary: false, m_class: "M3", state: "ELEVATED" }, { member: "KBE", primary: false, m_class: "M3", state: "ELEVATED" }], m_class: "M3", modifier: "BROAD MEASUREMENT CONSISTENCY", reading: "ACTIVATED", rule_path: "M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule)", limitation: "equity-proxy limits (fund mechanics); single-proxy results stay asset-specific" },
        { node: "N3", role: "broad_financial_sector", panel: [{ member: "XLF", primary: true, m_class: "M3", state: "ELEVATED" }, { member: "VFH", primary: false, m_class: "M3", state: "ELEVATED" }], m_class: "M3", modifier: "BROAD MEASUREMENT CONSISTENCY", reading: "ACTIVATED", rule_path: "M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule)", limitation: "sector ETFs are cap-weighted composites; not a statement about every financial firm" },
      ],
      edges: [
        { edge: "E1", from: "fomc_decision", to: "policy_rates_repricing", upstream_reading: "ACTIVATED", upstream_path: "upstream activation definitional (all 65 anchors exist); UPSTREAM NOT ACTIVATED and DOWNSTREAM WITHOUT UPSTREAM structurally unreachable on E1 (J0 section 12.3)", downstream_state: "ELEVATED", downstream_m_class: "M2", downstream_modifier: "BROAD MEASUREMENT CONSISTENCY", route_b_satisfied: false, state: "PROPAGATED", rule_path: "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (usable M1/M2 primary stands alone (Route A)) -> PROPAGATED (J0 section 5)" },
        { edge: "E2", from: "policy_rates_repricing", to: "balance_sheet_sensitive_second_order", upstream_reading: "ACTIVATED", upstream_path: "usable M2 primary at State A stands alone -> ACTIVATED (J0 section 5)", downstream_state: "ELEVATED", downstream_m_class: "M3", downstream_modifier: "BROAD MEASUREMENT CONSISTENCY", route_b_satisfied: false, state: "PROPAGATED", rule_path: "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)" },
        { edge: "E3", from: "balance_sheet_sensitive_second_order", to: "broad_financial_sector", upstream_reading: "ACTIVATED", upstream_path: "M3 primary at State A with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT) -> ACTIVATED (J0 section 5 corroboration rule)", downstream_state: "ELEVATED", downstream_m_class: "M3", downstream_modifier: "BROAD MEASUREMENT CONSISTENCY", route_b_satisfied: false, state: "PROPAGATED", rule_path: "precedence step 3: upstream ACTIVATED and downstream supports the ELEVATED edge claim (M3 primary with role BROAD MEASUREMENT CONSISTENCY (>= ROLE-CONSISTENT)) -> PROPAGATED (J0 section 5)" },
      ],
      timing_qualifier:
        "timing evidence is lens-dependent under daily measurement — published J2 [-5, -1] pre-event states: raw_return ORDINARY_UNRESOLVED; spy_relative_ar ORDINARY_UNRESOLVED; sector_relative_ar ELEVATED; sar ELEVATED. The J0 section-15 withdrawal condition for the 1d concentration claim was not triggered (tracked J2 section 7). Timing qualifies temporal interpretation only; it rewrites no J1B node state and no edge state.",
      collision_qualifier:
        "exact [t, t+1] collision register: C2 `opec-known-date-exclusion-register@i0-v1` (41 calendar dates) tags 0 of 65 events; the C1 BLS CPI / Employment Situation branch is unadjudicable in the published execution (no source-pinned era register); FOMC self-collision invariant holds (minimum anchor spacing 8). Events are described as outside known-register collisions only; no stronger clean-window claim exists. Collision status qualifies the readout and neither creates nor removes an edge state.",
      supports: [
        "every frozen edge reads **PROPAGATED under the frozen measurement rules**: the frozen upstream and downstream roles show aligned elevated-response states on the published [t, t+1] surface (E1, E2, E3).",
        "every measured role carries **BROAD MEASUREMENT CONSISTENCY**: no reading rests on a single proxy.",
        "claim-ladder ceiling (J0 section 14, tier 5): a **mechanism-consistent descriptive pattern** - this is a descriptive alignment, not proof of transmission, and it is never phrased as a confirmed mechanism.",
        "the rates-role reading and therefore E1 and E2 are **measurement-limited** (J0 section 8).",
        "all of it is same-sample Class B evidence: post-outcome robustness under prospectively frozen new tests, never independent historical confirmation.",
      ],
      unresolved: [
        "the ideal M1 policy-repricing measure (fed funds futures / OIS) is unavailable in the frozen substrate; the rates-role reading rests on an M2 official series plus an M3 investable proxy and stays measurement-limited.",
        "temporal placement is unresolved at daily resolution: timing evidence is lens-dependent under daily measurement; the graph adjudicates response-magnitude alignment, not sequencing.",
        "the C1 BLS CPI / Employment Situation collision branch is unadjudicable in the published execution; freedom from those releases is not certified for any event window.",
        "the three panels and two windows are correlated same-sample views over overlapping events, assets, and reference structures - not independent replications.",
      ],
      non_claims: [
        "causality (edge states are descriptive alignments under frozen measurement rules, never proof of transmission);",
        "prediction;",
        "tradeability;",
        "alpha;",
        "independent historical confirmation of Mission I, J1B, or J2;",
        "permanent price impact;",
        "intraday sequencing (daily data cannot resolve it);",
        "a structural macro model;",
        "mechanism proof beyond the frozen descriptive graph adjudication (tier-5 ceiling, J0 section 14);",
        "any hypothesis-test conclusion (calibration percentiles are placement positions, not test outcomes).",
      ],
    },
  };
}
