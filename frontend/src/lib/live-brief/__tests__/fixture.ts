/**
 * A complete, valid ``live-event-brief-v1`` brief used across the LEB tests.
 * Returned fresh each call so a mutation in one test never leaks into another.
 */
import { NON_CLAIM, type Brief } from "../types";

export function validBriefFixture(): Brief {
  return {
    brief_id: "brief-0001",
    schema_version: "live-event-brief-v1",
    title: "March FOMC rate decision",
    event_family: "FOMC",
    event_type: "Scheduled monetary-policy decision",
    event_date: "2026-03-18",
    scheduled_timestamp: "2026-03-18T18:00:00Z",
    timezone: "America/New_York",
    current_stage: "PRE_EVENT",
    created_at: "2026-03-15T12:00:00Z",
    updated_at: "2026-03-15T12:00:00Z",
    source_references: [
      {
        id: "src-1",
        label: "FOMC statement",
        url: "https://www.federalreserve.gov/newsevents/pressreleases",
        note: "official press release",
      },
    ],
    fact_summary: [
      {
        id: "fact-1",
        type: "FACT",
        text: "Policy rate held at the prior target range.",
        source_reference: "src-1",
        source_note: "",
        as_of: "2026-03-18T18:05:00Z",
      },
      {
        id: "interp-1",
        type: "INTERPRETATION",
        text: "The statement language reads marginally less restrictive.",
        source_reference: "",
        source_note: "",
        as_of: "2026-03-18T18:10:00Z",
      },
    ],
    delta_vs_prior: {
      previous_state: "Market priced a hold with a hawkish tilt.",
      new_information: "Dot plot unchanged; press conference pending.",
      unchanged_information: "Balance-sheet runoff pace.",
      unresolved_information: "Timing of the first cut.",
      operator_delta_summary: "Statement broadly as expected; guidance the open question.",
    },
    known_unknowns: [
      {
        id: "unk-1",
        type: "UNKNOWN",
        text: "Whether the press conference shifts the cut path.",
        source_reference: "",
        source_note: "no source yet — resolves at the presser",
        as_of: "2026-03-18T18:05:00Z",
      },
    ],
    mechanism_hypotheses: [
      {
        hypothesis_id: "hyp-1",
        name: "Duration-relief channel",
        mechanism_path: "less-restrictive guidance -> lower front-end yields -> long-duration bid",
        supporting_facts: ["fact-1"],
        contradicting_facts: [],
        unknowns: ["unk-1"],
        expected_asset_roles: ["RATES", "PRIMARY"],
        falsifiers: ["fals-1"],
        current_state: "OPEN",
      },
      {
        hypothesis_id: "hyp-2",
        name: "No-change reprice",
        mechanism_path: "guidance unchanged -> muted cross-asset response",
        supporting_facts: [],
        contradicting_facts: [],
        unknowns: [],
        expected_asset_roles: ["MARKET_BENCHMARK"],
        falsifiers: [],
        current_state: "UNRESOLVED",
      },
    ],
    asset_roles: [
      {
        id: "asset-1",
        asset: "TLT",
        role: "RATES",
        benchmark: "IEF",
        sector_or_relative_lens: "long-duration Treasuries",
        expected_channel: "front-end guidance to duration",
        observed_move: "",
        window: "1d",
        basis: "close-to-close, benchmark-relative",
        as_of: "2026-03-18T18:05:00Z",
        limitations: "single-name, no adjustment for issuance",
      },
    ],
    market_reactions: [
      {
        id: "rx-1",
        horizon: "1d",
        value: null,
        unit: "%",
        basis: "",
        window: "close-to-close",
        as_of: "2026-03-18T18:05:00Z",
        source: "operator entry",
      },
      {
        id: "rx-2",
        horizon: "intraday",
        value: -0.4,
        unit: "%",
        basis: "benchmark-relative to SPY",
        window: "event to close",
        as_of: "2026-03-18T20:00:00Z",
        source: "operator entry",
      },
    ],
    historical_context: {
      comparable_cohort: "FOMC",
      notes: "Consulted the Mission I FOMC ordinary-period comparison for context only.",
    },
    falsifiers: [
      {
        falsifier_id: "fals-1",
        statement: "Front-end yields rise on a less-restrictive read.",
        linked_hypothesis: "hyp-1",
        observable: "2y yield direction over 1d",
        evaluation_window: "1d",
        status: "NOT_YET_TESTABLE",
        evidence: "",
        as_of: "2026-03-18T18:05:00Z",
      },
    ],
    follow_up_checks: [
      {
        follow_up_id: "fu-1",
        question: "Did the duration bid persist to 5d?",
        linked_hypothesis: "hyp-1",
        due_stage: "FIVE_DAY",
        status: "PENDING",
        result: "",
        as_of: "2026-03-18T18:05:00Z",
      },
    ],
    revision_log: [
      {
        id: "rev-1",
        timestamp: "2026-03-15T12:00:00Z",
        stage: "PRE_EVENT",
        what_changed: "Brief created.",
        why_it_changed: "New scheduled event.",
        linked_fact_or_falsifier: "",
      },
    ],
    claim_ceiling: "Descriptive pre-event structuring; no directional read.",
    non_claim: NON_CLAIM,
  };
}
