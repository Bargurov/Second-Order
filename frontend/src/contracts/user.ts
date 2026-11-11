// The user contract (user-api-0.5, docs/admin-user-contract.md and its amendments in docs/onboarding-contract.md,
// docs/account-binding-contract.md, docs/news-usage-contract.md and docs/news-stories-contract.md): the only server
// payloads the Client reads and the only requests it sends. Owned by the logic conversation; the Client and the public
// pages import it and never edit it. user-api-0.1 to 0.4 payloads are also read: 0.2 only adds codes, reasons and
// fields, 0.3 only adds the account binding and its two refusals, 0.4 adds the news, interests, import and limits
// routes (src/contracts/news.ts) and their refusals, and 0.5 adds the stories, topics and Go deeper routes
// (src/contracts/stories.ts), the interests vocabulary news-interests-0.2 and their refusals.
//
// Account binding (0.3): a page names the account it was opened for in ACCOUNT_HEADER. Request helpers made with
// `userApi(fetcher, { account })` send it on every user read and write and on sign-out, never on the session read or
// sign-in. A request bound to another account than the browser's session is refused before anything is read or written
// (401 account_changed); a user write that names no account is refused too (428 account_binding_required).
//
// Every reader is fail-closed: a payload missing a required field, carrying an unknown state or contradicting itself
// (a recorded result without its charge, a quote outside the source text, a charge above what was reserved) is
// refused as unreadable rather than shown. Unknown extra fields are ignored. Nothing here carries or reads a model or
// provider name, a monetary amount, a token count or an operational log: the server's user projections omit them.
// The request helpers only describe requests; nothing is sent until a caller invokes one, and none retries.

export const USER_CONTRACT = "user-api-0.5";
/** The versions a reader accepts: this one, and 0.4 to 0.1, whose payloads are subsets of it. */
export const READABLE_CONTRACTS = [USER_CONTRACT, "user-api-0.4", "user-api-0.3", "user-api-0.2", "user-api-0.1"] as const;
export const SESSION_HEADER = "X-Second-Order-Session";
export const USER_HEADER = "X-Second-Order-User";
/** The account a page was opened for (its SessionUser.user_id), sent by bound request helpers. */
export const ACCOUNT_HEADER = "X-Second-Order-Account";

export const ROLES = ["admin", "user"] as const;
export const MODES = ["accounts", "local-operator"] as const;
export const SIGNED_OUT_REASONS = ["not_signed_in", "session_expired", "signed_out"] as const;
/** The provider's vocabulary; a server offers a verified, admin-enabled subset, in this order. */
export const EFFORTS = ["low", "medium", "high", "xhigh", "max"] as const;
/** In the server's order: when several apply, `reason` is the first and `reasons` lists them all. */
export const UNAVAILABLE_REASONS = ["sending_disabled", "no_credit_policy", "no_effort_enabled", "no_daily_limit",
  "no_credits_allocated", "no_credits_available", "account_inactive"] as const;
export const REGISTRATION_STATES = ["pending", "rejected"] as const;
export const ANALYSIS_STATES = ["prepared", "running", "recorded", "failed", "unresolved", "not_sent"] as const;
export const CHARGE_STATES = ["held", "charged", "returned", "under_review"] as const;
export const OUTCOMES = ["analysis", "no_additional_finding", "declined", "incomplete", "invalid"] as const;
export const QUOTE_STATES = ["active", "expired", "used", "superseded"] as const;
export const BASES = ["action", "data", "assessment", "forecast"] as const;
export const REVIEW_STATUSES = ["needs_revision", "human_reviewed"] as const;
export const ERROR_CODES = ["not_signed_in", "session_expired", "invalid_credentials", "registration_pending",
  "registration_rejected", "forbidden", "not_found",
  "unsupported_effort", "no_credit_policy", "request_over_budget", "already_attempted", "quote_expired",
  "quote_superseded", "quote_mismatch", "insufficient_credits", "no_daily_limit", "daily_limit_reached",
  "result_changed", "review_conflict", "no_result", "payload_too_large", "invalid_request", "invalid_source",
  "invalid_review", "sending_disabled", "accounts_unavailable", "internal_error", "account_changed",
  "account_binding_required",
  // user-api-0.4 (docs/news-usage-contract.md section 4): limits, then news and publication import.
  "no_usage_policy", "usage_limit_reached", "storage_limit_reached", "fetch_budget_reached", "request_key_reused",
  "interests_changed", "rate_limited", "too_many_requests", "entry_changed", "import_unsupported",
  "publication_unavailable", "publication_time_conflict", "import_in_progress", "publication_changed",
  "import_interrupted", "publication_unreadable", "publication_too_long",
  // user-api-0.5 (docs/news-stories-contract.md section 5): Go deeper.
  "story_changed", "deeper_unavailable", "newsroom_unreadable",
  // A Go deeper source saved before its publishers' passages were recorded (deeper-evidence-0.1).
  "source_unmarked"] as const;
/** The counted operations of docs/news-usage-contract.md section 3, in the order the server lists them. */
export const OPERATIONS = ["search", "import", "source", "preparation"] as const;
export const STORAGE_MEASURES = ["sources", "source_bytes"] as const;
export const MAX_NOTES = 20_000;
/** A source's limits, in characters (code points, as `Array.from(text).length` counts them) in any script. The
 * server reads a source form of up to MAX_SOURCE_FORM_BYTES, which every form within them fits as a browser sends it
 * (admin-user-contract.md, Source); tests/test_user_research.py holds these equal to the server's. */
