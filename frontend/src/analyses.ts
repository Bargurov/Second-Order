// My analyses: pure logic over the server's library of Tracker analyses and their human reviews.
// Every label restates a recorded value. Nothing here infers a topic, a review status or missing metadata, and a record
// that the server could not verify, or that this client cannot read, is listed as unreadable, never as "not reviewed".

// Explicit .ts specifiers: the Node test runner loads this module directly.
import { OUTCOME_INFO } from "./drafts.ts";
import { formatUtc } from "./format.ts";
import { publishedLocal } from "./library.ts";
import { STATUS_LABEL } from "./review.ts";
import type { DraftOutcome } from "./draftTypes";

export const ANALYSES_VIEW_VERSION = "analysis-library-view-0.1";
export const MOCK_RUN_MODEL_NOTE = "no provider was contacted";

export type ResponseMode = "mock" | "paid";
export type ReviewStatusValue = "human_reviewed" | "needs_revision";

export type ReviewState =
  | { state: "none"; versions: 0 }
  | { state: "current"; versions: number; status: ReviewStatusValue | null; latest_saved_at: string;
      notes_excerpt: string; notes_truncated: boolean; corrected_fields: number }
  | { state: "stale"; versions: number; latest_saved_at: string }
  | { state: "invalid"; versions: null; problem: string };

export interface AnalysisEntry {
  draft_id: string;
  capture_id: string;
  draft_view_sha256: string;
  event: { headline: string; source_url: string; published_at: string; published_at_as_supplied: string };
  captured_at: string;
  outcome: DraftOutcome;
  recorded_outcome: string;
  mode: ResponseMode;
  provenance: { model: string; effort: string | null; prompt_version: string; sent_at: string; received_at: string;
                http_status: number | null; request_id: string | null };
  model_output: { kind: "summary" | "explanation" | "problem"; text: string | null };
  review: ReviewState;
}

/** A record that could not be shown, with why. capture_id or draft_id is null when the record does not state it. */
export interface UnreadableRecord {
  capture_id: string | null;
  draft_id: string | null;
  problem: string;
}

export interface AnalysesLibrary {
  view_version: string;
  provider_called: false;
  entries: AnalysisEntry[];
  damaged: UnreadableRecord[];
  not_listed: { saved_events: { none: number; incomplete: number; awaiting_publication: number };
                prepared_drafts: number | null };
}

const HASH = /^[a-f0-9]{64}$/;
const isString = (value: unknown): value is string => typeof value === "string";
const isText = (value: unknown): value is string => isString(value) && value.length > 0;
const isTime = (value: unknown) => isString(value) && !Number.isNaN(Date.parse(value));
const isCount = (value: unknown) => Number.isInteger(value) && (value as number) >= 0;
const record = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
const OUTPUT_KIND: Record<DraftOutcome, AnalysisEntry["model_output"]["kind"]> = {
  draft: "summary", no_draft: "explanation", invalid: "problem", technical_failure: "problem",
};

function reviewProblem(value: unknown): string | null {
  const review = record(value);
  if (!review) return "it has no review state";
  switch (review.state) {
    case "none":
      return review.versions === 0 ? null : "its review state is inconsistent";
    case "current":
      return Number.isInteger(review.versions) && (review.versions as number) >= 1 &&
        (review.status === null || review.status === "human_reviewed" || review.status === "needs_revision") &&
        isTime(review.latest_saved_at) && isString(review.notes_excerpt) && typeof review.notes_truncated === "boolean" &&
        isCount(review.corrected_fields) ? null : "its current review is incomplete";
    case "stale":
      return Number.isInteger(review.versions) && (review.versions as number) >= 1 && isTime(review.latest_saved_at)
        ? null : "its review state is inconsistent";
    case "invalid":
      return review.versions === null && isText(review.problem) ? null : "its review state is inconsistent";
    default:
      return "its review state is not recognised";
  }
}

