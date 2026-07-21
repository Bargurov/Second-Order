/**
 * live-event-brief-v1 — the local-first Live Event Brief contract (LEB-0).
 *
 * This module is the single source of truth for the brief data shape, its
 * frozen enumerations, and the fixed non-claim.  It is pure data + constants
 * only: no React, no storage, no clock, no id generation.  Every operation
 * that mutates a brief (operations.ts) takes ``now`` and ``id`` as explicit
 * arguments so the pure layer stays deterministic and testable.
 *
 * Product boundary (root CLAUDE.md): a live brief is structured decision
 * support, never a forecast, causal result, significance claim, recommendation
 * or trade signal.  Historical Second Order evidence provides descriptive
 * context for a live event; it never becomes a prediction, recommendation or
 * classification of the live event.  No field here carries buy / sell / long /
 * short / target / conviction / position-sizing semantics.
 */

/** Versioned contract + local-storage key.  Bump only on a breaking change. */
export const SCHEMA_VERSION = "live-event-brief-v1" as const;
export const STORAGE_KEY = "live-event-brief-v1" as const;

// ---------------------------------------------------------------------------
// Frozen enumerations
// ---------------------------------------------------------------------------

/** Brief review-stage lifecycle.  Describes the review stage, NOT the
 *  economic outcome.  Movement is free (forward and backward). */
export const STAGES = [
  "PRE_EVENT",
  "LIVE",
  "ONE_DAY",
  "FIVE_DAY",
  "TWENTY_DAY",
  "CLOSED",
] as const;
export type Stage = (typeof STAGES)[number];

/** Human labels for stages (chrome only; the stored value is the enum). */
export const STAGE_LABELS: Record<Stage, string> = {
  PRE_EVENT: "Pre-event",
  LIVE: "Live",
  ONE_DAY: "1-day",
  FIVE_DAY: "5-day",
  TWENTY_DAY: "20-day",
  CLOSED: "Closed",
};

/** Every substantive research note is visibly typed as exactly one of these. */
export const ENTRY_TYPES = ["FACT", "INTERPRETATION", "UNKNOWN"] as const;
export type EntryType = (typeof ENTRY_TYPES)[number];

/** Operator research states for a competing mechanism hypothesis.  These are
 *  research states, not statistical labels, and never a "winner". */
export const HYPOTHESIS_STATES = [
  "OPEN",
  "SUPPORTED",
  "WEAKENED",
  "FALSIFIED",
  "UNRESOLVED",
] as const;
export type HypothesisState = (typeof HYPOTHESIS_STATES)[number];

/** Asset-role taxonomy.  Deliberately excludes any directional / sizing role. */
export const ASSET_ROLES = [
  "PRIMARY",
  "MARKET_BENCHMARK",
  "SECTOR",
  "RATES",
  "FX",
  "COMMODITY",
  "VOLATILITY",
  "OTHER",
] as const;
export type AssetRole = (typeof ASSET_ROLES)[number];

/** Market-reaction observation horizons. */
export const REACTION_HORIZONS = ["intraday", "1d", "5d", "20d"] as const;
export type ReactionHorizon = (typeof REACTION_HORIZONS)[number];

/** Falsifier evaluation status. */
export const FALSIFIER_STATUSES = [
  "NOT_YET_TESTABLE",
  "OPEN",
  "TRIGGERED",
  "NOT_TRIGGERED",
  "UNRESOLVED",
] as const;
export type FalsifierStatus = (typeof FALSIFIER_STATUSES)[number];

/** Follow-up check due stage (review stage the check is planned for). */
export const FOLLOW_UP_STAGES = [
  "LIVE",
  "ONE_DAY",
  "FIVE_DAY",
  "TWENTY_DAY",
] as const;
export type FollowUpStage = (typeof FOLLOW_UP_STAGES)[number];

/** Follow-up check answer status.  "Overdue" is DERIVED (a not-answered check
 *  whose due stage the brief has reached), never a stored status. */
export const FOLLOW_UP_STATUSES = ["PENDING", "ANSWERED", "UNRESOLVED"] as const;
export type FollowUpStatus = (typeof FOLLOW_UP_STATUSES)[number];

/** Declared comparability of the live family to a published Second Order
 *  cohort.  The operator declares it; the app never INFERS an analog. */
export const COMPARABLE_COHORTS = ["FOMC", "OPEC", "NONE"] as const;
export type ComparableCohort = (typeof COMPARABLE_COHORTS)[number];

// ---------------------------------------------------------------------------
// Fixed claim copy (dedicated non-claim — the one place negated banned
// vocabulary is permitted; all other chrome copy stays banned-word-clean)
// ---------------------------------------------------------------------------

/** The permanent, always-visible non-claim.  A stored brief must carry it
 *  verbatim; the operator-written claim ceiling can never widen past it. */
export const NON_CLAIM =
  "This brief is structured decision support, not a forecast, causal result, " +
  "significance claim, recommendation or trade signal.";

/** Always shown on every historical-context panel. */
export const HISTORICAL_CONTEXT_DISCLAIMER =
  "Historical context is descriptive and does not classify or forecast this live event.";

/** Shown when the live family maps to no published cohort. */
export const NO_COMPARABLE_COHORT =
  "No directly comparable published Second Order cohort is available.";

/**
 * Frozen aggregate Mission vocabulary (Mission G / I / J).  These labels
 * classify published historical cohorts and must never be injected as the
 * verdict of a LIVE event.  Matched case-sensitively as whole tokens against
 * operator-authored verdict-bearing free-text fields (see validate.ts).
 */
