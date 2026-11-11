// What a refused or unconfirmed reply means for the person using the Client. The server's `detail` is user-safe text
// (contract section 3) and is always shown; the fields some codes carry (credits, daily allowance, Effort options) are
// shown as the server stated them. A refusal never leads to an automatic retry, a cheaper Effort or another quote.
import type { ApiError, EffortOption, ErrorCode, Operation, Quote, Reply, Storage } from "../contracts/user.ts";
import { dayLabel, inUtc, inZone } from "./time.ts";

/** What the person can do next. Every step is a deliberate action; none happens on its own. */
export type NextStep = "new_quote" | "choose_effort" | "read_again" | "ask_admin" | "fix_form" | "paste" | "reload" |
  "none";

export interface Notice {
  tone: "refused" | "unconfirmed";
  code: ErrorCode | null;
  title: string;
  detail: string;
  facts: string[];
  next: NextStep;
  efforts: EffortOption[] | null;
  /** An import refusal that offers the paste step instead (the server's `paste_instead`). */
  pasteInstead?: boolean;
}

export type SessionReason = "not_signed_in" | "session_expired";

/** The counted operations as a sentence names them (docs/news-usage-contract.md section 3). */
export const OPERATION_NOUN: Record<Operation, string> = {
  search: "searches", import: "publication imports", source: "new sources", preparation: "newly prepared analyses",
};

const TITLES: Partial<Record<ErrorCode, [string, NextStep]>> = {
  unsupported_effort: ["This Effort is not offered now", "choose_effort"],
  no_credit_policy: ["Analyses cannot be quoted now", "ask_admin"],
  request_over_budget: ["This analysis is above the limit set for one request", "ask_admin"],
  no_daily_limit: ["No daily allowance is set for your account", "ask_admin"],
  sending_disabled: ["Analyses cannot run on this server now", "ask_admin"],
  accounts_unavailable: ["Accounts are not available on this server", "ask_admin"],
  already_attempted: ["This analysis has already been run", "read_again"],
  quote_expired: ["The quote has expired", "new_quote"],
  quote_superseded: ["The quote no longer applies", "new_quote"],
  quote_mismatch: ["The approval did not match the quote", "read_again"],
  insufficient_credits: ["Not enough credits", "ask_admin"],
  daily_limit_reached: ["Today's analyses are used", "none"],
  result_changed: ["The result changed since this page loaded", "read_again"],
  review_conflict: ["Another review version was saved since this page loaded", "read_again"],
  no_result: ["There is no recorded result to review", "read_again"],
  not_found: ["Not found", "none"],
  forbidden: ["This action is not available to your account", "none"],
  invalid_source: ["The source was not saved", "fix_form"],
  invalid_review: ["The review was not saved", "fix_form"],
  invalid_request: ["The request was refused as malformed", "read_again"],
  payload_too_large: ["The text is too long to send", "fix_form"],
  account_changed: ["This page was opened for another account", "reload"],
  account_binding_required: ["The request did not name your account", "reload"],
  no_usage_policy: ["Not available on this server yet", "ask_admin"],
  usage_limit_reached: ["Today's limit is used", "none"],
  storage_limit_reached: ["Your account cannot hold more", "ask_admin"],
  fetch_budget_reached: ["This server's publication requests for today are used", "paste"],
  request_key_reused: ["That search was already sent with other words", "none"],
  interests_changed: ["Your interests changed in another tab", "none"],
  rate_limited: ["Too many requests in a short time", "none"],
  too_many_requests: ["Requests are still in progress", "none"],
  entry_changed: ["The entry changed since the news was read", "read_again"],
  import_unsupported: ["This publication cannot be imported", "paste"],
  publication_unavailable: ["The publication could not be read", "paste"],
  publication_time_conflict: ["The publication's time disagrees with the feed", "none"],
  import_in_progress: ["This publication is being read now", "read_again"],
  publication_changed: ["The import changed since this page loaded", "read_again"],
  import_interrupted: ["This import stopped before it finished", "ask_admin"],
  publication_unreadable: ["The publication could not be read as text", "paste"],
  publication_too_long: ["The publication is too long to import", "paste"],
  story_changed: ["This story changed since the page was read", "read_again"],
  deeper_unavailable: ["A deeper analysis is not available for this story", "paste"],
  newsroom_unreadable: ["The news could not be read on this server", "ask_admin"],
  source_unmarked: ["This Go deeper source is not analysed again", "none"],
};

