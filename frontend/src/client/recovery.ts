// Same-account recovery of unsaved work across a session expiry, in this tab's memory only (never browser storage).
// When a request answers 401, the Client holds what was typed and not saved under the signed-in user's stable
// user_id. After signing in again the drafts go back only to that user_id, once, and only after an authoritative read
// (GET /api/user/account) confirms who is signed in; anyone else's sign-in discards them unseen, and so does an
// explicit sign-out. A review goes back into its editor only for the same analysis and result fingerprint, and keeps
// the version it was written after, so the server's review-conflict check still applies. Drafts hold form fields only,
// never a password, an approval or a quote; nothing here saves, quotes or runs anything.
import type { Analysis, ReviewStatus } from "../contracts/user.ts";
import { reviewLabel } from "./present.ts";

export interface SourceFields {
  headline: string; source_url: string; date: string; time: string; offset: string; text: string;
}

export type Recoverable =
  | { kind: "source"; fields: SourceFields }
  | { kind: "review"; analysisId: string; headline: string; resultSha256: string;
      /** The latest review version when the notes were written (null before the first): the save's parent. */
      base: string | null; status: ReviewStatus | null; notes: string };

export type ReviewDraft = Extract<Recoverable, { kind: "review" }>;

export const SOURCE_KEY = "new-source";
export const reviewKey = (analysisId: string) => `review:${analysisId}`;

interface Held { owner: string; drafts: Record<string, Recoverable> }

let held: Held | null = null;

/** At a session's end: keep `drafts` for `owner` (a user_id), replacing anything held before. */
export function hold(owner: string, drafts: Record<string, Recoverable>): void {
  held = Object.keys(drafts).length > 0 ? { owner, drafts: { ...drafts } } : null;
}

/** Whose drafts are held, if any. */
export const holding = (): string | null => held?.owner ?? null;

/** A user is signed in: another user's drafts are discarded unseen. Returns whether any are held for this user. */
export function admit(userId: string): boolean {
  if (held && held.owner !== userId) held = null;
  return held !== null;
}

/** After a read confirms the signed-in user: the drafts held for them, once. Anything else held is discarded. */
export function claim(userId: string): Record<string, Recoverable> {
  const drafts = held && held.owner === userId ? held.drafts : {};
  held = null;
  return drafts;
}

/** An explicit sign-out. */
export function discard(): void {
  held = null;
}

/** What to hold at expiry: every draft open now, and every recovered draft not yet reopened. */
export function toHold(live: Map<string, Recoverable>, recovered: Record<string, Recoverable>): Record<string, Recoverable> {
  return { ...recovered, ...Object.fromEntries(live) };
}

/** A recovered review goes back into the editor only for the same analysis and the same result. */
export function reviewRestore(draft: ReviewDraft, analysis: Analysis): "restore" | "stale" {
  return draft.analysisId === analysis.analysis_id && analysis.state === "recorded" &&
    analysis.result_sha256 === draft.resultSha256 ? "restore" : "stale";
}

/** The typed text, to copy before signing in again. */
export function draftText(draft: Recoverable): string {
  if (draft.kind === "review") return draft.notes || (draft.status ? reviewLabel(draft.status) : "");
  return [draft.fields.headline, draft.fields.source_url, draft.fields.text].filter(Boolean).join("\n\n");
}