/** Why an entry cannot be shown, or null when every field it is shown by has its expected type and agrees. */
export function entryProblem(value: unknown): string | null {
  const entry = record(value);
  if (!entry) return "it is not a record";
  const event = record(entry.event);
  const provenance = record(entry.provenance);
  const output = record(entry.model_output);
  if (!HASH.test(String(entry.draft_id)) || !HASH.test(String(entry.draft_view_sha256)) || !isText(entry.capture_id)) {
    return "its identifiers are missing";
  }
  if (!event || !isText(event.headline) || !isString(event.source_url) || !isTime(event.published_at) ||
      !isText(event.published_at_as_supplied) || !isTime(entry.captured_at)) {
    return "its event is incomplete";
  }
  if (!(String(entry.outcome) in OUTCOME_INFO) || !isText(entry.recorded_outcome)) return "its outcome is not recognised";
  if (entry.mode !== "mock" && entry.mode !== "paid") return "its response mode is not recognised";
  if (!provenance || !isText(provenance.model) || !isText(provenance.prompt_version) || !isTime(provenance.sent_at) ||
      !isTime(provenance.received_at) || !(provenance.effort === null || isString(provenance.effort)) ||
      !(provenance.http_status === null || Number.isInteger(provenance.http_status)) ||
      !(provenance.request_id === null || isString(provenance.request_id))) {
    return "its provenance is incomplete";
  }
  if (entry.mode === "mock" && (provenance.http_status !== null || provenance.request_id !== null)) {
    return "it is labelled a local mock but records a provider reply";
  }
  if (!output || output.kind !== OUTPUT_KIND[entry.outcome as DraftOutcome] ||
      !(output.text === null || isString(output.text))) {
    return "its model output does not match its outcome";
  }
  return reviewProblem(entry.review);
}

/**
 * The library as this client can show it, or why it cannot. The whole reply is refused only when its own envelope is
 * wrong; an entry this client cannot read is moved to the unreadable records with the reason, never dropped.
 */
export function readAnalyses(body: unknown): { library: AnalysesLibrary } | { problem: string } {
  const reply = record(body);
  const notListed = record(reply?.not_listed);
  const saved = record(notListed?.saved_events);
  if (!reply || reply.view_version !== ANALYSES_VIEW_VERSION || reply.provider_called !== false ||
      !Array.isArray(reply.entries) || !Array.isArray(reply.damaged) || !saved ||
      !["none", "incomplete", "awaiting_publication"].every((key) => isCount(saved[key])) ||
      !(notListed?.prepared_drafts === null || isCount(notListed?.prepared_drafts))) {
    return { problem: "The library reply could not be verified as this client's version, so nothing is shown." };
  }
  const entries: AnalysisEntry[] = [];
  const damaged: UnreadableRecord[] = [];
  const seen = new Set<string>();
  for (const item of reply.entries as unknown[]) {
    const problem = entryProblem(item);
    const id = record(item)?.draft_id;
    const capture = record(item)?.capture_id;
    if (problem === null && !seen.has(id as string)) {
      seen.add(id as string);
      entries.push(item as AnalysisEntry);
    } else {
      damaged.push({ capture_id: isText(capture) ? capture : null, draft_id: HASH.test(String(id)) ? String(id) : null,
                     problem: `This page could not read a listed analysis: ${problem ?? "it is listed twice"}.` });
    }
  }
  for (const item of reply.damaged as unknown[]) {
    const row = record(item);
    damaged.push({ capture_id: isText(row?.capture_id) ? row.capture_id : null,
                   draft_id: HASH.test(String(row?.draft_id)) ? String(row?.draft_id) : null,
                   problem: isText(row?.problem) ? row.problem : "The server reported an unreadable record without a reason." });
  }
  return { library: { ...(reply as unknown as AnalysesLibrary), entries, damaged } };
}

// ---------------------------------------------------------------- labels

export const MODE_INFO: Record<ResponseMode, { label: string; className: string }> = {
  mock: { label: "Local mock", className: "mode-mock" },
  paid: { label: "Paid provider response", className: "mode-paid" },
};

