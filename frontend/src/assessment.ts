// Outcome readiness, explicit assessment, Dossier preparation and outcome retrieval for frozen hypotheses. The server
// decides everything; this module shapes the requests, refuses replies it cannot read, and never repeats an action by
// itself: a lost reply is settled by a read.
import type { Loaded } from "./api";
import {
  LIFECYCLE_HEADER, isOverview, readable, type BaselineSummary, type HypothesisRow, type StoreState,
} from "./lifecycle.ts";
import type { Dossier } from "./types";

export const ASSESSMENT_VERSION = "lifecycle-assessment-0.1";
export const DOSSIER_VERSION = "lifecycle-dossier-0.1";
export const RETRIEVAL_PLAN_VERSION = "lifecycle-outcome-plan-0.2";
export const RETRIEVAL_RESULT_VERSION = "lifecycle-retrieval-result-0.1";
export const EVALUATE_AND_PREPARE = "Evaluate and prepare Dossier";

export type LifecycleState = "horizon_not_elapsed" | "outcome_missing" | "outcome_held" | "outcome_in_package" |
  "missing_values" | "ready" | "recorded";

export interface DossierState {
  state: "prepared" | "not_prepared" | "problem"; detail: string | null; prepared_at: string | null; file: string | null;
}
export interface AssessmentRow {
  evaluation_id: string; recorded_at: string; as_of: string; verdict: string; rules_version: string;
  rules_hash: string; baseline_snapshot_id: string | null; outcome_snapshot_id: string | null;
  legs: { leg_id: string; primary: boolean; observable_id: string; verdict: string }[];
  action_id: string | null; recorded_by: string; dossier: DossierState;
}
export interface JournalRow extends HypothesisRow {
  provider: string | null; state: LifecycleState | null; state_label: string | null; expected_target: string | null;
  assessments: AssessmentRow[];
}
export interface Journal {
  lifecycle_version: string; assessment_version?: string; store: StoreState; hypotheses: JournalRow[];
  classification: string; order?: string;
}
export interface Expected {
  freeze_date_new_york: string; rule: string; expected_score_anchor: string | null;
  legs: Record<string, { horizon: number; expected_target: string | null }>; note: string;
  latest_expected_target: string | null; counts_after: string | null; elapsed: boolean;
}
export interface LegReadiness {
  leg_id: string; observable_id: string; series_id: string; primary: boolean; horizon: number;
  state: "horizon_not_elapsed" | "outcome_missing" | "missing_values" | "ready";
  event_anchor: string | null; score_anchor: string | null; target: string | null; target_counts_after: string | null;
  gaps: { date: string; status: string }[]; detail: string | null;
}
export interface Candidate {
  snapshot_id: string; summary: BaselineSummary | null; usable: boolean; state: LegReadiness["state"] | null;
  legs: LegReadiness[]; problems: string[];
}
export interface OutcomePackage {
  package_id: string; status: string; received_at: string; coverage: { first: string; last: string } | null;
  covers_expected_targets: boolean; importable: boolean; serving_snapshot: string | null; reasons: string[];
  start: string;
}
export interface Readiness {
  assessment_version: string; hypothesis_id: string; headline: string; published_at: string; frozen_at: string;
  provider: string | null; state: LifecycleState; state_label: string; baseline_problem: string | null;
  expected: Expected; candidates: Candidate[]; packages: OutcomePackage[];
  package_problems: { retrieval: string; problem: string }[]; assessments: AssessmentRow[];
  store_schema: number | null; assessable_store: boolean; rules_note: string; fred_note: string | null;
  default_selection: string; classification: string | null; measurement_convention: string;
}
export interface AssessmentBinding {
  assessment_version: string; hypothesis_id: string; hypothesis_sha256: string; request_identity: string;
  provider: string; baseline_snapshot_id: string; outcome_snapshot_id: string; rules: Record<string, unknown>;
  rules_hash: string; cutoff: string | null; cutoff_rule: string; state: string;
  legs: { leg_id: string; state: string; event_anchor: string | null; score_anchor: string | null;
    target: string | null; gaps: { date: string; status: string }[] }[];
  prior_assessments: string[]; reassessment: boolean; dossier: { dossier_version: string };
}
export interface AssessmentPreview {
  assessment_version: string; preview_sha256: string; binding: AssessmentBinding; assessable: boolean;
  blockers: string[]; state: string; state_label: string; previewed_at: string;
  hypothesis: { hypothesis_id: string; headline: string; published_at: string; frozen_at: string;
    evidence_class: string; usage: string; effective_sha256: string | null; origin: string };
  baseline: BaselineSummary; outcome: BaselineSummary; outcome_problems: string[]; legs: LegReadiness[];
  expected: Expected; rules: { version: string; hash: string; configuration: Record<string, unknown>; note: string };
  cutoff: { at: string | null; rule: string }; prior_assessments: AssessmentRow[]; creates: string[];
  evaluation_note: string; classification: string | null; limitations: string[]; measurement_convention: string;
  provider_called: false; written: false; evaluated: false;
}
export interface Recorded {
  assessment_version: string; state: "recorded"; created: boolean; headline: string; action_id: string;
  hypothesis_id: string; evaluation_id: string; recorded_at: string; dossier: DossierState;
}
export interface AssessmentActionState {
  assessment_version: string; action_id: string; state: "recorded" | "not_recorded"; detail: string;
  hypothesis_id?: string; evaluation_id?: string; recorded_at?: string; dossier?: DossierState;
}
export interface StoredLeg {
  leg_id: string; primary: boolean; observable_id: string; horizon: number; unit: string; verdict: string;
  reason?: string; event_anchor?: string; score_anchor?: string; target_at?: string; measured_change?: number | null;
  signed_move?: number | null; percentile_rank?: number | null; reference_windows?: number;
}
export interface AssessmentView {
  assessment_version: string; hypothesis_id: string; evaluation_id: string; headline: string; published_at: string;
  frozen_at: string; recorded_at: string;
  evaluation: { as_of: string; verdict: string; rules: Record<string, unknown> & { version: string }; rules_hash: string;
    legs: StoredLeg[]; snapshots?: { baseline: string; outcome: string } };
  action: { binding: AssessmentBinding; approval: { received_at: string; reassessment: boolean } } | null;
  /** Each leg's recorded anchors as New York dates, from the server; a stored time is a date's end-of-day placeholder. */
  anchor_dates: Record<string, { event_anchor?: string; score_anchor?: string; target_at?: string }>;
  recorded_by: string; dossier: DossierState; baseline: BaselineSummary; outcome: BaselineSummary | null;
  position: number; assessments: number; classification: string | null; limitations: string[];
  measurement_convention: string;
}
export interface SnapshotStatus {
  snapshot_id: string; verifies: boolean; provider?: string; detail: string;
  raw_source: { held: boolean | null; detail: string } | null;
}
export interface LifecycleDossier {
  lifecycle_version: string; dossier_version: string; hypothesis_id: string; evaluation_id: string;
  action_id: string | null; prepared_at: string; reproduction: string; view: Dossier;
  snapshots: { baseline: SnapshotStatus; outcome: SnapshotStatus };
}
export interface DraftLink {
  draft_id: string; capture_id: string; hypothesis_id: string; action_id: string; frozen_at: string; headline: string;
  draft_view_sha256: string;
  review_at_freeze: { review_id: string; sequence: number; status: string; saved_at: string; attributed_to: string };
}
export interface DraftLinks {
  lifecycle_version: string; links: DraftLink[]; problems: { action_id: string; problem: string }[]; note: string;
}
export interface RetrievalPlan {
  plan_version: string; plan_sha256: string; as_of: string;
  source: { label: string; download: string; key: string; charge: string; vintage_note: string };
  hypotheses: { hypothesis_id: string; headline: string; required_from: string; required_through: string;
    past_sessions: number; held_sessions: number; missing_sessions: string[]; awaiting_release: string[];
    future_sessions: string[] }[];
  missing_sessions: string[]; future_sessions: string[];
  awaiting_release: { session: string; obtainable_from: string }[]; release_rule: string;
  reuse: { snapshots: { snapshot_id: string; hypotheses: string[] }[];
    packages: { package_id: string; hypotheses: string[]; needs_import: boolean }[] };
  requests: 0 | 1; request: { url: string; missing_sessions: number; missing_from: string; missing_to: string } | null;
  note: string; next_attempt: number; retrieval: { enabled: boolean; detail: string };
  attempts: { number: number; started: Record<string, unknown> | null; outcome: Record<string, unknown> | null;
    problem: string | null }[];
}
export interface RetrievalResult {
  result_version: string; plan_sha256: string; attempt: number; hypotheses: string[]; outcome: string;
  detail: string | null; package_id: string | null; validation: string | null; provider_called: true;
}
export interface AttemptState {
  result_version: string; plan_sha256: string; attempt: number; state: "not_started" | "uncertain" | "finished";
  detail: string | null;
}

