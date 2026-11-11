// Headline triage client. A selection of up to 25 inbox entries (current or retained) is resolved by the server from
// saved results first: each entry's result is reused under its input fingerprint, and only missing work is planned,
// as at most one request. Preview saves that request's exact bytes; a response needs its own explicit approval; reads
// only read. Relations are suggestions from the response that concluded them: entries are never merged, chained or
// hidden here, and every entry keeps its own official link. Every server reply is verified before it is shown.
import type { Loaded } from "./api.ts";
import { officialLink, utcStamp, type InboxItem } from "./inbox.ts";

export const TRIAGE_VIEW_VERSION = "headline-triage-view-0.4";
export const MAX_SELECTION = 25;
const TRIAGE_ID = /^triage-[0-9a-f]{24}$/;
const SHA256 = /^[0-9a-f]{64}$/;

export type Mode = "simulated" | "paid";
export type Status = "reuse" | "process" | "earlier_version" | "unresolved";

export interface TriageInput {
  id: string;
  source: string;
  publisher: string;
  feed_category: string;
  title: string;
  title_truncated: boolean;
  link: string;
  /** The feed's own timestamp: feed metadata, not a verified publication time. */
  feed_timestamp: { raw: string | null; element: string; utc: string | null };
  excerpt: string | null;
  excerpt_truncated: boolean;
}

export interface TriageConfig {
  model: string;
  effort: string;
  thinking: { type: string };
  prompt_version: string;
  schema_version: string;
}

export interface Provenance {
  triage_id: string;
  mode: Mode;
  config: TriageConfig;
  /** False when the result came from an earlier model, prompt or schema version. */
  current_config: boolean;
  received_at: string;
  request_sha256: string;
  response_id: string;
  request_id: string | null;
  /** The validation policy that accepted the result. */
  validation_policy: string;
  /** Set only when the result was accepted on an explicit local re-check, not when its response arrived. */
  revalidation: RecheckProvenance | null;
}

export interface RecheckProvenance {
  validation_policy: string;
  revalidated_at: string;
  original_outcome: string;
  original_validation_policy: string;
  original_message: string | null;
}

/** An explicit local re-check of a recorded response that was not accepted. Nothing is sent by one. */
export interface Recheck {
  state: "complete" | "invalid";
  validation_policy: string;
  current_policy: boolean;
  revalidated_at?: string;
  outcome: "accepted" | "not_accepted" | null;
  message?: string | null;
  detail?: string;
}

export interface EntryResult {
  category: string;
  event_type: string | null;
  summary: string;
  /** Numbers the summary or event type states that the entry's own title and excerpt do not. */
  figures_not_in_inputs: string[];
}

export interface Claim {
  claims: number;
  triage_id: string | null;
  claimed_at?: string;
  state: string;
  outcome?: string | null;
  detail?: string | null;
}

export interface SelectionRow {
  input: TriageInput;
  fingerprint: string;
  location: "current" | "retained";
  status: Status;
  /** The current result (reuse), or the earlier-version result shown with its provenance. */
  result: EntryResult | null;
  provenance: Provenance | null;
  claim: Claim | null;
  reprocess: boolean;
  other_versions_with_results: number;
  in_request: "entry" | "context" | null;
}

export type RelationKind = "possibly_same_event" | "update_or_correction" | "separate_releases";

export interface TriageRelation {
  relation: RelationKind;
  label: string;
  item_ids: string[];
  reason: string;
  feed_dates: { distinct_utc_dates: string[]; without_timestamp: number; note: string };
  provenance: Provenance;
  /** Whether the response's relations were checked against its request's comparison pairs (false: headline-triage-0.2). */
  scope_checked: boolean;
}

export interface TriageEstimate {
  simulated_usd: number;
  estimated_paid_if_output_reaches_max_usd: number;
  input_tokens_assumed: number;
  comparison_context_tokens_assumed: number;
  output_tokens_at_max: number;
  rate_card: string;
  prices: { source: string; read_on: string };
  assumptions: string[];
  caveat: string;
}