export const MAX_SOURCE_CHARACTERS = 50_000;
export const MAX_HEADLINE_CHARACTERS = 1_500;
export const MAX_SOURCE_FORM_BYTES = 270_000;
/** A source address's limit, in UTF-8 bytes of the address as sent (`new TextEncoder().encode(address).length`): a
 * character outside ASCII counts two to four. tests/test_user_research.py holds it equal to the server's. */
export const MAX_SOURCE_URL_CHARACTERS = 2_083;

export type Role = (typeof ROLES)[number];
export type Mode = (typeof MODES)[number];
export type SignedOutReason = (typeof SIGNED_OUT_REASONS)[number];
export type Effort = (typeof EFFORTS)[number];
export type UnavailableReason = (typeof UNAVAILABLE_REASONS)[number];
export type AnalysisState = (typeof ANALYSIS_STATES)[number];
export type ChargeState = (typeof CHARGE_STATES)[number];
export type Outcome = (typeof OUTCOMES)[number];
export type QuoteState = (typeof QUOTE_STATES)[number];
export type Basis = (typeof BASES)[number];
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];
export type ErrorCode = (typeof ERROR_CODES)[number];
export type UserContract = (typeof READABLE_CONTRACTS)[number];
export type RegistrationState = (typeof REGISTRATION_STATES)[number];
export type Operation = (typeof OPERATIONS)[number];
export type StorageMeasure = (typeof STORAGE_MEASURES)[number];

export const EFFORT_LABEL: Record<Effort, string> = {
  low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Maximum",
};

// ---------------------------------------------------------------- payload types

export interface SessionUser { user_id: string; username: string; display_name: string; role: Role }
export interface SignedInSession {
  contract: UserContract; mode: Mode; state: "signed_in"; user: SessionUser; expires_at: string | null;
}
export interface SignedOutSession {
  contract: UserContract; mode: Mode; state: "signed_out"; reason: SignedOutReason; user: null;
  expires_at: null;
}
export type Session = SignedInSession | SignedOutSession;

export interface Credits { available: number; held: number }
export interface Daily {
  timezone: string; day: string; limit: number | null; used: number; remaining: number | null; resets_at: string;
}
export interface EffortOption { effort: Effort; label: string }
export interface Unavailable { reason: UnavailableReason; detail: string }
export interface Account {
  contract: UserContract; user: SessionUser; credits: Credits; daily: Daily; efforts: EffortOption[];
  effort_note: string;
  /** `reasons` (user-api-0.2) lists every missing step in the server's order; a 0.1 payload omits it. */
  analysis: { available: true; reason: null; detail: null; reasons?: [] }
    | { available: false; reason: UnavailableReason; detail: string; reasons?: Unavailable[] };
}

/** A registrant's own registration, as sign-in refusals and the registration reply show it. */
export interface RegistrationStatus {
  username: string; display_name: string; status: RegistrationState; submitted_at: string;
  decided_at: string | null; detail: string;
}

export interface SourceForm { headline: string; source_url: string; published_at: string; source_text: string }
export interface SourceSummary {
  source_id: string; headline: string; source_url: string; published_at: string; published_at_as_supplied: string;
  captured_at: string; characters: number;
}
export interface Source extends SourceSummary { text: string }

/** The parts of a Go deeper source that are a publisher's own words (deeper-evidence-0.1). */
export const EVIDENCE_PARTS = ["headline", "excerpt", "text"] as const;
export type EvidencePart = (typeof EVIDENCE_PARTS)[number];
/** Where a Go deeper source's quote comes from: the report's number in the source, its publisher and the part. */
export interface QuoteEvidence { report: number; publisher: string; part: EvidencePart }
export interface LocatedQuote {
  text: string; match: "exact" | "normalized"; start: number; end: number; paragraphs: number[];
  source_passage: string; occurrences: number;
  /** Only on a Go deeper source's quote; absent on a quote of a source the user supplied. */
  evidence?: QuoteEvidence;
}
export interface Established { number: number; statement: string; basis: Basis; quotes: LocatedQuote[] }
export interface ResearchContent {
  established: Established[];
  interpretation: { kind: "finding" | "no_additional_finding"; text: string; based_on: number[] };
  assumptions: string[];
  competing_explanations: { explanation: string; would_distinguish: string }[];
  missing_information: string[];
  tests: { check: string; counts_against_if: string }[];
}
export interface Result {
  outcome: Outcome; note: string; recorded_at: string; analysis: ResearchContent | null; explanation: string | null;
}
export interface Quote {
  quote_id: string; analysis_id: string; effort: Effort; credits: number; policy_version: string; issued_at: string;
  expires_at: string; state: QuoteState;
}
export interface Charge {
  credits_reserved: number; credits_charged: number | null; credits_returned: number | null; state: ChargeState;
  quota_day: string;
}
export interface Review {
  review_id: string; sequence: number; parent_review_id: string | null; saved_at: string;
  status: ReviewStatus | null; notes: string; result_sha256: string;
  reviewer: { user_id: string; display_name: string };
}
export interface Analysis {
  analysis_id: string; effort: Effort; prepared_at: string; source: Source; state: AnalysisState;
  state_detail: string; quote: Quote | null; charge: Charge | null; result: Result | null;
  result_sha256: string | null; reviews: Review[]; retrospective: string;
  baseline: { state: "not_supplied"; note: string };
}
export interface AnalysisSummary {
  analysis_id: string; source: { source_id: string; headline: string; published_at: string }; effort: Effort;
  prepared_at: string; state: AnalysisState; outcome: Outcome | null; review_status: ReviewStatus | null;
  credits_charged: number | null;
}

