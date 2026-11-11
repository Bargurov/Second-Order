// Evidence-first research analysis (/api/research-analyses): a second analysis mode for a saved event, with its own
// request, result and review contracts. Replies are read fail-closed: a result is shown only when it belongs to the
// request shown, its outcome agrees with what it carries, its statements are numbered in order, its interpretation
// names only statements that exist, and every quoted passage is found again here, at its recorded place, in the
// captured text the saved request carries. A prepared request is never shown as an analysis. Nothing here requests
// anything outside this server, and nothing is sent, prepared or saved without an explicit action.
export { researchHref } from "./eventOverview.ts";

export const RESEARCH_FLOW_VERSION = "research-analysis-flow-0.1";
export const RESEARCH_REQUEST_VERSION = "research-request-0.1";
export const RESEARCH_RESULT_VERSION = "research-result-view-0.1";
export const RESEARCH_REVIEW_VERSION = "research-review-0.1";
/** A user account's request (one per capture, prompt version and Effort) and that account's own reviews of it. */
export const RESEARCH_USER_REQUEST_VERSION = "research-request-0.2";
export const RESEARCH_USER_REVIEW_VERSION = "research-review-0.2";
export const BASES = ["action", "data", "assessment", "forecast"] as const;
export const OUTCOMES = ["analysis", "no_additional_finding", "declined", "incomplete", "invalid",
  "technical_failure"] as const;
export const ATTEMPT_STATES = ["none", "incomplete", "recorded", "invalid"] as const;
export const REVIEW_STATUSES = ["needs_revision", "human_reviewed"] as const;
export const MOCK_OUTCOMES = ["analysis", "no_additional_finding", "declined"] as const;
export const MAX_NOTES = 20_000;
const REQUEST_ID = /^(\d{8}T\d{12}Z-[0-9a-f]{12})\.(research-prompt-[1-9][0-9]{0,3})(?:\.(low|medium|high|xhigh|max))?$/;
const USER_ID = /^u-[0-9a-f]{16}$/;

/** Whether a request was prepared for a user account: those run and are reviewed only through that account. */
export const isUserRequest = (requestId: string) => REQUEST_ID.exec(requestId)?.[3] !== undefined;
/** The Effort a user's request was prepared at, from its ID. */
export const requestEffort = (requestId: string) => REQUEST_ID.exec(requestId)?.[3] ?? null;
const SHA = /^[0-9a-f]{64}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type Basis = (typeof BASES)[number];
export type Outcome = (typeof OUTCOMES)[number];
export type AttemptStateName = (typeof ATTEMPT_STATES)[number];
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];
export type MockOutcome = (typeof MOCK_OUTCOMES)[number];