// ---------------------------------------------------------------- reading

const SHA = /^[0-9a-f]{64}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

function detail(body: unknown): string | null {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? (body as { detail: string }).detail : null;
}

/** A reply is accepted only with this client's version and the fields its pages read. */
export function versioned(body: unknown, key: string, version: string,
                          check: (value: Record<string, unknown>) => boolean): boolean {
  if (typeof body !== "object" || body === null) return false;
  const value = body as Record<string, unknown>;
  return value[key] === version && check(value);
}

const assessmentReply = (check: (value: Record<string, unknown>) => boolean) =>
  (body: unknown) => versioned(body, "assessment_version", ASSESSMENT_VERSION, check);

export const isReadiness = (value: Record<string, unknown>) =>
  typeof value.hypothesis_id === "string" && SHA.test(value.hypothesis_id) && typeof value.state === "string" &&
  Array.isArray(value.candidates) && Array.isArray(value.assessments) && Array.isArray(value.packages) &&
  typeof value.expected === "object" && value.expected !== null;

/** A preview must bind what it shows, write nothing and carry no result. */
export const isAssessmentPreview = (value: Record<string, unknown>) => {
  const binding = value.binding as AssessmentBinding | undefined;
  const hypothesis = value.hypothesis as AssessmentPreview["hypothesis"] | undefined;
  const outcome = value.outcome as BaselineSummary | undefined;
  return typeof value.preview_sha256 === "string" && SHA.test(value.preview_sha256) && typeof binding === "object" &&
    binding !== null && typeof value.assessable === "boolean" && Array.isArray(value.blockers) &&
    value.assessable === ((value.blockers as unknown[]).length === 0) && value.written === false &&
    value.evaluated === false && value.provider_called === false &&
    binding.hypothesis_id === hypothesis?.hypothesis_id && binding.outcome_snapshot_id === outcome?.snapshot_id &&
    (binding.reassessment === (binding.prior_assessments.length > 0)) &&
    (!value.assessable || typeof binding.cutoff === "string");
};
export const isRecorded = (value: Record<string, unknown>) =>
  value.state === "recorded" && typeof value.evaluation_id === "string" && SHA.test(value.evaluation_id) &&
  typeof value.dossier === "object" && value.dossier !== null && typeof value.headline === "string";
