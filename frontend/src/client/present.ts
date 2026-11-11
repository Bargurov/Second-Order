// Every sentence the Client shows about entitlements, states, charges and history, built from server payloads only.
// The server is the authority: these lines report what it said and when, and never count, predict or enforce anything.
import {
  EFFORT_LABEL, MAX_HEADLINE_CHARACTERS, MAX_SOURCE_CHARACTERS, MAX_SOURCE_URL_CHARACTERS, type Account, type AnalysisState, type AnalysisSummary, type Basis, type Charge,
  type Effort, type Outcome, type Quote, type ReviewStatus, type Analysis, type Unavailable, type UnavailableReason,
} from "../contracts/user.ts";
import type { FlowState } from "./flow.ts";
import { dayLabel, inUtc, inZone } from "./time.ts";

/** The attempt's state only. What happened to its credits is the charge's business (chargeLine), never this label's. */
export const STATE_LABEL: Record<AnalysisState, string> = {
  prepared: "Prepared · not run",
  running: "Running",
  recorded: "Recorded",
  failed: "Did not complete",
  unresolved: "Outcome not recorded",
  not_sent: "Not sent",
};

/** What the attempt means for the person, apart from its credits. Running, failed and unresolved runs are never sent
 * again, whatever later happened to their credits. */
export const ATTEMPT_LINE: Partial<Record<AnalysisState, string>> = {
  running: "It was sent once and is never sent again. Read this page again to see what the server has recorded.",
  failed: "This analysis did not complete. It is not run again.",
  unresolved: "No outcome was recorded for this run. It is not sent again.",
};

/** Shown while the page waits for a run's reply. It promises one attempt only, not a recorded outcome. */
export const RUNNING_NOTE = "Running. This can take several minutes. It is sent once and never again. If you leave, " +
  "come back and read this page again to see what the server has recorded; if no outcome could be recorded, the " +
  "attempt is held for an administrator's review.";

/** After a run whose reply is unconfirmed: until the analysis is read again, nothing else is offered. */
export const UNCERTAIN_NOTE = "The reply to this run did not arrive or could not be read, so this page does not know " +
  "whether it was sent. Nothing can be quoted, approved or run here until the analysis is read again from the server.";

export const OUTCOME_LABEL: Record<Outcome, string> = {
  analysis: "Analysis recorded",
  no_additional_finding: "No additional finding",
  declined: "Declined",
  incomplete: "Incomplete reply",
  invalid: "Reply did not pass the research checks",
};

export interface HeaderState {
  key: AnalysisState | "uncertain";
  label: string;
  outcome: { key: Outcome; label: string } | null;
}

/** The analysis page's header chips. While a run is uncertain the last read is out of date, so the header says only
 * that the outcome is unknown, never the stale state, until a successful read lifts the gate (flow.ts). */
export function headerState(flow: Pick<FlowState, "analysis" | "uncertain">): HeaderState | null {
  const analysis = flow.analysis;
  if (!analysis) return null;
  if (flow.uncertain) return { key: "uncertain", label: "Run outcome unknown", outcome: null };
  const outcome = analysis.result?.outcome;
  return { key: analysis.state, label: STATE_LABEL[analysis.state],
           outcome: outcome ? { key: outcome, label: OUTCOME_LABEL[outcome] } : null };
}

export const BASIS_LABEL: Record<Basis, string> = {
  action: "Action reported", data: "Data reported", assessment: "Publisher's assessment",
  forecast: "Publisher's forecast",
};

export const REVIEW_LABEL: Record<ReviewStatus, string> = { needs_revision: "Needs revision", human_reviewed: "Reviewed" };
export const NO_REVIEW = "No judgment recorded";
export const reviewLabel = (status: ReviewStatus | null) => (status ? REVIEW_LABEL[status] : NO_REVIEW);