export interface RunApproval { quote_id: string; effort: Effort; credits: number; approve: true }
export interface ReviewForm {
  parent_review_id: string | null; result_sha256: string; status: ReviewStatus | null; notes: string;
}

/** A counted operation's figures in a refusal (usage_limit_reached). */
export interface Quota { operation: Operation; limit: number; used: number; day: string; timezone: string;
  resets_at: string }
/** What an account holds against a storage limit (storage_limit_reached). */
export interface Storage { measure: StorageMeasure; limit: number; used: number; adding: number }

export interface ApiError {
  contract: UserContract; code: ErrorCode; detail: string;
  /** Present on some codes; see docs/admin-user-contract.md section 9, docs/onboarding-contract.md section 4 and
   * docs/news-usage-contract.md section 4. */
  credits?: Credits; daily?: Daily; resets_at?: string; efforts?: EffortOption[]; registration?: RegistrationStatus;
  quota?: Quota; storage?: Storage; retry_after_seconds?: number; paste_instead?: true;
  /** An import preview's refusal: whether the publisher's page was requested for it (then the preview counted). */
  requested?: boolean;
  /** interests_changed: the selection saved since the page loaded (read with news.ts readInterestsState). */
  interests?: unknown;
}

/** What the shell gives the Client app. The session is validated and its role is "user". */
export interface ClientAppProps {
  session: SignedInSession;
  signOut: () => Promise<void>;
  /** Call when any request answers 401: the shell shows the sign-in form with the reason. */
  sessionEnded: (reason: "not_signed_in" | "session_expired") => void;
}

// ---------------------------------------------------------------- readers

export type Read<T> = { ok: true; value: T } | { ok: false; problem: string };

export const SOURCE_ID = /^\d{8}T\d{12}Z-[0-9a-f]{12}$/;
const ANALYSIS_ID = /^[A-Za-z0-9._-]{1,160}$/;
const TOKEN_ID = /^[A-Za-z0-9_-]{8,80}$/;
const USER_ID = /^(u-[0-9a-f]{16}|local-operator)$/;
export const SHA = /^[0-9a-f]{64}$/;
export const DAY = /^\d{4}-\d{2}-\d{2}$/;
const TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?([+-]\d{2}:\d{2}|Z)$/;

export const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
export const text = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
export const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
export const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;
export const time = (value: unknown): value is string => typeof value === "string" && TIME.test(value) &&
  !Number.isNaN(Date.parse(value));
export const oneOf = <T extends string>(values: readonly T[], value: unknown): value is T =>
  typeof value === "string" && (values as readonly string[]).includes(value);

/** The text between two code-point offsets, as the server counts them. */
export const codePoints = (value: string, start: number, end: number) => Array.from(value).slice(start, end).join("");

/** Keys that belong only to admin payloads. A user payload that carries one, at any depth, is refused: the server's
 * projection is the guard, and this is the second one. */
export const ADMIN_ONLY_KEYS = ["model", "provider", "usage", "input_tokens", "output_tokens", "max_tokens",
  "cost_usd", "usage_cost_usd", "usage_cost_basis", "planning_estimate_usd", "estimated_cost", "cost_estimate",
  "prices", "http_status", "provider_request_id", "request_id_provider", "response_sha256", "request_sha256",
  "request", "response", "prompt_version", "provenance", "endpoint", "attempt_files"] as const;

function leakedKey(value: unknown, depth = 0): string | null {
  if (depth > 12 || typeof value !== "object" || value === null) return null;
  for (const [key, item] of Object.entries(value)) {
    if ((ADMIN_ONLY_KEYS as readonly string[]).includes(key)) return key;
    const nested = leakedKey(item, depth + 1);
    if (nested) return nested;
  }
  return null;
}

export function contractProblem(body: unknown): string | null {
  if (!record(body)) return "The reply is not a JSON object.";
  if (!oneOf(READABLE_CONTRACTS, body.contract)) return `The reply is not in the ${USER_CONTRACT} contract.`;
  const leaked = leakedKey(body);
  return leaked ? `The reply carries an administrator-only field (${leaked}); it is not shown.` : null;
}

function userProblem(user: unknown): string | null {
  if (!record(user)) return "The session has no user.";
  if (typeof user.user_id !== "string" || !USER_ID.test(user.user_id) || !text(user.username) ||
      !text(user.display_name) || !oneOf(ROLES, user.role)) return "The session's user is not readable.";
  return null;
}

export function readSession(body: unknown): Read<Session> {
  const problem = contractProblem(body);
  if (problem) return { ok: false, problem };
  const session = body as Record<string, unknown>;
  if (!oneOf(MODES, session.mode)) return { ok: false, problem: "The session's mode is unknown." };
  if (session.state === "signed_in") {
    const bad = userProblem(session.user);
    if (bad) return { ok: false, problem: bad };
    if (!(session.expires_at === null || time(session.expires_at))) {
      return { ok: false, problem: "The session's expiry is not a time." };
    }
    if (session.mode === "local-operator" && (session.user as SessionUser).role !== "admin") {
      return { ok: false, problem: "A local-operator session must be the operator." };
    }
    return { ok: true, value: session as unknown as SignedInSession };
  }
  if (session.state === "signed_out") {
    if (session.user !== null || session.expires_at !== null || !oneOf(SIGNED_OUT_REASONS, session.reason)) {
      return { ok: false, problem: "The signed-out session is not readable." };
    }
    return { ok: true, value: session as unknown as SignedOutSession };
  }
  return { ok: false, problem: "The session's state is unknown." };
}