export interface LocatedQuote {
  text: string; match: "exact" | "normalized"; start: number; end: number; paragraphs: number[];
  source_passage: string; occurrences: number;
  /** A Go deeper source's quote only (deeper-evidence-0.1): the report it is from, its publisher and the part. */
  evidence?: { report: number; publisher: string; part: "headline" | "excerpt" | "text" };
}
export interface EstablishedItem { number: number; statement: string; basis: Basis; quotes: LocatedQuote[] }
export interface Analysis {
  established: EstablishedItem[];
  interpretation: { kind: "finding" | "no_additional_finding"; text: string; based_on: number[] };
  assumptions: string[];
  competing_explanations: { explanation: string; would_distinguish: string }[];
  missing_information: string[];
  tests: { check: string; counts_against_if: string }[];
}
export interface ResultView {
  view_version: string; request_id: string; capture_id: string; prompt_version: string; mode: "mock" | "paid";
  synthetic: boolean; outcome: Outcome; recorded_outcome: string; outcome_note: string; problem: string | null;
  model_text: string | null; analysis: Analysis | null; baseline: { state: "not_supplied"; note: string };
  retrospective: string; frozen: false; evaluated: false;
  provenance: {
    request_sha256: string; response_sha256: string | null; response_id: string | null; model: string | null;
    stop_reason: string | null; usage: { input_tokens?: number; output_tokens?: number } | null;
    sent_at: string | null; received_at: string | null; http_status: number | null;
    provider_request_id: string | null; planning_estimate_usd: number | null; usage_cost_usd: number | null;
    usage_cost_basis: string | null;
  };
}
export interface Attempt {
  request_id: string; state: AttemptStateName; mode: "mock" | "paid" | null; sent: boolean; sent_at: string | null;
  files: string[]; detail: string; provider_called: false;
}
export interface ReviewRecord {
  record_version: string; request_id: string; sequence: number; parent_review_id: string | null; saved_at: string;
  attributed_to: string; status: ReviewStatus | null; notes: string; review_id: string;
  binding: { result_view_sha256: string; request_sha256: string; response_sha256: string | null;
    result_view_version: string; outcome: Outcome; mode: "mock" | "paid" };
}
export interface CostEstimate {
  mock_run_usd: number; estimated_real_run_if_output_reaches_max_usd: number; input_tokens_assumed: number;
  output_tokens_at_max: number; assumptions: string[]; caveat: string;
  prices: { input_usd_per_mtok: number; output_usd_per_mtok: number; read_on: string; source: string };
}
export interface Origin {
  state: "none" | "verified"; note?: string; item_id?: string; version?: number; versions?: number;
  content_sha256?: string; link_sha256?: string; title?: string; recorded_at?: string;
}
export interface ResearchRequestView {
  flow_version: string; request_version: string; request_id: string; capture_id: string; status: string;
  prompt_version: string; model: string; effort: string; max_tokens: number;
  /** research-prompt-1's strict tool; null since research-prompt-2, whose reply is the JSON output format. */
  tool: string | null; reply_format?: string; request_sha256: string;
  request_bytes: number; request: Record<string, unknown>; prepared_at: string;
  event: { headline: string; source_url: string; published_at: string };
  capture: { capture_id: string; request_sha256: string; request_prompt_version: string; source_sha256: string;
    source_bytes: number; captured_at: string };
  origin: Origin; baseline: { state: "not_supplied"; note: string }; retrospective: string; not_an_analysis: string;
  current_code: { comparison: string; detail: string }; cost_estimate: CostEstimate; provider_called: false;
  attempt: Attempt; result: ResultView | null; result_view_sha256: string | null; result_problem: string | null;
  reviews: { state: "verified" | "invalid"; records: ReviewRecord[]; problem: string | null };
  modes: { mock: { enabled: boolean; detail: string }; paid: { enabled: boolean; detail: string } };
  created?: boolean;
}
export interface ListedRequest {
  request_id: string; state: "verified" | "refused"; problem?: string; prompt_version?: string; prepared_at?: string;
  request_sha256?: string; attempt?: { state: AttemptStateName }; result?: { outcome: Outcome } | null;
}
export interface ResearchListing { flow_version: string; capture_id: string; provider_called: false;
  requests: ListedRequest[] }

// ---------------------------------------------------------------- words

export const BASIS_LABEL: Record<Basis, string> = {
  action: "Action the publisher reports",
  data: "Data the publisher reports",
  assessment: "The publisher's assessment: its view, attributed",
  forecast: "The publisher's forecast or expectation: attributed, not an outcome",
};
export const OUTCOME_LABEL: Record<Outcome, string> = {
  analysis: "Analysis recorded",
  no_additional_finding: "No additional finding",
  declined: "No analysis: declined",
  incomplete: "No analysis: the response stopped early",
  invalid: "Refused: the response broke the research contract",
  technical_failure: "No analysis: technical failure",
};
export const MODE_LABEL = { mock: "Local mock · synthetic, $0, no provider contacted", paid: "Model response · paid" };
export const STATUS_LABEL: Record<ReviewStatus, string> = { needs_revision: "Needs revision",
  human_reviewed: "Human-reviewed" };
export const NO_STATUS_LABEL = "No judgment recorded";
export const STATUS_NOTE = "These labels record your judgment. They do not verify the analysis, freeze it or " +
  "evaluate it.";
export const INTERPRETATION_LABEL = "The model's reading, not the publisher's words";

export const statusLabel = (status: ReviewStatus | null) => (status ? STATUS_LABEL[status] : NO_STATUS_LABEL);