export type ReviewKey = "none" | "needs_revision" | "human_reviewed" | "notes" | "stale" | "invalid";

export const REVIEW_INFO: Record<ReviewKey, { label: string; className: string }> = {
  none: { label: "Not reviewed", className: "review-none" },
  needs_revision: { label: STATUS_LABEL.needs_revision, className: "review-revision" },  // The review form's own words.
  human_reviewed: { label: STATUS_LABEL.human_reviewed, className: "review-done" },
  notes: { label: "Notes, no status", className: "review-notes" },
  stale: { label: "Not reviewed for this view", className: "review-stale" },
  invalid: { label: "Review history unreadable", className: "review-invalid" },
};

export function reviewKey(review: ReviewState): ReviewKey {
  if (review.state === "current") return review.status ?? "notes";
  return review.state;
}

const versions = (count: number) => (count === 1 ? "1 saved version" : `${count} saved versions`);

/** What the review state means, restating its exact condition. */
export function reviewDetail(review: ReviewState): string {
  switch (review.state) {
    case "none":
      return "No review has been saved for this analysis.";
    case "current": {
      const judged = review.status === "human_reviewed" ? "marked reviewed by a person"
        : review.status === "needs_revision" ? "marked as needing revision" : "saved with notes and no status";
      return `The latest of ${versions(review.versions)}, ${judged}, was saved on ${formatUtc(review.latest_saved_at)} ` +
        "against the view shown now.";
    }
    case "stale":
      return `The latest of ${versions(review.versions)} was saved against an earlier version of this view, so it ` +
        "does not count as a review of the view shown now.";
    case "invalid":
      return `The saved review versions do not verify, so no review status is shown: ${review.problem}`;
  }
}

export function modeDetail(entry: AnalysisEntry): string {
  const { model, prompt_version: version, http_status: status } = entry.provenance;
  return entry.mode === "mock"
    ? `Generated locally from a fixture shaped as ${model} (${version}); ${MOCK_RUN_MODEL_NOTE}.`
    : `One approved paid request to ${model} (${version})${status === null ? "; no HTTP status was recorded" : `, HTTP ${status}`}.`;
}

export const OUTPUT_LABEL: Record<AnalysisEntry["model_output"]["kind"], string> = {
  summary: "The model's proposed summary",
  explanation: "The model's explanation for declining",
  problem: "The recorded problem",
};

/** The publication time in its recorded offset, and the same instant in UTC. The reader's time zone is never used. */
export function publicationTimes(entry: AnalysisEntry): { local: string | null; utc: string } {
  const local = publishedLocal(entry.event.published_at_as_supplied);
  return { local: local ? `${local.day}, ${local.clock} ${local.offset}` : null,
           utc: formatUtc(entry.event.published_at) };
}