const STORAGE_TEXT = (storage: Storage): string => storage.measure === "sources"
  ? `Your account holds ${plural(storage.used, "source", "sources")} of the ${storage.limit} it may hold.`
  : `Your sources hold ${storage.used.toLocaleString("en-US")} of the ${storage.limit.toLocaleString("en-US")} bytes ` +
    `of text your account may hold; this one would add ${storage.adding.toLocaleString("en-US")}.`;

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/** A 401 that ends the session, or null. A 401 account_changed does not end this account's session: the browser is
 * signed in as another account, and the tab stops instead (identity.ts). */
export function sessionEndedBy(reply: Reply<unknown>): SessionReason | null {
  if (reply.state === "ok" || reply.status !== 401) return null;
  const code = reply.error?.code;
  if (code === "account_changed") return null;
  return code === "session_expired" ? "session_expired" : "not_signed_in";
}

function facts(error: ApiError, quote: Quote | null, timeZone: string): string[] {
  const lines: string[] = [];
  if (error.code === "insufficient_credits") {
    if (quote) lines.push(`This analysis needs ${plural(quote.credits, "credit", "credits")}.`);
    if (error.credits) {
      lines.push(`The server reports ${plural(error.credits.available, "credit", "credits")} available` +
        `${error.credits.held ? ` and ${error.credits.held} held by other analyses` : ""}.`);
    }
    lines.push("Credits are allocated by the administrator of this server.");
  }
  if (error.code === "daily_limit_reached") {
    const daily = error.daily;
    if (daily) {
      lines.push(daily.limit === null ? `${daily.used} used on ${dayLabel(daily.day)}.`
        : `${daily.used} of ${plural(daily.limit, "analysis", "analyses")} used on ${dayLabel(daily.day)}.`);
    }
    const resets = error.resets_at ?? daily?.resets_at;
    if (resets) lines.push(`The day resets ${inZone(resets, daily?.timezone ?? timeZone)} (${inUtc(resets)}).`);
    lines.push("Nothing was reserved or charged. Reading and reviewing saved results stay available.");
  }
  if (error.code === "unsupported_effort" && error.efforts) {
    lines.push(error.efforts.length === 0 ? "The server offers no Effort right now."
      : `The server now offers: ${error.efforts.map((option) => option.label).join(", ")}.`);
  }
  if (error.quota) {
    const quota = error.quota;
    lines.push(`${quota.used} of ${quota.limit} ${OPERATION_NOUN[quota.operation]} used on ${dayLabel(quota.day)}.`);
    lines.push(`The day resets ${inZone(quota.resets_at, quota.timezone)} (${inUtc(quota.resets_at)}).`);
  }
  if (error.storage) lines.push(STORAGE_TEXT(error.storage));
  if (error.code === "fetch_budget_reached" && error.resets_at) {
    lines.push(`The server's day resets ${inZone(error.resets_at, timeZone)} (${inUtc(error.resets_at)}).`);
  }
  if (error.retry_after_seconds !== undefined) {
    lines.push(`Wait at least ${plural(error.retry_after_seconds, "second", "seconds")} before trying again. ` +
      "Nothing is tried again by itself.");
  }
  if (error.requested === true) {
    lines.push("The publisher's page was requested for this, so it counts as one of today's publication imports.");
  } else if (error.requested === false) {
    lines.push("Nothing was requested from the publisher and nothing was counted.");
  }
  return lines;
}

/** The notice for a reply that is not "ok". `quote` is the quote the action used, when there was one. */
export function noticeFor(reply: Exclude<Reply<unknown>, { state: "ok" }>, quote: Quote | null = null,
                          timeZone = "UTC"): Notice {
  if (reply.state === "unconfirmed") {
    const said = /Nothing was retried/.test(reply.message);  // The contract's own message may already say it.
    return { tone: "unconfirmed", code: reply.error?.code ?? null, title: "No confirmed reply", efforts: null,
             detail: said ? reply.message : `${reply.message} Nothing was retried. Read this page again before acting.`,
             facts: [], next: "read_again" };
  }
  const error = reply.error;
  const [title, next] = TITLES[error.code] ?? ["The server refused this action", "none"];
  return { tone: "refused", code: error.code, title, detail: error.detail, facts: facts(error, quote, timeZone), next,
           efforts: error.code === "unsupported_effort" ? error.efforts ?? null : null,
           pasteInstead: error.paste_instead === true || error.code === "fetch_budget_reached" };
}

export const NEXT_TEXT: Record<NextStep, string | null> = {
  new_quote: "Ask for a new quote when you are ready; nothing was reserved.",
  choose_effort: "Choose one of the Effort options the server offers now. Nothing was prepared at the refused Effort.",
  read_again: "Read this page again to see the current state.",
  ask_admin: "Ask the administrator of this server.",
  fix_form: "Correct the form and save again.",
  paste: "You can open the official page and paste the publication's text into a new source yourself.",
  reload: "Reload this page.",
  none: null,
};
