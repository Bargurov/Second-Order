// Pure logic for a person's review of a saved draft. A review never changes the model's proposal: it is saved
// separately as a new version, attributed to the reviewer, and its status records human judgment only. A version
// is about the prepared view whose fingerprint it carries; versions saved against another view are never applied.

import type {
  DraftReviewView, LegCorrection, ReviewCorrections, ReviewHistory, ReviewPayload, ReviewRecord, ReviewStatus,
} from "./draftTypes";

export const STATUS_LABEL: Record<ReviewStatus, string> = {
  needs_revision: "Needs revision",
  human_reviewed: "Human-reviewed",
};
export const NO_STATUS_LABEL = "No judgment recorded";
export const STATUS_NOTE = "These labels record your judgment. They do not verify the model's reasoning, make a " +
  "draft eligible for research, freeze it or evaluate it.";
export const ATTRIBUTION_LABEL = "You, the local reviewer";
export const DISCARD_QUESTION = "Discard your unsaved review changes?";
export const MAX_NOTES = 20_000;
export const MAX_TEXT = 4_000;

export interface LegForm {
  rationale: string;
  falsifier: string;
  headline_reports_move: boolean;
}

export interface ReviewForm {
  status: ReviewStatus | null;
  notes: string;
  summary: string;
  legs: Record<string, LegForm>;
}

const NO_CORRECTIONS: ReviewCorrections = { summary: null, legs: {} };

/** The latest version of any view: what the next save follows. */
export const latestReview = (history: ReviewHistory): ReviewRecord | null => history.reviews.at(-1) ?? null;

export const savedAgainst = (record: ReviewRecord, fingerprint: string) =>
  record.binding.draft_view_sha256 === fingerprint;

/** The latest version, only if it was saved against the view that was loaded; otherwise none is current. */
export function currentReview(history: ReviewHistory, fingerprint: string): ReviewRecord | null {
  const latest = latestReview(history);
  return latest && savedAgainst(latest, fingerprint) ? latest : null;
}

/** Where a reviewer starts: the latest saved version over the model's proposal, or the proposal alone. */
export function formFrom(view: DraftReviewView, latest: ReviewRecord | null): ReviewForm {
  const corrections = latest?.corrections ?? NO_CORRECTIONS;
  const draft = view.draft;
  return {
    status: latest?.status ?? null,
    notes: latest?.notes ?? "",
    summary: draft ? corrections.summary ?? draft.summary : "",
    legs: Object.fromEntries((draft?.legs ?? []).map((leg) => {
      const corrected = corrections.legs[leg.id] ?? {};
      return [leg.id, {
        rationale: corrected.rationale ?? leg.rationale,
        falsifier: corrected.falsifier ?? leg.falsifier,
        headline_reports_move: corrected.headline_reports_move ?? leg.headline_reports_move,
      }];
    })),
  };
}

/** Only real changes from the model's proposal. Text is trimmed; a field put back to the original is not a correction. */
export function correctionsFrom(view: DraftReviewView, form: ReviewForm): ReviewCorrections {
  const draft = view.draft;
  if (!draft) return { summary: null, legs: {} };
  const legs: Record<string, LegCorrection> = {};
  for (const leg of draft.legs) {
    const edited = form.legs[leg.id];
    if (!edited) continue;
    const change: LegCorrection = {};
    if (edited.rationale.trim() !== leg.rationale) change.rationale = edited.rationale.trim();
    if (edited.falsifier.trim() !== leg.falsifier) change.falsifier = edited.falsifier.trim();
    if (edited.headline_reports_move !== leg.headline_reports_move) {
      change.headline_reports_move = edited.headline_reports_move;
    }
    if (Object.keys(change).length > 0) legs[leg.id] = change;
  }
  const summary = form.summary.trim();
  return { summary: summary !== draft.summary ? summary : null, legs };
}

/** The save, bound to the loaded view's fingerprint and following the latest version of any view. */
export function payloadFrom(view: DraftReviewView, fingerprint: string, form: ReviewForm,
                            latest: ReviewRecord | null): ReviewPayload {
  return {
    parent_review_id: latest?.review_id ?? null,
    binding: { draft_view_sha256: fingerprint, prompt_hash: view.provenance.prompt_hash,
               response_sha256: view.provenance.response_sha256 },
    status: form.status,
    notes: form.notes,
    corrections: correctionsFrom(view, form),
  };
}

/** JSON with sorted keys, so two reviews compare by content. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

const content = (review: Pick<ReviewRecord, "status" | "notes" | "corrections"> | null) =>
  canonical({ status: review?.status ?? null, notes: review?.notes ?? "",
              corrections: review?.corrections ?? NO_CORRECTIONS });

/** Whether the form differs from the current version (or, with none current, from an empty review). */
export function isDirty(view: DraftReviewView, form: ReviewForm, current: ReviewRecord | null): boolean {
  return content(current) !== content({ ...form, corrections: correctionsFrom(view, form) });
}