/** The label the server gives an Effort, or the contract's own label when the server no longer lists it. */
export function effortLabel(effort: Effort, account?: Account | null): string {
  return account?.efforts.find((option) => option.effort === effort)?.label ?? EFFORT_LABEL[effort];
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

export interface EntitlementLines {
  credits: string;
  held: string | null;
  daily: string;
  reset: string;
  resetUtc: string;
  availability: string | null;
  basis: string;
}

/** The account as the server reported it at `readAt` (an ISO time). */
export function entitlements(account: Account, readAt: string): EntitlementLines {
  const { credits, daily } = account;
  return {
    credits: `${plural(credits.available, "credit", "credits")} available`,
    held: credits.held > 0
      ? `${plural(credits.held, "credit", "credits")} held by analyses that are running or awaiting an administrator's review`
      : null,
    daily: daily.limit === null
      ? "No daily analysis limit is set for your account"
      : `${daily.remaining} of ${plural(daily.limit, "analysis", "analyses")} left today (${daily.used} used on ${dayLabel(daily.day)})`,
    reset: inZone(daily.resets_at, daily.timezone),
    resetUtc: inUtc(daily.resets_at),
    availability: account.analysis.available ? null : account.analysis.detail,
    basis: `As the server reported at ${inZone(readAt, daily.timezone)}. The server checks your balance and allowance ` +
      "again for every quote and run; this page does not count or reserve anything.",
  };
}

export interface MissingStep {
  reason: UnavailableReason;
  title: string;
  /** The server's own words for this step. */
  detail: string;
  /** Who can put it in place. */
  who: string;
  /** Credits held by earlier runs, when none are available now. */
  held: string | null;
}

const STEP_TITLE: Record<UnavailableReason, string> = {
  sending_disabled: "Analyses cannot run on this server now",
  no_credit_policy: "No credit terms are set on this server",
  no_effort_enabled: "No Effort is offered on this server",
  no_daily_limit: "No daily allowance is set for your account",
  no_credits_allocated: "No credits have been allocated to your account",
  no_credits_available: "No credits are available now",
  account_inactive: "Your account is not active",
};

const SERVER_WIDE = "This applies to the whole server; its administrator decides.";
const STEP_WHO: Record<UnavailableReason, string> = {
  sending_disabled: SERVER_WIDE, no_credit_policy: SERVER_WIDE, no_effort_enabled: SERVER_WIDE,
  no_daily_limit: "The administrator sets it for your account.",
  no_credits_allocated: "The administrator allocates credits to your account.",
  no_credits_available: "The administrator allocates credits to your account.",
  account_inactive: "Ask the administrator.",
};

/** Every step the server says is missing before an analysis can be quoted and run, in the server's order
 * (`analysis.reasons`, user-api-0.2; a 0.1 account names its first reason only). Nothing here is inferred from figures. */
export function missingSteps(account: Account): MissingStep[] {
  const availability = account.analysis;
  if (availability.available) return [];
  const listed: Unavailable[] = availability.reasons && availability.reasons.length > 0 ? availability.reasons
    : [{ reason: availability.reason, detail: availability.detail }];
  return listed.map(({ reason, detail }) => ({ reason, detail, title: STEP_TITLE[reason], who: STEP_WHO[reason],
    held: reason === "no_credits_available" && account.credits.held > 0
      ? `${plural(account.credits.held, "credit", "credits")} held by analyses that are running or awaiting an ` +
        "administrator's review." : null }));
}

const thousands = (count: number) => count.toLocaleString("en-US");

/** Beside the source text: the server's character limit (user contract section 6), counted as the server counts it. */
export const SOURCE_SIZE_NOTE = `Up to ${thousands(MAX_SOURCE_CHARACTERS)} characters in any script, counted as the ` +
  "server counts them: an emoji made of several parts (a flag, a skin tone) counts as several.";
export const HEADLINE_NOTE = `The publication's own headline, on one line, up to ${thousands(MAX_HEADLINE_CHARACTERS)} ` +
  "characters.";

/** Beside the source address: the server accepts an http(s) address of at most MAX_SOURCE_URL_CHARACTERS UTF-8 bytes
 * as sent (user contract section 6; the shared constant is held equal to the server's). In the server's own words, a
 * character outside basic Latin (ASCII) counts as two to four. */
export const SOURCE_URL_NOTE = "Where it was published: a web address beginning with https:// or http://, at most " +
  `${thousands(MAX_SOURCE_URL_CHARACTERS)} characters, where a character outside basic Latin counts as two to four.`;

const INCOMPLETE_URL = "Not a complete web address yet: it begins with https:// or http://.";
const encoder = new TextEncoder();

/** A typed source address the server would certainly refuse, parsed as the browser parses an address; an empty one is
 * left to the field being required. An address this passes is still checked by the server. */
function sourceUrlProblem(typed: string): string | undefined {
  const value = typed.trim();  // As it is sent.
  if (value === "") return undefined;
  let address: URL;
  try {
    address = new URL(value);
  } catch {
    return INCOMPLETE_URL;
  }
  if (address.protocol !== "https:" && address.protocol !== "http:") {
    return "Only a web address beginning with https:// or http:// is accepted.";
  }
  if (address.hostname === "") return INCOMPLETE_URL;
  const counted = encoder.encode(value).length;  // UTF-8 bytes: what the server counts.
  return counted > MAX_SOURCE_URL_CHARACTERS
    ? `The address counts as ${thousands(counted)} characters, where a character outside basic Latin counts as two to ` +
      `four; at most ${thousands(MAX_SOURCE_URL_CHARACTERS)} are accepted.`
    : undefined;
}

export interface SourceFormProblems { headline?: string; source_url?: string; text?: string }

/** The source form's limits before sending, by the server's counts (code points); the server checks them again. */
export function sourceFormProblems(form: { headline: string; text: string; source_url?: string }): SourceFormProblems {
  const problems: SourceFormProblems = {};
  const headline = Array.from(form.headline).length;
  if (/[\r\n]/.test(form.headline)) problems.headline = "A headline is one line.";
  else if (headline > MAX_HEADLINE_CHARACTERS) {
    problems.headline = `The headline has ${thousands(headline)} of ${thousands(MAX_HEADLINE_CHARACTERS)} characters.`;
  }
  const address = form.source_url === undefined ? undefined : sourceUrlProblem(form.source_url);
  if (address) problems.source_url = address;
  const text = Array.from(form.text).length;
  if (text > MAX_SOURCE_CHARACTERS) {
    problems.text = `The text has ${thousands(text)} of ${thousands(MAX_SOURCE_CHARACTERS)} characters.`;
  }
  return problems;
}

/** What happened to the credits of one run, from the server's durable charge record and nothing else: amounts the
 * server has not settled stay unstated. */
export function chargeLine(charge: Charge | null): string | null {
  if (charge === null) return null;
  const reserved = plural(charge.credits_reserved, "credit", "credits");
  const day = dayLabel(charge.quota_day);
  switch (charge.state) {
    case "held":
      return `${reserved} reserved while it runs, counted on ${day}'s allowance.`;
    case "under_review":
      return `${reserved} held for an administrator's review, counted on ${day}'s allowance. Nothing is refunded or ` +
        "charged automatically.";
    case "charged":
      return `${plural(charge.credits_charged ?? 0, "credit", "credits")} charged of ${reserved} reserved` +
        `${charge.credits_returned ? `; ${charge.credits_returned} returned` : ""}, counted on ${day}'s allowance.`;
    case "returned":
      return `${reserved} returned; nothing was charged.`;
  }
}

/** The approval the user gives: the analysis, its Effort and the credits, exactly as the quote states them. */
export function approvalSentence(analysis: Analysis, quote: Quote, account: Account | null): string {
  return `I approve running the ${effortLabel(quote.effort, account)} Effort analysis of “${analysis.source.headline}”, ` +
    `prepared ${inZone(analysis.prepared_at, account?.daily.timezone ?? "UTC")}. It reserves ` +
    `${plural(quote.credits, "credit", "credits")} now and one of today's analyses; I am never charged more than ` +
    `${plural(quote.credits, "credit", "credits")} for it.`;
}

/** When the quote was issued and until when the server accepts it, by the server's clock (never checked locally). */
export function quoteTimes(quote: Quote, timeZone: string): { until: string; issued: string } {
  return { until: inZone(quote.expires_at, timeZone),
           issued: `Issued ${inZone(quote.issued_at, timeZone)}, by the server's clock` };
}

export const QUOTE_STATE_TEXT: Record<Quote["state"], string> = {
  active: "Active",
  expired: "Expired: ask for a new quote.",
  used: "Already used for a run.",
  superseded: "No longer applies: the credit policy or the Effort options changed. Ask for a new quote.",
};

export interface HistoryRow {
  analysisId: string; sourceId: string; headline: string; effort: string; state: string; outcome: string | null;
  review: string | null; credits: string | null; prepared: string; stateKey: AnalysisState; outcomeKey: Outcome | null;
}

/** The user's analyses, newest prepared first. Credits charged appear only once the server has settled them. */
export function historyRows(summaries: AnalysisSummary[], account: Account | null): HistoryRow[] {
  const zone = account?.daily.timezone ?? "UTC";
  return [...summaries].sort((a, b) => Date.parse(b.prepared_at) - Date.parse(a.prepared_at)).map((row) => ({
    analysisId: row.analysis_id, sourceId: row.source.source_id, headline: row.source.headline,
    effort: `${effortLabel(row.effort, account)} Effort`, state: STATE_LABEL[row.state],
    outcome: row.outcome ? OUTCOME_LABEL[row.outcome] : null,
    review: row.state === "recorded" ? reviewLabel(row.review_status) : null,
    credits: row.credits_charged === null ? null : `${plural(row.credits_charged, "credit", "credits")} charged`,
    prepared: inZone(row.prepared_at, zone), stateKey: row.state, outcomeKey: row.outcome,
  }));
}