function creditsProblem(credits: unknown): string | null {
  return record(credits) && count(credits.available) && count(credits.held) ? null
    : "The credit balance is not readable.";
}

function dailyProblem(daily: unknown): string | null {
  if (!record(daily) || !text(daily.timezone) || typeof daily.day !== "string" || !DAY.test(daily.day) ||
      !count(daily.used) || !time(daily.resets_at)) return "The daily allowance is not readable.";
  if (daily.limit === null) {
    return daily.remaining === null ? null : "A daily allowance without a limit cannot have a remainder.";
  }
  if (!count(daily.limit) || !count(daily.remaining)) return "The daily allowance is not readable.";
  return daily.remaining === Math.max(0, daily.limit - daily.used) ? null
    : "The daily allowance's remainder does not follow from its limit and use.";
}

function effortsProblem(efforts: unknown): string | null {
  if (!Array.isArray(efforts)) return "The Effort options are not a list.";
  const seen = efforts.map((option) => record(option) && oneOf(EFFORTS, option.effort) && text(option.label)
    ? EFFORTS.indexOf(option.effort) : -1);
  if (seen.some((index) => index < 0)) return "An Effort option is not readable.";
  return seen.every((index, position) => position === 0 || index > seen[position - 1]) ? null
    : "The Effort options repeat or are out of order.";
}

export function readAccount(body: unknown): Read<Account> {
  const problem = contractProblem(body);
  if (problem) return { ok: false, problem };
  const account = body as Record<string, unknown>;
  const bad = userProblem(account.user) ?? creditsProblem(account.credits) ?? dailyProblem(account.daily) ??
    effortsProblem(account.efforts);
  if (bad) return { ok: false, problem: bad };
  if (!text(account.effort_note)) return { ok: false, problem: "The Effort note is missing." };
  const availability = account.analysis;
  if (!record(availability)) return { ok: false, problem: "The account does not say whether analyses can run." };
  const readable = availability.available === true
    ? availability.reason === null && availability.detail === null
    : availability.available === false && oneOf(UNAVAILABLE_REASONS, availability.reason) && text(availability.detail);
  if (!readable) return { ok: false, problem: "The account's analysis availability is not readable." };
  if (availability.reasons !== undefined) {
    const reasons = availability.reasons;
    const listed = Array.isArray(reasons) && reasons.every((item) => record(item) &&
      oneOf(UNAVAILABLE_REASONS, item.reason) && text(item.detail));
    if (!listed) return { ok: false, problem: "The account's missing steps are not readable." };
    const order = (reasons as Unavailable[]).map((item) => UNAVAILABLE_REASONS.indexOf(item.reason));
    const agrees = availability.available === true ? order.length === 0
      : order.length > 0 && (reasons as Unavailable[])[0].reason === availability.reason &&
        (reasons as Unavailable[])[0].detail === availability.detail &&
        order.every((index, position) => position === 0 || index > order[position - 1]);
    if (!agrees) return { ok: false, problem: "The account's missing steps disagree with its availability." };
  }
  return { ok: true, value: account as unknown as Account };
}

const SUBMITTED_KEYS = ["username", "display_name", "status", "submitted_at", "decided_at", "detail"];

/** A registrant's own status; it never carries an account ID, role, password, reason, credits or limit. */
export function registrationProblem(registration: unknown): string | null {
  if (!record(registration) || !text(registration.username) || !text(registration.display_name) ||
      !oneOf(REGISTRATION_STATES, registration.status) || !time(registration.submitted_at) ||
      !(registration.decided_at === null || time(registration.decided_at)) || !text(registration.detail)) {
    return "The registration is not readable.";
  }
  if ((registration.status === "pending") !== (registration.decided_at === null)) {
    return "The registration's decision time does not match its status.";
  }
  const extra = Object.keys(registration).find((key) => !SUBMITTED_KEYS.includes(key));
  return extra ? `The registration carries an unexpected field (${extra}).` : null;
}

function sourceSummaryProblem(source: unknown): string | null {
  if (!record(source) || typeof source.source_id !== "string" || !SOURCE_ID.test(source.source_id) ||
      !text(source.headline) || !text(source.source_url) || !time(source.published_at) ||
      !text(source.published_at_as_supplied) || !time(source.captured_at) || !count(source.characters)) {
    return "A source is not readable.";
  }
  return null;
}

export function sourceProblem(source: unknown): string | null {
  const bad = sourceSummaryProblem(source);
  if (bad) return bad;
  const body = (source as Record<string, unknown>).text;
  if (typeof body !== "string" || Array.from(body).length !== (source as SourceSummary).characters) {
    return "The source's text does not match its recorded length.";
  }
  return null;
}