/** A short preview, cut at a word where possible; the review screen shows the whole text. */
export function excerpt(text: string | null, limit = 240): string | null {
  if (text === null) return null;
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= limit) return flat;
  const cut = flat.slice(0, limit);
  const space = cut.lastIndexOf(" ");
  return `${(space > limit * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

/** A preview of the latest current note, marked as cut when either the server or this preview shortened it. */
export function noteExcerpt(review: ReviewState, limit = 200): string | null {
  if (review.state !== "current" || !review.notes_excerpt.trim()) return null;
  const shown = excerpt(review.notes_excerpt, limit) as string;
  return review.notes_truncated && !shown.endsWith("…") ? `${shown}…` : shown;
}

/** A source address shown as a link only when it is an http(s) URL; anything else stays plain text. */
export function sourceLink(url: string): { href: string; label: string } | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? { href: parsed.href, label: parsed.host } : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------- search, filters and addresses

export interface AnalysesFilters {
  query: string;
  outcome: DraftOutcome | null;
  mode: ResponseMode | null;
  review: ReviewKey | null;
}

export const OUTCOME_ORDER: DraftOutcome[] = ["draft", "no_draft", "invalid", "technical_failure"];
export const MODE_ORDER: ResponseMode[] = ["mock", "paid"];
export const REVIEW_ORDER: ReviewKey[] = ["none", "needs_revision", "human_reviewed", "notes", "stale", "invalid"];
export const ANALYSES_PATH = "/analyses";

const pick = <T extends string>(value: string | null, allowed: readonly T[]): T | null =>
  value !== null && (allowed as readonly string[]).includes(value) ? value as T : null;

/** The browsing state from the address (?q=&outcome=&mode=&review=); an unknown value is no filter, never a guess. */
export function readAnalysesFilters(search: string): AnalysesFilters {
  const params = new URLSearchParams(search);
  return { query: params.get("q") ?? "", outcome: pick(params.get("outcome"), OUTCOME_ORDER),
           mode: pick(params.get("mode"), MODE_ORDER), review: pick(params.get("review"), REVIEW_ORDER) };
}

export function analysesHref({ query, outcome, mode, review }: AnalysesFilters): string {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (outcome) params.set("outcome", outcome);
  if (mode) params.set("mode", mode);
  if (review) params.set("review", review);
  const text = params.toString();
  return text ? `${ANALYSES_PATH}?${text}` : ANALYSES_PATH;
}

/** What a search reads: the headline, the source address, the model's output and the latest current note. */
export function searchText(entry: AnalysisEntry): string {
  const note = entry.review.state === "current" ? entry.review.notes_excerpt : "";
  return [entry.event.headline, entry.event.source_url, entry.model_output.text ?? "", note].join("\n").toLowerCase();
}

function matches(entry: AnalysisEntry, filters: AnalysesFilters, skip?: keyof AnalysesFilters): boolean {
  const words = filters.query.toLowerCase().split(/\s+/).filter(Boolean);
  const text = searchText(entry);
  return words.every((word) => text.includes(word)) &&
    (skip === "outcome" || filters.outcome === null || entry.outcome === filters.outcome) &&
    (skip === "mode" || filters.mode === null || entry.mode === filters.mode) &&
    (skip === "review" || filters.review === null || reviewKey(entry.review) === filters.review);
}

export const filterAnalyses = (entries: AnalysisEntry[], filters: AnalysesFilters) =>
  entries.filter((entry) => matches(entry, filters));

/** For one filter, how many entries each of its options would show with the search and the other filters applied. */
export function facetCounts(entries: AnalysisEntry[], filters: AnalysesFilters,
                            facet: "outcome" | "mode" | "review"): Record<string, number> {
  const counts: Record<string, number> = { all: 0 };
  for (const entry of entries) {
    if (!matches(entry, filters, facet)) continue;
    counts.all += 1;
    const key = facet === "outcome" ? entry.outcome : facet === "mode" ? entry.mode : reviewKey(entry.review);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

/** The review screen for an entry: the Tracker's existing deep link, plus the way back to this exact view. */
export const reviewHref = (entry: AnalysisEntry, filters: AnalysesFilters) =>
  `/?draft=${entry.draft_id}&from=${encodeURIComponent(analysesHref(filters))}`;

/** The private overview of the saved event behind an entry. */
export const captureOverviewHref = (entry: AnalysisEntry) => `/events/capture/${encodeURIComponent(entry.capture_id)}`;

/** An event overview's own address: /events/inbox/<id> or /events/capture/<id>, with no query or fragment. */
const OVERVIEW_RETURN = /^\/events\/(inbox|capture)\/[^/?#]+$/;

/** The way back from the review screen: only an address of My analyses or of an event overview, never another one. */
export function returnPath(search: string): string | null {
  const from = new URLSearchParams(search).get("from");
  if (from === null || from.includes("#")) return null;
  return from === ANALYSES_PATH || from.startsWith(`${ANALYSES_PATH}?`) || OVERVIEW_RETURN.test(from) ? from : null;
}

/** The words of the way back, by where it leads. */
export const returnLabel = (path: string) =>
  OVERVIEW_RETURN.test(path) ? "← Back to the event overview" : "← Back to My analyses";