/** "Paragraph 3, characters 72–129", with how the passage was matched. */
export function locator(quote: LocatedQuote): string {
  const where = quote.paragraphs.length === 1 ? `Paragraph ${quote.paragraphs[0]}`
    : `Paragraphs ${quote.paragraphs[0]}–${quote.paragraphs.at(-1)}`;
  const match = quote.match === "exact" ? "exact match"
    : "matched after making quotation marks, dashes and spaces plain; the source's own wording is shown";
  const more = quote.occurrences > 1 ? `; the passage occurs ${quote.occurrences} times` +
    `${quote.evidence ? " in the publishers' passages" : ""}, the first is shown` : "";
  const from = quote.evidence ? ` · report ${quote.evidence.report} (${quote.evidence.publisher}), its ` +
    `${quote.evidence.part === "text" ? "publication text" : quote.evidence.part === "excerpt" ? "feed excerpt" :
      "headline"}` : "";
  return `${where}, characters ${quote.start}–${quote.end}${from} · ${match}${more}`;
}

// ---------------------------------------------------------------- reading

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null &&
  !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;
const nullable = (value: unknown, check: (item: unknown) => boolean) => value === null || check(value);
const oneOf = <T extends string>(values: readonly T[], value: unknown): value is T =>
  typeof value === "string" && (values as readonly string[]).includes(value);

/** The captured text the saved request carries, between its source tags; null when it does not have that shape. */
export function capturedText(request: Record<string, unknown>): string | null {
  const messages = request.messages;
  if (!Array.isArray(messages) || messages.length !== 1) return null;
  const content: unknown = (messages[0] as { content?: unknown }).content;
  if (typeof content !== "string") return null;
  const open = "\n\n<source_text>\n";
  const start = content.indexOf(open);
  if (start < 0 || content.indexOf(open, start + 1) >= 0 || !content.endsWith("\n</source_text>")) return null;
  return content.slice(start + open.length, -"\n</source_text>".length);
}

/** A slice by code points, as the server counts characters. */
export const codePoints = (text: string, start: number, end: number) => Array.from(text).slice(start, end).join("");

function analysisProblem(analysis: unknown, outcome: Outcome, source: string): string | null {
  if (!object(analysis) || !Array.isArray(analysis.established) || !object(analysis.interpretation)) {
    return "The analysis does not have its sections.";
  }
  const established = analysis.established as unknown[];
  if (established.length === 0) return "The analysis has no established statement.";
  for (const [index, item] of established.entries()) {
    if (!object(item) || item.number !== index + 1 || !isText(item.statement) || !oneOf(BASES, item.basis) ||
        !Array.isArray(item.quotes) || item.quotes.length === 0) {
      return `Established statement ${index + 1} is not numbered in order or lacks its quotes.`;
    }
    for (const quote of item.quotes as unknown[]) {
      if (!object(quote) || !isText(quote.text) || !isText(quote.source_passage) || !count(quote.start) ||
          !count(quote.end) || (quote.end as number) <= (quote.start as number) || !count(quote.occurrences) ||
          !Array.isArray(quote.paragraphs) || quote.paragraphs.length === 0 || !quote.paragraphs.every(count) ||
          !oneOf(["exact", "normalized"] as const, quote.match)) {
        return `A quote of statement ${index + 1} lacks its locator.`;
      }
      if ("evidence" in quote && (!object(quote.evidence) || !count(quote.evidence.report) ||
          (quote.evidence.report as number) < 1 || !isText(quote.evidence.publisher) ||
          !oneOf(["headline", "excerpt", "text"] as const, quote.evidence.part))) {
        return `A quote of statement ${index + 1} has an unreadable attribution to its report.`;
      }
      if (codePoints(source, quote.start as number, quote.end as number) !== quote.source_passage ||
          (quote.match === "exact" && quote.text !== quote.source_passage)) {
        return `A quote of statement ${index + 1} is not at its recorded place in the captured text.`;
      }
    }
  }
  const reading = analysis.interpretation;
  const basedOn = reading.based_on;
  const kind = outcome === "analysis" ? "finding" : "no_additional_finding";
  if (reading.kind !== kind || !isText(reading.text) || !Array.isArray(basedOn) || !basedOn.every(count) ||
      new Set(basedOn).size !== basedOn.length ||
      basedOn.some((number) => (number as number) < 1 || (number as number) > established.length) ||
      (kind === "finding" && basedOn.length === 0)) {
    return "The interpretation does not agree with the outcome or names statements that do not exist.";
  }
  const pairs = (value: unknown, keys: string[]) => Array.isArray(value) &&
    value.every((item) => object(item) && keys.every((key) => isText(item[key])));
  if (!texts(analysis.assumptions) || !texts(analysis.missing_information) ||
      !pairs(analysis.competing_explanations, ["explanation", "would_distinguish"]) ||
      !pairs(analysis.tests, ["check", "counts_against_if"])) {
    return "The analysis's assumptions, competing explanations, missing information or tests are malformed.";
  }
  return null;
}