function quoteProblem(quote: unknown, sourceText: string): string | null {
  if (!record(quote) || !text(quote.text) || !oneOf(["exact", "normalized"] as const, quote.match) ||
      !count(quote.start) || !count(quote.end) || quote.end <= quote.start || !Array.isArray(quote.paragraphs) ||
      !quote.paragraphs.every((number) => Number.isInteger(number) && number >= 1) ||
      typeof quote.source_passage !== "string" || !Number.isInteger(quote.occurrences) ||
      (quote.occurrences as number) < 1) return "A quoted passage is not readable.";
  if (codePoints(sourceText, quote.start, quote.end) !== quote.source_passage) {
    return "A quoted passage is not at its recorded place in the source text.";
  }
  if (quote.match === "exact" && quote.text !== quote.source_passage) {
    return "An exact quote differs from the passage it names.";
  }
  if ("evidence" in quote) {
    const evidence = quote.evidence;
    if (!record(evidence) || !Number.isInteger(evidence.report) || (evidence.report as number) < 1 ||
        !text(evidence.publisher) || !oneOf(EVIDENCE_PARTS, evidence.part)) {
      return "A quoted passage's attribution to its report is not readable.";
    }
  }
  return null;
}

function researchProblem(content: unknown, sourceText: string): string | null {
  if (!record(content) || !Array.isArray(content.established) || content.established.length === 0) {
    return "The analysis has no established statements.";
  }
  for (const [position, item] of content.established.entries()) {
    if (!record(item) || item.number !== position + 1 || !text(item.statement) || !oneOf(BASES, item.basis) ||
        !Array.isArray(item.quotes) || item.quotes.length === 0) return "An established statement is not readable.";
    for (const quote of item.quotes) {
      const bad = quoteProblem(quote, sourceText);
      if (bad) return bad;
    }
  }
  const reading = content.interpretation;
  if (!record(reading) || !oneOf(["finding", "no_additional_finding"] as const, reading.kind) || !text(reading.text) ||
      !Array.isArray(reading.based_on)) return "The interpretation is not readable.";
  const statements = content.established.length;
  const named = reading.based_on as unknown[];
  if (!named.every((number) => Number.isInteger(number) && (number as number) >= 1 && (number as number) <= statements)
      || new Set(named).size !== named.length) return "The interpretation names statements that do not exist.";
  if (reading.kind === "finding" && named.length === 0) return "A finding must name the statements it relies on.";
  if (!texts(content.assumptions) || !texts(content.missing_information)) return "The analysis lists are not readable.";
  const pairs = (value: unknown, first: string, second: string) => Array.isArray(value) &&
    value.every((item) => record(item) && text(item[first]) && text(item[second]));
  if (!pairs(content.competing_explanations, "explanation", "would_distinguish") ||
      !pairs(content.tests, "check", "counts_against_if")) return "The analysis lists are not readable.";
  return null;
}

function resultProblem(result: unknown, sourceText: string): string | null {
  if (!record(result) || !oneOf(OUTCOMES, result.outcome) || !text(result.note) || !time(result.recorded_at)) {
    return "The result is not readable.";
  }
  const carriesAnalysis = result.outcome === "analysis" || result.outcome === "no_additional_finding";
  if (carriesAnalysis) {
    if (result.explanation !== null) return "A result with an analysis carries no explanation.";
    const bad = researchProblem(result.analysis, sourceText);
    if (bad) return bad;
    const kind = (result.analysis as ResearchContent).interpretation.kind;
    if ((result.outcome === "analysis") !== (kind === "finding")) {
      return "The result's outcome and its interpretation disagree.";
    }
    return null;
  }
  if (result.analysis !== null) return "Only an analysis or a no-additional-finding result carries an analysis.";
  if (result.outcome !== "declined" && result.explanation !== null) return "Only a decline carries an explanation.";
  return result.explanation === null || text(result.explanation) ? null : "The decline's explanation is not text.";
}

function quoteRecordProblem(quote: unknown, analysisId?: string, effort?: string): string | null {
  if (!record(quote) || typeof quote.quote_id !== "string" || !TOKEN_ID.test(quote.quote_id) ||
      typeof quote.analysis_id !== "string" || !ANALYSIS_ID.test(quote.analysis_id) || !oneOf(EFFORTS, quote.effort) ||
      !Number.isInteger(quote.credits) || (quote.credits as number) < 1 || !text(quote.policy_version) ||
      !time(quote.issued_at) || !time(quote.expires_at) || !oneOf(QUOTE_STATES, quote.state)) {
    return "The quote is not readable.";
  }
  if (Date.parse(quote.expires_at) <= Date.parse(quote.issued_at)) return "The quote expires before it was issued.";
  if (analysisId !== undefined && (quote.analysis_id !== analysisId || quote.effort !== effort)) {
    return "The quote belongs to another analysis or Effort.";
  }
  return null;
}

function chargeProblem(charge: unknown): string | null {
  if (!record(charge) || !Number.isInteger(charge.credits_reserved) || (charge.credits_reserved as number) < 1 ||
      !oneOf(CHARGE_STATES, charge.state) || typeof charge.quota_day !== "string" || !DAY.test(charge.quota_day)) {
    return "The charge is not readable.";
  }
  const settled = charge.state === "charged" || charge.state === "returned";
  if (!settled) {
    return charge.credits_charged === null && charge.credits_returned === null ? null
      : "An unsettled charge cannot name charged or returned credits.";
  }
  if (!count(charge.credits_charged) || !count(charge.credits_returned) ||
      charge.credits_charged + charge.credits_returned !== charge.credits_reserved) {
    return "The settled charge does not add up to what was reserved.";
  }
  if (charge.state === "returned" && charge.credits_charged !== 0) return "A returned charge charges nothing.";
  return null;
}