export type Outcome = "triaged" | "not_accepted" | "provider_error" | "no_reply" | "credential_echo";

export type TriageAttempt =
  | { mode: string; attempt: string; state: "none" }
  | { mode: string; attempt: string; state: "incomplete"; detail: string; sent: boolean }
  | { mode: string; attempt: string; state: "invalid"; detail: string }
  | { mode: string; attempt: string; state: "complete"; outcome: Outcome; outcome_note: string; message: string | null;
      sent_at: string; received_at: string; request_id: string | null; cost: { usd: number; basis: string } | null;
      validation_policy?: string; revalidation?: Recheck | null; revalidatable?: boolean;
      result_basis?: "accepted_on_receipt" | "accepted_on_local_recheck" | null };

export interface Plan {
  requests: 0 | 1;
  entries: string[];
  context: string[];
  reused: string[];
  earlier_version: string[];
  unresolved: string[];
  reprocess: string[];
  pairs: { rule: string; candidates: number; compared: number; needed: [string, string][]; unresolved: [string, string][];
           earlier: [string, string][] };
  triage_id: string | null;
  request_sha256: string | null;
  request_bytes: number;
  request: Record<string, unknown> | null;
  max_tokens: number | null;
  cost_estimate: TriageEstimate | null;
  prepared: boolean;
  attempts: { simulated: TriageAttempt; paid: TriageAttempt } | null;
}

export interface Modes {
  simulated: { enabled: boolean; detail: string };
  paid: { enabled: boolean; detail: string };
}

export interface SelectionView {
  view_version: string;
  mode: Mode;
  config: TriageConfig;
  provider_called: boolean;
  items: SelectionRow[];
  relations: TriageRelation[];
  plan: Plan;
  taxonomy: Record<string, string>;
  unreadable_requests: { triage_id: string; detail: string }[];
  modes: Modes;
  prepared_now?: boolean;
}

export interface RequestsListing {
  view_version: string;
  modes: Modes;
  requests: {
    triage_id: string; state: "ready" | "unreadable"; prepared_at: string | null; detail?: string;
    entry_count?: number; context_count?: number; titles?: string[]; item_ids?: string[]; current_config?: boolean;
    comparison_pairs?: [string, string][] | null; sendable?: boolean;
    attempts?: Record<Mode, { state: string; outcome: string | null; attempts: number; detail: string | null;
                              attempt?: string; validation_policy?: string | null; response_sha256?: string | null;
                              revalidation?: Recheck | null; revalidatable?: boolean }>;
  }[];
}

const STATUSES = new Set(["reuse", "process", "earlier_version", "unresolved"]);
const RELATION_KINDS = new Set(["possibly_same_event", "update_or_correction", "separate_releases"]);
const OUTCOMES = new Set(["triaged", "not_accepted", "provider_error", "no_reply", "credential_echo"]);
const text = (value: unknown) => typeof value === "string";
const subset = (values: unknown, ids: Set<string>) => Array.isArray(values) && values.every((value) => ids.has(value));

function verifiedResult(result: unknown, taxonomy: Record<string, string>): boolean {
  const value = result as EntryResult | null;
  return !!value && value.category in taxonomy && text(value.summary) && (value.event_type === null || text(value.event_type))
    && Array.isArray(value.figures_not_in_inputs);
}

function verifiedAttempt(attempt: unknown): boolean {
  const value = attempt as TriageAttempt | null;
  if (!value || !text(value.attempt)) return false;
  if (value.state === "none") return true;
  if (value.state === "incomplete" || value.state === "invalid") return text(value.detail);
  return value.state === "complete" && OUTCOMES.has(value.outcome) && text(value.outcome_note);
}

