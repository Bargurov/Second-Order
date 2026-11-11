// Private market context for selected macro events: the server's saved events and verified retrievals of the Board's
// daily H.15 2-year and 10-year yields (committed downloads, earlier two-series retrievals, and kept release packages
// that a local validation accepted). Reads only read; the two writes (confirming an Inbox entry's context date, and
// approving one planned download of the release package) are explicit actions from this page, and the server
// re-checks both.
import type { Loaded } from "./api";
import type { FeedTimestamp } from "./inbox";
import { formatContextDate, type ContextDay } from "./marketContext.ts";

export const EVENT_CONTEXT_PAGE_VERSION = "event-market-context-page-0.2";
export const EVENT_CONTEXT_LIST_VERSION = "event-market-context-list-0.2";
export const EVENT_CONTEXT_VIEW_VERSION = "event-market-context-view-0.1";
export const RETRIEVAL_PLAN_VERSION = "market-retrieval-plan-0.2";
export const RETRIEVAL_RESULT_VERSION = "market-retrieval-result-0.2";
/** The operator's local command that validates a kept package; it fetches nothing. */
export const VALIDATE_COMMAND = "python -m second_order market-packages validate";
export const CONVENTION_ID = "new-york-calendar-date-1";
/** The Inbox sources this first slice supports; energy and trade entries are outside it. */
export const SUPPORTED_SOURCES: ReadonlySet<string> = new Set(["fed-monetary", "bls-empsit", "bls-cpi"]);
export const OUTSIDE_SHORT = "Market context is not offered for energy or trade entries in this first slice: daily " +
  "Treasury yields are paired only with Federal Reserve monetary-policy and BLS employment and inflation releases.";
const HEADER = "X-Second-Order-Context";
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type EventKind = "inbox" | "capture";

export interface Convention { id: string; statement: string }

export interface EventContext {
  date: string;
  basis: "confirmed" | "supplied";
  convention: Convention;
  window: { start: string; end: string; days_before: number; days_after: number };
  version?: number;
  confirmed_at?: string;
  suggested?: string | null;
}

export interface EventDefinition {
  key: string;
  kind: EventKind;
  id: string;
  supported: boolean;
  family: string | null;
  family_label: string | null;
  outside: string | null;
  title: string | null;
  link: string | null;
  publisher: string | null;
  timestamp: FeedTimestamp | null;
  supplied: { published_at_as_supplied: string; published_at: string; new_york_time: string; new_york_offset: string;
              note: string } | null;
  suggestion: { date: string; new_york_time: string; utc_offset: string; feed_raw: string | null; basis: string } | null;
  suggestion_problem: string | null;
  in_inbox: boolean | null;
  confirmations: { version: number; context_date: string; confirmed_at: string }[];
  context: EventContext | null;
  /** A date confirmed for another version of the entry: shown, never carried over to this version. */
  confirmation_stale: { version: number; context_date: string; title: string } | null;
  problem: string | null;
}

export interface Provenance {
  id: string;
  origin: "private" | "bundle" | "package";
  origin_label: string;
  file: string;
  url: string;
  requested_start: string;
  requested_end: string;
  returned_first: string;
  returned_last: string;
  rows: number;
  requested_at: string;
  received_at: string;
  http_status: number;
  content_type: string;
  response_date: string;
  bytes: number;
  sha256: string;
  client?: { user_agent: string; transport: string };
  run?: number;
  case?: string;
  method?: string;
  tool?: string;
  // A kept release package only:
  package_id?: string;
  release_prepared?: string | null;
  parser_version?: string;
  validated_at?: string | null;
  acquisition_method?: string;
}

/** A kept H.15 release package: used only when a validation for the current parser version accepted it. */
export interface KeptPackage {
  id: string;
  package_id: string;
  status: "accepted" | "refused" | "acquired_unvalidated";
  detail: string | null;
  url: string;
  requested_at: string;
  bytes: number;
  sha256: string;
  last_modified: string | null;
  acquisition_method: string;
  client: { user_agent: string; transport: string };
  parser_version: string;
  validated_at: string | null;
  release_prepared: string | null;
  coverage: { first: string; last: string } | null;
  other_validations: string[];
  marker_findings: number | null;
}

export interface Change {
  series: string;
  short_label: string;
  horizon: 1 | 5;
  from: string | null;
  to: string | null;
  from_raw: string | null;
  to_raw: string | null;
  change_bp: string | null;
  unavailable: string | null;
}