export const isAssessmentView = (value: Record<string, unknown>) =>
  typeof value.evaluation_id === "string" && SHA.test(value.evaluation_id) && typeof value.evaluation === "object" &&
  value.evaluation !== null && Array.isArray((value.evaluation as { legs?: unknown }).legs) &&
  typeof value.anchor_dates === "object" && value.anchor_dates !== null &&
  ((value.evaluation as { legs: { leg_id: string }[] }).legs).every((leg) => leg.leg_id in (value.anchor_dates as object));

export function isLifecycleDossier(body: unknown, hypothesisId: string, evaluationId: string): boolean {
  if (typeof body !== "object" || body === null) return false;
  const value = body as Partial<LifecycleDossier>;
  return value.dossier_version === DOSSIER_VERSION && value.hypothesis_id === hypothesisId &&
    value.evaluation_id === evaluationId && typeof value.view === "object" && value.view !== null &&
    value.view.id === hypothesisId && value.view.evaluation_id === evaluationId && value.view.state === "evaluated" &&
    typeof value.snapshots === "object" && value.snapshots !== null;
}
export const isDraftLinks = (value: Record<string, unknown>) =>
  Array.isArray(value.links) && Array.isArray(value.problems) &&
  (value.links as DraftLink[]).every((link) => SHA.test(link.draft_id) && SHA.test(link.hypothesis_id));