function resultProblem(result: unknown, view: Record<string, unknown>, source: string): string | null {
  if (!object(result) || result.view_version !== RESEARCH_RESULT_VERSION) return "The result is not this client's version.";
  const provenance = result.provenance;
  if (result.request_id !== view.request_id || result.capture_id !== view.capture_id || !object(provenance) ||
      provenance.request_sha256 !== view.request_sha256) {
    return "The result names another request than the one shown.";
  }
  if (!oneOf(["mock", "paid"] as const, result.mode) || result.synthetic !== (result.mode === "mock") ||
      !oneOf(OUTCOMES, result.outcome) || !isText(result.recorded_outcome) || !isText(result.outcome_note) ||
      result.frozen !== false || result.evaluated !== false || !object(result.baseline) ||
      result.baseline.state !== "not_supplied" || !isText(result.retrospective) ||
      !nullable(result.problem, isText) || !nullable(result.model_text, isText) ||
      !nullable(provenance.response_sha256, (value) => SHA.test(String(value)))) {
    return "The result's outcome, mode or provenance could not be verified.";
  }
  const carries = result.outcome === "analysis" || result.outcome === "no_additional_finding";
  if (carries !== (result.analysis !== null)) return "The result's outcome does not agree with what it carries.";
  if (!carries && result.problem === null && result.model_text === null) {
    return "A result without an analysis must say why.";
  }
  return carries ? analysisProblem(result.analysis, result.outcome as Outcome, source) : null;
}

function reviewsProblem(reviews: unknown, requestId: string): string | null {
  const version = isUserRequest(requestId) ? RESEARCH_USER_REVIEW_VERSION : RESEARCH_REVIEW_VERSION;
  if (!object(reviews) || !oneOf(["verified", "invalid"] as const, reviews.state) || !Array.isArray(reviews.records)) {
    return "The review versions could not be read.";
  }
  let parent: string | null = null;
  for (const [index, record] of (reviews.records as unknown[]).entries()) {
    if (!object(record) || record.record_version !== version || record.request_id !== requestId ||
        record.sequence !== index + 1 || record.parent_review_id !== parent || !SHA.test(String(record.review_id)) ||
        !nullable(record.status, (value) => oneOf(REVIEW_STATUSES, value)) || typeof record.notes !== "string" ||
        !object(record.binding) || !SHA.test(String(record.binding.result_view_sha256))) {
      return `Review version ${index + 1} does not follow the one before it.`;
    }
    parent = record.review_id as string;
  }
  return null;
}