export interface EventView {
  view_version: string;
  key: string;
  as_of: string;
  context: EventContext;
  publication: { new_york_date: string };
  window: { start: string; end: string; days_before: number; days_after: number };
  series: { id: string; label: string; short_label: string; description: string; unique_identifier: string;
            units_label: string; unit: string; fred_equivalent: string; fred_page: string }[];
  sessions: string[];
  days: (ContextDay & { observations: Record<string, ContextDay["observations"][string] & { retrievals: string[] }> })[];
  endpoints: { rule: { id: string; statement: string }; base: string | null; after_1: string | null;
               after_5: string | null; changes: Change[] };
  conflicts: { date: string; series: string; versions: { raw: string | null; retrievals: string[] }[] }[];
  status_counts: Record<string, number>;
  complete: boolean;
  retrievals: Provenance[];
  store_problems: StoreProblem[];
  calendar: { calendar: string; library: string; library_version: string; exceptions_version: string };
  source: { publisher: string; release: string; release_url: string; data_download_url: string; help_url: string;
            crosswalk_url: string; underlying_source: string; terms: { url: string; statement: string };
            vintage_note: string };
  limits: string[];
}

export interface StoreProblem { retrieval: string; problem: string }

export interface PlanSource {
  id: string;
  label: string;
  publisher: string;
  series: { id: string; label: string }[];
  address: string;
  download: string;
  key: string;
  charge: string;
  terms: { url: string; statement: string };
  availability: { checked_on: string; statement: string; urls: string[] };
  known_behaviour: string;
  vintage_note: string;
}

export interface Plan {
  plan_version: string;
  plan_sha256: string;
  as_of: string;
  source: PlanSource;
  events: { key: string; title: string | null; context_date: string; start: string; end: string }[];
  needed_sessions: number;
  held_sessions: number;
  missing_sessions: string[];
  missing_ranges: { start: string; end: string; sessions: number }[];
  future_sessions: string[];
  reuse: { retrieval: string; origin_label: string; requested_at: string; sessions: number }[];
  requests: 0 | 1;
  request: { url: string; download: "full_release_package"; missing_sessions: number; missing_from: string;
             missing_to: string } | null;
  next_attempt: number;
  attempts?: Attempt[];
  retrieval?: RetrievalStatus;
  packages_not_used?: KeptPackage[];
}

export type AttemptOutcome = "saved" | "retained_not_accepted" | "refused_reply" | "no_reply" | "not_saved";

/** One attempt: an earlier two-series CSV request (a date range) or a release-package download. */
export interface Attempt {
  plan_sha256: string;
  number: number;
  started: { attempt_version: string; events: string[]; url: string; started_at: string; client: { transport: string };
             requested_start?: string; requested_end?: string; download?: "full_release_package" } | null;
  outcome: { outcome: AttemptOutcome; detail: string | null; http_status: number | null; finished_at: string | null;
             retrieval_id?: string | null; package_id?: string | null } | null;
  problem: string | null;
}

export interface RetrievalStatus { enabled: boolean; detail: string }

export interface EventPage {
  page_version: string;
  as_of: string;
  event: EventDefinition;
  view: EventView | null;
  plan: Plan | null;
  others: { key: string; title: string | null; family_label: string | null; context_date: string;
            missing_sessions: number }[];
  attempts: Attempt[];
  retrieval: RetrievalStatus;
  store_problems: StoreProblem[];
  packages_not_used: KeptPackage[];
  convention: Convention;
  rule: { id: string; statement: string };
}

export interface ListedEvent {
  key: string;
  kind: EventKind;
  id: string | null;
  title: string | null;
  link: string | null;
  family_label: string | null;
  supported: boolean;
  outside: string | null;
  problem: string | null;
  context: EventContext | null;
  complete?: boolean;
  missing_sessions?: number;
  future_sessions?: number;
  conflicts?: number;
  changes?: Pick<Change, "series" | "short_label" | "horizon" | "change_bp" | "unavailable">[];
}

export interface ContextListing {
  list_version: string;
  as_of: string;
  retrieval: RetrievalStatus;
  events: ListedEvent[];
  outside: ListedEvent[];
  retrievals: Provenance[];
  packages: KeptPackage[];
  store_problems: StoreProblem[];
  attempts: Attempt[];
  source: PlanSource;
  outside_note: string;
}

export interface RetrievalResult {
  result_version: string;
  plan_sha256: string;
  attempt: number;
  outcome: AttemptOutcome;
  detail: string | null;
  package_id: string | null;
  validation: "accepted" | "refused" | null;
  provider_called: boolean;
  retries: 0;
}

function detail(body: unknown): string | null {
  const value = (body as { detail?: unknown } | null)?.detail;
  return typeof value === "string" ? value : null;
}

/** A read of one versioned reply. A refusal keeps the server's explanation, because the page shows it. */
async function read<T>(path: string, signal: AbortSignal | undefined, field: string, version: string): Promise<Loaded<T>> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  const message = detail(body) ?? `Unexpected response (${response.status}).`;
  if (response.status === 404) return { state: "missing", message };
  if (!response.ok) return { state: "error", message };
  if ((body as Record<string, unknown> | null)?.[field] !== version) {
    return { state: "error", message: "The server's reply could not be verified as this client's version." };
  }
  return { state: "ready", data: body as T };
}