/** Whether `record` is the version `sent` would create: same parent, view and content. */
const recordsPayload = (record: ReviewRecord, sent: ReviewPayload) =>
  record.parent_review_id === sent.parent_review_id &&
  record.binding.draft_view_sha256 === sent.binding.draft_view_sha256 && content(record) === content(sent);

/** History with a confirmed save appended, or null if the reply is not the next version of what was sent. */
export function appendSaved(history: ReviewHistory, sent: ReviewPayload, record: ReviewRecord): ReviewHistory | null {
  const next = record.draft_id === history.draft_id && record.sequence === history.reviews.length + 1 &&
    recordsPayload(record, sent);
  return next ? { ...history, reviews: [...history.reviews, record] } : null;
}

/**
 * "saved": the save was recorded and is the latest version. "superseded": it was recorded, but a newer version
 * follows it. "not-saved": nothing follows the save's parent. "conflict": a different version took its place.
 */
export type Reconciled =
  | { state: "saved"; record: ReviewRecord }
  | { state: "superseded"; record: ReviewRecord; latest: ReviewRecord }
  | { state: "not-saved" }
  | { state: "conflict"; message: string };

/**
 * What the saved versions say about a save whose reply was lost. Only the version that follows the save's parent
 * can be it; with none, nothing was saved. Read-only: this never sends the save again.
 */
export function reconcile(history: ReviewHistory, sent: ReviewPayload): Reconciled {
  const latest = latestReview(history);
  const follower = history.reviews.find((record) => record.parent_review_id === sent.parent_review_id);
  if (!follower) {
    return (latest?.review_id ?? null) === sent.parent_review_id
      ? { state: "not-saved" }
      : { state: "conflict", message: "The saved versions no longer include the version you started from." };
  }
  if (!recordsPayload(follower, sent)) {
    return { state: "conflict",
             message: `A different version ${follower.sequence} was saved after the one you started from, so yours ` +
               "was not saved." };
  }
  if (follower === latest || latest === null) return { state: "saved", record: follower };
  return { state: "superseded", record: follower, latest };
}

/** The versions up to and including `record`: what a page knows when it has not taken in the newer ones. */
export const historyUpTo = (history: ReviewHistory, record: ReviewRecord): ReviewHistory =>
  ({ ...history, reviews: history.reviews.slice(0, record.sequence) });

export const isEmptyReview = (payload: ReviewPayload) =>
  !payload.notes.trim() && payload.status === null && payload.corrections.summary === null &&
  Object.keys(payload.corrections.legs).length === 0;

/** Problems the server would refuse, shown before saving. */
export function formProblems(view: DraftReviewView, form: ReviewForm): string[] {
  const problems: string[] = [];
  if (form.notes.length > MAX_NOTES) problems.push(`Notes are limited to ${MAX_NOTES} characters.`);
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(form.notes)) problems.push("Notes contain a control character.");
  if (!view.draft) return problems;
  const texts: [string, string][] = [["The summary", form.summary]];
  for (const leg of view.draft.legs) {
    const edited = form.legs[leg.id];
    if (edited) texts.push([`Leg ${leg.id} reasoning`, edited.rationale], [`Leg ${leg.id} falsifier`, edited.falsifier]);
  }
  for (const [name, text] of texts) {
    if (!text.trim()) problems.push(`${name} cannot be empty; restore the model's text instead.`);
    if (text.length > MAX_TEXT) problems.push(`${name} is limited to ${MAX_TEXT} characters.`);
  }
  return problems;
}

export interface CorrectionRow {
  field: string;
  original: string;
  corrected: string;
}

/** A saved version's corrections beside the model's original values, for display. */
export function correctionRows(view: DraftReviewView, record: ReviewRecord): CorrectionRow[] {
  const draft = view.draft;
  if (!draft) return [];
  const rows: CorrectionRow[] = [];
  if (record.corrections.summary !== null) {
    rows.push({ field: "Summary", original: draft.summary, corrected: record.corrections.summary });
  }
  const labels = new Map(draft.nodes.map((node) => [node.id, node.label]));
  const flag = (value: boolean) => (value ? "Yes, the source reports this move" : "No");
  for (const leg of draft.legs) {
    const change = record.corrections.legs[leg.id];
    if (!change) continue;
    const name = `${leg.primary ? "Primary" : "Secondary"} leg · ${labels.get(leg.node_id) ?? leg.node_id}`;
    if (change.rationale !== undefined) rows.push({ field: `${name} · reasoning`, original: leg.rationale, corrected: change.rationale });
    if (change.falsifier !== undefined) rows.push({ field: `${name} · falsifier`, original: leg.falsifier, corrected: change.falsifier });
    if (change.headline_reports_move !== undefined) {
      rows.push({ field: `${name} · move already reported?`, original: flag(leg.headline_reports_move),
                  corrected: flag(change.headline_reports_move) });
    }
  }
  return rows;
}

export const statusLabel = (status: ReviewStatus | null) => (status ? STATUS_LABEL[status] : NO_STATUS_LABEL);

export const correctionCount = (corrections: ReviewCorrections) =>
  (corrections.summary === null ? 0 : 1) +
  Object.values(corrections.legs).reduce((sum, change) => sum + Object.keys(change).length, 0);