/** A selection view this page can show, or null. It fails closed on anything unexpected. */
export function verifiedSelection(body: unknown): SelectionView | null {
  const view = body as SelectionView | null;
  if (view?.view_version !== TRIAGE_VIEW_VERSION || (view.mode !== "simulated" && view.mode !== "paid") ||
      !Array.isArray(view.items) || view.items.length < 1 || view.items.length > MAX_SELECTION ||
      !Array.isArray(view.relations) || !view.plan || !view.taxonomy || typeof view.taxonomy !== "object" ||
      typeof view.modes?.simulated?.enabled !== "boolean" || typeof view.modes?.paid?.enabled !== "boolean" ||
      !Array.isArray(view.unreadable_requests)) return null;
  const ids = new Set(view.items.map((row) => row?.input?.id));
  if (ids.size !== view.items.length) return null;
  for (const row of view.items) {
    const input = row.input;
    if (!text(input.id) || !text(input.title) || !text(input.link) || !officialLink(input.link) || !input.feed_timestamp ||
        !STATUSES.has(row.status) || (row.location !== "current" && row.location !== "retained") || !text(row.fingerprint))
      return null;
    // A reused or earlier-version entry shows its saved result and where it came from; nothing else claims one.
    if ((row.status === "reuse" || row.status === "earlier_version") &&
        (!verifiedResult(row.result, view.taxonomy) || !row.provenance || !TRIAGE_ID.test(String(row.provenance.triage_id))))
      return null;
    if (row.result !== null && !verifiedResult(row.result, view.taxonomy)) return null;
    if (row.status === "reuse" && row.provenance?.current_config !== true) return null;
    if (row.status === "earlier_version" && row.provenance?.current_config !== false) return null;
    if (row.status === "unresolved" && !row.claim) return null;
    if (row.provenance && (typeof row.provenance.validation_policy !== "string" || !(row.provenance.revalidation === null ||
        typeof row.provenance.revalidation?.validation_policy === "string"))) return null;
    if ((row.in_request === "entry") !== (row.status === "process") ||
        ![null, "entry", "context"].includes(row.in_request)) return null;
  }
  for (const relation of view.relations) {
    const members = relation?.item_ids;
    if (!RELATION_KINDS.has(relation?.relation) || !text(relation.label) || !text(relation.reason) ||
        !Array.isArray(members) || members.length < 2 || new Set(members).size !== members.length ||
        !subset(members, ids as Set<string>) || !relation.feed_dates || !TRIAGE_ID.test(String(relation.provenance?.triage_id)) ||
        typeof relation.scope_checked !== "boolean")
      return null;
  }
  const plan = view.plan;
  const processing = view.items.filter((row) => row.status === "process").map((row) => row.input.id);
  const context = view.items.filter((row) => row.in_request === "context").map((row) => row.input.id);
  if (JSON.stringify(plan.entries) !== JSON.stringify(processing) || JSON.stringify(plan.context) !== JSON.stringify(context) ||
      !subset(plan.reprocess, ids as Set<string>) || !plan.pairs ||
      ![plan.pairs.needed, plan.pairs.unresolved, plan.pairs.earlier].every((pairs) => Array.isArray(pairs) &&
        pairs.every((pair) => Array.isArray(pair) && pair.length === 2 && pair[0] !== pair[1] &&
                              subset(pair, ids as Set<string>)))) return null;
  if (plan.requests === 0) {
    if (plan.entries.length || plan.pairs.needed.length || plan.triage_id !== null || plan.cost_estimate !== null) return null;
  } else if (plan.requests === 1) {
    if (!TRIAGE_ID.test(String(plan.triage_id)) || !SHA256.test(String(plan.request_sha256)) || !plan.request ||
        typeof plan.cost_estimate?.estimated_paid_if_output_reaches_max_usd !== "number" ||
        !Array.isArray(plan.cost_estimate.assumptions) || typeof plan.max_tokens !== "number") return null;
    if (plan.prepared && (!plan.attempts || !verifiedAttempt(plan.attempts.simulated) || !verifiedAttempt(plan.attempts.paid)))
      return null;
  } else return null;
  return view;
}

function verifiedListing(body: unknown): RequestsListing | null {
  const listing = body as RequestsListing | null;
  if (listing?.view_version !== TRIAGE_VIEW_VERSION || !Array.isArray(listing.requests) ||
      typeof listing.modes?.paid?.enabled !== "boolean") return null;
  return listing.requests.every((row) => TRIAGE_ID.test(String(row?.triage_id)) &&
    (row.state === "unreadable" ? text(row.detail) : row.state === "ready" && Array.isArray(row.titles))) ? listing : null;
}