/** A research request view, verified before anything in it is shown. */
export function readResearch(body: unknown): { view: ResearchRequestView } | { problem: string } {
  const user = isUserRequest(String(object(body) ? body.request_id : ""));
  if (!object(body) || body.flow_version !== RESEARCH_FLOW_VERSION ||
      body.request_version !== (user ? RESEARCH_USER_REQUEST_VERSION : RESEARCH_REQUEST_VERSION) ||
      (user ? !USER_ID.test(String(body.prepared_by)) || body.effort !== requestEffort(String(body.request_id))
        : body.prepared_by !== undefined && body.prepared_by !== null)) {
    return { problem: "The research request could not be verified as this client's version." };
  }
  const id = REQUEST_ID.exec(String(body.request_id));
  const attempt = body.attempt;
  const estimate = body.cost_estimate;
  const modes = body.modes;
  if (!id || id[1] !== body.capture_id || id[2] !== body.prompt_version || !SHA.test(String(body.request_sha256)) ||
      body.provider_called !== false || !isText(body.model) || !isText(body.effort) || !count(body.max_tokens) ||
      !count(body.request_bytes) || !object(body.request) || !isText(body.not_an_analysis) ||
      !object(body.capture) || body.capture.capture_id !== body.capture_id || !object(body.origin) ||
      !oneOf(["none", "verified"] as const, body.origin.state) || !object(body.event) ||
      !object(attempt) || attempt.request_id !== body.request_id || !oneOf(ATTEMPT_STATES, attempt.state) ||
      !object(estimate) || typeof estimate.estimated_real_run_if_output_reaches_max_usd !== "number" ||
      !texts(estimate.assumptions) || !isText(estimate.caveat) || !object(modes) || !object(modes.mock) ||
      !object(modes.paid) || typeof modes.mock.enabled !== "boolean" || typeof modes.paid.enabled !== "boolean") {
    return { problem: "The research request's identity, cost decision or attempt state could not be verified." };
  }
  const source = capturedText(body.request);
  if (source === null) return { problem: "The saved request does not carry the captured text in its expected frame." };
  if ((body.result === null) !== (attempt.state !== "recorded") ||
      (body.result === null) !== (body.result_view_sha256 === null) ||
      (body.result !== null && !SHA.test(String(body.result_view_sha256)))) {
    return { problem: "The attempt state and the result disagree." };
  }
  if (body.result !== null) {
    const problem = resultProblem(body.result, body, source);
    if (problem) return { problem };
  }
  const reviews = reviewsProblem(body.reviews, body.request_id as string);
  if (reviews) return { problem: reviews };
  return { view: body as unknown as ResearchRequestView };
}

export function readListing(body: unknown, captureId: string): { listing: ResearchListing } | { problem: string } {
  if (!object(body) || body.flow_version !== RESEARCH_FLOW_VERSION || body.capture_id !== captureId ||
      body.provider_called !== false || !Array.isArray(body.requests) ||
      !body.requests.every((row) => object(row) && REQUEST_ID.exec(String(row.request_id))?.[1] === captureId &&
        oneOf(["verified", "refused"] as const, row.state))) {
    return { problem: "The research requests of this saved event could not be verified." };
  }
  return { listing: body as unknown as ResearchListing };
}

/** The captured text in pieces, each marked with the established statements whose quotes cover it. */
export function markedSource(source: string, analysis: Analysis | null): { text: string; statements: number[] }[] {
  const points = Array.from(source);
  const cuts = new Set([0, points.length]);
  const spans = (analysis?.established ?? []).flatMap((item) =>
    item.quotes.map((quote) => ({ number: item.number, start: quote.start, end: quote.end })));
  for (const span of spans) { cuts.add(span.start); cuts.add(span.end); }
  const ordered = [...cuts].filter((cut) => cut >= 0 && cut <= points.length).sort((a, b) => a - b);
  const pieces: { text: string; statements: number[] }[] = [];
  for (let i = 0; i + 1 < ordered.length; i += 1) {
    const [start, end] = [ordered[i], ordered[i + 1]];
    const statements = [...new Set(spans.filter((span) => span.start <= start && end <= span.end)
      .map((span) => span.number))].sort((a, b) => a - b);
    pieces.push({ text: points.slice(start, end).join(""), statements });
  }
  return pieces;
}

// ---------------------------------------------------------------- reviews

export interface ReviewPayload {
  parent_review_id: string | null;
  binding: { result_view_sha256: string; request_sha256: string; response_sha256: string | null };
  status: ReviewStatus | null;
  notes: string;
}

export const latestReview = (view: ResearchRequestView) => view.reviews.records.at(-1) ?? null;
export const isCurrent = (record: ReviewRecord, view: ResearchRequestView) =>
  record.binding.result_view_sha256 === view.result_view_sha256;

export function reviewPayload(view: ResearchRequestView, status: ReviewStatus | null, notes: string): ReviewPayload {
  return { parent_review_id: latestReview(view)?.review_id ?? null,
           binding: { result_view_sha256: view.result_view_sha256 ?? "", request_sha256: view.request_sha256,
                      response_sha256: view.result?.provenance.response_sha256 ?? null },
           status, notes };
}

