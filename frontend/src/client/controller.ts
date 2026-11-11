// The Client's actions over the contract's request helpers (src/contracts/user.ts). Each action makes at most one
// request and returns what the page should do with the reply; none retries, falls back or chains another write.
import { approvalFor, type Account, type Analysis, type Reply, type UserApi } from "../contracts/user.ts";
import { mayRun, type FlowEvent, type FlowState } from "./flow.ts";
import { noticeFor, sessionEndedBy, type Notice, type SessionReason } from "./refusals.ts";

export type Outcome<T> =
  | { kind: "ok"; status: number; data: T }
  | { kind: "session"; reason: SessionReason }
  | { kind: "notice"; notice: Notice };

/** A reply as the page handles it: the data, the end of the session (any 401), or a notice. */
export function outcomeOf<T>(reply: Reply<T>, quote: FlowState["quote"] = null, timeZone = "UTC"): Outcome<T> {
  if (reply.state === "ok") return { kind: "ok", status: reply.status, data: reply.data };
  const ended = sessionEndedBy(reply);
  if (ended) return { kind: "session", reason: ended };
  return { kind: "notice", notice: noticeFor(reply, quote, timeZone) };
}

export const NOT_APPROVED: Notice = {
  tone: "refused", code: null, title: "Not approved", efforts: null, facts: [], next: "none",
  detail: "Approve the quote shown for this analysis before running it. Nothing was sent.",
};

export interface RunReply { duplicate: boolean; analysis: Analysis; account: Account }

/** Run one analysis under the quote the person approved: one request, repeating the quote exactly, and only when the
 * page's state allows it (`mayRun`: approved, nothing in flight, no uncertain run outstanding). Otherwise nothing is
 * sent. */
export async function runApproved(api: UserApi, state: FlowState, timeZone = "UTC"): Promise<Outcome<RunReply>> {
  if (!mayRun(state)) return { kind: "notice", notice: NOT_APPROVED };
  return outcomeOf(await api.run(state.analysis.analysis_id, approvalFor(state.quote)), state.quote, timeZone);
}

/** What a run's outcome does to the page. A reply that is not confirmed (lost, unreadable or a server error) leaves it
 * unknown whether the run was sent, so it gates the page until the analysis is read again; a definite refusal
 * (nothing was reserved or sent) does not. */
export function runEvents(outcome: Outcome<RunReply>): FlowEvent | { type: "session"; reason: SessionReason } {
  if (outcome.kind === "ok") return { type: "ran", analysis: outcome.data.analysis, duplicate: outcome.data.duplicate };
  if (outcome.kind === "session") return { type: "session", reason: outcome.reason };
  return outcome.notice.tone === "unconfirmed" ? { type: "run-unconfirmed", notice: outcome.notice }
    : { type: "notice", notice: outcome.notice };
}