function reviewProblem(review: unknown, position: number, parent: string | null): string | null {
  if (!record(review) || typeof review.review_id !== "string" || !TOKEN_ID.test(review.review_id) ||
      review.sequence !== position + 1 || review.parent_review_id !== parent || !time(review.saved_at) ||
      !(review.status === null || oneOf(REVIEW_STATUSES, review.status)) || typeof review.notes !== "string" ||
      typeof review.result_sha256 !== "string" || !SHA.test(review.result_sha256) || !record(review.reviewer) ||
      typeof review.reviewer.user_id !== "string" || !USER_ID.test(review.reviewer.user_id) ||
      !text(review.reviewer.display_name)) return "A review version is not readable.";
  return null;
}

/** The states, and what each must and must not carry. */
const STATE_RULES: Record<AnalysisState, { charges: readonly (ChargeState | null)[]; result: boolean }> = {
  prepared: { charges: [null], result: false },
  running: { charges: ["held"], result: false },
  recorded: { charges: ["charged", "under_review", "returned"], result: true },
  failed: { charges: ["under_review", "charged", "returned"], result: false },
  unresolved: { charges: ["under_review", "charged", "returned"], result: false },
  not_sent: { charges: ["returned"], result: false },
};

function analysisProblem(analysis: unknown): string | null {
  if (!record(analysis) || typeof analysis.analysis_id !== "string" || !ANALYSIS_ID.test(analysis.analysis_id) ||
      !oneOf(EFFORTS, analysis.effort) || !time(analysis.prepared_at) || !oneOf(ANALYSIS_STATES, analysis.state) ||
      !text(analysis.state_detail) || !text(analysis.retrospective) || !record(analysis.baseline) ||
      analysis.baseline.state !== "not_supplied" || !text(analysis.baseline.note)) {
    return "The analysis is not readable.";
  }
  const bad = sourceProblem(analysis.source);
  if (bad) return bad;
  const rules = STATE_RULES[analysis.state];
  if (analysis.charge !== null) {
    const chargeBad = chargeProblem(analysis.charge);
    if (chargeBad) return chargeBad;
  }
  const chargeState = analysis.charge === null ? null : (analysis.charge as Charge).state;
  if (!rules.charges.includes(chargeState)) return `A ${analysis.state} analysis cannot have this charge.`;
  if (analysis.quote !== null) {
    if (analysis.state !== "prepared") return "Only a prepared analysis shows a quote.";
    const quoteBad = quoteRecordProblem(analysis.quote, analysis.analysis_id, analysis.effort);
    if (quoteBad) return quoteBad;
  }
  if (rules.result) {
    const resultBad = resultProblem(analysis.result, (analysis.source as Source).text);
    if (resultBad) return resultBad;
    if (typeof analysis.result_sha256 !== "string" || !SHA.test(analysis.result_sha256)) {
      return "A recorded result has no fingerprint.";
    }
  } else if (analysis.result !== null || analysis.result_sha256 !== null) {
    return `A ${analysis.state} analysis carries no result.`;
  }
  if (!Array.isArray(analysis.reviews)) return "The reviews are not a list.";
  if (analysis.reviews.length > 0 && !rules.result) return "Only a recorded result can be reviewed.";
  let parent: string | null = null;
  for (const [position, review] of analysis.reviews.entries()) {
    const reviewBad = reviewProblem(review, position, parent);
    if (reviewBad) return reviewBad;
    parent = (review as Review).review_id;
  }
  return null;
}

function summaryProblem(summary: unknown): string | null {
  if (!record(summary) || typeof summary.analysis_id !== "string" || !ANALYSIS_ID.test(summary.analysis_id) ||
      !record(summary.source) || typeof summary.source.source_id !== "string" ||
      !SOURCE_ID.test(summary.source.source_id) || !text(summary.source.headline) ||
      !time(summary.source.published_at) || !oneOf(EFFORTS, summary.effort) || !time(summary.prepared_at) ||
      !oneOf(ANALYSIS_STATES, summary.state) || !(summary.outcome === null || oneOf(OUTCOMES, summary.outcome)) ||
      !(summary.review_status === null || oneOf(REVIEW_STATUSES, summary.review_status)) ||
      !(summary.credits_charged === null || count(summary.credits_charged))) return "An analysis summary is not readable.";
  if ((summary.state === "recorded") !== (summary.outcome !== null)) {
    return "An analysis summary's outcome does not match its state.";
  }
  return null;
}

export function wrapped<T>(body: unknown, check: (payload: Record<string, unknown>) => string | null): Read<T> {
  const problem = contractProblem(body) ?? check(body as Record<string, unknown>);
  return problem ? { ok: false, problem } : { ok: true, value: body as T };
}

export const listProblem = (value: unknown, item: (entry: unknown) => string | null) =>
  Array.isArray(value) ? value.map(item).find((problem) => problem !== null) ?? null : "The list is not a list.";

export const readSourceCreated = (body: unknown) =>
  wrapped<{ contract: string; source: Source }>(body, (payload) => sourceProblem(payload.source));
export const readSources = (body: unknown) =>
  wrapped<{ contract: string; sources: SourceSummary[] }>(body, (payload) =>
    listProblem(payload.sources, sourceSummaryProblem));
export const readSourceDetail = (body: unknown) =>
  wrapped<{ contract: string; source: Source; analyses: AnalysisSummary[] }>(body, (payload) =>
    sourceProblem(payload.source) ?? listProblem(payload.analyses, summaryProblem) ??
    ((payload.analyses as AnalysisSummary[]).every((row) => row.source.source_id === (payload.source as Source).source_id)
      ? null : "The source lists another source's analysis."));