function problem(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" ? detail : `Unexpected response (${status}).`;
}

async function read<T>(path: string, check: (body: unknown) => T | null, signal?: AbortSignal): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    return { state: "error", message: "The local API did not answer. Start it with: python -m second_order serve" };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) return { state: response.status === 404 ? "missing" : "error", message: problem(body, response.status) };
  const value = check(body);
  return value ? { state: "ready", data: value } : { state: "error", message: "The triage could not be verified." };
}

/** The server's saved triage requests and what this server offers. Reads only. */
export const fetchRequests = (signal?: AbortSignal) => read("/api/triage", verifiedListing, signal);

/** What a selection already has and the one request (or none) its missing work needs. Reads only. */
export function fetchSelection(ids: string[], mode: Mode, reprocess: string[], signal?: AbortSignal) {
  const query = new URLSearchParams([["mode", mode], ...ids.map((id) => ["ids", id]), ...reprocess.map((id) => ["reprocess", id])]);
  return read(`/api/triage/selection?${query}`, verifiedSelection, signal);
}

export type TriageAction<T> = { state: "done"; value: T } | { state: "failed" | "unconfirmed"; message: string };

async function act<T>(path: string, body: object, check: (body: unknown) => T | null): Promise<TriageAction<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Triage": "1" },
      body: JSON.stringify(body),
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server, and nothing was retried. Read the selection again to see what was recorded." };
  }
  const payload: unknown = await response.json().catch(() => null);
  // A 4xx is a refusal made before anything was reserved or sent; a 5xx does not prove what was recorded.
  if (!response.ok) return { state: response.status >= 500 ? "unconfirmed" : "failed", message: problem(payload, response.status) };
  const value = check(payload);
  return value ? { state: "done", value } : { state: "unconfirmed", message: "The server replied, but its answer could not be verified." };
}

/** Plan the selection and, only when missing work needs a request, save its exact bytes. Nothing is sent. */
export const previewTriage = (ids: string[], mode: Mode, reprocess: string[]) =>
  act("/api/triage", { item_ids: ids, mode, reprocess_ids: reprocess }, verifiedSelection);

/** The one approved attempt of the planned request in the view's mode. It names the comparisons the preview planned;
 *  the server checks them, the hash, the explicit re-requests and, for a paid request, the repeated estimate against
 *  the work as it stands before anything is reserved or sent, and refuses a stale approval. */
export function approveRequest(view: SelectionView) {
  const plan = view.plan;
  const shared = { request_sha256: plan.request_sha256, reprocess_ids: plan.reprocess, comparison_pairs: plan.pairs.needed };
  const body = view.mode === "simulated"
    ? { ...shared, approve_simulated_response: true }
    : { ...shared, approve_paid_request: true, estimated_max_usd: plan.cost_estimate?.estimated_paid_if_output_reaches_max_usd };
  return act(`/api/triage/${encodeURIComponent(String(plan.triage_id))}/${view.mode}`, body,
             (payload) => (payload as { view_version?: unknown } | null)?.view_version === TRIAGE_VIEW_VERSION ? payload : null);
}

export type RequestView = { view_version: string; triage_id: string; attempts: Record<Mode, TriageAttempt> };

/** An explicit local re-check of one recorded response that was not accepted, under the server's current rules. It
 *  names the exact saved response; nothing is sent, regenerated or changed, and the outcome is recorded apart. */
export const recheckResponse = (triageId: string, attempt: string, responseSha256: string) =>
  act(`/api/triage/${encodeURIComponent(triageId)}/${encodeURIComponent(attempt)}/revalidate`,
      { response_sha256: responseSha256 }, (payload) => {
        const view = payload as RequestView | null;
        return view?.view_version === TRIAGE_VIEW_VERSION && view.attempts ? view : null;
      });

