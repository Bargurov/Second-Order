/**
 * operations.ts — pure, deterministic brief transformations.
 *
 * Every function here is a pure function of its inputs.  Clock (``now``) and
 * identity (``id``) are always passed in by the caller (the UI supplies real
 * values inside event handlers, never during a render), so the same call with
 * the same arguments always yields the same brief.  No ``Date.now()``, no
 * ``crypto.randomUUID()``, no storage, no network.
 *
 * Invariants owned here (not left to the UI): the append-only revision log,
 * the review-stage change trail, the "up to three active hypotheses" cap, and
 * the derived overdue-follow-up view.
 */
import {
  MAX_ACTIVE_HYPOTHESES,
  NON_CLAIM,
  STAGES,
  type AssetRole,
  type AssetRoleRow,
  type Brief,
  type EntryType,
  type Falsifier,
  type FalsifierStatus,
  type FollowUp,
  type FollowUpStage,
  type FollowUpStatus,
  type Hypothesis,
  type HypothesisState,
  type MarketReaction,
  type ReactionHorizon,
  type Revision,
  type Stage,
  type TypedEntry,
} from "./types";

// ---------------------------------------------------------------------------
// Generic id-keyed list utilities (exported; used by the UI for edit/remove)
// ---------------------------------------------------------------------------

export function addItem<T>(arr: readonly T[], item: T): T[] {
  return [...arr, item];
}

export function patchItem<T>(
  arr: readonly T[],
  idOf: (t: T) => string,
  id: string,
  patch: Partial<T>,
): T[] {
  return arr.map((t) => (idOf(t) === id ? { ...t, ...patch } : t));
}

export function removeItem<T>(
  arr: readonly T[],
  idOf: (t: T) => string,
  id: string,
): T[] {
  return arr.filter((t) => idOf(t) !== id);
}

// ---------------------------------------------------------------------------
// Stage ordering
// ---------------------------------------------------------------------------

const STAGE_ORDINAL: Record<Stage, number> = STAGES.reduce(
  (acc, s, i) => ({ ...acc, [s]: i }),
  {} as Record<Stage, number>,
);

/** Follow-up due stages map onto the same axis as brief stages. */
const FOLLOW_UP_ORDINAL: Record<FollowUpStage, number> = {
  LIVE: STAGE_ORDINAL.LIVE,
  ONE_DAY: STAGE_ORDINAL.ONE_DAY,
  FIVE_DAY: STAGE_ORDINAL.FIVE_DAY,
  TWENTY_DAY: STAGE_ORDINAL.TWENTY_DAY,
};

// ---------------------------------------------------------------------------
// Brief-level helpers
// ---------------------------------------------------------------------------

/** Return a copy with ``updated_at`` advanced to ``now``. */
export function touch(brief: Brief, now: string): Brief {
  return { ...brief, updated_at: now };
}

/** Shallow-merge a partial brief and advance ``updated_at``.  Identity and
 *  the fixed non-claim are never overwritten from a patch. */
export function patchBrief(brief: Brief, patch: Partial<Brief>, now: string): Brief {
  return {
    ...brief,
    ...patch,
    brief_id: brief.brief_id,
    schema_version: brief.schema_version,
    created_at: brief.created_at,
    non_claim: NON_CLAIM,
    updated_at: now,
  };
}

// ---------------------------------------------------------------------------
// Create
// ---------------------------------------------------------------------------

export interface NewBriefInput {
  title: string;
  event_family: string;
  event_type: string;
  event_date: string;
  scheduled_timestamp: string;
  timezone: string;
}

export function createBrief(input: NewBriefInput, now: string, id: string, revisionId: string): Brief {
  return {
    brief_id: id,
    schema_version: "live-event-brief-v1",
    title: input.title,
    event_family: input.event_family,
    event_type: input.event_type,
    event_date: input.event_date,
    scheduled_timestamp: input.scheduled_timestamp,
    timezone: input.timezone,
    current_stage: "PRE_EVENT",
    created_at: now,
    updated_at: now,
    source_references: [],
    fact_summary: [],
    delta_vs_prior: {
      previous_state: "",
      new_information: "",
      unchanged_information: "",
      unresolved_information: "",
      operator_delta_summary: "",
    },
    known_unknowns: [],
    mechanism_hypotheses: [],
    asset_roles: [],
    market_reactions: [],
    historical_context: { comparable_cohort: "NONE", notes: "" },
    falsifiers: [],
    follow_up_checks: [],
    revision_log: [
      {
        id: revisionId,
        timestamp: now,
        stage: "PRE_EVENT",
        what_changed: "Brief created.",
        why_it_changed: "New live event opened for structured review.",
        linked_fact_or_falsifier: "",
      },
    ],
    claim_ceiling: "",
    non_claim: NON_CLAIM,
  };
}