export const readAnalysis = (body: unknown) =>
  wrapped<{ contract: string; analysis: Analysis }>(body, (payload) => analysisProblem(payload.analysis));
export const readPrepared = (body: unknown) =>
  wrapped<{ contract: string; created: boolean; analysis: Analysis }>(body, (payload) =>
    typeof payload.created === "boolean" ? analysisProblem(payload.analysis) : "The reply does not say whether the analysis was new.");
export const readAnalyses = (body: unknown) =>
  wrapped<{ contract: string; analyses: AnalysisSummary[] }>(body, (payload) =>
    listProblem(payload.analyses, summaryProblem));
export const readQuoteIssued = (body: unknown) =>
  wrapped<{ contract: string; quote: Quote; account: Account }>(body, (payload) =>
    quoteRecordProblem(payload.quote) ?? ((payload.quote as Quote).state === "active" ? null
      : "A newly issued quote must be active.") ??
    (readAccount(payload.account).ok ? null : "The account sent with the quote is not readable."));
export const readRun = (body: unknown) =>
  wrapped<{ contract: string; duplicate: boolean; analysis: Analysis; account: Account }>(body, (payload) =>
    typeof payload.duplicate !== "boolean" ? "The reply does not say whether the run was a repeat."
      : analysisProblem(payload.analysis) ?? ((payload.analysis as Analysis).state === "prepared"
        ? "A run's reply cannot show an analysis that never ran." : null) ??
        (readAccount(payload.account).ok ? null : "The account sent with the run is not readable."));
export const readReviewSaved = (body: unknown) =>
  wrapped<{ contract: string; review: Review; analysis: Analysis }>(body, (payload) => {
    const bad = analysisProblem(payload.analysis);
    if (bad) return bad;
    const reviews = (payload.analysis as Analysis).reviews;
    return reviews.length > 0 && JSON.stringify(reviews.at(-1)) === JSON.stringify(payload.review) ? null
      : "The saved review is not the analysis's latest version.";
  });
export const readExport = (body: unknown) =>
  wrapped<{ contract: string; exported_at: string; analysis: Analysis }>(body, (payload) =>
    time(payload.exported_at) ? analysisProblem(payload.analysis) : "The export has no time.");

function quotaProblem(quota: unknown): string | null {
  if (!record(quota) || !oneOf(OPERATIONS, quota.operation) || !count(quota.limit) || !count(quota.used) ||
      typeof quota.day !== "string" || !DAY.test(quota.day) || !text(quota.timezone) || !time(quota.resets_at)) {
    return "The limit is not readable.";
  }
  return null;
}

function storageProblem(storage: unknown): string | null {
  if (!record(storage) || !oneOf(STORAGE_MEASURES, storage.measure) || !count(storage.limit) || !count(storage.used) ||
      !count(storage.adding)) return "The storage is not readable.";
  return storage.used + storage.adding <= storage.limit ? "A storage refusal must exceed its limit." : null;
}

export function readError(body: unknown): Read<ApiError> {
  const problem = contractProblem(body);
  if (problem) return { ok: false, problem };
  const error = body as Record<string, unknown>;
  if (!oneOf(ERROR_CODES, error.code) || !text(error.detail)) return { ok: false, problem: "The refusal is not readable." };
  if (error.credits !== undefined && creditsProblem(error.credits)) return { ok: false, problem: "The refusal's credits are not readable." };
  if (error.daily !== undefined && dailyProblem(error.daily)) return { ok: false, problem: "The refusal's allowance is not readable." };
  if (error.resets_at !== undefined && !time(error.resets_at)) return { ok: false, problem: "The refusal's reset time is not readable." };
  if (error.efforts !== undefined && effortsProblem(error.efforts)) return { ok: false, problem: "The refusal's Effort options are not readable." };
  if (error.quota !== undefined && quotaProblem(error.quota)) return { ok: false, problem: "The refusal's limit is not readable." };
  if (error.storage !== undefined && storageProblem(error.storage)) return { ok: false, problem: "The refusal's storage is not readable." };
  if (error.retry_after_seconds !== undefined && !count(error.retry_after_seconds)) return { ok: false, problem: "The refusal's wait is not readable." };
  if (error.paste_instead !== undefined && error.paste_instead !== true) return { ok: false, problem: "The refusal's paste offer is not readable." };
  if (error.requested !== undefined && typeof error.requested !== "boolean") return { ok: false, problem: "The refusal's request note is not readable." };
  if ((error.code === "usage_limit_reached") !== (error.quota !== undefined)) return { ok: false, problem: "The refusal's limit is missing or unexpected." };
  if ((error.code === "storage_limit_reached") !== (error.storage !== undefined)) return { ok: false, problem: "The refusal's storage is missing or unexpected." };
  if ((error.code === "rate_limited" || error.code === "too_many_requests") !== (error.retry_after_seconds !== undefined)) {
    return { ok: false, problem: "The refusal's wait is missing or unexpected." };
  }
  const registered = error.code === "registration_pending" || error.code === "registration_rejected";
  if (registered !== (error.registration !== undefined)) return { ok: false, problem: "The refusal's registration is missing or unexpected." };
  if (registered) {
    const bad = registrationProblem(error.registration);
    if (bad) return { ok: false, problem: bad };
    if ((error.registration as RegistrationStatus).status !== String(error.code).slice("registration_".length)) {
      return { ok: false, problem: "The refusal and its registration disagree." };
    }
  }
  return { ok: true, value: error as unknown as ApiError };
}

// ---------------------------------------------------------------- requests