const sentence = (text: string) => /[.!?]$/.test(text.trim()) ? text.trim() : `${text.trim()}.`;

/** What a send recorded, from the server's own record of the attempt; nothing is inferred from the plan. */
export function sendOutcome(mode: Mode, attempt: TriageAttempt | undefined): { tone: "done" | "error"; text: string;
                                                                              reread?: boolean } {
  if (!attempt || attempt.state === "none") {
    return { tone: "error", reread: true, text: `No ${mode} attempt is recorded for this request. Read the selection again.` };
  }
  if (attempt.state === "incomplete") return { tone: "error", reread: true, text: attempt.detail };
  if (attempt.state === "invalid") return { tone: "error", reread: true, text: `The recorded ${mode} attempt does not verify: ${attempt.detail}` };
  const detail = sentence(attempt.message ?? attempt.outcome_note);
  switch (attempt.outcome) {
    case "triaged":
      return { tone: "done", text: `The ${mode} response was recorded and accepted under ${attempt.validation_policy ??
        "the validation rules"}; its results are saved for reuse.` };
    case "not_accepted":
      return { tone: "error", text: `The ${mode} response was recorded but not accepted: ${detail} Nothing from it is ` +
        "shown as triage; its entries stay unresolved, and nothing is sent again on its own." };
    case "no_reply":
      return { tone: "error", text: detail };
    case "provider_error":
      return { tone: "error", text: `${detail} Nothing is retried.` };
    default:
      return { tone: "error", text: detail };
  }
}

/** What a local re-check recorded, plainly. */
export function recheckOutcome(check: Recheck | null | undefined): { tone: "done" | "error"; text: string } {
  if (check?.state === "complete" && check.outcome === "accepted") {
    return { tone: "done", text: `Accepted on a local re-check under ${check.validation_policy}. Nothing was sent or ` +
      "regenerated: it is the response this request received, under its original prompt, and the original record " +
      "of it as not accepted is unchanged." };
  }
  if (check?.state === "complete" && check.outcome === "not_accepted") {
    return { tone: "error", text: `Still not accepted on a local re-check under ${check.validation_policy}: ` +
      `${sentence(check.message ?? "")} Nothing was sent, and the original record is unchanged.` };
  }
  return { tone: "error", text: "The local re-check could not be confirmed. Read the saved requests again." };
}

/** How a result accepted on a local re-check is labelled; empty for one accepted when its response arrived. */
export function recheckLabel(provenance: Provenance): string {
  const check = provenance.revalidation;
  return check ? ` · accepted on a local re-check under ${check.validation_policy} (${utcStamp(check.revalidated_at)}),` +
    ` after it was not accepted on receipt under ${check.original_validation_policy}; generated by this request's ` +
    "original response, not regenerated or re-sent" : "";
}

/** Add or remove one entry; a selection never exceeds MAX_SELECTION. */
export function toggled(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((value) => value !== id);
  return selected.length >= MAX_SELECTION ? selected : [...selected, id];
}

/** Whether two selections hold the same entries, in any order. */
export const sameEntries = (a: string[], b: string[]) => a.length === b.length && a.every((id) => b.includes(id));

export interface RowNote { relation: TriageRelation; others: TriageInput[]; unmerged: boolean }
export interface TriageRow extends SelectionRow { notes: RowNote[] }
export type TriageSection =
  | { kind: "group"; relation: TriageRelation; rows: TriageRow[] }
  | { kind: "entry"; row: TriageRow };

/**
 * The grouped view. Each "possibly the same event" suggestion becomes a group exactly as stated, newest response
 * first, at its first entry's place. A suggestion from another response that shares an entry with a group already
 * placed is never merged or chained into it: it stays a note on its entries. Every entry appears exactly once.
 */