// ---------------------------------------------------------------------------
// Revision log (append-only) + stage changes
// ---------------------------------------------------------------------------

export interface RevisionInput {
  stage?: Stage;
  what_changed: string;
  why_it_changed?: string;
  linked_fact_or_falsifier?: string;
}

/** Append a revision entry.  The log is append-only: earlier entries are never
 *  edited or dropped. */
export function appendRevision(brief: Brief, input: RevisionInput, now: string, id: string): Brief {
  const rev: Revision = {
    id,
    timestamp: now,
    stage: input.stage ?? brief.current_stage,
    what_changed: input.what_changed,
    why_it_changed: input.why_it_changed ?? "",
    linked_fact_or_falsifier: input.linked_fact_or_falsifier ?? "",
  };
  return { ...brief, revision_log: [...brief.revision_log, rev], updated_at: now };
}

/**
 * Move to another review stage (forward or backward) without losing notes,
 * recording the transition in the append-only revision log.  Moving to the
 * current stage is a no-op that still leaves earlier notes intact.
 */
export function setStage(brief: Brief, stage: Stage, now: string, revisionId: string): Brief {
  if (stage === brief.current_stage) return brief;
  const moved: Brief = { ...brief, current_stage: stage };
  return appendRevision(
    moved,
    {
      stage,
      what_changed: `Review stage changed to ${stage}.`,
      why_it_changed: "Operator advanced or revisited the review stage.",
    },
    now,
    revisionId,
  );
}

// ---------------------------------------------------------------------------
// Typed research entries
// ---------------------------------------------------------------------------

export interface TypedEntryInput {
  type: EntryType;
  text: string;
  source_reference?: string;
  source_note?: string;
}

export function addTypedEntry(
  brief: Brief,
  section: "fact_summary" | "known_unknowns",
  input: TypedEntryInput,
  now: string,
  id: string,
): Brief {
  const entry: TypedEntry = {
    id,
    type: input.type,
    text: input.text,
    source_reference: input.source_reference ?? "",
    source_note: input.source_note ?? "",
    as_of: now,
  };
  return { ...brief, [section]: [...brief[section], entry], updated_at: now };
}

// ---------------------------------------------------------------------------
// Competing hypotheses (cap: up to three ACTIVE, i.e. non-falsified)
// ---------------------------------------------------------------------------

export function countActiveHypotheses(brief: Brief): number {
  return brief.mechanism_hypotheses.filter((h) => h.current_state !== "FALSIFIED").length;
}

export interface HypothesisInput {
  name: string;
  mechanism_path: string;
  supporting_facts?: string[];
  contradicting_facts?: string[];
  unknowns?: string[];
  expected_asset_roles?: string[];
  falsifiers?: string[];
  current_state?: HypothesisState;
}

export type AddResult = { ok: true; brief: Brief } | { ok: false; reason: string };

export function addHypothesis(brief: Brief, input: HypothesisInput, now: string, id: string): AddResult {
  const state = input.current_state ?? "OPEN";
  if (state !== "FALSIFIED" && countActiveHypotheses(brief) >= MAX_ACTIVE_HYPOTHESES) {
    return {
      ok: false,
      reason: `Up to ${MAX_ACTIVE_HYPOTHESES} active competing hypotheses. Falsify or remove one first.`,
    };
  }
  const hyp: Hypothesis = {
    hypothesis_id: id,
    name: input.name,
    mechanism_path: input.mechanism_path,
    supporting_facts: input.supporting_facts ?? [],
    contradicting_facts: input.contradicting_facts ?? [],
    unknowns: input.unknowns ?? [],
    expected_asset_roles: input.expected_asset_roles ?? [],
    falsifiers: input.falsifiers ?? [],
    current_state: state,
  };
  return {
    ok: true,
    brief: { ...brief, mechanism_hypotheses: [...brief.mechanism_hypotheses, hyp], updated_at: now },
  };
}