export const isRetrievalPlan = (body: unknown) => versioned(body, "plan_version", RETRIEVAL_PLAN_VERSION, (value) =>
  typeof value.plan_sha256 === "string" && SHA.test(value.plan_sha256) && Array.isArray(value.hypotheses) &&
  (value.requests === 0 || value.requests === 1) && (value.requests === 1) === (value.request !== null) &&
  Array.isArray(value.awaiting_release) && typeof value.next_attempt === "number");

async function read<T>(path: string, signal: AbortSignal, accept: (body: unknown) => boolean): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch {
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 404) return { state: "missing", message: detail(body) ?? "Not found." };
  if (!response.ok) return { state: "error", message: detail(body) ?? `Unexpected response (${response.status}).` };
  if (!accept(body)) return { state: "error", message: "The reply could not be read by this page." };
  return { state: "ready", data: body as T };
}

const path = (...parts: string[]) => parts.map(encodeURIComponent).join("/");

/** The journal: the store's state and every frozen hypothesis with its lifecycle state and assessments. */
export const fetchJournal = (signal: AbortSignal) =>
  read<Journal>("/api/lifecycle", signal, (body) => readable(body, (value) =>
    value.assessment_version === ASSESSMENT_VERSION && isOverview(value) &&
    (value.hypotheses as JournalRow[]).every((row) => Array.isArray(row.assessments))));

export const fetchReadiness = (hypothesisId: string, signal: AbortSignal) =>
  read<Readiness>(`/api/lifecycle/hypotheses/${path(hypothesisId)}/readiness`, signal, assessmentReply(isReadiness));
export const fetchAssessment = (hypothesisId: string, evaluationId: string, signal: AbortSignal) =>
  read<AssessmentView>(`/api/lifecycle/hypotheses/${path(hypothesisId)}/assessments/${path(evaluationId)}`, signal,
                       assessmentReply(isAssessmentView));
export const fetchLifecycleDossier = (hypothesisId: string, evaluationId: string, signal: AbortSignal) =>
  read<LifecycleDossier>(`/api/lifecycle/hypotheses/${path(hypothesisId)}/dossiers/${path(evaluationId)}`, signal,
                         (body) => isLifecycleDossier(body, hypothesisId, evaluationId));
export const fetchDraftLinks = (signal: AbortSignal) =>
  read<DraftLinks>("/api/lifecycle/draft-links", signal, (body) => readable(body, isDraftLinks));
/** After a lost reply: read whether this approval recorded an assessment. A read; it never approves again. */
export const checkAssessmentAction = (actionId: string, signal: AbortSignal) =>
  read<AssessmentActionState>(`/api/lifecycle/assessment-actions/${path(actionId)}`, signal,
                              assessmentReply((value) => value.state === "recorded" || value.state === "not_recorded"));
export const checkRetrievalAttempt = (planSha: string, attempt: number, signal: AbortSignal) =>
  read<AttemptState>(`/api/lifecycle/retrievals/${path(planSha)}/${attempt}`, signal,
                     (body) => versioned(body, "result_version", RETRIEVAL_RESULT_VERSION, (value) =>
                       ["not_started", "uncertain", "finished"].includes(String(value.state))));

// ---------------------------------------------------------------- the explicit actions

export type ActionResult<T, P = never> =
  | { state: "done"; status: number; data: T }
  | { state: "refused"; status: number; message: string; preview: P | null }
  | { state: "unconfirmed"; message: string };