export const eventHref = (kind: EventKind, id: string) => `/market-context/${kind}/${encodeURIComponent(id)}`;

export const fetchEventPage = (kind: EventKind, id: string, signal?: AbortSignal) =>
  read<EventPage>(`/api/market-context/${kind}/${encodeURIComponent(id)}`, signal, "page_version",
                  EVENT_CONTEXT_PAGE_VERSION);

export const fetchContextListing = (signal?: AbortSignal) =>
  read<ContextListing>("/api/market-context", signal, "list_version", EVENT_CONTEXT_LIST_VERSION);

/** The plan for several saved events at once: a read, nothing is requested. */
export const fetchPlan = (keys: string[], signal?: AbortSignal) =>
  read<Plan>(`/api/market-context/plan?${keys.map((key) => `event=${encodeURIComponent(key)}`).join("&")}`, signal,
             "plan_version", RETRIEVAL_PLAN_VERSION);

export type Action<T> = { state: "done"; value: T } | { state: "refused" | "unconfirmed"; message: string };

async function post<T>(path: string, body: object, check: (value: unknown) => boolean): Promise<Action<T>> {
  let response: Response;
  try {
    response = await fetch(path, { method: "POST", body: JSON.stringify(body),
                                   headers: { "Content-Type": "application/json", Accept: "application/json", [HEADER]: "1" } });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Nothing was retried; read the " +
                                            "event again to see what was recorded." };
  }
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = detail(value) ?? `Unexpected response (${response.status}).`;
    return { state: response.status >= 500 ? "unconfirmed" : "refused", message };
  }
  if (!check(value)) return { state: "unconfirmed", message: "The server replied, but its reply could not be verified." };
  return { state: "done", value: value as T };
}

export const confirmContextDate = (itemId: string, contextDate: string, version: number) =>
  post<{ saved_now: boolean; version: number }>(`/api/market-context/inbox/${encodeURIComponent(itemId)}/confirm`,
    { context_date: contextDate, convention: CONVENTION_ID, version },
    (value) => typeof (value as { saved_now?: unknown } | null)?.saved_now === "boolean");

/** Approve one planned download: the plan's SHA-256, its events and the attempt number the page showed. */
export const approveRetrieval = (plan: Plan) =>
  post<RetrievalResult>("/api/market-context/retrievals",
    { plan_sha256: plan.plan_sha256, events: plan.events.map((event) => event.key), attempt: plan.next_attempt },
    (value) => (value as { result_version?: unknown } | null)?.result_version === RETRIEVAL_RESULT_VERSION);

// ---------------------------------------------------------------- words

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/** "+12 bp", "−4 bp", "0 bp": the server's exact difference, with a typographic minus. */
export function formatBp(change: string | null): string {
  if (change === null) return "Unavailable";
  return `${change.startsWith("-") ? `−${change.slice(1)}` : change} bp`;
}

export const HORIZON_LABEL: Record<number, string> = { 1: "1st session after", 5: "5th session after" };

/** The descriptive-change table: one row per series and horizon, with its endpoints or why it is unavailable. */
export function changeRows(view: EventView) {
  return view.endpoints.changes.map((change) => ({
    key: `${change.series}-${change.horizon}`,
    series: change.short_label,
    horizon: HORIZON_LABEL[change.horizon],
    from: change.from ? `${formatContextDate(change.from)}${change.from_raw ? `: ${change.from_raw}%` : ""}` : "—",
    to: change.to ? `${formatContextDate(change.to)}${change.to_raw ? `: ${change.to_raw}%` : ""}` : "Outside the window",
    change: formatBp(change.change_bp),
    available: change.change_bp !== null,
    unavailable: change.unavailable,
  }));
}

const PACKAGE_STATUS: Record<KeptPackage["status"], string> = {
  accepted: "validated and used",
  acquired_unvalidated: "acquired, not yet validated, so not used",
  refused: "kept, but its validation refused its data, so not used",
};

/** A kept package's status in words, with the reason for a refusal. */
export function packageStatus(item: KeptPackage): string {
  return `${PACKAGE_STATUS[item.status] ?? item.status}${item.status === "refused" && item.detail ? `: ${item.detail}` : ""}`;
}

