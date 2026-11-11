// The person's own review of a recorded result: append-only versions, each bound to the result fingerprint the page
// shows (result_sha256) and following the latest version. Saving is always an explicit action; this module only builds
// the form and says why it cannot be saved yet.
import { MAX_NOTES, type Analysis, type Review, type ReviewForm, type ReviewStatus } from "../contracts/user.ts";

export interface Draft { status: ReviewStatus | null; notes: string }

export const latestReview = (analysis: Analysis): Review | null => analysis.reviews.at(-1) ?? null;

/** A version counts as the current judgment only when it was saved against the result shown now. */
export const isCurrent = (review: Review, analysis: Analysis) => review.result_sha256 === analysis.result_sha256;

/** The editor starts from the latest version saved against this result, or empty. */
export function startingDraft(analysis: Analysis): Draft {
  const latest = latestReview(analysis);
  return latest && isCurrent(latest, analysis) ? { status: latest.status, notes: latest.notes } : { status: null, notes: "" };
}

export function isDirty(analysis: Analysis, draft: Draft): boolean {
  const start = startingDraft(analysis);
  return start.status !== draft.status || start.notes !== draft.notes;
}

/** Why the draft cannot be saved now; empty when it can. */
export function draftProblems(analysis: Analysis, draft: Draft): string[] {
  const problems: string[] = [];
  if (analysis.state !== "recorded" || analysis.result_sha256 === null) problems.push("There is no recorded result to review.");
  if (Array.from(draft.notes).length > MAX_NOTES) problems.push(`Notes are limited to ${MAX_NOTES.toLocaleString("en-US")} characters.`);
  if (draft.status === null && draft.notes.trim() === "") problems.push("Choose a status or write a note.");
  const latest = latestReview(analysis);
  if (latest && isCurrent(latest, analysis) && latest.status === draft.status && latest.notes === draft.notes) {
    problems.push("Nothing changed since the last saved version.");
  }
  return problems;
}

/** The ReviewForm for the result shown, following the latest saved version, or `base`: the version a recovered draft
 * was written after, so a version saved since is refused as a conflict rather than silently followed. */
export function reviewForm(analysis: Analysis, draft: Draft, base?: string | null): ReviewForm {
  return { parent_review_id: base === undefined ? latestReview(analysis)?.review_id ?? null : base,
           result_sha256: analysis.result_sha256 ?? "", status: draft.status, notes: draft.notes };
}
