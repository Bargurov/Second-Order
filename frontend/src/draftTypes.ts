// Shapes of the prepared, read-only draft review views (view_version "draft-review-view-0.1").
// A separate contract from the frozen-hypothesis Dossier: a draft is not frozen, has no freeze time and no
// evaluation, chart or ranking. Its map and legs reuse the hypothesis schema's shapes, nothing more.

import type { LegDefinition, MapEdge, MapNode } from "./types";

/** A recorded attempt, grouped for review. A decline ("no_draft") is neither invalid nor a technical failure. */
export type DraftOutcome = "draft" | "no_draft" | "invalid" | "technical_failure";

export interface DraftSummaryRow {
  id: string;
  pilot: string;
  case: string;
  headline: string;
  published_at: string;
  outcome: DraftOutcome;
  model: string;
  prompt_version: string;
  sent_at: string;
}

export interface DraftIndex {
  view_version: string;
  drafts: DraftSummaryRow[];
}

/** The source exactly as the recorded request stated it: untrusted input, shown as plain text. */
export interface DraftSource {
  headline: string;
  source_url: string;
  published_at: string;
  text: string;
}

/** The model's public proposal. */
export interface DraftContent {
  summary: string;
  nodes: MapNode[];
  edges: MapEdge[];
  legs: LegDefinition[];
}

/** What a declining model said publicly; thinking is never included. */
export interface DraftExplanation {
  text: string[];
  stop_reason: string;
  category: string | null;
  provider_explanation: string | null;
}

export interface DraftProvenance {
  pilot: string;
  case: string;
  synthetic_case: boolean;
  model: string;
  effort: string | null;
  max_tokens: number | null;
  prompt_version: string;
  prompt_hash: string;
  request_id: string | null;
  reserved_at: string;
  sent_at: string;
  received_at: string;
  http_status: number | null;
  recorded_outcome: string;
  response_sha256: string | null;
}

export interface DraftReviewView {
  view_version: string;
  id: string;
  review_status: string;
  outcome: DraftOutcome;
  source: DraftSource;
  draft: DraftContent | null;
  explanation: DraftExplanation | null;
  problem: string | null;
  provenance: DraftProvenance;
}

// ---------- Human review records (record_version "draft-human-review-0.1") ----------
// A person's saved judgment of one prepared draft. It never changes the model's proposal: corrections are
// stored separately, attributed to the reviewer, and a status records human judgment only.

export type ReviewStatus = "needs_revision" | "human_reviewed";

export interface LegCorrection {
  rationale?: string;
  falsifier?: string;
  headline_reports_move?: boolean;
}

export interface ReviewCorrections {
  summary: string | null;
  legs: Record<string, LegCorrection>;
}

export interface ReviewRecord {
  record_version: string;
  review_id: string;
  draft_id: string;
  sequence: number;
  parent_review_id: string | null;
  saved_at: string;
  attributed_to: string;
  status: ReviewStatus | null;
  notes: string;
  corrections: ReviewCorrections;
  binding: {
    draft_view_sha256: string;
    draft_view_version: string;
    outcome: string;
    prompt_hash: string;
    response_sha256: string | null;
    request_id: string | null;
    pilot: string;
    case: string;
  };
}

/** Saved versions, with the fingerprint of the prepared view the server holds now. */
export interface ReviewHistory {
  view_version: string;
  draft_id: string;
  draft_view_sha256: string;
  reviews: ReviewRecord[];
}

/** A prepared view with the fingerprint (SHA-256 of its exact bytes) the server sent with it. */
export interface LoadedDraft {
  view: DraftReviewView;
  fingerprint: string;
}

/** What the page sends; the server stamps the time and the version number, and checks the binding. */
export interface ReviewPayload {
  parent_review_id: string | null;
  binding: { draft_view_sha256: string; prompt_hash: string; response_sha256: string | null };
  status: ReviewStatus | null;
  notes: string;
  corrections: ReviewCorrections;
}