export const AGGREGATE_MISSION_LABELS = [
  "ELEVATED",
  "PROPAGATED",
  "ACTIVATED",
  "ORDINARY_UNRESOLVED",
  "ORDINARY-UNRESOLVED",
  "BROAD MEASUREMENT CONSISTENCY",
  "MEMP",
] as const;

/** Maximum simultaneously-active (non-falsified) competing hypotheses. */
export const MAX_ACTIVE_HYPOTHESES = 3;

// ---------------------------------------------------------------------------
// Record shapes
// ---------------------------------------------------------------------------

/** An official / primary source reference for the event. */
export interface SourceReference {
  id: string;
  label: string;
  /** Optional URL to the primary source. */
  url: string;
  /** Optional operator note (e.g. "press release, not yet linked"). */
  note: string;
}

/**
 * A typed research note.  A FACT must carry either a source_reference or an
 * explicit source_note stating the source is not yet attached.  An
 * INTERPRETATION is never rendered as established fact; an UNKNOWN stays
 * visible until explicitly resolved (never silently converted).
 */
export interface TypedEntry {
  id: string;
  type: EntryType;
  text: string;
  /** For FACT: a source_references id, a raw citation, or "". */
  source_reference: string;
  /** For FACT with no source yet: explicit operator note. */
  source_note: string;
  as_of: string;
}

/** The "What changed?" delta.  Never auto-generated in LEB-0. */
export interface WhatChanged {
  previous_state: string;
  new_information: string;
  unchanged_information: string;
  unresolved_information: string;
  operator_delta_summary: string;
}

/** A competing mechanism hypothesis (research states, never a winner). */
export interface Hypothesis {
  hypothesis_id: string;
  name: string;
  mechanism_path: string;
  supporting_facts: string[];
  contradicting_facts: string[];
  unknowns: string[];
  expected_asset_roles: string[];
  falsifiers: string[];
  current_state: HypothesisState;
}

/** A row of the asset-role map.  Descriptive only — no direction or sizing. */
export interface AssetRoleRow {
  id: string;
  asset: string;
  role: AssetRole;
  benchmark: string;
  sector_or_relative_lens: string;
  expected_channel: string;
  observed_move: string;
  window: string;
  basis: string;
  as_of: string;
  limitations: string;
}

/**
 * A manual market-reaction observation.  A missing value is null (shown as
 * unavailable, never omitted).  A numeric value requires a basis.  The
 * reaction is never auto-classified as elevated / ordinary / significant.
 */
export interface MarketReaction {
  id: string;
  horizon: ReactionHorizon;
  value: number | null;
  unit: string;
  basis: string;
  window: string;
  as_of: string;
  source: string;
}

/** Operator-authored historical-context record (the descriptive evidence
 *  itself is fetched lazily and read-only; only the operator's declared
 *  comparability and notes are stored). */
export interface HistoricalContext {
  comparable_cohort: ComparableCohort;
  notes: string;
}

/** A falsifier tied (optionally) to a hypothesis. */
export interface Falsifier {
  falsifier_id: string;
  statement: string;
  linked_hypothesis: string;
  observable: string;
  evaluation_window: string;
  status: FalsifierStatus;
  evidence: string;
  as_of: string;
}

/** A planned follow-up check. */
export interface FollowUp {
  follow_up_id: string;
  question: string;
  linked_hypothesis: string;
  due_stage: FollowUpStage;
  status: FollowUpStatus;
  result: string;
  as_of: string;
}

/** An append-only revision-log entry. */
export interface Revision {
  id: string;
  timestamp: string;
  stage: Stage;
  what_changed: string;
  why_it_changed: string;
  linked_fact_or_falsifier: string;
}

/** The complete brief. */
export interface Brief {
  brief_id: string;
  schema_version: typeof SCHEMA_VERSION;
  title: string;
  event_family: string;
  event_type: string;
  event_date: string;
  scheduled_timestamp: string;
  timezone: string;
  current_stage: Stage;
  created_at: string;
  updated_at: string;
  source_references: SourceReference[];
  fact_summary: TypedEntry[];
  delta_vs_prior: WhatChanged;
  known_unknowns: TypedEntry[];
  mechanism_hypotheses: Hypothesis[];
  asset_roles: AssetRoleRow[];
  market_reactions: MarketReaction[];
  historical_context: HistoricalContext;
  falsifiers: Falsifier[];
  follow_up_checks: FollowUp[];
  revision_log: Revision[];
  claim_ceiling: string;
  non_claim: string;
}

/**
 * Canonical top-level field order for deterministic export/serialisation.
 * Kept in lockstep with the data contract; the export layer rebuilds objects
 * in this order so identical input yields byte-identical output.
 */
export const BRIEF_FIELD_ORDER: readonly (keyof Brief)[] = [
  "brief_id",
  "schema_version",
  "title",
  "event_family",
  "event_type",
  "event_date",
  "scheduled_timestamp",
  "timezone",
  "current_stage",
  "created_at",
  "updated_at",
  "source_references",
  "fact_summary",
  "delta_vs_prior",
  "known_unknowns",
  "mechanism_hypotheses",
  "asset_roles",
  "market_reactions",
  "historical_context",
  "falsifiers",
  "follow_up_checks",
  "revision_log",
  "claim_ceiling",
  "non_claim",
];