// ---------------------------------------------------------------------------
// Asset roles
// ---------------------------------------------------------------------------

export interface AssetRoleInput {
  asset: string;
  role: AssetRole;
  benchmark?: string;
  sector_or_relative_lens?: string;
  expected_channel?: string;
  observed_move?: string;
  window?: string;
  basis?: string;
  limitations?: string;
}

export function addAssetRole(brief: Brief, input: AssetRoleInput, now: string, id: string): Brief {
  const row: AssetRoleRow = {
    id,
    asset: input.asset,
    role: input.role,
    benchmark: input.benchmark ?? "",
    sector_or_relative_lens: input.sector_or_relative_lens ?? "",
    expected_channel: input.expected_channel ?? "",
    observed_move: input.observed_move ?? "",
    window: input.window ?? "",
    basis: input.basis ?? "",
    as_of: now,
    limitations: input.limitations ?? "",
  };
  return { ...brief, asset_roles: [...brief.asset_roles, row], updated_at: now };
}

// ---------------------------------------------------------------------------
// Market reactions (a missing value stays null → shown as unavailable)
// ---------------------------------------------------------------------------

export interface MarketReactionInput {
  horizon: ReactionHorizon;
  value: number | null;
  unit?: string;
  basis?: string;
  window?: string;
  source?: string;
}

export function addMarketReaction(brief: Brief, input: MarketReactionInput, now: string, id: string): Brief {
  const rx: MarketReaction = {
    id,
    horizon: input.horizon,
    value: input.value,
    unit: input.unit ?? "",
    basis: input.basis ?? "",
    window: input.window ?? "",
    as_of: now,
    source: input.source ?? "",
  };
  return { ...brief, market_reactions: [...brief.market_reactions, rx], updated_at: now };
}

// ---------------------------------------------------------------------------
// Falsifiers
// ---------------------------------------------------------------------------

export interface FalsifierInput {
  statement: string;
  linked_hypothesis?: string;
  observable?: string;
  evaluation_window?: string;
  status?: FalsifierStatus;
  evidence?: string;
}

export function addFalsifier(brief: Brief, input: FalsifierInput, now: string, id: string): Brief {
  const f: Falsifier = {
    falsifier_id: id,
    statement: input.statement,
    linked_hypothesis: input.linked_hypothesis ?? "",
    observable: input.observable ?? "",
    evaluation_window: input.evaluation_window ?? "",
    status: input.status ?? "NOT_YET_TESTABLE",
    evidence: input.evidence ?? "",
    as_of: now,
  };
  return { ...brief, falsifiers: [...brief.falsifiers, f], updated_at: now };
}

// ---------------------------------------------------------------------------
// Follow-up checks
// ---------------------------------------------------------------------------

export interface FollowUpInput {
  question: string;
  linked_hypothesis?: string;
  due_stage: FollowUpStage;
  status?: FollowUpStatus;
  result?: string;
}

export function addFollowUp(brief: Brief, input: FollowUpInput, now: string, id: string): Brief {
  const fu: FollowUp = {
    follow_up_id: id,
    question: input.question,
    linked_hypothesis: input.linked_hypothesis ?? "",
    due_stage: input.due_stage,
    status: input.status ?? "PENDING",
    result: input.result ?? "",
    as_of: now,
  };
  return { ...brief, follow_up_checks: [...brief.follow_up_checks, fu], updated_at: now };
}

/**
 * Follow-up checks whose due stage the brief has reached (or passed) and which
 * are not yet ANSWERED.  Derived — never a stored status — so it always tracks
 * the current stage.
 */
export function overdueFollowUps(brief: Brief): FollowUp[] {
  const current = STAGE_ORDINAL[brief.current_stage];
  return brief.follow_up_checks.filter(
    (f) => f.status !== "ANSWERED" && current >= FOLLOW_UP_ORDINAL[f.due_stage],
  );
}