/** What the plan will and will not do, in sentences the page shows before any approval. */
export function planSentences(plan: Plan): string[] {
  const sentences = [`${plan.events.length === 1 ? "This event needs" : "These events need"} ${plural(
    plan.needed_sessions, "expected session")} before today (${formatContextDate(plan.as_of)}, New York); ${
    plan.held_sessions} ${plan.held_sessions === 1 ? "is" : "are"} already held locally.`];
  if (plan.reuse.length) {
    sentences.push(`Reused from ${plural(plan.reuse.length, "local retrieval")}, which may overlap: ${plan.reuse.map(
      (item) => `${item.retrieval} (${plural(item.sessions, "session")}, requested ${item.requested_at})`).join("; ")}.`);
  }
  if (plan.future_sessions.length) {
    sentences.push(`${plural(plan.future_sessions.length, "session")} on or after today cannot be requested yet ` +
      "and stay future.");
  }
  if (plan.request) {
    const { request } = plan;
    sentences.push(`Missing: ${plural(request.missing_sessions, "session")} (${plan.missing_ranges.map((range) =>
      range.start === range.end ? formatContextDate(range.start) : `${formatContextDate(range.start)} to ${
        formatContextDate(range.end)}`).join("; ")}).`);
    sentences.push("Planned: exactly 1 request, which downloads the Board's complete H.15 release package: every " +
      "series of the release over its full history, not a two-series or date-bounded download. Only the 2-year and " +
      "10-year series are read from it, and it is kept privately so that later selections reuse it.");
  } else {
    sentences.push("Planned: no request. Everything these events need before today is already held.");
  }
  const unused = plan.packages_not_used ?? [];
  if (unused.length) {
    sentences.push(`${plural(unused.length, "kept release package")} ${unused.length === 1 ? "is" : "are"} not used: ${
      unused.map((item) => `${item.package_id} (${packageStatus(item)})`).join("; ")}. A package not yet validated can ` +
      `be validated locally with ${VALIDATE_COMMAND}, which fetches nothing, before approving another download.`);
  }
  return sentences;
}

const OUTCOME_WORDS: Record<string, string> = {
  saved: "saved", retained_not_accepted: "the package was kept, but its data was not accepted, so it is not used",
  refused_reply: "the reply was not kept", no_reply: "no reply was received", not_saved: "the reply could not be kept",
};

/** One attempt in words: when it started, what it requested, and what became of it (or that nothing was recorded). */
export function attemptLine(attempt: Attempt): string {
  const started = attempt.started;
  const what = !started ? "" : started.requested_start && started.requested_end
    ? `, the two-series download of ${formatContextDate(started.requested_start)} to ${formatContextDate(started.requested_end)}`
    : ", the full H.15 release package";
  const head = `Attempt ${attempt.number}${started ? `, started ${started.started_at}${what}` : ""}`;
  if (attempt.problem) return `${head}: ${attempt.problem}.`;
  if (!attempt.outcome) return `${head}: no outcome was recorded. It may still be running, or it stopped before its ` +
    "outcome was saved; nothing is retried automatically.";
  const status = attempt.outcome.http_status ? ` (HTTP ${attempt.outcome.http_status})` : "";
  return `${head}: ${OUTCOME_WORDS[attempt.outcome.outcome] ?? attempt.outcome.outcome}${status}. ${
    attempt.outcome.detail ?? ""}`.trim();
}

/** What the page says after an approval, read from the recorded outcome, never assumed. */
export function resultMessage(result: RetrievalResult): { text: string; tone: "done" | "error" } {
  return result.outcome === "saved"
    ? { text: `Attempt ${result.attempt}: ${result.detail ?? "the package was kept and accepted."}`, tone: "done" }
    : { text: `Attempt ${result.attempt}: ${OUTCOME_WORDS[result.outcome] ?? result.outcome}. ${result.detail ?? ""} ` +
              "Nothing was retried automatically.", tone: "error" };
}

/** A capture's stated time, or an Inbox entry's feed timestamp, as the page shows it. */
export function timeNote(event: EventDefinition): string {
  if (event.supplied) {
    return `Publication time supplied with the saved event: ${event.supplied.published_at_as_supplied} ` +
      `(${event.supplied.new_york_time} New York time, UTC${event.supplied.new_york_offset}). ${event.supplied.note}`;
  }
  if (event.timestamp) {  // With a suggestion, its own basis says this once; without one, it is said here.
    return `Feed timestamp (${event.timestamp.origin}): ${event.timestamp.raw ?? "none"}.` + (event.suggestion ? ""
      : " A feed timestamp is metadata, not a verified publication instant.");
  }
  return "";
}

/** The status line of a listed event. */
export function listedStatus(event: ListedEvent): string {
  if (event.problem) return event.problem;
  if (!event.context) return "No context date confirmed yet.";
  if (event.complete) return "Every expected session in the window is held locally.";
  const parts = [];
  if (event.missing_sessions) parts.push(`${plural(event.missing_sessions, "session")} not held locally`);
  if (event.future_sessions) parts.push(`${plural(event.future_sessions, "session")} on or after today`);
  if (event.conflicts) parts.push(`${plural(event.conflicts, "value")} where retrieval versions disagree`);
  return parts.length ? `Partial window: ${parts.join("; ")}.` : "Partial window.";
}