/** The outcome of one request. "refused" (4xx) means this call reserved, sent and wrote nothing. "unconfirmed" (a
 * 5xx, a lost reply or an unreadable one) proves nothing either way: read the record again; never retry on your own. */
export type Reply<T, E = ApiError> =
  | { state: "ok"; status: number; data: T }
  | { state: "refused"; status: number; error: E }
  | { state: "unconfirmed"; status: number | null; message: string; error: E | null };

export type Fetcher = (input: string, init: RequestInit) => Promise<Response>;

const UNREACHABLE = "No reply arrived from the server. Nothing was retried; read the page again before acting.";

/** One request, never retried; `readRefusal` reads the route's error shape (the user contract's by default).
 * `account`, when given, binds the request to that account (ACCOUNT_HEADER). */
export async function request<T, E = ApiError>(fetcher: Fetcher, method: "GET" | "POST", path: string,
                                               body: object | undefined, header: string,
                                               read: (body: unknown) => Read<T>,
                                               readRefusal: (body: unknown) => Read<E> = readError as never,
                                               account: string | null = null,
): Promise<Reply<T, E>> {
  const bound: Record<string, string> = account === null ? {} : { [ACCOUNT_HEADER]: account };
  const init: RequestInit = method === "GET"
    ? { method, headers: { Accept: "application/json", ...bound }, credentials: "same-origin" }
    : { method, credentials: "same-origin", body: JSON.stringify(body ?? {}),
        headers: { Accept: "application/json", "Content-Type": "application/json", [header]: "1", ...bound } };
  let response: Response;
  try {
    response = await fetcher(path, init);
  } catch {
    return { state: "unconfirmed", status: null, message: UNREACHABLE, error: null };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = readRefusal(payload);
    if (response.status < 500 && error.ok) return { state: "refused", status: response.status, error: error.value };
    return { state: "unconfirmed", status: response.status, error: error.ok ? error.value : null,
             message: error.ok ? (error.value as { detail: string }).detail : `Unexpected reply (${response.status}).` };
  }
  const parsed = read(payload);
  return parsed.ok ? { state: "ok", status: response.status, data: parsed.value }
    : { state: "unconfirmed", status: response.status, error: null,
        message: `The server replied, but the reply could not be read: ${parsed.problem}` };
}

const path = (...parts: string[]) => parts.map((part, index) => index === 0 ? part : encodeURIComponent(part)).join("/");

/** The account a page was opened for: the signed-in session's user. */
export interface AccountBinding { account: string }

/** Request helpers bound to one fetch implementation (the browser's by default; a test transport in tests) and, for a
 * signed-in page, to its account. Unbound helpers can read the session, sign in and register; the server refuses their
 * user writes (428 account_binding_required). */
export function userApi(fetcher: Fetcher = (input, init) => fetch(input, init), binding: AccountBinding | null = null) {
  const account = binding?.account ?? null;
  const get = <T>(url: string, read: (body: unknown) => Read<T>) =>
    request(fetcher, "GET", url, undefined, USER_HEADER, read, undefined, account);
  const post = <T>(url: string, body: object, read: (body: unknown) => Read<T>) =>
    request(fetcher, "POST", url, body, USER_HEADER, read, undefined, account);
  return {
    session: () => request(fetcher, "GET", "/api/session", undefined, SESSION_HEADER, readSession),
    signIn: (username: string, password: string) =>
      request(fetcher, "POST", "/api/session/login", { username, password }, SESSION_HEADER, readSession),
    signOut: () => request(fetcher, "POST", "/api/session/logout", {}, SESSION_HEADER, readSession, undefined, account),
    account: () => get("/api/user/account", readAccount),
    addSource: (form: SourceForm) => post("/api/user/sources", form, readSourceCreated),
    sources: () => get("/api/user/sources", readSources),
    source: (sourceId: string) => get(path("/api/user/sources", sourceId), readSourceDetail),
    prepareAnalysis: (sourceId: string, effort: Effort) =>
      post("/api/user/analyses", { source_id: sourceId, effort }, readPrepared),
    analyses: () => get("/api/user/analyses", readAnalyses),
    analysis: (analysisId: string) => get(path("/api/user/analyses", analysisId), readAnalysis),
    quote: (analysisId: string) => post(`${path("/api/user/analyses", analysisId)}/quotes`, {}, readQuoteIssued),
    run: (analysisId: string, approval: RunApproval) =>
      post(`${path("/api/user/analyses", analysisId)}/runs`, approval, readRun),
    review: (analysisId: string, form: ReviewForm) =>
      post(`${path("/api/user/analyses", analysisId)}/reviews`, form, readReviewSaved),
    exportHref: (analysisId: string) => `${path("/api/user/analyses", analysisId)}/export`,
  };
}

export type UserApi = ReturnType<typeof userApi>;

/** A refusal about the account binding: the browser is now signed in as another account than the page's
 * (account_changed), or a write named no account (account_binding_required). Nothing was read or written. */
export function bindingRefusal(reply: Reply<unknown, ApiError>): "account_changed" | "account_binding_required" | null {
  if (reply.state === "ok") return null;
  const code = reply.error?.code;
  return code === "account_changed" || code === "account_binding_required" ? code : null;
}

/** The approval for a quote: the user's explicit credit decision, repeating the quote exactly. */
export const approvalFor = (quote: Quote): RunApproval =>
  ({ quote_id: quote.quote_id, effort: quote.effort, credits: quote.credits, approve: true });