/** Problems the server would refuse, shown before saving. */
export function reviewProblems(view: ResearchRequestView, status: ReviewStatus | null, notes: string): string[] {
  const problems: string[] = [];
  if (notes.length > MAX_NOTES) problems.push(`Notes are limited to ${MAX_NOTES} characters.`);
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(notes)) problems.push("Notes contain a control character.");
  if (status === null && !notes.trim()) problems.push("Add notes or choose a status.");
  const latest = latestReview(view);
  if (latest && isCurrent(latest, view) && latest.status === status && latest.notes === notes) {
    problems.push("Nothing changed since the last saved version.");
  }
  return problems;
}

// ---------------------------------------------------------------- the local API

export type Read<T> = { state: "ready"; data: T } | { state: "missing" | "error"; message: string };
export type Action<T> = { state: "saved"; data: T } | { state: "failed" | "unconfirmed"; message: string };

const detail = (body: unknown) => object(body) && typeof body.detail === "string" ? body.detail : null;

async function read<T>(path: string, check: (body: unknown) => { problem: string } | T,
                       signal?: AbortSignal): Promise<Read<T>> {
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
  const checked = check(body);
  return object(checked) && "problem" in checked && typeof checked.problem === "string"
    ? { state: "error", message: checked.problem } : { state: "ready", data: checked as T };
}

export const fetchListing = (captureId: string, signal?: AbortSignal) =>
  read<ResearchListing>(`/api/research-analyses?capture_id=${encodeURIComponent(captureId)}`, (body) => {
    const checked = readListing(body, captureId);
    return "listing" in checked ? checked.listing : checked;
  }, signal);

export const fetchResearch = (requestId: string, signal?: AbortSignal) =>
  read<ResearchRequestView>(`/api/research-analyses/${encodeURIComponent(requestId)}`, (body) => {
    const checked = readResearch(body);
    return "view" in checked ? checked.view : checked;
  }, signal);

/** One explicit local write, from this page with the research header. Never retried automatically. */
async function act<T>(path: string, body: object, check: (body: unknown) => boolean): Promise<Action<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Second-Order-Research": "1" },
      body: JSON.stringify(body),
    });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server. Nothing was retried; read the " +
      "recorded state before doing anything else." };
  }
  const reply: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    // A 4xx is a refusal made before anything was written; a 5xx does not prove what was recorded.
    const message = detail(reply) ?? `Unexpected response (${response.status}).`;
    return { state: response.status >= 500 ? "unconfirmed" : "failed", message };
  }
  return check(reply) ? { state: "saved", data: reply as T }
    : { state: "unconfirmed", message: "The server replied, but its reply could not be verified." };
}

export interface SendResult { flow_version: string; request_id: string; mode: "mock" | "paid"; outcome: Outcome;
  provider_called: boolean; cost_usd: number | null }

const sent = (requestId: string) => (body: unknown) => object(body) && body.flow_version === RESEARCH_FLOW_VERSION &&
  body.request_id === requestId && oneOf(OUTCOMES, body.outcome);

export const prepareResearch = (captureId: string) =>
  act<ResearchRequestView>("/api/research-analyses", { capture_id: captureId },
                           (body) => "view" in readResearch(body) && (body as { capture_id?: unknown }).capture_id === captureId);

export const sendMock = (requestId: string, requestHash: string, outcome: MockOutcome) =>
  act<SendResult>(`/api/research-analyses/${encodeURIComponent(requestId)}/mock`,
                  { request_sha256: requestHash, mock_outcome: outcome }, sent(requestId));

/** The one paid action: the body repeats the request hash and the planning estimate the page showed. */
export const sendPaid = (requestId: string, requestHash: string, estimate: number) =>
  act<SendResult>(`/api/research-analyses/${encodeURIComponent(requestId)}/paid`,
                  { request_sha256: requestHash, approve_paid_request: true, estimated_max_usd: estimate },
                  sent(requestId));

export const saveReview = (requestId: string, payload: ReviewPayload) =>
  act<ReviewRecord>(`/api/research-analyses/${encodeURIComponent(requestId)}/reviews`, payload,
                    (body) => object(body) && body.record_version === RESEARCH_REVIEW_VERSION &&
                      body.request_id === requestId);