/** One POST from this page. A missing reply or a server error is "unconfirmed": nothing is sent again by itself. */
async function act<T, P = never>(target: string, body: object, accept: (body: unknown) => boolean,
                                 acceptPreview?: (body: unknown) => boolean): Promise<ActionResult<T, P>> {
  let response: Response;
  try {
    response = await fetch(target, {
      method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", Accept: "application/json", [LIFECYCLE_HEADER]: "1" },
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Nothing was sent again; check the outcome." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (response.status >= 500) {
    return { state: "unconfirmed", message: detail(payload) ?? `The server failed (${response.status}); check the outcome.` };
  }
  if (!response.ok) {
    const preview = acceptPreview && typeof payload === "object" && payload !== null && "preview" in payload &&
      acceptPreview((payload as { preview: unknown }).preview) ? (payload as { preview: P }).preview : null;
    return { state: "refused", status: response.status, message: detail(payload) ?? `Refused (${response.status}).`,
             preview };
  }
  if (!accept(payload)) return { state: "unconfirmed", message: "The server replied, but the reply could not be read." };
  return { state: "done", status: response.status, data: payload as T };
}

export const importOutcome = (hypothesisId: string, packageId: string) =>
  act<{ created: boolean; reused: boolean; snapshot: BaselineSummary | null; usable: boolean; problems: string[] }>(
    "/api/lifecycle/outcome-imports", { hypothesis_id: hypothesisId, package_id: packageId },
    assessmentReply((value) => typeof value.created === "boolean" && typeof value.usable === "boolean"));
export const previewAssessment = (hypothesisId: string, snapshotId: string) =>
  act<AssessmentPreview>("/api/lifecycle/assessment-preview",
    { inputs: { hypothesis_id: hypothesisId, outcome_snapshot_id: snapshotId } }, assessmentReply(isAssessmentPreview));
/** Evaluate and prepare Dossier: the approval names the preview it approves and whether it is a reassessment. */
export const approveAssessment = (preview: AssessmentPreview, reassessment: boolean) =>
  act<Recorded, AssessmentPreview>("/api/lifecycle/assessments", {
    inputs: { hypothesis_id: preview.binding.hypothesis_id, outcome_snapshot_id: preview.binding.outcome_snapshot_id },
    preview_sha256: preview.preview_sha256, approve_assessment: true, reassessment,
    previewed_binding: preview.binding,
  }, assessmentReply(isRecorded), assessmentReply(isAssessmentPreview));
export const prepareDossier = (hypothesisId: string, evaluationId: string) =>
  act<{ created: boolean; dossier: DossierState; evaluated: false }>("/api/lifecycle/dossier-preparations",
    { hypothesis_id: hypothesisId, evaluation_id: evaluationId, approve_preparation: true },
    assessmentReply((value) => value.evaluated === false && typeof value.dossier === "object"));
export const previewRetrieval = (hypotheses: string[]) =>
  act<RetrievalPlan>("/api/lifecycle/retrieval-preview", { hypotheses }, isRetrievalPlan);
export const approveRetrieval = (plan: RetrievalPlan) =>
  act<RetrievalResult>("/api/lifecycle/retrievals", {
    plan_sha256: plan.plan_sha256, hypotheses: plan.hypotheses.map((row) => row.hypothesis_id),
    attempt: plan.next_attempt,
  }, (body) => versioned(body, "result_version", RETRIEVAL_RESULT_VERSION,
                        (value) => typeof value.outcome === "string" && typeof value.attempt === "number"));

// ---------------------------------------------------------------- presentation

export function assessmentHref(hypothesisId: string, evaluationId: string): string {
  return `/hypotheses/${encodeURIComponent(hypothesisId)}/assessments/${encodeURIComponent(evaluationId)}`;
}
export function lifecycleDossierHref(hypothesisId: string, evaluationId: string): string {
  return `/hypotheses/${encodeURIComponent(hypothesisId)}/dossiers/${encodeURIComponent(evaluationId)}`;
}

/** Verdict words as stored, for reading; never ranked, colored by favourability or summarised into a rate. */
export function verdictWord(verdict: string): string {
  return verdict.replace(/_/g, " ");
}

/** The latest assessment by record time, said as such; never chosen by its result. */
export function latestByRecordTime(rows: AssessmentRow[]): AssessmentRow | null {
  return rows.reduce<AssessmentRow | null>((latest, row) =>
    latest === null || row.recorded_at > latest.recorded_at ||
    (row.recorded_at === latest.recorded_at && row.evaluation_id > latest.evaluation_id) ? row : latest, null);
}

/** The freeze that used this draft, joined only by the draft ID its verified freeze record names. */
export function linkForDraft(links: DraftLinks, draftId: string): DraftLink | null {
  return links.links.find((link) => link.draft_id === draftId) ?? null;
}

export const DOSSIER_STATE_LABEL: Record<DossierState["state"], string> = {
  prepared: "Dossier prepared", not_prepared: "Dossier not prepared", problem: "Dossier file does not verify",
};