export function groupedSections(view: SelectionView): TriageSection[] {
  const groups: TriageRelation[] = [];
  for (const relation of view.relations) {
    if (relation.relation !== "possibly_same_event") continue;
    if (!groups.some((group) => group.item_ids.some((id) => relation.item_ids.includes(id)))) groups.push(relation);
  }
  const rows = triageRows(view, groups);
  const placed = new Set<string>();
  const sections: TriageSection[] = [];
  for (const row of rows) {
    if (placed.has(row.input.id)) continue;
    const group = groups.find((relation) => relation.item_ids.includes(row.input.id));
    if (group) {
      const members = rows.filter((candidate) => group.item_ids.includes(candidate.input.id));
      members.forEach((member) => placed.add(member.input.id));
      sections.push({ kind: "group", relation: group, rows: members });
    } else {
      placed.add(row.input.id);
      sections.push({ kind: "entry", row });
    }
  }
  return sections;
}

/** Every entry once, in order, with the relations it is part of; those shown as groups are left out of its notes. */
export function triageRows(view: SelectionView, groups: TriageRelation[] = []): TriageRow[] {
  return view.items.map((row) => ({
    ...row,
    notes: view.relations.filter((relation) => relation.item_ids.includes(row.input.id) && !groups.includes(relation))
      .map((relation) => ({
        relation, unmerged: relation.relation === "possibly_same_event" && groups.length > 0,
        others: view.items.filter((other) => other.input.id !== row.input.id && relation.item_ids.includes(other.input.id))
          .map((other) => other.input),
      })),
  }));
}

/** Said of a relation from a headline-triage-0.2 response, whose relations were not limited to planned comparisons. */
export function scopeNote(relation: TriageRelation): string {
  return relation.scope_checked ? ""
    : " Suggested under the earlier triage contract, whose replies were not limited to the comparisons a request planned.";
}

/** What a relation's feed dates show, always as feed metadata. */
export function feedDateNote(relation: TriageRelation): string {
  const { distinct_utc_dates: dates, without_timestamp: missing } = relation.feed_dates;
  const parts = [dates.length === 0 ? "No feed dates" : `Feed date${dates.length === 1 ? "" : "s"} ${dates.join(", ")}`];
  if (dates.length > 1) parts.push("the dates differ");
  if (missing > 0) parts.push(`${missing} ${missing === 1 ? "entry has" : "entries have"} no feed timestamp`);
  return `${parts.join("; ")}. Feed timestamps are feed metadata, not verified publication times.`;
}

/** The inbox entry an Analyze button would use: the entry as it is now, current or retained, if it is still held. */
export function currentEntry(input: TriageInput, current: InboxItem[]): InboxItem | null {
  const item = current.find((candidate) => candidate.id === input.id);
  return item && officialLink(item.link) ? item : null;
}

const OUTCOME_LABEL: Record<Outcome, string> = {
  triaged: "Accepted", not_accepted: "Not accepted", provider_error: "Provider error", no_reply: "No reply",
  credential_echo: "Discarded",
};

/** A short status for one attempt of the planned request. */
export function attemptLabel(attempt: TriageAttempt): string {
  if (attempt.state === "none") return "Not requested";
  if (attempt.state === "incomplete") return attempt.sent ? "Sent, no response recorded" : "Reserved, not sent";
  if (attempt.state === "invalid") return "Recorded attempt does not verify";
  return OUTCOME_LABEL[attempt.outcome];
}

/** A short status from a saved-request listing row. */
export function listedLabel(attempt: { state: string; outcome: string | null } | undefined): string {
  if (!attempt) return "unknown";
  if (attempt.state === "complete" && attempt.outcome && attempt.outcome in OUTCOME_LABEL) {
    return OUTCOME_LABEL[attempt.outcome as Outcome].toLowerCase();
  }
  return ({ none: "not requested", incomplete: "incomplete", invalid: "does not verify" } as Record<string, string>)[attempt.state]
    ?? "unknown";
}

/** What one entry's status says, plainly. */
export function statusLabel(row: SelectionRow): string {
  switch (row.status) {
    case "reuse": return "Saved result reused";
    case "earlier_version": return "Saved result from an earlier version";
    case "unresolved": return "Earlier attempt unresolved";
    default: return row.reprocess ? "Requested again by you" : "Needs a result";
  }
}
